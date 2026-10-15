"""SS-06 / WEB-12: the rules for one-time login and signup codes (no database)."""

from __future__ import annotations

import datetime as dt
import uuid

import jwt
import pytest

from mesiri.application.identity import login_codes as lc
from mesiri.domains.identity.auth_service import ALGORITHM, SECRET_KEY

_NOW = dt.datetime(2026, 10, 15, 9, 0, tzinfo=dt.UTC)
_PHONE = "919876543210"


class _Store:
    """In-memory LoginCodeStore with the same filters as the Postgres one."""

    def __init__(self) -> None:
        self.rows: list[dict] = []

    async def sent_since(self, phone, purpose, since):
        return [
            r["created_at"]
            for r in self.rows
            if r["phone"] == phone and r["purpose"] == purpose and r["created_at"] >= since
        ]

    async def add(self, *, phone, purpose, code_hash, expires_at, created_at):
        self.rows.append(
            {
                "id": uuid.uuid4(),
                "phone": phone,
                "purpose": purpose,
                "code_hash": code_hash,
                "expires_at": expires_at,
                "attempts": 0,
                "consumed_at": None,
                "created_at": created_at,
            }
        )

    async def void_open(self, phone, purpose, now):
        for r in self.rows:
            if r["phone"] == phone and r["purpose"] == purpose and r["consumed_at"] is None:
                r["consumed_at"] = now

    async def latest_open(self, phone, purpose, now):
        open_rows = [
            r
            for r in self.rows
            if r["phone"] == phone
            and r["purpose"] == purpose
            and r["consumed_at"] is None
            and r["expires_at"] > now
            and r["attempts"] < lc.MAX_ATTEMPTS
        ]
        if not open_rows:
            return None
        r = max(open_rows, key=lambda row: row["created_at"])
        return lc.StoredCode(id=r["id"], code_hash=r["code_hash"], attempts=r["attempts"])

    def _row(self, code_id):
        return next(r for r in self.rows if r["id"] == code_id)

    async def count_attempt(self, code_id):
        self._row(code_id)["attempts"] += 1

    async def consume(self, code_id, now):
        self._row(code_id)["consumed_at"] = now


async def _issue(store, *, at=_NOW, purpose=lc.PURPOSE_LOGIN, phone=_PHONE):
    return await lc.issue_code(store, phone, purpose, now=at)


def test_codes_are_six_digits() -> None:
    codes = {lc.generate_code() for _ in range(200)}
    assert all(len(c) == 6 and c.isdigit() for c in codes)
    assert len(codes) > 150  # random, not a counter


async def test_code_is_stored_hashed_and_works_once() -> None:
    store = _Store()
    issued = await _issue(store)
    assert issued.expires_at == _NOW + dt.timedelta(minutes=10)
    assert issued.code not in store.rows[0]["code_hash"]

    later = _NOW + dt.timedelta(minutes=2)
    assert (
        await lc.check_code(store, _PHONE, lc.PURPOSE_LOGIN, issued.code, now=later)
        is lc.CheckResult.OK
    )
    assert (
        await lc.check_code(store, _PHONE, lc.PURPOSE_LOGIN, issued.code, now=later)
        is lc.CheckResult.NO_CODE
    )


async def test_typed_spaces_and_dashes_are_ignored() -> None:
    store = _Store()
    issued = await _issue(store)
    typed = f"{issued.code[:3]} - {issued.code[3:]}"
    assert (
        await lc.check_code(store, _PHONE, lc.PURPOSE_LOGIN, typed, now=_NOW) is lc.CheckResult.OK
    )


async def test_code_expires_after_ten_minutes() -> None:
    store = _Store()
    issued = await _issue(store)
    late = _NOW + dt.timedelta(minutes=10, seconds=1)
    assert (
        await lc.check_code(store, _PHONE, lc.PURPOSE_LOGIN, issued.code, now=late)
        is lc.CheckResult.NO_CODE
    )


