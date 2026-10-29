"""Updates that reach a site day after it was confirmed (BE-13).

A confirmed site day is frozen (P7): its current DPR version is what the
engineer confirmed, and may already be with the client. An entry for that
day created after that version was built is not in it. Decided 15 Oct:

- **Not sent yet** (the day is confirmed but its report hasn't gone out):
  the day **reopens**. A new version is built and the day goes back for
  confirmation (`revise_version`, which resets it to DRAFT).
- **Already sent**: a **revised version** is recorded with the reason, the
  day keeps its status, and **nothing is re-sent**.
- Either way the entry is listed once under "Late entries for earlier days"
  in the site's next report, and confirmed when that report is confirmed.

`process_late_entries` runs on the scheduler tick and finds them centrally,
from the same tables and dates the DPR is built from, so no module
(Labour, Materials, Progress) changes. `day_status_for_fact` lets the
WhatsApp reply say so straight away.

Takes an externally-supplied connection and never commits.
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy import text

from mesiri.application.dpr import fact_review, site_day

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection

_log = logging.getLogger(__name__)

REOPENED = "reopened"
REVISED = "revised"

#: How far back the check looks; older confirmed days are left alone.
LOOKBACK_DAYS = 45

#: (source table, fact type, SQL for the entry's site day and summary).
#: Dates match the DPR assembly (repositories/dpr.py) and fact_reviews'
#: _FACT_SOURCES; withdrawn rows (deleted, voided, reversals) are skipped.
_SOURCES: tuple[tuple[str, str, str], ...] = (
    (
        "activities",
        "activity",
        """
        SELECT a.id AS source_id, a.id AS fact_id, a.organization_id, a.project_id, a.site_id,
               a.activity_date AS fact_date, a.created_at,
               concat_ws(': ', initcap(replace(a.work_type, '_', ' ')), a.narrative) AS summary
        FROM activities a
        WHERE a.deleted_at IS NULL AND a.site_id IS NOT NULL
        """,
    ),
    (
        "activity_quantities",
        "activity",
        """
        SELECT q.id AS source_id, a.id AS fact_id, a.organization_id, a.project_id, a.site_id,
               a.activity_date AS fact_date, q.created_at,
               concat_ws(' ', initcap(replace(a.work_type, '_', ' ')), 'progress:',
                         trim(to_char(q.quantity, 'FM999999990.##'))) AS summary
        FROM activity_quantities q JOIN activities a ON a.id = q.activity_id
        WHERE a.deleted_at IS NULL AND a.site_id IS NOT NULL
          AND q.created_at > a.created_at + interval '5 seconds'
        """,
    ),
    (
        "site_issues",
        "site_issue",
        """
        SELECT i.id AS source_id, i.id AS fact_id, i.organization_id, i.project_id, i.site_id,
               i.occurred_at::date AS fact_date, i.created_at,
               concat_ws(': ', 'Issue', initcap(replace(i.issue_type::text, '_', ' ')),
                         i.narrative) AS summary
        FROM site_issues i
        WHERE i.site_id IS NOT NULL
        """,
    ),
    (
        "labour_attendance_reports",
        "labour_report",
        """
        SELECT r.id AS source_id, r.id AS fact_id, r.organization_id, r.project_id, r.site_id,
               r.occurred_date AS fact_date, r.created_at,
               'Labour attendance' AS summary
        FROM labour_attendance_reports r
        WHERE r.voided_at IS NULL AND r.site_id IS NOT NULL
        """,
    ),
    (
        "material_receipts",
        "material_receipt",
        """
        SELECT m.id AS source_id, m.id AS fact_id, m.organization_id, m.project_id, m.site_id,
               m.occurred_date AS fact_date, m.created_at,
               concat_ws(' ', 'Received', trim(to_char(m.quantity, 'FM999999990.##')), m.unit,
                         m.material_name) AS summary
        FROM material_receipts m
        WHERE m.reverses_movement_id IS NULL AND m.site_id IS NOT NULL
        """,
    ),
    (
        "material_usage",
        "material_usage",
        """
        SELECT m.id AS source_id, m.id AS fact_id, m.organization_id, m.project_id, m.site_id,
               m.occurred_date AS fact_date, m.created_at,
               concat_ws(' ', 'Used', trim(to_char(m.quantity, 'FM999999990.##')), m.unit,
                         m.material_name) AS summary
        FROM material_usage m
        WHERE m.reverses_movement_id IS NULL AND m.site_id IS NOT NULL
        """,
    ),
)


@dataclass(frozen=True, slots=True)
class LateEntryResult:
    recorded: int
    reopened_days: int
    revised_days: int


def outcome_for(*, day_status: str, sent: bool) -> str:
    """Reopen while the report hasn't gone out; otherwise record a revision."""
    if day_status == site_day.PUBLISHED or sent:
        return REVISED
    return REOPENED


