"""[258] (5 Nov 13:07, an admin's Manglish voice note): the reply showed the "🎤 _what was heard_" line twice. The model
copied it: the conversation memory kept each voice reply with its heard line, so the model saw that format and
wrote it again itself. Only the code draws the line, once; the memory keeps the reply without it.

Guards: a voice note's reply still starts with the heard line (WA-209); a typed message gets none; other words of
the model are untouched.
"""

from __future__ import annotations

import pytest
from tests.agent_api.standin import STAND_IN_TOOLS
from tests.agent_api.test_api_whatsapp_119 import CTX, Harness, _message

from agent_api import whatsapp as wa
from mesiri_ai.fakes import FakeToolCallingProvider
from mesiri_contracts.assistant.enums import InputModality

HEARD = "pay helpers, early, work is nearly attendance in the bhagathili k varuga"


@pytest.fixture(autouse=True)
def _stand_in_tools(monkeypatch):  # noqa: ANN001, ANN202
    from agent_api import tools as tools_mod

    real = tools_mod.build_tools
    monkeypatch.setattr(wa, "build_tools", lambda openapi: real(
        openapi, tuple(a for a in tools_mod.ALLOWED if a.name in STAND_IN_TOOLS)))


async def test_the_heard_line_the_model_copied_is_not_shown_twice() -> None:
    model = FakeToolCallingProvider([f"🎤 _{HEARD}_\n\nEthra helpers vannu ennu onnu koodi parayaamo?"])
    h = Harness(model, transcript=HEARD)
    await h.service.handle(_message(None, modality=InputModality.VOICE), CTX)
    text = h.sent[-1].text
    assert text.count("🎤") == 1 and text.startswith(f"🎤 _{HEARD}_\n\n")
    assert text.endswith("Ethra helpers vannu ennu onnu koodi parayaamo?")


def test_the_memory_keeps_the_reply_without_the_heard_line() -> None:
    kept = wa.for_memory(f"🎤 _{HEARD}_\n\nEthra helpers vannu?")
    assert "🎤" not in kept and kept == "Ethra helpers vannu?"


@pytest.mark.parametrize("text", [
    "50 bags cement ready.",
    "Mic button-il record cheythu ayakkoo.",  # the word, not the line
    "Cement 🎤 later",  # an emoji inside a sentence is not the heard line
])
def test_guard_other_words_stay(text: str) -> None:
    assert wa.without_heard_echo(text) == text


async def test_guard_a_typed_message_gets_no_heard_line() -> None:
    model = FakeToolCallingProvider(["Ethra helpers vannu?"])
    h = Harness(model)
    await h.service.handle(_message("helpers ethra"), CTX)
    assert "🎤" not in h.sent[-1].text
