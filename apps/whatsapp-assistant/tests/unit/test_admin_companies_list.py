"""SA-02: the control panel's companies list returns status and setup
progress from the one shared read (application/organizations/companies_overview)."""

from __future__ import annotations

import datetime as dt
import uuid

from admin import router as admin_router
from mesiri.application.organizations.companies_overview import CompanyOverview, SetupProgress

_NOW = dt.datetime(2026, 10, 15, 12, 0, tzinfo=dt.UTC)


class _Connect:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb):
        return None


class _Engine:
    def connect(self):
        return _Connect()


async def test_list_returns_status_and_setup(monkeypatch) -> None:
    company = CompanyOverview(
        id=uuid.uuid4(),
        name="Skyline Builders",
        deployment_type="SaaS",
        db_route="shared-cluster-01",
        status="trial",
        effective_status="trial",
        trial_started_at=_NOW,
        trial_ends_at=_NOW + dt.timedelta(days=7),
        trial_days_left=7,
        converted_at=None,
        signup_source="whatsapp",
        created_at=_NOW,
        updated_at=_NOW,
        setup=SetupProgress(
            has_team=True, has_site=True, first_update_at=_NOW, first_dpr_sent_at=None
        ),
    )

    async def fake_list(conn):
        return [company]

    monkeypatch.setattr(admin_router, "get_engine", lambda: _Engine())
    monkeypatch.setattr(admin_router, "list_companies", fake_list)

    [item] = await admin_router.list_organizations({})

    body = item.model_dump()
    # The old fields are still there for older callers (Test Message page).
    assert body["id"] == company.id
    assert body["name"] == "Skyline Builders"
    assert body["deployment_type"] == "SaaS"
    assert body["effective_status"] == "trial"
    assert body["trial_days_left"] == 7
    assert body["signup_source"] == "whatsapp"
    assert body["setup"] == {
        "has_team": True,
        "has_site": True,
        "first_update_at": _NOW,
        "first_dpr_sent_at": None,
    }
