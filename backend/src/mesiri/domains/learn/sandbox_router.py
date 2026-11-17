"""SS-66: Learn Mesiri's sample company, one per person (docs/plans/guided-demo-plan.md section 17.2).

    GET    /learn/sandbox   is there one for me?
    POST   /learn/sandbox   open mine (made first if there is none) and get a sandbox token, for a role
    DELETE /learn/sandbox   remove mine now (Reset is DELETE then POST)

Called with the person's real token. A sandbox token gets 403 here: no sample company inside a sample company. The
routes hold no request transaction: making the company and filling it run in their own transactions
(application/learn/sandbox.py), so the filling, which goes through the API, sees the company once it exists.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from mesiri.application.learn import sandbox
from mesiri.domains.shared.auth import get_current_user
from mesiri.domains.shared.modules import database_for

router = APIRouter(prefix="/learn/sandbox", tags=["learn"])


class SandboxState(BaseModel):
    exists: bool
    organization_id: uuid.UUID | None = None
    name: str | None = None
    created_at: dt.datetime | None = None
    expires_at: dt.datetime | None = None
    #: The sample company's own date (SS-74a).
    today: dt.date | None = None


class OpenIn(BaseModel):
    role: str = sandbox.OWNER


class Opened(BaseModel):
    token: str
    expires_at: dt.datetime
    organization_id: uuid.UUID
    name: str
    role: str
    user_name: str
    created: bool
    #: The sample company's own date (SS-74a): the dashboard's "today" while in it.
    today: dt.date | None = None
    seeded: dict[str, int] = {}
    failed: list[str] = []


def _engine(request: Request) -> Any:
    database = database_for(request)
    if database is None:
        raise HTTPException(status_code=503, detail="The database is not available.")
    return database._require_engine  # noqa: SLF001 -- its own transactions, never the request's


async def _person(request: Request, payload: dict) -> sandbox.RealPerson:
    if payload.get("sandbox"):
        raise HTTPException(status_code=403, detail="You are already in the sample company.")
    try:
        user_id, org_id = uuid.UUID(str(payload.get("sub"))), uuid.UUID(str(payload.get("org")))
    except ValueError as exc:
        # A platform admin's token has no company: there is no real company to make a sample for.
        raise HTTPException(status_code=403, detail="The sample company is for people in a company.") from exc
    try:
        async with _engine(request).connect() as conn:
            return await sandbox.real_person(conn, user_id, org_id)
    except sandbox.SandboxError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc


@router.get("", response_model=SandboxState)
async def get_sandbox(request: Request, payload: dict = Depends(get_current_user)) -> SandboxState:
    person = await _person(request, payload)
    async with _engine(request).connect() as conn:
        row = await sandbox.find(conn, person)
    if row is None:
        return SandboxState(exists=False)
    return SandboxState(exists=True, organization_id=row["id"], name=row["name"], created_at=row["created_at"],
                        expires_at=row["sandbox_expires_at"], today=row["sandbox_today"])


@router.post("", response_model=Opened)
async def open_sandbox(request: Request, body: OpenIn | None = None,
                       payload: dict = Depends(get_current_user)) -> Opened:
    person = await _person(request, payload)
    try:
        out = await sandbox.open_sandbox(_engine(request), request.app, person, role=(body or OpenIn()).role)
    except sandbox.SandboxError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    return Opened(**out.__dict__)


@router.delete("", status_code=204)
async def delete_sandbox(request: Request, payload: dict = Depends(get_current_user)) -> Response:
    person = await _person(request, payload)
    try:
        await sandbox.remove_sandbox(_engine(request), person)
    except sandbox.SandboxError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    return Response(status_code=204)
