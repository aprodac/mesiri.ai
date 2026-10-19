"""SS-05 end to end against a real Postgres: the owner asks for the join
code from their own WhatsApp context, a newcomer sends it, the owner is
asked with Approve / Reject (Meta mocked at the HTTP transport), and
Approve hands the person on to the contact-share steps.

Data is committed (the actor reader opens its own connection), so the
company is deleted again afterwards."""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import text

from backend.postgres.actor import PostgresActorReader
from channel.replies import ReplySpec
from channel.whatsapp.outbound import WhatsAppSender
from mesiri.application.organizations.create_company import NewCompany, create_company
from mesiri.bootstrap.settings import Settings
from mesiri.infrastructure.postgres.database import PostgresDatabase
from mesiri.infrastructure.redis.client import FakeRedis
from mesiri_contracts.assistant.enums import InputModality
from runtime import join_journey as jj

pytestmark = pytest.mark.integration

BUSINESS = "15550001111"


@pytest.fixture
async def world():
    db = PostgresDatabase(Settings().postgres)
    await db.connect()
    owner_wa = f"9198{uuid.uuid4().int % 10**8:08d}"
    async with db.transaction() as conn:
        created = await create_company(
            conn,
            NewCompany(
                name=f"Joinable Builders {uuid.uuid4().hex[:4]}",
                owner_name="Suresh",
                owner_phone=owner_wa,
                project_name="Green Towers",
                site_names=("Block A",),
            ),
        )
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"messages": [{"id": f"wamid.{uuid.uuid4().hex}"}]})

    sender = WhatsAppSender(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        access_token="token",
        phone_number_id="PHONE_NUMBER_ID",
    )
    joins: list[tuple] = []

    class _ContactShare:
        async def start_join(self, actor, *, name, phone, business_number):
            joins.append((actor.user_id, name, phone, business_number))
            return ReplySpec(text="*Confirm this action?* create user")

    journey = jj.JoinJourney(sender=sender, db=db, redis=FakeRedis(), contact_share=_ContactShare())
    yield SimpleNamespace(
        db=db, created=created, owner_wa=owner_wa, captured=captured, joins=joins, j=journey
    )
    async with db.transaction() as conn:
        org = created.organization_id
        await conn.execute(text("DELETE FROM organization_settings WHERE organization_id = :o"), {"o": org})
        await conn.execute(text("DELETE FROM admin_audit_log WHERE organization_id = :o"), {"o": org})
        await conn.execute(text("DELETE FROM organizations WHERE id = :o"), {"o": org})
    await db.disconnect()


def _message(text="", *, wa_id, profile=None, tap=None):
    return SimpleNamespace(
        modality=InputModality.TEXT,
        text=text,
        sender=SimpleNamespace(wa_id=wa_id, profile_name=profile),
        metadata={"interactive_reply_id": tap, "display_phone_number": BUSINESS},
    )


async def test_code_request_approve_end_to_end(world) -> None:
    owner = await PostgresActorReader().resolve_by_whatsapp_id(world.owner_wa)
    assert owner is not None

    # 1. The owner asks for the code; the message to forward carries the link.
    forward = await world.j.handle_code_request(_message("join code", wa_id=world.owner_wa), owner)
    code = forward.text.split("*JOIN ")[1].split("*")[0]
    assert f"https://wa.me/{BUSINESS}?text=JOIN%20{code}" in forward.text

    # 2. A newcomer sends it: the owner gets Approve / Reject on WhatsApp.
    newcomer = f"9197{uuid.uuid4().int % 10**8:08d}"
    reply = await world.j.handle_unregistered(
        _message(f"join {code.lower()}", wa_id=newcomer, profile="Ravi Kumar")
    )
    assert reply.startswith("Thanks Ravi!")
    [ask] = [c for c in world.captured if c.get("type") == "interactive"]
    assert ask["to"] == world.owner_wa
    approve_id = ask["interactive"]["action"]["buttons"][0]["reply"]["id"]
    assert approve_id.startswith(f"{jj.APPROVE_PREFIX}{world.created.organization_id}:")

    # 3. Approve, from the owner's own context: on to the contact-share steps.
    approved = await world.j.handle_tap(_message(tap=approve_id, wa_id=world.owner_wa), owner)
    assert approved.text.startswith("*Confirm this action?*")
    assert world.joins == [(owner.user_id, "Ravi Kumar", newcomer, BUSINESS)]

    # A second tap does nothing more.
    again = await world.j.handle_tap(_message(tap=approve_id, wa_id=world.owner_wa), owner)
    assert again.text == "That request was already approved."
    assert len(world.joins) == 1


async def test_a_replaced_code_stops_working(world) -> None:
    owner = await PostgresActorReader().resolve_by_whatsapp_id(world.owner_wa)
    first = await world.j.handle_code_request(_message("join code", wa_id=world.owner_wa), owner)
    old = first.text.split("*JOIN ")[1].split("*")[0]
    await world.j.handle_code_request(_message("new join code", wa_id=world.owner_wa), owner)

    reply = await world.j.handle_unregistered(
        _message(f"JOIN {old}", wa_id=f"9197{uuid.uuid4().int % 10**8:08d}", profile="Ravi")
    )
    assert reply == jj.WRONG_CODE
