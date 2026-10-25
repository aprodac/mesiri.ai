"""A question nobody answered is closed, not asked again (audit 05, live 24 Oct)."""

from __future__ import annotations

from runtime.agent.prompt import Turn
from runtime.agent.stale_questions import CLOSED, STALE_SECONDS, close_stale_questions

QUESTION = "How much is that in cum?\n[options: The amount in cubic meters / 2 / 3]"
NOW = 1_000_000.0


def test_an_earlier_question_is_closed_and_loses_its_options():
    turns = (Turn("40 bags sand", QUESTION, NOW - 60), Turn("20 bags cement came", "✅ Saved: Cement 20 bags", NOW - 30))
    first, second = close_stale_questions(turns, NOW)
    assert first.assistant_reply == "How much is that in cum?" + CLOSED
    assert "[options" not in first.assistant_reply
    assert second == turns[1]


def test_the_last_question_stays_open_while_it_is_recent():
    turns = (Turn("40 bags sand", QUESTION, NOW - 60),)
    assert close_stale_questions(turns, NOW) == turns


def test_the_last_question_goes_cold_after_a_quarter_of_an_hour():
    turns = (Turn("40 bags sand", QUESTION, NOW - STALE_SECONDS - 1),)
    (turn,) = close_stale_questions(turns, NOW)
    assert turn.assistant_reply.endswith(CLOSED)


def test_a_turn_without_a_time_or_a_question_is_left_alone():
    turns = (Turn("hi", "Hello! What are you reporting?", 0.0), Turn("ok", "Saved: 5 workers", 0.0))
    assert close_stale_questions(turns, NOW) == (Turn("hi", "Hello! What are you reporting?" + CLOSED, 0.0), turns[1])
