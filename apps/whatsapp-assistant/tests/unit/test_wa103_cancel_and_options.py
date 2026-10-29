"""[103]: "cancel that" during an open question drops it; a project name with a
comma stays one option."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from channel.replies import ReplySpec
from mesiri_contracts.assistant.enums import InputModality
from runtime.agent import toolbox as tb
from runtime.agent.entry_base import choose
from runtime.agent.left_it import LEFT_IT, is_drop_word, question_is_open
from runtime.agent.tools import ScopeLookup
from runtime.agent.turn import AgentTurnDeps, run_agent_turn


def _pack(reply, *, pending=False):
    turn = SimpleNamespace(user_text="x", assistant_reply=reply)
    return SimpleNamespace(recent_turns=(turn,), has_pending_confirmation=pending)


@pytest.mark.parametrize("text", ["cancel that", "Cancel", "venda", "Vendaa!", "never mind", "വേണ്ട"])
def test_drop_words(text):
    assert is_drop_word(text)


@pytest.mark.parametrize("text", ["cancel the cement entry", "yes", "", None, "venda 10 bags"])
def test_other_messages_are_not_drop_words(text):
    assert not is_drop_word(text)


def test_a_question_with_buttons_or_a_question_mark_is_open():
    assert question_is_open(_pack("Which project is Site B part of?\n[options: A / B]"))
    assert question_is_open(_pack("Which project is Site B part of?"))


def test_a_saved_card_or_a_statement_is_not_an_open_question():
    assert not question_is_open(_pack("📝 To save:\n• Cement 10 bags\n[options: ✅ Save / ❌ Cancel]"))
    assert not question_is_open(_pack("Okay, noted."))
    assert not question_is_open(SimpleNamespace(recent_turns=()))
    assert not question_is_open(None)


async def _turn(text, pack):
    sent = AsyncMock()
    ran = []

    async def run(**_kw):
        ran.append(1)
        raise AssertionError("the model must not run")

    deps = AgentTurnDeps(
        runner=SimpleNamespace(run=run),
        make_gateway=lambda m, lang: SimpleNamespace(handled=[], finish=AsyncMock()),
        send_spec=sent,
        transcribe=None,
        message_logger=AsyncMock(),
        memory_loader=SimpleNamespace(load=AsyncMock(return_value=pack)),
    )
    msg = SimpleNamespace(text=text, modality=InputModality.TEXT, correlation_id="c", sender=SimpleNamespace(wa_id="1"))
    actor = SimpleNamespace(user_id="u", full_name="A", role="S", org_name="O", projects=[], sites=[], organization_id="o")
    await run_agent_turn(msg, actor, deps)
    return sent, ran


async def test_cancel_that_with_a_question_open_says_left_it_and_skips_the_model():
    sent, ran = await _turn("cancel that", _pack("Which project is Site B part of?\n[options: A / B]"))
    assert not ran
    spec = sent.await_args.args[0]
    assert spec.text == LEFT_IT == "Okay, left it."


async def test_cancel_with_a_card_waiting_goes_to_the_model_as_before():
    with pytest.raises(AssertionError, match="model must not run"):
        await _turn("cancel that", _pack("📝 To save:\n• Cement"))


KNOWN = ["Green Villa, Kakkanad"]


def test_a_comma_name_split_by_the_model_is_put_back():
    assert tb.rejoin_names(["Green Villa", "Kakkanad", "Tower A"], KNOWN) == ["Green Villa, Kakkanad", "Tower A"]
    assert tb.rejoin_names(["Green Villa, Kakkanad", "Tower A"], KNOWN) == ["Green Villa, Kakkanad", "Tower A"]
    assert tb.rejoin_names(["Green Villa", "Tower A"], KNOWN) == ["Green Villa", "Tower A"]


async def test_ask_user_gives_one_button_for_a_comma_project():
    scope = ScopeLookup(projects=(("p1", "Green Villa, Kakkanad"), ("p2", "Tower A")))
    box = tb.AgentToolbox(SimpleNamespace(), scope, "text")
    await box.handle("ask_user", {"question": "Which project is Site B part of?", "options": ["Green Villa", "Kakkanad", "Tower A"], "other_parts": []})
    assert isinstance(box.parked, ReplySpec)
    # 21 characters: too long for a 20-character button, so a list (never a cut button)
    assert [r.title for r in box.parked.list_rows] == ["Green Villa, Kakkanad", "Tower A"]


def test_choose_lists_names_in_quotes_so_a_comma_is_not_a_separator():
    say = choose("Which project?", ["Green Villa, Kakkanad", "Tower A"], "project")
    assert '"Green Villa, Kakkanad" | "Tower A"' in say.text
    assert say.options == ("Green Villa, Kakkanad", "Tower A")
