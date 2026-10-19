"""Per-project auto-DPR: the backend half of making `projects.
auto_generate_dpr` actually do something.

Two moments a day (BE-16): at `reporting_cutoff_time` the drafts are built
(`generate_project_dpr`); the project DPR is SENT later, once every site is
confirmed or at `dpr_send_deadline` (`due_project_sends` /
`finalize_project_dpr` / `mark_project_dpr_sent`, further down).

Until this module existed, `auto_generate_dpr`/`reporting_cutoff_time`/
`reporting_timezone` (migration 0260) were dashboard-editable but never
read anywhere -- toggling "auto-generate DPR" on a project changed nothing.
This is the DB-facing half (finding due projects, generating today's DPR
for one); the scheduler-facing half (recipients, notification queuing,
`is_due` timing, the tick loop itself) lives on the assistant side at
runtime/project_auto_dpr.py, same capability-boundary split
run_dpr_generation.py's own module docstring describes (backend assembles
+ writes daily_reports rows; the assistant renders/sends).

Deliberately narrower than scripts/run_dpr_generation.py's nightly sweep:
that script (still ops-cron-driven, unconnected to any per-project setting)
regenerates every org's site+project reports on ONE fixed daily schedule.
This module generates ONE project's own SITE-level drafts (for its own
active sites with today's activity) and PROJECT-level rollup, called only
when that project's own `is_due()` check (reporting_cutoff_time/timezone)
says it's time -- so a project set to 6pm IST gets its DPR at 6pm IST,
independent of whenever the ops cron happens to run.
"""

from __future__ import annotations

import datetime
import json
import uuid
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa

from mesiri.application.automations.scheduling import is_due, local_now, parse_time_of_day
from mesiri.application.dpr import site_day
from mesiri.domains.organizations.lifecycle import operational_sql
from mesiri.infrastructure.postgres.repositories.dpr import PostgresDprRepository

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection


async def due_projects_for_auto_dpr(
    conn: AsyncConnection, *, now_utc: datetime.datetime
) -> list[dict[str, Any]]:
    """Every project with auto_generate_dpr=true whose own reporting_cutoff_
    time/reporting_timezone says it's due, and hasn't already fired for its
    own local date (auto_dpr_last_run_on). Archived projects, and projects
    in a company that may not use Mesiri right now (suspended, or a trial
    that has expired), are excluded -- lifecycle.operational_sql, the same
    rule every other "is this company active?" check uses."""
    rows = (
        await conn.execute(
            sa.text(
                f"""
                SELECT p.id, p.organization_id, p.reporting_cutoff_time,
                       p.reporting_timezone, p.auto_dpr_last_run_on
                FROM projects p
                JOIN organizations o ON o.id = p.organization_id
                WHERE p.auto_generate_dpr = true
                  AND p.status != 'archived'
                  AND {operational_sql("o")}
                """
            )
        )
    ).mappings().all()

    due: list[dict[str, Any]] = []
    for row in rows:
        if is_due(
            frequency="DAILY",
            day_of_week=None,
            time_of_day=row["reporting_cutoff_time"] or "18:00",
            timezone_name=row["reporting_timezone"] or "UTC",
            last_run_on=row["auto_dpr_last_run_on"],
            now_utc=now_utc,
        ):
            due.append(dict(row))
    return due


async def _sites_with_activity_for_project(
    conn: AsyncConnection,
    *,
    organization_id: uuid.UUID,
    project_id: uuid.UUID,
    report_date: datetime.date,
) -> list[uuid.UUID]:
    """Mirrors scripts/run_dpr_generation.py's `_sites_with_activity`,
    narrowed to one project -- same UNION of activities/site_issues, same
    "logged something today" definition of "needs a SITE-level draft"."""
    rows = (
        await conn.execute(
            sa.text(
                """
                SELECT DISTINCT site_id FROM activities
                WHERE organization_id = :org_id AND project_id = :project_id
                  AND activity_date = :report_date AND deleted_at IS NULL
                UNION
                SELECT DISTINCT site_id FROM site_issues
                WHERE organization_id = :org_id AND project_id = :project_id
                  AND occurred_at::date = :report_date
                """
            ),
            {
                "org_id": organization_id,
                "project_id": project_id,
                "report_date": report_date,
            },
        )
    ).mappings().all()
    return [row["site_id"] for row in rows]


