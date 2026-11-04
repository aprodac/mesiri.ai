"""[231]: with Manglish or Hinglish chosen, no reply carries a Malayalam or Devanagari letter; one Ref, the current one.

Reported (4 Nov, Ilan, Manglish chosen): "team-ine അറിയിച്ചിട്ടുണ്ട്" came out in script (cor_4cfb178d, cor_9814a1ec,
the model's own words), and the 13:37 reply ended with two refs: the Confirm tap's older "#a553de" the model copied
from the history, and the current "#9814a1". Fix: the last step before a reply is sent (``latin_reply``) writes any
script word in Latin letters for these two languages; the Ref is always the current message's, whatever the model
wrote. Guards: Malayalam / Hindi chosen stay in script; Latin names, numbers, emoji are untouched.
"""

from __future__ import annotations

import re
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from tests.agent_api.standin import ORG, STAND_IN_TOOLS, USER, stand_in_api
from tests.agent_api.test_api_feedback_126 import CTX, _message

from agent_api import whatsapp as wa
from agent_api.feedback import TELL_THE_TEAM, feedback_instruction
from channel.replies import ListRow, ReplySpec
from mesiri.infrastructure.redis.client import FakeRedis
from mesiri_ai.fakes import FakeToolCallingProvider
from runtime.agent.wording import LINES as TEMPLATES

KEY = f"agent_api:{ORG}:{USER}"
SCRIPT = re.compile(r"[ऀ-ॿഀ-ൿ]")
SLIP = "Ningalude feedback njan team-ine അറിയിച്ചിട്ടുണ്ട്."


@pytest.fixture(autouse=True)
def _tools(monkeypatch: pytest.MonkeyPatch) -> None:
    from agent_api import tools as tools_mod

    real = tools_mod.build_tools
    monkeypatch.setattr(wa, "build_tools", lambda openapi: real(
        openapi, tuple(a for a in tools_mod.ALLOWED if a.name in STAND_IN_TOOLS)))


async def _journey(language: str | None, model_words: str, message=None) -> ReplySpec:
    """Their saved choice, one message that is passed to the team, the reply that goes out."""
    redis = FakeRedis()
    if language:
        await redis.set_json(KEY, {"language": language, "chosen_language": language})
    sent: list[ReplySpec] = []

    async def send(spec: ReplySpec, wa_id: str) -> None:
        sent.append(spec)

    model = FakeToolCallingProvider([[(TELL_THE_TEAM, {"kind": "missing_feature", "about": "x"})], model_words])
    service = wa.ApiWhatsApp(provider=model, database=None, redis=redis, send=send, transcribe=None,
                             message_logger=AsyncMock(), trace_logger=AsyncMock(), app=stand_in_api([]))
    await service.handle(message or _message("Ariyikkuka and ariyichittund parayumbo an Malayalam text verunne"),
                         SimpleNamespace(**vars(CTX)))
    return sent[-1]


async def test_the_1337_reply_has_no_script_and_exactly_the_current_ref() -> None:
    message = _message("Ariyikkuka and ariyichittund parayumbo an Malayalam text verunne")
    message.correlation_id = "cor_9814a1ec3050491888df67a08f239801"
    words = f"Ilan, ee padhangal alle?\n\n{SLIP}\n\nRef #a553de"  # the model copied the older Confirm-tap ref
    reply = await _journey("manglish", words, message)
    assert not SCRIPT.search(reply.text)
    assert "ariyichchittuntu" in reply.text and "team-ine" in reply.text
    assert re.findall(r"#[0-9a-f]{6}", reply.text) == ["#9814a1"]
    assert reply.text.count("Ref") == 1


async def test_the_1328_reply_has_no_script() -> None:
    reply = await _journey("manglish", f"Ilan, saved records-inte web link ippo tharan kazhiyilla. {SLIP}")
    assert not SCRIPT.search(reply.text) and "Ilan" in reply.text


async def test_hinglish_has_no_devanagari() -> None:
    reply = await _journey("hinglish", "Aapka feedback team ko बता दिया। Tower A, 20 bags 👍")
    assert not SCRIPT.search(reply.text)
    assert "bata diya" in reply.text and "Tower A, 20 bags 👍" in reply.text


@pytest.mark.parametrize("language,words", [("malayalam", "നന്ദി 👍 ടീമിനെ അറിയിച്ചു."), ("hindi", "टीम को बता दिया।"),
                                            (None, "Thanks, told the team.")])
async def test_guard_other_languages_are_unchanged(language: str | None, words: str) -> None:
    reply = await _journey(language, words)
    assert reply.text.startswith(words)


def test_latin_reply_covers_buttons_and_leaves_latin_names_alone() -> None:
    spec = ReplySpec(text="Ready: 20 bags Cement, Tower A 👍 ടീം", buttons=(ListRow("a", "ശരി", "ടീം"), ListRow("b", "Cancel")))
    out = wa.latin_reply(spec, "manglish")
    assert not SCRIPT.search(out.text) and out.text.startswith("Ready: 20 bags Cement, Tower A 👍")
    assert [r.title for r in out.buttons][1] == "Cancel" and not SCRIPT.search(out.buttons[0].title + out.buttons[0].description)
    assert wa.latin_reply(spec, "malayalam") is spec


def test_a_site_named_in_malayalam_script_is_shown_in_latin_letters() -> None:
    out = wa.latin_reply(ReplySpec(text="Site: ടവർ A"), "manglish")
    assert not SCRIPT.search(out.text) and out.text.startswith("Site: ")


def test_without_refs_only_removes_refs() -> None:
    assert wa.without_refs("ok\n\nRef #a553de\n\nRef #9814a1") == "ok"
    assert wa.without_refs("Sand #2 at Tower A") == "Sand #2 at Tower A"


@pytest.mark.parametrize("language", ["manglish", "hinglish"])
def test_every_wording_entry_is_in_latin_letters(language: str) -> None:
    bad = [k for k, v in TEMPLATES.items() if SCRIPT.search(v.get(language, ""))]
    assert not bad, bad


def test_the_instruction_after_tell_the_team_asks_for_latin_letters() -> None:
    for kind in ("missing_feature", "bad_ux", "idea"):
        assert "Latin letters only" in feedback_instruction({"kind": kind})
