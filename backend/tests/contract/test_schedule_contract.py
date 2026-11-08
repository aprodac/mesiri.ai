"""Contract tests for project start, the schedule and the BOQ import (ST-01, ST-03, ST-04, ST-05).

Requires a live Postgres reachable via Settings().postgres.dsn() -- run with `pytest -m integration`.
Fixtures mirror test_boq_api_contract.py.
"""

from __future__ import annotations

import base64
import datetime
import io
import json
import uuid

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from contract.company_day import company_today
from mesiri.bootstrap.settings import Settings
from mesiri.domains.identity.auth_service import create_access_token
from mesiri.http.app import create_app
from mesiri.infrastructure.postgres.dependency import get_db_conn

pytestmark = pytest.mark.integration
D = datetime.timedelta(days=1)


@pytest.fixture
async def test_engine():
    engine = create_async_engine(Settings().postgres.dsn(), echo=False)
    yield engine
    await engine.dispose()


@pytest.fixture
async def client(test_engine: AsyncEngine, monkeypatch):
    monkeypatch.setattr("mesiri.domains.shared.modules._database_for", lambda request: None)
    app = create_app()

    async def override_get_db_conn():
        async with test_engine.begin() as conn:
            yield conn

    app.dependency_overrides[get_db_conn] = override_get_db_conn
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
        yield c


async def _exec(engine, sql: str, **params):
    async with engine.begin() as conn:
        return await conn.execute(sa.text(sql), params)


async def _org(engine) -> uuid.UUID:
    org_id = uuid.uuid4()
    await _exec(engine, "INSERT INTO organizations (id, name, deployment_type, db_route, status, created_at, updated_at) "
                        "VALUES (:id, 'Schedule Org', 'local', 'default', 'active', now(), now())", id=org_id)
    return org_id


async def _user(engine, org_id, role: str, policy: str = '{"mode": "all_projects", "projects": []}') -> tuple:
    user_id = uuid.uuid4()
    await _exec(engine, "INSERT INTO users (id, organization_id, email, hashed_password, full_name, role, status, "
                        "access_policy, whatsapp_number, created_at, updated_at) VALUES (:id, :org, :email, 'hash', "
                        "'T', :role, 'active', CAST(:policy AS jsonb), :wa, now(), now())",
                id=user_id, org=org_id, email=f"{uuid.uuid4().hex[:8]}@example.com", role=role, policy=policy,
                wa=f"+9190{uuid.uuid4().int % 10**8:08d}")
    return user_id, create_access_token(data={"sub": str(user_id), "org": str(org_id), "role": role})


async def _project(engine, org_id, name="Villa Kakkanad") -> tuple[uuid.UUID, uuid.UUID]:
    project_id, site_id = uuid.uuid4(), uuid.uuid4()
    await _exec(engine, "INSERT INTO projects (id, organization_id, name, created_at, updated_at) "
                        "VALUES (:id, :org, :name, now(), now())", id=project_id, org=org_id, name=name)
    await _exec(engine, "INSERT INTO sites (id, project_id, organization_id, name, status, created_at, updated_at) "
                        "VALUES (:id, :p, :org, 'Main building', 'active', now(), now())",
                id=site_id, p=project_id, org=org_id)
    return project_id, site_id


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def ctx(test_engine):
    org = await _org(test_engine)
    project, site = await _project(test_engine, org)
    admin_id, admin = await _user(test_engine, org, "admin")
    return {"org": org, "project": project, "site": site, "admin": admin, "admin_id": admin_id}


async def _section(client, ctx, name: str) -> str:
    r = await client.post(f"/projects/{ctx['project']}/boq/sections", json={"name": name}, headers=_h(ctx["admin"]))
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _line(client, ctx, section_id: str, work: str, qty: str, unit="cum", rate=None) -> str:
    r = await client.post(f"/projects/{ctx['project']}/boq/sections/{section_id}/lines",
                          json={"work": work, "unit": unit, "planned_quantity": qty, "client_rate": rate},
                          headers=_h(ctx["admin"]))
    assert r.status_code == 201, r.text
    lines = [ln for s in r.json()["sections"] for ln in s["lines"]] if "sections" in r.json() else None
    if lines is not None:
        return next(ln["id"] for ln in lines if ln["work"] == work)
    return r.json()["id"]


