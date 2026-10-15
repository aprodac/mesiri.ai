"""The owner's getting-started checklist (SS-07): GET /company/setup-progress.

Every item is worked out from what already happened, never ticked by hand:
the same setup block the superadmin's companies list shows
(application/organizations/companies_overview), so the owner and the Mesiri
team see the same progress. The one answer that isn't visible in the data,
"the default report time is fine", is POST /company/setup-progress/report-time-ok:
it records the report-time question as answered in the WhatsApp setup
questions' own record (setup_progress, SS-14), so WhatsApp doesn't ask it
again and an answer given on WhatsApp ticks the dashboard.

Kept out of router.py (already past the file-size limit) and attached to its
router, so it is served wherever /company is.
"""

from __future__ import annotations

import datetime as dt
import uuid
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.application.organizations.companies_overview import company_setup
from mesiri.domains.organizations import settings as org_settings
from mesiri.domains.organizations import setup_questions
from mesiri.domains.shared.auth import require_admin
from mesiri.infrastructure.postgres.dependency import get_db_conn
from mesiri.infrastructure.postgres.repositories.organization_settings import (
    PostgresOrganizationSettingsRepository,
)

# No prefix: included into router.py's router, which is /company.
router = APIRouter()


class FirstProject(BaseModel):
    id: uuid.UUID
    name: str
    send_time: str  # "HH:MM" in the project's timezone, when its DPR goes out


class SetupProgressResponse(BaseModel):
    has_team: bool
    has_site: bool
    has_logo: bool
    report_time_set: bool
    first_update_at: dt.datetime | None
    first_dpr_sent_at: dt.datetime | None
    # What "Report time" talks about and links to; None with no project yet.
    first_project: FirstProject | None
    effective_status: str
    trial_days_left: int | None


def _org_id(admin: dict) -> uuid.UUID:
    org = admin.get("org")
    if not org:
        raise HTTPException(status_code=400, detail="Token missing org claim")
    return uuid.UUID(org)


@router.get("/setup-progress", response_model=SetupProgressResponse)
async def get_setup_progress(
    admin: dict = Depends(require_admin),
    conn: AsyncConnection = Depends(get_db_conn),
) -> SetupProgressResponse:
    org_id = _org_id(admin)

    company = await company_setup(conn, org_id)
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")

    project = (
        (
            await conn.execute(
                sa.text(
                    "SELECT id, name, dpr_send_deadline FROM projects "
                    "WHERE organization_id = :org ORDER BY created_at, name LIMIT 1"
                ),
                {"org": org_id},
            )
        )
        .mappings()
        .first()
    )

    setup = company.setup
    return SetupProgressResponse(
        has_team=setup.has_team,
        has_site=setup.has_site,
        has_logo=setup.has_logo,
        report_time_set=setup.report_time_set,
        first_update_at=setup.first_update_at,
        first_dpr_sent_at=setup.first_dpr_sent_at,
        first_project=(
            FirstProject(
                id=project["id"], name=project["name"], send_time=project["dpr_send_deadline"]
            )
            if project is not None
            else None
        ),
        effective_status=company.effective_status,
        trial_days_left=company.trial_days_left,
    )


@router.post("/setup-progress/report-time-ok", response_model=SetupProgressResponse)
async def keep_report_time(
    admin: dict = Depends(require_admin),
    conn: AsyncConnection = Depends(get_db_conn),
) -> SetupProgressResponse:
    """ "The report time is fine": the report-time setup question, answered."""
    org_id = _org_id(admin)
    timezone = (
        await conn.execute(
            sa.text("SELECT timezone FROM organizations WHERE id = :org"), {"org": org_id}
        )
    ).scalar()
    try:
        today = dt.datetime.now(ZoneInfo(timezone or "UTC")).date()
    except (KeyError, ValueError):
        today = dt.datetime.now(dt.UTC).date()

    repo = PostgresOrganizationSettingsRepository(conn)
    progress = await repo.get(org_id, org_settings.SETUP_PROGRESS)
    await repo.set(
        org_id,
        org_settings.SETUP_PROGRESS,
        setup_questions.record(
            progress, setup_questions.REPORT_TIME, setup_questions.ANSWERED, today=today
        ),
        updated_by=uuid.UUID(admin["sub"]) if admin.get("sub") else None,
    )
    return await get_setup_progress(admin=admin, conn=conn)
