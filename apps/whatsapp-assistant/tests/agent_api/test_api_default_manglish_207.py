"""WA-207 (5 Nov 2026, set in session): everyone is answered in Manglish unless they chose otherwise.

No choice (NULL in ``users.reply_language``) now means Manglish, whatever language the message is in. A chosen language
still wins; "reply in my language again" is stored as "auto" and follows each message, as before WA-207.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel
from tests.agent_api.test_api_whatsapp_119 import CTX, FakeRedis, _message

from agent_api import whatsapp as wa
from agent_api.tools import ALLOWED
from mesiri.domains.identity.preferences_router import effective_reply_language
from mesiri.domains.shared.auth import get_current_user
from mesiri_ai.fakes import FakeToolCallingProvider

pytestmark = pytest.mark.default_language

MANGLISH = "This person chose to always get replies in Manglish"


@pytest.fixture(autouse=True)
def _tools(monkeypatch: pytest.MonkeyPatch) -> None:
    from agent_api import tools as tools_mod

    real = tools_mod.build_tools
    monkeypatch.setattr(wa, "build_tools",
                        lambda openapi: real(openapi, tuple(a for a in ALLOWED if a.name == "set_reply_language")))


class _Choice(BaseModel):
    reply_language: str


def _api(stored: list, *, broken: bool = False) -> FastAPI:
    """The two /me routes as the real router answers them since WA-207."""
    app = FastAPI()

    @app.get("/me/preferences")
    async def get(jwt: dict = Depends(get_current_user)):
        if broken:
            raise HTTPException(status_code=500, detail="db down")
        return {"reply_language": effective_reply_language(stored[0])}

    @app.put("/me/reply-language")
    async def put(body: _Choice, jwt: dict = Depends(get_current_user)):
        stored[0] = body.reply_language
        return {"reply_language": effective_reply_language(stored[0])}

    return app


async def _prompt(text: str, stored: str | None, *, broken: bool = False) -> str:
    from unittest.mock import AsyncMock

    model = FakeToolCallingProvider(["Sheri."])

    async def send(spec: Any, wa_id: str) -> None:
        return None

    service = wa.ApiWhatsApp(provider=model, database=None, redis=FakeRedis(), send=send, transcribe=None,
                             message_logger=AsyncMock(), trace_logger=AsyncMock(), app=_api([stored], broken=broken))
    await service.handle(_message(text), SimpleNamespace(**vars(CTX)))
    return model.last_system_prompt or ""


@pytest.mark.parametrize("text", ["20 bags cement came today", "ഇന്ന് 20 ചാക്ക് സിമന്റ് വന്നു", "aaj 20 bag cement aaya"])
async def test_no_choice_is_manglish_whatever_the_message_is_in(text: str) -> None:
    assert MANGLISH in await _prompt(text, None)


async def test_no_choice_and_the_choice_unreadable_is_still_manglish() -> None:
    assert MANGLISH in await _prompt("20 bags cement came today", None, broken=True)


async def test_guard_a_chosen_language_still_wins() -> None:
    prompt = await _prompt("innu 20 bag cement vannu", "english")
    assert "always get replies in English" in prompt and MANGLISH not in prompt


async def test_guard_auto_follows_each_message_as_before() -> None:
    prompt = await _prompt("20 bags cement came today", "auto")
    assert "This message is in English" in prompt and MANGLISH not in prompt


def test_the_backend_reads_a_stored_choice_the_same_way() -> None:
    assert effective_reply_language(None) == "manglish"
    assert effective_reply_language("auto") == "auto"
    assert effective_reply_language("malayalam") == "malayalam"
    assert effective_reply_language("klingon") == "manglish"
