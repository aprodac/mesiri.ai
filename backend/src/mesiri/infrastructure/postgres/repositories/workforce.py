"""Read/write access for the workforce register and attendance reports.

Companion to labour_execution.py, which owns the *write* path a WhatsApp
confirmation takes (persist_success/persist_rejection against the same four
tables). This file is the dashboard-facing read side, plus the register's
own CRUD (workforce_workers is the one table here that a dashboard writes to
directly, since promoting/editing a worker is not a WhatsApp-confirmed
workflow the way attendance is).

Mirrors materials.py's PostgresMaterialReadRepository for shape: plain
sqlalchemy Core tables, no ORM, every method takes an externally-supplied
connection and never commits.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

_workforce_workers = sa.Table(
    "workforce_workers",
    sa.MetaData(),
    sa.Column("id", sa.UUID(as_uuid=True)),
    sa.Column("organization_id", sa.UUID(as_uuid=True)),
    sa.Column("name", sa.String),
    sa.Column("trade", sa.String),
    sa.Column("worker_type", sa.String),
    sa.Column("default_daily_wage", sa.Numeric),
    sa.Column("contractor", sa.String),
    sa.Column("status", sa.String),
    sa.Column("created_at", sa.DateTime(timezone=True)),
    sa.Column("created_by", sa.UUID(as_uuid=True)),
    sa.Column("updated_at", sa.DateTime(timezone=True)),
    sa.Column("updated_by", sa.UUID(as_uuid=True)),
)

_labour_attendance_reports = sa.Table(
    "labour_attendance_reports",
    sa.MetaData(),
    sa.Column("id", sa.UUID(as_uuid=True)),
    sa.Column("organization_id", sa.UUID(as_uuid=True)),
    sa.Column("project_id", sa.UUID(as_uuid=True)),
    sa.Column("site_id", sa.UUID(as_uuid=True)),
    sa.Column("occurred_date", sa.Date),
    sa.Column("recorded_via", sa.String),
    sa.Column("notes", sa.Text),
    sa.Column("corrects_report_id", sa.UUID(as_uuid=True)),
    sa.Column("correlation_id", sa.String),
    sa.Column("created_at", sa.DateTime(timezone=True)),
    sa.Column("created_by", sa.UUID(as_uuid=True)),
    # Migration 0462 -- a withdrawn report. Stays fully readable; simply
    # stops counting. See _live_report_condition.
    sa.Column("voided_at", sa.DateTime(timezone=True)),
    sa.Column("voided_by", sa.UUID(as_uuid=True)),
    sa.Column("void_reason", sa.Text),
)

_labour_attendance_lines = sa.Table(
    "labour_attendance_lines",
    sa.MetaData(),
    sa.Column("id", sa.UUID(as_uuid=True)),
    sa.Column("report_id", sa.UUID(as_uuid=True)),
    sa.Column("worker_id", sa.UUID(as_uuid=True)),
    sa.Column("worker_name", sa.String),
    sa.Column("worker_name_original", sa.String),
    sa.Column("trade", sa.String),
    sa.Column("headcount", sa.Integer),
    sa.Column("daily_wage", sa.Numeric),
    sa.Column("contractor", sa.String),
    sa.Column("activity", sa.String),
    sa.Column("attendance_status", sa.String),
    sa.Column("overtime_hours", sa.Numeric),
    sa.Column("remarks", sa.Text),
    sa.Column("created_at", sa.DateTime(timezone=True)),
)


def _day_fraction():
    """Man-days one person on this line contributes: 1 present, 0.5 half day,
    0 absent.

    A photographed muster roll lists the whole crew, absentees included. Before
    this existed every listed row was counted as a day worked, so reading one
    sheet would invent a day's work -- and a day's wage -- for everyone who did
    not turn up. NULL (every row written before migration 0456) reads as
    present, which is what those rows meant.
    """
    return sa.case(
        (_labour_attendance_lines.c.attendance_status == "absent", sa.literal(0)),
        (_labour_attendance_lines.c.attendance_status == "half_day", sa.literal(Decimal("0.5"))),
        else_=sa.literal(1),
    )

_labour_attendance_attachments = sa.Table(
    "labour_attendance_attachments",
    sa.MetaData(),
    sa.Column("id", sa.UUID(as_uuid=True)),
    sa.Column("report_id", sa.UUID(as_uuid=True)),
    sa.Column("media_object_key", sa.String),
    sa.Column("attachment_type", sa.String),
    sa.Column("created_at", sa.DateTime(timezone=True)),
    sa.Column("created_by", sa.UUID(as_uuid=True)),
)


def _line_totals(lines: list[dict[str, Any]]) -> tuple[int, Decimal]:
    """Headcount and cost for one report's lines.

    Decimal throughout, never float: `daily_wage` is Numeric(14, 2) and comes
    back from the driver as a Decimal. Accumulating it in binary float made
    3x1166.67 + 3x1166.67 + 7x820.10 land on 12740.720000000001, which pydantic
    then re-widened via str() so the dashboard rendered the full 17-digit repr.
    The three other implementations of this same total (the WhatsApp
    confirmation, the labour query service, and the contract-level command)
    are all Decimal-exact -- this one was the outlier, so the dashboard
    disagreed with the confirmation message for the very same report.

    A missing wage skips the line's cost rather than contributing zero, so a
    partially-priced report understates cost instead of dragging an average
    down to nothing.
    """
    headcount = 0
    cost = Decimal("0")
    for line in lines:
        status = str(line.get("attendance_status") or "present")
        # A person marked absent was reported, but did not work. Counting them
        # would put a day's wage against someone the sheet says was not there.
        if status == "absent":
            continue
        count = int(line.get("headcount") or 1)
        fraction = Decimal("0.5") if status == "half_day" else Decimal("1")
        headcount += count
        wage = line.get("daily_wage")
        if wage is not None:
            cost += Decimal(str(wage)) * count * fraction
    return headcount, cost.quantize(Decimal("0.01"))


def _superseded_report_ids():
    """Reports that a later report explicitly corrects.

    A supervisor who forgets someone re-sends the whole list, which by design
    creates a second immutable row rather than editing the first (P5). Both
    rows stay readable for audit, but only the live one may feed a total --
    counting both is what made a day of 18 workers read as 16 + 18 = 34
    man-days with cost inflated to match.

    Extracted so the list, the duplicate-warning lookup and the report
    aggregation cannot drift apart on the one rule they must all apply. Any
    new read that produces a total belongs here too.
    """
    return (
        sa.select(_labour_attendance_reports.c.corrects_report_id)
        .where(_labour_attendance_reports.c.corrects_report_id.isnot(None))
        .scalar_subquery()
    )


#: The two ways a report stops counting, in the one place that decides it.
#:
#: SQL text rather than a SQLAlchemy expression because the readers are split
#: across packages and query styles: this repository builds Core selects,
#: while the DPR repository and the assistant's labour query write raw
#: `text()`. Both must apply the identical rule, and the previous attempt at
#: sharing it -- a Core-only helper (_superseded_report_ids above) -- is
#: exactly why they drifted: neither could use it, so neither did, and
#: superseded reports kept counting in the DPR and in "how many workers came
#: this week?" long after the dashboard stopped counting them.
#:
#: `{alias}` is the reports table's alias in the caller's query.
LIVE_REPORT_SQL = (
    "{alias}.voided_at IS NULL "
    "AND {alias}.id NOT IN ("
    "    SELECT corrects_report_id FROM labour_attendance_reports "
    "    WHERE corrects_report_id IS NOT NULL)"
)


def live_report_sql(alias: str) -> str:
    """`LIVE_REPORT_SQL` bound to one query's table alias."""
    return LIVE_REPORT_SQL.format(alias=alias)


