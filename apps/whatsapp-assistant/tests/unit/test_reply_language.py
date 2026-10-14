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
    assert "await user_language_store.get(user_id=ctx.user_id)" in journey_source


def test_the_overview_has_an_example_and_no_module_list():
    from channel.replies import render_capability_answer

    text = render_capability_answer([]).text
    assert "“6 masons and 4 helpers" in text
    assert "money" not in text.lower()