async def generate_project_dpr(
    conn: AsyncConnection,
    *,
    organization_id: uuid.UUID,
    project_id: uuid.UUID,
    report_date: datetime.date,
) -> bool:
    """Generates today's SITE-level DRAFT for each of this project's active
    sites with logged activity, then the PROJECT-level rollup -- mirrors
    scripts/run_dpr_generation.py's two passes exactly, scoped to one
    project instead of every org. Re-running for the same project+date is
    safe (P7): an already-APPROVED/PUBLISHED version is left untouched
    (`create_version` raises `ValueError`, caught and skipped here, same as
    the nightly script does).

    Returns True if the PROJECT-level rollup was (re)generated, False if it
    was already frozen (APPROVED/PUBLISHED) and nothing changed -- the
    caller still has something to notify about either way (the existing
    version), this only distinguishes "fresh" from "already there"."""
    repo = PostgresDprRepository(conn)

    for site_id in await _sites_with_activity_for_project(
        conn, organization_id=organization_id, project_id=project_id, report_date=report_date
    ):
        payload = await repo.assemble_site_report_payload(
            organization_id=organization_id,
            project_id=project_id,
            site_id=site_id,
            report_date=report_date,
        )
        daily_report_id = await repo.get_or_create_daily_report(
            organization_id=organization_id,
            project_id=project_id,
            site_id=site_id,
            report_date=report_date,
        )
        try:
            # The project's cutoff has passed, so each day is labelled
            # needs details or ready (BE-08).
            await repo.create_version(
                daily_report_id=daily_report_id, payload=payload, evaluate_readiness=True
            )
        except ValueError:
            continue

    # Sites that logged no activity still get their day, labelled, so the
    # evening gap-check has something to ask about.
    await repo.open_site_days(
        organization_id=organization_id, project_id=project_id, report_date=report_date
    )

    payload, sources = await repo.assemble_project_report_payload(
        organization_id=organization_id, project_id=project_id, report_date=report_date
    )
    project_daily_report_id = await repo.get_or_create_project_daily_report(
        organization_id=organization_id, project_id=project_id, report_date=report_date
    )
    try:
        version = await repo.create_version(daily_report_id=project_daily_report_id, payload=payload)
    except ValueError:
        return False
    await repo.record_project_sources(project_version_id=version["id"], sources=sources)
    return True


# ---------------------------------------------------------------------------
# Sending the project DPR (BE-16)
#
# The cutoff above only builds drafts. The project DPR goes to the owner/PM
# once every site's engineer has confirmed, or at the project's send
# deadline, or when someone presses "Send now" -- whichever comes first --
# with an unconfirmed site shown as "Not reported" (P8). A single-site
# project sends its confirmed site DPR itself: nobody approves twice.
#
# The backend decides and prepares; the WhatsApp side
# (runtime/project_auto_dpr.py) renders the PDF, sends it, then calls
# `mark_project_dpr_sent` -- the backend never talks to Meta.
# ---------------------------------------------------------------------------


def send_reason(
    *,
    site_statuses: list[str | None],
    local_now: datetime.datetime,
    send_deadline: str | None,
    requested: bool,
    auto_enabled: bool,
) -> str | None:
    """Why the project DPR should go out now -- "requested", "all_confirmed"
    or "deadline" -- or None. Pure. A project with no active site has
    nothing to send. "Send now" works even with the automatic DPR off."""
    if not site_statuses:
        return None
    if requested:
        return "requested"
    if not auto_enabled:
        return None
    if all(status in site_day.FROZEN for status in site_statuses):
        return "all_confirmed"
    try:
        deadline = parse_time_of_day(send_deadline or "21:00")
    except (ValueError, IndexError):
        deadline = parse_time_of_day("21:00")
    if local_now.time() >= deadline:
        return "deadline"
    return None


