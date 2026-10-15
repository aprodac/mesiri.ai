"""SS-10: the control panel's trial-control and platform-settings routes map
outcomes to HTTP and keep WhatsApp's copy of the company current."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from fastapi import HTTPException

from admin import platform_settings_router
from admin import router as admin_router
from mesiri.application.organizations import trial_controls
from mesiri.application.organizations.trial_controls import PlanState, TrialControlError

_NOW = dt.datetime.now(dt.UTC)


class _Ctx:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb):
        return None


class _Engine:
    def begin(self):
        return _Ctx()

    def connect(self):
        return _Ctx()


@pytest.fixture
def wired(monkeypatch):
    calls: dict[str, list] = {"actions": [], "projected": []}
    result: dict[str, object] = {}

    async def fake_apply(conn, org_id, action, *, actor, days=None, reason=None):
        calls["actions"].append((org_id, action, days, reason, actor.label))
        if isinstance(result.get("value"), Exception):
            raise result["value"]
        return result["value"]

    async def fake_project(entity_type, entity_id):
        calls["projected"].append((entity_type, entity_id))

    monkeypatch.setattr(admin_router, "get_engine", lambda: _Engine())
    monkeypatch.setattr(trial_controls, "apply_trial_action", fake_apply)
    monkeypatch.setattr(admin_router, "project_entity", fake_project)
    return calls, result


async def test_extend_passes_days_and_reprojects(wired) -> None:
    calls, result = wired
    org = uuid.uuid4()
    result["value"] = PlanState("trial", _NOW, _NOW + dt.timedelta(days=10), None)

    response = await admin_router.extend_organization_trial(
        org, admin_router.TrialExtendRequest(days=7), {"sub": str(uuid.uuid4()), "name": "Alan"}
    )

    assert calls["actions"] == [(org, "extend", 7, None, "Alan")]
    assert calls["projected"] == [("organization", org)]
    assert response.status == "trial"
    assert response.effective_status == "trial"


async def test_suspend_passes_the_reason(wired) -> None:
    calls, result = wired
    org = uuid.uuid4()
    result["value"] = PlanState("suspended", None, None, None)

    response = await admin_router.suspend_organization(
        org, admin_router.SuspendRequest(reason="unpaid"), {}
    )

    assert calls["actions"][0][1:4] == ("suspend", None, "unpaid")
    assert response.effective_status == "suspended"


async def test_convert_and_reactivate_route_to_their_actions(wired) -> None:
    calls, result = wired
    result["value"] = PlanState("active", None, None, _NOW)
    await admin_router.convert_organization(uuid.uuid4(), {})
    await admin_router.reactivate_organization(uuid.uuid4(), {})
    assert [a[1] for a in calls["actions"]] == ["convert", "reactivate"]


@pytest.mark.parametrize("status", [404, 409, 400])
async def test_refusals_map_to_http_and_project_nothing(wired, status) -> None:
    calls, result = wired
    result["value"] = TrialControlError("nope", status_code=status)

    with pytest.raises(HTTPException) as exc:
        await admin_router.convert_organization(uuid.uuid4(), {})

    assert exc.value.status_code == status
    assert exc.value.detail == "nope"
    assert calls["projected"] == []


@pytest.fixture
def settings_wired(monkeypatch):
    calls: list = []

    async def fake_update(conn, key, value, *, actor):
        calls.append((key, value))
        if value.get("trial_days") == 0:
            raise ValueError("trial_days must be between 1 and 365")
        return {"trial_days": value["trial_days"], "retention_days_after_expiry": 30}

    monkeypatch.setattr(platform_settings_router, "get_engine", lambda: _Engine())
    monkeypatch.setattr(platform_settings_router, "update_platform_setting", fake_update)
    return calls


async def test_setting_update_returns_what_was_stored(settings_wired) -> None:
    response = await platform_settings_router.update_platform_setting_route(
        "trial_policy", {"trial_days": 14}, {}
    )
    assert response == {
        "key": "trial_policy",
        "value": {"trial_days": 14, "retention_days_after_expiry": 30},
    }


async def test_setting_bad_value_is_400_and_unknown_key_404(settings_wired) -> None:
    with pytest.raises(HTTPException) as bad:
        await platform_settings_router.update_platform_setting_route(
            "trial_policy", {"trial_days": 0}, {}
        )
    assert bad.value.status_code == 400

    with pytest.raises(HTTPException) as unknown:
        await platform_settings_router.update_platform_setting_route("nope", {}, {})
    assert unknown.value.status_code == 404
    assert settings_wired == [("trial_policy", {"trial_days": 0})]
