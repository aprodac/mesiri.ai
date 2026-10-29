"""Request 142 (B): the save journal on a real database (migration 0493).

Run with a live database:
    pytest apps/whatsapp-assistant/tests/integration/test_save_journal_postgres.py -m integration
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from sqlalchemy import text

from mesiri.application.organizations.create_company import NewCompany, create_company
from mesiri.bootstrap.settings import Settings
from mesiri.infrastructure.postgres.database import PostgresDatabase
from runtime.agent.journal import JournalEntry, JournalFact, PostgresJournalStore

pytestmark = pytest.mark.integration


@pytest.fixture
async def companies():
    db = PostgresDatabase(Settings().postgres)
    await db.connect()
    made = []
    async with db.transaction() as conn:
        for name in ("Journal A", "Journal B"):
            made.append(
                await create_company(
                    conn,
                    NewCompany(
                        name=f"{name} {uuid.uuid4().hex[:6]}",
                        owner_name="Owner",
                        owner_phone=f"9197{uuid.uuid4().int % 10**8:08d}",
                        project_name="Green Villa",
                        site_names=("Green Villa",),
                    ),
                    now=dt.datetime(2026, 10, 29, 6, tzinfo=dt.UTC),
                )
            )
    yield db, made
    async with db.transaction() as conn:
        for c in made:
            await conn.execute(text("DELETE FROM save_journal WHERE organization_id = :o"), {"o": c.organization_id})


def _entry(company, **kw) -> JournalEntry:
    return JournalEntry(
        organization_id=str(company.organization_id),
        user_id=str(company.owner_user_id),
        draft_id=uuid.uuid4().hex,
        site_id=str(company.sites[0].site_id),
        site="Green Villa",
        day="2026-10-29",
        facts=[
            JournalFact("labour_entry", str(uuid.uuid4()), "save_labour", {"workers": [{"trade": "mason", "headcount": 3}]}, "3 workers (3 mason)"),
            JournalFact("material_receipt", str(uuid.uuid4()), "save_material_receipt", {"material": "cement"}, "Cement in: 50 bags"),
        ],
        **kw,
    )


async def test_record_read_undo_and_isolation(companies):
    db, (a, b) = companies
    store = PostgresJournalStore(db)
    mine = _entry(a)
    await store.record(mine)

    got = await store.recent(mine.organization_id, mine.user_id)
    assert [e.id for e in got] == [mine.id]
    assert got[0].site == "Green Villa" and got[0].day == "2026-10-29"
    assert [f.tool for f in got[0].facts] == ["save_labour", "save_material_receipt"]
    assert got[0].facts[0].args == {"workers": [{"trade": "mason", "headcount": 3}]}

    # another company's sender, and a stranger in the same company, see nothing and change nothing
    assert await store.recent(str(b.organization_id), str(b.owner_user_id)) == []
    assert await store.get(mine.id, str(b.organization_id), str(b.owner_user_id)) is None
    assert await store.get(mine.id, mine.organization_id, str(uuid.uuid4())) is None
    await store.mark_undone(mine.id, str(b.organization_id), str(b.owner_user_id), [f.fact_id for f in mine.facts])
    assert all(not f.undone for f in (await store.get(mine.id, mine.organization_id, mine.user_id)).facts)

    # undoing one fact leaves the entry; undoing the last one takes it out of "recent"
    await store.mark_undone(mine.id, mine.organization_id, mine.user_id, [mine.facts[0].fact_id])
    entry = await store.get(mine.id, mine.organization_id, mine.user_id)
    assert [f.undone for f in entry.facts] == [True, False]
    assert [e.id for e in await store.recent(mine.organization_id, mine.user_id)] == [mine.id]
    await store.mark_undone(mine.id, mine.organization_id, mine.user_id, [mine.facts[1].fact_id])
    assert await store.recent(mine.organization_id, mine.user_id) == []
    async with db.transaction() as conn:
        done = (await conn.execute(text("SELECT undone_at FROM save_journal WHERE id = :i"), {"i": uuid.UUID(mine.id)})).scalar()
    assert done is not None
