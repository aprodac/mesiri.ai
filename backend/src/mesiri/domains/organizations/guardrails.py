"""Self-serve guardrails (SS-09): the rules, without I/O.

Whether a signup may go ahead, which flags a signup earns, and whether a
trial company is over its daily usage caps. The numbers come from the
`trial_guardrails` platform setting; the counts come from the caller
(application/organizations/signup_guard.py and trial_usage.py).

Refusal messages are shown to the person signing up, so they are plain and
say what to do next.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from zoneinfo import ZoneInfo

# Refusal reasons (stored on signup_attempts.reason) and what the person sees.
SIGNUP_CLOSED = "signup_closed"
COUNTRY_NOT_ALLOWED = "country_not_allowed"
PREVIOUS_TRIAL = "previous_trial"
DAILY_LIMIT = "daily_limit"
IP_LIMIT = "ip_limit"

REFUSAL_MESSAGES: dict[str, str] = {
    SIGNUP_CLOSED: "Sign-up is closed for now. Contact Mesiri to get started.",
    COUNTRY_NOT_ALLOWED: (
        "Mesiri is only available for Indian WhatsApp numbers for now. "
        "Contact Mesiri if you'd like to use it."
    ),
    PREVIOUS_TRIAL: (
        "This number has already had a free trial. Message us to continue with Mesiri."
    ),
    DAILY_LIMIT: "We're getting a lot of sign-ups right now. Please try again tomorrow.",
    IP_LIMIT: "We're getting a lot of sign-ups right now. Please try again tomorrow.",
}

# Flags: recorded, never blocking.
FLAG_SHARED_IP = "shared_ip"
FLAG_PREVIOUS_TRIAL = "previous_trial"
FLAG_BURST = "burst"
FLAG_FOREIGN_NUMBER = "foreign_number"

# Platform signups over this share of the daily limit flag a "burst".
_BURST_SHARE = Decimal("0.8")

# A trial's "day" for the caps: India time, the same day its reports use.
CAP_TIMEZONE = ZoneInfo("Asia/Kolkata")

TRIAL_LIMIT_MESSAGE = (
    "You've reached today's free-trial limit, so I can't read more updates today. "
    "Mesiri will be back tomorrow morning. Message us if you need more."
)


@dataclass(frozen=True, slots=True)
class SignupCounts:
    """What the database says about this attempt, for `evaluate_signup`."""

    # When this number last started a trial (any company, deleted or not).
    last_trial_started_at: dt.datetime | None
    # Self-serve trials created across the platform in the last 24 hours.
    signups_last_day: int
    # Other numbers seen from this IP in the last 24 hours (not this one).
    other_phones_from_ip: int


@dataclass(frozen=True, slots=True)
class SignupVerdict:
    refused_reason: str | None
    flags: tuple[str, ...]

    @property
    def allowed(self) -> bool:
        return self.refused_reason is None


def country_allowed(phone: str, allowed_codes: list[str]) -> bool:
    """`phone` is digits with the country code first (WhatsApp-id form)."""
    return any(phone.startswith(code) for code in allowed_codes)


def evaluate_signup(
    *,
    phone: str,
    has_ip: bool,
    counts: SignupCounts,
    rules: dict[str, object],
    now: dt.datetime,
) -> SignupVerdict:
    """Refuse or allow one self-serve signup attempt, with its flags.
    Checks run cheapest-and-most-specific first; the first refusal wins."""
    flags: list[str] = []
    allowed_codes = list(rules["allowed_country_codes"])  # type: ignore[arg-type]
    if not country_allowed(phone, allowed_codes):
        return SignupVerdict(COUNTRY_NOT_ALLOWED, (FLAG_FOREIGN_NUMBER,))

    window_days = int(rules["trial_per_phone_days"])  # type: ignore[arg-type]
    if counts.last_trial_started_at is not None:
        if now - counts.last_trial_started_at < dt.timedelta(days=window_days):
            return SignupVerdict(PREVIOUS_TRIAL, (FLAG_PREVIOUS_TRIAL,))
        flags.append(FLAG_PREVIOUS_TRIAL)

    max_per_day = int(rules["max_signups_per_day"])  # type: ignore[arg-type]
    if counts.signups_last_day >= max_per_day:
        return SignupVerdict(DAILY_LIMIT, tuple(flags))
    if max_per_day and Decimal(counts.signups_last_day + 1) > _BURST_SHARE * max_per_day:
        flags.append(FLAG_BURST)

    if has_ip:
        max_phones = int(rules["max_phones_per_ip_per_day"])  # type: ignore[arg-type]
        if counts.other_phones_from_ip >= max_phones:
            return SignupVerdict(IP_LIMIT, (*flags, FLAG_SHARED_IP))
        if counts.other_phones_from_ip >= 1:
            flags.append(FLAG_SHARED_IP)

    return SignupVerdict(None, tuple(flags))


def cap_day_start(now: dt.datetime) -> dt.datetime:
    """Midnight today, India time, as an aware datetime."""
    local = now.astimezone(CAP_TIMEZONE)
    return local.replace(hour=0, minute=0, second=0, microsecond=0)


@dataclass(frozen=True, slots=True)
class TrialUsageVerdict:
    over_cap: bool
    reason: str | None = None


NOT_OVER = TrialUsageVerdict(over_cap=False)


def evaluate_trial_usage(
    *, ai_cost_inr: Decimal, whatsapp_messages: int, rules: dict[str, object]
) -> TrialUsageVerdict:
    """Is a trial company over today's caps? A cap of 0 means no cap."""
    ai_cap = int(rules["trial_daily_ai_cost_inr"])  # type: ignore[arg-type]
    wa_cap = int(rules["trial_daily_whatsapp_messages"])  # type: ignore[arg-type]
    if ai_cap and ai_cost_inr >= ai_cap:
        return TrialUsageVerdict(True, "ai_cost")
    if wa_cap and whatsapp_messages >= wa_cap:
        return TrialUsageVerdict(True, "whatsapp_messages")
    return NOT_OVER
