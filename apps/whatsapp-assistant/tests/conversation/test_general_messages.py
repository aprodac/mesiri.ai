"""Eval set for general (non-work) messages (request [68]).

CI runs the structure with a scripted provider: every message goes through the
real agent turn, once with a good reply, once with a bad one that must be
regenerated, once with a model that keeps misbehaving (the fixed floor). The
``live`` test runs the real model and prints a 0/1/2 score per message; it is
not part of CI (``pytest -m live``).
"""

from __future__ import annotations

import os
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from tests.conversation.helpers import load_cases

from channel.replies import ReplySpec
from runtime.agent.runner import AgentResult
from runtime.agent.turn import AgentTurnDeps, run_agent_turn
from runtime.persona import is_what_can_you_do, violations, what_can_you_do

CASES = load_cases()
MAL = re.compile(r"[ഀ-ൿ]")


def test_the_eval_set_has_the_scorecard_messages():
    assert len(CASES) == 34
    assert {c["batch"] for c in CASES} == set("ABCDEFG")


def _toolbox():
    return SimpleNamespace(saved=[], attempted_writes=0, parked=None, answers=[], notes=[])


def _deps(replies, sent, flagged):
    queue = list(replies)

    async def run(**_kwargs):
        text = queue.pop(0) if len(queue) > 1 else queue[0]
        return AgentResult("ok", ReplySpec(text=text), _toolbox())

    return AgentTurnDeps(
        runner=SimpleNamespace(run=run),
        make_gateway=lambda msg, lang: SimpleNamespace(handled=[], finish=AsyncMock()),
        send_spec=lambda spec, wa: _record(sent, spec),
        transcribe=None,
        message_logger=AsyncMock(),
        on_conversational=lambda: flagged.append(True),
    )


async def _record(sent, spec):
    sent.append(spec)


def _message(text):
    from mesiri_contracts.assistant.enums import InputModality

    return SimpleNamespace(
        text=text,
        modality=InputModality.TEXT,
        correlation_id="c1",
        sender=SimpleNamespace(wa_id="9198"),
    )


def _actor():
    return SimpleNamespace(
        user_id="u1", full_name="Ravi Kumar", role="SUPERVISOR", org_name="Acme",
        projects=[], sites=[], organization_id="o1",
    )


def _check(case, text):
    assert len(text) <= case["max_chars"]
    assert violations(text) == []
    if case["lang"] == "ml":
        assert MAL.search(text)
    elif case["lang"] == "manglish":
        assert not MAL.search(text)


GOOD = "Fair enough! Send me today's site update, e.g. “6 masons, 4 helpers”."


@pytest.mark.parametrize("case", CASES, ids=[c["message"] for c in CASES])
async def test_a_clean_reply_goes_out_untouched_as_one_message(case):
    if is_what_can_you_do(case["message"]):
        pytest.skip("answered by the fixed 3-line text, see test_persona")
    sent, flagged = [], []
    deps = _deps([GOOD], sent, flagged)
    await run_agent_turn(_message(case["message"]), _actor(), deps)
    assert [s.text for s in sent] == [GOOD]
    assert flagged == [True]


@pytest.mark.parametrize("case", CASES, ids=[c["message"] for c in CASES])
async def test_a_model_that_keeps_breaking_the_voice_gets_the_fixed_floor(case):
    if is_what_can_you_do(case["message"]):
        pytest.skip("answered by the fixed 3-line text, see test_persona")
    sent, flagged = [], []
    deps = _deps(["I am a large language model, trained by Google."], sent, flagged)
    deps.user_language_store = SimpleNamespace(
        get_profile=AsyncMock(
            return_value=(
                {"manglish": "Malayalam", "ml": "Malayalam"}.get(case["lang"]),
                "latin" if case["lang"] == "manglish" else "native",
            )
        ),
        remember=AsyncMock(),
    )
    await run_agent_turn(_message(case["message"]), _actor(), deps)
    assert len(sent) == 1
    _check(case, sent[0].text)


