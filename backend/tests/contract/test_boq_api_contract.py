"""Contract tests for the BOQ API (CC-02): sections, lines, money, revisions, access.

Requires a live Postgres reachable via Settings().postgres.dsn() -- run with
`pytest -m integration`. Fixtures mirror test_materials_api_contract.py.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from mesiri.bootstrap.settings import Settings
from mesiri.domains.identity.auth_service import create_access_token
from mesiri.http.app import create_app
from mesiri.infrastructure.postgres.dependency import get_db_conn

pytestmark = pytest.mark.integration


@pytest.fixture
async def test_engine():
    engine = create_async_engine(Settings().postgres.dsn(), echo=False)
    yield engine
    await engine.dispose()


@pytest.fixture
async def clean_db(test_engine: AsyncEngine):
    async with test_engine.begin() as conn:
        await conn.execute(sa.text("DELETE FROM work_package_planned_items"))
        await conn.execute(sa.text("UPDATE activities SET work_package_id = NULL"))
        await conn.execute(sa.text("DELETE FROM work_packages"))
    yield


@pytest.fixture
async def client(test_engine: AsyncEngine, monkeypatch, clean_db):
    monkeypatch.setattr("mesiri.domains.shared.modules._database_for", lambda request: None)
    app = create_app()

    async def override_get_db_conn():
        async with test_engine.begin() as conn:
            yield conn

    app.dependency_overrides[get_db_conn] = override_get_db_conn
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
        yield c


async def _org(engine) -> uuid.UUID:
    org_id = uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO organizations (id, name, deployment_type, db_route, status, created_at, updated_at) "
                "VALUES (:id, 'BOQ Org', 'local', 'default', 'active', now(), now())"
            ),
            {"id": org_id},
        )
    return org_id


async def _user(engine, org_id, role: str, policy: str = '{"mode": "all_projects", "projects": []}') -> str:
    user_id = uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO users (id, organization_id, email, hashed_password, full_name, role, status, "
                "access_policy, created_at, updated_at) VALUES (:id, :org, :email, 'hash', 'T', :role, "
                "'active', CAST(:policy AS jsonb), now(), now())"
            ),
            {"id": user_id, "org": org_id, "email": f"{uuid.uuid4().hex[:8]}@example.com", "role": role, "policy": policy},
        )
    return create_access_token(data={"sub": str(user_id), "org": str(org_id), "role": role})


async def _project(engine, org_id) -> uuid.UUID:
    project_id, site_id = uuid.uuid4(), uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO projects (id, organization_id, name, created_at, updated_at) "
                "VALUES (:id, :org, 'Villa Kakkanad', now(), now())"
            ),
            {"id": project_id, "org": org_id},
        )
        await conn.execute(
            sa.text(
                "INSERT INTO sites (id, project_id, organization_id, name, status, created_at, updated_at) "
                "VALUES (:id, :p, :org, 'Main building', 'active', now(), now())"
            ),
            {"id": site_id, "p": project_id, "org": org_id},
        )
    return project_id


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def ctx(test_engine):
    org = await _org(test_engine)
    return {"org": org, "project": await _project(test_engine, org), "admin": await _user(test_engine, org, "admin")}


async def _section(client, ctx, name="Plastering", **extra) -> dict:
    r = await client.post(f"/projects/{ctx['project']}/boq/sections", json={"name": name, **extra}, headers=_h(ctx["admin"]))
    assert r.status_code == 201, r.text
    return r.json()


async def _add_line(client, ctx, section_id, **body) -> dict:
    r = await client.post(
        f"/projects/{ctx['project']}/boq/sections/{section_id}/lines", json=body, headers=_h(ctx["admin"])
    )
    assert r.status_code == 201, r.text
    return r.json()


async def test_boq_lines_carry_contract_budget_and_margin(client, ctx):
    section = await _section(client, ctx, code="4")
    line = await _add_line(
        client, ctx, section["id"], work="Internal plastering 12 mm", unit="sq ft", planned_quantity="18000",
        boq_code="4.1", client_rate="42", labour_rate="14", material_rate="22",
    )
    assert line["unit"] == "sqft"
    # Money is sent as exact strings, never floats.
    assert line["contract_value"] == "756000.00" and line["planned_quantity"] == "18000.000"
    assert Decimal(line["contract_value"]) == Decimal("756000.00")
    assert Decimal(line["budget_cost"]) == Decimal("648000.00")
    assert Decimal(line["margin"]) == Decimal("108000.00")

    concrete = await _section(client, ctx, name="Concrete work")
    await _add_line(client, ctx, concrete["id"], work="M20 in columns", unit="m3", planned_quantity="20")

    boq = (await client.get(f"/projects/{ctx['project']}/boq", headers=_h(ctx["admin"]))).json()
    assert [s["name"] for s in boq["sections"]] == ["Plastering", "Concrete work"]
    assert boq["totals"]["line_count"] == 2
    assert Decimal(boq["totals"]["contract_value"]) == Decimal("756000.00")
    # The concrete line has no rates: no project margin, and the totals say why.
    assert boq["totals"]["margin"] is None
    assert boq["totals"]["lines_without_client_rate"] == 1
    assert boq["totals"]["lines_without_budget_rate"] == 1


async def test_quantity_change_is_a_revision_and_history_is_kept(client, ctx, test_engine):
    section = await _section(client, ctx)
    line = await _add_line(client, ctx, section["id"], work="Plaster", unit="sqft", planned_quantity="100", client_rate="40")
    r = await client.patch(
        f"/projects/{ctx['project']}/boq/lines/{line['id']}",
        json={"planned_quantity": "120", "revision_reason": "Balcony added", "labour_rate": "15"},
        headers=_h(ctx["admin"]),
    )
    assert r.status_code == 200, r.text
    revised = r.json()
    assert revised["id"] != line["id"] and revised["revision_no"] == 2
    assert Decimal(revised["planned_quantity"]) == Decimal("120")
    assert Decimal(revised["labour_rate"]) == Decimal("15")  # in-place change carried into the revision
    assert Decimal(revised["contract_value"]) == Decimal("4800.00")
    async with test_engine.begin() as conn:
        rows = (await conn.execute(
            sa.text("SELECT planned_quantity, superseded_by_id FROM work_package_planned_items WHERE work_package_id = :s ORDER BY revision_no"),
            {"s": section["id"]},
        )).all()
    assert [r[0] for r in rows] == [Decimal("100"), Decimal("120")]
    assert str(rows[0][1]) == revised["id"] and rows[1][1] is None
    # The old revision can no longer be edited; the current one can be removed with its history.
    old = await client.patch(f"/projects/{ctx['project']}/boq/lines/{line['id']}", json={"boq_code": "x"}, headers=_h(ctx["admin"]))
    assert old.status_code == 404
    gone = await client.delete(f"/projects/{ctx['project']}/boq/lines/{revised['id']}", headers=_h(ctx["admin"]))
    assert gone.status_code == 204
    async with test_engine.begin() as conn:
        left = (await conn.execute(sa.text("SELECT count(*) FROM work_package_planned_items WHERE work_package_id = :s"), {"s": section["id"]})).scalar_one()
    assert left == 0


async def test_same_quantity_or_rates_only_edit_in_place(client, ctx):
    section = await _section(client, ctx)
    line = await _add_line(client, ctx, section["id"], work="Brickwork", unit="cum", planned_quantity="10", client_rate="5000")
    r = await client.patch(
        f"/projects/{ctx['project']}/boq/lines/{line['id']}",
        json={"planned_quantity": "10.000", "client_rate": None, "work": "Brickwork 230 mm"},
        headers=_h(ctx["admin"]),
    )
    assert r.status_code == 200, r.text
    assert r.json()["id"] == line["id"] and r.json()["revision_no"] == 1
    assert r.json()["client_rate"] is None and r.json()["contract_value"] is None
    assert r.json()["work"] == "Brickwork 230 mm"


async def test_validation_duplicates_units_and_codes(client, ctx):
    section = await _section(client, ctx, code="A")
    await _add_line(client, ctx, section["id"], work="Plaster", unit="sqft", planned_quantity="1")
    base = f"/projects/{ctx['project']}/boq"
    dup = await client.post(f"{base}/sections/{section['id']}/lines", json={"work": "Plaster", "unit": "sq.ft", "planned_quantity": "2"}, headers=_h(ctx["admin"]))
    assert dup.status_code == 409
    # Same work in another unit is a different line.
    other = await client.post(f"{base}/sections/{section['id']}/lines", json={"work": "Plaster", "unit": "sqm", "planned_quantity": "2"}, headers=_h(ctx["admin"]))
    assert other.status_code == 201
    bad_unit = await client.post(f"{base}/sections/{section['id']}/lines", json={"work": "X", "unit": "furlong", "planned_quantity": "1"}, headers=_h(ctx["admin"]))
    assert bad_unit.status_code == 422 and "furlong" in bad_unit.json()["detail"]
    negative = await client.post(f"{base}/sections/{section['id']}/lines", json={"work": "X", "unit": "nos", "planned_quantity": "1", "client_rate": "-5"}, headers=_h(ctx["admin"]))
    assert negative.status_code == 422
    zero_qty = await client.post(f"{base}/sections/{section['id']}/lines", json={"work": "X", "unit": "nos", "planned_quantity": "0"}, headers=_h(ctx["admin"]))
    assert zero_qty.status_code == 422
    code = await client.post(f"{base}/sections", json={"name": "Other", "code": "A"}, headers=_h(ctx["admin"]))
    assert code.status_code == 409
    foreign_site = await client.post(f"{base}/sections", json={"name": "Other", "site_id": str(uuid.uuid4())}, headers=_h(ctx["admin"]))
    assert foreign_site.status_code == 422


async def test_section_with_logged_work_is_not_removed(client, ctx, test_engine):
    section = await _section(client, ctx)
    empty = await _section(client, ctx, name="Empty")
    async with test_engine.begin() as conn:
        site_id = (await conn.execute(sa.text("SELECT id FROM sites WHERE project_id = :p"), {"p": ctx["project"]})).scalar_one()
        await conn.execute(
            sa.text(
                "INSERT INTO activities (id, organization_id, project_id, site_id, work_package_id, activity_date, source) "
                "VALUES (:id, :org, :p, :s, :w, current_date, 'dashboard')"
            ),
            {"id": uuid.uuid4(), "org": ctx["org"], "p": ctx["project"], "s": site_id, "w": section["id"]},
        )
    base = f"/projects/{ctx['project']}/boq/sections"
    assert (await client.delete(f"{base}/{section['id']}", headers=_h(ctx["admin"]))).status_code == 409
    assert (await client.delete(f"{base}/{empty['id']}", headers=_h(ctx["admin"]))).status_code == 204


async def test_who_may_see_the_boq(client, ctx, test_engine):
    url = f"/projects/{ctx['project']}/boq"
    engineer = await _user(test_engine, ctx["org"], "SITE_ENGINEER")
    assert (await client.get(url, headers=_h(engineer))).status_code == 403
    finance = await _user(test_engine, ctx["org"], "FINANCE")
    assert (await client.get(url, headers=_h(finance))).status_code == 200
    # A project manager with no access to this project.
    pm = await _user(test_engine, ctx["org"], "PROJECT_MANAGER", '{"mode": "custom_projects", "projects": []}')
    assert (await client.get(url, headers=_h(pm))).status_code == 403
    # Another company's admin never sees it.
    other_org = await _org(test_engine)
    stranger = await _user(test_engine, other_org, "admin")
    assert (await client.get(url, headers=_h(stranger))).status_code == 404


# -- CC-04: work done against the lines -----------------------------------------------------------


async def _work(engine, ctx, *, quantity: str, unit: str, work: str = "M20 concrete slab", project=None) -> str:
    """A site's work update with one quantity, as the DPR saves it; returns the quantity's id."""
    project = project or ctx["project"]
    activity_id, quantity_id = uuid.uuid4(), uuid.uuid4()
    async with engine.begin() as conn:
        site_id = (await conn.execute(sa.text("SELECT id FROM sites WHERE project_id = :p"), {"p": project})).scalar_one()
        unit_id = (await conn.execute(sa.text("SELECT id FROM units_of_measure WHERE code = :u"), {"u": unit})).scalar_one()
        await conn.execute(
            sa.text(
                "INSERT INTO activities (id, organization_id, project_id, site_id, work_type, activity_date, source) "
                "VALUES (:id, :org, :p, :s, :w, current_date, 'dashboard')"
            ),
            {"id": activity_id, "org": ctx["org"], "p": project, "s": site_id, "w": work},
        )
        await conn.execute(
            sa.text("INSERT INTO activity_quantities (id, activity_id, unit_id, quantity) VALUES (:id, :a, :u, :q)"),
            {"id": quantity_id, "a": activity_id, "u": unit_id, "q": Decimal(quantity)},
        )
    return str(quantity_id)


async def _concrete(client, ctx) -> tuple[dict, str]:
    section = await _section(client, ctx, name="Concrete work")
    line = await _add_line(
        client, ctx, section["id"], work="M20 concrete in slab", unit="cum", planned_quantity="100",
        labour_rate="1500", material_rate="3500",
    )
    return line, f"/projects/{ctx['project']}/boq"


def _line_in(boq: dict, line_id: str) -> dict:
    return next(ln for s in boq["sections"] for ln in s["lines"] if ln["id"] == line_id)


async def test_work_put_on_a_line_counts_once_and_earns_by_kind(client, ctx, test_engine):
    line, url = await _concrete(client, ctx)
    q = await _work(test_engine, ctx, quantity="8", unit="cum")
    h = _h(ctx["admin"])

    listed = (await client.get(f"{url}/work?unlinked=true", headers=h)).json()["work"]
    assert [w["id"] for w in listed] == [q]
    assert listed[0]["suggested_line_id"] == line["id"]  # offered, not saved
    assert _line_in((await client.get(url, headers=h)).json(), line["id"])["done_quantity"] == "0"

    for _ in range(2):  # put on the line twice: still counted once
        assert (await client.put(f"{url}/work/{q}", json={"line_id": line["id"]}, headers=h)).status_code == 204
    got = _line_in((await client.get(url, headers=h)).json(), line["id"])
    assert Decimal(got["done_quantity"]) == 8 and Decimal(got["remaining_quantity"]) == 92
    assert got["earned_labour"] == "12000.00" and got["earned_material"] == "28000.00" and got["earned"] == "40000.00"
    assert (await client.get(f"{url}/work?unlinked=true", headers=h)).json()["work"] == []

    assert (await client.put(f"{url}/work/{q}", json={"line_id": None}, headers=h)).status_code == 204
    assert Decimal(_line_in((await client.get(url, headers=h)).json(), line["id"])["done_quantity"]) == 0


async def test_work_stays_on_the_line_through_a_quantity_revision(client, ctx, test_engine):
    line, url = await _concrete(client, ctx)
    q = await _work(test_engine, ctx, quantity="8", unit="cum")
    h = _h(ctx["admin"])
    await client.put(f"{url}/work/{q}", json={"line_id": line["id"]}, headers=h)
    revised = await client.patch(f"{url}/lines/{line['id']}", json={"planned_quantity": "120", "revision_reason": "Balcony"}, headers=h)
    got = _line_in((await client.get(url, headers=h)).json(), revised.json()["id"])
    assert Decimal(got["done_quantity"]) == 8 and Decimal(got["remaining_quantity"]) == 112
    work = (await client.get(f"{url}/work", headers=h)).json()["work"]
    assert work[0]["line_id"] == revised.json()["id"]


async def test_removed_work_and_other_units_are_not_added(client, ctx, test_engine):
    line, url = await _concrete(client, ctx)
    h = _h(ctx["admin"])
    sqft = await _work(test_engine, ctx, quantity="400", unit="sqft")
    r = await client.put(f"{url}/work/{sqft}", json={"line_id": line["id"]}, headers=h)
    assert r.status_code == 422 and "cum" in r.json()["detail"]

    q = await _work(test_engine, ctx, quantity="5", unit="cum")
    await client.put(f"{url}/work/{q}", json={"line_id": line["id"]}, headers=h)
    async with test_engine.begin() as conn:
        await conn.execute(
            sa.text("UPDATE activities SET deleted_at = now() FROM activity_quantities q WHERE q.activity_id = activities.id AND q.id = :q"),
            {"q": q},
        )
    assert Decimal(_line_in((await client.get(url, headers=h)).json(), line["id"])["done_quantity"]) == 0
    assert (await client.put(f"{url}/work/{q}", json={"line_id": None}, headers=h)).status_code == 404


async def test_work_of_another_project_or_a_line_elsewhere_is_refused(client, ctx, test_engine):
    line, url = await _concrete(client, ctx)
    h = _h(ctx["admin"])
    other = await _project(test_engine, ctx["org"])
    elsewhere = await _work(test_engine, ctx, quantity="3", unit="cum", project=other)
    assert (await client.put(f"{url}/work/{elsewhere}", json={"line_id": line["id"]}, headers=h)).status_code == 404
    other_url = f"/projects/{other}/boq"
    assert (await client.put(f"{other_url}/work/{elsewhere}", json={"line_id": line["id"]}, headers=h)).status_code == 422


async def test_engineers_do_not_see_or_change_work_on_lines(client, ctx, test_engine):
    line, url = await _concrete(client, ctx)
    q = await _work(test_engine, ctx, quantity="8", unit="cum")
    engineer = _h(await _user(test_engine, ctx["org"], "SITE_ENGINEER"))
    assert (await client.get(f"{url}/work", headers=engineer)).status_code == 403
    assert (await client.put(f"{url}/work/{q}", json={"line_id": line["id"]}, headers=engineer)).status_code == 403


async def test_work_order_measurements_count_on_the_boq_line_once(client, ctx, test_engine):
    """A confirmed measurement on a work-order line that is a BOQ line counts; one taken from a
    site work update does not count again (the work update itself is already on the line)."""
    line, url = await _concrete(client, ctx)
    h = _h(ctx["admin"])
    q = await _work(test_engine, ctx, quantity="4", unit="cum")
    async with test_engine.begin() as conn:
        vendor = (await conn.execute(sa.text(
            "INSERT INTO vendors (id, organization_id, name, status, created_by) VALUES (gen_random_uuid(), :org, 'Concrete team', "
            "'active', (SELECT id FROM users WHERE organization_id = :org LIMIT 1)) RETURNING id"), {"org": ctx["org"]})).scalar_one()
        wo = (await conn.execute(sa.text(
            "INSERT INTO work_orders (organization_id, number, vendor_id, project_id, status) VALUES (:org, 1, :v, :p, 'issued') "
            "RETURNING id"), {"org": ctx["org"], "v": vendor, "p": ctx["project"]})).scalar_one()
        wol = (await conn.execute(sa.text(
            "INSERT INTO work_order_lines (organization_id, work_order_id, planned_item_id, description, unit, quantity, rate) "
            "VALUES (:org, :wo, :pi, 'M20 concrete in slab', 'm3', 100, 1400) RETURNING id"),
            {"org": ctx["org"], "wo": wo, "pi": line["id"]})).scalar_one()
        for qty, status, source, aq in (("6", "confirmed", "web", None), ("9", "proposed", "web", None),
                                        ("4", "confirmed", "activity", q)):
            await conn.execute(sa.text(
                "INSERT INTO work_order_measurements (organization_id, work_order_id, line_id, measured_on, quantity, status, source, "
                "activity_quantity_id) VALUES (:org, :wo, :l, current_date, :q, :st, :src, :aq)"),
                {"org": ctx["org"], "wo": wo, "l": wol, "q": Decimal(qty), "st": status, "src": source, "aq": aq})
        await conn.execute(sa.text("UPDATE activity_quantities SET work_order_line_id = :l, planned_item_id = :pi WHERE id = :q"),
                           {"l": wol, "pi": line["id"], "q": q})
    # 6 measured on the web + 4 from the work update; the proposed 9 is not confirmed yet.
    assert Decimal(_line_in((await client.get(url, headers=h)).json(), line["id"])["done_quantity"]) == 10
    r = await client.put(f"{url}/work/{q}", json={"line_id": None}, headers=h)
    assert r.status_code == 409  # changed on the work order, so the two never disagree