async def test_five_wrong_tries_kill_the_code() -> None:
    store = _Store()
    issued = await _issue(store)
    wrong = "000000" if issued.code != "000000" else "111111"
    for _ in range(lc.MAX_ATTEMPTS):
        assert (
            await lc.check_code(store, _PHONE, lc.PURPOSE_LOGIN, wrong, now=_NOW)
            is lc.CheckResult.WRONG
        )
    assert (
        await lc.check_code(store, _PHONE, lc.PURPOSE_LOGIN, issued.code, now=_NOW)
        is lc.CheckResult.NO_CODE
    )


async def test_a_code_is_for_one_number_and_one_purpose() -> None:
    store = _Store()
    issued = await _issue(store, purpose=lc.PURPOSE_SIGNUP)
    assert (
        await lc.check_code(store, _PHONE, lc.PURPOSE_LOGIN, issued.code, now=_NOW)
        is lc.CheckResult.NO_CODE
    )
    assert (
        await lc.check_code(store, "919999999999", lc.PURPOSE_SIGNUP, issued.code, now=_NOW)
        is lc.CheckResult.NO_CODE
    )
    assert (
        await lc.check_code(store, _PHONE, lc.PURPOSE_SIGNUP, issued.code, now=_NOW)
        is lc.CheckResult.OK
    )


async def test_resend_waits_a_minute_and_voids_the_old_code() -> None:
    store = _Store()
    first = await _issue(store)
    with pytest.raises(lc.LoginCodeError) as exc_info:
        await _issue(store, at=_NOW + dt.timedelta(seconds=20))
    assert exc_info.value.retry_after_s == 40

    second = await _issue(store, at=_NOW + dt.timedelta(seconds=61))
    at = _NOW + dt.timedelta(seconds=62)
    if first.code != second.code:
        assert (
            await lc.check_code(store, _PHONE, lc.PURPOSE_LOGIN, first.code, now=at)
            is lc.CheckResult.WRONG
        )
    assert (
        await lc.check_code(store, _PHONE, lc.PURPOSE_LOGIN, second.code, now=at)
        is lc.CheckResult.OK
    )


async def test_at_most_five_codes_an_hour() -> None:
    store = _Store()
    for i in range(lc.MAX_SENDS_PER_WINDOW):
        await _issue(store, at=_NOW + dt.timedelta(minutes=2 * i))
    with pytest.raises(lc.LoginCodeError) as exc_info:
        await _issue(store, at=_NOW + dt.timedelta(minutes=10))
    # The oldest of the five leaves the hour at 10:00, 50 minutes from now.
    assert exc_info.value.retry_after_s == 50 * 60
    await _issue(store, at=_NOW + dt.timedelta(hours=1, seconds=1))


async def test_unknown_purpose_is_refused() -> None:
    with pytest.raises(ValueError, match="purpose"):
        await _issue(_Store(), purpose="reset")


def test_signup_ticket_round_trip() -> None:
    ticket = lc.issue_signup_ticket(_PHONE, now=dt.datetime.now(dt.UTC))
    assert lc.read_signup_ticket(ticket) == _PHONE


def test_expired_or_forged_signup_ticket_is_refused() -> None:
    old = lc.issue_signup_ticket(_PHONE, now=dt.datetime.now(dt.UTC) - dt.timedelta(hours=1))
    with pytest.raises(lc.SignupTicketError):
        lc.read_signup_ticket(old)
    with pytest.raises(lc.SignupTicketError):
        lc.read_signup_ticket("not-a-ticket")


def test_a_login_token_is_not_a_signup_ticket_and_vice_versa() -> None:
    login_token = jwt.encode(
        {"sub": "u", "phone": _PHONE, "exp": dt.datetime.now(dt.UTC) + dt.timedelta(hours=1)},
        SECRET_KEY,
        algorithm=ALGORITHM,
    )
    with pytest.raises(lc.SignupTicketError):
        lc.read_signup_ticket(login_token)

    ticket = lc.issue_signup_ticket(_PHONE, now=dt.datetime.now(dt.UTC))
    with pytest.raises(jwt.PyJWTError):
        jwt.decode(ticket, SECRET_KEY, algorithms=[ALGORITHM])
