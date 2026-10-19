"""REST API for Daily Progress Reports (DPR).

Mounted at /dpr so:
  GET   /dpr/site-days?date=YYYY-MM-DD     every active site's working day (BE-08)
  PATCH /dpr/site-days/{site_id}/conditions?date=  weather, hours lost, site working, plan (BE-14)
  POST  /dpr/projects/{project_id}/send    "Send now": project DPR out on the next tick (BE-16)
  GET   /dpr/projects/{project_id}/day?date=  the project DPR page: sites, roll-up, versions (WEB-05)
  GET   /dpr/projects/{project_id}/recipients               who gets the project DPR (BE-15)
  POST  /dpr/projects/{project_id}/recipients               add a user or outside contact
  DELETE /dpr/projects/{project_id}/recipients/{id}         remove one
  POST  /dpr/projects/{project_id}/recipients/{id}/opt-in   record their WhatsApp opt-in
  POST  /dpr/projects/{project_id}/recipients/{id}/opt-out  record their opt-out
  POST  /dpr/facts/{fact_type}/{fact_id}/confirm   confirm one draft (BE-09)
  POST  /dpr/facts/{fact_type}/{fact_id}/reject    reject one draft, with a reason (BE-09)
  GET   /dpr/daily-reports                 list daily reports
  GET   /dpr/daily-reports/{report_id}     get daily report details
  POST  /dpr/daily-reports                 create daily report draft
  POST  /dpr/daily-reports/{report_id}/approve approve a report
  POST  /dpr/daily-reports/{report_id}/revise  correct an approved/published report
"""

from __future__ import annotations

import datetime
import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.application.dpr.fact_review import FactReviewError
from mesiri.application.dpr.site_day import InvalidSiteDayTransition
from mesiri.authorization.context import AuthorizationContext
from mesiri.domains.dpr.pdf import render_dpr_pdf_bytes
from mesiri.domains.projects.router import get_auth_context
from mesiri.domains.shared.media import assert_downloadable_url
from mesiri.domains.shared.modules import require_module
from mesiri.infrastructure.objectstorage.dependency import get_object_storage
from mesiri.infrastructure.postgres.dependency import get_db_conn
from mesiri.infrastructure.postgres.repositories.dpr import PostgresDprRepository
from mesiri.infrastructure.postgres.repositories.fact_reviews import PostgresFactReviewRepository
from mesiri_contracts.common.storage import ObjectStoragePort

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/dpr",
    tags=["dpr"],
    dependencies=[Depends(require_module("dpr"))],
)


class CreateDprRequest(BaseModel):
    report_date: str
    project_id: uuid.UUID | None = None
    site_id: uuid.UUID | None = None
    weather: str = "sunny"
    temperature_celsius: float | None = None
    shift: str = "day"
    narrative_summary: str | None = None
    work_items: list[dict[str, Any]] = []
    labour_items: list[dict[str, Any]] = []
    equipment_items: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []


class ApproveDprRequest(BaseModel):
    notes: str | None = None


class ReviseDprRequest(BaseModel):
    revision_reason: str
    narrative_summary: str | None = None


def _resolve_project_ids(
    auth_context: AuthorizationContext, project_id: uuid.UUID | None
) -> tuple[set[uuid.UUID] | None, bool]:
    if project_id is not None:
        if not auth_context.project_scope.grants_all_org_projects:
            if project_id not in auth_context.project_scope.project_ids:
                return None, True
        return {project_id}, False
    if not auth_context.project_scope.grants_all_org_projects:
        if not auth_context.project_scope.project_ids:
            return None, True
        return auth_context.project_scope.project_ids, False
    return None, False


