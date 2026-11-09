"""Contract tests for the period report (PRC-19): GET /reports/period, /pdf, /xlsx on Postgres.

Requires a live Postgres reachable via Settings().postgres.dsn() -- run with `pytest -m integration`.

The rule under test: every figure is the owning module's own, so the report agrees with the module's page (the
schedule's progress, cost control's man-days and spending); a site engineer never sees rupees; another company's
user sees nothing; the PDF and the Excel are the same report.
"""

from __future__ import annotations

import datetime
import io
import uuid
from decimal import Decimal

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from mesiri.application.dpr.project_day import company_today
from mesiri.bootstrap.settings import Settings
from mesiri.domains.identity.auth_service import create_access_token
from mesiri.http.app import create_app
from mesiri.infrastructure.postgres.dependency import get_db_conn

pytestmark = pytest.mark.integration

_ALL = '{"mode": "all_projects", "projects": []}'
D = datetime.timedelta(days=1)


@pytest.fixture
async def test_engine():
    engine = create_async_engine(Settings().postgres.dsn(), echo=False)
    yield engine
    await engine.dispose()


@pytest.fixture
async def client(test_engine: AsyncEngine, monkeypatch):
    from mesiri.infrastructure.objectstorage.dependency import get_object_storage
    from mesiri.infrastructure.objectstorage.fake import FakeObjectStorage

    monkeypatch.setattr("mesiri.domains.shared.modules._database_for", lambda request: None)
    app = create_app()
    storage = FakeObjectStorage()
    app.dependency_overrides[get_object_storage] = lambda: storage

    async def override_get_db_conn():
        async with test_engine.begin() as conn:
            yield conn

    app.dependency_overrides[get_db_conn] = override_get_db_conn
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
        c.storage = storage  # the PDFs a send stored
        yield c


async def _run(engine, sql: str, **params):
    async with engine.begin() as conn:
        return await conn.execute(sa.text(sql), params)


async def _org(engine, name: str) -> uuid.UUID:
    org = uuid.uuid4()
    await _run(engine, "INSERT INTO organizations (id, name, deployment_type, db_route, status, created_at, updated_at) "
               "VALUES (:id, :n, 'local', 'default', 'active', now(), now())", id=org, n=name)
    return org


async def _user(engine, org, role: str, name: str = "T", whatsapp: bool = True) -> tuple[uuid.UUID, str]:
    user_id = uuid.uuid4()
    await _run(engine,
               "INSERT INTO users (id, organization_id, email, hashed_password, full_name, role, status, access_policy, "
               "whatsapp_number, created_at, updated_at) VALUES (:id, :org, :e, 'hash', :name, :role, 'active', "
               "CAST(:p AS jsonb), :wa, now(), now())", id=user_id, org=org, e=f"{uuid.uuid4().hex[:8]}@example.com",
               role=role, p=_ALL, name=name, wa=f"+9190{uuid.uuid4().int % 10**8:08d}" if whatsapp else None)
    return user_id, create_access_token(data={"sub": str(user_id), "org": str(org), "role": role})


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def ctx(test_engine):
    org = await _org(test_engine, "Report Org")
    project, site = uuid.uuid4(), uuid.uuid4()
    admin_id, admin = await _user(test_engine, org, "admin", "Ilan Usman")
    engineer_id, engineer = await _user(test_engine, org, "site_engineer", "Sajan K")
    await _run(test_engine, "INSERT INTO projects (id, organization_id, name, client, created_at, updated_at) "
               "VALUES (:id, :org, 'Villa Kakkanad', 'Thomas Mathew', now() - interval '40 days', now())",
               id=project, org=org)
    await _run(test_engine, "INSERT INTO sites (id, project_id, organization_id, name, status, created_at, updated_at) "
               "VALUES (:id, :p, :org, 'Main', 'active', now(), now())", id=site, p=project, org=org)
    cat = uuid.uuid4()
    await _run(test_engine, "INSERT INTO expense_categories (id, organization_id, name, code, cost_centre, created_by) "
               "VALUES (:id, :org, 'Materials', 'MAT', 'materials', :by)", id=cat, org=org, by=admin_id)
    async with test_engine.begin() as conn:
        today = await company_today(conn, org)
    other = await _org(test_engine, "Other Org")
    _, stranger = await _user(test_engine, other, "admin")
    yield {"org": org, "other": other, "project": project, "site": site, "admin": admin, "admin_id": admin_id,
           "engineer": engineer, "engineer_id": engineer_id, "stranger": stranger, "cat": cat, "today": today}
    async with test_engine.begin() as conn:
        for sql in (
            "DELETE FROM report_snapshots WHERE organization_id = :org",
            "DELETE FROM notifications WHERE organization_id = :org",
            "DELETE FROM automations WHERE organization_id = :org",
            "DELETE FROM site_issues WHERE organization_id = :org",
            "DELETE FROM activity_quantities WHERE activity_id IN (SELECT id FROM activities WHERE organization_id = :org)",
            "DELETE FROM activities WHERE organization_id = :org",
            "DELETE FROM expenses WHERE organization_id = :org",
            "DELETE FROM expense_categories WHERE organization_id = :org",
            "DELETE FROM labour_attendance_reports WHERE organization_id = :org",
            "DELETE FROM work_packages WHERE organization_id = :org",
            "DELETE FROM site_members WHERE site_id IN (SELECT id FROM sites WHERE organization_id = :org)",
            "DELETE FROM project_members WHERE project_id IN (SELECT id FROM projects WHERE organization_id = :org)",
        ):
            await conn.execute(sa.text(sql), {"org": org})
        for o in (org, other):
            await conn.execute(sa.text("DELETE FROM organizations WHERE id = :org"), {"org": o})


