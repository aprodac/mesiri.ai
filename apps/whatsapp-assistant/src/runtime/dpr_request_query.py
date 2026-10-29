"""A stored DPR's status and PDF ("is the day's report confirmed, and where is it?").

Read-only, plain async methods so a node never queries a repository itself.
What a day HOLDS is not read here: that is Day Facts (``runtime/day_facts.py``,
``DayFacts.site_day``), the one reader of a site's day; "send me the report"
(``runtime/agent/report_entry.py``) asks this service only whether a confirmed
PDF exists. ``report_date`` is the caller's, in the project's zone.
"""

from __future__ import annotations

import datetime
import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mesiri.infrastructure.postgres.database import PostgresDatabase


class DprRequestQueryService:
    def __init__(self, db: PostgresDatabase) -> None:
        self._db = db

    async def find_report(
        self,
        *,
        organization_id: str,
        project_id: str | None,
        site_id: str | None,
        report_date: datetime.date,
    ) -> dict[str, Any]:
        """Status of `report_date`'s DPR for this scope. `site_id` set ->
        the SITE-level report; `site_id` None (project_id still required)
        -> the PROJECT-level roll-up (see backend's dpr.py module docstring,
        ADR-D9/P8) -- added for runtime/project_auto_dpr.py, which has no
        single site to ask about, only the whole project's own auto-DPR
        setting. `report_date` is the CALLER's responsibility to resolve
        against the relevant timezone (see runtime/inbound_journey.py's
        `today_for` for the per-user case, application/automations/
        scheduling.py's `local_now` for the per-project one) -- this
        service does no timezone math of its own, same split
        labour_query_service.py's `resolve_date_range` makes. Always
        returns a dict (never None) -- `status` is one of "not_generated"
        (no daily_reports row for that date yet), "pending_render" (a
        version exists but rendered_object_key is still NULL), or "ready"
        (a PDF is stored -- `object_key`/`code` are set). Request [58]: a
        version nobody has confirmed yet (`DRAFT`/`IN_REVIEW`) with no PDF is
        "pending_confirmation", not "pending_render" -- waiting for a render
        that is not coming is a different thing to tell the sender. Both carry
        `update_count`, the updates the report holds; `confirmed` says whether
        the day is signed off."""
        if not project_id:
            return {"status": "not_generated", "object_key": None, "code": None}

        try:
            org_id = uuid.UUID(organization_id)
            proj_uuid = uuid.UUID(project_id)
            site_uuid = uuid.UUID(site_id) if site_id else None
        except (TypeError, ValueError):
            return {"status": "not_generated", "object_key": None, "code": None}

        query = _report_query(
            organization_id=org_id,
            project_id=proj_uuid,
            site_id=site_uuid,
            report_date=report_date,
        )

        async with self._db.transaction() as conn:
            row = (await conn.execute(query)).mappings().first()

        if row is None:
            return {"status": "not_generated", "object_key": None, "code": None}
        # Signed off only when approved or published: a day still collecting
        # (NEEDS_DETAILS, READY, 0466) is not "being prepared" -- it waits on
        # the site (round 3b, 21 Oct: "ask again in a few minutes" for a day
        # that was missing its work done).
        confirmed = row["report_status"] in ("APPROVED", "PUBLISHED")
        found = {
            "code": row["code"],
            "confirmed": confirmed,
            "update_count": int(row["update_count"] or 0),
            "missing": [str(m) for m in (row["missing"] or []) if m],
        }
        if row["rendered_object_key"]:
            return {"status": "ready", "object_key": row["rendered_object_key"], **found}
        status = "pending_render" if confirmed else "pending_confirmation"
        return {"status": status, "object_key": None, **found}


#: Mirrors the `daily_report_level` Postgres enum (migration 0440). The bare
#: sa.column("level") is untyped, so `level == "SITE"` binds as VARCHAR and
#: Postgres has no `daily_report_level = varchar` operator: every real lookup
#: failed, which "send me today's report" reported as "can't look up today's
#: report". Typed here, same fix as runtime/activity_query.py.
def _report_query(
    *,
    organization_id: uuid.UUID,
    project_id: uuid.UUID,
    site_id: uuid.UUID | None,
    report_date: datetime.date,
):  # type: ignore[no-untyped-def]
    import sqlalchemy as sa
    from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM

    level_type = PG_ENUM("SITE", "PROJECT", name="daily_report_level", create_type=False)
    status_type = PG_ENUM(
        "DRAFT",
        "IN_REVIEW",
        "APPROVED",
        "PUBLISHED",
        "NOT_REPORTED",
        name="daily_report_status",
        create_type=False,
    )
    daily_reports = sa.table(
        "daily_reports",
        sa.column("id"),
        sa.column("organization_id"),
        sa.column("project_id"),
        sa.column("site_id"),
        sa.column("report_date"),
        sa.column("level", level_type),
        sa.column("code"),
        sa.column("current_version_id"),
        sa.column("status", status_type),
        sa.column("missing_sections"),
    )
    daily_report_versions = sa.table(
        "daily_report_versions",
        sa.column("id"),
        sa.column("rendered_object_key"),
        sa.column("payload"),
    )

    scope_clause = (
        sa.and_(daily_reports.c.site_id == site_id, daily_reports.c.level == "SITE")
        if site_id is not None
        else sa.and_(daily_reports.c.site_id.is_(None), daily_reports.c.level == "PROJECT")
    )
    return (
        sa.select(
            daily_reports.c.code,
            sa.cast(daily_reports.c.status, sa.Text).label("report_status"),
            daily_report_versions.c.rendered_object_key,
            sa.cast(
                sa.literal_column("daily_report_versions.payload ->> 'activity_count'"), sa.Integer
            ).label("update_count"),
            sa.literal_column("daily_reports.missing_sections -> 'blocking'").label("missing"),
        )
        .select_from(
            daily_reports.join(
                daily_report_versions,
                daily_reports.c.current_version_id == daily_report_versions.c.id,
                isouter=True,
            )
        )
        .where(
            daily_reports.c.organization_id == organization_id,
            daily_reports.c.project_id == project_id,
            daily_reports.c.report_date == report_date,
            scope_clause,
        )
        .limit(1)
    )
