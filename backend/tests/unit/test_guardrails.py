"""SS-09: self-serve guardrail rules and the trial usage guard (no database)."""

from __future__ import annotations

import contextlib
import datetime as dt
import uuid
from decimal import Decimal

import pytest

from mesiri.application.organizations import trial_usage
from mesiri.domains.organizations import guardrails, platform_settings

_NOW = dt.datetime(2026, 10, 15, 6, 0, tzinfo=dt.UTC)
RULES = platform_settings.with_defaults("trial_guardrails", None)


def _counts(**overrides) -> guardrails.SignupCounts:
    fields = {"last_trial_started_at": None, "signups_last_day": 0, "other_phones_from_ip": 0}
    fields.update(overrides)
    return guardrails.SignupCounts(**fields)


def _verdict(phone="919876543210", has_ip=True, rules=RULES, **counts):
    return guardrails.evaluate_signup(
        phone=phone, has_ip=has_ip, counts=_counts(**counts), rules=rules, now=_NOW
    )


def test_defaults() -> None:
    assert RULES == {
        "allowed_country_codes": ["91"],
        "trial_per_phone_days": 365,
        "max_signups_per_day": 25,
        "max_phones_per_ip_per_day": 3,
        "trial_daily_ai_cost_inr": 50,
        "trial_daily_whatsapp_messages": 200,
    }
    # The default's list is not shared with callers.
    RULES["allowed_country_codes"].append("1")
    assert platform_settings.with_defaults("trial_guardrails", None)[
        "allowed_country_codes"
    ] == ["91"]
    RULES["allowed_country_codes"].remove("1")


def test_a_clean_indian_signup_is_allowed_without_flags() -> None:
    assert _verdict() == guardrails.SignupVerdict(None, ())


def test_foreign_number_is_refused() -> None:
    verdict = _verdict(phone="14155550100")
    assert verdict.refused_reason == guardrails.COUNTRY_NOT_ALLOWED
    assert verdict.flags == (guardrails.FLAG_FOREIGN_NUMBER,)


def test_one_trial_per_number_per_window() -> None:
    recent = _verdict(last_trial_started_at=_NOW - dt.timedelta(days=30))
    assert recent.refused_reason == guardrails.PREVIOUS_TRIAL
    long_ago = _verdict(last_trial_started_at=_NOW - dt.timedelta(days=400))
    assert long_ago.allowed
    assert long_ago.flags == (guardrails.FLAG_PREVIOUS_TRIAL,)


def test_platform_daily_limit_and_burst_flag() -> None:
    assert _verdict(signups_last_day=25).refused_reason == guardrails.DAILY_LIMIT
    assert _verdict(signups_last_day=20).flags == (guardrails.FLAG_BURST,)
    assert _verdict(signups_last_day=18).flags == ()


def test_ip_limit_counts_other_numbers_and_flags_sharing() -> None:
    assert _verdict(other_phones_from_ip=1).flags == (guardrails.FLAG_SHARED_IP,)
    refused = _verdict(other_phones_from_ip=3)
    assert refused.refused_reason == guardrails.IP_LIMIT
    # No IP (WhatsApp door): the IP rule doesn't apply.
    assert _verdict(has_ip=False, other_phones_from_ip=99).allowed


def test_every_refusal_has_a_message() -> None:
    for reason in (
        guardrails.SIGNUP_CLOSED,
        guardrails.COUNTRY_NOT_ALLOWED,
        guardrails.PREVIOUS_TRIAL,
        guardrails.DAILY_LIMIT,
        guardrails.IP_LIMIT,
    ):
        assert guardrails.REFUSAL_MESSAGES[reason]


def test_setting_validation() -> None:
    valid = platform_settings.validate(
        "trial_guardrails", {"allowed_country_codes": ["91", "971", "91"]}
    )
    assert valid["allowed_country_codes"] == ["91", "971"]
    with pytest.raises(ValueError, match="allowed_country_codes"):
        platform_settings.validate("trial_guardrails", {"allowed_country_codes": ["+91"]})
    with pytest.raises(ValueError, match="max_signups_per_day"):
        platform_settings.validate("trial_guardrails", {"max_signups_per_day": 0})
    with pytest.raises(ValueError, match="unknown fields"):
        platform_settings.validate("trial_guardrails", {"max_trials": 1})


@pytest.mark.parametrize(
    ("ai", "wa", "expected"),
    [
        ("3.20", 30, guardrails.NOT_OVER),
        ("50", 30, guardrails.TrialUsageVerdict(True, "ai_cost")),
        ("1", 200, guardrails.TrialUsageVerdict(True, "whatsapp_messages")),
    ],
)
def test_trial_caps(ai, wa, expected) -> None:
    verdict = guardrails.evaluate_trial_usage(
        ai_cost_inr=Decimal(ai), whatsapp_messages=wa, rules=RULES
    )
    assert verdict == expected


def test_a_zero_cap_means_no_cap() -> None:
    rules = {**RULES, "trial_daily_ai_cost_inr": 0, "trial_daily_whatsapp_messages": 0}
    verdict = guardrails.evaluate_trial_usage(
        ai_cost_inr=Decimal(10_000), whatsapp_messages=10_000, rules=rules
    )
    assert not verdict.over_cap


def test_cap_day_starts_at_midnight_india_time() -> None:
    # 20:00 UTC on the 15th is 01:30 on the 16th in India.
    start = guardrails.cap_day_start(dt.datetime(2026, 10, 15, 20, 0, tzinfo=dt.UTC))
    assert start == dt.datetime(2026, 10, 15, 18, 30, tzinfo=dt.UTC)


class _Db:
    def __init__(self) -> None:
        self.opened = 0
        self.fail = False

    @contextlib.asynccontextmanager
    async def transaction(self):
        self.opened += 1
        if self.fail:
            raise RuntimeError("db down")
        yield object()


async def test_guard_caches_for_a_minute_and_fails_open(monkeypatch) -> None:
    verdicts = [guardrails.TrialUsageVerdict(True, "ai_cost")]

    async def fake_check(conn, org, *, now=None):
        return verdicts[0]

    monkeypatch.setattr(trial_usage, "check_trial_usage", fake_check)
    clock = [0.0]
    db = _Db()
    guard = trial_usage.TrialUsageGuard(db, clock=lambda: clock[0])
    org = uuid.uuid4()

    assert (await guard.check(org)).over_cap
    clock[0] = 30.0
    assert (await guard.check(str(org))).over_cap
    assert db.opened == 1  # cached

    clock[0] = 61.0
    db.fail = True
    assert not (await guard.check(org)).over_cap  # a failing check lets it through
