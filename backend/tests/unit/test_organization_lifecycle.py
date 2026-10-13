"""SS-02: one rule for "may this company use Mesiri right now?"."""

from __future__ import annotations

import datetime as dt

import pytest

from mesiri.domains.organizations import lifecycle as lc

NOW = dt.datetime(2026, 10, 13, 12, 0, tzinfo=dt.UTC)
LATER = NOW + dt.timedelta(days=3)
EARLIER = NOW - dt.timedelta(seconds=1)


@pytest.mark.parametrize(
    ("status", "ends", "expected"),
    [
        ("active", None, lc.ACTIVE),
        ("Active", None, lc.ACTIVE),  # pre-0463 spelling
        ("trial", LATER, lc.TRIAL),
        ("trial", None, lc.TRIAL),  # trial with no end date stays a trial
        ("trial", EARLIER, lc.EXPIRED),  # ended trial expires without a job
        ("trial", NOW, lc.EXPIRED),  # ends exactly now: no longer usable
        ("expired", None, lc.EXPIRED),
        ("suspended", None, lc.SUSPENDED),
        ("archived", None, lc.SUSPENDED),  # unknown fails closed
        (None, None, lc.SUSPENDED),
    ],
)
def test_effective_status(status, ends, expected):
    assert lc.effective_status(status, ends, NOW) == expected


@pytest.mark.parametrize(
    ("status", "ends", "operational"),
    [
        ("active", None, True),
        ("trial", LATER, True),
        ("trial", EARLIER, False),
        ("expired", None, False),
        ("suspended", None, False),
        ("whatever", None, False),
    ],
)
def test_is_operational(status, ends, operational):
    assert lc.is_operational(status, ends, NOW) is operational


def test_operational_sql_matches_the_python_rule():
    sql = lc.operational_sql("o")
    assert "lower(o.status) = 'active'" in sql
    assert "lower(o.status) = 'trial'" in sql
    assert "o.trial_ends_at > now()" in sql
    assert "o.trial_ends_at IS NULL" in sql


def test_operational_sql_without_alias():
    sql = lc.operational_sql("")
    assert "lower(status) = 'active'" in sql
    assert "o." not in sql


def test_trial_window():
    start, end = lc.trial_window(NOW, 7)
    assert start == NOW
    assert end == NOW + dt.timedelta(days=7)
    with pytest.raises(ValueError):
        lc.trial_window(NOW, 0)


@pytest.mark.parametrize(
    ("ends", "left"),
    [
        (None, None),
        (EARLIER, 0),
        (NOW, 0),
        (NOW + dt.timedelta(days=7), 7),
        (NOW + dt.timedelta(days=6, hours=1), 7),  # part of a day counts
        (NOW + dt.timedelta(hours=2), 1),
    ],
)
def test_trial_days_left(ends, left):
    assert lc.trial_days_left(ends, NOW) == left


def test_statuses_match_the_organization_enum():
    from mesiri.infrastructure.postgres.models.organization import OrganizationStatus

    assert {m.value for m in OrganizationStatus} == set(lc.STATUSES)
