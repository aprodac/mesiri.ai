"""Shared set-up for the v3 assistant tests.

WA-207 (5 Nov 2026): a person who chose no reply language gets Manglish. The tests written before that check how a
reply follows the language of each message, which is exactly what a person who chose "auto" gets ("reply in my
language again"). So by default every test here runs as that person; a test of the default itself is marked
``@pytest.mark.default_language`` and sees the real default.
"""

from __future__ import annotations

import pytest

from agent_api import whatsapp as wa


@pytest.fixture(autouse=True)
def _follow_each_message_unless_marked(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    if request.node.get_closest_marker("default_language") is None:
        monkeypatch.setattr(wa, "DEFAULT_REPLY_LANGUAGE", None)
