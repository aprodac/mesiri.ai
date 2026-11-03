"""WA-169: a reply language the person chose is kept in the database (``users.reply_language``) and always wins.

Reported (3 Nov): the language of every reply was re-decided from each message, so a person who wanted Manglish got
English after an English message and Malayalam script after a Malayalam one. The classic choice lived only in Redis
and v3 never read it. Now: ``PUT /me/reply-language`` (v3 tool ``set_reply_language``, the dashboard too) stores it;
every v3 turn reads ``GET /me/preferences`` beside the facts and the one decision (``_turn_language``) puts the choice
first. Guards: with no choice, the message still decides (WA-165's "Tower A" keeps theirs); an unreadable choice
keeps the last one known; ``auto`` goes back to following each message.
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import Depends, FastAPI
from pydantic import BaseModel
from tests.agent_api.standin import ORG, USER
from tests.agent_api.test_api_whatsapp_119 import CTX, FakeRedis, _message

from agent_api import whatsapp as wa
from agent_api.tools import ALLOWED, build_tools
from mesiri.domains.identity import preferences_router
from mesiri_ai.fakes import FakeToolCallingProvider

KEY = f"agent_api:{ORG}:{USER}"


class Choice(BaseModel):
    reply_language: str


class Prefs:
    """The two /me routes as the real router answers them; ``broken`` = the read fails."""

    def __init__(self, chosen: str | None = None, *, broken: bool = False) -> None:
        self.chosen, self.broken, self.reads = chosen, broken, 0

    def api(self) -> FastAPI:
        from fastapi import HTTPException

        from mesiri.domains.shared.auth import get_current_user

        app = FastAPI()

        @app.get("/me/preferences")
        async def get(jwt: dict = Depends(get_current_user)):
            self.reads += 1
            if self.broken:
                raise HTTPException(status_code=500, detail="db down")
            assert jwt["sub"] == USER  # always the caller's own row
            return {"reply_language": self.chosen}

        @app.put("/me/reply-language")
        async def put(body: Choice, jwt: dict = Depends(get_current_user)):
            self.chosen = None if body.reply_language == "auto" else body.reply_language
            return {"reply_language": self.chosen}

        return app


class Harness:
    def __init__(self, prefs: Prefs, model: FakeToolCallingProvider) -> None:
        from unittest.mock import AsyncMock

        self.sent: list = []
        self.redis = FakeRedis()
        self.model = model

        async def send(spec: Any, wa_id: str) -> None:
            self.sent.append(spec)

        self.service = wa.ApiWhatsApp(provider=model, database=None, redis=self.redis, send=send, transcribe=None,
                                      message_logger=AsyncMock(), trace_logger=AsyncMock(), app=prefs.api())

    async def say(self, text: str) -> None:
        await self.service.handle(_message(text), SimpleNamespace(**vars(CTX)))

    async def state(self) -> dict:
        return await self.redis.get_json(KEY) or {}


@pytest.fixture(autouse=True)
def _tools(monkeypatch: pytest.MonkeyPatch) -> None:
    from agent_api import tools as tools_mod

    real = tools_mod.build_tools
    monkeypatch.setattr(wa, "build_tools",
                        lambda openapi: real(openapi, tuple(a for a in ALLOWED if a.name == "set_reply_language")))


# -- the reported case: Manglish chosen, an English / Malayalam-script message still gets Manglish ----------------

@pytest.mark.parametrize("said", ["how much cement is left?", "ഇന്ന് 200 ഇഷ്ടിക വന്നു", "Tower A"])
async def test_a_chosen_language_wins_over_the_language_of_the_message(said: str) -> None:
    h = Harness(Prefs("manglish"), FakeToolCallingProvider(["Sheri."]))
    await h.say(said)
    assert "chose to always get replies in Manglish" in (h.model.last_system_prompt or "")
    assert "This message is in" not in (h.model.last_system_prompt or "")
    state = await h.state()
    assert state["language"] == "manglish" and state["chosen_language"] == "manglish"


async def test_sibling_code_written_lines_follow_the_choice_too() -> None:
    """A voice note that could not be heard is worded by the code (no model): the choice from the last turn holds."""
    h = Harness(Prefs("malayalam"), FakeToolCallingProvider(["ശരി."]))
    await h.say("ok")
    assert await h.service._language_of_sender(SimpleNamespace(**vars(CTX)), "how are you?") == "malayalam"


# -- guards -----------------------------------------------------------------------------------------------------

async def test_guard_no_choice_the_message_decides_as_before() -> None:
    h = Harness(Prefs(None), FakeToolCallingProvider(["Ok."]))
    await h.say("how much cement is left?")
    assert "This message is in English" in (h.model.last_system_prompt or "")
    assert "chose to always" not in (h.model.last_system_prompt or "")
    assert "chosen_language" not in await h.state()


async def test_guard_no_choice_a_site_name_keeps_their_language() -> None:
    h = Harness(Prefs(None), FakeToolCallingProvider(["ശരി."]))
    await h.redis.set_json(KEY, {"language": "malayalam", "pending_at": time.time()})
    await h.say("Tower A")
    assert (await h.state())["language"] == "malayalam"


async def test_guard_an_unreadable_choice_keeps_the_last_one_known() -> None:
    h = Harness(Prefs(broken=True), FakeToolCallingProvider(["Sheri."]))
    await h.redis.set_json(KEY, {"language": "manglish", "chosen_language": "manglish"})
    await h.say("how much cement is left?")
    assert "chose to always get replies in Manglish" in (h.model.last_system_prompt or "")


async def test_guard_a_cleared_choice_goes_back_to_following_each_message() -> None:
    prefs = Prefs("manglish")
    h = Harness(prefs, FakeToolCallingProvider(["Ok."]))
    await h.redis.set_json(KEY, {"language": "manglish", "chosen_language": "manglish"})
    prefs.chosen = None  # "auto" saved from the dashboard or WhatsApp
    await h.say("how much cement is left?")
    assert "This message is in English" in (h.model.last_system_prompt or "")
    assert "chosen_language" not in await h.state()


def test_unit_the_one_decision() -> None:
    assert wa._turn_language("how much cement is left?", {"chosen_language": "hinglish"}) == "hinglish"
    assert wa._turn_language("how much cement is left?", {"language": "malayalam"}) == "english"
    assert wa._turn_language("Tower A", {"language": "malayalam"}) == "malayalam"
    assert wa._turn_language("hi", {"chosen_language": "klingon"}) == "english"  # never an unknown value


# -- the route and the tool -------------------------------------------------------------------------------------

def test_the_tool_is_the_real_route_and_a_write_held_for_save() -> None:
    app = FastAPI()
    app.include_router(preferences_router.router)
    tools = build_tools(app.openapi(), tuple(a for a in ALLOWED if a.name == "set_reply_language"))
    tool = tools["set_reply_language"]
    assert tool.is_write and tool.method == "PUT" and tool.path == "/me/reply-language"
    enum = tool.spec.parameters["properties"]["reply_language"]["enum"]
    assert set(enum) == {*preferences_router.REPLY_LANGUAGES, "auto"}
    assert set(preferences_router.REPLY_LANGUAGES) == set(wa.LANGUAGE_LINES)  # the column holds what v3 speaks


def test_the_migration_check_holds_the_same_values() -> None:
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[4] / "backend/migrations/versions/0501_users_reply_language.py"
    spec = importlib.util.spec_from_file_location("m0501", path)
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    assert module._VALUES == preferences_router.REPLY_LANGUAGES
    assert module.down_revision == "0500"
