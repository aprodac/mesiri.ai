"""Request 143 against a real database: the DPR assembly and Day Facts put a
timestamped entry on the PROJECT's day (``mesiri.application.dpr.project_day``),
never the UTC one.

Before: a progress update or an issue saved at 00:30 IST (19:00 UTC the day
before) sat on the previous day in the report, while its activity was on the
right one (ADR draft-per-message §19.4).

    pytest apps/whatsapp-assistant/tests/integration/test_report_day_postgres.py -m integration
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from sqlalchemy import text

from mesiri.application.organizations.create_company import NewCompany, create_company
from mesiri.bootstrap.settings import Settings
from mesiri.infrastructure.postgres.database import PostgresDatabase
from runtime.day_facts import DayFacts

pytestmark = pytest.mark.integration

STARTED = dt.date(2026, 10, 21)
IST_DAY = dt.date(2026, 10, 22)
#: 00:30 IST on 22 Oct is 19:00 UTC on the 21st.
AFTER_MIDNIGHT_IST = dt.datetime(2026, 10, 21, 19, 0, tzinfo=dt.UTC)


async def test_an_entry_after_midnight_ist_is_on_the_ist_day_of_the_report():
    db = PostgresDatabase(Settings().postgres)
    await db.connect()
    async with db.transaction() as conn:
        created = await create_company(
            conn,
            NewCompany(
                name=f"Report day {uuid.uuid4().hex[:6]}",
                owner_name="Owner",
                owner_phone=f"9197{uuid.uuid4().int % 10**8:08d}",
                project_name="Green Villa",
                site_names=("Kakkanad",),
            ),
            now=dt.datetime(2026, 10, 20, 6, tzinfo=dt.UTC),
        )
        org, project, site = created.organization_id, created.project_id, created.sites[0].site_id
        await conn.execute(
            text("UPDATE organizations SET timezone = 'Asia/Kolkata' WHERE id = :o"), {"o": org}
        )
        activity = uuid.uuid4()
        await conn.execute(
            text(
                "INSERT INTO activities (id, organization_id, project_id, site_id, activity_date, work_type, narrative)"
                " VALUES (:id, :org, :p, :s, :d, 'tiling', 'Tiling, ground floor: 70%')"
            ),
            {"id": activity, "org": org, "p": project, "s": site, "d": STARTED},
        )
        await conn.execute(
            text(
                "INSERT INTO progress_updates (id, activity_id, occurred_at, update_kind, narrative)"
                " VALUES (:id, :a, :at, 'PROGRESS', 'Tiling, ground floor: 82%')"
            ),
            {"id": uuid.uuid4(), "a": activity, "at": AFTER_MIDNIGHT_IST},
        )
        await conn.execute(
            text(
                "INSERT INTO site_issues (id, organization_id, project_id, site_id, issue_type, narrative, occurred_at)"
                " VALUES (:id, :org, :p, :s, 'EQUIPMENT_BREAKDOWN', 'mixer breakdown', :at)"
            ),
            {"id": uuid.uuid4(), "org": org, "p": project, "s": site, "at": AFTER_MIDNIGHT_IST},
        )
    try:
        facts = DayFacts(db).for_turn()
        ist = await facts.site_day(organization_id=org, project_id=project, site_id=site, day=IST_DAY)
        before = await facts.site_day(organization_id=org, project_id=project, site_id=site, day=STARTED)

        works = [a.get("work_type") for a in ist.payload.get("activities") or []]
        assert "tiling" in works  # the 82% update, continued on the IST day
        assert [i.get("narrative") for i in ist.payload.get("issues") or []] == ["mixer breakdown"]
        assert not before.payload.get("issues")  # not on the UTC day any more
        assert ist.lines and not ist.empty
    finally:
        async with db.transaction() as conn:
            await conn.execute(text("DELETE FROM organizations WHERE id = :o"), {"o": org})
        await db.disconnect()
