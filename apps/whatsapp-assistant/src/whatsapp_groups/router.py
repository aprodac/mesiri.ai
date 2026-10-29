"""A site's WhatsApp group, for the dashboard's site page (WA-87).

``GET`` says whether the site has a group and gives its invite link; ``POST``
makes one (runtime/group_chat.py's ``create_for_site``, the same path as
"make a group for <site>" on WhatsApp). Company admins only: a group lets
outsiders see the site's DPR, so who may make one is the owner's call.

Lives in the assistant, not the backend: making a group is a call to Meta,
and only this app holds WhatsApp credentials (runtime/send_pending_notifications.py).
Auth and the site lookup reuse projects/router.py's.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from projects.router import get_current_user, get_engine, sites_table

router = APIRouter(prefix="/projects", tags=["whatsapp-groups"])

_organizations = sa.Table(
    "organizations", sa.MetaData(), sa.Column("id", sa.UUID, primary_key=True), sa.Column("name", sa.String)
)


class WhatsAppGroupResponse(BaseModel):
    #: Groups are switched on for this server (WHATSAPP_GROUPS_ENABLED).
    enabled: bool
    #: none | creating | active | failed
    status: str
    inviteLink: str | None = None
    name: str | None = None
    message: str | None = None


def _group_chat(request: Request):
    container = getattr(request.app.state, "container", None)
    return getattr(container, "group_chat", None)


async def _admin_site(payload: dict, project_id: uuid.UUID, site_id: uuid.UUID) -> tuple[str, str, str]:
    """(org id, org name, site name) of a site in the caller's company, for an admin."""
    org_id = payload.get("org")
    if not org_id:
        raise HTTPException(status_code=400, detail="User has no organization")
    if (payload.get("role") or "").upper() != "ADMIN":
        raise HTTPException(status_code=403, detail="Admin access required for the site's WhatsApp group")
    async with get_engine().begin() as conn:
        row = (
            await conn.execute(
                sa.select(sites_table.c.name, _organizations.c.name.label("org_name"))
                .select_from(sites_table.join(_organizations, _organizations.c.id == sites_table.c.organization_id))
                .where(
                    sites_table.c.id == site_id,
                    sites_table.c.project_id == project_id,
                    sites_table.c.organization_id == org_id,
                )
            )
        ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Site not found")
    return str(org_id), row.org_name or "", row.name or "Site"


def _response(group: dict | None, *, enabled: bool, message: str | None = None) -> WhatsAppGroupResponse:
    if group is None:
        return WhatsAppGroupResponse(enabled=enabled, status="none", message=message)
    return WhatsAppGroupResponse(
        enabled=enabled,
        status=group.get("status") or "none",
        inviteLink=group.get("invite_link"),
        name=group.get("subject"),
        message=message,
    )


@router.get("/{project_id}/sites/{site_id}/whatsapp-group", response_model=WhatsAppGroupResponse)
async def get_site_whatsapp_group(
    project_id: uuid.UUID, site_id: uuid.UUID, request: Request, payload: dict = Depends(get_current_user)
):
    org_id, _org_name, _site_name = await _admin_site(payload, project_id, site_id)
    chat = _group_chat(request)
    if chat is None or not chat.enabled:
        return _response(None, enabled=False)
    return _response(await chat.site_group(organization_id=org_id, site_id=str(site_id)), enabled=True)


@router.post("/{project_id}/sites/{site_id}/whatsapp-group", response_model=WhatsAppGroupResponse)
async def create_site_whatsapp_group(
    project_id: uuid.UUID, site_id: uuid.UUID, request: Request, payload: dict = Depends(get_current_user)
):
    org_id, org_name, site_name = await _admin_site(payload, project_id, site_id)
    chat = _group_chat(request)
    if chat is None or not chat.enabled:
        raise HTTPException(status_code=503, detail="WhatsApp groups aren't switched on yet")

    from runtime.group_chat import create_reply

    result = await chat.create_for_site(
        organization_id=org_id,
        org_name=org_name,
        project_id=str(project_id),
        site_id=str(site_id),
        site_name=site_name,
        created_by_user_id=payload.get("sub"),
    )
    if result.status == "failed":
        raise HTTPException(status_code=502, detail=create_reply(result, site_name))
    if result.status == "not_eligible":
        raise HTTPException(status_code=409, detail=create_reply(result, site_name))
    group = await chat.site_group(organization_id=org_id, site_id=str(site_id))
    return _response(group, enabled=True, message=create_reply(result, site_name))
