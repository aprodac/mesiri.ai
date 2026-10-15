"""SS-08: trial reminder rules, continue requests and the read-only guard (no database)."""

from __future__ import annotations

import datetime as dt

import pytest

from mesiri.domains.organizations import settings as org_settings
from mesiri.domains.organizations import trial_notices as notices
from mesiri.domains.shared.trial_guard import is_guarded

NOW = dt.datetime(2026, 10, 20, 6, 0, tzinfo=dt.UTC)


@pytest.mark.parametrize(
    ("ends_in", "expected"),
    [
        (dt.timedelta(days=3), None),
        (dt.timedelta(days=1, hours=12), notices.ENDING_SOON),
        (dt.timedelta(days=2), notices.ENDING_SOON),
        (dt.timedelta(hours=20), notices.LAST_DAY),
        (dt.timedelta(hours=-1), None),  # already over
    ],
)
def test_which_reminder_is_due(ends_in, expected) -> None:
    assert notices.reminder_due(NOW + ends_in, NOW) == expected


def test_no_reminder_without_an_end_date() -> None:
    assert notices.reminder_due(None, NOW) is None


def test_end_day_is_in_local_time() -> None:
    # 20:00 UTC on the 21st is the 22nd in India.
    ends = dt.datetime(2026, 10, 21, 20, 0, tzinfo=dt.UTC)
    assert notices.end_day_label(ends, "Asia/Kolkata") == "22 Oct"
    assert notices.end_day_label(ends, "not/a-zone") == "22 Oct"


def test_reminder_texts() -> None:
    soon = notices.reminder_message(
        notices.ENDING_SOON, company="Suresh Builders", end_day="22 Oct", reports_sent=5
    )
    assert "ends on *22 Oct*" in soon and "*5 daily reports*" in soon and "CONTINUE" in soon
    last = notices.reminder_message(
        notices.LAST_DAY, company="Suresh Builders", end_day="22 Oct", reports_sent=0
    )
    assert last.startswith("⏳ Last reminder") and "ends on *22 Oct*" in last
    assert "So far" not in last


@pytest.mark.parametrize("text", ["CONTINUE", "continue", " *Continue* ", "Continue with Mesiri"])
def test_continue_words(text) -> None:
    assert notices.is_continue(text)


@pytest.mark.parametrize("text", ["continue the slab work", "", None, "no"])
def test_not_continue(text) -> None:
    assert not notices.is_continue(text)


def test_one_open_continue_request_at_a_time() -> None:
    requests, added = notices.add_continue_request([], user_id="u", via="whatsapp", now=NOW)
    assert added and requests[0]["status"] == notices.OPEN
    requests, added = notices.add_continue_request(requests, user_id="u", via="dashboard", now=NOW)
    assert not added and len(requests) == 1


def test_continue_requests_are_refused_by_the_generic_settings_api() -> None:
    with pytest.raises(ValueError, match="own page"):
        org_settings.validate(org_settings.CONTINUE_REQUESTS, [])


@pytest.mark.parametrize(
    ("method", "path", "guarded"),
    [
        ("GET", "/projects", False),
        ("POST", "/projects", True),
        ("DELETE", "/dpr/projects/x/recipients/y", True),
        ("POST", "/auth/login", False),
        ("POST", "/auth/code/verify", False),
        ("POST", "/webhook", False),
        ("POST", "/company/trial/continue", False),
        ("POST", "/company/trialx", True),
    ],
)
def test_which_requests_the_guard_looks_at(method, path, guarded) -> None:
    assert is_guarded(method, path) is guarded
