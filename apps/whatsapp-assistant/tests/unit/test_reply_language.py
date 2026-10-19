"""WA-11: conversational replies in the sender's language.

ReplyComposer writes a greeting / small-talk / "what can you do?" reply in
the sender's language (and may answer their small talk first); anything that
goes wrong sends the English reply instead. UserLanguageStore remembers the
language each sender last spoke, so even the instant "hi" answer follows it.
"""

from __future__ import annotations

import asyncio
import inspect
import json

import pytest

from runtime.reply_language import ReplyComposer, UserLanguageStore, normalize_language

REPLY = "I'm here to help. Just send me what happened on site today."


class _Ai:
    def __init__(self, text: str | None = "സഹായിക്കാൻ ഞാൻ ഇവിടെയുണ്ട്.", *, raw: str | None = None, delay: float = 0.0, fail: bool = False):
        self.text = text
        self.raw = raw
        self.delay = delay
        self.fail = fail
        self.calls: list[dict] = []

    async def generate_json(self, *, system_prompt: str, user_prompt: str, correlation_id=None) -> str:
        self.calls.append(json.loads(user_prompt))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail:
            raise RuntimeError("provider down")
        return self.raw if self.raw is not None else json.dumps({"text": self.text}, ensure_ascii=False)


@pytest.mark.parametrize(
    ("value", "expected"),
    [("Malayalam", "Malayalam"), (" ml ", "ml"), ("English", None), ("en", None), ("", None), (None, None), ("unknown", None)],
)
def test_language_names_and_english(value, expected):
    assert normalize_language(value) == expected


async def test_english_with_nothing_to_answer_needs_no_ai_call():
    ai = _Ai()
    assert await ReplyComposer(ai).compose(REPLY, language="English") == REPLY
    assert ai.calls == []


async def test_a_malayalam_speaker_gets_malayalam():
    ai = _Ai()
    composed = await ReplyComposer(ai).compose(REPLY, language="Malayalam", user_message="സുഖമാണോ")
    assert composed == "സഹായിക്കാൻ ഞാൻ ഇവിടെയുണ്ട്."
    [call] = ai.calls
    assert call["LANGUAGE"] == "Malayalam" and call["MESSAGE"] == "സുഖമാണോ" and call["REPLY"] == REPLY


async def test_english_small_talk_is_answered_too():
    ai = _Ai(text="I'm good, thanks! " + REPLY)
    composed = await ReplyComposer(ai).compose(REPLY, language=None, user_message="how are you?")
    assert composed.startswith("I'm good")
    assert ai.calls[0]["LANGUAGE"] == "English"


@pytest.mark.parametrize(
    "ai",
    [
        _Ai(fail=True),
        _Ai(raw="not json"),
        _Ai(text=""),
        _Ai(text="x" * 5000),  # far longer than the reply: content was added
    ],
)
async def test_anything_wrong_sends_the_english_reply(ai):
    assert await ReplyComposer(ai).compose(REPLY, language="Hindi") == REPLY


async def test_a_slow_answer_sends_the_english_reply():
    ai = _Ai(delay=1.0)
    assert await ReplyComposer(ai, timeout_seconds=0.05).compose(REPLY, language="Tamil") == REPLY


async def test_fixed_replies_are_composed_once_per_language():
    ai = _Ai()
    composer = ReplyComposer(ai)
    first = await composer.compose(REPLY, language="Malayalam")
    second = await composer.compose(REPLY, language="Malayalam")
    assert first == second
    assert len(ai.calls) == 1


class _Redis:
    def __init__(self, *, broken: bool = False):
        self.data: dict = {}
        self.broken = broken

    def namespaced(self, *parts: str) -> str:
        return ":".join(parts)

    async def set_json(self, key, value, *, ttl_seconds=None):
        if self.broken:
            raise ConnectionError("redis down")
        self.data[key] = value

    async def get_json(self, key):
        if self.broken:
            raise ConnectionError("redis down")
        return self.data.get(key)


async def test_the_language_a_sender_speaks_is_remembered():
    store = UserLanguageStore(_Redis())
    await store.remember(user_id="u1", detected_language="Malayalam")
    assert await store.get(user_id="u1") == "Malayalam"


async def test_switching_back_to_english_is_remembered_as_english():
    store = UserLanguageStore(_Redis())
    await store.remember(user_id="u1", detected_language="Malayalam")
    await store.remember(user_id="u1", detected_language="English")
    assert await store.get(user_id="u1") is None


async def test_nothing_detected_keeps_what_was_known():
    store = UserLanguageStore(_Redis())
    await store.remember(user_id="u1", detected_language="Hindi")
    await store.remember(user_id="u1", detected_language=None)
    assert await store.get(user_id="u1") == "Hindi"