async def _seed(client, engine, ctx) -> dict:
    """A BOQ section with two priced lines on the schedule, a week of attendance and work, an expense, an issue."""
    h, p, today = _h(ctx["admin"]), ctx["project"], ctx["today"]
    sec = (await client.post(f"/projects/{p}/boq/sections", json={"name": "Finishes"}, headers=h)).json()["id"]
    url = f"/projects/{p}/boq/sections/{sec}/lines"
    for body in ({"work": "Internal plastering", "unit": "sqft", "planned_quantity": "10000", "client_rate": "60",
                  "labour_rate": "14"},
                 {"work": "Brickwork", "unit": "cum", "planned_quantity": "100", "client_rate": "6000",
                  "labour_rate": "2000"}):
        r = await client.post(url, headers=h, json=body)
        assert r.status_code == 201, r.text
    boq = (await client.get(f"/projects/{p}/boq", headers=h)).json()
    lines = {ln["work"]: ln["id"] for s in boq["sections"] for ln in s["lines"]}
    r = await client.patch(f"/projects/{p}/schedule/activities/{sec}", headers=h,
                           json={"start": str(today - 20 * D), "end": str(today + 19 * D)})
    assert r.status_code == 200, r.text
    for days_ago in (1, 2, 3):
        report = uuid.uuid4()
        await _run(engine, "INSERT INTO labour_attendance_reports (id, organization_id, project_id, site_id, "
                   "occurred_date, recorded_via, created_at, created_by) VALUES (:id, :org, :p, :s, :d, "
                   "'whatsapp_text', clock_timestamp(), :u)", id=report, org=ctx["org"], p=p, s=ctx["site"],
                   d=today - days_ago * D, u=ctx["admin_id"])
        for trade, n, wage in (("mason", 4, "1100"), ("helper", 2, "800")):
            await _run(engine, "INSERT INTO labour_attendance_lines (id, report_id, trade, headcount, daily_wage, "
                       "created_at) VALUES (:id, :r, :t, :n, :w, now())", id=uuid.uuid4(), r=report, t=trade, n=n,
                       w=Decimal(wage))
        act = uuid.uuid4()
        await _run(engine, "INSERT INTO activities (id, organization_id, project_id, site_id, work_type, activity_date, "
                   "source) VALUES (:id, :org, :p, :s, 'Plastering', :d, 'dashboard')", id=act, org=ctx["org"], p=p,
                   s=ctx["site"], d=today - days_ago * D)
        await _run(engine, "INSERT INTO activity_quantities (id, activity_id, unit_id, quantity, planned_item_id) "
                   "VALUES (:id, :a, (SELECT unit_id FROM work_package_planned_items WHERE id = :l), :q, :l)",
                   id=uuid.uuid4(), a=act, q=Decimal("500"), l=uuid.UUID(lines["Internal plastering"]))
    await _run(engine, "INSERT INTO expenses (id, organization_id, project_id, site_id, amount, occurred_date, created_by, "
               "category_id, workflow_status) VALUES (:id, :org, :p, :s, 42000, :d, :by, :c, 'confirmed')",
               id=uuid.uuid4(), org=ctx["org"], p=p, s=ctx["site"], d=today - 2 * D, by=ctx["admin_id"], c=ctx["cat"])
    await _run(engine, "INSERT INTO site_issues (id, organization_id, project_id, site_id, issue_type, severity, "
               "narrative, occurred_at, status, created_at, updated_at) VALUES (:id, :org, :p, :s, 'MATERIAL_SHORTAGE', "
               "'HIGH', 'Cement not delivered', now() - interval '2 days', 'OPEN', now(), now())",
               id=uuid.uuid4(), org=ctx["org"], p=p, s=ctx["site"])
    return {"section": sec, "lines": lines}


