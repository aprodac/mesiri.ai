"""WA-09 against a real Postgres (integration): one invite per company and
number, never re-asked, and a reply answers every company that invited the
number. Each test runs in a transaction that is rolled back."""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import text

from mesiri.application.dpr import opt_in_invite
from mesiri.application.dpr.recipients import OPTED_IN, OPTED_OUT, WHATSAPP_REPLY, may_message
from mesiri.application.organizations.create_company import NewCompany, create_company
from mesiri.infrastructure.postgres.repositories.report_recipients import (
    PostgresReportRecipientRepository,
)

pytestmark = pytest.mark.integration

TODAY = dt.date(2026, 10, 16)
CLIENT = "919876500399"


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


async def _company(conn, name: str, phone: str):
    return await create_company(
        conn,
        NewCompany(name=name, owner_name="Owner", owner_phone=phone, project_name=f"{name} Towers"),
        now=dt.datetime.now(dt.UTC),
    )


async def _invites(conn, org) -> list[dict]:
    rows = await conn.execute(
        text("SELECT rule_key, recipient_user_id, payload FROM notifications WHERE organization_id = :o"),
        {"o": org},
    )
    return [dict(r) for r in rows.mappings().all()]


async def test_one_invite_per_company_and_number(conn) -> None:
    a = await _company(conn, "Alpha", "919876500301")
    queue = dict(organization_id=a.organization_id, project_id=a.project_id, phone=CLIENT, today=TODAY)

    assert await opt_in_invite.queue_invite(conn, **queue)
    assert not await opt_in_invite.queue_invite(conn, **queue)  # same day
    assert not await opt_in_invite.queue_invite(conn, **{**queue, "today": TODAY + dt.timedelta(days=3)})

    (invite,) = await _invites(conn, a.organization_id)
    assert invite["rule_key"] == f"dpr_optin:{CLIENT}"
    assert invite["recipient_user_id"] is None
    assert invite["payload"]["to_wa_id"] == CLIENT
    assert "Alpha would like to send you the daily progress report for Alpha Towers" in (
        invite["payload"]["message"]
    )
    # The invite itself passes the sender's consent check (it asks for consent)...
    assert may_message(consent_state=None, requires_opt_in=invite["payload"]["requires_opt_in"])[0]


async def test_never_asked_again_once_answered(conn) -> None:
    a = await _company(conn, "Alpha", "919876500302")
    await PostgresReportRecipientRepository(conn).record_consent(
        organization_id=a.organization_id, phone=CLIENT, state=OPTED_OUT, method=WHATSAPP_REPLY
    )
    assert not await opt_in_invite.queue_invite(
        conn, organization_id=a.organization_id, project_id=a.project_id, phone=CLIENT, today=TODAY
    )
    assert await _invites(conn, a.organization_id) == []


async def test_a_reply_answers_every_company_that_invited_the_number(conn) -> None:
    a = await _company(conn, "Alpha", "919876500303")
    b = await _company(conn, "Beta", "919876500304")
    c = await _company(conn, "Gamma", "919876500305")  # never invited this number
    for co in (a, b):
        await opt_in_invite.queue_invite(
            conn, organization_id=co.organization_id, project_id=co.project_id, phone=CLIENT, today=TODAY
        )
    repo = PostgresReportRecipientRepository(conn)

    answered = await opt_in_invite.record_answer(conn, phone=CLIENT, answer=opt_in_invite.YES)
    assert answered.state == OPTED_IN
    assert answered.companies == ["Alpha", "Beta"]
    for co in (a, b):
        assert await repo.latest_consent_state(organization_id=co.organization_id, phone=CLIENT) == OPTED_IN
    assert await repo.latest_consent_state(organization_id=c.organization_id, phone=CLIENT) is None

    stopped = await opt_in_invite.record_answer(conn, phone=CLIENT, answer=opt_in_invite.STOP)
    assert stopped.state == OPTED_OUT
    assert await repo.latest_consent_state(organization_id=a.organization_id, phone=CLIENT) == OPTED_OUT


async def test_a_number_nobody_invited_is_not_an_answer(conn) -> None:
    assert await opt_in_invite.record_answer(conn, phone="919876500398", answer=opt_in_invite.YES) is None


async def test_adding_a_contact_on_the_dashboard_queues_the_invite(conn) -> None:
    from mesiri.authorization.context import AuthorizationContext, ProjectAccessScope
    from mesiri.domains.dpr import router as dpr_router

    a = await _company(conn, "Alpha", "919876500306")
    auth = AuthorizationContext(
        user_id=a.owner_user_id,
        organization_id=a.organization_id,
        role="ADMIN",
        status="active",
        access_policy={},  # type: ignore[arg-type]
        project_scope=ProjectAccessScope(mode="all_projects", project_ids=set()),
    )
    added = await dpr_router.add_report_recipient(
        a.project_id,
        dpr_router.AddRecipientRequest(name="Client Rao", phone="+91 98765 00399"),
        auth_context=auth,
        conn=conn,
    )
    assert added["invite_queued"] is True
    # Agreed already (e.g. in the contract): no invite.
    other = await dpr_router.add_report_recipient(
        a.project_id,
        dpr_router.AddRecipientRequest(
            name="Architect", phone="919876500398", opted_in=True, opt_in_note="contract clause 12"
        ),
        auth_context=auth,
        conn=conn,
    )
    assert other["invite_queued"] is False
    assert [i["rule_key"] for i in await _invites(conn, a.organization_id)] == [f"dpr_optin:{CLIENT}"]