async def _patch(client, ctx, aid: str, token=None, **body):
    return await client.patch(f"/projects/{ctx['project']}/schedule/activities/{aid}", json=body,
                              headers=_h(token or ctx["admin"]))


async def _schedule(client, ctx, token=None) -> dict:
    r = await client.get(f"/projects/{ctx['project']}/schedule", headers=_h(token or ctx["admin"]))
    assert r.status_code == 200, r.text
    return r.json()


def _act(sched: dict, aid: str) -> dict:
    return next(a for a in sched["activities"] if a["id"] == aid)


async def _measure(engine, ctx, line_id: str, qty: str, day: datetime.date, kind="ACHIEVED"):
    """A work update from site counted on a BOQ line (what WhatsApp saves)."""
    act_id = uuid.uuid4()
    await _exec(engine, "INSERT INTO activities (id, organization_id, project_id, site_id, activity_date, status) "
                        "VALUES (:id, :org, :p, :s, :d, 'COMPLETED')",
                id=act_id, org=ctx["org"], p=ctx["project"], s=ctx["site"], d=day)
    await _exec(engine, "INSERT INTO activity_quantities (id, activity_id, unit_id, quantity, measurement_type, "
                        "planned_item_id) VALUES (gen_random_uuid(), :a, (SELECT unit_id FROM "
                        "work_package_planned_items WHERE id = :l), :q, CAST(:k AS activity_measurement_type), :l)",
                a=act_id, l=uuid.UUID(line_id), q=qty, k=kind)


# -- the schedule ----------------------------------------------------------------------------------------------------

async def test_dates_links_and_push_after(client, ctx):
    today = company_today()
    a = await _section(client, ctx, "Excavation")
    b = await _section(client, ctx, "Footings")
    c = await _section(client, ctx, "Slab")
    assert (await _patch(client, ctx, a, start=str(today + 10 * D), end=str(today + 14 * D))).status_code == 200
    assert (await _patch(client, ctx, b, start=str(today + 15 * D), end=str(today + 21 * D),
                         after=[{"id": a}])).status_code == 200
    assert (await _patch(client, ctx, c, start=str(today + 22 * D), end=str(today + 29 * D),
                         after=[{"id": b}])).status_code == 200

    # Preview: Excavation takes 3 more days; Footings and Slab would move 3 days; nothing is saved.
    r = await _patch(client, ctx, a, end=str(today + 17 * D), preview=True)
    body = r.json()
    assert r.status_code == 200 and body["saved"] is False
    assert {m["name"]: m["days"] for m in body["moved"]} == {"Footings": 3, "Slab": 3}
    assert body["finish_moves"] == 3
    assert _act(await _schedule(client, ctx), b)["start"] == str(today + 15 * D)

    # Save it: they move, keeping their length.
    r = await _patch(client, ctx, a, end=str(today + 17 * D))
    assert r.json()["saved"] is True
    sched = r.json()["schedule"]
    assert (_act(sched, b)["start"], _act(sched, b)["end"]) == (str(today + 18 * D), str(today + 24 * D))
    assert _act(sched, c)["start"] == str(today + 25 * D)
    assert {_act(sched, x)["critical"] for x in (a, b, c)} == {True}

    # Without push, only the activity itself moves and the broken link is reported.
    r = await _patch(client, ctx, a, end=str(today + 20 * D), push=False)
    assert r.json()["moved"] == []
    assert r.json()["schedule"]["summary"]["conflicts"] == 1


async def test_cycle_is_refused_and_milestone_is_one_day(client, ctx):
    today = company_today()
    a = await _section(client, ctx, "A")
    b = await _section(client, ctx, "B")
    await _patch(client, ctx, a, start=str(today), end=str(today + 2 * D))
    await _patch(client, ctx, b, start=str(today + 3 * D), end=str(today + 4 * D), after=[{"id": a}])
    r = await _patch(client, ctx, a, after=[{"id": b}])
    assert r.status_code == 409 and "circle" in r.json()["detail"]

    r = await client.post(f"/projects/{ctx['project']}/schedule/activities",
                          json={"name": "Slab cast", "start": str(today + 5 * D), "milestone": True,
                                "after": [{"id": b}]}, headers=_h(ctx["admin"]))
    assert r.status_code == 201, r.text
    m = _act(r.json()["schedule"], r.json()["focus"])
    assert m["milestone"] and m["start"] == m["end"] == str(today + 5 * D) and m["duration"] == 0