#: BE-10: labour is a snapshot per site and day -- the latest figure replaces
#: an earlier one. A line stops counting when a *later* live report for the
#: same site and day carries a line with the same key:
#:
#: - a named worker (register id or name) is one person: their latest line
#:   for the day is the one that counts, so "Raju" sent twice is one man-day;
#: - a plain headcount ("10 masons", "Ravi: 12 helpers") is keyed by
#:   contractor + trade, so 10 then 12 Ravi masons is 12, not 22, while a
#:   different contractor or trade still adds on top.
#:
#: Contractor, trade and name compare trimmed and case-insensitive, the same
#: way `_group_expressions` buckets them. Nothing is deleted or rewritten
#: (P5): the earlier line stays readable, it just no longer feeds a total.
#: Applies on top of `LIVE_REPORT_SQL`, never instead of it -- a superseded or
#: voided report neither counts nor replaces anything.
#:
#: `{line}` / `{report}` are the lines and reports aliases in the caller's
#: query; the line must belong to that report.
COUNTED_LINE_SQL = (
    "NOT EXISTS ("
    "    SELECT 1 FROM labour_attendance_lines later_line"
    "    JOIN labour_attendance_reports later_report"
    "      ON later_report.id = later_line.report_id"
    "    WHERE later_report.organization_id = {report}.organization_id"
    "      AND later_report.project_id = {report}.project_id"
    "      AND later_report.site_id IS NOT DISTINCT FROM {report}.site_id"
    "      AND later_report.occurred_date = {report}.occurred_date"
    "      AND (later_report.created_at, later_report.id)"
    "          > ({report}.created_at, {report}.id)"
    "      AND later_report.voided_at IS NULL"
    "      AND later_report.id NOT IN ("
    "          SELECT corrects_report_id FROM labour_attendance_reports"
    "          WHERE corrects_report_id IS NOT NULL)"
    "      AND ("
    "        ({line}.worker_id IS NOT NULL AND later_line.worker_id = {line}.worker_id)"
    "        OR (NULLIF(btrim({line}.worker_name), '') IS NOT NULL"
    "            AND lower(btrim(later_line.worker_name)) = lower(btrim({line}.worker_name)))"
    "        OR ({line}.worker_id IS NULL AND NULLIF(btrim({line}.worker_name), '') IS NULL"
    "            AND later_line.worker_id IS NULL"
    "            AND NULLIF(btrim(later_line.worker_name), '') IS NULL"
    "            AND lower(btrim(COALESCE(later_line.contractor, '')))"
    "                = lower(btrim(COALESCE({line}.contractor, '')))"
    "            AND lower(btrim(COALESCE(later_line.trade, '')))"
    "                = lower(btrim(COALESCE({line}.trade, ''))))"
    "      )"
    ")"
)


