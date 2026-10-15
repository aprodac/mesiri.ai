"""Whether a self-serve signup may go ahead (SS-06; the hook SS-09 fills in).

Every self-serve door asks here before it sends a signup code and again
before it creates the company. Today the only rule is the platform switch
`self_serve.signup_enabled` (off by default, SS-02).

SS-09 (guardrails: one active trial per phone, signup rate limits, flagged
signups) adds its checks inside `check_signup`, so every door gets them at
once. `SignupAttempt` already carries what those checks need: the number,
the door, and the caller's IP address when there is one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from mesiri.domains.organizations.platform_settings import SELF_SERVE
from mesiri.infrastructure.postgres.repositories.platform_settings import (
    PostgresPlatformSettingsRepository,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection


@dataclass(frozen=True, slots=True)
class SignupAttempt:
    phone: str
    signup_source: str  # lifecycle.SIGNUP_SOURCES: "web", "whatsapp"
    ip_address: str | None = None


class SignupRefused(Exception):  # noqa: N818 - a refusal, not a fault
    """The signup may not go ahead; the message is safe to show the person."""


async def check_signup(conn: AsyncConnection, attempt: SignupAttempt) -> None:
    """Raises SignupRefused when this signup may not go ahead."""
    self_serve = await PostgresPlatformSettingsRepository(conn).get(SELF_SERVE)
    if not self_serve.get("signup_enabled"):
        raise SignupRefused("Sign-up is closed for now. Contact Mesiri to get started.")
