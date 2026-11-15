"""The signed-in person's own preferences (WA-169): the language their WhatsApp replies are in, and how Mesiri
guides them (SS-27: their start mode and the page guides they closed).

Self only: the route reads and writes the caller's own ``users`` row (the id comes from their token,
never from the request), so it grants nothing and changes nobody else. The dashboard and the
WhatsApp assistant (v3 tool ``set_reply_language``) use the same two routes.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Literal

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.authorization.context import AuthorizationContext
from mesiri.domains.organizations import settings as org_settings
from mesiri.domains.projects.router import get_auth_context
from mesiri.infrastructure.postgres.dependency import get_db_conn
from mesiri.infrastructure.postgres.repositories.organization_settings import (
    PostgresOrganizationSettingsRepository,
)

router = APIRouter(prefix="/me", tags=["me"])

#: The reply languages a person can choose (migration 0501's check holds the same list).
REPLY_LANGUAGES: tuple[str, ...] = ("english", "manglish", "malayalam", "hindi", "hinglish")
#: WA-207 (5 Nov 2026, set in session): everyone gets Manglish replies unless they choose otherwise.
DEFAULT_REPLY_LANGUAGE = "manglish"
#: "Reply in my language again": follow the language of each message (stored as itself since migration 0504).
FOLLOW_EACH_MESSAGE = "auto"

#: SS-27: the answers to "How would you like to start?" (migration 0553's check holds the same list).
#: guided: step by step · bring_data: help me bring my Excel in · switching: I've used other construction software ·
#: free: no tips (docs/plans/guided-onboarding-plan.md section 6.1).
START_MODES: tuple[str, ...] = ("guided", "bring_data", "switching", "free")
StartMode = Literal["guided", "bring_data", "switching", "free"]
#: Not answered: a new person is guided (a tip can be closed, a missing one can't be found); someone who was
#: already using Mesiri before this existed is left alone and never asked (D-GO5).
NEW_PERSON_FOR = dt.timedelta(days=14)
#: A dashboard page path as the guides name it ("/today", "/finance/expenses").
_PAGE = re.compile(r"^/[a-z0-9/_-]{0,80}$")
#: A person can close at most this many page guides; past it, the oldest entries are dropped.
GUIDE_SEEN_MAX = 300

_users = sa.Table(
    "users",
    sa.MetaData(),
    sa.Column("id", sa.UUID(as_uuid=True)),
    sa.Column("organization_id", sa.UUID(as_uuid=True)),
    sa.Column("reply_language", sa.String),
    sa.Column("voice_transcript", sa.Boolean),
    sa.Column("start_mode", sa.String),
    sa.Column("guide_seen", postgresql.JSONB),
    sa.Column("created_at", sa.DateTime(timezone=True)),
)


class Preferences(BaseModel):
    #: The language replies are in: a chosen one, "manglish" when none was chosen (WA-207), or "auto" (follow each
    #: message, when they asked for that).
    reply_language: str | None = None
    #: WA-246: a voice note's reply starts with what was heard ("🎤 ..."): the person's own switch, else the
    #: company's ``voice_transcript`` setting; off by default.
    voice_transcript: bool = False
    #: SS-27: how Mesiri guides this person: their answer, or what no answer means for them (start_mode_for).
    start_mode: str = "guided"
    #: SS-28: True only while "How would you like to start?" should be asked (a new person, not answered yet).
    ask_start_mode: bool = False
    #: SS-29/SS-37: per page, the guide version they closed.
    guide_seen: dict[str, int] = Field(default_factory=dict)


class StartModeIn(BaseModel):
    start_mode: StartMode


class GuideSeenIn(BaseModel):
    #: The page whose guide was closed, as a path ("/today").
    page: str
    #: The guide's version (module-map's guideVersion); a later version shows the strip once more.
    version: int = Field(ge=1, le=1000)

    @field_validator("page")
    @classmethod
    def _a_page_path(cls, value: str) -> str:
        if not _PAGE.match(value):
            raise ValueError("page must be a dashboard path such as /today")
        return value


def start_mode_for(stored: str | None, created_at: dt.datetime | None, now: dt.datetime) -> tuple[str, bool]:
    """SS-27/D-GO5: (the mode to use, whether to ask). An answer stands. No answer: a person added in the last
    two weeks is guided and asked; anyone older was using Mesiri before this existed: no tips, never asked."""
    if stored in START_MODES:
        return str(stored), False
    if created_at is not None and created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=dt.UTC)
    if created_at is not None and now - created_at > NEW_PERSON_FOR:
        return "free", False
    return "guided", True


def clean_guide_seen(raw: object) -> dict[str, int]:
    """The stored guide_seen, keeping only page -> version entries that make sense."""
    if not isinstance(raw, dict):
        return {}
    return {
        str(k): int(v) for k, v in raw.items()
        if isinstance(k, str) and _PAGE.match(k) and isinstance(v, int) and not isinstance(v, bool) and v >= 1
    }


class ReplyLanguageIn(BaseModel):
    #: "auto": follow the language of each message.
    reply_language: Literal["english", "manglish", "malayalam", "hindi", "hinglish", "auto"]


def _mine(ctx: AuthorizationContext) -> sa.ColumnElement[bool]:
    return sa.and_(_users.c.id == ctx.user_id, _users.c.organization_id == ctx.organization_id)


@router.get("/preferences", response_model=Preferences)
async def get_preferences(
    ctx: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
) -> Preferences:
    """The caller's preferences: ``reply_language`` (none chosen: Manglish, WA-207; "auto": follow each message) and
    ``voice_transcript`` (WA-246)."""
    row = (await conn.execute(
        sa.select(_users.c.reply_language, _users.c.voice_transcript, _users.c.start_mode, _users.c.guide_seen,
                  _users.c.created_at).where(_mine(ctx))
    )).first()
    mode, ask = start_mode_for(getattr(row, "start_mode", None), getattr(row, "created_at", None), dt.datetime.now(dt.UTC))
    return Preferences(reply_language=effective_reply_language(row.reply_language if row else None),
                       voice_transcript=await _voice_transcript(conn, ctx, row.voice_transcript if row else None),
                       start_mode=mode, ask_start_mode=ask and row is not None,
                       guide_seen=clean_guide_seen(getattr(row, "guide_seen", None)))


async def _voice_transcript(conn: AsyncConnection, ctx: AuthorizationContext, person: bool | None) -> bool:
    """WA-246: the person's own switch, else the company's (one indexed read only when the person has none)."""
    if isinstance(person, bool):
        return person
    company = await PostgresOrganizationSettingsRepository(conn).get(ctx.organization_id, org_settings.VOICE_TRANSCRIPT)
    return org_settings.voice_transcript_shown(None, company)


def effective_reply_language(stored: str | None) -> str:
    """WA-207: what a stored choice means: a language, "auto", or (nothing chosen) Manglish."""
    if stored in REPLY_LANGUAGES or stored == FOLLOW_EACH_MESSAGE:
        return str(stored)
    return DEFAULT_REPLY_LANGUAGE


@router.put("/reply-language", response_model=Preferences)
async def set_reply_language(
    body: ReplyLanguageIn,
    ctx: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
) -> Preferences:
    """Set the language the caller's WhatsApp replies are always in, whatever language they write in;
    ``auto`` follows the language of each message (kept as "auto": no choice at all means Manglish, WA-207)."""
    value = body.reply_language
    result = await conn.execute(_users.update().where(_mine(ctx)).values(reply_language=value))
    if not result.rowcount:
        raise HTTPException(status_code=404, detail="User not found")
    return Preferences(reply_language=value)  # voice_transcript: read with GET


@router.put("/start-mode", response_model=Preferences)
async def set_start_mode(
    body: StartModeIn,
    ctx: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
) -> Preferences:
    """SS-27: the caller's answer to "How would you like to start?" (dashboard, Settings, and the WhatsApp question
    and v3 tool ``set_start_mode``). Changes only how Mesiri guides them, never what they may see or do."""
    result = await conn.execute(_users.update().where(_mine(ctx)).values(start_mode=body.start_mode))
    if not result.rowcount:
        raise HTTPException(status_code=404, detail="User not found")
    return Preferences(start_mode=body.start_mode, ask_start_mode=False)  # the rest: read with GET


@router.post("/guide-seen", response_model=Preferences)
async def mark_guide_seen(
    body: GuideSeenIn,
    ctx: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
) -> Preferences:
    """SS-29: the caller closed a page's guide strip at this version; it shows again only for a later version.
    "Show me around again" is ``DELETE /me/guide-seen``."""
    row = (await conn.execute(sa.select(_users.c.guide_seen).where(_mine(ctx)))).first()
    if row is None:
        raise HTTPException(status_code=404, detail="User not found")
    seen = clean_guide_seen(row.guide_seen)
    seen.pop(body.page, None)
    seen[body.page] = body.version  # newest last, so the oldest go first past the cap
    seen = dict(list(seen.items())[-GUIDE_SEEN_MAX:])
    await conn.execute(_users.update().where(_mine(ctx)).values(guide_seen=seen))
    return Preferences(guide_seen=seen)


@router.delete("/guide-seen", response_model=Preferences)
async def reset_guide_seen(
    ctx: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
) -> Preferences:
    """SS-29 "Show me around again": every page's guide strip shows once more."""
    result = await conn.execute(_users.update().where(_mine(ctx)).values(guide_seen={}))
    if not result.rowcount:
        raise HTTPException(status_code=404, detail="User not found")
    return Preferences(guide_seen={})