async def test_a_redis_problem_never_breaks_a_reply():
    store = UserLanguageStore(_Redis(broken=True))
    await store.remember(user_id="u1", detected_language="Hindi")
    assert await store.get(user_id="u1") is None


def test_only_conversational_replies_are_composed_and_greetings_follow_the_language():
    """Workflow prompts, confirmations and receipts carry exact numbers and
    names and must not go through the composer; the instant "hi" answer must
    use the remembered language."""
    import runtime.inbound_journey.process as process
    import runtime.message_journey as journey

    source = inspect.getsource(process)
    block = source[source.index("# WA-11: a conversational reply") : source.index("# WA-01 save first")]
    assert "planner_decision.decision_type is PlannerDecisionType.DIRECT_REPLY" in block
    assert "workflow_run is None" in block and "held_reply is None" in block
    assert "await user_language_store.remember(" in source

    journey_source = inspect.getsource(journey)
    assert "await user_language_store.get_profile(user_id=ctx.user_id)" in journey_source


def test_the_overview_has_an_example_and_no_module_list():
    from channel.replies import render_capability_answer

    text = render_capability_answer([]).text
    assert "“6 masons and 4 helpers" in text
    assert "money" not in text.lower()


# --- Reply in the script the sender typed (request [55]) -------------------------

MANGLISH = "njan site il ethi, innu slab concrete cheythu"


async def test_manglish_is_stored_as_latin_script():
    store = UserLanguageStore(_Redis())
    await store.remember(user_id="u1", detected_language="Malayalam", detected_script="latin")
    assert await store.get_profile(user_id="u1") == ("Malayalam", "latin")


async def test_script_is_inferred_from_the_text_when_the_model_did_not_report_it():
    store = UserLanguageStore(_Redis())
    await store.remember(user_id="u1", detected_language="Malayalam", text=MANGLISH)
    assert await store.get_script(user_id="u1") == "latin"
    await store.remember(user_id="u1", detected_language="Malayalam", text="ഇന്ന് സ്ലാബ് ചെയ്തു")
    assert await store.get_script(user_id="u1") == "native"


async def test_script_defaults_to_native_and_english_is_never_latin_script():
    store = UserLanguageStore(_Redis())
    assert await store.get_script(user_id="nobody") == "native"
    await store.remember(user_id="u1", detected_language="English", text="used 10 bags cement")
    assert await store.get_profile(user_id="u1") == (None, "native")


async def test_compose_asks_for_english_letters_for_a_latin_script_sender():
    ai = _Ai(text="Sheri, njan note cheythu.")
    composed = await ReplyComposer(ai).compose(REPLY, language="Malayalam", script="latin")
    assert composed == "Sheri, njan note cheythu."
    [call] = ai.calls
    assert call["SCRIPT"] == "latin"
    from runtime.reply_language import _SYSTEM_PROMPT

    assert "English/Roman letters" in _SYSTEM_PROMPT


async def test_script_is_part_of_the_composed_reply_cache_key():
    ai = _Ai()
    composer = ReplyComposer(ai)
    await composer.compose(REPLY, language="Malayalam", script="native")
    await composer.compose(REPLY, language="Malayalam", script="latin")
    assert [c["SCRIPT"] for c in ai.calls] == ["native", "latin"]


def test_fixed_replies_for_a_latin_script_sender_stay_english_not_malayalam_script():
    from channel.replies import ReplySpec
    from runtime.reply_language import localize_fixed_reply, localize_reply_spec

    text = "✅ Recorded. Thank you."
    assert localize_fixed_reply(text, "Malayalam", "latin") == text
    assert localize_fixed_reply(text, "Malayalam", "native") != text
    assert localize_fixed_reply(text, "Malayalam") != text  # script unknown = native, as before
    spec = ReplySpec(text=text)
    assert localize_reply_spec(spec, "Malayalam", "latin") is spec


def test_extraction_result_keeps_only_a_known_script():
    from mesiri_ai.models import ExtractionResult

    assert ExtractionResult(detected_script=" Latin ").detected_script == "latin"
    assert ExtractionResult(detected_script="klingon").detected_script is None
    assert ExtractionResult().detected_script is None


def test_the_agent_is_told_to_answer_manglish_in_english_letters():
    from datetime import datetime

    from runtime.agent.prompt import SYSTEM_PROMPT, AgentContext, render_context

    assert "English letters" in SYSTEM_PROMPT and "Manglish" in SYSTEM_PROMPT
    ctx = AgentContext(
        user_name="Ravi", role="SITE_ENGINEER", company="Acme", now=datetime(2026, 10, 19, 9, 0),
        last_language="Malayalam", last_script="latin",
    )
    assert "English letters" in render_context(ctx)
    native = AgentContext(
        user_name="Ravi", role="SITE_ENGINEER", company="Acme", now=datetime(2026, 10, 19, 9, 0),
        last_language="Malayalam", last_script="native",
    )
    assert "English letters" not in render_context(native)
