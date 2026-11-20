"""SS-74c: the planned simulation played on a real database, through the whole app (guided-demo-plan.md section 18).

A sample company is made with the real seed (``open_sandbox``), then ``next_day`` plays the plan
(application/learn/sample_plan.py) as each role's sandbox user through the app's own routes, in process: every entry
of every day to Green Villa's handover must save (nothing failed, nothing left waiting), and the person's own entries
must be left for them, ticked when they do them, and hold up what needs them when they don't.

Slow (the seed and 62 days: about 90 s), so integration only.
"""

from __future__ import annotations

import datetime as dt
import uuid

import httpx
import jwt
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from mesiri.application.learn import sample_plan, sandbox
from mesiri.application.learn import sandbox_player as player
from mesiri.application.organizations.create_company import NewCompany, create_company
from mesiri.application.organizations.delete_company import delete_company
from mesiri.bootstrap.settings import Settings
from mesiri.domains.identity.auth_service import ALGORITHM, SECRET_KEY

pytestmark = pytest.mark.integration


@pytest.fixture
async def world(monkeypatch):
    for key in ("WHATSAPP_VERIFY_TOKEN", "WHATSAPP_APP_SECRET", "WHATSAPP_ACCESS_TOKEN"):
        monkeypatch.setenv(key, "test")  # nothing is sent: the sample company has no phone numbers
    from runtime.lifecycle import create_app

    app = create_app()
    engine = create_async_engine(Settings().postgres.dsn())
    async with engine.begin() as conn:
        made = await create_company(conn, NewCompany(
            name="Acme Real Builders", owner_name="Asha Menon", owner_email=f"asha.{uuid.uuid4().hex}@acme.test",
            project_name="Real Tower", site_names=("Block 1",)))
    person = sandbox.RealPerson(made.owner_user_id, made.organization_id, "Asha Menon")
    async with app.router.lifespan_context(app):
        yield app, engine, person
    async with engine.begin() as conn:
        for (org,) in (await conn.execute(text("SELECT id FROM organizations WHERE sandbox_user_id = :u"),
                                          {"u": made.owner_user_id})).all():
            await delete_company(conn, org)
        await delete_company(conn, made.organization_id)
    await engine.dispose()


async def test_the_whole_plan_plays_to_handover(world):
    app, engine, person = world
    opened = await sandbox.open_sandbox(engine, app, person)
    assert not opened.failed and opened.today.weekday() == 5
    # As the owner, landing only on days the owner has nothing to do until the last.
    for days in (1, 5, 6, 6, 4, 5, 6, 6, 6, 5, 5, 6, 1):
        moved = await player.next_day(engine, app, person, role="ADMIN", days=days)
        assert not moved.failed, moved.failed[:3]
    assert moved.day == sample_plan.plan().last_day and not moved.waiting
    # The last day is the owner's: Green Villa's final running bill, then the handover (project bible D2).
    assert [f.kind for f in moved.for_you] == ["ra_bill", "stage"]
    async with engine.connect() as conn:
        today = (await conn.execute(text("SELECT sandbox_today FROM organizations WHERE id = :o"),
                                    {"o": opened.organization_id})).scalar()
        played = (await conn.execute(text("SELECT count(*) FROM sandbox_played WHERE organization_id = :o "
                                          "AND status = 'played' AND entry_id NOT LIKE 'day:%'"),
                                     {"o": opened.organization_id})).scalar()
    assert today == opened.today + dt.timedelta(days=moved.day)
    assert played == len(sample_plan.plan().entries) - len(moved.for_you)
    assert jwt.decode(moved.token, SECRET_KEY, algorithms=[ALGORITHM])["today"] == today.isoformat()
    with pytest.raises(sandbox.SandboxError):
        await player.next_day(engine, app, person, role="ADMIN", days=1)  # handed over: start over to play again


