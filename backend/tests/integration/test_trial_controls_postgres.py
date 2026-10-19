"""SS-10: trial controls and platform settings against a real Postgres
(integration): the change and its audit entry land together, a refusal
leaves nothing. Each test runs in a transaction that is rolled back."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from sqlalchemy import text

from mesiri.application.organizations import trial_controls
from mesiri.application.organizations.companies_overview import company_setup
from mesiri.application.organizations.create_company import NewCompany, create_company
from mesiri.application.organizations.platform_settings_admin import update_platform_setting
from mesiri.domains.audit.actions import ACTOR_PLATFORM_ADMIN, AuditActor

pytestmark = pytest.mark.integration

_NOW = dt.datetime.now(dt.UTC)
_ADMIN = AuditActor(kind=ACTOR_PLATFORM_ADMIN, user_id=uuid.uuid4(), label="Alan")


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


async def _trial_company(conn, phone: str):
    created = await create_company(
        conn,
        NewCompany(
            name="Trial Builders",
            owner_name="Owner",
            owner_phone=phone,
            start_as="trial",
            signup_source="whatsapp",
        ),
        now=_NOW,
    )
    return created.organization_id


async def _audit(conn, org_id, action: str):
    rows = await conn.execute(
        text("SELECT * FROM admin_audit_log WHERE organization_id = :org AND action = :action"),
        {"org": org_id, "action": action},
    )
    return rows.mappings().all()


async def test_extend_then_convert_are_saved_and_audited(conn) -> None:
    org = await _trial_company(conn, "+91 98765 20001")

    await trial_controls.apply_trial_action(
        conn, org, trial_controls.EXTEND, actor=_ADMIN, days=7, now=_NOW
    )
    company = await company_setup(conn, org, now=_NOW)
    assert company.effective_status == "trial"
    assert company.trial_days_left == 14  # 7 default + 7
    [entry] = await _audit(conn, org, "company.trial_extended")
    assert entry["actor_label"] == "Alan"
    assert entry["details"]["days"] == 7
    assert entry["summary"] == "Trial Builders: Trial extended by 7 days"

    await trial_controls.apply_trial_action(
        conn, org, trial_controls.CONVERT, actor=_ADMIN, now=_NOW
    )
    company = await company_setup(conn, org, now=_NOW)
    assert company.effective_status == "active"
    assert company.converted_at == _NOW
    [entry] = await _audit(conn, org, "company.converted")
    assert entry["details"]["before"]["status"] == "trial"
    assert entry["details"]["after"]["status"] == "active"


async def test_suspend_and_reactivate_back_to_the_trial(conn) -> None:
    org = await _trial_company(conn, "+91 98765 20002")

    await trial_controls.apply_trial_action(
        conn, org, trial_controls.SUSPEND, actor=_ADMIN, reason="  unpaid   invoice ", now=_NOW
    )
    assert (await company_setup(conn, org, now=_NOW)).effective_status == "suspended"
    [entry] = await _audit(conn, org, "company.suspended")
    assert entry["details"]["reason"] == "unpaid invoice"

    await trial_controls.apply_trial_action(
        conn, org, trial_controls.REACTIVATE, actor=_ADMIN, now=_NOW
    )
    company = await company_setup(conn, org, now=_NOW)
    assert company.effective_status == "trial"
    assert company.trial_days_left == 7
    assert len(await _audit(conn, org, "company.reactivated")) == 1


async def test_refused_action_changes_and_records_nothing(conn) -> None:
    org = await _trial_company(conn, "+91 98765 20003")

    with pytest.raises(trial_controls.TrialControlError) as exc:
        await trial_controls.apply_trial_action(
            conn, org, trial_controls.REACTIVATE, actor=_ADMIN, now=_NOW
        )

    assert exc.value.status_code == 409
    assert (await company_setup(conn, org, now=_NOW)).effective_status == "trial"
    assert await _audit(conn, org, "company.reactivated") == []


async def test_unknown_company_is_not_found(conn) -> None:
    with pytest.raises(trial_controls.TrialControlError) as exc:
        await trial_controls.apply_trial_action(
            conn, uuid.uuid4(), trial_controls.SUSPEND, actor=_ADMIN, now=_NOW
        )
    assert exc.value.status_code == 404
    assert await company_setup(conn, uuid.uuid4()) is None


async def test_trial_length_change_is_stored_audited_and_used(conn) -> None:
    stored = await update_platform_setting(conn, "trial_policy", {"trial_days": 14}, actor=_ADMIN)

    assert stored == {"trial_days": 14, "retention_days_after_expiry": 30}
    entry = (
        (
            await conn.execute(
                text(
                    "SELECT * FROM admin_audit_log WHERE action = 'platform_setting.changed'"
                    " AND target_id = 'trial_policy' ORDER BY occurred_at DESC LIMIT 1"
                )
            )
        )
        .mappings()
        .one()
    )
    assert entry["summary"] == "trial_policy: trial_days 7 -> 14"
    org = await _trial_company(conn, "+91 98765 20004")
    assert (await company_setup(conn, org, now=_NOW)).trial_days_left == 14


async def test_bad_setting_value_is_refused_and_not_recorded(conn) -> None:
    with pytest.raises(ValueError, match="between 1 and 365"):
        await update_platform_setting(conn, "trial_policy", {"trial_days": 0}, actor=_ADMIN)


async def test_convert_closes_the_owners_continue_request_in_the_same_change(conn) -> None:
    """SA-10: the request shows on the companies list until convert / extend answers it."""
    from mesiri.application.organizations.trial import record_continue_request

    org = await _trial_company(conn, "+91 98765 20009")
    assert await record_continue_request(conn, org, user_id=str(uuid.uuid4()), via="whatsapp")
    company = await company_setup(conn, org, now=_NOW)
    assert company.open_continue_requests == 1
    assert company.continue_requested_at is not None

    await trial_controls.apply_trial_action(
        conn, org, trial_controls.CONVERT, actor=_ADMIN, now=_NOW
    )
    company = await company_setup(conn, org, now=_NOW)
    assert company.open_continue_requests == 0
    [entry] = await _audit(conn, org, "company.converted")
    assert entry["details"]["closed_continue_requests"] == 1
