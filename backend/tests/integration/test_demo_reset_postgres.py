"""SA-30: a demo company reset in one tap, against a real Postgres (integration).

The demo is deleted and created again with the same people and fresh sample records (through the API as its
owner). Guards: a company that is not marked as a demo is refused and left untouched; a failure leaves the old demo.
The reset commits, so each test removes what it made.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration


@pytest.fixture
async def world():
    from sqlalchemy.ext.asyncio import create_async_engine

    from mesiri.bootstrap.settings import Settings
    from mesiri.infrastructure.postgres.database import PostgresDatabase

    engine = create_async_engine(Settings().postgres.dsn())
    database = PostgresDatabase(Settings().postgres)
    await database.connect()
    made: list[uuid.UUID] = []
    yield engine, database, made
    from mesiri.application.organizations.delete_company import delete_company

    async with engine.begin() as conn:
        for org in made:
            await delete_company(conn, org)
    await database.disconnect()
    await engine.dispose()


async def _company(engine, *, demo: bool) -> tuple[uuid.UUID, str]:
    from mesiri.application.organizations.create_company import NewCompany, create_company

    tag = uuid.uuid4().hex[:6]
    phone = f"+91 98{uuid.uuid4().int % 10**8:08d}"
    async with engine.begin() as conn:
        created = await create_company(conn, NewCompany(name=f"Demo Builders {tag}", owner_name="Anil", owner_phone=phone,
                                                        owner_email=f"anil-{tag}@demo.test", project_name="Old project"))
        await conn.execute(text(
            "INSERT INTO users (id, organization_id, email, hashed_password, full_name, role, status, whatsapp_number) "
            "VALUES (:id, :o, :e, 'x', 'Ravi', 'SITE_ENGINEER', 'active', :w)"),
            {"id": uuid.uuid4(), "o": created.organization_id, "e": f"ravi-{tag}@demo.test", "w": f"+91 97{uuid.uuid4().int % 10**8:08d}"})
        if demo:
            await conn.execute(text(
                "INSERT INTO organization_settings (id, organization_id, key, value) VALUES (gen_random_uuid(), :o, 'demo_company', 'true'::jsonb)"),
                {"o": created.organization_id})
        await conn.execute(text(
            "INSERT INTO organization_settings (id, organization_id, key, value) VALUES (gen_random_uuid(), :o, 'join_code', '\"OLD-1234\"'::jsonb)"),
            {"o": created.organization_id})
    return created.organization_id, phone


async def test_the_demo_comes_back_with_its_people_settings_and_fresh_records(world) -> None:
    from admin.demo import reset_demo
    from mesiri.domains.audit.actions import AuditActor

    engine, database, made = world
    old_id, phone = await _company(engine, demo=True)
    made.append(old_id)
    actor = AuditActor(kind="platform_admin", label="Test admin")
    result = await reset_demo(engine, database, old_id, actor=actor, today=dt.date(2026, 11, 2))
    made.append(result.organization_id)

    assert result.organization_id != old_id and result.people == 2
    assert result.failed == [], result.failed
    # SA-36: two weeks on two projects (2 Nov 2026 is a Monday: 12 working days, 4 sites).
    assert result.seeded.get("project") == 1 and result.seeded.get("site") == 2 and result.seeded.get("member") == 2
    assert result.seeded.get("attendance") == 48 and result.seeded.get("work done") == 48 and result.seeded.get("expense") == 48
    assert result.seeded.get("site conditions") == 48 and result.seeded.get("worker") == 15 and result.seeded.get("vendor") == 7
    assert result.seeded.get("material received", 0) >= 40 and result.seeded.get("material used", 0) >= 150
    assert result.seeded.get("transfer") == 1 and result.seeded.get("issue") == 6 and result.seeded.get("issue resolved") == 3
    # WEB-85: what Live's stories need: minimums, orders, a supplier's bill, advances, wage sheets, an estimate with
    # the site's work counted on it, the client's contract and a first bill sent.
    assert result.seeded.get("minimum stock") == 6 and result.seeded.get("order") == 2 and result.seeded.get("supplier bill") == 1
    assert result.seeded.get("advance") == 3 and result.seeded.get("wage sheet approved") == 2
    assert result.seeded.get("estimate section") == 2 and result.seeded.get("estimate line") == 8
    assert result.seeded.get("work counted", 0) >= 18 and result.seeded.get("contract") == 1
    assert result.seeded.get("client bill") == 1 and result.seeded.get("client bill sent") == 1
    # A demo full of records (attendance with workers, expenses ...) resets again: the delete step clears the links
    # Postgres's cascades meet in the wrong order.
    again = await reset_demo(engine, database, result.organization_id, actor=actor, today=dt.date(2026, 11, 3))
    made.append(again.organization_id)
    assert again.failed == [] and again.people == 2
    result = again
    async with engine.connect() as conn:
        assert (await conn.execute(text("SELECT count(*) FROM organizations WHERE id = :o"), {"o": old_id})).scalar() == 0
        people = (await conn.execute(text("SELECT full_name, role, whatsapp_number FROM users WHERE organization_id = :o ORDER BY full_name"),
                                     {"o": result.organization_id})).all()
        assert [(p.full_name, p.role) for p in people] == [("Anil", "ADMIN"), ("Ravi", "SITE_ENGINEER")]
        digits = "".join(ch for ch in phone if ch.isdigit())
        assert digits in {"".join(ch for ch in (p.whatsapp_number or "") if ch.isdigit()) for p in people}
        settings = dict((await conn.execute(text("SELECT key, value FROM organization_settings WHERE organization_id = :o"),
                                            {"o": result.organization_id})).all())
        assert settings["demo_company"] is True and settings["assistant_mode"] == "api"
        assert "join_code" not in settings or settings["join_code"] != "OLD-1234"  # progress starts fresh
        sites = (await conn.execute(text("SELECT s.name FROM sites s JOIN projects p ON p.id = s.project_id WHERE p.organization_id = :o ORDER BY s.name"),
                                    {"o": result.organization_id})).scalars().all()
        assert sites == ["Annex", "Main block", "Tower A", "Tower B"]
        # Every delivery came before its use: no site's stock of anything goes below zero.
        negative = (await conn.execute(text(
            "SELECT count(*) FROM (SELECT site_id, material_id, sum(CASE WHEN movement_type = 'RECEIPT' THEN quantity ELSE -quantity END) AS q "
            "FROM material_movements WHERE organization_id = :o GROUP BY 1, 2) s WHERE q < 0"), {"o": result.organization_id})).scalar()
        assert negative == 0
        # WEB-85, the stories: an order with part still to come; a delivery at more than its order's rate; cement
        # under its minimum at Main block; the newest day's work left for the office to count.
        orders = (await conn.execute(text(
            "SELECT l.quantity, l.rate, COALESCE((SELECT SUM(r.quantity) FROM material_receipts r WHERE r.purchase_order_line_id = l.id), 0) AS came, "
            "(SELECT MAX(r.unit_cost) FROM material_receipts r WHERE r.purchase_order_line_id = l.id) AS top_rate "
            "FROM purchase_order_lines l JOIN purchase_orders o ON o.id = l.purchase_order_id WHERE o.organization_id = :o"),
            {"o": result.organization_id})).all()
        assert len(orders) == 2 and all(0 < x.came < x.quantity for x in orders), orders
        assert any(x.top_rate is not None and x.top_rate > x.rate for x in orders), "a delivery came at more than its order's rate"
        low = (await conn.execute(text(
            "SELECT count(*) FROM stock_levels l JOIN sites s ON s.id = l.site_id WHERE l.organization_id = :o AND s.name = 'Main block' "
            "AND l.min_qty > (SELECT COALESCE(SUM(CASE WHEN movement_type = 'RECEIPT' THEN quantity ELSE -quantity END), 0) "
            "FROM material_movements m WHERE m.site_id = l.site_id AND m.material_id = l.material_id)"), {"o": result.organization_id})).scalar()
        assert low == 1, "Main block's cement is under its minimum"
        audit = (await conn.execute(text("SELECT count(*) FROM admin_audit_log WHERE organization_id = :o AND action = 'company.demo_reset'"),
                                    {"o": result.organization_id})).scalar()
        assert audit == 1


async def test_guard_a_company_that_is_not_a_demo_is_refused_and_untouched(world) -> None:
    from admin.demo import DemoResetError, reset_demo
    from mesiri.domains.audit.actions import AuditActor

    engine, database, made = world
    org_id, _ = await _company(engine, demo=False)
    made.append(org_id)
    with pytest.raises(DemoResetError):
        await reset_demo(engine, database, org_id, actor=AuditActor(kind="platform_admin", label="Test admin"))
    async with engine.connect() as conn:
        assert (await conn.execute(text("SELECT count(*) FROM users WHERE organization_id = :o"), {"o": org_id})).scalar() == 2


async def test_deleting_a_company_with_records_removes_it_and_its_people(world) -> None:
    """The class the demo reset found: 'Delete Tenant' on a real company (records, workers, expenses) used to fail."""
    from admin.demo import reset_demo
    from mesiri.application.organizations.delete_company import delete_company
    from mesiri.domains.audit.actions import AuditActor

    engine, database, made = world
    org_id, phone = await _company(engine, demo=True)
    made.append(org_id)
    full = await reset_demo(engine, database, org_id, actor=AuditActor(kind="platform_admin", label="Test admin"),
                            today=dt.date(2026, 11, 2))
    async with engine.begin() as conn:
        await delete_company(conn, full.organization_id)
    async with engine.connect() as conn:
        assert (await conn.execute(text("SELECT count(*) FROM organizations WHERE id = :o"), {"o": full.organization_id})).scalar() == 0
        assert (await conn.execute(text("SELECT count(*) FROM users WHERE organization_id = :o"), {"o": full.organization_id})).scalar() == 0
        digits = "".join(ch for ch in phone if ch.isdigit())
        free = (await conn.execute(text("SELECT count(*) FROM users WHERE regexp_replace(whatsapp_number, '\\D', '', 'g') = :w"),
                                   {"w": digits})).scalar()
        assert free == 0  # the number can sign up again
