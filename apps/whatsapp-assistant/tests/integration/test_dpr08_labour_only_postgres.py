"""DPR-08: a site that sent only workers and a delivery is "not confirmed yet", not "not reported"."""

from __future__ import annotations

import datetime as dt
import json
import uuid

import pytest
from sqlalchemy import text

from mesiri.application.organizations.create_company import NewCompany, create_company
from runtime.project_auto_dpr import _unconfirmed_updates

pytestmark = pytest.mark.integration


async def test_dpr08_workers_and_materials_only_count_as_updates():
    from sqlalchemy.ext.asyncio import create_async_engine

    from mesiri.bootstrap.settings import Settings

    engine = create_async_engine(Settings().postgres.dsn())
    async with engine.connect() as conn:
        tx = await conn.begin()
        c = await create_company(conn, NewCompany(
            name="D8", owner_name="O", owner_phone=f"+91 9{uuid.uuid4().int % 10**9:09d}",
            project_name="P", site_name="Site 2"))
        day = dt.date(2026, 10, 24)
        rid, vid = uuid.uuid4(), uuid.uuid4()
        await conn.execute(text(
            "INSERT INTO daily_reports (id, organization_id, project_id, site_id, level, report_date, code, status)"
            " VALUES (:i, :o, :p, :s, 'SITE', :d, 'X', 'DRAFT')"),
            {"i": rid, "o": c.organization_id, "p": c.project_id, "s": c.site_id, "d": day})
        payload = {"activity_count": 0, "labour": {"headcount": 4}, "materials": [{"material_name": "Cement"}], "issues": []}
        await conn.execute(text(
            "INSERT INTO daily_report_versions (id, daily_report_id, version_no, payload)"
            " VALUES (:v, :r, 1, CAST(:pl AS jsonb))"), {"v": vid, "r": rid, "pl": json.dumps(payload)})
        await conn.execute(text("UPDATE daily_reports SET current_version_id = :v WHERE id = :r"), {"v": vid, "r": rid})
        found = await _unconfirmed_updates(conn, organization_id=c.organization_id, project_id=c.project_id, report_date=day)
        assert found == {"Site 2": 2}  # workers + one material; not "not reported"
        await tx.rollback()
    await engine.dispose()