async def test_progress_comes_from_site_reports_and_late_work_pushes_what_follows(client, test_engine, ctx):
    today = company_today()
    exc = await _section(client, ctx, "Excavation")
    ftg = await _section(client, ctx, "Footings")
    line = await _line(client, ctx, exc, "Excavation in soil", "100")
    await _patch(client, ctx, exc, start=str(today - 7 * D), end=str(today - 3 * D))
    await _patch(client, ctx, ftg, start=str(today - 2 * D), end=str(today + 4 * D), after=[{"id": exc}])
    await _measure(test_engine, ctx, line, "30", today - 7 * D)
    await _measure(test_engine, ctx, line, "30", today - 5 * D)

    sched = await _schedule(client, ctx)
    e, f = _act(sched, exc), _act(sched, ftg)
    assert e["progress"] == 60 and e["state"] == "late" and e["days_late"] == 3
    assert e["actual_start"] == str(today - 7 * D) and e["updates"] == 2
    assert e["lines"][0]["done_quantity"] == "60.000" or e["lines"][0]["done_quantity"].startswith("60")
    assert f["pushed_days"] > 0
    assert sched["summary"]["slip_days"] > 0 and sched["summary"]["counts"]["late"] == 1

    # "Total so far is 100" replaces the daily figures: it is done.
    await _measure(test_engine, ctx, line, "100", today, kind="CUMULATIVE")
    assert _act(await _schedule(client, ctx), exc)["state"] == "done"


async def test_mark_done_and_quick_plan(client, ctx):
    today = company_today()
    ids = [await _section(client, ctx, n) for n in ("Mobilisation", "Excavation", "Handover")]
    r = await client.post(f"/projects/{ctx['project']}/schedule/sequence",
                          json={"start": str(today), "items": [{"id": ids[0], "days": 3}, {"id": ids[1], "days": 5},
                                                               {"id": ids[2], "days": 0}]},
                          headers=_h(ctx["admin"]))
    assert r.status_code == 200, r.text
    sched = r.json()["schedule"]
    assert [(_act(sched, i)["start"], _act(sched, i)["end"]) for i in ids] == [
        (str(today), str(today + 2 * D)), (str(today + 3 * D), str(today + 7 * D)),
        (str(today + 8 * D), str(today + 8 * D))]
    assert _act(sched, ids[2])["milestone"] and len(sched["links"]) == 2

    r = await _patch(client, ctx, ids[0], done=True)
    assert _act(r.json()["schedule"], ids[0])["state"] == "done"


async def test_delete_only_an_activity_with_no_boq_lines(client, ctx):
    sec = await _section(client, ctx, "Plastering")
    await _line(client, ctx, sec, "Internal plaster", "500", unit="sqft")
    r = await client.delete(f"/projects/{ctx['project']}/schedule/activities/{sec}", headers=_h(ctx["admin"]))
    assert r.status_code == 409 and "BOQ" in r.json()["detail"]
    r = await client.post(f"/projects/{ctx['project']}/schedule/activities",
                          json={"name": "Curing", "start": str(company_today()), "end": str(company_today() + 6 * D)},
                          headers=_h(ctx["admin"]))
    new_id = r.json()["focus"]
    r = await client.delete(f"/projects/{ctx['project']}/schedule/activities/{new_id}", headers=_h(ctx["admin"]))
    assert r.status_code == 204


async def test_engineer_reads_but_cannot_change_and_other_projects_are_closed(client, test_engine, ctx):
    sec = await _section(client, ctx, "Brickwork")
    _, engineer = await _user(test_engine, ctx["org"], "site_engineer")
    sched = await _schedule(client, ctx, token=engineer)
    assert sched["can_edit"] is False and _act(sched, sec)["name"] == "Brickwork"
    assert "client_rate" not in str(sched)
    r = await _patch(client, ctx, sec, token=engineer, start=str(company_today()), end=str(company_today()))
    assert r.status_code == 403

    other, _ = await _project(test_engine, ctx["org"], name="Other job")
    policy = json.dumps({"mode": "custom_projects", "projects": [{"projectId": str(other),
                                                                  "siteAccess": {"mode": "all_sites"}}]})
    _, limited = await _user(test_engine, ctx["org"], "site_engineer", policy=policy)
    r = await client.get(f"/projects/{ctx['project']}/schedule", headers=_h(limited))
    assert r.status_code == 403

    stranger_org = await _org(test_engine)
    _, stranger = await _user(test_engine, stranger_org, "admin")
    r = await client.get(f"/projects/{ctx['project']}/schedule", headers=_h(stranger))
    assert r.status_code in (403, 404)


