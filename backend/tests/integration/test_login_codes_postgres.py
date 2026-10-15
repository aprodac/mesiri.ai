"""SS-06 / WEB-12: the login-code store and the signup check against a real
Postgres (integration). Every test runs in a transaction that is rolled back."""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import text

from mesiri.application.identity import login_codes as lc
from mesiri.application.organizations.signup_guard import (
    SignupAttempt,
    SignupRefused,
    check_signup,
)
from mesiri.domains.organizations.platform_settings import SELF_SERVE
from mesiri.infrastructure.postgres.repositories.login_codes import PostgresLoginCodeStore
from mesiri.infrastructure.postgres.repositories.platform_settings import (
    PostgresPlatformSettingsRepository,
)

pytestmark = pytest.mark.integration

_NOW = dt.datetime(2026, 10, 15, 9, 0, tzinfo=dt.UTC)
_PHONE = "919876500042"


@pytest.fixture
async def conn():
    from sqlalchemy.ext.asyncio import create_async_engine

    from mesiri.bootstrap.settings import Settings

    engine = create_async_engine(Settings().postgres.dsn())
    async with engine.connect() as connection:
        tx = await connection.begin()
        yield connection
        await tx.rollback()
    await engine.dispose()


async def test_issue_check_and_use_up_a_code(conn) -> None:
    store = PostgresLoginCodeStore(conn)
    issued = await lc.issue_code(store, _PHONE, lc.PURPOSE_LOGIN, now=_NOW)

    row = (
        (await conn.execute(text("SELECT * FROM login_codes WHERE phone = :p"), {"p": _PHONE}))
        .mappings()
        .one()
    )
    assert row["purpose"] == "login"
    assert row["code_hash"] != issued.code
    assert row["expires_at"] == _NOW + lc.CODE_TTL

    wrong = "000000" if issued.code != "000000" else "111111"
    assert await lc.check_code(store, _PHONE, "login", wrong, now=_NOW) is lc.CheckResult.WRONG
    assert await lc.check_code(store, _PHONE, "login", issued.code, now=_NOW) is lc.CheckResult.OK
    assert (
        await lc.check_code(store, _PHONE, "login", issued.code, now=_NOW) is lc.CheckResult.NO_CODE
    )

    row = (
        (await conn.execute(text("SELECT * FROM login_codes WHERE phone = :p"), {"p": _PHONE}))
        .mappings()
        .one()
    )
    assert row["attempts"] == 1
    assert row["consumed_at"] == _NOW


async def test_new_code_voids_the_old_and_limits_count_from_rows(conn) -> None:
    store = PostgresLoginCodeStore(conn)
    first = await lc.issue_code(store, _PHONE, lc.PURPOSE_SIGNUP, now=_NOW)
    with pytest.raises(lc.LoginCodeError):
        await lc.issue_code(store, _PHONE, lc.PURPOSE_SIGNUP, now=_NOW + dt.timedelta(seconds=5))
    second = await lc.issue_code(
        store, _PHONE, lc.PURPOSE_SIGNUP, now=_NOW + dt.timedelta(minutes=2)
    )
    at = _NOW + dt.timedelta(minutes=3)
    if first.code != second.code:
        assert (
            await lc.check_code(store, _PHONE, "signup", first.code, now=at) is lc.CheckResult.WRONG
        )
    assert await lc.check_code(store, _PHONE, "signup", second.code, now=at) is lc.CheckResult.OK


async def test_signup_is_refused_until_switched_on(conn) -> None:
    attempt = SignupAttempt(phone=_PHONE, signup_source="web", ip_address="203.0.113.7")
    settings = PostgresPlatformSettingsRepository(conn)

    await settings.set(SELF_SERVE, {"signup_enabled": False}, updated_by=None)
    with pytest.raises(SignupRefused, match="closed"):
        await check_signup(conn, attempt)

    await settings.set(SELF_SERVE, {"signup_enabled": True}, updated_by=None)
    await check_signup(conn, attempt)