async def test_my_entries_wait_for_me_and_are_ticked_when_i_do_them(world):
    app, engine, person = world
    await sandbox.open_sandbox(engine, app, person, role="FINANCE")
    moved = await player.next_day(engine, app, person, role="FINANCE", days=7)  # day 7, a Saturday: pay day
    mine = {f.kind for f in moved.for_you}
    assert {"wage_pay", "supplier_bill"} <= mine
    # Meera pays Green Villa's wages herself, on the dashboard's route, with the new token.
    async with engine.connect() as conn:
        org = (await conn.execute(text("SELECT id FROM organizations WHERE sandbox_user_id = :u"),
                                  {"u": person.user_id})).scalar()
        sheet = (await conn.execute(text(
            "SELECT w.id FROM wage_sheets w JOIN projects p ON p.id = w.project_id WHERE w.organization_id = :o "
            "AND p.name = 'Green Villa' AND w.status = 'approved' ORDER BY w.period_to DESC LIMIT 1"), {"o": org})).scalar()
        account = (await conn.execute(text("SELECT id FROM money_accounts WHERE organization_id = :o LIMIT 1"),
                                      {"o": org})).scalar()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        paid = await client.post(f"/labour/wage-sheets/{sheet}/pay", json={"account_id": str(account)},
                                 headers={"Authorization": f"Bearer {moved.token}"})
    assert paid.status_code == 200, paid.text
    left = await player.clock(engine, person, "FINANCE")
    wages = [f for f in left.for_you if f.kind == "wage_pay"]
    assert len(wages) == 1 and "Lake View" in wages[0].what  # only the sheet she paid is ticked
    # Left undone, the rest stay hers the next day.
    nxt = await player.next_day(engine, app, person, role="FINANCE", days=1)
    assert any(f.kind == "supplier_bill" and f.day == 7 for f in nxt.for_you)


async def test_what_i_did_not_do_holds_up_what_needs_it(world):
    app, engine, person = world
    await sandbox.open_sandbox(engine, app, person, role="SITE_ENGINEER")
    moved = await player.next_day(engine, app, person, role="SITE_ENGINEER", days=2)
    assert any(f.kind == "request" for f in moved.for_you)  # Ravi's requests are his to raise
    moved = await player.next_day(engine, app, person, role="SITE_ENGINEER", days=1)
    # He didn't ask, so Anil has nothing to order: the orders wait (and so will the lorries).
    assert any(w["what"].startswith("Order ") for w in moved.waiting)
    with pytest.raises(sandbox.SandboxError):
        await player.next_day(engine, app, person, role="SITE_ENGINEER", days=player.MAX_DAYS + 1)


async def test_the_month_end_count_plays_on_the_real_api(world):
    """LRN-F23: on day 16 Ravi's count of the Main block is saved through the stock-count routes, 3 bags short
    (wastage); approving it is the owner's own entry that day, left for the person playing the owner."""
    app, engine, person = world
    opened = await sandbox.open_sandbox(engine, app, person)
    for days in (1, 5, 6, 4):  # to day 16
        moved = await player.next_day(engine, app, person, role="ADMIN", days=days)
        assert not moved.failed, moved.failed[:3]
    async with engine.connect() as conn:
        counts = (await conn.execute(text(
            "SELECT c.status, l.book_qty, l.counted_qty, l.reason FROM stock_counts c "
            "JOIN stock_count_lines l ON l.count_id = c.id JOIN materials_catalog m ON m.id = l.material_id "
            "JOIN sites s ON s.id = c.site_id WHERE c.organization_id = :o AND s.name = 'Main block' "
            "AND m.name ILIKE 'cement%' AND l.counted_qty IS NOT NULL"), {"o": opened.organization_id})).mappings().all()
    assert len(counts) == 1 and counts[0]["status"] == "open" and counts[0]["reason"] == "wastage"
    assert float(counts[0]["book_qty"]) - float(counts[0]["counted_qty"]) == 3
    assert "count_approve" in {f.kind for f in moved.for_you}
