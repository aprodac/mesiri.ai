"""SA-02: how a company row reads in the superadmin's list (no database)."""

from __future__ import annotations

import datetime as dt
import uuid

from mesiri.application.organizations.companies_overview import to_overview

_NOW = dt.datetime(2026, 10, 15, 12, 0, tzinfo=dt.UTC)


def _row(**overrides):
    row = {
        "id": uuid.uuid4(),
        "name": "Skyline Builders",
        "deployment_type": "SaaS",
        "db_route": "shared-cluster-01",
        "status": "trial",
        "trial_started_at": _NOW - dt.timedelta(days=2),
        "trial_ends_at": _NOW + dt.timedelta(days=5),
        "converted_at": None,
        "signup_source": "whatsapp",
        "created_at": _NOW - dt.timedelta(days=2),
        "updated_at": _NOW - dt.timedelta(days=2),
        "active_users": 1,
        "has_site": True,
        "first_update_at": None,
        "first_dpr_sent_at": None,
    }
    row.update(overrides)
    return row


def test_trial_shows_days_left() -> None:
    company = to_overview(_row(), _NOW)
    assert company.effective_status == "trial"
    assert company.trial_days_left == 5


def test_trial_past_its_end_reads_expired_with_no_days_left() -> None:
    company = to_overview(_row(trial_ends_at=_NOW - dt.timedelta(hours=1)), _NOW)
    assert company.status == "trial"  # stored value unchanged
    assert company.effective_status == "expired"
    assert company.trial_days_left is None


def test_active_and_old_capitalised_status() -> None:
    company = to_overview(_row(status="Active", trial_ends_at=None), _NOW)
    assert company.effective_status == "active"
    assert company.trial_days_left is None


def test_owner_alone_is_not_a_team() -> None:
    assert to_overview(_row(active_users=1), _NOW).setup.has_team is False
    assert to_overview(_row(active_users=2), _NOW).setup.has_team is True
    assert to_overview(_row(active_users=None), _NOW).setup.has_team is False


def test_setup_progress_is_carried_through() -> None:
    first = _NOW - dt.timedelta(days=1)
    company = to_overview(_row(has_site=False, first_update_at=first, first_dpr_sent_at=_NOW), _NOW)
    assert company.setup.has_site is False
    assert company.setup.first_update_at == first
    assert company.setup.first_dpr_sent_at == _NOW


def test_missing_signup_source_counts_as_superadmin() -> None:
    assert to_overview(_row(signup_source=None), _NOW).signup_source == "superadmin"
