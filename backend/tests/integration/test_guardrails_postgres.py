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


async def test_sa26_an_allowed_number_gets_one_more_trial_only(conn) -> None:
    """SA-26: "Allow a new trial" after a trial lifts it once; the next trial limits again."""
    from mesiri.application.audit.record import record_admin_action
    from mesiri.application.organizations.delete_company import delete_company
    from mesiri.domains.audit import actions as audit

    phone = _phone()
    first = await _trial(conn, phone, at=_NOW - dt.timedelta(days=10))
    await delete_company(conn, first.organization_id)  # the team deleted the test company
    attempt = SignupAttempt(phone=phone, signup_source="whatsapp")
    with pytest.raises(SignupRefused):
        await check_signup(conn, attempt, now=_NOW)

    await record_admin_action(
        conn,
        actor=audit.AuditActor(kind=audit.ACTOR_PLATFORM_ADMIN, label="Test admin"),
        action=audit.SIGNUP_TRIAL_ALLOWED,
        target_type="phone",
        target_id=phone,
        details={"phone": phone},
        now=_NOW - dt.timedelta(days=1),
    )
    await check_signup(conn, attempt, now=_NOW)  # allowed now

    # The new trial counts again: the old allow doesn't carry over.
    await _trial(conn, phone, at=_NOW)
    with pytest.raises(SignupRefused, match="already had a free trial"):
        await check_signup(conn, attempt, now=_NOW + dt.timedelta(hours=1))


async def test_sa26_an_allow_before_the_trial_does_not_count(conn) -> None:
    from mesiri.application.audit.record import record_admin_action
    from mesiri.domains.audit import actions as audit

    phone = _phone()
    await record_admin_action(
        conn,
        actor=audit.AuditActor(kind=audit.ACTOR_PLATFORM_ADMIN),
        action=audit.SIGNUP_TRIAL_ALLOWED,
        target_type="phone",
        target_id=phone,
        details={"phone": phone},
        now=_NOW - dt.timedelta(days=20),
    )
    await _trial(conn, phone, at=_NOW - dt.timedelta(days=10))
    with pytest.raises(SignupRefused):
        await check_signup(conn, SignupAttempt(phone=phone, signup_source="whatsapp"), now=_NOW)


async def _deleted(conn, created, *, at: dt.datetime, trial_ends_at: dt.datetime | None) -> None:
    """The control panel's Delete Tenant: the one delete step, then its audit entry."""
    from mesiri.application.audit.record import record_admin_action
    from mesiri.application.organizations.delete_company import delete_company
    from mesiri.domains.audit import actions as audit

    await delete_company(conn, created.organization_id)
    details = {"name": created.name} | ({"trial_ends_at": trial_ends_at} if trial_ends_at else {})
    await record_admin_action(
        conn,
        actor=audit.AuditActor(kind=audit.ACTOR_PLATFORM_ADMIN),
        action=audit.COMPANY_DELETED,
        organization_id=created.organization_id,
        target_type="organization",
        target_id=created.organization_id,
        details=details,
        now=at,
    )


async def test_ss24_deleted_after_2_days_of_7_leaves_5(conn) -> None:
    from mesiri.application.organizations.create_company import NewCompany, create_company

    phone = _phone()
    start = _NOW - dt.timedelta(days=30)
    first = await _trial(conn, phone, at=start)  # 7 days (the default)
    await _deleted(conn, first, at=start + dt.timedelta(days=2), trial_ends_at=first.trial_ends_at)

    decision = await check_signup(conn, SignupAttempt(phone=phone, signup_source="whatsapp"), now=_NOW)
    assert decision.trial_left == dt.timedelta(days=5)
    assert "previous_trial" in decision.flags

    again = await create_company(
        conn,
        NewCompany(name="Again Co", owner_name="T", owner_phone=phone, start_as="trial",
                   signup_source="whatsapp", trial_left=decision.trial_left),
        now=_NOW,
    )  # fmt: skip
    assert again.trial_ends_at - again.trial_started_at == dt.timedelta(days=5)

    # Deleted again after 1 more day: 4 days are left; the count never resets inside the window.
    await _deleted(conn, again, at=_NOW + dt.timedelta(days=1), trial_ends_at=again.trial_ends_at)
    later = await check_signup(
        conn, SignupAttempt(phone=phone, signup_source="whatsapp"), now=_NOW + dt.timedelta(days=3)
    )
    assert later.trial_left == dt.timedelta(days=4)


async def test_ss24_an_extension_before_the_delete_counts(conn) -> None:
    phone = _phone()
    first = await _trial(conn, phone, at=_NOW - dt.timedelta(days=9))
    # Extended to 10 days by the team, deleted on day 9: one day left.
    extended = first.trial_started_at + dt.timedelta(days=10)
    await _deleted(conn, first, at=_NOW, trial_ends_at=extended)
    decision = await check_signup(conn, SignupAttempt(phone=phone, signup_source="whatsapp"), now=_NOW)
    assert decision.trial_left == dt.timedelta(days=1)


async def test_ss24_an_old_delete_without_its_end_uses_the_trial_as_created(conn) -> None:
    phone = _phone()
    first = await _trial(conn, phone, at=_NOW - dt.timedelta(days=3))
    await _deleted(conn, first, at=_NOW - dt.timedelta(days=1), trial_ends_at=None)
    decision = await check_signup(conn, SignupAttempt(phone=phone, signup_source="whatsapp"), now=_NOW)
    assert decision.trial_left == dt.timedelta(days=5)  # 7 - 2 used


async def test_ss24_a_trial_used_up_is_refused(conn) -> None:
    phone = _phone()
    first = await _trial(conn, phone, at=_NOW - dt.timedelta(days=20))
    await _deleted(conn, first, at=_NOW - dt.timedelta(days=10), trial_ends_at=first.trial_ends_at)
    with pytest.raises(SignupRefused) as exc:
        await check_signup(conn, SignupAttempt(phone=phone, signup_source="whatsapp"), now=_NOW)
    assert exc.value.reason == "previous_trial"


async def test_ss24_less_than_an_hour_left_is_used_up(conn) -> None:
    phone = _phone()
    first = await _trial(conn, phone, at=_NOW - dt.timedelta(days=8))
    ends = first.trial_ends_at
    await _deleted(conn, first, at=ends - dt.timedelta(minutes=30), trial_ends_at=ends)
    with pytest.raises(SignupRefused):
        await check_signup(conn, SignupAttempt(phone=phone, signup_source="whatsapp"), now=_NOW)


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
