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
from mesiri.bootstrap.settings import get_settings
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
    # Whether the DPR goes out by itself at send_time; off, someone sends it.
    auto_dpr: bool = False


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
    # Mesiri's own WhatsApp number, for the welcome screen's "send your first
    # update" invite; None when the deployment hasn't set one.
    whatsapp_number: str | None = None
    # "Hide for now" (SS-19): the card stays hidden for the whole company
    # until then. None: showing.
    hidden_until: dt.datetime | None = None


#: How long "Hide for now" hides the card before it comes back, if unfinished.
HIDE_FOR = dt.timedelta(days=7)


def hidden_until(record: object, now: dt.datetime) -> dt.datetime | None:
    """When the hidden card comes back, from the stored record; None once past."""
    raw = record.get("hidden_until") if isinstance(record, dict) else None
    try:
        until = dt.datetime.fromisoformat(str(raw)) if raw else None
    except ValueError:
        return None
    if until is not None and until.tzinfo is None:
        until = until.replace(tzinfo=dt.UTC)
    return until if until is not None and until > now else None


def mesiri_whatsapp_number() -> str | None:
    """The number people message, as set (MESIRI_WHATSAPP__DISPLAY_NUMBER)."""
    number = (get_settings().whatsapp.display_number or "").strip()
    return number or None


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
                    "SELECT id, name, dpr_send_deadline, auto_generate_dpr FROM projects "
                    "WHERE organization_id = :org ORDER BY created_at, name LIMIT 1"
                ),
                {"org": org_id},
            )
        )
        .mappings()
        .first()
    )

    setup = company.setup
    card = await PostgresOrganizationSettingsRepository(conn).get(
        org_id, org_settings.GETTING_STARTED
    )
    return SetupProgressResponse(
        has_team=setup.has_team,
        has_site=setup.has_site,
        has_logo=setup.has_logo,
        report_time_set=setup.report_time_set,
        first_update_at=setup.first_update_at,
        first_dpr_sent_at=setup.first_dpr_sent_at,
        first_project=(
            FirstProject(
                id=project["id"],
                name=project["name"],
                send_time=project["dpr_send_deadline"],
                auto_dpr=bool(project["auto_generate_dpr"]),
            )
            if project is not None
            else None
        ),
        effective_status=company.effective_status,
        trial_days_left=company.trial_days_left,
        whatsapp_number=mesiri_whatsapp_number(),
        hidden_until=hidden_until(card, dt.datetime.now(dt.UTC)),
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


async def _set_hidden(admin: dict, conn: AsyncConnection, until: dt.datetime | None) -> None:
    await PostgresOrganizationSettingsRepository(conn).set(
        _org_id(admin),
        org_settings.GETTING_STARTED,
        {"hidden_until": until.isoformat() if until else None},
        updated_by=uuid.UUID(admin["sub"]) if admin.get("sub") else None,
    )


@router.post("/setup-progress/hide", response_model=SetupProgressResponse)
async def hide_card(
    admin: dict = Depends(require_admin),
    conn: AsyncConnection = Depends(get_db_conn),
) -> SetupProgressResponse:
    """ "Hide for now" (SS-19): hidden for the company for HIDE_FOR."""
    await _set_hidden(admin, conn, dt.datetime.now(dt.UTC) + HIDE_FOR)
    return await get_setup_progress(admin=admin, conn=conn)


@router.post("/setup-progress/show", response_model=SetupProgressResponse)
async def show_card(
    admin: dict = Depends(require_admin),
    conn: AsyncConnection = Depends(get_db_conn),
) -> SetupProgressResponse:
    """Bring the card back (the sidebar's "Finish setup")."""
    await _set_hidden(admin, conn, None)
    return await get_setup_progress(admin=admin, conn=conn)
