"""Open-activity lookup for the Activity Continuation workflow (wiring layer only).

Same shape and justification as runtime/vendor_query.py: adapts a plain read
query into an async method the inbound journey can call before the graph
runs (a node must never query a repository itself -- see
workflows/runtime.py). Never opens a write transaction.

Implements the "find today's open activity for this reporter/site" lookup
docs/execution/DAILY_REPORTING_PLAN.md's P10/§1B.2 describe: a continuation
message ("finished plastering", "completed another 40 sqm") should never
have to name which activity it means when there is exactly one plausible
answer.

Scoped by reporter AND site, not just project: two engineers on the same
site must never have their activities conflated, and neither should two
sites on the same project.

`find_open_activity` (singular, most-recent-wins) still backs #2 Batch
Media's photo-evidence attach (runtime/dependencies.py) -- there is no
message text to compare a photo against, so recency really is the best
available signal there, and a photo landing on the wrong-but-recent
activity is a low-stakes mistake. `find_open_activities` (plural) backs the
create-vs-continue resolver instead (workflows/site_update/matching.py):
when there IS message text, recency alone is not enough (see
docs/execution/ACTIVITY_RESOLUTION_AND_CORRECTION_PLAN.md's F1) -- the
resolver needs every open candidate, not just the newest, to compare
against what the message actually describes.

Deliberately NOT filtered by "today's date": an IN_PROGRESS activity that
spans past midnight (a late finish, or simply never marked complete) must
still be continuable the next message regardless of the server's calendar
date -- the same class of bug canonicalization/occurred_date.py's docstring
describes for a *stated* date applies here to an *inferred* one. "Open"
(status) is the only signal that matters; recency (`updated_at`) only breaks
ties when more than one activity is open at once.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM

from runtime.day_facts import open_work_sql

if TYPE_CHECKING:
    from mesiri.infrastructure.postgres.database import PostgresDatabase

#: Activities in either of these states are still "open" for continuation.
#: STOPPED is where a PAUSED update lands too -- the activity_status enum
#: (migrations/0430_progress_add_activities_and_updates.py) has no distinct
#: "paused" value, so progress_execution.py's _STATUS_BY_KIND maps PAUSED ->
#: STOPPED, and "resumed after rain" must still be able to find that activity
#: to reopen it. Only COMPLETED is truly terminal and excluded here -- a
#: message about finished work with no open activity falls through to
#: activity_creation instead (see workflows/site_update/'s handling of
#: no_open_activity).
_OPEN_STATUSES = ("PLANNED", "IN_PROGRESS", "STOPPED")

#: Mirrors the `activity_status` Postgres enum from migrations/versions/
#: 0430_progress_add_activities_and_updates.py. sa.column("status") alone is
#: untyped, so .in_(_OPEN_STATUSES) would bind as VARCHAR and Postgres has no
#: `activity_status = varchar` operator -- create_type=False since the type
#: already exists in the database.
_ACTIVITY_STATUS_TYPE = PG_ENUM(
    "PLANNED", "IN_PROGRESS", "COMPLETED", "STOPPED", name="activity_status", create_type=False
)


class ActivityQueryService:
    def __init__(self, db: PostgresDatabase) -> None:
        self._db = db

    async def find_open_activity(
        self,
        *,
        organization_id: str,
        site_id: str | None,
        reported_by_user_id: str | None,
    ) -> dict[str, Any] | None:
        """The open activity for this reporter on this site, if exactly (or
        most plausibly) one exists. None when there is nothing to continue --
        a normal, common outcome, not a failure."""
        if not site_id or not reported_by_user_id:
            return None

        import sqlalchemy as sa

        try:
            org_id = uuid.UUID(organization_id)
            site_uuid = uuid.UUID(site_id)
            reporter_uuid = uuid.UUID(reported_by_user_id)
        except (TypeError, ValueError):
            return None

        activities = sa.table(
            "activities",
            sa.column("id"),
            sa.column("organization_id"),
            sa.column("site_id"),
            sa.column("reported_by_user_id"),
            sa.column("status", _ACTIVITY_STATUS_TYPE),
            sa.column("work_type"),
            sa.column("narrative"),
            sa.column("deleted_at"),
            sa.column("updated_at"),
        )

        query = (
            sa.select(
                activities.c.id,
                activities.c.work_type,
                activities.c.narrative,
                activities.c.status,
            )
            .where(
                activities.c.organization_id == org_id,
                activities.c.site_id == site_uuid,
                activities.c.reported_by_user_id == reporter_uuid,
                activities.c.status.in_(_OPEN_STATUSES),
                activities.c.deleted_at.is_(None),
                sa.text(open_work_sql("activities.id")),
            )
            .order_by(activities.c.updated_at.desc())
            .limit(1)
        )

        async with self._db.transaction() as conn:
            row = (await conn.execute(query)).mappings().first()

        if row is None:
            return None
        return {
            "activity_id": str(row["id"]),
            "work_type": row["work_type"],
            "narrative": row["narrative"],
            "status": row["status"],
        }

    async def find_open_activities(
        self,
        *,
        organization_id: str,
        site_id: str | None,
        reported_by_user_id: str | None,
        limit: int = 50,
        site_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Every open activity for this reporter on this site, most recently
        updated first. Empty list when there is nothing open -- a normal,
        common outcome (e.g. the first report of the day), not a failure.

        `limit` is a sanity cap, not a real-world expectation (WRK-04: it was
        10, and a site running more open jobs than that lost the rest).
        ``site_ids`` (WRK-05): the sender's open work across several sites, when
        none is chosen yet; each row then says which site it is at."""
        if (not site_id and not site_ids) or not reported_by_user_id:
            return []

        import sqlalchemy as sa

        try:
            org_id = uuid.UUID(organization_id)
            site_uuid = uuid.UUID(site_id) if site_id else None
            many = [uuid.UUID(x) for x in site_ids or []]
            reporter_uuid = uuid.UUID(reported_by_user_id)
        except (TypeError, ValueError):
            return []

        activities = sa.table(
            "activities",
            sa.column("id"),
            sa.column("organization_id"),
            sa.column("site_id"),
            sa.column("reported_by_user_id"),
            sa.column("status", _ACTIVITY_STATUS_TYPE),
            sa.column("work_type"),
            sa.column("narrative"),
            sa.column("deleted_at"),
            sa.column("updated_at"),
        )

        query = (
            sa.select(
                activities.c.id,
                activities.c.site_id,
                activities.c.work_type,
                activities.c.narrative,
                activities.c.status,
            )
            .where(
                activities.c.organization_id == org_id,
                activities.c.site_id == site_uuid if site_uuid is not None else activities.c.site_id.in_(many),
                activities.c.reported_by_user_id == reporter_uuid,
                activities.c.status.in_(_OPEN_STATUSES),
                activities.c.deleted_at.is_(None),
                sa.text(open_work_sql("activities.id")),
            )
            .order_by(activities.c.updated_at.desc())
            .limit(limit)
        )

        async with self._db.transaction() as conn:
            rows = (await conn.execute(query)).mappings().all()

        return [
            {
                "activity_id": str(row["id"]),
                "site_id": str(row["site_id"]),
                "work_type": row["work_type"],
                "narrative": row["narrative"],
                "status": row["status"],
            }
            for row in rows
        ]

    async def get_activity_if_open(
        self, *, organization_id: str, activity_id: str
    ) -> dict[str, Any] | None:
        """Revalidate a *remembered* activity_id (memory/conversation_scope.py's
        CurrentActivityStore is a hint, never authoritative -- see that
        module's docstring) against the real row before a continuation
        message is allowed to target it. None whenever the id is stale: the
        activity was completed/deleted since it was remembered, or never
        belonged to this organization at all."""
        if not activity_id:
            return None

        import sqlalchemy as sa

        try:
            org_id = uuid.UUID(organization_id)
            act_id = uuid.UUID(activity_id)
        except (TypeError, ValueError):
            return None

        activities = sa.table(
            "activities",
            sa.column("id"),
            sa.column("organization_id"),
            sa.column("status", _ACTIVITY_STATUS_TYPE),
            sa.column("work_type"),
            sa.column("narrative"),
            sa.column("deleted_at"),
        )

        query = sa.select(
            activities.c.id, activities.c.work_type, activities.c.narrative, activities.c.status
        ).where(
            activities.c.id == act_id,
            activities.c.organization_id == org_id,
            activities.c.status.in_(_OPEN_STATUSES),
            activities.c.deleted_at.is_(None),
            sa.text(open_work_sql("activities.id")),
        )

        async with self._db.transaction() as conn:
            row = (await conn.execute(query)).mappings().first()

        if row is None:
            return None
        return {
            "activity_id": str(row["id"]),
            "work_type": row["work_type"],
            "narrative": row["narrative"],
            "status": row["status"],
        }

    async def find_activity_for_photos(
        self,
        *,
        organization_id: str,
        reported_by_user_id: str | None,
        site_ids: list[str],
        recent_hours: int = 48,
    ) -> dict[str, Any] | None:
        """PHO-01: the activity a "Site Update" photo belongs to. The sender's
        open work at those sites first (most recently touched), else the work
        they reported in the last ``recent_hours`` even if it is finished --
        "finished plastering", then its photos. None when they have reported
        nothing to attach to."""
        import sqlalchemy as sa

        if not reported_by_user_id or not site_ids:
            return None
        try:
            org_id = uuid.UUID(organization_id)
            reporter = uuid.UUID(reported_by_user_id)
            sites = [uuid.UUID(s) for s in site_ids]
        except (TypeError, ValueError):
            return None
        async with self._db.transaction() as conn:
            row = (
                await conn.execute(
                    sa.text(
                        "SELECT id, site_id, work_type, narrative, status::text AS status FROM activities"
                        " WHERE organization_id = :org AND reported_by_user_id = :user"
                        "   AND site_id = ANY(:sites) AND deleted_at IS NULL"
                        "   AND (status::text = ANY(:open)"
                        "        OR updated_at >= now() - make_interval(hours => :hours))"
                        " ORDER BY (status::text = ANY(:open)) DESC, updated_at DESC LIMIT 1"
                    ),
                    {"org": org_id, "user": reporter, "sites": sites, "open": list(_OPEN_STATUSES),
                     "hours": recent_hours},
                )
            ).mappings().first()
        if row is None:
            return None
        return {
            "activity_id": str(row["id"]),
            "site_id": str(row["site_id"]),
            "work_type": row["work_type"],
            "narrative": row["narrative"],
            "status": row["status"],
        }