async def due_project_sends(
    conn: AsyncConnection, *, now_utc: datetime.datetime
) -> list[dict[str, Any]]:
    """Every project whose DPR should be sent now and has not been sent for
    its own local date yet. Same company/archived rules as the cutoff."""
    projects = (
        await conn.execute(
            sa.text(
                f"""
                SELECT p.id, p.organization_id, p.reporting_timezone, p.auto_generate_dpr,
                       p.dpr_send_deadline, p.dpr_last_sent_on, p.dpr_send_requested_on
                FROM projects p
                JOIN organizations o ON o.id = p.organization_id
                WHERE (p.auto_generate_dpr = true OR p.dpr_send_requested_on IS NOT NULL)
                  AND p.status != 'archived'
                  AND {operational_sql("o")}
                """
            )
        )
    ).mappings().all()

    due: list[dict[str, Any]] = []
    for project in projects:
        local = local_now(timezone_name=project["reporting_timezone"] or "UTC", now_utc=now_utc)
        report_date = local.date()
        if project["dpr_last_sent_on"] == report_date:
            continue
        site_rows = (
            await conn.execute(
                sa.text(
                    """
                    SELECT dr.status::text AS status
                    FROM sites s
                    LEFT JOIN daily_reports dr
                      ON dr.site_id = s.id AND dr.level = 'SITE' AND dr.report_date = :report_date
                    WHERE s.organization_id = :org_id AND s.project_id = :project_id
                      AND s.status = 'active'
                    """
                ),
                {
                    "org_id": project["organization_id"],
                    "project_id": project["id"],
                    "report_date": report_date,
                },
            )
        ).mappings().all()
        reason = send_reason(
            site_statuses=[row["status"] for row in site_rows],
            local_now=local,
            send_deadline=project["dpr_send_deadline"],
            requested=project["dpr_send_requested_on"] == report_date,
            auto_enabled=bool(project["auto_generate_dpr"]),
        )
        if reason is not None:
            due.append(
                {
                    "id": project["id"],
                    "organization_id": project["organization_id"],
                    "report_date": report_date,
                    "reason": reason,
                }
            )
    return due


async def finalize_project_dpr(
    conn: AsyncConnection,
    *,
    organization_id: uuid.UUID,
    project_id: uuid.UUID,
    report_date: datetime.date,
) -> dict[str, Any] | None:
    """The report to send for this project and date, made ready: confirmed
    and with a version. Returns {"daily_report_id", "site_id", "level"}, or
    None when the project has no active site.

    Single-site project whose site is confirmed -> that site DPR. Otherwise
    the PROJECT roll-up, built only from confirmed site DPRs (P8), each
    unconfirmed site recorded as not reported, and marked APPROVED by
    composition -- nobody approves the same day twice. Safe to call again:
    an already-confirmed roll-up is returned as it is (a send that failed
    half-way is retried without rebuilding the report)."""
    repo = PostgresDprRepository(conn)
    site_rows = (
        await conn.execute(
            sa.text(
                """
                SELECT id FROM sites
                WHERE organization_id = :org_id AND project_id = :project_id AND status = 'active'
                """
            ),
            {"org_id": organization_id, "project_id": project_id},
        )
    ).mappings().all()
    if not site_rows:
        return None

    if len(site_rows) == 1:
        site_id = site_rows[0]["id"]
        day = await repo.find_site_report(
            organization_id=organization_id,
            project_id=project_id,
            site_id=site_id,
            report_date=report_date,
        )
        if day is not None and day["status"] in site_day.FROZEN:
            return {"daily_report_id": day["id"], "site_id": site_id, "level": "SITE"}

    report_id = await repo.get_or_create_project_daily_report(
        organization_id=organization_id, project_id=project_id, report_date=report_date
    )
    status_row = (
        await conn.execute(
            sa.text("SELECT status::text AS status FROM daily_reports WHERE id = :id"),
            {"id": report_id},
        )
    ).mappings().first()
    if status_row is None or status_row["status"] not in site_day.FROZEN:
        payload, sources = await repo.assemble_project_report_payload(
            organization_id=organization_id, project_id=project_id, report_date=report_date
        )
        version = await repo.create_version(daily_report_id=report_id, payload=payload)
        await repo.record_project_sources(project_version_id=version["id"], sources=sources)
        await conn.execute(
            sa.text("UPDATE daily_reports SET status = 'APPROVED', updated_at = now() WHERE id = :id"),
            {"id": report_id},
        )
        await conn.execute(
            sa.text("UPDATE daily_report_versions SET approved_at = now() WHERE id = :id"),
            {"id": version["id"]},
        )
    return {"daily_report_id": report_id, "site_id": None, "level": "PROJECT"}


