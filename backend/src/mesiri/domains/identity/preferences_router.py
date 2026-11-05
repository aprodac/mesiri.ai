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
from mesiri.domains.projects.router import get_auth_context
from mesiri.infrastructure.postgres.dependency import get_db_conn

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
)


class Preferences(BaseModel):
    #: The language replies are in: a chosen one, "manglish" when none was chosen (WA-207), or "auto" (follow each
    #: message, when they asked for that).
    reply_language: str | None = None


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
    """The caller's preferences: ``reply_language`` (none chosen: Manglish, WA-207; "auto": follow each message)."""
    value = (await conn.execute(sa.select(_users.c.reply_language).where(_mine(ctx)))).scalar_one_or_none()
    return Preferences(reply_language=effective_reply_language(value))


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
    return Preferences(reply_language=value)
