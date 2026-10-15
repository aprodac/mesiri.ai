"""Whether a self-serve signup may go ahead (SS-06 hook, SS-09 guardrails).

Every self-serve door asks here before it sends a signup code and again
before it creates the company (in the same transaction as create_company):
the web signup (auth/code_login.py) and the WhatsApp signup
(runtime/signup_journey.py). In order:

1. the platform switch `self_serve.signup_enabled` (off by default, SS-02);
2. the `trial_guardrails` platform setting (SS-09): the number's country,
   one free trial per number per N days (from the audit log, which outlives
   deleted companies), a platform-wide daily limit on self-serve trials,
   and, for the web, a limit on different numbers from one IP address.

Every call is logged in `signup_attempts` with its outcome and the flags it
earned (shared IP, an earlier trial, a signup burst), in the caller's
transaction -- so a door that rolls back on refusal keeps only the allowed
attempts (which is all the per-IP count needs); refusals are also logged. The
rules themselves are pure, in domains/organizations/guardrails.py.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from mesiri.domains.organizations import guardrails
from mesiri.domains.organizations.platform_settings import SELF_SERVE, TRIAL_GUARDRAILS
from mesiri.infrastructure.postgres.repositories.admin_audit import (
    PostgresAdminAuditRepository,
)
from mesiri.infrastructure.postgres.repositories.platform_settings import (
    PostgresPlatformSettingsRepository,
)
from mesiri.infrastructure.postgres.repositories.signup_attempts import (
    PostgresSignupAttemptRepository,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection

_log = logging.getLogger(__name__)

_DAY = dt.timedelta(days=1)


@dataclass(frozen=True, slots=True)
class SignupAttempt:
    phone: str
    signup_source: str  # lifecycle.SIGNUP_SOURCES: "web", "whatsapp"
    ip_address: str | None = None


@dataclass(frozen=True, slots=True)
class SignupDecision:
    """An allowed signup, and the flags it earned (recorded, not blocking)."""

    flags: tuple[str, ...] = ()


class SignupRefused(Exception):  # noqa: N818 - a refusal, not a fault
    """The signup may not go ahead; the message is safe to show the person.
    `reason` is the guardrails.* code stored on the attempt."""

    def __init__(self, message: str, *, reason: str = guardrails.SIGNUP_CLOSED) -> None:
        super().__init__(message)
        self.reason = reason


async def check_signup(
    conn: AsyncConnection, attempt: SignupAttempt, *, now: dt.datetime | None = None
) -> SignupDecision:
    """Raises SignupRefused when this signup may not go ahead. Logs the
    attempt either way, in the caller's transaction."""
    now = now or dt.datetime.now(dt.UTC)
    settings = PostgresPlatformSettingsRepository(conn)

    self_serve = await settings.get(SELF_SERVE)
    if not self_serve.get("signup_enabled"):
        # Not logged: with signup off there is nothing to guard, and the
        # switch is the whole answer.
        raise SignupRefused(guardrails.REFUSAL_MESSAGES[guardrails.SIGNUP_CLOSED])

    rules = await settings.get(TRIAL_GUARDRAILS)
    audit = PostgresAdminAuditRepository(conn)
    attempts = PostgresSignupAttemptRepository(conn)
    phone = "".join(ch for ch in attempt.phone if ch.isdigit())
    counts = guardrails.SignupCounts(
        last_trial_started_at=await audit.last_trial_started_for_phone(phone),
        signups_last_day=await audit.count_self_signups_since(now - _DAY),
        other_phones_from_ip=(
            await attempts.other_phones_from_ip(attempt.ip_address, phone, since=now - _DAY)
            if attempt.ip_address
            else 0
        ),
    )
    verdict = guardrails.evaluate_signup(
        phone=phone,
        has_ip=bool(attempt.ip_address),
        counts=counts,
        rules=rules,
        now=now,
    )
    await attempts.record(
        phone=phone,
        signup_source=attempt.signup_source,
        ip_address=attempt.ip_address,
        reason=verdict.refused_reason,
        flags=verdict.flags,
        at=now,
    )
    if verdict.flags:
        _log.warning(
            "signup.flagged phone=%s source=%s flags=%s refused=%s",
            phone,
            attempt.signup_source,
            ",".join(verdict.flags),
            verdict.refused_reason,
        )
    if not verdict.allowed:
        reason = verdict.refused_reason or guardrails.SIGNUP_CLOSED
        # Also logged here: a caller that lets SignupRefused roll its
        # transaction back (the web door) loses the attempt row.
        _log.info(
            "signup.refused phone=%s source=%s reason=%s", phone, attempt.signup_source, reason
        )
        raise SignupRefused(guardrails.REFUSAL_MESSAGES[reason], reason=reason)
    return SignupDecision(flags=verdict.flags)
