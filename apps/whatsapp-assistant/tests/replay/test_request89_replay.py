"""Request 89: the [88] re-test messages (22 Oct) through the real journey, with
the model scripted the way the live one answered (flat "Okay.", Manglish for an
English message). The model is also wrong when asked again (the fake replays its
script), so what is checked is the code's own floor: the reply's language and a
natural line naming the card's items, never a flat "Okay."."""

from __future__ import annotations

import pytest
from tests.replay.test_agent_replay import world  # noqa: F401,F811  (fixture)

from mesiri_ai.fakes import FakeToolCallingProvider
from runtime.agent.prompt import reply_language
from runtime.agent.reply_text import manglish_word_count
from runtime.agent.runner import _MANGLISH_WORDS

CASES = [
    # (message, expected language, tool call, the live model's flat/wrong words, words the card line must hold)
    (
        "used 10 bags cement for columns",
        "english",
        ("save_material_usage", {"material": "cement", "quantity": 10, "unit": "bags", "purpose": "columns"}),
        "Okay. Nokki shariyenkil Save tap cheyyu.",
        ["10"],
    ),
    (
        "crane breakdown, work stopped since morning",
        "english",
        ("report_issue", {"issue_type": "EQUIPMENT", "narrative": "crane breakdown, work stopped since morning"}),
        "Okay. Shariyenkil Save tap cheyyu.",
        ["crane"],
    ),
    (
        "ground floor flooring theernnu",
        "manglish",
        ("save_work_done", {"narrative": "ground floor flooring theernnu", "work_type": "flooring", "location": "ground floor"}),
        "Okay.",
        ["flooring"],
    ),
]


@pytest.mark.parametrize("message, language, call, live_words, card_words", CASES)
async def test_the_retest_messages_get_the_right_language_and_a_natural_line(world, message, language, call, live_words, card_words):  # noqa: F811
    assert reply_language(message) == language
    result = await world.say(FakeToolCallingProvider([[call], live_words]), message)
    assert result.outcome == "ok", result.reply
    text = result.reply.text
    first = text.split("\n")[0]
    assert first.casefold() not in {"okay.", "ok."}, text
    assert any(w in text.casefold() for w in card_words), text
    assert "Save" in first
    manglish = manglish_word_count(first, _MANGLISH_WORDS)
    assert (manglish > 0) == (language == "manglish"), text
