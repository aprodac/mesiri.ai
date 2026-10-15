"""One-time codes sent on WhatsApp to log in or sign up (SS-06, WEB-12).

One mechanism for both: the web signup proves the phone is the person's by
sending a code to it, and an owner with no password (WhatsApp signups,
control-panel onboarding) logs in to the dashboard the same way.

The rules, all here so they are testable without a database:

    a code       6 digits, good for 10 minutes and one use
    wrong tries  5 per code, then it is dead and a new one must be sent
    resending    once a minute per number and purpose, 5 an hour
    a new code   voids the older ones for that number and purpose

Only an HMAC of the code is stored, keyed by the login-token secret, so a
database read does not hand out working codes. Where the row lives is the
store's business (infrastructure/postgres/repositories/login_codes.py), how
the code reaches the phone is the sender's (the assistant app's WhatsApp
template, or a dev sender that only logs it).

A verified signup code becomes a short-lived signup ticket: the phone,
signed, carried from "code is right" to "company created" while the person
answers the questions. It is signed with a key derived from, not equal to,
the login-token secret, so a ticket can never pass as a login.
"""

from __future__ import annotations

import datetime as dt
import enum
import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from typing import Protocol

import jwt

from mesiri.domains.identity.auth_service import ALGORITHM, SECRET_KEY

PURPOSE_LOGIN = "login"
PURPOSE_SIGNUP = "signup"
PURPOSES = (PURPOSE_LOGIN, PURPOSE_SIGNUP)

CODE_DIGITS = 6
CODE_TTL = dt.timedelta(minutes=10)
MAX_ATTEMPTS = 5
RESEND_AFTER = dt.timedelta(seconds=60)
SEND_WINDOW = dt.timedelta(hours=1)
MAX_SENDS_PER_WINDOW = 5

SIGNUP_TICKET_TTL = dt.timedelta(minutes=30)
_TICKET_KEY = hmac.new(SECRET_KEY.encode(), b"mesiri-signup-ticket", hashlib.sha256).hexdigest()
_TICKET_TYPE = "signup_ticket"


class LoginCodeError(ValueError):
    """A code can't be sent yet; `retry_after_s` says when it can."""

    def __init__(self, message: str, *, retry_after_s: int) -> None:
        super().__init__(message)
        self.retry_after_s = retry_after_s


class SignupTicketError(ValueError):
    """The signup ticket is missing, forged or expired."""


class CheckResult(enum.StrEnum):
    OK = "ok"
    WRONG = "wrong"  # an open code exists and this isn't it; the try was counted
    NO_CODE = "no_code"  # nothing to check against: never sent, used, expired or locked


@dataclass(frozen=True, slots=True)
class StoredCode:
    id: uuid.UUID
    code_hash: str
    attempts: int


@dataclass(frozen=True, slots=True)
class IssuedCode:
    code: str
    expires_at: dt.datetime
    resend_after_s: int


class LoginCodeStore(Protocol):
    async def sent_since(self, phone: str, purpose: str, since: dt.datetime) -> list[dt.datetime]:
        """When each code for this number and purpose was sent, since `since`."""
        ...

    async def add(
        self,
        *,
        phone: str,
        purpose: str,
        code_hash: str,
        expires_at: dt.datetime,
        created_at: dt.datetime,
    ) -> None: ...

    async def void_open(self, phone: str, purpose: str, now: dt.datetime) -> None:
        """Mark every unused code for this number and purpose as used."""
        ...

    async def latest_open(self, phone: str, purpose: str, now: dt.datetime) -> StoredCode | None:
        """The newest code that is unused, unexpired and under the try limit,
        locked for the rest of the transaction."""
        ...

    async def count_attempt(self, code_id: uuid.UUID) -> None: ...

    async def consume(self, code_id: uuid.UUID, now: dt.datetime) -> None: ...


class LoginCodeSender(Protocol):
    """Gets a code to a phone. True when it was handed over for delivery."""

    async def send(self, phone: str, code: str) -> bool: ...


def generate_code() -> str:
    return f"{secrets.randbelow(10**CODE_DIGITS):0{CODE_DIGITS}d}"


def hash_code(phone: str, purpose: str, code: str) -> str:
    message = f"{purpose}:{phone}:{code}".encode()
    return hmac.new(SECRET_KEY.encode(), message, hashlib.sha256).hexdigest()


def clean_code(raw: object) -> str:
    """What the person typed, without the spaces or dashes people add."""
    return "".join(ch for ch in str(raw or "") if ch.isdigit())


def _check_purpose(purpose: str) -> None:
    if purpose not in PURPOSES:
        raise ValueError(f"purpose must be one of {list(PURPOSES)}")


def _seconds(delta: dt.timedelta) -> int:
    return max(1, int(delta.total_seconds() + 0.999))


async def issue_code(
    store: LoginCodeStore, phone: str, purpose: str, *, now: dt.datetime
) -> IssuedCode:
    """A new code for `phone`, recorded in `store`; older ones stop working.
    Raises LoginCodeError when this number asked too recently or too often.
    Sending it is the caller's job, after this succeeds."""
    _check_purpose(purpose)
    sent = sorted(await store.sent_since(phone, purpose, now - SEND_WINDOW))
    if sent and now - sent[-1] < RESEND_AFTER:
        raise LoginCodeError(
            "A code was sent a moment ago. Wait a little before asking for another.",
            retry_after_s=_seconds(sent[-1] + RESEND_AFTER - now),
        )
    if len(sent) >= MAX_SENDS_PER_WINDOW:
        raise LoginCodeError(
            "Too many codes asked for this number. Try again later.",
            retry_after_s=_seconds(sent[-MAX_SENDS_PER_WINDOW] + SEND_WINDOW - now),
        )

    await store.void_open(phone, purpose, now)
    code = generate_code()
    expires_at = now + CODE_TTL
    await store.add(
        phone=phone,
        purpose=purpose,
        code_hash=hash_code(phone, purpose, code),
        expires_at=expires_at,
        created_at=now,
    )
    return IssuedCode(code=code, expires_at=expires_at, resend_after_s=_seconds(RESEND_AFTER))


async def check_code(
    store: LoginCodeStore, phone: str, purpose: str, code: str, *, now: dt.datetime
) -> CheckResult:
    """Check `code` against the open code for this number and purpose. A right
    code is used up; a wrong one counts a try. The caller must commit either
    way: a wrong try that rolls back is a free guess."""
    _check_purpose(purpose)
    stored = await store.latest_open(phone, purpose, now)
    if stored is None:
        return CheckResult.NO_CODE
    if not hmac.compare_digest(stored.code_hash, hash_code(phone, purpose, clean_code(code))):
        await store.count_attempt(stored.id)
        return CheckResult.WRONG
    await store.consume(stored.id, now)
    return CheckResult.OK


def issue_signup_ticket(phone: str, *, now: dt.datetime) -> str:
    payload = {"typ": _TICKET_TYPE, "phone": phone, "exp": now + SIGNUP_TICKET_TTL}
    return jwt.encode(payload, _TICKET_KEY, algorithm=ALGORITHM)


def read_signup_ticket(ticket: str) -> str:
    """The verified phone in a signup ticket; raises SignupTicketError."""
    try:
        payload = jwt.decode(ticket or "", _TICKET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError as exc:
        raise SignupTicketError("This signup has expired. Start again.") from exc
    phone = payload.get("phone")
    if payload.get("typ") != _TICKET_TYPE or not isinstance(phone, str) or not phone:
        raise SignupTicketError("This signup has expired. Start again.")
    return phone
