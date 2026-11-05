"""WEB-58 (5 Nov): a v3 voice note kept neither its words nor their English on the message (0 of 53 in production), so
the dashboard's Live showed it empty and could not turn Malayalam into English. The speech step already gives both in
one call; they now go on the message (``update_body_text``, as classic did), in the background. And a reply never
carries the code's note on an older Mesiri's replies (the model copied it into "Hello sukhamaano" on 5 Nov).
"""

from __future__ import annotations

import asyncio

import pytest
from tests.agent_api.standin import STAND_IN_TOOLS, two_receipts_model
from tests.agent_api.test_api_whatsapp_119 import CTX, Harness, _message

from agent_api import memory
from agent_api import whatsapp as wa
from agent_api.reply_guard import without_ids, without_internals
from mesiri_contracts.assistant.enums import InputModality


@pytest.fixture(autouse=True)
def _stand_in_tools(monkeypatch):  # noqa: ANN001, ANN202 -- as test_api_whatsapp_119 does
    from agent_api import tools as tools_mod

    real = tools_mod.build_tools
    monkeypatch.setattr(wa, "build_tools", lambda openapi: real(
        openapi, tuple(a for a in tools_mod.ALLOWED if a.name in STAND_IN_TOOLS)))


async def _settle() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


def _kept(h: Harness) -> list[dict]:
    return [c.kwargs for c in h.logger.update_body_text.await_args_list]


async def test_a_malayalam_voice_note_keeps_its_words_and_english() -> None:
    h = Harness(two_receipts_model(), transcript="ഇന്ന് 50 ചാക്ക് സിമന്റ് വന്നു")

    async def transcribe(message, hint=None):  # noqa: ANN001, ANN202 -- the speech step: words, English, language
        return "ഇന്ന് 50 ചാക്ക് സിമന്റ് വന്നു", "50 bags of cement came today", "ml"

    h.service._transcribe = transcribe
    note = _message(None, modality=InputModality.VOICE)
    await h.service.handle(note, CTX)
    await _settle()

    assert _kept(h)[-1] == {
        "correlation_id": note.correlation_id,
        "body_text": "ഇന്ന് 50 ചാക്ക് സിമന്റ് വന്നു",
        "translated_text": "50 bags of cement came today",
    }


async def test_an_english_voice_note_keeps_its_words_without_a_copy_as_english() -> None:
    h = Harness(two_receipts_model(), transcript="50 bags cement came")

    async def transcribe(message, hint=None):  # noqa: ANN001, ANN202
        return "50 bags cement came", "50 Bags cement came", "en"

    h.service._transcribe = transcribe
    await h.service.handle(_message(None, modality=InputModality.VOICE), CTX)
    await _settle()

    assert _kept(h)[-1]["translated_text"] is None and _kept(h)[-1]["body_text"] == "50 bags cement came"


async def test_a_typed_message_and_an_unheard_voice_note_write_nothing() -> None:
    typed = Harness(two_receipts_model())
    await typed.service.handle(_message(), CTX)
    unheard = Harness(two_receipts_model(), transcript="")
    await unheard.service.handle(_message(None, modality=InputModality.VOICE), CTX)
    await _settle()

    assert _kept(typed) == [] and _kept(unheard) == []


def test_a_reply_never_carries_the_older_mesiri_note() -> None:
    said = "🎤 _Hello sukhamaano_ " + memory.OLDER_NOTE + "Hello Ilan! Enikku kuzhappamilla."
    assert without_ids(said) == "🎤 _Hello sukhamaano_ Hello Ilan! Enikku kuzhappamilla."
    # A sibling: the note mid-reply, and in the final clean-up every reply goes through.
    assert "older version" not in without_internals("Sure. " + memory.OLDER_NOTE + "Cement 40 bags.")
    # The guard: words that only mention an older version are kept.
    assert without_ids("An older version of the drawing is on site.") == "An older version of the drawing is on site."
