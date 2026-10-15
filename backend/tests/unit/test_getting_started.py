"""SS-07: the two setup items the checklist added to the shared setup
progress (no database)."""

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
        "trial_started_at": _NOW,
        "trial_ends_at": _NOW + dt.timedelta(days=7),
        "converted_at": None,
        "signup_source": "web",
        "created_at": _NOW,
        "updated_at": _NOW,
        "active_users": 1,
        "has_site": True,
        "first_update_at": None,
        "first_dpr_sent_at": None,
        "has_logo": False,
        "report_time_set": False,
    }
    row.update(overrides)
    return row


def test_logo_and_report_time_are_carried_through() -> None:
    setup = to_overview(_row(has_logo=True, report_time_set=True), _NOW).setup
    assert (setup.has_logo, setup.report_time_set) == (True, True)


def test_rows_without_the_new_columns_read_as_not_done() -> None:
    row = _row()
    del row["has_logo"], row["report_time_set"]
    setup = to_overview(row, _NOW).setup
    assert (setup.has_logo, setup.report_time_set) == (False, False)
