"""Fix 2 (live sweep 7 Nov: "Site B-il innu ethra mason?" at 00:05 asked about the new calendar day, so the masons
saved minutes earlier were "not recorded"): before the company's working day starts, "today" is the day that just
ended. Borrowed from site-diary practice: the report belongs to the shift's date.
"""

from __future__ import annotations

import datetime as dt

import pytest

from mesiri.domains.organizations import settings


def _at(hour: int, minute: int = 0) -> dt.datetime:
    return dt.datetime(2026, 11, 8, hour, minute)


def test_just_after_midnight_is_still_the_day_that_ended() -> None:
    assert settings.working_day(_at(0, 5)) == dt.date(2026, 11, 7)
    assert settings.working_day(_at(3, 59)) == dt.date(2026, 11, 7)


def test_from_the_days_start_it_is_the_new_day() -> None:
    assert settings.working_day(_at(4, 0)) == dt.date(2026, 11, 8)
    assert settings.working_day(_at(23, 30)) == dt.date(2026, 11, 8)  # a late-evening update stays on its day


def test_a_company_sets_its_own_start() -> None:
    assert settings.working_day(_at(5, 30), "06:00") == dt.date(2026, 11, 7)
    assert settings.working_day(_at(0, 30), "00:00") == dt.date(2026, 11, 8)  # calendar days, if they want


def test_the_setting_is_validated_and_a_bad_stored_value_falls_back() -> None:
    assert settings.default_for(settings.WORKING_DAY_STARTS_AT) == "04:00"
    assert settings.validate(settings.WORKING_DAY_STARTS_AT, "5:30") == "05:30"
    for bad in ("13:00", "noon", "25:00"):
        with pytest.raises(ValueError):
            settings.validate(settings.WORKING_DAY_STARTS_AT, bad)
    assert settings.working_day(_at(1), "garbage") == dt.date(2026, 11, 7)  # the default, never a crash
