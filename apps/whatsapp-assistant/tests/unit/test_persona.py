"""Request [68]: the Mesiri voice guardrail, the fixed "what can you do", the
read-only "today so far" line, and one message for a conversational reply."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from channel.replies import ReplySpec
from runtime import persona
from runtime.agent.prompt import SYSTEM_PROMPT, AgentContext, render_context
from runtime.agent.runner import AgentResult
from runtime.agent.turn import AgentTurnDeps, run_agent_turn
from runtime.today_context import build_today_line, render_line


@pytest.mark.parametrize(
    "text",
    [
        "I am a large language model, trained by Google.",
        "I'm built on Gemini.",
        "That's an OpenAI thing.",
        "I run on GPT-4.",
        "I'm a language model.",
        "I was trained by a big company.",
        "How can I help you today?",
        "x" * 401,
        "Sure:\n1. Tell me\n2. Ask me\n3. Get reports",
    ],
)
def test_each_banned_shape_is_rejected(text):
    assert persona.violations(text)


def test_a_plain_reply_passes():
    assert persona.violations("I'm Mesiri's site assistant. Try “cement stock?”.") == []


async def test_a_bad_reply_is_regenerated_once_then_accepted():
    calls = []

    async def regen(rules):
        calls.append(rules)
        return "Hey! Send me today's update."

    out = await persona.guard("trained by Google", user_text="hi", regenerate=regen)
    assert out.text == "Hey! Send me today's update."
    assert not out.fell_back and calls == [["provider_or_model_named"]]


async def test_a_second_bad_reply_falls_back_to_the_fixed_line():
    async def regen(rules):
        return "How can I help you today?"

    out = await persona.guard("Gemini here", user_text="hi", regenerate=regen)
    assert out.fell_back and persona.violations(out.text) == []
    assert len(out.hits) == 2


async def test_a_failing_regeneration_falls_back_too():
    async def regen(rules):
        raise RuntimeError("provider down")

    out = await persona.guard("Gemini here", user_text="hi", regenerate=regen)
    assert out.fell_back


def test_the_fallback_pick_is_stable_per_text_and_varies_across_texts():
    assert persona.fallback_line("are you hardcoded") == persona.fallback_line("Are you hardcoded ")
    picks = {persona.fallback_line(t) for t in ("a", "b", "c", "d", "e", "f", "g", "h", "i", "j")}
    assert len(picks) > 1


def test_what_can_you_do_in_english_manglish_and_malayalam():
    en = persona.what_can_you_do()
    manglish = persona.what_can_you_do("Malayalam", "latin")
    ml = persona.what_can_you_do("Malayalam", "native")
    for text in (en, manglish, ml):
        assert len(text.splitlines()) == 4 and set(persona.violations(text)) <= {"menu"}  # it IS the 3-point answer
    assert "Tell me" in en and "Njan" in manglish
    assert "സൈറ്റ്" in ml and ml != manglish
    # the message itself can be in Malayalam script even when no language is stored
    assert persona.what_can_you_do(None, None, "എന്താ ചെയ്യാൻ പറ്റുക?") == ml


@pytest.mark.parametrize(
    "text", ["what can you do?", "What can you do", "enthokke cheyyan pattum", "എന്താ ചെയ്യാൻ പറ്റുക?"]
)
def test_the_what_can_you_do_question_is_recognised(text):
    assert persona.is_what_can_you_do(text)


@pytest.mark.parametrize("text", ["what can you do about the leak on floor 3", "6 mason vannu", "hi"])
def test_other_messages_are_not(text):
    assert not persona.is_what_can_you_do(text)


def test_the_voice_is_in_the_agent_prompt_and_context_line_renders():
    assert "Mesiri voice" in SYSTEM_PROMPT and "-> " in SYSTEM_PROMPT
    ctx = AgentContext(
        user_name="Anil", role="S", company="Acme", now=__import__("datetime").datetime(2026, 10, 20, 9),
        today_line="Today so far: Anil, Site A1. Nothing saved yet today.",
    )
    assert "Today so far" in render_context(ctx)


def test_today_line_names_the_work_saved():
    line = render_line("Anil", "Site A1", {"activities": [{"work_type": "Plastering"}, {"work_type": "plastering"}]})
    assert line == "Today so far: Anil, Site A1. Saved today: Plastering."


async def test_a_slow_context_lookup_is_left_out():
    async def slow(**_kw):
        await asyncio.sleep(1)
        return {"activities": []}

    service = SimpleNamespace(search=slow)
    actor = SimpleNamespace(organization_id="o", full_name="Anil K", sites=[])
    assert await build_today_line(service, actor, timeout=0.01) is None


async def test_a_failing_or_missing_context_lookup_is_left_out():
    actor = SimpleNamespace(organization_id="o", full_name="Anil K", sites=[])
    boom = SimpleNamespace(search=AsyncMock(side_effect=RuntimeError("db")))
    assert await build_today_line(boom, actor) is None
    assert await build_today_line(None, actor) is None


# -- one message: no setup nudge after a question reply -----------------------------


def _toolbox(**kw):
    base = dict(saved=[], attempted_writes=0, parked=None, answers=[], notes=[])
    base.update(kw)
    return SimpleNamespace(**base)


async def _turn(toolbox, text="Not much, you?"):
    flagged = []

    async def run(**_kw):
        return AgentResult("ok", ReplySpec(text=text), toolbox)

    deps = AgentTurnDeps(
        runner=SimpleNamespace(run=run),
        make_gateway=lambda m, lang: SimpleNamespace(handled=[], finish=AsyncMock()),
        send_spec=AsyncMock(),
        transcribe=None,
        message_logger=AsyncMock(),
        on_conversational=lambda: flagged.append(1),
    )
    from mesiri_contracts.assistant.enums import InputModality

    msg = SimpleNamespace(
        text="how are you", modality=InputModality.TEXT, correlation_id="c", sender=SimpleNamespace(wa_id="1")
    )
    actor = SimpleNamespace(
        user_id="u", full_name="A", role="S", org_name="O", projects=[], sites=[], organization_id="o"
    )
    await run_agent_turn(msg, actor, deps)
    return flagged


async def test_a_small_talk_reply_holds_setup_nudges():
    assert await _turn(_toolbox()) == [1]


async def test_a_reply_that_saved_something_does_not_mark_conversational():
    assert await _turn(_toolbox(saved=[object()])) == []
