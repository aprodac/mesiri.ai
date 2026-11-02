"""WA-151 on a real database: "10 TMT steel bars used" when the company stocks TMT in kg (Ilan, Paraclette, 2 Nov).

- A steel material whose name gives the bar size ("TMT 12mm") converts by itself: 10 bars = 106.67 kg.
- Without a size, the line is refused naming the stock unit and the unit sent; the company sets "1 bar = 10.67 kg"
  once (admin / project manager only), and the same line then saves converted, through one Save.
- Receipts and transfers convert the same way; a line already in the stock unit is untouched.

Needs Postgres at head; marked ``integration``.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
import sqlalchemy as sa
from tests.integration.test_api_agent_119_postgres import _company

from agent_api.agent import PendingWrite, confirm
from agent_api.app import build_api_app
from agent_api.client import Actor, ApiClient, new_idempotency_key

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
async def _fresh_projects_engine():
    """One projects-router engine per test (each test has its own event loop)."""
    import projects.router as projects_router

    projects_router._engine = None
    yield
    if projects_router._engine is not None:
        await projects_router._engine.dispose()
    projects_router._engine = None


@pytest.fixture
async def database():
    from mesiri.bootstrap.settings import Settings
    from mesiri.infrastructure.postgres.database import PostgresDatabase

    db = PostgresDatabase(Settings().postgres)
    await db.connect()
    yield db
    await db.disconnect()


async def _material(db, company: dict, name: str, unit: str) -> str:  # noqa: ANN001
    import uuid

    mid = uuid.uuid4()
    async with db.transaction() as conn:
        await conn.execute(sa.text(
            "INSERT INTO materials_catalog (id, organization_id, name, default_unit_id, is_active, created_by) "
            "VALUES (:id, :org, :name, (SELECT id FROM units_of_measure WHERE code = :unit), true, :user)"),
            {"id": mid, "org": company["org"], "user": company["user"], "name": name, "unit": unit})
    return str(mid)


async def _unit(db, code: str) -> str:  # noqa: ANN001
    async with db.transaction() as conn:
        return str((await conn.execute(sa.text("SELECT id FROM units_of_measure WHERE code = :c"), {"c": code})).scalar())


def _usage(company: dict, material: str, unit: str, qty: int, line: str) -> PendingWrite:
    return PendingWrite(tool="record_usage", method="POST", path="/materials/outflows", params={}, body={
        "project_id": company["project"], "site_id": company["site"], "material_id": material, "unit_id": unit,
        "quantity": qty, "occurred_date": "2026-11-02"}, summary=line, idempotency_key=new_idempotency_key())


async def _used(db, company: dict, material: str) -> list:  # noqa: ANN001
    async with db.transaction() as conn:
        return (await conn.execute(sa.text(
            "SELECT quantity, unit, notes FROM material_usage WHERE organization_id = :o AND material_id = :m"),
            {"o": company["org"], "m": material})).all()


async def test_bars_of_a_sized_tmt_convert_into_kg_by_themselves(database) -> None:  # noqa: ANN001
    co = await _company(database, "Paraclette test")
    tmt = await _material(database, co, "TMT 12mm", "kg")
    client = ApiClient(Actor(co["user"], co["org"], "ADMIN", "Ilan"), app=build_api_app(database))
    try:
        [result] = await confirm(client, [_usage(co, tmt, await _unit(database, "nos"), 10, "10 TMT bars used")])
    finally:
        await client.close()
    assert result.ok, result.body
    [(qty, unit, notes)] = await _used(database, co, tmt)
    assert (Decimal(qty), unit) == (Decimal("106.67"), "kg") and "reported as 10 Numbers" in notes


async def test_without_a_size_the_company_sets_it_once_and_the_same_line_saves(database) -> None:  # noqa: ANN001
    co = await _company(database, "Paraclette test 2")
    tmt = await _material(database, co, "TMT Steel", "kg")
    nos = await _unit(database, "nos")
    app = build_api_app(database)
    client = ApiClient(Actor(co["user"], co["org"], "ADMIN", "Ilan"), app=app)
    try:
        line = _usage(co, tmt, nos, 10, "10 TMT steel bars used at Tower A")
        [refused] = await confirm(client, [line])
        assert refused.status == 422
        assert "Stock Unit (expected kg); no conversion from Numbers is set" in str(refused.body)
        from agent_api.units import plain_refusal

        assert "How many kg is one bar?" in plain_refusal(str(refused.body.get("detail")), "english")

        # One Save: the conversion is prepared after the line, and still saves first.
        conversion = PendingWrite(tool="set_unit_conversion", method="PUT", path=f"/materials/{tmt}/unit-conversions",
                                  params={}, body={"from_unit_id": nos, "one_unit_equals": "10.67"},
                                  summary="1 bar of TMT Steel = 10.67 kg", idempotency_key=new_idempotency_key())
        again = PendingWrite(**{**line.to_json(), "idempotency_key": new_idempotency_key()})
        results = await confirm(client, [again, conversion])
        assert [r.ok for r in results] == [True, True], [r.body for r in results]
        assert results[1].body["message"] == "Saved for the company: 1 Numbers of TMT Steel = 10.67 Kilograms."
    finally:
        await client.close()
    [(qty, unit, _)] = await _used(database, co, tmt)
    assert (Decimal(qty), unit) == (Decimal("106.7"), "kg")


async def test_guard_only_an_admin_or_project_manager_sets_a_conversion(database) -> None:  # noqa: ANN001
    import uuid

    co = await _company(database, "Paraclette test 3")
    tmt = await _material(database, co, "TMT Steel", "kg")
    supervisor = uuid.uuid4()
    async with database.transaction() as conn:
        await conn.execute(sa.text(
            "INSERT INTO users (id, organization_id, email, hashed_password, full_name, role, created_at, updated_at) "
            "VALUES (:id, :org, :email, 'x', 'Ravi', 'SITE_SUPERVISOR', now(), now())"),
            {"id": supervisor, "org": co["org"], "email": f"{supervisor}@t.in"})
    client = ApiClient(Actor(str(supervisor), co["org"], "SITE_SUPERVISOR", "Ravi"), app=build_api_app(database))
    try:
        response = await client.call("PUT", f"/materials/{tmt}/unit-conversions",
                                     json={"from_unit_id": await _unit(database, "nos"), "one_unit_equals": "10.67"})
    finally:
        await client.close()
    assert response.status == 403


async def test_guard_a_line_in_the_stock_unit_and_a_receipt_with_a_rate(database) -> None:  # noqa: ANN001
    co = await _company(database, "Paraclette test 4")
    tmt = await _material(database, co, "TMT 16mm", "kg")
    kg, nos = await _unit(database, "kg"), await _unit(database, "nos")
    client = ApiClient(Actor(co["user"], co["org"], "ADMIN", "Ilan"), app=build_api_app(database))
    try:
        plain = await client.call("POST", "/materials/outflows", json={
            "project_id": co["project"], "site_id": co["site"], "material_id": tmt, "unit_id": kg,
            "quantity": 50, "occurred_date": "2026-11-02"})
        receipt = await client.call("POST", "/materials/inflows", json={
            "project_id": co["project"], "site_id": co["site"], "material_id": tmt, "unit_id": nos,
            "quantity": 20, "unit_cost": 1200, "occurred_date": "2026-11-02"})
    finally:
        await client.close()
    assert plain.status == 201 and receipt.status == 201, (plain.body, receipt.body)
    assert [(Decimal(q), u, n) for q, u, n in await _used(database, co, tmt)] == [(Decimal("50"), "kg", None)]
    async with database.transaction() as conn:
        qty, unit, rate = (await conn.execute(sa.text(
            "SELECT quantity, unit, unit_cost FROM material_receipts WHERE organization_id = :o AND material_id = :m"),
            {"o": co["org"], "m": tmt})).one()
    # 20 bars of 16 mm (18.963 kg each) = 379.26 kg; Rs 1200 a bar = Rs 63.28 a kg.
    assert (Decimal(qty), unit) == (Decimal("379.26"), "kg") and Decimal(rate) == Decimal("63.28")