def counted_line_sql(line: str, report: str) -> str:
    """`COUNTED_LINE_SQL` bound to one query's line and report aliases."""
    return COUNTED_LINE_SQL.format(line=line, report=report)


def _counted_line_clause():
    """`COUNTED_LINE_SQL` for this module's unaliased Core tables."""
    return sa.text(counted_line_sql("labour_attendance_lines", "labour_attendance_reports"))


#: Grouping key -> the SQL expression attendance is bucketed by, and the
#: expression that names the bucket for display. Trades and contractors are
#: grouped case-insensitively on a trimmed value so "Mason" and "mason " are
#: one row, while the label keeps an original spelling.
def _group_expressions(group_by: str):
    if group_by == "trade":
        key = sa.func.coalesce(sa.func.lower(sa.func.trim(_labour_attendance_lines.c.trade)), "")
        return key, sa.func.max(_labour_attendance_lines.c.trade)
    if group_by == "contractor":
        key = sa.func.coalesce(
            sa.func.lower(sa.func.trim(_labour_attendance_lines.c.contractor)), ""
        )
        return key, sa.func.max(_labour_attendance_lines.c.contractor)
    if group_by == "worker":
        # A temporary worker has no register row, so worker_id is NULL and the
        # name is the only identity there is -- keying on worker_id alone would
        # silently drop 30-60% of construction attendance (principle P3).
        key = sa.func.coalesce(
            sa.cast(_labour_attendance_lines.c.worker_id, sa.String),
            sa.func.lower(sa.func.trim(_labour_attendance_lines.c.worker_name)),
        )
        return key, sa.func.max(_labour_attendance_lines.c.worker_name)
    return (
        sa.cast(_labour_attendance_reports.c.occurred_date, sa.String),
        sa.cast(sa.func.max(_labour_attendance_reports.c.occurred_date), sa.String),
    )


