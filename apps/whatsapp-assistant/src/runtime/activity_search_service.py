"""Progress/activity read service for the activity.query workflow (#17
Search / Ask Mesiri).

Same shape and justification as runtime/labour_query_service.py: a plain
async method the assistant can call, reading already-saved activities and
open site issues so a node never queries a repository itself (see
workflows/runtime.py). Never opens a write transaction.

Answers "what did I log today?", "what happened on site X yesterday?", "any
open issues on site Y?" -- the questions a supervisor asks about work
already recorded, complementing labour_query (attendance) and expense_query
(spending) for the Daily Reporting module's own records.

**Scope is not optional.** Every read is filtered by organization, and by
the caller's current project/site the same way labour_query is -- a search
that leaked across projects would leak what is happening on someone else's
site.

Open issues are NOT date-scoped: a blocker raised three days ago that is
still open is still relevant today, unlike an activity log entry which is
inherently a record of a specific day.
"""

from __future__ import annotations

import datetime
import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM

if TYPE_CHECKING:
    from mesiri.infrastructure.postgres.database import PostgresDatabase

#: Individual rows fetched per category. The reply node further caps what it
#: displays (_MAX_ENTRIES_SHOWN); this is the ceiling on what is even read
#: from the database for one answer.
_MAX_ROWS = 20

#: Mirror the `activity_status`/`site_issue_status` Postgres enums from
#: migrations/versions/0430_progress_add_activities_and_updates.py. An
#: untyped sa.column("status") binds string literals as VARCHAR, and Postgres
#: has no `<enum> = varchar` operator -- create_type=False since both types
#: already exist in the database (see runtime/activity_query.py's identical
#: fix for the same failure mode).
_ACTIVITY_STATUS_TYPE = PG_ENUM(
    "PLANNED", "IN_PROGRESS", "COMPLETED", "STOPPED", name="activity_status", create_type=False
)
_SITE_ISSUE_STATUS_TYPE = PG_ENUM(
    "OPEN",
    "ACKNOWLEDGED",
    "RESOLVED",
    "WONT_FIX",
    # Added by migration 0460 -- a withdrawn report. This mirror must list
    # every value the database type has, or a comparison against a CANCELLED
    # row binds as an unknown label.
    "CANCELLED",
    name="site_issue_status",
    create_type=False,
)


