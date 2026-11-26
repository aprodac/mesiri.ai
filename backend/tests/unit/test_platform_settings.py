"""SS-02: platform-wide settings (trial policy, self-serve switch)."""

from __future__ import annotations

import pytest

from mesiri.domains.organizations import platform_settings as ps


def test_defaults():
    assert ps.default_for(ps.TRIAL_POLICY) == {"trial_days": 7, "retention_days_after_expiry": 30}
    # Signup is on (15 Oct), but in testing mode (SS-79): the team sets up every company by hand.
    assert ps.default_for(ps.SELF_SERVE) == {"signup_enabled": True, "callback_only": True}


def test_defaults_are_copies():
    ps.default_for(ps.TRIAL_POLICY)["trial_days"] = 99
    assert ps.default_for(ps.TRIAL_POLICY)["trial_days"] == 7


def test_with_defaults_fills_missing_fields_and_ignores_unknown():
    merged = ps.with_defaults(ps.TRIAL_POLICY, {"trial_days": 14, "stale_field": 1})
    assert merged == {"trial_days": 14, "retention_days_after_expiry": 30}
    assert ps.with_defaults(ps.TRIAL_POLICY, None)["trial_days"] == 7


def test_validate_accepts_partial_update():
    assert ps.validate(ps.TRIAL_POLICY, {"trial_days": 14})["trial_days"] == 14
    assert ps.validate(ps.SELF_SERVE, {"signup_enabled": True}) == {"signup_enabled": True, "callback_only": True}
    assert ps.validate(ps.SELF_SERVE, {"callback_only": False})["callback_only"] is False


@pytest.mark.parametrize(
    "value",
    [
        {"trial_days": 0},
        {"trial_days": 366},
        {"trial_days": "7"},
        {"trial_days": True},
        {"retention_days_after_expiry": -1},
        {"trail_days": 7},  # typo is rejected, not silently ignored
        "7",
    ],
)
def test_validate_rejects_bad_trial_policy(value):
    with pytest.raises(ValueError):
        ps.validate(ps.TRIAL_POLICY, value)


def test_validate_rejects_non_boolean_switch():
    with pytest.raises(ValueError):
        ps.validate(ps.SELF_SERVE, {"signup_enabled": "yes"})
    with pytest.raises(ValueError):
        ps.validate(ps.SELF_SERVE, {"callback_only": "yes"})


def test_unknown_key():
    with pytest.raises(KeyError):
        ps.validate("nope", {})
    with pytest.raises(KeyError):
        ps.default_for("nope")
