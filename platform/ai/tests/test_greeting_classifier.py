"""mesiri_ai.greeting_classifier — deterministic greeting/menu detection.

Lives in mesiri_ai (not interactions/) specifically so understanding/ can use
it without violating the ingress -> understanding -> ... -> interactions
dependency direction. These tests pin the matching behavior directly, since
both understanding/pipeline.py and interactions/handler.py depend on it
staying deterministic.
"""

from __future__ import annotations

import pytest

from mesiri_ai.greeting_classifier import is_greeting_trigger


@pytest.mark.parametrize(
    "text",
    ["hi", "Hi", "HI", "hii", "hey", "hello", "menu", "help", "start", "namaskaram", "Hlo", "hy", "helo"],
)
def test_recognizes_configured_greeting_phrases_case_insensitively(text):
    assert is_greeting_trigger(text) is True


def test_recognizes_malayalam_greetings():
    assert is_greeting_trigger("ഹായ്") is True
    assert is_greeting_trigger("നമസ്കാരം") is True


def test_does_not_match_a_word_containing_a_phrase_as_a_substring():
    """Token matching, not substring matching, for single-word phrases --
    "hire" must not match "hi", mirroring classifier.py's "no in now" rule."""
    assert is_greeting_trigger("hire someone for the site") is False
    assert (
        is_greeting_trigger("start the equipment now") is False
    )  # "start" is a full token here though
    assert is_greeting_trigger("restart the pump") is False


def test_does_not_match_a_real_material_report():
    assert is_greeting_trigger("50 bags of cement arrived") is False
    assert (
        is_greeting_trigger("hi, 20 bags used for foundation") is False
    )  # real content alongside "hi"


@pytest.mark.parametrize("text", [None, "", "   "])
def test_empty_or_none_is_not_a_greeting(text):
    assert is_greeting_trigger(text) is False


@pytest.mark.parametrize("text", ["Hi!", "hello.", "  hey,  ", "menu?"])
def test_trailing_punctuation_is_tolerated(text):
    """Greetings get punctuated far more often than confirmation replies do,
    so unlike confirmation_phrases.json's classifier this needs to strip it."""
    assert is_greeting_trigger(text) is True


def test_multiple_greeting_words_together_still_counts():
    assert is_greeting_trigger("hi hello") is True