async def process_late_entries(
    conn: AsyncConnection, *, today: dt.date | None = None
) -> LateEntryResult:
    """Find entries created after their (frozen) site day's version was built,
    record each once, and reopen or revise that day."""
    since = (today or dt.date.today()) - dt.timedelta(days=LOOKBACK_DAYS)
    found: list[dict[str, Any]] = []
    for table, fact_type, source_sql in _SOURCES:
        rows = (
            (
                await conn.execute(
                    text(
                        f"""
                    WITH src AS ({source_sql})
                    SELECT src.*, dr.id AS daily_report_id, dr.status::text AS day_status,
                           (p.dpr_last_sent_on IS NOT NULL
                            AND p.dpr_last_sent_on >= src.fact_date) AS sent
                    FROM src
                    JOIN daily_reports dr
                      ON dr.organization_id = src.organization_id
                     AND dr.site_id = src.site_id
                     AND dr.report_date = src.fact_date
                     AND dr.level::text = 'SITE'
                    JOIN daily_report_versions v ON v.id = dr.current_version_id
                    JOIN projects p ON p.id = dr.project_id
                    WHERE dr.status::text = ANY(:frozen)
                      AND src.fact_date >= :since
                      AND src.created_at > v.created_at
                      AND NOT EXISTS (
                          SELECT 1 FROM late_entries le
                          WHERE le.source_table = :table AND le.source_id = src.source_id
                      )
                    """
                    ),
                    {"frozen": sorted(site_day.FROZEN), "since": since, "table": table},
                )
            )
            .mappings()
            .all()
        )
        found.extend({**row, "source_table": table, "fact_type": fact_type} for row in rows)

    days: dict[uuid.UUID, list[dict[str, Any]]] = {}
    for row in found:
        days.setdefault(row["daily_report_id"], []).append(row)

    reopened = revised = 0
    for report_id, entries in days.items():
        first = entries[0]
        outcome = outcome_for(day_status=first["day_status"], sent=bool(first["sent"]))
        for entry in entries:
            await conn.execute(
                text(
                    """
                    INSERT INTO late_entries (
                        id, organization_id, project_id, site_id, report_date, daily_report_id,
                        source_table, source_id, fact_type, fact_id, entry_created_at, outcome,
                        summary
                    ) VALUES (
                        :id, :org, :project, :site, :date, :report, :table, :source_id,
                        :fact_type, :fact_id, :created_at, :outcome, :summary
                    )
                    ON CONFLICT ON CONSTRAINT uq_late_entries_source DO NOTHING
                    """
                ),
                {
                    "id": uuid.uuid4(),
                    "org": entry["organization_id"],
                    "project": entry["project_id"],
                    "site": entry["site_id"],
                    "date": entry["fact_date"],
                    "report": report_id,
                    "table": entry["source_table"],
                    "source_id": entry["source_id"],
                    "fact_type": entry["fact_type"],
                    "fact_id": entry["fact_id"],
                    "created_at": entry["created_at"],
                    "outcome": outcome,
                    "summary": (entry["summary"] or "")[:300] or None,
                },
            )
        await _revise_day(conn, first, entries, outcome)
        if outcome == REOPENED:
            reopened += 1
        else:
            revised += 1
        _log.info(
            "dpr.late_entries site=%s date=%s count=%d outcome=%s",
            first["site_id"],
            first["fact_date"],
            len(entries),
            outcome,
        )
    return LateEntryResult(recorded=len(found), reopened_days=reopened, revised_days=revised)


async def _revise_day(
    conn: AsyncConnection, day: dict[str, Any], entries: list[dict[str, Any]], outcome: str
) -> None:
    from mesiri.infrastructure.postgres.repositories.dpr import PostgresDprRepository

    repo = PostgresDprRepository(conn)
    payload = await repo.assemble_site_report_payload(
        organization_id=day["organization_id"],
        project_id=day["project_id"],
        site_id=day["site_id"],
        report_date=day["fact_date"],
    )
    listed = "; ".join(e["summary"] or e["fact_type"] for e in entries[:5])
    more = f" and {len(entries) - 5} more" if len(entries) > 5 else ""
    await repo.revise_version(
        daily_report_id=day["daily_report_id"],
        payload=payload,
        narrative_summary=None,
        revision_reason=f"late entry: {listed}{more}"[:500],
        reset_status=outcome == REOPENED,
    )


