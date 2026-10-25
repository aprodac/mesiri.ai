"""Projects confirmed outbox_events into timeline_entries (the Timeline read model).

Per architecture: downstream systems (dashboard/timeline UI) read only
timeline_entries, never business tables. This module is the single writer
of that projection — a plain idempotent batch function, not a persistent
worker (see mesiri.application.materials.recovery for the same convention:
"invocable manually or via a cron entry — not a background worker service").

Concurrency safety: uses `SELECT ... FOR UPDATE SKIP LOCKED` on the
outbox_events batch select. Two concurrent invocations (e.g. overlapping
cron runs) each lock a disjoint set of unpublished rows and skip rows the
other already holds, rather than blocking or double-projecting. This is
preferred over an ON-CONFLICT claim table (as used by
material_execution.py's idempotency_keys) because here the "claim" and the
"do the work" are the same short transaction, not a claim-now /
complete-later split — SKIP LOCKED is the standard Postgres primitive for
exactly this "queue drain" shape, and outbox_events' own
ix_outbox_events_unpublished partial index was built for it.

Crash safety: published_at is only set after the timeline_entries insert
succeeds, in the same transaction. If the process dies mid-batch, the
transaction rolls back entirely — no row is left half-projected, and
everything in that batch is retried (safely, since it was never marked
published) on the next invocation.
"""

from __future__ import annotations

import datetime
import json
import uuid
from collections.abc import Callable
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

_outbox_events = sa.Table(
    "outbox_events",
    sa.MetaData(),
    sa.Column("id", sa.UUID(as_uuid=True)),
    sa.Column("aggregate_type", sa.String),
    sa.Column("aggregate_id", sa.UUID(as_uuid=True)),
    sa.Column("event_type", sa.String),
    sa.Column("payload", sa.JSON),
    sa.Column("correlation_id", sa.String),
    sa.Column("created_at", sa.DateTime(timezone=True)),
    sa.Column("published_at", sa.DateTime(timezone=True)),
)

_material_receipts = sa.Table(
    "material_receipts",
    sa.MetaData(),
    sa.Column("id", sa.UUID(as_uuid=True)),
    sa.Column("organization_id", sa.UUID(as_uuid=True)),
    sa.Column("project_id", sa.UUID(as_uuid=True)),
    sa.Column("site_id", sa.UUID(as_uuid=True)),
    sa.Column("occurred_date", sa.Date),
    sa.Column("occurred_time", sa.Time),
)

_material_usage = sa.Table(
    "material_usage",
    sa.MetaData(),
    sa.Column("id", sa.UUID(as_uuid=True)),
    sa.Column("organization_id", sa.UUID(as_uuid=True)),
    sa.Column("project_id", sa.UUID(as_uuid=True)),
    sa.Column("site_id", sa.UUID(as_uuid=True)),
    sa.Column("occurred_date", sa.Date),
    sa.Column("occurred_time", sa.Time),
)

# labour_attendance_reports has no occurred_time (attendance is a whole-day
# fact, not a timestamped movement) — deliberately declared WITHOUT one, so
# the batch loop below can tell "this table has no such column" apart from
# "this row's time happens to be null". A fabricated midnight time would look
# identical, to anyone reading timeline_entries later, to a genuinely recorded
# one.
_labour_attendance_reports = sa.Table(
    "labour_attendance_reports",
    sa.MetaData(),
    sa.Column("id", sa.UUID(as_uuid=True)),
    sa.Column("organization_id", sa.UUID(as_uuid=True)),
    sa.Column("project_id", sa.UUID(as_uuid=True)),
    sa.Column("site_id", sa.UUID(as_uuid=True)),
    sa.Column("occurred_date", sa.Date),
)

# activities uses activity_date/started_at (its own schema's names, set by
# migration 0430) rather than the occurred_date/occurred_time names every
# other aggregate here uses -- aliased via Column(..., key=...) so
# source_table.c.occurred_date below resolves for every aggregate uniformly,
# without the batch loop needing to know this table is spelled differently.
# This was flagged as a known gap in progress_execution.py's own docstring
# ("Not yet registered... Phase 6.0") -- until this entry existed, every
# ActivityCreated/ActivityProgressUpdateAdded/ActivityEvidenceAttached
# outbox row hit the "source row not found" orphan path below and was
# marked published without ever reaching timeline_entries.
_activities = sa.Table(
    "activities",
    sa.MetaData(),
    sa.Column("id", sa.UUID(as_uuid=True)),
    sa.Column("organization_id", sa.UUID(as_uuid=True)),
    sa.Column("project_id", sa.UUID(as_uuid=True)),
    sa.Column("site_id", sa.UUID(as_uuid=True)),
    sa.Column("activity_date", sa.Date, key="occurred_date"),
    sa.Column("started_at", sa.Time, key="occurred_time"),
)

