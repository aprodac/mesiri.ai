"""Per-project auto-DPR: the backend half of making `projects.
auto_generate_dpr` actually do something.

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
import uuid
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa

from mesiri.application.automations.scheduling import is_due
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
            await repo.create_version(daily_report_id=daily_report_id, payload=payload)
        except ValueError:
            continue

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


async def mark_project_auto_dpr_run(
    conn: AsyncConnection, *, project_id: uuid.UUID, ran_on: datetime.date
) -> None:
    await conn.execute(
        sa.text("UPDATE projects SET auto_dpr_last_run_on = :ran_on WHERE id = :id"),
        {"ran_on": ran_on, "id": project_id},
    )
