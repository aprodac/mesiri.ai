"""SS-19: "Hide for now" on the getting-started card is kept for the company,
until a time, instead of in one browser."""

from __future__ import annotations

import datetime as dt

from mesiri.domains.organizations import settings as org_settings
from mesiri.domains.organizations.setup_router import HIDE_FOR, hidden_until

NOW = dt.datetime(2026, 10, 25, 12, 0, tzinfo=dt.UTC)


def test_hidden_until_a_future_time() -> None:
    until = NOW + HIDE_FOR
    assert hidden_until({"hidden_until": until.isoformat()}, NOW) == until


def test_comes_back_once_the_time_has_passed() -> None:
    assert hidden_until({"hidden_until": (NOW - dt.timedelta(minutes=1)).isoformat()}, NOW) is None


def test_showing_when_never_hidden_or_unreadable() -> None:
    assert hidden_until({}, NOW) is None
    assert hidden_until({"hidden_until": None}, NOW) is None
    assert hidden_until({"hidden_until": "soon"}, NOW) is None
    assert hidden_until(None, NOW) is None


def test_a_time_without_zone_is_read_as_utc() -> None:
    assert hidden_until({"hidden_until": "2026-10-26T12:00:00"}, NOW) == dt.datetime(
        2026, 10, 26, 12, 0, tzinfo=dt.UTC
    )


def test_the_generic_settings_api_cannot_write_it() -> None:
    assert org_settings.is_known_key(org_settings.GETTING_STARTED)
    assert org_settings.GETTING_STARTED in org_settings.DEDICATED_ENDPOINT_KEYS
    assert org_settings.default_for(org_settings.GETTING_STARTED) == {}