async def mark_project_dpr_sent(
    conn: AsyncConnection,
    *,
    project_id: uuid.UUID,
    report_date: datetime.date,
    daily_report_id: uuid.UUID,
) -> None:
    """After the WhatsApp side has queued the DPR: the sent report and every
    confirmed site day it carried become "sent" (PUBLISHED), and the project
    is marked sent for that date so it goes once a day."""
    await conn.execute(
        sa.text(
            "UPDATE daily_reports SET status = 'PUBLISHED', updated_at = now() "
            "WHERE id = :id AND status = 'APPROVED'"
        ),
        {"id": daily_report_id},
    )
    await conn.execute(
        sa.text(
            """
            UPDATE daily_reports SET status = 'PUBLISHED', updated_at = now()
            WHERE project_id = :project_id AND report_date = :report_date
              AND level = 'SITE' AND status = 'APPROVED'
            """
        ),
        {"project_id": project_id, "report_date": report_date},
    )
    await conn.execute(
        sa.text(
            "UPDATE projects SET dpr_last_sent_on = :report_date, dpr_send_requested_on = NULL "
            "WHERE id = :id"
        ),
        {"report_date": report_date, "id": project_id},
    )


async def request_project_dpr_send(
    conn: AsyncConnection, *, organization_id: uuid.UUID, project_id: uuid.UUID, now_utc: datetime.datetime
) -> datetime.date | None:
    """"Send now": asks the sender to send today's project DPR on its next
    tick (within about a minute), marking unconfirmed sites not reported.
    Returns the project's local date, or None if the project is not found.
    Refuses (ValueError) when today's DPR has already been sent."""
    row = (
        await conn.execute(
            sa.text(
                "SELECT reporting_timezone, dpr_last_sent_on FROM projects "
                "WHERE organization_id = :org_id AND id = :id"
            ),
            {"org_id": organization_id, "id": project_id},
        )
    ).mappings().first()
    if row is None:
        return None
    report_date = local_now(timezone_name=row["reporting_timezone"] or "UTC", now_utc=now_utc).date()
    if row["dpr_last_sent_on"] == report_date:
        raise ValueError("today's DPR for this project has already been sent")
    await conn.execute(
        sa.text("UPDATE projects SET dpr_send_requested_on = :d WHERE id = :id"),
        {"d": report_date, "id": project_id},
    )
    return report_date


async def mark_project_auto_dpr_run(
    conn: AsyncConnection, *, project_id: uuid.UUID, ran_on: datetime.date
) -> None:
    await conn.execute(
        sa.text("UPDATE projects SET auto_dpr_last_run_on = :ran_on WHERE id = :id"),
        {"ran_on": ran_on, "id": project_id},
    )


# ---------------------------------------------------------------------------
# The evening review (WA-04)
#
# Between the cutoff (drafts built, each site day labelled) and the send
# deadline, each site's engineer is messaged about their day -- what is
# missing, or that it is ready to confirm (application/dpr/evening_review.py).
# What they send in reply is saved as usual; `refresh_site_day` then brings
# the day up to date, so a filled gap turns the day ready within a tick.
# ---------------------------------------------------------------------------

_DEFAULT_SEND_DEADLINE = "21:00"


def send_deadline_or_default(value: str | None) -> str:
    """The project's send deadline ("HH:MM"), or 21:00 when unset or bad."""
    try:
        parse_time_of_day(value or _DEFAULT_SEND_DEADLINE)
    except (ValueError, IndexError):
        return _DEFAULT_SEND_DEADLINE
    return value or _DEFAULT_SEND_DEADLINE


