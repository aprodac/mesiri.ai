"""The signed-in person's own preferences (WA-169): today, the language their WhatsApp replies are in.

Self only: the route reads and writes the caller's own ``users`` row (the id comes from their token,
never from the request), so it grants nothing and changes nobody else. The dashboard and the
WhatsApp assistant (v3 tool ``set_reply_language``) use the same two routes.
"""

from __future__ import annotations

from typing import Literal

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
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

_users = sa.Table(
    "users",
    sa.MetaData(),
    sa.Column("id", sa.UUID(as_uuid=True)),
    sa.Column("organization_id", sa.UUID(as_uuid=True)),
    sa.Column("reply_language", sa.String),
    sa.Column("voice_transcript", sa.Boolean),
    sa.Column("morning_brief", sa.Boolean),
)


class Preferences(BaseModel):
    #: The language replies are in: a chosen one, "manglish" when none was chosen (WA-207), or "auto" (follow each
    #: message, when they asked for that).
    reply_language: str | None = None
    #: WA-246: a voice note's reply starts with what was heard ("🎤 ..."): the person's own switch, else the
    #: company's ``voice_transcript`` setting; off by default.
    voice_transcript: bool = False
    #: GM-08: the 8 am WhatsApp brief (tasks due, what is waiting, what to act on now); on by default.
    morning_brief: bool = True


class MorningBriefIn(BaseModel):
    on: bool


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
    row = (await conn.execute(sa.select(_users.c.reply_language, _users.c.voice_transcript, _users.c.morning_brief)
                              .where(_mine(ctx)))).first()
    return Preferences(reply_language=effective_reply_language(row.reply_language if row else None),
                       voice_transcript=await _voice_transcript(conn, ctx, row.voice_transcript if row else None),
                       morning_brief=getattr(row, "morning_brief", None) is not False)


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


@router.put("/morning-brief")
async def set_morning_brief(
    body: MorningBriefIn,
    ctx: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
) -> dict:
    """GM-08: turn the caller's own 8 am WhatsApp brief on or off."""
    result = await conn.execute(_users.update().where(_mine(ctx)).values(morning_brief=body.on))
    if not result.rowcount:
        raise HTTPException(status_code=404, detail="User not found")
    return {"morning_brief": body.on}