#: WA-77 (Alan, 25 Oct): a late entry still waiting for its Save is not
#: listed in a report, nor claimed by one, until it is saved.
_SAVED = fact_review.counted_sql_by_column("late_entries.fact_type", "late_entries.fact_id")


async def late_entries_for_report(
    conn: AsyncConnection,
    *,
    organization_id: Any,
    site_id: Any,
    report_date: dt.date,
    report_id: Any | None,
) -> list[dict[str, Any]]:
    """What a site report lists under "Late entries for earlier days":
    earlier days' late entries not yet shown in another report (or shown in
    this one)."""
    rows = (
        (
            await conn.execute(
                text(
                    f"""
                SELECT report_date, summary, fact_type, outcome, entry_created_at
                FROM late_entries
                WHERE organization_id = :org AND site_id = :site AND report_date < :date
                  AND (shown_in_report_id IS NULL OR shown_in_report_id = :report_id)
                  AND {_SAVED}
                ORDER BY report_date, entry_created_at
                """
                ),
                {
                    "org": organization_id,
                    "site": site_id,
                    "date": report_date,
                    "report_id": report_id,
                },
            )
        )
        .mappings()
        .all()
    )
    return [
        {
            "report_date": r["report_date"].isoformat(),
            "summary": r["summary"] or r["fact_type"].replace("_", " "),
            "outcome": r["outcome"],
        }
        for r in rows
    ]


async def claim_for_report(
    conn: AsyncConnection,
    *,
    organization_id: Any,
    site_id: Any,
    report_date: dt.date,
    report_id: Any,
    actor_user_id: Any | None,
) -> int:
    """When a site day is confirmed: the earlier days' late entries it lists
    are now shown (once), and their drafts are confirmed with it. A day that
    was reopened for late entries also claims those, since re-confirming the
    day puts them in its own report (so the next day doesn't list them)."""
    rows = (
        (
            await conn.execute(
                text(
                    f"""
                UPDATE late_entries SET shown_in_report_id = :report_id
                WHERE organization_id = :org AND site_id = :site
                  AND (report_date < :date
                       OR (report_date = :date AND outcome = 'reopened'))
                  AND shown_in_report_id IS NULL
                  AND {_SAVED}
                RETURNING fact_type, fact_id
                """
                ),
                {
                    "org": organization_id,
                    "site": site_id,
                    "date": report_date,
                    "report_id": report_id,
                },
            )
        )
        .mappings()
        .all()
    )
    if not rows:
        return 0
    from mesiri.infrastructure.postgres.repositories.fact_reviews import (
        PostgresFactReviewRepository,
    )

    reviews = PostgresFactReviewRepository(conn)
    for fact_type, fact_id in {(r["fact_type"], r["fact_id"]) for r in rows}:
        try:
            async with conn.begin_nested():
                await reviews.confirm(
                    organization_id=organization_id,
                    fact_type=fact_type,
                    fact_id=fact_id,
                    actor_user_id=actor_user_id,
                )
        except Exception:  # noqa: BLE001 -- a withdrawn item has nothing to confirm
            _log.info("dpr.late_entry_confirm_skipped fact=%s:%s", fact_type, fact_id)
    return len(rows)


async def is_recorded_late(conn: AsyncConnection, *, fact_type: str, fact_id: Any) -> bool:
    """Whether this item is a recorded late entry (it was never in the frozen
    version, so withdrawing it can't change what was confirmed)."""
    row = (
        await conn.execute(
            text("SELECT 1 FROM late_entries WHERE fact_type = :t AND fact_id = :id LIMIT 1"),
            {"t": fact_type, "id": fact_id},
        )
    ).first()
    return row is not None


async def day_status_for_fact(
    conn: AsyncConnection, *, organization_id: Any, site_id: Any, fact_date: dt.date
) -> str | None:
    """For the WhatsApp reply: None (day open), REOPENED or REVISED -- what
    the late-entry check will do with an entry for this day."""
    row = (
        (
            await conn.execute(
                text(
                    """
                SELECT dr.status::text AS status,
                       (p.dpr_last_sent_on IS NOT NULL AND p.dpr_last_sent_on >= :date) AS sent
                FROM daily_reports dr JOIN projects p ON p.id = dr.project_id
                WHERE dr.organization_id = :org AND dr.site_id = :site
                  AND dr.report_date = :date AND dr.level::text = 'SITE'
                """
                ),
                {"org": organization_id, "site": site_id, "date": fact_date},
            )
        )
        .mappings()
        .first()
    )
    if row is None or row["status"] not in site_day.FROZEN:
        return None
    return outcome_for(day_status=row["status"], sent=bool(row["sent"]))