class ActivitySearchService:
    def __init__(self, db: PostgresDatabase) -> None:
        self._db = db

    async def search(
        self,
        *,
        organization_id: str,
        project_id: str | None,
        site_id: str | None,
        start_date: datetime.date,
        end_date: datetime.date,
        work_type: str | None = None,
        include_unsaved: bool = False,
    ) -> dict[str, Any]:
        """Activities logged over [start_date, end_date] plus currently open
        site issues in scope.

        WA-77 (Alan, 25 Oct): what was saved; an entry still waiting for its
        Save is left out. `include_unsaved` keeps it, for the agent's own
        picture of today (so it never logs the same thing twice).

        Returns a plain dict rather than a domain object because the only
        consumer is the reply node, which formats it -- the same choice
        labour_query's seeding makes.
        """
        import sqlalchemy as sa

        try:
            org_id = uuid.UUID(organization_id)
        except (TypeError, ValueError):
            return _empty_results()

        proj_uuid: uuid.UUID | None = None
        if project_id:
            try:
                proj_uuid = uuid.UUID(project_id)
            except (TypeError, ValueError):
                proj_uuid = None
        site_uuid: uuid.UUID | None = None
        if site_id:
            try:
                site_uuid = uuid.UUID(site_id)
            except (TypeError, ValueError):
                site_uuid = None

        activities = sa.table(
            "activities",
            sa.column("id"),
            sa.column("organization_id"),
            sa.column("project_id"),
            sa.column("site_id"),
            sa.column("work_type"),
            sa.column("narrative"),
            sa.column("status", _ACTIVITY_STATUS_TYPE),
            sa.column("activity_date"),
            sa.column("deleted_at"),
            sa.column("updated_at"),
        )
        site_issues = sa.table(
            "site_issues",
            sa.column("id"),
            sa.column("organization_id"),
            sa.column("project_id"),
            sa.column("site_id"),
            sa.column("issue_type"),
            sa.column("severity"),
            sa.column("narrative"),
            sa.column("status", _SITE_ISSUE_STATUS_TYPE),
            sa.column("occurred_at"),
        )

        # WRK-01: work started earlier that has an update in the period is
        # part of the period's log, as it is of the day's DPR.
        updates = sa.table(
            "progress_updates",
            sa.column("activity_id"),
            sa.column("occurred_at", sa.DateTime(timezone=True)),
            sa.column("deleted_at"),
        )
        updated_in_period = sa.exists().where(
            updates.c.activity_id == activities.c.id,
            updates.c.deleted_at.is_(None),
            sa.cast(updates.c.occurred_at, sa.Date) >= start_date,
            sa.cast(updates.c.occurred_at, sa.Date) <= end_date,
        )
        activity_conditions = [
            activities.c.organization_id == org_id,
            sa.or_(
                sa.and_(activities.c.activity_date >= start_date, activities.c.activity_date <= end_date),
                updated_in_period,
            ),
            activities.c.deleted_at.is_(None),
        ]
        issue_conditions = [
            site_issues.c.organization_id == org_id,
            # Request 104, D4: what the dashboard counts as open -- open and
            # acknowledged ("being handled").
            site_issues.c.status.in_(["OPEN", "ACKNOWLEDGED"]),
            # Not the "Question for your engineer" notes older versions saved as issues.
            sa.func.coalesce(site_issues.c.narrative, "").notlike("Question for your engineer:%"),
        ]
        # A null project/site on the caller's context means "don't narrow",
        # not "match rows with a null column" -- mirrors labour_query.
        if proj_uuid is not None:
            activity_conditions.append(activities.c.project_id == proj_uuid)
            issue_conditions.append(site_issues.c.project_id == proj_uuid)
        if site_uuid is not None:
            activity_conditions.append(activities.c.site_id == site_uuid)
            issue_conditions.append(site_issues.c.site_id == site_uuid)
        if work_type:
            activity_conditions.append(activities.c.work_type.ilike(f"%{work_type.strip()}%"))
        if not include_unsaved:
            from mesiri.application.dpr import fact_review

            activity_conditions.append(sa.text(fact_review.counted_sql(fact_review.ACTIVITY, "activities.id")))
            issue_conditions.append(sa.text(fact_review.counted_sql(fact_review.SITE_ISSUE, "site_issues.id")))

        activity_query = (
            sa.select(
                activities.c.work_type,
                activities.c.narrative,
                activities.c.status,
                activities.c.activity_date,
            )
            .where(*activity_conditions)
            .order_by(activities.c.activity_date.desc(), activities.c.updated_at.desc())
            .limit(_MAX_ROWS)
        )
        activity_count_query = sa.select(sa.func.count()).select_from(
            sa.select(activities.c.id).where(*activity_conditions).subquery()
        )
        issue_query = (
            sa.select(
                site_issues.c.issue_type,
                site_issues.c.severity,
                site_issues.c.narrative,
                site_issues.c.status,
                site_issues.c.occurred_at,
            )
            .where(*issue_conditions)
            .order_by(site_issues.c.occurred_at.desc())
            .limit(_MAX_ROWS)
        )
        issue_count_query = sa.select(sa.func.count()).select_from(
            sa.select(site_issues.c.id).where(*issue_conditions).subquery()
        )

        async with self._db.transaction() as conn:
            activity_rows = (await conn.execute(activity_query)).mappings().all()
            activity_total = (await conn.execute(activity_count_query)).scalar_one()
            issue_rows = (await conn.execute(issue_query)).mappings().all()
            issue_total = (await conn.execute(issue_count_query)).scalar_one()

        return {
            "activities": [
                {
                    "work_type": row["work_type"],
                    "narrative": row["narrative"],
                    "status": row["status"],
                    # Selected above only for ORDER BY until this was added --
                    # a tabular export (PDF) needs the date on every row, not
                    # just the query's own sort order.
                    "activity_date": row["activity_date"].isoformat()
                    if row["activity_date"]
                    else None,
                }
                for row in activity_rows
            ],
            "activity_count": int(activity_total),
            "open_issues": [
                {
                    "issue_type": row["issue_type"],
                    "severity": row["severity"],
                    "narrative": row["narrative"],
                    "status": row["status"],
                    "occurred_at": row["occurred_at"].isoformat() if row["occurred_at"] else None,
                }
                for row in issue_rows
            ],
            "open_issue_count": int(issue_total),
        }


def _empty_results() -> dict[str, Any]:
    return {"activities": [], "activity_count": 0, "open_issues": [], "open_issue_count": 0}
