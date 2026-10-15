"""The owner's getting-started checklist (SS-07): GET /company/setup-progress.

Every item is worked out from what already happened, never ticked by hand:
the same setup block the superadmin's companies list shows
(application/organizations/companies_overview), so the owner and the Mesiri
team see the same progress. The one answer that isn't visible in the data,
"the default report time is fine", is saved with the generic
PUT /company/settings (key `getting_started`).

Kept out of router.py (already past the file-size limit) and attached to its
router, so it is served wherever /company is.
"""

from __future__ import annotations

import datetime as dt
import uuid

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.application.organizations.companies_overview import company_setup
from mesiri.domains.shared.auth import require_admin
from mesiri.infrastructure.postgres.dependency import get_db_conn

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


@router.get("/setup-progress", response_model=SetupProgressResponse)
async def get_setup_progress(
    admin: dict = Depends(require_admin),
    conn: AsyncConnection = Depends(get_db_conn),
) -> SetupProgressResponse:
    org = admin.get("org")
    if not org:
        raise HTTPException(status_code=400, detail="Token missing org claim")
    org_id = uuid.UUID(org)

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