# -- project start -------------------------------------------------------------------------------------------------

async def test_project_start_checklist_and_stage(client, ctx):
    r = await client.get(f"/projects/{ctx['project']}/start", headers=_h(ctx["admin"]))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["project"]["stage"] == "running"
    assert body["next"] == "dates" and body["ready"] is False
    steps = {s["key"]: s for s in body["steps"]}
    assert steps["sites"]["done"] is True and steps["boq"]["done"] is False

    r = await client.patch(f"/projects/{ctx['project']}/start",
                           json={"stage": "won", "start_date": "2026-12-01", "planned_finish": "2027-06-30"},
                           headers=_h(ctx["admin"]))
    assert r.status_code == 200 and r.json()["project"]["stage_label"] == "Won"
    assert r.json()["next"] == "boq"

    bad = await client.patch(f"/projects/{ctx['project']}/start", json={"stage": "dreaming"}, headers=_h(ctx["admin"]))
    assert bad.status_code == 422
    backwards = await client.patch(f"/projects/{ctx['project']}/start", json={"planned_finish": "2026-01-01"},
                                   headers=_h(ctx["admin"]))
    assert backwards.status_code == 422

    r = await client.get("/lifecycle/projects", headers=_h(ctx["admin"]))
    mine = next(p for p in r.json() if p["id"] == str(ctx["project"]))
    assert mine["stage"] == "won" and mine["planned_finish"] == "2027-06-30"


# -- BOQ import ------------------------------------------------------------------------------------------------------

def _xlsx(rows: list[list]) -> str:
    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    sheet.title = "Estimate"
    for row in rows:
        sheet.append(row)
    out = io.BytesIO()
    book.save(out)
    return base64.b64encode(out.getvalue()).decode()


async def test_template_previews_then_imports_with_dates_and_links_and_is_safe_to_rerun(client, ctx):
    r = await client.get(f"/projects/{ctx['project']}/boq/import/template", headers=_h(ctx["admin"]))
    assert r.status_code == 200
    file = base64.b64encode(r.content).decode()
    url = f"/projects/{ctx['project']}/boq/import"

    preview = await client.post(f"{url}/preview", json={"file_base64": file}, headers=_h(ctx["admin"]))
    assert preview.status_code == 200, preview.text
    p = preview.json()
    assert p["saved"] is False and p["lines_added"] == 6 and p["sections_added"] == 4 and p["problems"] == 0
    boq = await client.get(f"/projects/{ctx['project']}/boq", headers=_h(ctx["admin"]))
    assert boq.json()["sections"] == []

    done = (await client.post(url, json={"file_base64": file}, headers=_h(ctx["admin"]))).json()
    assert done["saved"] is True and done["lines_added"] == 6 and done["dated_sections"] == 4 and done["links"] == 3
    assert done["contract_value"] == p["contract_value"]
    sched = await _schedule(client, ctx)
    found = {a["name"]: a for a in sched["activities"]}
    assert found["Foundation"]["start"] == "2026-12-09" and found["Foundation"]["after"]
    again = (await client.post(url, json={"file_base64": file}, headers=_h(ctx["admin"]))).json()
    assert again["lines_added"] == 0 and again["lines_kept"] == 6 and again["sections_added"] == 0