async def projects_in_review_window(
    conn: AsyncConnection, *, now_utc: datetime.datetime
) -> list[dict[str, Any]]:
    """Projects whose day is under review right now: the automatic DPR's
    cutoff has run for today (local date), the DPR has not been sent yet,
    and the send deadline has not passed. Same company/archived rules as
    the cutoff."""
    rows = (
        await conn.execute(
            sa.text(
                f"""
                SELECT p.id, p.organization_id, p.name, p.reporting_timezone,
                       p.dpr_send_deadline, p.auto_dpr_last_run_on, p.dpr_last_sent_on
                FROM projects p
                JOIN organizations o ON o.id = p.organization_id
                WHERE p.auto_generate_dpr = true
                  AND p.status != 'archived'
                  AND {operational_sql("o")}
                """
            )
        )
    ).mappings().all()

    window: list[dict[str, Any]] = []
    for row in rows:
        local = local_now(timezone_name=row["reporting_timezone"] or "UTC", now_utc=now_utc)
        report_date = local.date()
        if row["auto_dpr_last_run_on"] != report_date or row["dpr_last_sent_on"] == report_date:
            continue
        deadline = send_deadline_or_default(row["dpr_send_deadline"])
        if local.time() >= parse_time_of_day(deadline):
            continue
        window.append(
            {
                "id": row["id"],
                "organization_id": row["organization_id"],
                "name": row["name"],
                "report_date": report_date,
                "send_deadline": deadline,
            }
        )
    return window


async def site_days_for_review(
    conn: AsyncConnection,
    *,
    organization_id: uuid.UUID,
    project_id: uuid.UUID,
    report_date: datetime.date,
) -> list[dict[str, Any]]:
    """Every active site of the project with its day: status, missing
    sections, when the day was last labelled, when anything was last saved
    on it, and whether anything was saved at all. Labour is read only."""
    rows = (
        await conn.execute(
            sa.text(
                """
                WITH facts AS (
                    SELECT site_id, created_at AS at, true AS live FROM fact_reviews
                     WHERE organization_id = :org_id AND fact_date = :d
                    UNION ALL
                    SELECT site_id, updated_at, deleted_at IS NULL FROM activities
                     WHERE organization_id = :org_id AND activity_date = :d
                    UNION ALL
                    SELECT site_id, updated_at, true FROM site_issues
                     WHERE organization_id = :org_id AND occurred_at::date = :d
                    UNION ALL
                    SELECT site_id, GREATEST(created_at, voided_at), voided_at IS NULL
                      FROM labour_attendance_reports
                     WHERE organization_id = :org_id AND occurred_date = :d
                    UNION ALL
                    SELECT site_id, updated_at, true FROM material_receipts
                     WHERE organization_id = :org_id AND occurred_date = :d
                    UNION ALL
                    SELECT site_id, updated_at, true FROM material_usage
                     WHERE organization_id = :org_id AND occurred_date = :d
                )
                SELECT s.id AS site_id, s.name AS site_name,
                       dr.id AS daily_report_id, dr.status::text AS status,
                       dr.missing_sections, dr.updated_at AS day_updated_at,
                       (SELECT max(f.at) FROM facts f WHERE f.site_id = s.id) AS last_fact_at,
                       EXISTS (SELECT 1 FROM facts f WHERE f.site_id = s.id AND f.live)
                         AS has_facts
                FROM sites s
                LEFT JOIN daily_reports dr
                  ON dr.site_id = s.id AND dr.level = 'SITE' AND dr.report_date = :d
                WHERE s.organization_id = :org_id AND s.project_id = :project_id
                  AND s.status = 'active'
                ORDER BY s.name
                """
            ),
            {"org_id": organization_id, "project_id": project_id, "d": report_date},
        )
    ).mappings().all()
    days = []
    for row in rows:
        day = dict(row)
        if isinstance(day["missing_sections"], str):
            day["missing_sections"] = json.loads(day["missing_sections"])
        days.append(day)
    return days