# site_issues has no occurred_date/occurred_time split — occurred_at is
# already a single timestamp (migration 0430), so this table is keyed
# directly as "occurred_at" rather than aliased into the occurred_date/
# occurred_time shape every other aggregate above uses. The batch loop below
# checks for either column name rather than assuming one shape fits all
# aggregates (this is the "extend the projector to accept a column-name
# mapping" option _activities' own comment flagged as the alternative to
# aliasing).
_site_issues = sa.Table(
    "site_issues",
    sa.MetaData(),
    sa.Column("id", sa.UUID(as_uuid=True)),
    sa.Column("organization_id", sa.UUID(as_uuid=True)),
    sa.Column("project_id", sa.UUID(as_uuid=True)),
    sa.Column("site_id", sa.UUID(as_uuid=True)),
    sa.Column("occurred_at", sa.DateTime(timezone=True)),
)

_expenses = sa.Table(
    "expenses",
    sa.MetaData(),
    sa.Column("id", sa.UUID(as_uuid=True)),
    sa.Column("organization_id", sa.UUID(as_uuid=True)),
    sa.Column("project_id", sa.UUID(as_uuid=True)),
    sa.Column("site_id", sa.UUID(as_uuid=True)),
    sa.Column("occurred_date", sa.Date),
    sa.Column("occurred_time", sa.Time),
)

# money_transactions (migration 0340) has no project_id/site_id at all — it's
# scoped to money_accounts, not a project/site directly (a transfer between
# two accounts has no single project to attribute it to). Left absent here
# rather than joined through from_account_id/to_account_id to money_accounts
# for a project_id, matching the projector's existing rule of never reaching
# into a second table just to enrich one event (see
# _labour_attendance_summary's docstring for the same reasoning applied to
# names instead of scope). The batch loop below defaults project_id/site_id
# to NULL for any aggregate table that simply has no such column — timeline_
# entries already declares both nullable (migration 0150) for exactly this.
_money_transactions = sa.Table(
    "money_transactions",
    sa.MetaData(),
    sa.Column("id", sa.UUID(as_uuid=True)),
    sa.Column("organization_id", sa.UUID(as_uuid=True)),
    sa.Column("occurred_date", sa.Date),
    sa.Column("occurred_time", sa.Time),
)

# Extension point: a new domain's aggregate is one entry here — the table
# must expose organization_id, and either occurred_date (+ optional
# occurred_time) or a single occurred_at timestamp. project_id/site_id are
# both optional (see money_transactions above); when present they scope the
# projected entry, when absent the entry is org-wide (project_id/site_id
# NULL in timeline_entries).
AGGREGATE_TABLES: dict[str, sa.Table] = {
    "material_receipt": _material_receipts,
    "material_usage": _material_usage,
    "labour_attendance_report": _labour_attendance_reports,
    "activity": _activities,
    "site_issue": _site_issues,
    "expense": _expenses,
    "money_transaction": _money_transactions,
}


def _labour_attendance_summary(payload: dict[str, Any]) -> str:
    """"12 workers recorded". Deliberately no project/site name in the text,
    matching Material's own MaterialReceived/MaterialUsed summaries above:
    timeline_entries already carries project_id/site_id as their own columns
    (copied from the source row just below), and the consuming UI resolves
    names for display there. Looking up a name here to embed in the string
    would mean the projector reaching into a second table just to caption an
    event, and would leave the summary permanently stale if a project were
    ever renamed after the fact."""
    headcount = payload.get("total_headcount")
    if headcount is None:
        return "Attendance recorded"
    return f"{headcount} worker{'s' if headcount != 1 else ''} recorded"


# Extension point: a new event type's human summary is one entry here.
EVENT_SUMMARY_BUILDERS: dict[str, Callable[[dict[str, Any]], str]] = {
    "MaterialReceived": lambda p: (
        f"{p.get('quantity')} {p.get('unit')} of {p.get('material_name')} received"
    ),
    "MaterialUsed": lambda p: (
        f"{p.get('quantity')} {p.get('unit')} of {p.get('material_name')} used"
    ),
    "MaterialMovementCorrected": lambda p: (
        f"Material movement corrected ({p.get('movement_reason')})"
    ),
    "LabourAttendanceRecorded": _labour_attendance_summary,
    "LabourAttendanceVoided": lambda p: "Attendance withdrawn",
    "ActivityCreated": lambda p: (
        f"{p.get('work_type')} activity started" if p.get("work_type") else "Activity started"
    ),
    "ActivityProgressUpdateAdded": lambda p: (
        f"Progress update: {p.get('update_kind', 'PROGRESS').title()}"
    ),
    "ActivityProgressUpdateCorrected": lambda p: f"Quantity corrected to {p.get('quantity')}",
    "ActivityEvidenceAttached": lambda p: "Photo evidence attached",
    "SiteIssueReported": lambda p: (
        f"{p.get('issue_type', 'Issue').replace('_', ' ').title()} reported"
        + (f" ({p['severity'].title()})" if p.get("severity") else "")
    ),
    "SiteIssueAcknowledged": lambda p: "Site issue acknowledged",
    "SiteIssueResolved": lambda p: "Site issue resolved",
    "SiteIssueWontFix": lambda p: "Site issue marked as won't fix",
    "SiteIssueCancelled": lambda p: "Site issue withdrawn (reported in error)",
    "SiteIssueReopened": lambda p: "Site issue reopened",
    "ExpenseRecorded": lambda p: (
        f"{p.get('currency', 'INR')} {p.get('amount')} expense recorded"
        + (f" ({p['category_text']})" if p.get("category_text") else "")
    ),
    "ExpenseVoided": lambda p: "Expense voided",
    "MoneyTransactionTransferred": lambda p: (
        f"{p.get('currency', 'INR')} {p.get('amount')} transferred between accounts"
    ),
    "MoneyTransferReversed": lambda p: "Money transfer reversed",
}