async def test_a_real_estimate_sheet_with_heading_rows(client, ctx):
    file = _xlsx([
        ["ABC Builders - Estimate for Villa"],
        [],
        ["Sl No", "Description of work", "Qty", "Unit", "Rate", "Amount"],
        ["A", "EARTHWORK", None, None, None, None],
        [1, "Excavation for foundation", 120, "cum", "350", 42000],
        [2, "Anti-termite treatment", 900, "sqft", 12, 10800],
        ["B", "CONCRETE", None, None, None, None],
        [3, "RCC M20 in columns", "18.5", "m3", "9,800", 181300],
        [4, "Something odd", 3, "furlongs", 10, 30],
        [None, "Sub total", None, None, None, 234100],
    ])
    r = await client.post(f"/projects/{ctx['project']}/boq/import", json={"file_base64": file},
                          headers=_h(ctx["admin"]))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sections_added"] == 2 and body["lines_added"] == 3 and body["problems"] == 1
    assert "Amount" in body["ignored_columns"]
    problem = next(x for x in body["rows"] if x["result"] == "problem")
    assert "furlongs" in problem["message"]
    boq = (await client.get(f"/projects/{ctx['project']}/boq", headers=_h(ctx["admin"]))).json()
    assert [s["name"] for s in boq["sections"]] == ["A EARTHWORK", "B CONCRETE"]
    rcc = boq["sections"][1]["lines"][0]
    assert rcc["client_rate"] == "9800.00" and rcc["boq_code"] == "3"


async def test_import_refuses_what_is_not_a_boq_and_engineers(client, test_engine, ctx):
    url = f"/projects/{ctx['project']}/boq/import/preview"
    r = await client.post(url, json={"file_base64": base64.b64encode(b"not excel").decode()}, headers=_h(ctx["admin"]))
    assert r.status_code == 422 and "Excel" in r.json()["detail"]
    r = await client.post(url, json={"file_base64": _xlsx([["Name", "Phone"], ["Ravi", "98"]])},
                          headers=_h(ctx["admin"]))
    assert r.status_code == 422 and "No BOQ" in r.json()["detail"]
    _, engineer = await _user(test_engine, ctx["org"], "site_engineer")
    r = await client.post(url, json={"file_base64": _xlsx([["Work", "Unit", "Qty"], ["x", "cum", 1]])},
                          headers=_h(engineer))
    assert r.status_code == 403


# -- WhatsApp notes ----------------------------------------------------------------------------------------------------

async def test_late_work_queues_one_delay_note_a_day_to_the_people_who_run_the_project(client, test_engine, ctx):
    from mesiri.domains.schedule.reminders import queue_schedule_reminders

    today = company_today()
    exc = await _section(client, ctx, "Excavation")
    ftg = await _section(client, ctx, "Footings")
    await _patch(client, ctx, exc, start=str(today - 7 * D), end=str(today - 2 * D))
    await _patch(client, ctx, ftg, start=str(today - 1 * D), end=str(today + 5 * D), after=[{"id": exc}])
    _, engineer = await _user(test_engine, ctx["org"], "site_engineer")

    async with test_engine.begin() as conn:
        first = await queue_schedule_reminders(conn, ctx["org"], today)
        again = await queue_schedule_reminders(conn, ctx["org"], today)
    assert again == 0
    rows = (await _exec(test_engine, "SELECT rule_key, recipient_user_id, payload FROM notifications "
                                     "WHERE organization_id = :org", org=ctx["org"])).mappings().all()
    delay = [r for r in rows if r["rule_key"] == "schedule_delays"]
    assert first >= 1 and [r["recipient_user_id"] for r in delay] == [ctx["admin_id"]]  # not the engineer
    note = delay[0]["payload"]["message"]
    assert "*Excavation* is 2 days late" in note and "pushes Footings" in note


async def test_nothing_is_sent_for_a_schedule_on_time_or_a_tender(client, test_engine, ctx):
    from mesiri.domains.schedule.reminders import queue_schedule_reminders

    today = company_today()
    a = await _section(client, ctx, "Mobilisation")
    await _patch(client, ctx, a, start=str(today + 3 * D), end=str(today + 6 * D))
    async with test_engine.begin() as conn:
        assert await queue_schedule_reminders(conn, ctx["org"], today) == (1 if today.weekday() == 0 else 0)
    await _patch(client, ctx, a, start=str(today - 9 * D), end=str(today - 6 * D))
    await client.patch(f"/projects/{ctx['project']}/start", json={"stage": "tender"}, headers=_h(ctx["admin"]))
    async with test_engine.begin() as conn:
        assert await queue_schedule_reminders(conn, ctx["org"], today + D) == 0