@pytest.mark.parametrize("case", [c for c in CASES if is_what_can_you_do(c["message"])])
async def test_what_can_you_do_is_the_fixed_text_with_no_model_call(case):
    sent, flagged = [], []
    deps = _deps(["should never be used"], sent, flagged)
    deps.runner = SimpleNamespace(run=AsyncMock(side_effect=AssertionError("model called")))
    await run_agent_turn(_message(case["message"]), _actor(), deps)
    assert len(sent) == 1 and len(sent[0].text.splitlines()) <= 4
    assert sent[0].text == what_can_you_do(None, None, case["message"])
    assert flagged == [True]


@pytest.mark.live
@pytest.mark.parametrize("case", CASES, ids=[c["message"] for c in CASES])
async def test_live_model_scores(case):
    """Real model. Prints 0/1/2 (2 = passes every deterministic trait)."""
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        pytest.skip("GEMINI_API_KEY not set")
    from mesiri.bootstrap.settings import GeminiSettings
    from mesiri_ai.adapters.gemini.adapter import GeminiProvider
    from runtime.agent.gateway import StepResult  # noqa: F401
    from runtime.agent.runner import AgentRunner

    runner = AgentRunner(GeminiProvider(GeminiSettings(api_key=key)))
    sent = []
    deps = _deps(["unused"], sent, [])
    deps.runner = runner
    await run_agent_turn(_message(case["message"]), _actor(), deps)
    text = sent[0].text
    bad = violations(text)
    score = 2 if not bad else 0
    print(f"SCORE {score}/2 | {case['message']!r} -> {text!r} {bad}")
    assert score == 2


# --- multi-turn: the model sees the last turns, no reply repeats (request [75]) ---------

from tests.conversation.helpers import load_sequences  # noqa: E402

from runtime.capability_help import CapabilityHelpService  # noqa: E402


class _ConversationalModel:
    """Stands in for the model: answers by what the prompt shows, once with a
    deliberately repeated line to prove the repeat check regenerates."""

    def __init__(self) -> None:
        self.prompts: list[dict] = []
        self.sent_repeat = False

    async def generate_json(self, system_prompt, user_prompt, *, correlation_id=None):
        import json

        payload = json.loads(user_prompt)
        self.prompts.append(payload)
        said = payload["MESSAGE"].lower()
        previous = [t["you"] for t in payload["RECENT_CONVERSATION"]]
        if "hardcoded" in said:
            text = "No, I read what you write and answer it. I'm focused on your site records."
        elif "anything" in said:
            text = ("Only your company's site work: workers, progress, materials, expenses and "
                    "reports. I don't do general questions like news or weather.")
        elif previous and "curious" in said:
            if not self.sent_repeat:
                self.sent_repeat = True
                text = previous[-1]  # a repeat: must be regenerated
            else:
                text = "Fair enough, curious is good! Ask me anything about the site anytime."
        else:
            text = "Fair enough!"
        import json as _json

        return _json.dumps({"reply": text})


@pytest.mark.parametrize("seq", load_sequences(), ids=[s["id"] for s in load_sequences()])
async def test_a_multi_turn_conversation_gets_distinct_relevant_replies(seq):
    model = _ConversationalModel()
    service = CapabilityHelpService(model)
    turns: list[tuple[str, str]] = []
    replies: list[str] = []
    for step in seq["steps"]:
        out = await service.smalltalk(step["message"], turns=turns)
        assert out.source in {"ai", "ai_retry"}  # never the fixed floor
        assert violations(out.text) == []
        low = out.text.lower()
        assert any(w in low for w in step["any_of"]), (step["message"], out.text)
        if "also_any_of" in step:
            assert any(w in low for w in step["also_any_of"]), (step["message"], out.text)
        turns.append((step["message"], out.text))
        replies.append(out.text)
    assert len(set(replies)) == len(replies)
    assert model.sent_repeat  # the repeat check fired on the follow-up
    # the follow-up was written with the scope answer in view
    assert "only your company" in str(model.prompts[-1]["RECENT_CONVERSATION"]).lower()
