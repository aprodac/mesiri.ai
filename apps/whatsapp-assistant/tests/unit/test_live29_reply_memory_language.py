"""Live 29 Oct (WhatsApp screenshots): a swipe-reply was never understood, the
model forgot what it had just said, an issue from an earlier day was answered as
today's, and the sender could not set the language every reply is in."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from channel.whatsapp import sent_text
from ingress.normalization import MessageNormalizer
from mesiri.infrastructure.redis.client import FakeRedis
from mesiri_ai.fakes import FakeToolCallingProvider
from mesiri_contracts.assistant.enums import InputModality
from mesiri_contracts.assistant.normalized_message import (
    NormalizedMessage,
    ReplyContext,
    SenderInfo,
)
from runtime.agent import history, wording
from runtime.agent import runner as r
from runtime.agent.gateway import StepResult
from runtime.agent.prompt import (
    AgentContext,
    build_messages,
    preferred_language,
    reply_language,
    reply_letters_rule,
)
from runtime.agent.tools import SET_REPLY_LANGUAGE, ScopeLookup, tool_specs
from runtime.agent.turn import AgentTurnDeps, run_agent_turn
from runtime.reply_language import UserLanguageStore
from workflows.activity_query.nodes import generate_activity_search_reply

CTX = AgentContext(user_name="Anil", role="SUPERVISOR", company="Acme", now=datetime(2026, 10, 29, 13, 30))
SITE_LOG = "No work saved today. Materials: 10 bags cement in. 2 issues: rain stopped work, cement stock?"


@pytest.fixture
def store(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(sent_text, "_store", redis)
    return redis


# -- 1. a swipe-reply is seen ---------------------------------------------------------------------


def _inbound(**extra):
    return {"from": "919000000001", "id": "wamid.in", "timestamp": "1761725000", **extra}


def test_a_swipe_reply_reads_metas_context_id():
    message = _inbound(type="text", text={"body": "What is this message then?"}, context={"from": "1555", "id": "wamid.bot"})
    normalized = MessageNormalizer().normalize(message, contacts=[], phone_number_id="p", display_phone_number="d")
    assert normalized.reply_context is not None
    assert normalized.reply_context.replied_to_message_id == "wamid.bot"


def test_a_button_tap_is_not_read_as_a_swipe_reply():
    message = _inbound(
        type="interactive",
        interactive={"type": "button_reply", "button_reply": {"id": "save", "title": "Save"}},
        context={"from": "1555", "id": "wamid.card"},
    )
    normalized = MessageNormalizer().normalize(message, contacts=[], phone_number_id="p", display_phone_number="d")
    assert normalized.reply_context is None


def test_a_forward_is_still_not_a_reply():
    message = _inbound(type="text", text={"body": "fwd"}, context={"forwarded": True})
    normalized = MessageNormalizer().normalize(message, contacts=[], phone_number_id="p", display_phone_number="d")
    assert normalized.reply_context is None and normalized.metadata.get("forwarded") is True


def test_the_words_of_each_kind_of_sent_message():
    assert sent_text.text_of_fields({"type": "text", "text": {"body": "hi"}}) == "hi"
    interactive = {"type": "interactive", "interactive": {"header": {"text": "Stock"}, "body": {"text": "Cement 86 bags"}}}
    assert sent_text.text_of_fields(interactive) == "Stock\nCement 86 bags"
    assert sent_text.text_of_fields({"type": "image", "image": {"caption": "Saved"}}) == "Saved"
    assert sent_text.text_of_fields({"type": "template", "template": {"name": "x"}}) == ""


async def test_what_mesiri_sent_is_read_back_by_its_id(store):
    sent_text.report_sent(wamid="wamid.bot", message_fields={"type": "text", "text": {"body": SITE_LOG}})
    await sent_text.remember(wamid="wamid.mine", text="10 bag cement vannu", by="sender")
    await asyncio.sleep(0)
    assert await sent_text.text_of("wamid.bot") == (SITE_LOG, "mesiri")
    assert await sent_text.text_of("wamid.mine") == ("10 bag cement vannu", "sender")
    assert await sent_text.text_of("wamid.unknown") is None


async def test_no_store_keeps_nothing_and_never_raises(monkeypatch):
    monkeypatch.setattr(sent_text, "_store", None)
    sent_text.report_sent(wamid="w", message_fields={"type": "text", "text": {"body": "x"}})
    await sent_text.remember(wamid="w", text="x")
    assert await sent_text.text_of("w") is None


def test_the_model_is_shown_the_quoted_message_before_theirs():
    ctx = replace(CTX, replying_to=(SITE_LOG, "mesiri"))
    last = build_messages(ctx, "What is this message then ????")[-1][1]
    assert 'They are replying to your earlier message: "' + SITE_LOG in last
    assert last.index("They are replying") < last.index("User message:")
    # The language is still decided from their own words, never the quote.
    assert "This message is English" in last


def _message(text, *, quoted=None):
    return NormalizedMessage(
        message_id="wamid.in",
        sender=SenderInfo(wa_id="919000000001", profile_name="A"),
        timestamp=datetime(2026, 10, 29, 8, 0),
        modality=InputModality.TEXT,
        text=text,
        reply_context=ReplyContext(replied_to_message_id=quoted) if quoted else None,
    )


def _deps(seen, *, language_store=None):
    async def run(**kw):
        seen.append(kw)
        return r.AgentResult("degraded", r.ReplySpec(text="ok"), SimpleNamespace(parked=None, saved=[]))

    return AgentTurnDeps(
        runner=SimpleNamespace(run=run),
        make_gateway=lambda m, lang: SimpleNamespace(handled=[], finish=AsyncMock()),
        send_spec=AsyncMock(),
        transcribe=None,
        message_logger=AsyncMock(),
        user_language_store=language_store,
    )


_ACTOR = SimpleNamespace(user_id="u", full_name="A", role="S", org_name="O", projects=[], sites=[], organization_id="o")


async def test_a_turn_passes_the_quoted_words_and_keeps_its_own(store):
    await sent_text.remember(wamid="wamid.bot", text=SITE_LOG)
    seen: list = []
    await run_agent_turn(_message("What is this message then?", quoted="wamid.bot"), _ACTOR, _deps(seen))
    assert seen[0]["ctx"].replying_to == (SITE_LOG, "mesiri")
    assert seen[0]["user_text"] == "What is this message then?"
    # A later swipe-reply to THIS message can be read too.
    assert await sent_text.text_of("wamid.in") == ("What is this message then?", "sender")


async def test_a_quote_that_is_not_known_is_a_plain_message(store):
    seen: list = []
    await run_agent_turn(_message("ithu entha?", quoted="wamid.old"), _ACTOR, _deps(seen))
    assert seen[0]["ctx"].replying_to is None


# -- 2. the model remembers what it said --------------------------------------------------------


def test_the_gist_keeps_every_plain_sentence_not_only_the_first():
    # The last sentence ends on "?", so only it goes (a question is never carried).
    assert history.gist(SITE_LOG) == "No work saved today. Materials: 10 bags cement in."
    shown = history.gist("ഇന്ന് ജോലികളൊന്നും രേഖപ്പെടുത്തിയിട്ടില്ല.\nമെറ്റീരിയൽ: 10 ചാക്ക് സിമൻ്റ് വന്നു.\n• card line")
    assert "10 ചാക്ക്" in shown and "card line" not in shown


def test_the_gist_still_drops_questions_cards_and_options():
    assert history.gist("Ethra kg aanu?\n[options: 2 / Other]") == ""
    assert history.gist("Sheri, 6 mason vannu.\n📝 To save: 6 mason\n[options: Save / Cancel]") == "Sheri, 6 mason vannu."
    assert history.gist("Cement 10 bags vannu. Ethra use cheythu?") == "Cement 10 bags vannu."
    assert len(history.gist("word " * 300)) <= history.GIST_MAX


def test_the_model_is_told_never_to_deny_its_own_messages():
    assert "Never say you did not send a message" in r.SYSTEM_PROMPT


# -- 3. an issue from an earlier day is not today's ----------------------------------------------


def test_an_issue_open_since_an_earlier_day_says_so_in_todays_log():
    results = {
        "date_range_label": "today",
        "activities": [],
        "open_issues": [
            {"issue_type": "WEATHER", "narrative": "rain stopped work", "carried_over": True, "since": "24 Oct"},
            {"issue_type": "OTHER", "narrative": "crane down", "carried_over": False},
        ],
    }
    text = generate_activity_search_reply({"collected_fields": {"activity_search_results": results}})["pending_prompt"]
    assert "rain stopped work (open since 24 Oct)" in text
    assert "crane down" in text and "crane down (" not in text


# -- 4. the reply language the sender sets ------------------------------------------------------


def test_a_set_language_wins_over_the_messages_own():
    token = preferred_language.set("malayalam")
    try:
        assert reply_language("innu 10 bag cement vannu") == "malayalam"
        assert "set their reply language to Malayalam" in reply_letters_rule("innu 10 bag cement vannu")
        assert wording.language_of("ok") == "malayalam"
        assert r.script_problems("Sheri, 10 bag cement vannu ennu save cheyyam", "10 bag cement vannu")
        assert not r.script_problems("ശരി, 10 ചാക്ക് സിമൻ്റ് വന്നു", "10 bag cement vannu")
    finally:
        preferred_language.reset(token)
    assert reply_language("innu 10 bag cement vannu") == "manglish"  # unset: the message decides again


async def test_the_preference_is_kept_and_shapes_the_profile():
    store = UserLanguageStore(FakeRedis())
    await store.remember(user_id="u", detected_language="english", text="hello there")
    assert await store.get_profile(user_id="u") == (None, "native")
    assert await store.set_preference(user_id="u", preference="malayalam")
    assert await store.get_preference(user_id="u") == "malayalam"
    assert await store.get_profile(user_id="u") == ("Malayalam", "native")
    await store.set_preference(user_id="u", preference="manglish")
    assert await store.get_profile(user_id="u") == ("Malayalam", "latin")
    await store.set_preference(user_id="u", preference=None)
    assert await store.get_preference(user_id="u") is None
    assert await store.get_profile(user_id="u") == (None, "native")


def test_the_tool_is_offered():
    spec = next(s for s in tool_specs() if s.name == SET_REPLY_LANGUAGE)
    assert spec.parameters["required"] == ["language"]
    assert "auto" in spec.parameters["properties"]["language"]["enum"]


class _Gateway:
    async def finish(self):
        return None

    async def run(self, candidate, *, text):
        return StepResult("saved", text="ok")


async def _set(language, setter):
    provider = FakeToolCallingProvider([[("set_reply_language", {"language": language})], "ശരി, ഇനി മലയാളത്തിൽ മറുപടി തരാം."])
    token = preferred_language.set(None)
    try:
        result = await r.AgentRunner(provider).run(
            ctx=CTX,
            user_text="njan manglish type cheyyum, reply malayalathil mathi",
            gateway=_Gateway(),
            scope=ScopeLookup(),
            reply_language_setter=setter,
        )
        return result, preferred_language.get()
    finally:
        preferred_language.reset(token)


async def test_setting_the_language_keeps_it_and_this_reply_follows_it():
    kept = []

    async def setter(value):
        kept.append(value)
        return True

    result, now = await _set("malayalam", setter)
    assert kept == ["malayalam"] and now == "malayalam"
    assert result.outcome == "ok" and "മലയാള" in result.reply.text
    assert result.toolbox.saved == [] and result.toolbox.attempted_writes == 0


async def test_auto_clears_it_and_no_store_refuses_it():
    kept = []

    async def setter(value):
        kept.append(value)
        return True

    _result, now = await _set("auto", setter)
    assert kept == [None] and now is None
    result, now = await _set("malayalam", None)
    assert now is None
    outcome = next(c.outcome.content for c in result.run.calls if c.name == SET_REPLY_LANGUAGE)
    assert outcome["status"] == "not_saved"


async def test_a_turn_loads_the_set_language_and_resets_it_after():
    store = UserLanguageStore(FakeRedis())
    await store.set_preference(user_id="u", preference="malayalam")
    seen: list = []

    async def run(**kw):
        seen.append((kw, preferred_language.get()))
        return r.AgentResult("degraded", r.ReplySpec(text="ok"), SimpleNamespace(parked=None, saved=[]))

    deps = _deps([], language_store=store)
    deps.runner = SimpleNamespace(run=run)
    await run_agent_turn(_message("10 bag cement vannu"), _ACTOR, deps)
    kw, during = seen[0]
    assert during == "malayalam" and kw["ctx"].last_language == "Malayalam"
    assert callable(kw["reply_language_setter"])
    assert preferred_language.get() is None


# -- 5. what Mesiri sent on its own, the ack's language, a longer memory ------------------------


async def test_the_last_message_sent_is_kept_per_recipient(store):
    sent_text.report_sent(
        wamid="w1", message_fields={"type": "text", "text": {"body": "Evening: send today's update?"}}, recipient="9190"
    )
    await asyncio.sleep(0)
    text, at = await sent_text.last_sent_to("9190")
    assert text == "Evening: send today's update?" and at > 0
    assert await sent_text.last_sent_to("other") is None


async def test_a_reminder_sent_after_the_last_reply_is_shown_to_the_model(store):
    import time

    from runtime.agent.turn import _last_system_message

    now = time.time()
    await store.set_json("last_sent:919000000001", {"text": "Add another site?", "at": now - 60})
    message = _message("yes")
    message = message.model_copy(update={"timestamp": datetime.fromtimestamp(now, tz=UTC)})
    pack = SimpleNamespace(recent_turns=(SimpleNamespace(assistant_reply="Sheri, saved.", at=now - 600),))
    note = await _last_system_message(message, pack, _deps([]))
    assert note is not None and '"Add another site?"' in note
    # Already the last reply in the conversation: nothing added.
    same = SimpleNamespace(recent_turns=(SimpleNamespace(assistant_reply="Add another site?", at=now - 30),))
    assert await _last_system_message(message, same, _deps([])) is None
    # Sent after their message came in: not what it answers.
    await store.set_json("last_sent:919000000001", {"text": "🎤 listening", "at": now + 1})
    assert await _last_system_message(message, pack, _deps([])) is None


def test_the_conversation_is_remembered_for_two_hours():
    from memory.requirements import RECENT_TURNS

    assert RECENT_TURNS.ttl_seconds == 2 * 60 * 60