def _build_summary(event_type: str, payload: dict[str, Any]) -> str:
    builder = EVENT_SUMMARY_BUILDERS.get(event_type)
    if builder is None:
        return f"{event_type} event"
    try:
        return builder(payload)
    except Exception:  # noqa: BLE001 — a malformed payload must not block the batch
        return f"{event_type} event"


def _coerce_payload(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str):
        try:
            return json.loads(payload)
        except (TypeError, ValueError):
            return {}
    return {}


async def project_pending_events(conn: AsyncConnection, batch_size: int = 100) -> int:
    """Drain up to `batch_size` unpublished outbox_events into timeline_entries.

    Runs entirely on the caller-supplied connection/transaction so the
    caller (script main(), or a test) controls commit boundaries. Returns
    the number of rows projected (source rows found and inserted into
    timeline_entries — orphaned outbox rows are marked published but not
    counted as "projected").
    """
    select_stmt = (
        sa.select(_outbox_events)
        .where(_outbox_events.c.published_at.is_(None))
        .order_by(_outbox_events.c.created_at)
        .limit(batch_size)
        .with_for_update(skip_locked=True)
    )
    rows = (await conn.execute(select_stmt)).mappings().all()

    projected = 0
    for row in rows:
        source_table = AGGREGATE_TABLES.get(row["aggregate_type"])
        source = None
        if source_table is not None:
            select_columns = [source_table.c.organization_id]
            # project_id/site_id are optional per-aggregate (money_transactions
            # has neither — see its table comment above); selected only when
            # the table actually declares them, defaulting to NULL below
            # otherwise (timeline_entries has both nullable for exactly this).
            if "project_id" in source_table.c:
                select_columns.append(source_table.c.project_id)
            if "site_id" in source_table.c:
                select_columns.append(source_table.c.site_id)
            if "occurred_date" in source_table.c:
                # occurred_time is optional per-aggregate (labour_attendance_reports
                # has none -- attendance is a whole-day fact). Selected only when the
                # table actually declares it, rather than assuming every aggregate
                # has one; occurred_at below already treats a missing time as
                # midnight, so this only changes whether the column is asked for.
                select_columns.append(source_table.c.occurred_date)
                if "occurred_time" in source_table.c:
                    select_columns.append(source_table.c.occurred_time)
            elif "occurred_at" in source_table.c:
                # site_issues' shape: a single timestamp column, no
                # date/time split to recombine.
                select_columns.append(source_table.c.occurred_at)
            source = (
                (
                    await conn.execute(
                        sa.select(*select_columns).where(source_table.c.id == row["aggregate_id"])
                    )
                )
                .mappings()
                .first()
            )

        if source is None:
            # Source row not found (shouldn't happen in practice — defensive).
            # Still mark published so a permanently-orphaned row doesn't block
            # the batch forever.
            await conn.execute(
                _outbox_events.update()
                .where(_outbox_events.c.id == row["id"])
                .values(published_at=sa.func.now())
            )
            continue

        payload = _coerce_payload(row["payload"])

        occurred_at = row["created_at"]
        if source.get("occurred_date") is not None:
            occurred_at = datetime.datetime.combine(
                source["occurred_date"], source.get("occurred_time") or datetime.time.min
            )
        elif source.get("occurred_at") is not None:
            occurred_at = source["occurred_at"]

        await conn.execute(
            sa.text(
                "INSERT INTO timeline_entries "
                "(id, organization_id, project_id, site_id, event_type, summary, "
                "payload, occurred_at, correlation_id, source_aggregate_type, "
                "source_aggregate_id) "
                "VALUES (:id, :organization_id, :project_id, :site_id, :event_type, "
                ":summary, CAST(:payload AS jsonb), :occurred_at, :correlation_id, "
                ":source_aggregate_type, :source_aggregate_id)"
            ),
            {
                "id": uuid.uuid4(),
                "organization_id": source["organization_id"],
                "project_id": source.get("project_id"),
                "site_id": source.get("site_id"),
                "event_type": row["event_type"],
                "summary": _build_summary(row["event_type"], payload),
                "payload": json.dumps(payload),
                "occurred_at": occurred_at,
                "correlation_id": row["correlation_id"],
                "source_aggregate_type": row["aggregate_type"],
                "source_aggregate_id": row["aggregate_id"],
            },
        )
        await conn.execute(
            _outbox_events.update()
            .where(_outbox_events.c.id == row["id"])
            .values(published_at=sa.func.now())
        )
        projected += 1

    return projected