@router.get("/daily-reports")
async def list_daily_reports(
    project_id: uuid.UUID | None = None,
    site_id: uuid.UUID | None = None,
    status: str | None = None,
    category: str | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    project_ids, denied = _resolve_project_ids(auth_context, project_id)
    if denied:
        return {"items": [], "total": 0}

    repo = PostgresDprRepository(conn)
    items, total = await repo.list_reports(
        organization_id=auth_context.organization_id,
        project_ids=project_ids,
        site_id=site_id,
        status=status,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )
    return {"items": items, "total": total}


@router.get("/site-days")
async def list_site_days(
    report_date: datetime.date = Query(alias="date"),
    project_id: uuid.UUID | None = None,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Every active site's working day for one date (BE-08): status
    (draft = collecting, needs_details, ready, in_review = with engineer,
    approved = confirmed, published = sent), what is missing, and live
    counts (workers, work items, photos, open issues, latest update). Plus
    each project's cutoff, send deadline and DPR status -- everything the
    Today page shows (WEB-03)."""
    project_ids, denied = _resolve_project_ids(auth_context, project_id)
    if denied:
        return {"date": report_date.isoformat(), "items": [], "projects": []}

    repo = PostgresDprRepository(conn)
    items = await repo.list_site_days(
        organization_id=auth_context.organization_id,
        project_ids=project_ids,
        report_date=report_date,
    )
    projects = await repo.list_project_days(
        organization_id=auth_context.organization_id,
        project_ids=project_ids,
        report_date=report_date,
    )
    # Drafts still to confirm on each site's day (BE-09).
    drafts = await PostgresFactReviewRepository(conn).draft_counts_by_site(
        organization_id=auth_context.organization_id, report_date=report_date
    )
    for item in items:
        item["drafts"] = drafts.get(item["site_id"], 0)
    return {"date": report_date.isoformat(), "items": items, "projects": projects}


def _site_denied(
    auth_context: AuthorizationContext, project_id: uuid.UUID, site_id: uuid.UUID | None
) -> bool:
    """No access to the project, or (custom sites) not to this site. A
    project-level report (no site) needs only the project."""
    _, denied = _resolve_project_ids(auth_context, project_id)
    if denied:
        return True
    if site_id is None:
        return False
    scope = auth_context.site_scope_for_project(project_id)
    return not scope.grants_all_sites and site_id not in scope.site_ids


_MEDIA_URL_TTL_SECONDS = 600


async def _signed_url(object_storage: ObjectStoragePort, key: str | None) -> str | None:
    """A short-lived link to a stored photo/voice note, or None when storage
    can't give one (the panel then shows the item without it)."""
    if not key:
        return None
    try:
        return assert_downloadable_url(
            await object_storage.generate_presigned_url(
                key, expires_in_seconds=_MEDIA_URL_TTL_SECONDS
            )
        )
    except Exception:  # noqa: BLE001 -- one missing photo must not hide the rest
        logger.warning("dpr.sources_media_unavailable key=%s", key)
        return None


@router.get("/site-days/{site_id}")
async def get_site_day(
    site_id: uuid.UUID,
    report_date: datetime.date = Query(alias="date"),
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """One site's working day, for the site DPR page (WEB-04): its status and
    what is missing (as the Today page shows it), the report as it stands
    now, every item that can be confirmed or removed (`items`, with ids and
    draft/confirmed), and the report's versions."""
    repo = PostgresDprRepository(conn)
    site = await repo.find_site(organization_id=auth_context.organization_id, site_id=site_id)
    if site is None or site["project_id"] is None:
        raise HTTPException(status_code=404, detail="Site not found")
    project_id = site["project_id"]
    if _site_denied(auth_context, project_id, site_id):
        raise HTTPException(status_code=404, detail="Site not found")

    days = await repo.list_site_days(
        organization_id=auth_context.organization_id,
        project_ids={project_id},
        report_date=report_date,
    )
    day = next((d for d in days if str(d["site_id"]) == str(site_id)), None)
    projects = await repo.list_project_days(
        organization_id=auth_context.organization_id,
        project_ids={project_id},
        report_date=report_date,
    )
    payload, items = await repo.assemble_site_day(
        organization_id=auth_context.organization_id,
        project_id=project_id,
        site_id=site_id,
        report_date=report_date,
    )
    report_id = day.get("daily_report_id") if day else None
    versions = (
        await repo.list_versions(organization_id=auth_context.organization_id, report_id=report_id)
        if report_id
        else []
    )
    return {
        "date": report_date.isoformat(),
        "site_id": str(site_id),
        "project_id": str(project_id),
        "day": day,
        "project": projects[0] if projects else None,
        "report": payload,
        "items": items,
        "drafts": sum(1 for i in items if i["review"] == "draft"),
        "versions": versions,
    }


@router.get("/facts/{fact_type}/{fact_id}/sources")
async def get_fact_sources(
    fact_type: str,
    fact_id: uuid.UUID,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
    object_storage: ObjectStoragePort = Depends(get_object_storage),
):
    """Where one item came from (WEB-04's sources panel): WhatsApp messages
    with sender and time, what the AI read and how sure it was, photos
    (short-lived links), and its draft/confirm/reject history."""
    repo = PostgresFactReviewRepository(conn)
    try:
        located = await repo.locate(auth_context.organization_id, fact_type, fact_id)
    except FactReviewError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if located["project_id"] is None or _site_denied(
        auth_context, located["project_id"], located["site_id"]
    ):
        raise HTTPException(status_code=404, detail="that item was not found")
    sources = await repo.sources(
        organization_id=auth_context.organization_id, fact_type=fact_type, fact_id=fact_id
    )
    for message in sources["messages"]:
        message["media_url"] = await _signed_url(object_storage, message.pop("media_object_key"))
    for photo in sources["photos"]:
        photo["url"] = await _signed_url(object_storage, photo.pop("media_object_key"))
    return sources


class SiteDayConditionsRequest(BaseModel):
    """Only the fields sent are changed; null clears one (BE-14)."""

    weather: str | None = None
    hours_lost: float | None = None
    site_working: str | None = None
    tomorrow_plan: str | None = None


@router.patch("/site-days/{site_id}/conditions")
async def set_site_day_conditions(
    site_id: uuid.UUID,
    req: SiteDayConditionsRequest,
    report_date: datetime.date = Query(alias="date"),
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Weather, hours lost, site working (full/half/none) and tomorrow's
    plan for one site's day. `site_working: "none"` is the "no work today"
    button: the day becomes ready with nothing required."""
    repo = PostgresDprRepository(conn)
    site = await repo.find_site(organization_id=auth_context.organization_id, site_id=site_id)
    if site is None or site["project_id"] is None:
        raise HTTPException(status_code=404, detail="Site not found")
    _, denied = _resolve_project_ids(auth_context, site["project_id"])
    if denied:
        raise HTTPException(status_code=404, detail="Site not found")

    changes = req.model_dump(exclude_unset=True)
    if isinstance(changes.get("tomorrow_plan"), str):
        changes["tomorrow_plan"] = changes["tomorrow_plan"].strip() or None
    try:
        result = await repo.set_site_day_conditions(
            organization_id=auth_context.organization_id,
            project_id=site["project_id"],
            site_id=site_id,
            report_date=report_date,
            changes=changes,
        )
    except InvalidSiteDayTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {**result, "daily_report_id": str(result["daily_report_id"])}


@router.post("/projects/{project_id}/send")
async def send_project_dpr_now(
    project_id: uuid.UUID,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """"Send now" (BE-16): today's project DPR goes out within about a
    minute, built from the sites confirmed so far; the rest show as "Not
    reported". The WhatsApp side does the sending."""
    from mesiri.application.projects.auto_dpr import request_project_dpr_send

    _, denied = _resolve_project_ids(auth_context, project_id)
    if denied:
        raise HTTPException(status_code=404, detail="Project not found")
    try:
        report_date = await request_project_dpr_send(
            conn,
            organization_id=auth_context.organization_id,
            project_id=project_id,
            now_utc=datetime.datetime.now(datetime.UTC),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if report_date is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"status": "queued", "report_date": report_date.isoformat()}


@router.get("/projects/{project_id}/day")
async def get_project_day(
    project_id: uuid.UUID,
    report_date: datetime.date = Query(alias="date"),
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """One project's day, for the project DPR page (WEB-05): the project's
    DPR status (as the Today page shows it), each site's day, and the
    project DPR itself -- as it was sent once it has gone out
    (`report_source: "sent"`), otherwise a preview of what would go out now,
    built from the sites confirmed so far (`"preview"`, writes nothing).
    Plus the project report's versions."""
    _, denied = _resolve_project_ids(auth_context, project_id)
    if denied:
        raise HTTPException(status_code=404, detail="Project not found")

    repo = PostgresDprRepository(conn)
    projects = await repo.list_project_days(
        organization_id=auth_context.organization_id,
        project_ids={project_id},
        report_date=report_date,
    )
    if not projects:
        raise HTTPException(status_code=404, detail="Project not found")
    project = projects[0]

    sites = await repo.list_site_days(
        organization_id=auth_context.organization_id,
        project_ids={project_id},
        report_date=report_date,
    )
    drafts = await PostgresFactReviewRepository(conn).draft_counts_by_site(
        organization_id=auth_context.organization_id, report_date=report_date
    )
    for site in sites:
        site["drafts"] = drafts.get(site["site_id"], 0)

    # The cutoff already builds a draft roll-up, so only a frozen one (made
    # ready to send, then sent) is what went out; until then it is previewed.
    report_id = project.get("project_report_id")
    report = (
        await repo.get_current_payload(
            organization_id=auth_context.organization_id, report_id=report_id
        )
        if report_id and project.get("project_report_status") in ("approved", "published")
        else None
    )
    source = "sent"
    if report is None:
        source = "preview"
        report, _ = await repo.assemble_project_report_payload(
            organization_id=auth_context.organization_id,
            project_id=project_id,
            report_date=report_date,
            preview=True,
        )
    # Only versions that went out (approved): the cutoff's draft roll-up was
    # built before the sites were confirmed, so its PDF carries figures that
    # were never sent.
    versions = (
        [
            v
            for v in await repo.list_versions(
                organization_id=auth_context.organization_id, report_id=report_id
            )
            if v["approved_at"]
        ]
        if report_id and source == "sent"
        else []
    )
    return {
        "date": report_date.isoformat(),
        "project_id": str(project_id),
        "project": project,
        "sites": sites,
        "report": report,
        "report_source": source,
        "versions": versions,
    }


# ---------------------------------------------------------------------------
# Recipients and opt-ins (BE-15)
# ---------------------------------------------------------------------------


class AddRecipientRequest(BaseModel):
    """A company user (`user_id`) or an outside contact (`name` + `phone`).
    `opted_in` records, in the same step, that the contact agreed to get
    the DPR on WhatsApp (e.g. in the contract); `opt_in_note` says how."""

    user_id: uuid.UUID | None = None
    name: str | None = None
    phone: str | None = None
    label: str | None = None
    opted_in: bool = False
    opt_in_note: str | None = None


class ConsentRequest(BaseModel):
    note: str | None = None


def _present_recipient(row: dict[str, Any]) -> dict[str, Any]:
    is_user = row["user_id"] is not None
    return {
        "id": str(row["id"]),
        "kind": "user" if is_user else "contact",
        "user_id": str(row["user_id"]) if is_user else None,
        "name": row["name"],
        "phone": row["phone"],
        "label": row["label"],
        "role": row.get("user_role"),
        # "opted_in" / "opted_out" / None. A contact with None is not sent
        # anything yet; a user with None is (joining the company counts).
        "opt_in": row.get("consent_state"),
        "will_receive": _will_receive(row),
    }


def _will_receive(row: dict[str, Any]) -> bool:
    from mesiri.application.dpr.recipients import may_message

    if not row["phone"]:
        return False  # a user with no WhatsApp number on file
    allowed, _ = may_message(
        consent_state=row.get("consent_state"), requires_opt_in=row["user_id"] is None
    )
    return allowed


async def _recipients_scope(
    auth_context: AuthorizationContext, conn: AsyncConnection, project_id: uuid.UUID, *, write: bool
):
    from mesiri.application.dpr.recipients import MANAGER_ROLES
    from mesiri.infrastructure.postgres.repositories.report_recipients import (
        PostgresReportRecipientRepository,
    )

    _, denied = _resolve_project_ids(auth_context, project_id)
    repo = PostgresReportRecipientRepository(conn)
    if denied or not await repo.project_exists(
        organization_id=auth_context.organization_id, project_id=project_id
    ):
        raise HTTPException(status_code=404, detail="Project not found")
    if write and (auth_context.role or "").upper() not in MANAGER_ROLES:
        raise HTTPException(
            status_code=403, detail="Only admins and project managers can change DPR recipients"
        )
    return repo


@router.get("/projects/{project_id}/recipients")
async def list_report_recipients(
    project_id: uuid.UUID,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Who gets this project's DPR (BE-15). `using_defaults: true` means no
    list is set and the project's admins and project managers get it."""
    repo = await _recipients_scope(auth_context, conn, project_id, write=False)
    rows = await repo.list_active(organization_id=auth_context.organization_id, project_id=project_id)
    return {
        "project_id": str(project_id),
        "using_defaults": not rows,
        "recipients": [_present_recipient(row) for row in rows],
    }


@router.post("/projects/{project_id}/recipients", status_code=201)
async def add_report_recipient(
    project_id: uuid.UUID,
    req: AddRecipientRequest,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Add a company user or an outside contact to this project's DPR list.
    Adding the first one replaces the default audience (admins + PMs).

    An outside contact added without an opt-in on record is sent one
    WhatsApp invite to opt in (WA-09); `invite_queued` says whether it was."""
    from mesiri.application.dpr.recipients import (
        OPTED_IN,
        RECORDED_BY_ADMIN,
        RecipientError,
        clean_contact,
    )

    repo = await _recipients_scope(auth_context, conn, project_id, write=True)
    org_id = auth_context.organization_id
    invite_queued = False

    if req.user_id is not None:
        if req.name or req.phone:
            raise HTTPException(status_code=422, detail="Send either user_id or name and phone, not both")
        if not await repo.active_user_in_org(organization_id=org_id, user_id=req.user_id):
            raise HTTPException(status_code=422, detail="No active user with that id in this company")
        if await repo.has_active(project_id=project_id, user_id=req.user_id):
            raise HTTPException(status_code=409, detail="Already a recipient")
        recipient_id = await repo.add(
            organization_id=org_id,
            project_id=project_id,
            actor_user_id=auth_context.user_id,
            user_id=req.user_id,
            label=(req.label or "").strip() or None,
        )
    else:
        try:
            contact = clean_contact(name=req.name, phone=req.phone, label=req.label)
        except RecipientError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if await repo.has_active(project_id=project_id, phone=contact["phone"]):
            raise HTTPException(status_code=409, detail="Already a recipient")
        recipient_id = await repo.add(
            organization_id=org_id,
            project_id=project_id,
            actor_user_id=auth_context.user_id,
            **contact,
        )
        if req.opted_in:
            await repo.record_consent(
                organization_id=org_id,
                phone=contact["phone"],
                state=OPTED_IN,
                method=RECORDED_BY_ADMIN,
                note=(req.opt_in_note or "").strip() or None,
                actor_user_id=auth_context.user_id,
            )
        else:
            from mesiri.application.dpr.opt_in_invite import queue_invite

            invite_queued = await queue_invite(
                conn,
                organization_id=org_id,
                project_id=project_id,
                phone=contact["phone"],
                today=datetime.date.today(),
            )

    row = await repo.find_active(organization_id=org_id, project_id=project_id, recipient_id=recipient_id)
    return {**_present_recipient(row), "invite_queued": invite_queued}


@router.delete("/projects/{project_id}/recipients/{recipient_id}", status_code=204)
async def remove_report_recipient(
    project_id: uuid.UUID,
    recipient_id: uuid.UUID,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Take someone off the list. Removing the last one brings the default
    audience (admins + PMs) back."""
    repo = await _recipients_scope(auth_context, conn, project_id, write=True)
    removed = await repo.remove(
        organization_id=auth_context.organization_id,
        project_id=project_id,
        recipient_id=recipient_id,
        actor_user_id=auth_context.user_id,
    )
    if not removed:
        raise HTTPException(status_code=404, detail="Recipient not found")
    return Response(status_code=204)


async def _record_recipient_consent(
    project_id: uuid.UUID,
    recipient_id: uuid.UUID,
    req: ConsentRequest,
    auth_context: AuthorizationContext,
    conn: AsyncConnection,
    *,
    state: str,
) -> dict[str, Any]:
    from mesiri.application.dpr.recipients import RECORDED_BY_ADMIN

    repo = await _recipients_scope(auth_context, conn, project_id, write=True)
    org_id = auth_context.organization_id
    row = await repo.find_active(organization_id=org_id, project_id=project_id, recipient_id=recipient_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Recipient not found")
    if not row["phone"]:
        raise HTTPException(status_code=422, detail="This user has no WhatsApp number on file")
    await repo.record_consent(
        organization_id=org_id,
        phone=row["phone"],
        state=state,
        method=RECORDED_BY_ADMIN,
        note=(req.note or "").strip() or None,
        actor_user_id=auth_context.user_id,
    )
    row = await repo.find_active(organization_id=org_id, project_id=project_id, recipient_id=recipient_id)
    return _present_recipient(row)


@router.post("/projects/{project_id}/recipients/{recipient_id}/opt-in")
async def record_recipient_opt_in(
    project_id: uuid.UUID,
    recipient_id: uuid.UUID,
    req: ConsentRequest,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Record that this person agreed to get the DPR on WhatsApp (given
    outside Mesiri, e.g. in the contract or by email); `note` says how."""
    from mesiri.application.dpr.recipients import OPTED_IN

    return await _record_recipient_consent(
        project_id, recipient_id, req, auth_context, conn, state=OPTED_IN
    )


@router.post("/projects/{project_id}/recipients/{recipient_id}/opt-out")
async def record_recipient_opt_out(
    project_id: uuid.UUID,
    recipient_id: uuid.UUID,
    req: ConsentRequest,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Record that this person asked not to get WhatsApp messages from this
    company. Stops every message to that number, not only the DPR."""
    from mesiri.application.dpr.recipients import OPTED_OUT

    return await _record_recipient_consent(
        project_id, recipient_id, req, auth_context, conn, state=OPTED_OUT
    )


class RejectFactRequest(BaseModel):
    reason: str


async def _fact_in_scope(
    repo: PostgresFactReviewRepository,
    auth_context: AuthorizationContext,
    fact_type: str,
    fact_id: uuid.UUID,
) -> None:
    try:
        located = await repo.locate(auth_context.organization_id, fact_type, fact_id)
    except FactReviewError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    _, denied = _resolve_project_ids(auth_context, located["project_id"])
    if denied:
        raise HTTPException(status_code=404, detail="that item was not found")


@router.post("/facts/{fact_type}/{fact_id}/confirm")
async def confirm_fact(
    fact_type: str,
    fact_id: uuid.UUID,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Confirm one draft (BE-09). fact_type: activity, site_issue,
    labour_report, material_receipt, material_usage."""
    repo = PostgresFactReviewRepository(conn)
    await _fact_in_scope(repo, auth_context, fact_type, fact_id)
    try:
        changed = await repo.confirm(
            organization_id=auth_context.organization_id,
            fact_type=fact_type,
            fact_id=fact_id,
            actor_user_id=auth_context.user_id,
        )
    except FactReviewError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"status": "confirmed", "changed": changed}


@router.post("/facts/{fact_type}/{fact_id}/reject")
async def reject_fact(
    fact_type: str,
    fact_id: uuid.UUID,
    req: RejectFactRequest,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Reject one draft (BE-09): it is withdrawn through its own module's
    undo (activity voided, issue cancelled, attendance withdrawn, material
    reversed) and the reason recorded. Refused for a confirmed day."""
    repo = PostgresFactReviewRepository(conn)
    await _fact_in_scope(repo, auth_context, fact_type, fact_id)
    try:
        await repo.reject(
            organization_id=auth_context.organization_id,
            fact_type=fact_type,
            fact_id=fact_id,
            actor_user_id=auth_context.user_id,
            reason=req.reason,
        )
    except FactReviewError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"status": "rejected"}


@router.get("/daily-reports/{report_id}")
async def get_daily_report_detail(
    report_id: uuid.UUID,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    repo = PostgresDprRepository(conn)
    report = await repo.get_report(
        organization_id=auth_context.organization_id,
        report_id=report_id,
    )
    if not report:
        raise HTTPException(status_code=404, detail="Daily report not found")
    return report


@router.post("/daily-reports")
async def create_daily_report(
    req: CreateDprRequest,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    repo = PostgresDprRepository(conn)
    created = await repo.create_report(
        organization_id=auth_context.organization_id,
        user_id=auth_context.user_id,
        payload=req.model_dump(),
    )
    return created


@router.post("/daily-reports/{report_id}/submit-for-review")
async def submit_daily_report_for_review(
    report_id: uuid.UUID,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """DRAFT -> IN_REVIEW."""
    repo = PostgresDprRepository(conn)
    success = await repo.submit_for_review(
        organization_id=auth_context.organization_id,
        report_id=report_id,
    )
    if not success:
        raise HTTPException(status_code=404, detail="Report not found or not in DRAFT status")
    return {"status": "success"}


@router.post("/daily-reports/{report_id}/approve")
async def approve_daily_report(
    report_id: uuid.UUID,
    req: ApproveDprRequest,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    repo = PostgresDprRepository(conn)
    success = await repo.approve_report(
        organization_id=auth_context.organization_id,
        user_id=auth_context.user_id,
        report_id=report_id,
        notes=req.notes,
    )
    if not success:
        raise HTTPException(status_code=404, detail="Report not found or already approved")
    return {"status": "success"}


@router.post("/daily-reports/{report_id}/publish")
async def publish_daily_report(
    report_id: uuid.UUID,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """APPROVED -> PUBLISHED."""
    repo = PostgresDprRepository(conn)
    success = await repo.publish_report(
        organization_id=auth_context.organization_id,
        report_id=report_id,
    )
    if not success:
        raise HTTPException(status_code=404, detail="Report not found or not in APPROVED status")
    return {"status": "success"}


@router.post("/daily-reports/{report_id}/revise")
async def revise_daily_report(
    report_id: uuid.UUID,
    req: ReviseDprRequest,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Correct an already APPROVED/PUBLISHED report: re-assembles the
    payload from what's actually recorded now (same composition
    create_version uses) and inserts it as a new version superseding the
    current one, with a stated `revision_reason`. Status resets to DRAFT so
    the correction goes back through submit-for-review/approve/publish.

    Works for both SITE reports (re-assembled from current activities/
    issues/labour/materials) and PROJECT roll-ups (re-assembled from
    whichever SITE versions are current now, ADR-D9/P8 -- a site whose own
    report changed since the roll-up was generated is what a project-level
    revision exists to pick up).

    404s for a report with no live data to re-assemble from at all -- the
    manual-entry path (POST /dpr/daily-reports with a hand-typed payload),
    which never gets composed from real records.
    """
    if not req.revision_reason or not req.revision_reason.strip():
        raise HTTPException(status_code=400, detail="revision_reason is required")

    repo = PostgresDprRepository(conn)
    scope = await repo.get_report_scope(
        organization_id=auth_context.organization_id, report_id=report_id
    )
    if scope is None:
        raise HTTPException(status_code=404, detail="Daily report not found")

    sources: list[tuple[uuid.UUID, uuid.UUID | None]] | None = None
    if scope["level"] == "SITE" and scope["site_id"] is not None:
        payload = await repo.assemble_site_report_payload(
            organization_id=auth_context.organization_id,
            project_id=scope["project_id"],
            site_id=scope["site_id"],
            report_date=scope["report_date"],
        )
    elif scope["level"] == "PROJECT":
        payload, sources = await repo.assemble_project_report_payload(
            organization_id=auth_context.organization_id,
            project_id=scope["project_id"],
            report_date=scope["report_date"],
        )
    else:
        raise HTTPException(
            status_code=400,
            detail="Only a generated site-level or project-level report can be revised",
        )

    try:
        version = await repo.revise_version(
            daily_report_id=report_id,
            payload=payload,
            narrative_summary=req.narrative_summary,
            revision_reason=req.revision_reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if sources is not None:
        await repo.record_project_sources(project_version_id=version["id"], sources=sources)

    return {"status": "success", **{k: str(v) if v is not None else v for k, v in version.items()}}


@router.get("/daily-reports/{report_id}/versions")
async def list_daily_report_versions(
    report_id: uuid.UUID,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Every version of one report, newest first (WEB-04)."""
    repo = PostgresDprRepository(conn)
    scope = await repo.get_report_scope(
        organization_id=auth_context.organization_id, report_id=report_id
    )
    if scope is None or _site_denied(auth_context, scope["project_id"], scope["site_id"]):
        raise HTTPException(status_code=404, detail="Daily report not found")
    return {
        "items": await repo.list_versions(
            organization_id=auth_context.organization_id, report_id=report_id
        )
    }


@router.get("/daily-reports/{report_id}/pdf")
async def get_daily_report_pdf(
    report_id: uuid.UUID,
    version_id: uuid.UUID | None = None,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
    object_storage: ObjectStoragePort = Depends(get_object_storage),
):
    """Serve one DPR as a downloadable PDF.

    If the nightly cron (runtime/render_pending_dpr_pdfs.py) has already
    rendered this version, that polished Playwright/Jinja artifact is
    fetched from object storage and returned as-is (best fidelity, matches
    what WhatsApp sees). Otherwise a plain-tabular PDF is rendered on the
    spot from the same payload via fpdf2 (see domains/dpr/pdf.py) so the
    dashboard never has to show "come back later" for a report that has a
    real payload but hasn't been picked up by the cron yet.

    404s (not 200-with-empty-body) for a report with no current version at
    all -- the manual-entry creation path (POST /dpr/daily-reports with no
    activities behind it) has nothing real to render.
    """
    repo = PostgresDprRepository(conn)
    report = await repo.get_report_for_pdf(
        organization_id=auth_context.organization_id, report_id=report_id, version_id=version_id
    )
    if report is None:
        raise HTTPException(
            status_code=404,
            detail="This report has no generated content yet (no activities recorded, or it "
            "was created manually without a payload).",
        )

    filename = f"{report['code'] or 'DPR'}.pdf"

    if report["rendered_object_key"]:
        stored = await object_storage.get_object(report["rendered_object_key"])
        pdf_bytes = stored.data
    else:
        payload = report["payload"]
        if isinstance(payload, str):
            import json

            payload = json.loads(payload)
        pdf_bytes = render_dpr_pdf_bytes(
            code=report["code"],
            report_date=report["report_date"],
            project_name=report["project_name"],
            site_name=report["site_name"],
            workflow_status=report["workflow_status"],
            payload=payload,
        )

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
