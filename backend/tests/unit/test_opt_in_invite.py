"""WA-09: the opt-in invite's wording and how replies are read (no database)."""

from __future__ import annotations

import pytest

from mesiri.application.dpr.opt_in_invite import (
    STOP,
    STOP_ID,
    YES,
    YES_ID,
    Answered,
    invite_payload,
    parse_reply,
)
from mesiri.application.dpr.recipients import OPTED_IN, OPTED_OUT


@pytest.mark.parametrize(
    ("text", "tap", "expected"),
    [
        ("YES", None, YES),
        ("yes.", None, YES),
        (" Yes please ", None, YES),
        ("ok", None, YES),
        ("STOP", None, STOP),
        ("stop!", None, STOP),
        ("no", None, STOP),
        ("Unsubscribe", None, STOP),
        (None, YES_ID, YES),
        (None, STOP_ID, STOP),
        ("yes the slab is done", None, None),  # a sentence is not an answer
        ("hello", None, None),
        ("", None, None),
    ],
)
def test_replies(text, tap, expected) -> None:
    assert parse_reply(text, tap) == expected


def test_invite_payload() -> None:
    payload = invite_payload(phone="919876500301", company="Suresh Builders", project="Green Towers")
    assert payload["to_wa_id"] == "919876500301"
    assert payload["requires_opt_in"] is False
    assert payload["message"] == (
        "Suresh Builders would like to send you the daily progress report for Green Towers on "
        "WhatsApp. Reply YES to receive it, or STOP to never be messaged."
    )
    assert payload["buttons"] == [{"id": YES_ID, "title": "YES"}, {"id": STOP_ID, "title": "STOP"}]
    assert payload["template"] == {
        "name": "mesiri_dpr_optin",
        "body_params": ["Suresh Builders", "Green Towers"],
        "button_payloads": [YES_ID, STOP_ID],
    }


def test_answer_replies() -> None:
    assert Answered(OPTED_IN, ["Suresh Builders"]).reply() == (
        "Thanks. You'll get the daily progress report from Suresh Builders here."
    )
    assert Answered(OPTED_OUT, ["Alpha", "Beta"]).reply() == (
        "Done. Alpha and Beta won't message you here again. Reply YES if you change your mind."
    )
