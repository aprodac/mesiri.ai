"""REST API for the client view (CV-01, CV-02). Plan: docs/plans/client-view-plan.md.

  GET   /client-links                          the company's links (all projects the caller reaches)
  GET   /projects/{project_id}/client-links    one project's links
  POST  /projects/{project_id}/client-links    make a link; the token comes back once, never again
  POST  /client-links/{link_id}/revoke         turn a link off, at once
  GET   /client/{token}                        the client's page: NO LOGIN, the token is the permission

Links are made and seen by the roles that see client contracts and bills (``may_manage_money``: owner, admin,
finance), within the projects they reach, because the page shows the bills.

The public read finds the link with no company set, then scopes the rest of the transaction to the link's company,
so row-level security holds for everything the page reads. A malformed, unknown or revoked token is the same 404,
so the answer says nothing about which tokens exist.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.authorization.context import AuthorizationContext
from mesiri.authorization.roles import may_manage_money
from mesiri.domains.billing.router import _out
from mesiri.domains.client_view import links, view
from mesiri.domains.projects.router import get_auth_context
from mesiri.infrastructure.objectstorage.dependency import get_object_storage
from mesiri.infrastructure.postgres.dependency import get_db_conn
from mesiri.infrastructure.postgres.tenant import apply_tenant, bind_tenant
from mesiri_contracts.common.storage import ObjectStoragePort

router = APIRouter(tags=["client-view"])

NOT_FOUND = "This link is not valid any more. Ask the builder for a new one."


class LinkIn(BaseModel):
    label: str | None = Field(default=None, max_length=120, description="Who the link is for: 'Mr. Thomas'")

    @field_validator("label")
    @classmethod
    def _clean(cls, v: str | None) -> str | None:
        v = " ".join((v or "").split())
        return v or None


def _require(auth: AuthorizationContext, project_id: uuid.UUID | None = None) -> None:
    if not may_manage_money(auth.role):
        raise HTTPException(status_code=403, detail="Only the owner, an admin or finance can share a project with "
                                                    "its client")
    if project_id is not None and not auth.project_scope.grants_all_org_projects \
            and project_id not in auth.project_scope.project_ids:
        raise HTTPException(status_code=403, detail="Not authorized for this project")


def _scope(auth: AuthorizationContext) -> set | None:
    return None if auth.project_scope.grants_all_org_projects else set(auth.project_scope.project_ids)


async def _project_exists(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID) -> None:
    found = (await conn.execute(text("SELECT 1 FROM projects WHERE id = :p AND organization_id = :org"),
                                {"p": project_id, "org": org})).first()
    if found is None:
        raise HTTPException(status_code=404, detail="Project not found")


@router.get("/client-links")
async def list_all(auth: AuthorizationContext = Depends(get_auth_context),
                   conn: AsyncConnection = Depends(get_db_conn)) -> dict[str, Any]:
    _require(auth)
    return {"links": _out(await links.list_links(conn, auth.organization_id, _scope(auth)))}


@router.get("/projects/{project_id}/client-links")
async def list_for_project(project_id: uuid.UUID, auth: AuthorizationContext = Depends(get_auth_context),
                           conn: AsyncConnection = Depends(get_db_conn)) -> dict[str, Any]:
    _require(auth, project_id)
    return {"links": _out(await links.list_links(conn, auth.organization_id, {project_id}))}


@router.post("/projects/{project_id}/client-links", status_code=201)
async def create(project_id: uuid.UUID, body: LinkIn, auth: AuthorizationContext = Depends(get_auth_context),
                 conn: AsyncConnection = Depends(get_db_conn)) -> dict[str, Any]:
    _require(auth, project_id)
    await _project_exists(conn, auth.organization_id, project_id)
    link_id, token = await links.create(conn, auth.organization_id, project_id, body.label, auth.user_id)
    link = await links.get(conn, auth.organization_id, link_id)
    return {"link": _out(link), "token": token}


@router.post("/client-links/{link_id}/revoke")
async def revoke(link_id: uuid.UUID, auth: AuthorizationContext = Depends(get_auth_context),
                 conn: AsyncConnection = Depends(get_db_conn)) -> dict[str, Any]:
    _require(auth)
    link = await links.get(conn, auth.organization_id, link_id)
    if link is None:
        raise HTTPException(status_code=404, detail="Link not found")
    _require(auth, link["project_id"])
    await links.revoke(conn, auth.organization_id, link_id, auth.user_id)
    return {"link": _out(await links.get(conn, auth.organization_id, link_id))}


@router.get("/client/{token}")
async def client_page(token: str, response: Response, conn: AsyncConnection = Depends(get_db_conn),
                      storage: ObjectStoragePort = Depends(get_object_storage)) -> dict[str, Any]:
    link = await links.open_link(conn, token)
    if link is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    org = link["organization_id"]
    bind_tenant(org)
    await apply_tenant(conn, org)
    page = await view.build(conn, storage, org, link["project_id"])
    if page is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    # Photo links expire; a shared device or proxy must not keep the page.
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return _out(page)
