"""SS-10: the rules of the superadmin's trial controls (no database)."""

from __future__ import annotations

import datetime as dt

import pytest

from mesiri.application.organizations.trial_controls import (
    CONVERT,
    EXTEND,
    REACTIVATE,
    SUSPEND,
    PlanState,
    TrialControlError,
    plan_change,
)

_NOW = dt.datetime(2026, 10, 15, 12, 0, tzinfo=dt.UTC)
_DAY = dt.timedelta(days=1)


def _trial(ends_in_days: float = 3, **overrides) -> PlanState:
    fields = {
        "status": "trial",
        "trial_started_at": _NOW - 4 * _DAY,
        "trial_ends_at": _NOW + ends_in_days * _DAY,
        "converted_at": None,
    }
    fields.update(overrides)
    return PlanState(**fields)


def _active(**overrides) -> PlanState:
    fields = {
        "status": "active",
        "trial_started_at": None,
        "trial_ends_at": None,
        "converted_at": None,
    }
    fields.update(overrides)
    return PlanState(**fields)


def test_extend_a_running_trial_adds_to_its_end() -> None:
    after, summary = plan_change(EXTEND, _trial(3), _NOW, days=7)
    assert after.status == "trial"
    assert after.trial_ends_at == _NOW + 10 * _DAY
    assert after.trial_started_at == _NOW - 4 * _DAY
    assert summary == "Trial extended by 7 days"


def test_extend_an_ended_trial_counts_from_now() -> None:
    # Stored as trial but past its end, or already marked expired: both work.
    for current in (_trial(-2), _trial(-2, status="expired")):
        after, _ = plan_change(EXTEND, current, _NOW, days=5)
        assert after.status == "trial"
        assert after.trial_ends_at == _NOW + 5 * _DAY


def test_extend_by_one_day_reads_singular() -> None:
    assert plan_change(EXTEND, _trial(), _NOW, days=1)[1] == "Trial extended by 1 day"


def test_convert_keeps_trial_dates_and_stamps_converted_at() -> None:
    current = _trial(-1)
    after, summary = plan_change(CONVERT, current, _NOW)
    assert after.status == "active"
    assert after.converted_at == _NOW
    assert after.trial_ends_at == current.trial_ends_at
    assert summary == "Converted to paid"


def test_suspend_from_any_live_status() -> None:
    for current in (_trial(), _trial(-1), _active()):
        assert plan_change(SUSPEND, current, _NOW)[0].status == "suspended"


@pytest.mark.parametrize(
    ("current", "expected"),
    [
        (_active(status="suspended"), "active"),  # never on a trial
        (_trial(status="suspended", converted_at=_NOW - _DAY), "active"),  # converted earlier
        (_trial(3, status="suspended"), "trial"),  # back to its running trial
        (_trial(-3, status="suspended"), "trial"),  # ...which reads expired at once
    ],
)
def test_reactivate_returns_to_where_it_was(current, expected) -> None:
    after, summary = plan_change(REACTIVATE, current, _NOW)
    assert after.status == expected
    assert summary == f"Reactivated as {expected}"


@pytest.mark.parametrize(
    ("action", "current", "message"),
    [
        (EXTEND, _active(), "Only a trial can be extended; this company is active"),
        (EXTEND, _trial(status="suspended"), "this company is suspended"),
        (CONVERT, _active(), "already active"),
        (CONVERT, _trial(status="suspended"), "reactivate it first"),
        (SUSPEND, _active(status="suspended"), "already suspended"),
        (REACTIVATE, _trial(), "this one is trial"),
        (REACTIVATE, _trial(-1), "this one is expired"),
    ],
)
def test_actions_that_dont_fit_the_status_are_refused(action, current, message) -> None:
    with pytest.raises(TrialControlError, match=message) as exc:
        plan_change(action, current, _NOW, days=7)
    assert exc.value.status_code == 409


@pytest.mark.parametrize("days", [0, 91, -1, None, True, 2.5])
def test_extend_needs_1_to_90_days(days) -> None:
    with pytest.raises(TrialControlError, match="from 1 to 90") as exc:
        plan_change(EXTEND, _trial(), _NOW, days=days)
    assert exc.value.status_code == 400


def test_unknown_action_is_a_bad_request() -> None:
    with pytest.raises(TrialControlError) as exc:
        plan_change("delete", _trial(), _NOW)
    assert exc.value.status_code == 400
