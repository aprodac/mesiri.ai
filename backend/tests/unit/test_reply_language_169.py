"""WA-169: the caller's own reply language (``users.reply_language``). Self only: the row is the token's user in
the token's company, never one named by the request; ``auto`` clears the choice."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from mesiri.domains.identity import preferences_router as me

ORG, USER = uuid.uuid4(), uuid.uuid4()
CTX = SimpleNamespace(user_id=USER, organization_id=ORG, role="SITE_ENGINEER")


class Conn:
    def __init__(self, stored: str | None = None, rows: int = 1, *, person: bool | None = None,
                 company: object = None) -> None:
        self.stored, self.rows, self.statements = stored, rows, []
        self.person, self.company = person, company

    async def execute(self, statement):  # noqa: ANN001, ANN201
        compiled = statement.compile()
        if statement.is_select and "organization_settings" in str(compiled):  # WA-246: the company's switch
            self.settings_reads = getattr(self, "settings_reads", 0) + 1
            row = None if self.company is None else SimpleNamespace(value=self.company)
            return SimpleNamespace(first=lambda: row)
        self.statements.append(statement)
        if statement.is_select:
            row = SimpleNamespace(reply_language=self.stored, voice_transcript=self.person)
            return SimpleNamespace(first=lambda: row)
        self.stored = compiled.params.get("reply_language")
        return SimpleNamespace(rowcount=self.rows)


def _where_params(conn: Conn) -> set:
    return {v for k, v in conn.statements[-1].compile().params.items() if k.startswith(("id", "organization_id"))}


async def test_set_stores_the_choice_on_the_callers_own_row() -> None:
    conn = Conn()
    out = await me.set_reply_language(me.ReplyLanguageIn(reply_language="manglish"), CTX, conn)
    assert out.reply_language == "manglish" and conn.stored == "manglish"
    assert _where_params(conn) == {USER, ORG}


async def test_auto_is_kept_as_follow_each_message() -> None:
    # WA-207: no choice now means Manglish, so "reply in my language again" is stored as "auto" (migration 0504).
    conn = Conn("manglish")
    out = await me.set_reply_language(me.ReplyLanguageIn(reply_language="auto"), CTX, conn)
    assert out.reply_language == "auto" and conn.stored == "auto"


async def test_no_row_is_a_404() -> None:
    with pytest.raises(HTTPException) as err:
        await me.set_reply_language(me.ReplyLanguageIn(reply_language="hindi"), CTX, Conn(rows=0))
    assert err.value.status_code == 404


def test_an_unknown_language_is_refused() -> None:
    with pytest.raises(ValidationError):
        me.ReplyLanguageIn(reply_language="klingon")


@pytest.mark.parametrize(("stored", "shown"), [("malayalam", "malayalam"), ("auto", "auto"),
                                               (None, "manglish"), ("tamil", "manglish")])  # WA-207: Manglish by default
async def test_get_reads_the_callers_own_row(stored: str | None, shown: str | None) -> None:
    conn = Conn(stored)
    assert (await me.get_preferences(CTX, conn)).reply_language == shown
    assert _where_params(conn) == {USER, ORG}


# WA-246 (Ilan, 5 Nov: "option to turn on or off this for companies or users, and by default for all turn it off"):
# the "🎤 what was heard" line above a voice note's reply.
@pytest.mark.parametrize(("person", "company", "shown"), [
    (None, None, False),     # nothing set anywhere: off for everyone
    (None, True, True),      # the company switched it on
    (None, False, False),
    (False, True, False),    # the person's own off wins over the company's on
    (True, None, True),      # and their on over the company's default
    (None, "yes", False),    # an unreadable company value is off
])
async def test_voice_transcript_person_then_company_then_off(person, company, shown) -> None:  # noqa: ANN001
    conn = Conn(person=person, company=company)
    assert (await me.get_preferences(CTX, conn)).voice_transcript is shown
    assert _where_params(conn) == {USER, ORG}


async def test_a_persons_own_choice_needs_no_company_read() -> None:
    conn = Conn(person=True, company=False)
    await me.get_preferences(CTX, conn)
    assert not getattr(conn, "settings_reads", 0)
