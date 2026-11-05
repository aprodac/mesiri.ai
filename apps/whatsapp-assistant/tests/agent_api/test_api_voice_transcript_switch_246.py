"""WA-246 (Ilan, 5 Nov 2026, on a voice note's reply that began "🎤 _Hello sukhamaano_"): "we need in the control panel
an option to turn this on or off for companies or users, and by default for all turn it off".

Root cause: the "🎤 _what was heard_" line (WA-209) was drawn on every voice note's reply, with no switch.
Fix: ``GET /me/preferences`` says ``voice_transcript`` (the person's own switch, else the company's setting, else
off); v3 reads it in the preferences read it already makes each turn (no new call on the reply path), and draws the
line only when it is true.

Guards: switched on, the reply is exactly as before (WA-209); off, a heard line the model copied from the history
is still taken out ([258]); a typed message never gets one; the reply under it is unchanged.
"""

from __future__ import annotations

import pytest
from tests.agent_api.standin import STAND_IN_TOOLS, two_receipts_model
from tests.agent_api.test_api_whatsapp_119 import CTX, Harness, _message

from agent_api import whatsapp as wa
from mesiri_ai.fakes import FakeToolCallingProvider
from mesiri_contracts.assistant.enums import InputModality

SAID = "50 bag cement, 50 TMT vannu"


@pytest.fixture(autouse=True)
def _stand_in_tools(monkeypatch):  # noqa: ANN001, ANN202
    from agent_api import tools as tools_mod

    real = tools_mod.build_tools
    monkeypatch.setattr(wa, "build_tools", lambda openapi: real(
        openapi, tuple(a for a in tools_mod.ALLOWED if a.name in STAND_IN_TOOLS)))


@pytest.mark.parametrize("switch", [False, None])  # None: the preferences could not be read
async def test_off_or_unread_a_voice_notes_reply_has_no_heard_line(switch) -> None:  # noqa: ANN001
    h = Harness(two_receipts_model(), transcript=SAID, voice_transcript=switch)
    await h.service.handle(_message(None, modality=InputModality.VOICE), CTX)
    reply = h.sent[-1]
    assert "🎤" not in reply.text
    assert reply.text.startswith("Ready: 50 bags cement") and "*Ready to save:*" in reply.text
    assert [b.title for b in reply.buttons] == ["Save", wa.EDIT_TITLE, "Cancel"]


async def test_on_the_reply_starts_with_what_was_heard() -> None:
    h = Harness(two_receipts_model(), transcript=SAID, voice_transcript=True)
    await h.service.handle(_message(None, modality=InputModality.VOICE), CTX)
    assert h.sent[-1].text.startswith(f"🎤 _{SAID}_\n\nReady: 50 bags cement")


async def test_guard_off_a_heard_line_the_model_copied_is_still_taken_out() -> None:
    model = FakeToolCallingProvider([f"🎤 _{SAID}_\n\nEthra helpers vannu?"])
    h = Harness(model, transcript=SAID, voice_transcript=False)
    await h.service.handle(_message(None, modality=InputModality.VOICE), CTX)
    assert "🎤" not in h.sent[-1].text and h.sent[-1].text.endswith("Ethra helpers vannu?")


async def test_guard_on_a_typed_message_still_has_none() -> None:
    h = Harness(two_receipts_model(), voice_transcript=True)
    await h.service.handle(_message(), CTX)
    assert "🎤" not in h.sent[-1].text


async def test_nothing_is_left_behind_per_message() -> None:
    h = Harness(two_receipts_model(), transcript=SAID, voice_transcript=True)
    await h.service.handle(_message(None, modality=InputModality.VOICE), CTX)
    assert h.service._heard_shown == {}
