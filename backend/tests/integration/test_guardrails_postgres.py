"""SS-09: signup guardrails and trial caps against a real Postgres (integration)."""

from __future__ import annotations

import contextlib
import datetime as dt
import uuid

import pytest
from sqlalchemy import text

from mesiri.application.organizations.create_company import NewCompany, create_company
from mesiri.application.organizations.signup_guard import (
    SignupAttempt,
    SignupRefused,
    check_signup,
)
from mesiri.application.organizations.trial_usage import check_trial_usage
from mesiri.application.usage.recorder import UsageRecorder
from mesiri.infrastructure.postgres.repositories.platform_settings import (
    PostgresPlatformSettingsRepository,
)
from mesiri.infrastructure.postgres.repositories.signup_attempts import (
    PostgresSignupAttemptRepository,
)

pytestmark = pytest.mark.integration

_NOW = dt.datetime(2026, 10, 15, 6, 0, tzinfo=dt.UTC)


@pytest.fixture
async def conn():
    from sqlalchemy.ext.asyncio import create_async_engine

    from mesiri.bootstrap.settings import Settings

    engine = create_async_engine(Settings().postgres.dsn())
    async with engine.connect() as connection:
        tx = await connection.begin()
        settings = PostgresPlatformSettingsRepository(connection)
        await settings.set("self_serve", {"signup_enabled": True}, updated_by=None)
        # Isolate from whatever else the shared test database holds.
        await connection.execute(text("DELETE FROM signup_attempts"))
        await connection.execute(
            text("DELETE FROM admin_audit_log WHERE action = 'company.created'")
        )
        yield connection
        await tx.rollback()
    await engine.dispose()


def _phone() -> str:
    return "919" + str(uuid.uuid4().int)[:9]


async def _trial(conn, phone: str, *, at: dt.datetime = _NOW):
    return await create_company(
        conn,
        NewCompany(
            name="Trial Co",
            owner_name="T",
            owner_phone=phone,
            start_as="trial",
            signup_source="whatsapp",
        ),
        now=at,
    )


async def test_a_deleted_trials_number_cannot_start_another(conn) -> None:
    phone = _phone()
    created = await _trial(conn, phone, at=_NOW - dt.timedelta(days=10))
    await conn.execute(
        text("DELETE FROM organizations WHERE id = :id"), {"id": created.organization_id}
    )
    with pytest.raises(SignupRefused, match="already had a free trial") as exc:
        await check_signup(conn, SignupAttempt(phone=phone, signup_source="whatsapp"), now=_NOW)
    assert exc.value.reason == "previous_trial"
    [row] = (
        await conn.execute(
            text("SELECT outcome, reason, flags FROM signup_attempts WHERE phone = :p"),
            {"p": phone},
        )
    ).all()
    assert tuple(row) == ("refused", "previous_trial", ["previous_trial"])


async def test_platform_daily_limit_counts_self_signups_only(conn) -> None:
    await PostgresPlatformSettingsRepository(conn).set(
        "trial_guardrails", {"max_signups_per_day": 2}, updated_by=None
    )
    await _trial(conn, _phone())
    # A company made by Mesiri staff doesn't count.
    await create_company(
        conn, NewCompany(name="Staff Co", owner_name="S", owner_phone=_phone()), now=_NOW
    )
    decision = await check_signup(
        conn, SignupAttempt(phone=_phone(), signup_source="web"), now=_NOW
    )
    assert decision.flags == ("burst",)
    await _trial(conn, _phone())
    with pytest.raises(SignupRefused) as exc:
        await check_signup(conn, SignupAttempt(phone=_phone(), signup_source="web"), now=_NOW)
    assert exc.value.reason == "daily_limit"


async def test_ip_limit_counts_distinct_numbers(conn) -> None:
    ip = "203.0.113.7"
    first, second, third, fourth = (_phone() for _ in range(4))
    for phone in (first, first, second):  # a number checked twice counts once
        await check_signup(conn, SignupAttempt(phone, "web", ip), now=_NOW)
    decision = await check_signup(conn, SignupAttempt(third, "web", ip), now=_NOW)
    assert decision.flags == ("shared_ip",)
    with pytest.raises(SignupRefused) as exc:
        await check_signup(conn, SignupAttempt(fourth, "web", ip), now=_NOW)
    assert exc.value.reason == "ip_limit"
    flags = await PostgresSignupAttemptRepository(conn).flags_for_phone(third)
    assert flags == ["shared_ip"]


async def test_switch_off_refuses_without_logging(conn) -> None:
    await PostgresPlatformSettingsRepository(conn).set(
        "self_serve", {"signup_enabled": False}, updated_by=None
    )
    with pytest.raises(SignupRefused, match="closed"):
        await check_signup(conn, SignupAttempt(_phone(), "web"), now=_NOW)
    count = (await conn.execute(text("SELECT count(*) FROM signup_attempts"))).scalar_one()
    assert count == 0


class _SameConnection:
    def __init__(self, conn) -> None:
        self._conn = conn

    @contextlib.asynccontextmanager
    async def transaction(self):
        yield self._conn


async def test_trial_caps_apply_to_trials_only(conn) -> None:
    trial = await _trial(conn, _phone())
    active = await create_company(
        conn, NewCompany(name="Paying Co", owner_name="P", owner_phone=_phone()), now=_NOW
    )
    await PostgresPlatformSettingsRepository(conn).set(
        "trial_guardrails", {"trial_daily_whatsapp_messages": 2}, updated_by=None
    )
    now = dt.datetime.now(dt.UTC)
    recorder = UsageRecorder(_SameConnection(conn), now=lambda: now)
    for company in (trial, active):
        for _ in range(2):
            await recorder.record_whatsapp_sent(
                wamid=f"wamid.{uuid.uuid4().hex}",
                recipient=company.owner_whatsapp_number,
                category="service",
            )

    trial_verdict = await check_trial_usage(conn, trial.organization_id, now=now)
    assert (trial_verdict.over_cap, trial_verdict.reason) == (True, "whatsapp_messages")
    assert not (await check_trial_usage(conn, active.organization_id, now=now)).over_cap
    # Tomorrow (India time) it starts again.
    tomorrow = now + dt.timedelta(days=1)
    assert not (await check_trial_usage(conn, trial.organization_id, now=tomorrow)).over_cap