async def refresh_site_day(
    conn: AsyncConnection,
    *,
    organization_id: uuid.UUID,
    project_id: uuid.UUID,
    site_id: uuid.UUID,
    report_date: datetime.date,
) -> dict[str, Any] | None:
    """Bring a site day up to date after the cutoff, e.g. once the engineer
    has sent the labour count the gap-check asked for. A new version only
    when the payload changed; a day with nothing recorded is only
    labelled. Leaves a confirmed day alone (P7). Returns the day's
    {"status", "missing_sections"}, or None for a confirmed day."""
    from mesiri.application.dpr import evening_review

    repo = PostgresDprRepository(conn)
    daily_report_id = await repo.get_or_create_daily_report(
        organization_id=organization_id,
        project_id=project_id,
        site_id=site_id,
        report_date=report_date,
    )
    row = (
        await conn.execute(
            sa.text(
                """
                SELECT dr.status::text AS status, dr.current_version_id, v.payload
                FROM daily_reports dr
                LEFT JOIN daily_report_versions v ON v.id = dr.current_version_id
                WHERE dr.id = :id
                """
            ),
            {"id": daily_report_id},
        )
    ).mappings().first()
    if row is None or row["status"] in site_day.FROZEN:
        return None

    payload = await repo.assemble_site_report_payload(
        organization_id=organization_id,
        project_id=project_id,
        site_id=site_id,
        report_date=report_date,
    )
    current = row["payload"]
    if isinstance(current, str):
        current = json.loads(current)
    if row["current_version_id"] is not None and current == json.loads(json.dumps(payload)):
        # Nothing new: just note that the day was looked at.
        await conn.execute(
            sa.text("UPDATE daily_reports SET updated_at = now() WHERE id = :id"),
            {"id": daily_report_id},
        )
    elif row["current_version_id"] is not None or evening_review.has_content(payload):
        await repo.create_version(
            daily_report_id=daily_report_id, payload=payload, evaluate_readiness=True
        )
    else:
        await repo.label_site_day(daily_report_id=daily_report_id, payload=payload)

    status_row = (
        await conn.execute(
            sa.text(
                "SELECT status::text AS status, missing_sections FROM daily_reports WHERE id = :id"
            ),
            {"id": daily_report_id},
        )
    ).mappings().first()
    missing = status_row["missing_sections"]
    if isinstance(missing, str):
        missing = json.loads(missing)
    return {"status": status_row["status"], "missing_sections": missing}


async def site_day_reporters(
    conn: AsyncConnection,
    *,
    organization_id: uuid.UUID,
    site_id: uuid.UUID,
    report_date: datetime.date,
) -> list[str]:
    """Who saved drafts on the site's day -- the evening message's
    recipients when the site has no engineer."""
    rows = (
        await conn.execute(
            sa.text(
                """
                SELECT DISTINCT fr.actor_user_id FROM fact_reviews fr
                JOIN users u ON u.id = fr.actor_user_id AND lower(u.status) = 'active'
                WHERE fr.organization_id = :org_id AND fr.site_id = :site_id
                  AND fr.fact_date = :d AND fr.state = 'draft'
                """
            ),
            {"org_id": organization_id, "site_id": site_id, "d": report_date},
        )
    ).mappings().all()
    return sorted(str(row["actor_user_id"]) for row in rows)


async def site_day_for_confirm(
    conn: AsyncConnection,
    *,
    organization_id: uuid.UUID,
    site_id: uuid.UUID,
    report_date: datetime.date,
) -> dict[str, Any] | None:
    """What the evening confirmation (WA-05) needs about a site day: its
    report id and status, the current version's payload, and each draft
    still on it with what the AI read ({"confidence", "fields"}). None
    when the day has no report yet."""
    day = (
        await conn.execute(
            sa.text(
                """
                SELECT dr.id AS daily_report_id, dr.status::text AS status, v.payload
                FROM daily_reports dr
                LEFT JOIN daily_report_versions v ON v.id = dr.current_version_id
                WHERE dr.organization_id = :org_id AND dr.site_id = :site_id
                  AND dr.level = 'SITE' AND dr.report_date = :d
                """
            ),
            {"org_id": organization_id, "site_id": site_id, "d": report_date},
        )
    ).mappings().first()
    if day is None:
        return None
    drafts = (
        await conn.execute(
            sa.text(
                """
                SELECT e.confidence, e.extracted -> 'fields' AS fields FROM (
                    SELECT DISTINCT ON (fact_type, fact_id) state, extraction_id
                    FROM fact_reviews
                    WHERE organization_id = :org_id AND site_id = :site_id
                      AND fact_date = :d
                    ORDER BY fact_type, fact_id, created_at DESC
                ) latest
                LEFT JOIN extractions e ON e.id = latest.extraction_id
                WHERE latest.state = 'draft'
                """
            ),
            {"org_id": organization_id, "site_id": site_id, "d": report_date},
        )
    ).mappings().all()
    payload = day["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    return {
        "daily_report_id": day["daily_report_id"],
        "status": day["status"],
        "payload": payload or {},
        "drafts": [
            {
                "confidence": row["confidence"],
                "fields": json.loads(row["fields"]) if isinstance(row["fields"], str) else row["fields"],
            }
            for row in drafts
        ],
    }
