"""SS-15: /auth/me carries the company's trial status for the dashboard's
"trial ended, read-only" banner, and never fails the page over it."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

from auth import router as auth_router
from mesiri.infrastructure.postgres.repositories import organization_settings

_ORG = "11111111-1111-1111-1111-111111111111"


class _Result:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


class _Conn:
    def __init__(self, row):
        self._row = row

    async def execute(self, *_args, **_kwargs):
        return _Result(self._row)


class _Connect:
    def __init__(self, row):
        self._row = row

    async def __aenter__(self):
        return _Conn(self._row)

    async def __aexit__(self, *exc):
        return None


@pytest.fixture
def company(monkeypatch):
    state = SimpleNamespace(row=None, requests=[])

    class _Engine:
        def connect(self):
            return _Connect(state.row)

    class _Repo:
        def __init__(self, conn):
            pass

        async def get(self, organization_id, key):
            assert key == "continue_requests"
            return state.requests

    monkeypatch.setattr(auth_router, "get_engine", lambda: _Engine())
    monkeypatch.setattr(organization_settings, "PostgresOrganizationSettingsRepository", _Repo)
    return state


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


async def test_platform_admin_has_no_company() -> None:
    assert await auth_router._company_status_for("") is None


async def test_trial_in_progress_has_days_left(company) -> None:
    company.row = SimpleNamespace(
        status="trial", trial_ends_at=_now() + dt.timedelta(days=3, hours=1)
    )
    status = await auth_router._company_status_for(_ORG)
    assert status.status == "trial"
    assert status.trial_days_left in (3, 4)
    assert status.continue_requested is False


async def test_trial_past_its_end_reads_expired(company) -> None:
    company.row = SimpleNamespace(status="trial", trial_ends_at=_now() - dt.timedelta(hours=1))
    status = await auth_router._company_status_for(_ORG)
    assert status.status == "expired"
    assert status.trial_days_left is None


async def test_open_continue_request_is_reported(company) -> None:
    company.row = SimpleNamespace(status="trial", trial_ends_at=_now() - dt.timedelta(days=1))
    company.requests = [{"status": "done"}, {"status": "open", "via": "whatsapp"}]
    assert (await auth_router._company_status_for(_ORG)).continue_requested is True
    company.requests = [{"status": "done"}]
    assert (await auth_router._company_status_for(_ORG)).continue_requested is False


async def test_active_company(company) -> None:
    company.row = SimpleNamespace(status="active", trial_ends_at=None)
    status = await auth_router._company_status_for(_ORG)
    assert (status.status, status.trial_days_left) == ("active", None)


async def test_lookup_failure_shows_no_banner_instead_of_failing(monkeypatch) -> None:
    def broken_engine():
        raise RuntimeError("database down")

    monkeypatch.setattr(auth_router, "get_engine", broken_engine)
    assert await auth_router._company_status_for(_ORG) is None
