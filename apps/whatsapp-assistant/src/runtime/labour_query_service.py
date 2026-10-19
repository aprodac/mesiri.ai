"""Attendance read service for the labour.query workflow.

Same shape and justification as runtime/expense_query_service.py: a plain
async method the assistant can call, reading confirmed attendance so a node
never queries a repository itself (see workflows/runtime.py). Never opens a
write transaction.

Answers "how many workers today?", "labour cost this week", "who worked
yesterday" — the questions a supervisor asks about work already recorded.
Until this existed, an attendance was visible exactly once, in the
confirmation message at the moment it was sent; afterwards the assistant had
nothing to say about it even though the record was sitting in the database.

**Scope is not optional.** Every read is filtered by organization, and by the
caller's current project/site the same way expense queries are. Attendance
carries names and wages, so a query that leaked across projects would leak
who works where and for how much.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mesiri.infrastructure.postgres.database import PostgresDatabase

_DATE_RANGE_LABELS = {"today": "today", "this_week": "this week", "this_month": "this month"}

#: Named workers listed individually in the reply before it summarises. Ten
#: is what a WhatsApp message can show without becoming a wall of text; past
#: that, the totals are the useful part and the names are noise.
_MAX_NAMES_SHOWN = 10


def resolve_date_range(
    bucket: str | None, *, today: datetime.date | None = None
) -> tuple[datetime.date, datetime.date, str]:
    """Map an extracted `date_range` bucket to a concrete (start, end, label).

    Defaults to **today** rather than expense's "this month": the question a
    supervisor actually asks is "how many workers today", and attendance is a
    daily rhythm in a way spending is not.

    `today` is injectable so the caller can pass the *sender's* today rather
    than the server's — the same UTC-vs-site-timezone trap
    canonicalization/occurred_date.py exists to close.
    """
    today = today or datetime.date.today()
    if bucket == "this_week":
        start = today - datetime.timedelta(days=today.weekday())
        return start, today, _DATE_RANGE_LABELS["this_week"]
    if bucket == "this_month":
        return today.replace(day=1), today, _DATE_RANGE_LABELS["this_month"]
    return today, today, _DATE_RANGE_LABELS["today"]


class LabourQueryService:
    def __init__(self, db: PostgresDatabase) -> None:
        self._db = db

    async def summarize_attendance(
        self,
        *,
        organization_id: str,
        project_id: str | None,
        site_id: str | None,
        start_date: datetime.date,
        end_date: datetime.date,
        trade: str | None = None,
    ) -> dict[str, Any]:
        """Headcount, cost and who worked, over [start_date, end_date].

        Returns a plain dict rather than a domain object because the only
        consumer is the reply node, which formats it — the same choice
        expense_query's seeding makes.

        `total_cost` is operational cost: the wages actually recorded on each
        line. **Not payroll** — no overtime, deductions or statutory
        contributions, all of which are explicitly a different module.
        """
        import sqlalchemy as sa

        from mesiri.infrastructure.postgres.repositories.workforce import counted_line_sql

        try:
            org_id = uuid.UUID(organization_id)
        except (TypeError, ValueError):
            return _empty_summary()

        reports = sa.table(
            "labour_attendance_reports",
            sa.column("id"),
            sa.column("organization_id"),
            sa.column("project_id"),
            sa.column("site_id"),
            sa.column("occurred_date"),
            sa.column("corrects_report_id"),
            sa.column("voided_at"),
        )
        lines = sa.table(
            "labour_attendance_lines",
            sa.column("report_id"),
            sa.column("worker_name"),
            sa.column("trade"),
            sa.column("headcount"),
            sa.column("daily_wage"),
        )

        # A superseded or voided report is still readable but must never feed
        # a total -- the same rule backend's repositories/workforce.py applies
        # to the dashboard aggregate. Neither half was applied here before, so
        # "how many workers came this week?" counted a re-sent day twice (the
        # 16 + 18 = 34 man-day error) and would have kept counting a report
        # withdrawn as wrong-site. Expressed in Core rather than reusing that
        # module's LIVE_REPORT_SQL because this is a Core select and importing
        # backend SQL text into a Core `where` would not compose -- the rule is
        # two conditions, so it is restated exactly rather than approximated.
        superseded = (
            sa.select(reports.c.corrects_report_id)
            .where(reports.c.corrects_report_id.isnot(None))
            .scalar_subquery()
        )
        conditions = [
            reports.c.organization_id == org_id,
            reports.c.occurred_date >= start_date,
            reports.c.occurred_date <= end_date,
            reports.c.voided_at.is_(None),
            reports.c.id.notin_(superseded),
            # BE-10: a figure re-sent later the same day replaces the earlier
            # one. Unlike the two conditions above, this rule is a correlated
            # subquery too long to restate safely, so the backend's own text
            # is used -- it composes here because these Core tables are named,
            # not aliased.
            sa.text(counted_line_sql("labour_attendance_lines", "labour_attendance_reports")),
        ]
        # Scoping mirrors expense_query: a null project/site on the caller's
        # context means "don't narrow", not "match rows with a null column".
        if project_id:
            try:
                conditions.append(reports.c.project_id == uuid.UUID(project_id))
            except (TypeError, ValueError):
                pass
        if site_id:
            try:
                conditions.append(reports.c.site_id == uuid.UUID(site_id))
            except (TypeError, ValueError):
                pass
        if trade:
            conditions.append(lines.c.trade == trade.strip().lower())

        query = (
            sa.select(
                lines.c.worker_name,
                lines.c.trade,
                lines.c.headcount,
                lines.c.daily_wage,
                reports.c.occurred_date,
            )
            .select_from(lines.join(reports, lines.c.report_id == reports.c.id))
            .where(*conditions)
            .order_by(reports.c.occurred_date.desc(), lines.c.worker_name)
        )

        async with self._db.transaction() as conn:
            rows = (await conn.execute(query)).mappings().all()

        return _summarize(rows)


def _empty_summary() -> dict[str, Any]:
    return {"headcount": 0, "total_cost": "0", "named": [], "trades": [], "days": 0, "rows": []}


def _summarize(rows: list[Any]) -> dict[str, Any]:
    """Fold raw lines into the shape the reply node renders.

    Named workers are de-duplicated across the period: someone who worked
    five days is one person, and a "who worked this week" answer listing the
    same name five times would be useless. Headcount is NOT de-duplicated —
    it is worker-days, which is what cost is calculated from.

    `rows` (added alongside the aggregates, not in place of them) keeps one
    entry per attendance line -- every individual wage and every day a name
    appears, none of which the aggregates above preserve. Additive only: the
    text reply node still reads just the aggregate keys, unaware this exists;
    only a tabular export (PDF) needs it.
    """
    headcount = 0
    total = Decimal("0")
    named: list[str] = []
    trades: list[str] = []
    days: set[datetime.date] = set()
    raw_rows: list[dict[str, Any]] = []

    for row in rows:
        try:
            count = int(row["headcount"] or 1)
        except (TypeError, ValueError):
            count = 1
        headcount += count

        wage = row["daily_wage"]
        if wage is not None:
            try:
                total += Decimal(str(wage)) * count
            except (ArithmeticError, ValueError):
                pass

        name = str(row["worker_name"] or "").strip()
        if name and name not in named:
            named.append(name)

        trade = str(row["trade"] or "").strip()
        if trade and trade not in trades:
            trades.append(trade)

        if row["occurred_date"] is not None:
            days.add(row["occurred_date"])

        raw_rows.append(
            {
                "occurred_date": row["occurred_date"].isoformat() if row["occurred_date"] else None,
                "worker_name": row["worker_name"],
                "trade": row["trade"],
                "headcount": count,
                "daily_wage": str(wage) if wage is not None else None,
            }
        )

    return {
        "headcount": headcount,
        "total_cost": str(total),
        "named": named[:_MAX_NAMES_SHOWN],
        "named_total": len(named),
        "trades": trades,
        "days": len(days),
        "rows": raw_rows,
    }
