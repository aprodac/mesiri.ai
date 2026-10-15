"""Platform settings — Mesiri-wide rules set by the Mesiri team (SS-02).

Same shape as `settings.py` (per-company settings) but for values that apply
to every company: how long a free trial lasts, how long an expired trial's
data is kept, whether anyone can sign up on their own. Pure definitions, no
I/O; the store is infrastructure/postgres/repositories/platform_settings.py.

No row exists until someone changes a value in the superadmin, so each
default IS the behaviour. Self-serve signup defaults to off: switching it on
is a deliberate decision, never a side effect of a deploy.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass

TRIAL_POLICY = "trial_policy"
SELF_SERVE = "self_serve"
USAGE_PRICING = "usage_pricing"
TRIAL_GUARDRAILS = "trial_guardrails"

DEFAULT_TRIAL_POLICY: dict[str, int] = {
    # Length of a new company's free trial. Extendable per company.
    "trial_days": 7,
    # How long an expired trial's data is kept before it may be deleted.
    "retention_days_after_expiry": 30,
}

DEFAULT_SELF_SERVE: dict[str, bool] = {
    # Unknown WhatsApp numbers and the web signup page can create a company.
    "signup_enabled": False,
}

DEFAULT_USAGE_PRICING: dict[str, float] = {
    # USD -> INR for AI costs priced in dollars (BE-25). Each cost row keeps
    # the INR it was worth when written, so changing this never rewrites
    # history. Default: RBI reference rate of 18 May 2026, the latest found.
    "usd_inr": 96.29,
}

DEFAULT_TRIAL_GUARDRAILS: dict[str, object] = {
    # SS-09. Self-serve signups only from numbers with these country codes
    # (Mesiri is India-only for now; an OTP abroad also costs ~20x).
    "allowed_country_codes": ["91"],
    # A number can start a new free trial only this many days after its last.
    "trial_per_phone_days": 365,
    # Self-serve trials created across the platform in any 24 hours.
    "max_signups_per_day": 25,
    # Different numbers signing up from one IP address in 24 hours (web).
    "max_phones_per_ip_per_day": 3,
    # A trial company's own usage per day (India time) before Mesiri pauses
    # until tomorrow -- runaway protection, ~15x a normal trial's day.
    "trial_daily_ai_cost_inr": 50,
    "trial_daily_whatsapp_messages": 200,
}

# Bounds a superadmin can't go past by typo.
_TRIAL_DAYS_RANGE = (1, 365)
_RETENTION_DAYS_RANGE = (0, 3650)
_USD_INR_RANGE = (50.0, 200.0)
_GUARDRAIL_RANGES: dict[str, tuple[int, int]] = {
    "trial_per_phone_days": (0, 3650),
    "max_signups_per_day": (1, 100_000),
    "max_phones_per_ip_per_day": (1, 1000),
    "trial_daily_ai_cost_inr": (0, 100_000),
    "trial_daily_whatsapp_messages": (0, 100_000),
}


@dataclass(frozen=True, slots=True)
class PlatformSettingSpec:
    key: str
    default: dict[str, object]
    description: str


_SPECS: dict[str, PlatformSettingSpec] = {
    TRIAL_POLICY: PlatformSettingSpec(
        key=TRIAL_POLICY,
        default=DEFAULT_TRIAL_POLICY,
        description="Free trial length and how long data is kept after a trial expires.",
    ),
    SELF_SERVE: PlatformSettingSpec(
        key=SELF_SERVE,
        default=DEFAULT_SELF_SERVE,
        description="Whether new companies can sign up on their own (WhatsApp and web).",
    ),
    USAGE_PRICING: PlatformSettingSpec(
        key=USAGE_PRICING,
        default=DEFAULT_USAGE_PRICING,
        description="Exchange rate used to show AI costs (billed in USD) in rupees.",
    ),
    TRIAL_GUARDRAILS: PlatformSettingSpec(
        key=TRIAL_GUARDRAILS,
        default=DEFAULT_TRIAL_GUARDRAILS,
        description=(
            "Self-serve limits: allowed countries, one trial per number, daily sign-up "
            "limits, and each trial's daily AI and WhatsApp caps."
        ),
    ),
}


def is_known_key(key: str) -> bool:
    return key in _SPECS


def default_for(key: str) -> dict[str, object]:
    spec = _SPECS.get(key)
    if spec is None:
        raise KeyError(f"unknown platform setting: {key}")
    # Deep: a default holding a list must not be shared with the caller.
    return copy.deepcopy(spec.default)


def all_specs() -> tuple[PlatformSettingSpec, ...]:
    return tuple(_SPECS.values())


def with_defaults(key: str, stored: object) -> dict[str, object]:
    """The stored value with any missing field filled from the default, so
    adding a field later never breaks a row saved before it existed."""
    merged = default_for(key)
    if isinstance(stored, dict):
        merged.update({k: v for k, v in stored.items() if k in merged})
    return merged


def _int_in_range(name: str, value: object, bounds: tuple[int, int]) -> int:
    low, high = bounds
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be a whole number")
    if not low <= value <= high:
        raise ValueError(f"{name} must be between {low} and {high}")
    return value


def validate(key: str, value: object) -> dict[str, object]:
    """Check a value before it is stored. Unknown fields are rejected so a
    typo can't be saved and silently ignored."""
    if not is_known_key(key):
        raise KeyError(f"unknown platform setting: {key}")
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be an object")
    unknown = set(value) - set(_SPECS[key].default)
    if unknown:
        raise ValueError(f"unknown fields for {key}: {sorted(unknown)}")
    merged = with_defaults(key, value)
    if key == TRIAL_POLICY:
        merged["trial_days"] = _int_in_range("trial_days", merged["trial_days"], _TRIAL_DAYS_RANGE)
        merged["retention_days_after_expiry"] = _int_in_range(
            "retention_days_after_expiry",
            merged["retention_days_after_expiry"],
            _RETENTION_DAYS_RANGE,
        )
    elif key == SELF_SERVE:
        if not isinstance(merged["signup_enabled"], bool):
            raise ValueError("signup_enabled must be true or false")
    elif key == USAGE_PRICING:
        rate = merged["usd_inr"]
        if isinstance(rate, bool) or not isinstance(rate, (int, float)):
            raise ValueError("usd_inr must be a number")
        low, high = _USD_INR_RANGE
        if not low <= rate <= high:
            raise ValueError(f"usd_inr must be between {low:g} and {high:g}")
        merged["usd_inr"] = float(rate)
    elif key == TRIAL_GUARDRAILS:
        codes = merged["allowed_country_codes"]
        if not isinstance(codes, list) or not all(
            isinstance(c, str) and c.isdigit() and 1 <= len(c) <= 3 for c in codes
        ):
            raise ValueError("allowed_country_codes must be a list of codes like \"91\"")
        merged["allowed_country_codes"] = sorted(set(codes))
        for name, bounds in _GUARDRAIL_RANGES.items():
            merged[name] = _int_in_range(name, merged[name], bounds)
    return merged
