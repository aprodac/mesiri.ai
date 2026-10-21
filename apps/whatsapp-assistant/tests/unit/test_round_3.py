"""Fixes from the 21 Oct WhatsApp test, round 3 (docs/qa/runs/2026-10-21-round-3)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from channel.replies import render_module_disabled_reply
from runtime.agent import save_button
from runtime.agent.prompt import is_manglish, reply_letters_rule
from runtime.agent.runner import without_saved_claims
from runtime.site_day_review import day_lines


@pytest.mark.parametrize(
    ("text", "kept"),
    [
        # Test 1: the only sentence was "... vannu, save cheythu." and the whole
        # reply went, leaving the Save card with no words of the model's.
        ("50 bag cement vannu, save cheythu.", "50 bag cement vannu."),
        # Test 8: "noted" claimed the shortage was kept before the tap.
        ("I've noted the shortage. Tap Save to keep it.", "Tap Save to keep it."),
        ("Recorded.", ""),
        ("Not saved yet, tap Save.", "Not saved yet, tap Save."),
    ],
)
def test_only_the_claim_is_dropped_not_the_rest_of_the_sentence(text, kept):
    assert without_saved_claims(text) == kept


@pytest.mark.parametrize(
    ("message", "manglish"),
    [
        ("nale slab-inu cement mathiyo?", True),
        ("cement stock ethra und?", True),
        ("50 bag cement vannu", True),
        ("is there enough cement for tomorrow's slab?", False),
        ("Received 40 bags sand", False),
        ("500 kg steel aaya", False),
    ],
)
def test_manglish_is_told_apart_from_english(message, manglish):
    assert is_manglish(message) is manglish


def test_a_manglish_message_is_answered_in_manglish():
    rule = reply_letters_rule("nale slab-inu cement mathiyo?")
    assert "reply in Manglish" in rule and "Not English" in rule
    assert "Manglish" not in reply_letters_rule("how much sand is left?").split(":")[0]


def test_cancel_after_save_is_one_plain_sentence():
    settled = SimpleNamespace(done=0, already=0, refused=["it was already saved; fix it on the dashboard"])
    assert save_button.tap_reply(save_button.CANCEL, settled) == (
        "That one is already saved, so it can't be cancelled here. To change it, edit it on the dashboard."
    )


def test_an_admin_is_not_told_to_ask_their_admin():
    assert render_module_disabled_reply("finance", "ADMIN").endswith("Ask the Mesiri team to turn them on.")
    assert render_module_disabled_reply("finance", "SITE_ENGINEER").endswith("Ask your admin to turn them on.")


def test_the_day_so_far_names_the_materials():
    payload = {"materials": [{"material_name": "Cement"}, {"material_name": "M sand"}]}
    assert day_lines(payload) == ["• Materials: Cement, M sand"]
