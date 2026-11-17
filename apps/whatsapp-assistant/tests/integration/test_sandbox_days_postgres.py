"""SS-74d: save points and Go back on a real database, through the whole app (guided-demo-plan.md 18.5, 18.12).

A sample company is made with the real seed, days are played, and going back must put back **every row exactly** as
the save point had it (not just the counts); going forth again replays the plan; "try today again" undoes what the
person did today; the save points after the day gone back to are gone; a real company is never touched.

Slow (the seed and a few days), so integration only.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from mesiri.application.learn import sandbox
from mesiri.application.learn import sandbox_days as sd
from mesiri.application.learn import sandbox_player as player
from mesiri.application.organizations.create_company import NewCompany, create_company
from mesiri.application.organizations.delete_company import delete_company
from mesiri.bootstrap.settings import Settings

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


async def _rows(engine, org) -> dict[str, list[str]]:
    """Every row of the company, per table, in a stable order (JSON has no row order)."""
    async with engine.connect() as conn:
        snap = await sd.snapshot(conn, org)
    return {t: sorted(json.dumps(r, sort_keys=True) for r in json.loads(v)) for t, v in snap.items()}


async def _counts(engine, org) -> dict[str, int]:
    return {t: len(r) for t, r in (await _rows(engine, org)).items()}


async def test_back_and_forth(world):
    app, engine, person = world
    opened = await sandbox.open_sandbox(engine, app, person, role="FINANCE")
    org = opened.organization_id
    async with engine.connect() as conn:
        assert [d for d, _ in await sd.days(conn, org)] == [0]  # day 0 saved when the sample was made
    at_zero = await _rows(engine, org)

    moved = await player.next_day(engine, app, person, role="FINANCE", days=2)
    assert moved.day == 2 and not moved.failed
    at_two = await _rows(engine, org)
    moved = await player.next_day(engine, app, person, role="FINANCE", days=2)
    assert moved.day == 4 and not moved.failed
    four_counts = await _counts(engine, org)
    clock = await player.clock(engine, person, "FINANCE")
    assert [g["day"] for g in clock.can_go_back_to] == [0, 1, 2, 3, 4]

    # Back to day 2: every row exactly as the save point had it, the date with it, days 3 and 4 gone.
    back = await player.go_back(engine, person, day=2, role="FINANCE")
    assert back.day == 2 and back.date == opened.today + dt.timedelta(days=2)
    assert await _rows(engine, org) == at_two
    async with engine.connect() as conn:
        today = (await conn.execute(text("SELECT sandbox_today FROM organizations WHERE id = :o"), {"o": org})).scalar()
        assert today == back.date
        assert [d for d, _ in await sd.days(conn, org)] == [0, 1, 2]
    assert back.for_you == (await player.clock(engine, person, "FINANCE")).for_you

    # Forth again: the same plan plays, so the company comes back to the same shape.
    again = await player.next_day(engine, app, person, role="FINANCE", days=2)
    assert again.day == 4 and not again.failed
    assert await _counts(engine, org) == four_counts

    # All the way back to the start.
    await player.go_back(engine, person, day=0, role=sandbox.OWNER)
    assert await _rows(engine, org) == at_zero


async def test_try_today_again_undoes_what_i_did_today(world):
    app, engine, person = world
    opened = await sandbox.open_sandbox(engine, app, person, role="FINANCE")
    org = opened.organization_id
    await player.next_day(engine, app, person, role="FINANCE", days=1)
    start_of_day = await _rows(engine, org)
    # Something changed today.
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE organization_settings SET value = '\"changed\"'::jsonb "
                                "WHERE organization_id = :o AND key = 'assistant_mode'"), {"o": org})
    assert await _rows(engine, org) != start_of_day
    await player.go_back(engine, person, day=1, role="FINANCE")
    assert await _rows(engine, org) == start_of_day


async def test_one_move_at_a_time_and_only_days_played(world):
    app, engine, person = world
    opened = await sandbox.open_sandbox(engine, app, person)
    org = opened.organization_id
    with pytest.raises(sandbox.SandboxError) as no_future:
        await player.go_back(engine, person, day=3)
    assert no_future.value.status == 422
    async with engine.connect() as conn:
        assert await sd.hold(conn, org)  # another Next day under way
        await conn.commit()
        try:
            for move in (player.next_day(engine, app, person), player.go_back(engine, person, day=0)):
                with pytest.raises(sandbox.SandboxError) as busy:
                    await move
                assert busy.value.status == 409
        finally:
            await sd.release(conn, org)
            await conn.commit()
    # Two at once from two tabs: one plays, the other is told to wait; nothing breaks.
    results = await asyncio.gather(player.next_day(engine, app, person), player.next_day(engine, app, person),
                                   return_exceptions=True)
    assert sorted(type(r).__name__ for r in results) == ["Moved", "SandboxError"]


async def test_a_real_company_is_never_saved_or_put_back(world):
    _app, engine, person = world
    async with engine.begin() as conn:
        for step in (sd.save(conn, person.organization_id, 0, dt.date.today()),
                     sd.restore(conn, person.organization_id, 0)):
            with pytest.raises(sd.NotASample):
                await step
