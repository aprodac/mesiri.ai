"""SS-66: Learn Mesiri's sample company, one per person (docs/plans/guided-demo-plan.md section 17.2).

    GET    /learn/sandbox   is there one for me?
    GET    /learn/sandbox/clock, POST /learn/sandbox/next-day   days pass (SS-74c)
    POST   /learn/sandbox/go-back   back to the start of a day played (SS-74d)
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
from pydantic import BaseModel, Field

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


# --- SS-74c: days pass (docs/plans/guided-demo-plan.md section 18) ----------------------------------------------


class ForYouOut(BaseModel):
    id: str
    day: int
    what: str
    kind: str
    page: str
    done: bool


class ClockOut(BaseModel):
    day: int
    date: dt.date
    last_day: int
    for_you: list[ForYouOut] = []
    #: The save points there are to go back to, oldest first (SS-74d): [{"day", "date"}].
    can_go_back_to: list[dict[str, Any]] = []


class NextDayIn(BaseModel):
    days: int = 1
    #: The role the person is playing: theirs is left for them on the day they land on.
    role: str = sandbox.OWNER
    #: UX-104: the guided project playing on to a chapter's day: the plan entries (ids) that chapter asks the person to
    #: do on the day they land on. Everything else, theirs too, is played by the cast on the way, so "For you" and the
    #: morning briefing hold only the story's own to-dos. Left out: a plain Next day (the person's day is theirs).
    keep: list[str] | None = Field(default=None, max_length=20)


class MovedOut(BaseModel):
    day: int
    date: dt.date
    #: A new sandbox token: the sample's date moved, and the token carries it.
    token: str
    expires_at: dt.datetime
    summary: list[dict[str, Any]] = []
    #: UX-71: the days' notable moments ({day, who, kind, what}), for the "a day passes" scene.
    highlights: list[dict[str, Any]] = []
    #: UX-71: on handover, the whole run's totals for the end credits.
    finale: dict[str, Any] | None = None
    for_you: list[ForYouOut] = []
    waiting: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []


@router.get("/clock", response_model=ClockOut)
async def get_clock(request: Request, role: str = sandbox.OWNER, payload: dict = Depends(get_current_user)) -> ClockOut:
    from mesiri.application.learn import sandbox_player

    person = await _person(request, payload)
    try:
        out = await sandbox_player.clock(_engine(request), person, role.upper())
    except sandbox.SandboxError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    return ClockOut(day=out.day, date=out.date, last_day=out.last_day, for_you=[ForYouOut(**f.__dict__) for f in out.for_you],
                    can_go_back_to=out.can_go_back_to)


@router.post("/next-day", response_model=MovedOut)
async def post_next_day(request: Request, body: NextDayIn | None = None,
                        payload: dict = Depends(get_current_user)) -> MovedOut:
    from mesiri.application.learn import sandbox_player

    body = body or NextDayIn()
    person = await _person(request, payload)
    if body.role.upper() not in sandbox.PLAYABLE_ROLES:
        raise HTTPException(status_code=422, detail=f"role must be one of {list(sandbox.PLAYABLE_ROLES)}")
    try:
        out = await sandbox_player.next_day(_engine(request), request.app, person, role=body.role, days=body.days,
                                            keep=None if body.keep is None else frozenset(body.keep))
    except sandbox.SandboxError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    return MovedOut(**{**out.__dict__, "for_you": [ForYouOut(**f.__dict__) for f in out.for_you]})


class GoBackIn(BaseModel):
    #: The plan day to go back to the start of (today's own day = try today again).
    day: int
    role: str = sandbox.OWNER


@router.post("/go-back", response_model=MovedOut)
async def post_go_back(request: Request, body: GoBackIn, payload: dict = Depends(get_current_user)) -> MovedOut:
    """SS-74d: my sample company as it was at the start of that day; the days after it go (plan section 18.5)."""
    from mesiri.application.learn import sandbox_player

    person = await _person(request, payload)
    if body.role.upper() not in sandbox.PLAYABLE_ROLES:
        raise HTTPException(status_code=422, detail=f"role must be one of {list(sandbox.PLAYABLE_ROLES)}")
    try:
        out = await sandbox_player.go_back(_engine(request), person, day=body.day, role=body.role)
    except sandbox.SandboxError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    return MovedOut(**{**out.__dict__, "for_you": [ForYouOut(**f.__dict__) for f in out.for_you]})
