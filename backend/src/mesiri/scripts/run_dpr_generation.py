"""Generates/refreshes a SITE-level DPR draft for every site that logged
activity or a site issue on the target date, then a PROJECT-level roll-up
for every project with at least one active site (#16 Daily Report
Generation, ADR-D9/P8).

Invocable manually or via a cron entry -- not a persistent worker service,
same convention as run_notification_checks.py and project_timeline_events.py.
This is the BACKEND half only: it assembles the payload and writes
daily_reports/daily_report_versions rows. It never renders a PDF or sends
anything -- Playwright lives on the assistant side (ADR-D8), and the
backend must not know about Meta's Cloud API. The assistant-side render
script is runtime/render_pending_dpr_pdfs.py.

Re-running for the same site+date is safe and expected: it inserts a new
DRAFT version reflecting whatever has been logged since the last run
(P1 append-only facts, P7 freeze-on-approval -- create_version refuses to
touch an already-APPROVED/PUBLISHED report, see dpr.py). This is the
natural way an engineer's afternoon updates show up in the same day's DPR
without a separate "regenerate" trigger.

The PROJECT-level pass runs for every project with an active site,
regardless of whether every one of its sites has an approved SITE version
yet -- P8's "cutoff" model: a site that hasn't reported is recorded
NOT_REPORTED on the roll-up, not something the whole project's reporting
waits on. It also runs after ALL sites' SITE-level generation for the
date, so same-day project rollups see whatever sites did get generated in
this same run.

Recommended VPS crontab entry (ops-managed, not tracked in this repo):
    0 20 * * * cd /opt/mesiri/backend && \\
        PYTHONPATH=/opt/mesiri/shared/contracts/src:/opt/mesiri/platform/ai/src:/opt/mesiri/backend/src \\
        /opt/mesiri/.venv/bin/python -m mesiri.scripts.run_dpr_generation \\
        >> /var/log/mesiri/dpr-generation.log 2>&1

Run:  python -m mesiri.scripts.run_dpr_generation [YYYY-MM-DD]
"""

from __future__ import annotations

import asyncio
import datetime
import sys
import uuid

from ..bootstrap.settings import Settings
from ..domains.organizations.lifecycle import operational_sql
from ..infrastructure.postgres.database import PostgresDatabase
from ..infrastructure.postgres.repositories.dpr import PostgresDprRepository


async def _projects_with_active_sites(conn, *, organization_id: uuid.UUID):
    from sqlalchemy import text

    rows = (
        await conn.execute(
            text(
                "SELECT DISTINCT project_id FROM sites "
                "WHERE organization_id = :org_id AND status = 'active'"
            ),
            {"org_id": organization_id},
        )
    ).mappings().all()
    return [row["project_id"] for row in rows]


async def _sites_with_activity(conn, *, organization_id: uuid.UUID, report_date: datetime.date):
    from sqlalchemy import text

    rows = (
        await conn.execute(
            text(
                """
                SELECT DISTINCT project_id, site_id FROM activities
                WHERE organization_id = :org_id AND activity_date = :report_date
                  AND deleted_at IS NULL
                UNION
                SELECT DISTINCT project_id, site_id FROM site_issues
                WHERE organization_id = :org_id AND occurred_at::date = :report_date
                """
            ),
            {"org_id": organization_id, "report_date": report_date},
        )
    ).mappings().all()
    return [(row["project_id"], row["site_id"]) for row in rows]


async def run(*, report_date: datetime.date | None = None) -> int:
    """Generates a DRAFT version for every (project, site) with activity on
    `report_date` (defaults to today) across every active organization.
    Returns the number of versions created."""
    from sqlalchemy import text

    target_date = report_date or datetime.date.today()
    settings = Settings()
    db = PostgresDatabase(settings.postgres)
    await db.connect()
    total = 0
    try:
        async with db.transaction() as conn:
            org_rows = (
                await conn.execute(text(f"SELECT id FROM organizations WHERE {operational_sql('')}"))
            ).mappings().all()
            repo = PostgresDprRepository(conn)
            for org_row in org_rows:
                organization_id = org_row["id"]
                scopes = await _sites_with_activity(
                    conn, organization_id=organization_id, report_date=target_date
                )
                for project_id, site_id in scopes:
                    payload = await repo.assemble_site_report_payload(
                        organization_id=organization_id,
                        project_id=project_id,
                        site_id=site_id,
                        report_date=target_date,
                    )
                    daily_report_id = await repo.get_or_create_daily_report(
                        organization_id=organization_id,
                        project_id=project_id,
                        site_id=site_id,
                        report_date=target_date,
                    )
                    try:
                        # Runs after the working day, so days are labelled
                        # needs details or ready (BE-08).
                        await repo.create_version(
                            daily_report_id=daily_report_id,
                            payload=payload,
                            evaluate_readiness=True,
                        )
                        total += 1
                    except ValueError:
                        # Already APPROVED/PUBLISHED -- refuse to overwrite a
                        # frozen day's payload (P7). Not a failure worth
                        # aborting the whole run over.
                        continue

                # PROJECT-level roll-up (ADR-D9/P8): runs after every site's
                # SITE-level pass above for this org+date, for every project
                # with at least one active site -- regardless of whether
                # every site has an approved version yet (a site that
                # hasn't reported is recorded NOT_REPORTED, not something
                # the project rollup waits on).
                project_ids = await _projects_with_active_sites(
                    conn, organization_id=organization_id
                )
                for project_id in project_ids:
                    # Sites that logged no activity still get their day.
                    await repo.open_site_days(
                        organization_id=organization_id,
                        project_id=project_id,
                        report_date=target_date,
                    )
                    payload, sources = await repo.assemble_project_report_payload(
                        organization_id=organization_id,
                        project_id=project_id,
                        report_date=target_date,
                    )
                    project_daily_report_id = await repo.get_or_create_project_daily_report(
                        organization_id=organization_id,
                        project_id=project_id,
                        report_date=target_date,
                    )
                    try:
                        version = await repo.create_version(
                            daily_report_id=project_daily_report_id, payload=payload
                        )
                    except ValueError:
                        continue
                    await repo.record_project_sources(
                        project_version_id=version["id"], sources=sources
                    )
                    total += 1
    finally:
        await db.disconnect()
    return total


def main() -> int:
    target: datetime.date | None = None
    if len(sys.argv) > 1:
        target = datetime.date.fromisoformat(sys.argv[1])
    total = asyncio.run(run(report_date=target))
    print(f"dpr-generation: created/refreshed {total} version(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