class PostgresWorkforceReadRepository:
    """Register CRUD (workforce_workers) and attendance report reads."""

    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    # --- Register -----------------------------------------------------

    async def list_workers(
        self,
        *,
        organization_id: uuid.UUID,
        status: str | None = None,
        search: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        conditions = [_workforce_workers.c.organization_id == organization_id]
        if status is not None:
            conditions.append(_workforce_workers.c.status == status)
        if search:
            conditions.append(_workforce_workers.c.name.ilike(f"%{search}%"))

        total = (
            await self._conn.execute(
                sa.select(sa.func.count()).select_from(_workforce_workers).where(*conditions)
            )
        ).scalar_one()

        rows = (
            await self._conn.execute(
                sa.select(_workforce_workers)
                .where(*conditions)
                .order_by(_workforce_workers.c.name)
                .limit(limit)
                .offset(offset)
            )
        ).mappings().all()
        return [dict(row) for row in rows], int(total)

    async def get_worker(
        self, organization_id: uuid.UUID, worker_id: uuid.UUID
    ) -> dict[str, Any] | None:
        row = (
            await self._conn.execute(
                sa.select(_workforce_workers).where(
                    _workforce_workers.c.organization_id == organization_id,
                    _workforce_workers.c.id == worker_id,
                )
            )
        ).mappings().first()
        return dict(row) if row is not None else None

    async def create_worker(
        self,
        *,
        organization_id: uuid.UUID,
        name: str,
        trade: str | None,
        worker_type: str,
        default_daily_wage: float | None,
        contractor: str | None,
        status: str,
        created_by: uuid.UUID,
    ) -> dict[str, Any]:
        worker_id = uuid.uuid4()
        await self._conn.execute(
            _workforce_workers.insert().values(
                id=worker_id,
                organization_id=organization_id,
                name=name,
                trade=trade,
                worker_type=worker_type,
                default_daily_wage=default_daily_wage,
                contractor=contractor,
                status=status,
                created_at=sa.func.now(),
                created_by=created_by,
                updated_at=sa.func.now(),
                updated_by=created_by,
            )
        )
        worker = await self.get_worker(organization_id, worker_id)
        assert worker is not None
        return worker

    async def update_worker(
        self,
        *,
        organization_id: uuid.UUID,
        worker_id: uuid.UUID,
        patch: dict[str, Any],
        updated_by: uuid.UUID,
    ) -> dict[str, Any] | None:
        if not patch:
            return await self.get_worker(organization_id, worker_id)
        await self._conn.execute(
            _workforce_workers.update()
            .where(
                _workforce_workers.c.organization_id == organization_id,
                _workforce_workers.c.id == worker_id,
            )
            .values(**patch, updated_at=sa.func.now(), updated_by=updated_by)
        )
        return await self.get_worker(organization_id, worker_id)

    # --- Attendance reports (read-only; writes go through labour_execution.py) -

    async def list_reports(
        self,
        *,
        organization_id: uuid.UUID,
        project_ids: set[uuid.UUID] | None,
        site_id: uuid.UUID | None = None,
        date_from: datetime.date | None = None,
        date_to: datetime.date | None = None,
        limit: int = 50,
        offset: int = 0,
        include_superseded: bool = False,
    ) -> tuple[list[dict[str, Any]], int]:
        """Attendance reports for the dashboard, newest first.

        Superseded reports are excluded by default. A supervisor who forgets
        someone re-sends the whole list, which by design creates a second
        immutable row for the same site and day (P5 -- attendance is never
        rewritten). Counting both is what made a day of 18 workers show as
        16 + 18 = 34 man-days, with cost inflated to match. The replacement
        report points at the one it corrects via `corrects_report_id`, so the
        superseded row stays fully readable for audit but no longer feeds any
        total. Pass include_superseded=True to see the complete history.

        Voided reports (migration 0462 -- withdrawn as filed against the
        wrong site) are excluded on the same terms and by the same flag:
        both are "still readable, no longer counts."
        """
        conditions = [_labour_attendance_reports.c.organization_id == organization_id]
        if not include_superseded:
            conditions.append(_labour_attendance_reports.c.id.notin_(_superseded_report_ids()))
            conditions.append(_labour_attendance_reports.c.voided_at.is_(None))
        if project_ids is not None:
            conditions.append(_labour_attendance_reports.c.project_id.in_(project_ids))
        if site_id is not None:
            conditions.append(_labour_attendance_reports.c.site_id == site_id)
        if date_from is not None:
            conditions.append(_labour_attendance_reports.c.occurred_date >= date_from)
        if date_to is not None:
            conditions.append(_labour_attendance_reports.c.occurred_date <= date_to)

        total = (
            await self._conn.execute(
                sa.select(sa.func.count())
                .select_from(_labour_attendance_reports)
                .where(*conditions)
            )
        ).scalar_one()

        report_rows = (
            await self._conn.execute(
                sa.select(_labour_attendance_reports)
                .where(*conditions)
                .order_by(_labour_attendance_reports.c.occurred_date.desc())
                .limit(limit)
                .offset(offset)
            )
        ).mappings().all()

        items: list[dict[str, Any]] = []
        for report in report_rows:
            line_rows = (
                await self._conn.execute(
                    sa.select(_labour_attendance_lines).where(
                        _labour_attendance_lines.c.report_id == report["id"]
                    )
                )
            ).mappings().all()
            lines = [dict(line) for line in line_rows]
            headcount, cost = _line_totals(lines)
            items.append(
                {
                    **dict(report),
                    "line_count": len(lines),
                    "total_headcount": headcount,
                    "total_cost": cost,
                }
            )
        return items, int(total)

    async def aggregate_attendance(
        self,
        *,
        organization_id: uuid.UUID,
        group_by: str,
        project_ids: set[uuid.UUID] | None = None,
        site_id: uuid.UUID | None = None,
        date_from: datetime.date | None = None,
        date_to: datetime.date | None = None,
        include_superseded: bool = False,
    ) -> list[dict[str, Any]]:
        """Attendance totalled per trade / contractor / day / worker.

        Aggregated in SQL rather than by loading rows and summing in Python,
        for two reasons. The dashboard's previous version capped itself at 100
        reports and 200 workers and then reported the truncated total as if it
        were complete; and a year of one 80-worker site is ~29,000 lines, which
        there is no reason to move across the wire to add up.

        Cost is `headcount x daily_wage` **from the attendance line**, never
        from workforce_workers -- editing a worker's wage next month must not
        change what last month cost. `days_worked` counts *distinct* dates, so
        a worker recorded twice on one day (two sites, or a corrected report)
        is one day, never two.

        Money stays exact: daily_wage is Numeric(14, 2) and Postgres sums
        NUMERIC exactly, so no float ever touches the total. A line with no
        wage contributes its man-days but no cost, and is left out of
        priced_man_days -- the same rule `_line_totals` applies, so this
        aggregate and the per-report totals agree.
        """
        key_expr, label_expr = _group_expressions(group_by)

        headcount = sa.func.coalesce(_labour_attendance_lines.c.headcount, 1)
        priced = _labour_attendance_lines.c.daily_wage.isnot(None)

        conditions = [_labour_attendance_reports.c.organization_id == organization_id]
        if not include_superseded:
            conditions.append(_labour_attendance_reports.c.id.notin_(_superseded_report_ids()))
            conditions.append(_labour_attendance_reports.c.voided_at.is_(None))
        if project_ids is not None:
            conditions.append(_labour_attendance_reports.c.project_id.in_(project_ids))
        if site_id is not None:
            conditions.append(_labour_attendance_reports.c.site_id == site_id)
        if date_from is not None:
            conditions.append(_labour_attendance_reports.c.occurred_date >= date_from)
        if date_to is not None:
            conditions.append(_labour_attendance_reports.c.occurred_date <= date_to)
        if not include_superseded:
            # BE-10: a figure re-sent later the same day replaces this one.
            conditions.append(_counted_line_clause())
        if group_by == "worker":
            # Headcount groups ("10 masons") have no identity to attribute a
            # day to. They still count toward every cost and man-day total in
            # the other reports; they simply cannot appear as a named row here.
            conditions.append(
                sa.or_(
                    _labour_attendance_lines.c.worker_id.isnot(None),
                    _labour_attendance_lines.c.worker_name.isnot(None),
                )
            )

        rows = (
            await self._conn.execute(
                sa.select(
                    key_expr.label("key"),
                    label_expr.label("label"),
                    sa.func.sum(headcount * _day_fraction()).label("man_days"),
                    sa.func.coalesce(
                        sa.func.sum(sa.case((priced, headcount * _day_fraction()), else_=0)), 0
                    ).label("priced_man_days"),
                    sa.func.coalesce(
                        sa.func.sum(
                            sa.case(
                                (
                                    priced,
                                    headcount
                                    * _day_fraction()
                                    * _labour_attendance_lines.c.daily_wage,
                                ),
                                else_=0,
                            )
                        ),
                        0,
                    ).label("total_cost"),
                    sa.func.count(sa.distinct(_labour_attendance_reports.c.occurred_date)).label(
                        "days_worked"
                    ),
                    sa.func.min(_labour_attendance_reports.c.occurred_date).label("first_date"),
                    sa.func.max(_labour_attendance_reports.c.occurred_date).label("last_date"),
                    sa.func.count(sa.distinct(_labour_attendance_lines.c.report_id)).label(
                        "report_count"
                    ),
                    sa.func.max(_labour_attendance_lines.c.trade).label("trade"),
                    sa.func.max(_labour_attendance_lines.c.contractor).label("contractor"),
                )
                .select_from(
                    _labour_attendance_lines.join(
                        _labour_attendance_reports,
                        _labour_attendance_reports.c.id == _labour_attendance_lines.c.report_id,
                    )
                )
                .where(*conditions)
                .group_by(key_expr)
            )
        ).mappings().all()

        return [dict(row) for row in rows]

    async def worker_statistics(
        self,
        *,
        organization_id: uuid.UUID,
        project_ids: set[uuid.UUID] | None = None,
        site_id: uuid.UUID | None = None,
        date_from: datetime.date | None = None,
        date_to: datetime.date | None = None,
        worker_id: uuid.UUID | None = None,
        include_dates: bool = False,
    ) -> list[dict[str, Any]]:
        """Per-person attendance history, derived on read and never stored.

        Days worked, first and last seen, earnings and the trades/contractors
        someone has actually worked under are all facts *about the attendance
        record*, not fields on the worker. Storing them would mean maintaining
        a second copy that drifts the moment a report is superseded, and would
        invite exactly the editable "days worked" field the whole refactor
        exists to remove.

        Covers everyone who worked, not everyone on the register: a temporary
        worker has no workforce_workers row, so their identity is the name on
        the line. Headcount groups are excluded -- "7 masons" has nobody to
        attribute a day to.

        `days_worked` is distinct dates; `attendance_count` is the number of
        reports they appear in. The two differ when someone is recorded on two
        sites on one day, and the difference is real information, not an error.

        `include_dates` adds the individual dates, for a calendar view. Off by
        default and used only by the single-worker lookup: a register of 200
        people with a year each would put ~70,000 date strings on the wire for
        a list nobody asked to see day by day.
        """
        conditions = [
            _labour_attendance_reports.c.organization_id == organization_id,
            _labour_attendance_reports.c.id.notin_(_superseded_report_ids()),
            # BE-10: the same person sent twice for one site-day is one day.
            _counted_line_clause(),
            sa.or_(
                _labour_attendance_lines.c.worker_id.isnot(None),
                _labour_attendance_lines.c.worker_name.isnot(None),
            ),
        ]
        if project_ids is not None:
            conditions.append(_labour_attendance_reports.c.project_id.in_(project_ids))
        if site_id is not None:
            conditions.append(_labour_attendance_reports.c.site_id == site_id)
        if date_from is not None:
            conditions.append(_labour_attendance_reports.c.occurred_date >= date_from)
        if date_to is not None:
            conditions.append(_labour_attendance_reports.c.occurred_date <= date_to)
        if worker_id is not None:
            conditions.append(_labour_attendance_lines.c.worker_id == worker_id)

        key_expr = sa.func.coalesce(
            sa.cast(_labour_attendance_lines.c.worker_id, sa.String),
            sa.func.lower(sa.func.trim(_labour_attendance_lines.c.worker_name)),
        )
        headcount = sa.func.coalesce(_labour_attendance_lines.c.headcount, 1)
        priced = _labour_attendance_lines.c.daily_wage.isnot(None)

        rows = (
            await self._conn.execute(
                sa.select(
                    key_expr.label("key"),
                    sa.func.max(sa.cast(_labour_attendance_lines.c.worker_id, sa.String)).label(
                        "worker_id"
                    ),
                    sa.func.max(_labour_attendance_lines.c.worker_name).label("name"),
                    sa.func.count(sa.distinct(_labour_attendance_reports.c.occurred_date)).label(
                        "days_worked"
                    ),
                    sa.func.count(sa.distinct(_labour_attendance_lines.c.report_id)).label(
                        "attendance_count"
                    ),
                    sa.func.sum(headcount * _day_fraction()).label("man_days"),
                    sa.func.coalesce(
                        sa.func.sum(sa.case((priced, headcount * _day_fraction()), else_=0)), 0
                    ).label("priced_man_days"),
                    sa.func.coalesce(
                        sa.func.sum(
                            sa.case(
                                (
                                    priced,
                                    headcount
                                    * _day_fraction()
                                    * _labour_attendance_lines.c.daily_wage,
                                ),
                                else_=0,
                            )
                        ),
                        0,
                    ).label("total_earnings"),
                    sa.func.min(_labour_attendance_reports.c.occurred_date).label("first_seen"),
                    sa.func.max(_labour_attendance_reports.c.occurred_date).label("last_seen"),
                    # NULLs come back inside these arrays and are stripped in
                    # Python rather than with a FILTER clause, which keeps the
                    # statement compiling on the default dialect the unit tests
                    # use.
                    sa.func.array_agg(sa.distinct(_labour_attendance_lines.c.trade)).label(
                        "trades"
                    ),
                    sa.func.array_agg(sa.distinct(_labour_attendance_lines.c.contractor)).label(
                        "contractors"
                    ),
                    *(
                        [
                            sa.func.array_agg(
                                sa.distinct(_labour_attendance_reports.c.occurred_date)
                            ).label("dates_worked")
                        ]
                        if include_dates
                        else []
                    ),
                )
                .select_from(
                    _labour_attendance_lines.join(
                        _labour_attendance_reports,
                        _labour_attendance_reports.c.id == _labour_attendance_lines.c.report_id,
                    )
                )
                .where(*conditions)
                .group_by(key_expr)
            )
        ).mappings().all()

        return [dict(row) for row in rows]

    async def find_existing_report_for_day(
        self,
        organization_id: uuid.UUID,
        *,
        project_id: uuid.UUID,
        site_id: uuid.UUID | None,
        occurred_date: datetime.date,
    ) -> dict[str, Any] | None:
        """The live (non-superseded) report already recorded for this site-day.

        Used to warn a supervisor *before* anything is written that they have
        already reported for this day, and to show what is on record so they
        can decide whether the new report replaces it. Returns None when the
        day is clear, which is the ordinary case.
        """
        conditions = [
            _labour_attendance_reports.c.organization_id == organization_id,
            _labour_attendance_reports.c.project_id == project_id,
            _labour_attendance_reports.c.occurred_date == occurred_date,
            _labour_attendance_reports.c.id.notin_(_superseded_report_ids()),
            # A withdrawn report must not be offered as something to replace:
            # the day is clear again once it is voided.
            _labour_attendance_reports.c.voided_at.is_(None),
        ]
        # A NULL site_id means "the project's only/unspecified site"; match it
        # as its own bucket rather than colliding with every named site.
        if site_id is None:
            conditions.append(_labour_attendance_reports.c.site_id.is_(None))
        else:
            conditions.append(_labour_attendance_reports.c.site_id == site_id)

        report = (
            await self._conn.execute(
                sa.select(_labour_attendance_reports)
                .where(*conditions)
                .order_by(_labour_attendance_reports.c.created_at.desc())
                .limit(1)
            )
        ).mappings().first()
        if report is None:
            return None

        line_rows = (
            await self._conn.execute(
                sa.select(_labour_attendance_lines).where(
                    _labour_attendance_lines.c.report_id == report["id"]
                )
            )
        ).mappings().all()
        headcount, cost = _line_totals([dict(line) for line in line_rows])
        return {**dict(report), "total_headcount": headcount, "total_cost": cost}

    async def find_latest_voidable_report(
        self, organization_id: uuid.UUID, *, reported_by_user_id: uuid.UUID
    ) -> dict[str, Any] | None:
        """The most recent live report this person filed -- the target of
        "cancel that attendance, wrong site".

        Scoped to the reporter, not the organization, for the same reason
        find_latest_activity is (ADR-D15): "my last report" must mean the
        one *this* supervisor sent, never whatever another site happened to
        file thirty seconds later. Superseded and voided rows are skipped so
        a repeated undo walks backwards through real reports instead of
        re-offering one already withdrawn.

        Ordered by created_at (when it was sent), not occurred_date (the day
        it describes) -- backfilling last Tuesday and immediately undoing it
        must target that report, not whichever has the latest date.
        """
        report = (
            await self._conn.execute(
                sa.text(
                    "SELECT r.*, p.name AS project_name, s.name AS site_name "
                    "FROM labour_attendance_reports r "
                    "LEFT JOIN projects p ON p.id = r.project_id "
                    "LEFT JOIN sites s ON s.id = r.site_id "
                    "WHERE r.organization_id = :org_id "
                    "  AND r.created_by = :user_id "
                    f"  AND {live_report_sql('r')} "
                    "ORDER BY r.created_at DESC LIMIT 1"
                ),
                {"org_id": organization_id, "user_id": reported_by_user_id},
            )
        ).mappings().first()
        if report is None:
            return None

        line_rows = (
            await self._conn.execute(
                sa.select(_labour_attendance_lines).where(
                    _labour_attendance_lines.c.report_id == report["id"]
                )
            )
        ).mappings().all()
        headcount, cost = _line_totals([dict(line) for line in line_rows])
        return {**dict(report), "total_headcount": headcount, "total_cost": cost}

    async def void_attendance_report(
        self,
        *,
        organization_id: uuid.UUID,
        report_id: uuid.UUID,
        reason: str,
        voided_by_user_id: uuid.UUID | None,
    ) -> str | None:
        """Withdraw a report from every total without deleting it (migration
        0462). Returns None on success, or a short rejection reason.

        Mirrors PostgresProgressReadRepository.void_activity: a stamp on the
        parent row is enough, because every total joins through it -- the
        lines and attachments underneath stop counting without a second
        write, and stay readable for audit. A reason is required for the
        same reason it is there: a withdrawal with no stated cause is
        indistinguishable from data loss to whoever reads the row later.

        The `voided_at IS NULL` guard makes a double-void a no-op rather
        than re-stamping a new timestamp over the original withdrawal.
        """
        if not reason or not reason.strip():
            return "reason is required to withdraw an attendance report"

        now = datetime.datetime.now(datetime.UTC)
        res = await self._conn.execute(
            sa.update(_labour_attendance_reports)
            .where(
                _labour_attendance_reports.c.organization_id == organization_id,
                _labour_attendance_reports.c.id == report_id,
                _labour_attendance_reports.c.voided_at.is_(None),
            )
            .values(voided_at=now, voided_by=voided_by_user_id, void_reason=reason.strip())
        )
        if res.rowcount == 0:
            return "that attendance report no longer exists or was already withdrawn"
        return None

    async def get_report(
        self, organization_id: uuid.UUID, report_id: uuid.UUID
    ) -> dict[str, Any] | None:
        report = (
            await self._conn.execute(
                sa.select(_labour_attendance_reports).where(
                    _labour_attendance_reports.c.organization_id == organization_id,
                    _labour_attendance_reports.c.id == report_id,
                )
            )
        ).mappings().first()
        if report is None:
            return None

        line_rows = (
            await self._conn.execute(
                sa.select(_labour_attendance_lines).where(
                    _labour_attendance_lines.c.report_id == report_id
                )
            )
        ).mappings().all()
        lines = [dict(line) for line in line_rows]

        attachment_rows = (
            await self._conn.execute(
                sa.select(_labour_attendance_attachments).where(
                    _labour_attendance_attachments.c.report_id == report_id
                )
            )
        ).mappings().all()

        headcount, cost = _line_totals(lines)
        return {
            **dict(report),
            "lines": lines,
            "attachments": [dict(a) for a in attachment_rows],
            # line_count is required (no default) on
            # LabourAttendanceReportSummaryResponse -- list_reports below sets
            # it correctly; this method never did, so every single-report
            # detail fetch 500'd on response validation. "lines" is the raw
            # per-worker line count, distinct from total_headcount (a headcount
            # group is one line but several people).
            "line_count": len(lines),
            "total_headcount": headcount,
            "total_cost": cost,
        }

    async def list_attachments_for_organization(
        self,
        organization_id: uuid.UUID,
        *,
        project_ids: set[uuid.UUID] | None = None,
        site_id: uuid.UUID | None = None,
        start_date: datetime.date | None = None,
        end_date: datetime.date | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Every attendance sheet photo across the org, newest first -- the
        "see all attendance sheets together" gallery view. Mirrors
        expenses.py's PostgresExpenseAttachmentRepository.list_for_organization
        for shape, but takes a `project_ids` SET rather than a single
        project_id -- matching list_reports's own signature above, not
        expense's. A caller with access to several specific projects (but not
        the whole org) must be filtered to exactly those, and a single
        optional id can't express that; None still means "no project filter"
        (portfolio-wide), same convention list_reports already uses.

        Ilan's Phase 7 ask (Timeline/Gallery/analytics): a report's headcount
        and cost are computed from its lines in the same pass, the same
        aggregation _line_totals already does for get_report, so a gallery
        thumbnail can show "12 workers — 27 Jul 2026" without the caller
        fetching each report separately.
        """
        conditions = [_labour_attendance_reports.c.organization_id == organization_id]
        if project_ids is not None:
            conditions.append(_labour_attendance_reports.c.project_id.in_(project_ids))
        if site_id is not None:
            conditions.append(_labour_attendance_reports.c.site_id == site_id)
        if start_date is not None:
            conditions.append(_labour_attendance_reports.c.occurred_date >= start_date)
        if end_date is not None:
            conditions.append(_labour_attendance_reports.c.occurred_date <= end_date)

        rows = (
            await self._conn.execute(
                sa.select(
                    _labour_attendance_attachments.c.id,
                    _labour_attendance_attachments.c.report_id,
                    _labour_attendance_attachments.c.media_object_key,
                    _labour_attendance_attachments.c.attachment_type,
                    _labour_attendance_attachments.c.created_at,
                    _labour_attendance_reports.c.occurred_date,
                    _labour_attendance_reports.c.project_id,
                    _labour_attendance_reports.c.site_id,
                )
                .select_from(
                    _labour_attendance_attachments.join(
                        _labour_attendance_reports,
                        _labour_attendance_reports.c.id == _labour_attendance_attachments.c.report_id,
                    )
                )
                .where(*conditions)
                .order_by(_labour_attendance_attachments.c.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        ).mappings().all()

        if not rows:
            return []

        # Headcount per report, computed the same way get_report does, so a
        # gallery card can caption itself without a follow-up call. Batched
        # into one query per unique report_id rather than N, same convention
        # expenses/router.py's category/vendor name resolution uses below.
        report_ids = {row["report_id"] for row in rows}
        line_rows = (
            await self._conn.execute(
                sa.select(
                    _labour_attendance_lines.c.report_id,
                    _labour_attendance_lines.c.headcount,
                    _labour_attendance_lines.c.daily_wage,
                ).where(_labour_attendance_lines.c.report_id.in_(report_ids))
            )
        ).mappings().all()
        totals: dict[uuid.UUID, tuple[int, float]] = {}
        for report_id in report_ids:
            lines = [dict(r) for r in line_rows if r["report_id"] == report_id]
            totals[report_id] = _line_totals(lines)

        return [
            {
                **dict(row),
                "total_headcount": totals[row["report_id"]][0],
                "total_cost": totals[row["report_id"]][1],
            }
            for row in rows
        ]
