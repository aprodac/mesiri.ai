"""WEB-82: Live's ripple read from real records, against a real Postgres (integration).

The demo company's reset (SA-36) saves two weeks of deliveries, use and attendance through the API. For the newest
delivery with a rate, the newest use and the newest attendance report, the effects read must agree with the
records themselves: the stock is the ledger's balance, the wages are the lines' wages, and the money stays hidden
from a role that does not see spending.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text

from mesiri.domains.dpr import effects

pytestmark = pytest.mark.integration
TODAY = dt.date(2026, 11, 3)


@pytest.fixture
async def demo():
    from sqlalchemy.ext.asyncio import create_async_engine

    from admin.demo import reset_demo
    from mesiri.application.organizations.create_company import NewCompany, create_company
    from mesiri.application.organizations.delete_company import delete_company
    from mesiri.bootstrap.settings import Settings
    from mesiri.domains.audit.actions import AuditActor
    from mesiri.infrastructure.postgres.database import PostgresDatabase

    engine = create_async_engine(Settings().postgres.dsn())
    database = PostgresDatabase(Settings().postgres)
    await database.connect()
    tag = uuid.uuid4().hex[:6]
    async with engine.begin() as conn:
        made = await create_company(conn, NewCompany(
            name=f"Ripple Builders {tag}", owner_name="Anil", owner_phone=f"+91 98{uuid.uuid4().int % 10**8:08d}",
            owner_email=f"anil-{tag}@demo.test", project_name="Old project"))
        await conn.execute(text(
            "INSERT INTO organization_settings (id, organization_id, key, value) "
            "VALUES (gen_random_uuid(), :o, 'demo_company', 'true'::jsonb)"), {"o": made.organization_id})
    result = await reset_demo(engine, database, made.organization_id,
                              actor=AuditActor(kind="platform_admin", label="Test admin"), today=TODAY)
    assert result.failed == [], result.failed
    yield engine, result.organization_id
    async with engine.begin() as conn:
        await delete_company(conn, result.organization_id)
    await database.disconnect()
    await engine.dispose()


def _one(cards, key):
    return next((c for c in cards if c["key"] == key), None)


async def test_a_delivery_a_use_and_an_attendance_agree_with_their_records(demo) -> None:
    engine, org = demo
    async with engine.connect() as conn:
        # --- the newest delivery with a rate and a supplier on the list -------------------------------------
        r = (await conn.execute(text(
            "SELECT r.id, r.site_id, r.material_id, r.quantity, r.unit_cost, r.vendor_id FROM material_receipts r "
            "WHERE r.organization_id = :o AND r.movement_reason = 'RECEIVED' AND r.transfer_id IS NULL "
            "AND r.unit_cost IS NOT NULL AND r.vendor_id IS NOT NULL ORDER BY r.created_at DESC LIMIT 1"), {"o": org})).first()
        assert r is not None, "the demo has a priced delivery from a listed supplier"
        balance = (await conn.execute(text(
            "SELECT COALESCE(SUM(CASE WHEN movement_type = 'RECEIPT' THEN quantity ELSE -quantity END), 0) "
            "FROM material_movements WHERE organization_id = :o AND site_id = :s AND material_id = :m"),
            {"o": org, "s": r.site_id, "m": r.material_id})).scalar()

        facts = await effects.read_receipt(conn, org, r.id, TODAY, sees_money=True)
        out = effects.cards("material_receipt", facts, True)
        keys = [c["key"] for c in out["cards"]]
        assert keys[0] == "stock" and keys[-1] == "report" and "rate" in keys and "supplier" in keys, keys
        assert Decimal(_one(out["cards"], "stock")["after"]) == Decimal(balance)
        assert Decimal(facts["rate"]["entered"]) == Decimal(r.unit_cost)
        assert Decimal(facts["supplier"]["balance"]) > 0
        assert Decimal(facts["amount"]) == Decimal(r.unit_cost) * Decimal(r.quantity)

        # Guard: the same delivery for a role that does not see spending has no rupee on it.
        plain = effects.cards("material_receipt", await effects.read_receipt(conn, org, r.id, TODAY, sees_money=False), False)
        assert [c["key"] for c in plain["cards"]] == ["stock", "report"]
        assert "₹" not in " ".join(c["sentence"] for c in plain["cards"])

        # --- the newest use -----------------------------------------------------------------------------------
        u = (await conn.execute(text(
            "SELECT u.id, u.site_id, u.material_id, u.quantity, u.created_at FROM material_usage u "
            "WHERE u.organization_id = :o AND u.movement_reason = 'CONSUMED' AND u.transfer_id IS NULL "
            "AND u.reverses_movement_id IS NULL ORDER BY u.created_at DESC LIMIT 1"), {"o": org})).first()
        held = (await conn.execute(text(
            "SELECT COALESCE(SUM(CASE WHEN movement_type = 'RECEIPT' THEN quantity ELSE -quantity END), 0) "
            "FROM material_movements WHERE organization_id = :o AND site_id = :s AND material_id = :m"),
            {"o": org, "s": u.site_id, "m": u.material_id})).scalar()
        used = effects.cards("material_usage", await effects.read_usage(conn, org, u.id, TODAY, True), True)
        stock = _one(used["cards"], "stock")
        assert Decimal(stock["after"]) == Decimal(held)
        assert stock["before"] is not None and Decimal(stock["before"]) == Decimal(held) + Decimal(u.quantity)

        # --- the newest attendance report -------------------------------------------------------------------
        a = (await conn.execute(text(
            "SELECT r.id FROM labour_attendance_reports r WHERE r.organization_id = :o AND r.voided_at IS NULL "
            "ORDER BY r.occurred_date DESC, r.created_at DESC LIMIT 1"), {"o": org})).first()
        lines = (await conn.execute(text(
            "SELECT COALESCE(headcount, 1) AS heads, daily_wage, attendance_status FROM labour_attendance_lines "
            "WHERE report_id = :id"), {"id": a.id})).all()
        factor = {"present": Decimal(1), "half_day": Decimal("0.5"), "absent": Decimal(0)}
        wages = sum((Decimal(ln.heads) * factor[ln.attendance_status or "present"] * Decimal(ln.daily_wage)
                     for ln in lines if ln.daily_wage is not None), Decimal(0))
        heads = sum(int(ln.heads) for ln in lines if (ln.attendance_status or "present") != "absent")
        att = await effects.read_attendance(conn, org, a.id, TODAY, True)
        cards = effects.cards("labour_report", att, True)["cards"]
        assert Decimal(_one(cards, "on_site")["after"]) == heads
        assert Decimal(att["wages"]["today"]) == wages and wages > 0
        assert Decimal(att["wages"]["week"]) >= wages
        assert [c["key"] for c in effects.cards("labour_report", await effects.read_attendance(conn, org, a.id, TODAY, False), False)["cards"]] == ["on_site", "report"]


        # --- guard: half of a transfer, and a record that is not there, have no ripple -----------------------
        # (One test: a second demo reset in the same run meets the app's connection pool on a closed event loop.)
        t = (await conn.execute(text(
            "SELECT id FROM material_usage WHERE organization_id = :o AND transfer_id IS NOT NULL LIMIT 1"), {"o": org})).first()
        assert t is not None, "the demo has a transfer"
        assert await effects.read_usage(conn, org, t.id, TODAY, True) is None
        assert await effects.read_receipt(conn, org, uuid.uuid4(), TODAY, True) is None
        assert await effects.read_attendance(conn, org, uuid.uuid4(), TODAY, True) is None