def _q(ctx, extra: str = "") -> str:
    today = ctx["today"]
    return (f"project_id={ctx['project']}&period=custom&date_from={today - 6 * D}&date_to={today}" + extra)


async def test_the_report_agrees_with_the_module_pages(client, ctx, test_engine):
    await _seed(client, test_engine, ctx)
    h, p, today = _h(ctx["admin"]), ctx["project"], ctx["today"]
    r = await client.get(f"/reports/period?{_q(ctx)}", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["unavailable"] == []
    s = body["sections"]
    assert {"work", "schedule", "labour", "money", "issues", "completeness"} <= set(s)

    # Work: 1,500 sq ft of 10,000 at ₹60 against a ₹1.2 L + ₹6 L BOQ: 1500*60 / 1,200,000 = 7.5% of the job.
    assert s["work"]["done_pct"] == "7.5"
    sched = (await client.get(f"/projects/{p}/schedule", headers=h)).json()
    assert s["work"]["progress_to_date"] == sched["summary"]["progress"]
    assert s["work"]["plan_pct"] is not None and s["work"]["rows"][0]["done_in_period"][0]["quantity"] == "1500"

    # Labour: 3 days x (4 masons + 2 helpers) = 18 man-days; wages 3 x (4,400 + 1,600) = 18,000. Same as cost control.
    assert s["labour"]["man_days"] == "18" and s["labour"]["wages"] == "18000.00"
    variance = (await client.get(f"/cost/projects/{p}/variance?date_from={today - 6 * D}&date_to={today}",
                                 headers=h)).json()
    assert Decimal(variance["labour"]["man_days"]) == Decimal(s["labour"]["man_days"])
    assert {t["label"]: t["man_days"] for t in s["labour"]["by_trade"]} == {"Mason": "12", "Helper": "6"}

    # Money: the period's full cost, the cost module's own centres.
    centres = (await client.get(f"/cost/centres?project_id={p}&date_from={today - 6 * D}&date_to={today}",
                                headers=h)).json()
    assert Decimal(s["money"]["spent"]) == Decimal(centres["total"])
    assert Decimal(s["money"]["spent"]) >= Decimal("42000")
    assert s["money"]["owed"] == "0.00"

    # Issues and "Needs you": the open HIGH issue is serious and is in the list.
    assert s["issues"]["open"] == 1 and s["issues"]["serious_open"] == 1 and s["issues"]["status"] == "bad"
    assert any(n["kind"] == "issue" for n in body["needs_you"])
    # Completeness: no site report was confirmed, so every day is missing, and that is said, never "good".
    assert s["completeness"]["status"] != "good" and len(s["completeness"]["days_missing"]) == 7
    assert body["headline"]["lead"] and body["kpis"][0]["key"] == "work"
    assert body["period"]["days"] == 7 and body["previous"]["to"] == str(today - 7 * D)


async def test_a_site_engineer_never_sees_rupees(client, ctx, test_engine):
    await _seed(client, test_engine, ctx)
    r = await client.get(f"/reports/period?{_q(ctx)}", headers=_h(ctx["engineer"]))
    assert r.status_code == 200, r.text
    body = r.json()
    assert "money" not in body["sections"] and body["sees_money"] is False
    assert "wages" not in body["sections"]["labour"]
    assert all("wages" not in t for t in body["sections"]["labour"]["by_trade"])
    assert "₹" not in str(body)


async def test_another_company_sees_nothing(client, ctx, test_engine):
    r = await client.get(f"/reports/period?{_q(ctx)}", headers=_h(ctx["stranger"]))
    assert r.status_code in (403, 404)


async def test_a_bad_period_is_said_in_words(client, ctx):
    h, today = _h(ctx["admin"]), ctx["today"]
    r = await client.get(f"/reports/period?project_id={ctx['project']}&period=custom&date_from={today}", headers=h)
    assert r.status_code == 422 and "both dates" in r.json()["detail"]
    r = await client.get(f"/reports/period?project_id={ctx['project']}&period=week&date={today + 30 * D}", headers=h)
    assert r.status_code == 422 and "not started" in r.json()["detail"]


async def test_week_and_month_default_to_the_last_finished_one(client, ctx):
    h, today = _h(ctx["admin"]), ctx["today"]
    week = (await client.get(f"/reports/period?project_id={ctx['project']}&period=week", headers=h)).json()["period"]
    start = datetime.date.fromisoformat(week["from"])
    assert start.weekday() == 0 and datetime.date.fromisoformat(week["to"]) < today
    month = (await client.get(f"/reports/period?project_id={ctx['project']}&period=month", headers=h)).json()["period"]
    assert month["from"].endswith("-01") and datetime.date.fromisoformat(month["to"]) < today


async def test_pdf_and_excel_are_the_same_report(client, ctx, test_engine):
    from openpyxl import load_workbook

    await _seed(client, test_engine, ctx)
    h = _h(ctx["admin"])
    pdf = await client.get(f"/reports/period/pdf?{_q(ctx)}", headers=h)
    assert pdf.status_code == 200, pdf.text
    assert pdf.headers["content-type"] == "application/pdf" and pdf.content.startswith(b"%PDF")
    assert "mesiri-villa-kakkanad-report-" in pdf.headers["content-disposition"]
    xlsx = await client.get(f"/reports/period/xlsx?{_q(ctx)}", headers=h)
    assert xlsx.status_code == 200, xlsx.text
    book = load_workbook(io.BytesIO(xlsx.content))
    labour = book["Labour"]
    days = [row for row in labour.iter_rows(min_row=2, values_only=True) if row[0] and str(row[0])[:2] == "20"]
    assert sum(Decimal(str(r[1])) for r in days) == Decimal(18)



# -- R2: the owner's brief, sending, sent copies, schedules (RPT-01, PRC-20) -----------------------------------------

async def _second_project(engine, ctx, name: str = "Aluva Warehouse") -> uuid.UUID:
    pid = uuid.uuid4()
    await _run(engine, "INSERT INTO projects (id, organization_id, name, created_at, updated_at) "
               "VALUES (:id, :org, :n, now(), now())", id=pid, org=ctx["org"], n=name)
    return pid


def _week(ctx) -> dict:
    today = ctx["today"]
    return {"period": "custom", "date_from": str(today - 6 * D), "date_to": str(today)}


async def test_the_brief_lists_every_running_project_worst_first(client, ctx, test_engine):
    await _seed(client, test_engine, ctx)
    await _second_project(test_engine, ctx)
    q = f"period=custom&date_from={ctx['today'] - 6 * D}&date_to={ctx['today']}"
    r = await client.get(f"/reports/portfolio?{q}", headers=_h(ctx["admin"]))
    assert r.status_code == 200, r.text
    brief = r.json()
    names = [p["name"] for p in brief["projects"]]
    assert names == ["Villa Kakkanad", "Aluva Warehouse"]  # the one with the late activity and the issue first
    assert brief["projects"][0]["status"] == "bad" and brief["projects"][0]["serious_issues"] == 1
    assert brief["headline"]["lead"].startswith("2 projects, 1 needs you")
    assert brief["totals"]["man_days"] == "18"
    eng = (await client.get(f"/reports/portfolio?{q}", headers=_h(ctx["engineer"]))).json()
    assert eng["sees_money"] is False and "₹" not in str(eng)
    pdf = await client.get(f"/reports/portfolio/pdf?{q}", headers=_h(ctx["admin"]))
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    xlsx = await client.get(f"/reports/portfolio/xlsx?{q}", headers=_h(ctx["admin"]))
    assert xlsx.status_code == 200 and xlsx.content[:2] == b"PK"


async def test_a_send_freezes_a_copy_per_person_as_they_may_see_it(client, ctx, test_engine):
    await _seed(client, test_engine, ctx)
    nowa_id, _ = await _user(test_engine, ctx["org"], "finance", "Divya", whatsapp=False)
    outsider = uuid.uuid4()
    body = {"scope": "project", "project_id": str(ctx["project"]), **_week(ctx), "note": "Rain on Thursday",
            "recipient_user_ids": [str(ctx["admin_id"]), str(ctx["engineer_id"]), str(nowa_id), str(outsider)]}
    r = await client.post("/reports/send", json=body, headers=_h(ctx["admin"]))
    assert r.status_code == 200, r.text
    out = r.json()
    people = {p["name"]: p for p in out["people"]}
    assert out["queued"] == 2 and out["skipped"] == 2
    assert people["Divya"]["reason"] == "no WhatsApp number"
    assert people["Someone"]["reason"] == "not in this company"
    assert people["Ilan Usman"]["sees_money"] is True and people["Sajan K"]["sees_money"] is False

    rows = (await _run(test_engine, "SELECT n.rule_key, n.payload, n.status, rs.report, rs.note, rs.pdf_object_key, "
                                    "u.full_name FROM report_snapshots rs JOIN notifications n ON n.id = rs.notification_id "
                                    "JOIN users u ON u.id = rs.recipient_user_id WHERE rs.send_id = :s",
                       s=uuid.UUID(out["send_id"]))).mappings().all()
    by = {r["full_name"]: r for r in rows}
    assert set(by) == {"Ilan Usman", "Sajan K"}
    for r in rows:
        assert r["rule_key"] == f"period_report:{out['send_id']}" and r["status"] == "pending"
        assert r["payload"]["template"]["name"] == "mesiri_period_report"
        assert len(r["payload"]["template"]["body_params"]) == 3
        assert r["payload"]["document_filename"].startswith("Villa-Kakkanad-")
        assert "Note from Ilan Usman: Rain on Thursday" in r["payload"]["message"]
        assert (await client.storage.get_object(r["pdf_object_key"])).data.startswith(b"%PDF")
    assert "money" in by["Ilan Usman"]["report"]["sections"]
    assert "money" not in by["Sajan K"]["report"]["sections"] and "₹" not in str(by["Sajan K"]["report"])

    sent = (await client.get(f"/reports/sent?project_id={ctx['project']}", headers=_h(ctx["admin"]))).json()
    assert sent["sends"][0]["note"] == "Rain on Thursday"
    assert {p["word"] for p in sent["sends"][0]["people"]} == {"Waiting to go"}
    admin_copy = next(p["snapshot_id"] for p in sent["sends"][0]["people"] if p["name"] == "Ilan Usman")
    one = await client.get(f"/reports/sent/{admin_copy}", headers=_h(ctx["admin"]))
    assert one.status_code == 200 and one.json()["changed_since"] == []
    assert (await client.get(f"/reports/sent/{admin_copy}", headers=_h(ctx["engineer"]))).status_code == 404
    pdf = await client.get(f"/reports/sent/{admin_copy}/pdf", headers=_h(ctx["admin"]))
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")

    # A late attendance: the sent copy keeps its figures and says what moved.
    report = uuid.uuid4()
    await _run(test_engine, "INSERT INTO labour_attendance_reports (id, organization_id, project_id, site_id, "
               "occurred_date, recorded_via, created_at, created_by) VALUES (:id, :org, :p, :s, :d, 'whatsapp_text', "
               "clock_timestamp(), :u)", id=report, org=ctx["org"], p=ctx["project"], s=ctx["site"],
               d=ctx["today"] - 5 * D, u=ctx["admin_id"])
    await _run(test_engine, "INSERT INTO labour_attendance_lines (id, report_id, trade, headcount, daily_wage, "
               "created_at) VALUES (:id, :r, 'mason', 3, 1100, now())", id=uuid.uuid4(), r=report)
    later = (await client.get(f"/reports/sent/{admin_copy}", headers=_h(ctx["admin"]))).json()
    assert {"label": "Man-days", "sent": "18", "now": "21"} in later["changed_since"]
    assert later["report"]["sections"]["labour"]["man_days"] == "18"


async def test_only_managers_send_to_others_and_names_are_never_guessed(client, ctx, test_engine):
    body = {"scope": "project", "project_id": str(ctx["project"]), **_week(ctx)}
    r = await client.post("/reports/send", json={**body, "recipient_user_ids": [str(ctx["admin_id"])]},
                          headers=_h(ctx["engineer"]))
    assert r.status_code == 403
    mine = await client.post("/reports/send", json=body, headers=_h(ctx["engineer"]))
    assert mine.status_code == 200 and mine.json()["queued"] == 1
    await _user(test_engine, ctx["org"], "project_manager", "Sajan M")
    r = await client.post("/reports/send", json={**body, "recipient_names": ["sajan"]}, headers=_h(ctx["admin"]))
    assert r.status_code == 422 and "Sajan K" in r.json()["detail"] and "Sajan M" in r.json()["detail"]
    r = await client.post("/reports/send", json={**body, "recipient_names": ["Sajan K"]}, headers=_h(ctx["admin"]))
    assert r.status_code == 200 and [p["name"] for p in r.json()["people"]] == ["Sajan K"]
    r = await client.post("/reports/send", json={**body, "recipient_names": ["Nobody Here"]}, headers=_h(ctx["admin"]))
    assert r.status_code == 422 and "No one called" in r.json()["detail"]


async def test_a_schedule_goes_by_itself_once_a_day_and_can_be_stopped(client, ctx, test_engine):
    from mesiri.domains.reports.period.send import run_scheduled

    await _seed(client, test_engine, ctx)
    h = _h(ctx["admin"])
    r = await client.post("/reports/schedules", headers=h, json={
        "project_id": str(ctx["project"]), "frequency": "WEEKLY", "day_of_week": 0, "time_of_day": "08:00",
        "recipient_user_ids": [str(ctx["engineer_id"])], "note": "Weekly for site"})
    assert r.status_code == 201, r.text
    sched = r.json()
    assert sched["recipients"] == [{"user_id": str(ctx["engineer_id"]), "name": "Sajan K"}]
    assert (await client.post("/reports/schedules", headers=_h(ctx["engineer"]), json={
        "frequency": "MONTHLY", "recipient_user_ids": [str(ctx["admin_id"])]})).status_code == 403
    monthly = await client.post("/reports/schedules", headers=_h(ctx["engineer"]), json={"frequency": "MONTHLY"})
    assert monthly.status_code == 201 and monthly.json()["day_of_week"] is None
    listed = (await client.get(f"/reports/schedules?project_id={ctx['project']}", headers=h)).json()["schedules"]
    assert [s["id"] for s in listed] == [sched["id"]]
    brief_schedules = (await client.get("/reports/schedules?scope=portfolio", headers=h)).json()["schedules"]
    assert [s["frequency"] for s in brief_schedules] == ["MONTHLY"]

    row = dict((await _run(test_engine, "SELECT * FROM automations WHERE id = :id",
                           id=uuid.UUID(sched["id"]))).mappings().one())
    assert row["action"] == "SEND_PERIOD_REPORT" and row["audience"] == "USERS"
    async with test_engine.begin() as conn:
        first = await run_scheduled(conn, client.storage, row, [str(ctx["engineer_id"])])
    async with test_engine.begin() as conn:
        again = await run_scheduled(conn, client.storage, row, [str(ctx["engineer_id"])])
    assert first["queued"] == 1 and first["period"]["kind"] == "week"
    assert again["queued"] == 0 and again["people"][0]["reason"] == "already sent to them today"
    n = (await _run(test_engine, "SELECT rule_key, payload FROM notifications WHERE organization_id = :org AND "
                                 "rule_key = :k", org=ctx["org"], k=f"automation:{sched['id']}")).mappings().all()
    assert len(n) == 1 and "Note from Ilan Usman: Weekly for site" in n[0]["payload"]["message"]

    assert (await client.delete(f"/reports/schedules/{sched['id']}", headers=_h(ctx["engineer"]))).status_code == 403
    assert (await client.delete(f"/reports/schedules/{sched['id']}", headers=h)).status_code == 200
    assert (await client.get(f"/reports/schedules?project_id={ctx['project']}", headers=h)).json()["schedules"] == []
