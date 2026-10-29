"""WA-83 (plan of 27 Oct, phase 4): one way in for "help" and the menu.

Live 27 Oct (docs/qa/runs/2026-10-27-whatsapp-live-tests, screenshot 19): a bare
"help" got the old category menu, with Money and Reminders that the company has
switched off; "asdfgh" got "I couldn't understand that" with nothing to copy.
"""

from __future__ import annotations

import pytest

from channel.replies import render_greeting_menu
from runtime.agent.turn import _NOT_UNDERSTOOD
from workflows import registry


@pytest.fixture
def modules():
    def set_(names):  # noqa: ANN001, ANN202
        registry.set_enabled_modules(names)

    yield set_
    registry.set_enabled_modules(None)


def test_the_menu_follows_the_companys_modules(modules):
    modules(["dpr", "labour", "materials"])
    titles = [r.title for r in render_greeting_menu().list_rows]
    assert "Money" not in titles
    assert not [t for t in titles if "Reminder" in t]


def test_with_every_module_on_the_menu_is_unchanged(modules):
    modules(None)
    assert [r.id for r in render_greeting_menu().list_rows] == [c.row_id for c in registry.iter_menu_categories()]
    assert "Money" in [r.title for r in render_greeting_menu().list_rows]


@pytest.mark.parametrize(
    "text, hit",
    [
        ("I couldn't understand that. Please tell me what you want to do.", True),
        ("Sorry, I didn't understand.", True),
        ("Enikku manassilaayilla, onnu koodi parayamo?", True),
        ("എനിക്ക് മനസ്സിലായില്ല", True),
        ("Innu 7 per vannu.", False),
        ("I understand: 4 mason on the card.", False),
    ],
)
def test_a_reply_that_did_not_understand(text, hit):
    assert bool(_NOT_UNDERSTOOD.search(text)) is hit
