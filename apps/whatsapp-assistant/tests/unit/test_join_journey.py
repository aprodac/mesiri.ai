"""SS-05: joining a company with its code on WhatsApp."""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

import pytest

from backend.ports import ActorIdentity, ProjectSummary
from channel.replies import ReplySpec
from mesiri.application.organizations.team_join import Approver, Company
from mesiri.domains.organizations import team_join as rules
from mesiri.infrastructure.redis.client import FakeRedis
from mesiri_contracts.assistant.draft_action import DraftActionType
from mesiri_contracts.assistant.enums import InputModality
from runtime import contact_share_journey as cs
from runtime import join_journey as jj

ORG = uuid.uuid4()
NOW = dt.datetime(2026, 10, 19, 9, 0, tzinfo=dt.UTC)
NEWCOMER = "919876500001"


class _Sender:
    def __init__(self) -> None:
        self.texts: list[tuple[str, str]] = []
        self.buttons: list[tuple[str, str, list]] = []

    async def send_text(self, to, body):
        self.texts.append((to, body))

    async def send_button(self, to, *, body, buttons):
        self.buttons.append((to, body, buttons))


class _Db:
    def transaction(self):
        class _Tx:
            async def __aenter__(self):
                return "conn"

            async def __aexit__(self, *exc):
                return False

        return _Tx()


def _message(text="", *, wa_id=NEWCOMER, profile="Ravi Kumar", tap=None):
    return SimpleNamespace(
        modality=InputModality.TEXT,
        text=text,
        sender=SimpleNamespace(wa_id=wa_id, profile_name=profile),
        metadata={"interactive_reply_id": tap, "display_phone_number": "15550001111"},
    )


def _actor(role="ADMIN", org=ORG, projects=None) -> ActorIdentity:
    return ActorIdentity(
        user_id=str(uuid.uuid4()),
        full_name="Suresh",
        role=role,
        organization_id=str(org),
        org_name="Acme Builders",
        org_active=True,
        projects=projects if projects is not None else [ProjectSummary(id=str(uuid.uuid4()), name="Green Villa")],
    )


@pytest.fixture
def world(monkeypatch):
    """A fake store for the company's code and requests, in place of the
    database functions (their SQL is covered by the Postgres tests)."""
    state = {"code": "ACME-4821", "requests": [], "joins": []}

    async def company_for_code(conn, code):
        return Company(organization_id=ORG, name="Acme Builders") if code == state["code"] else None

    async def request_to_join(conn, org, *, phone, name, now):
        state["requests"], request, new = rules.add_request(
            state["requests"], phone=phone, name=name, now=now
        )
        return request, new

    async def decide_request(conn, org, *, request_id, approve, by, now):
        state["requests"], request, decided = rules.decide(
            state["requests"], request_id=request_id, approve=approve, by=by, now=now
        )
        return request, decided

    async def approvers(conn, org):
        return [Approver(user_id=uuid.uuid4(), name="Suresh", whatsapp_number="+91 98765 00099")]

    async def join_code(conn, org, *, rotate=False, now, updated_by=None):
        if rotate:
            state["code"] = "ACME-1111"
        return state["code"]

    for name, fn in (
        ("company_for_code", company_for_code),
        ("request_to_join", request_to_join),
        ("decide_request", decide_request),
        ("approvers", approvers),
        ("join_code", join_code),
    ):
        monkeypatch.setattr(jj.team_join, name, fn)

    class _ContactShare:
        async def start_join(self, actor, *, name, phone, business_number):
            state["joins"].append((name, phone, business_number))
            return ReplySpec(text="*Confirm this action?* create user")

    sender = _Sender()
    journey = jj.JoinJourney(
        sender=sender, db=_Db(), redis=FakeRedis(), contact_share=_ContactShare(), now=lambda: NOW
    )
    return SimpleNamespace(j=journey, sender=sender, state=state)


def _ref(world) -> str:
    return f"{ORG}:{world.state['requests'][-1]['id']}"


# -- the newcomer ---------------------------------------------------------------


async def test_a_join_message_asks_the_admins(world) -> None:
    reply = await world.j.handle_unregistered(_message("join acme 4821"))

    assert reply.startswith("Thanks Ravi! I've asked *Acme Builders*")
    [(to, body, buttons)] = world.sender.buttons
    assert to == "919876500099"
    assert "*Ravi Kumar* (+919876500001) wants to join *Acme Builders*" in body
    assert [b.title for b in buttons] == ["Approve", "Reject"]
    assert buttons[0].id == f"{jj.APPROVE_PREFIX}{_ref(world)}"


async def test_asking_again_sends_no_second_alert(world) -> None:
    await world.j.handle_unregistered(_message("JOIN ACME-4821"))
    reply = await world.j.handle_unregistered(_message("JOIN ACME-4821"))

    assert "already with them" in reply
    assert len(world.sender.buttons) == 1


async def test_wrong_codes_are_counted_and_then_refused(world) -> None:
    for _ in range(rules.MAX_WRONG_CODES_PER_DAY):
        assert await world.j.handle_unregistered(_message("JOIN ACME-0000")) == jj.WRONG_CODE
    # Even the right code is refused for the rest of the day.
    assert await world.j.handle_unregistered(_message("JOIN ACME-4821")) == jj.TOO_MANY_TRIES
    assert world.sender.buttons == []


async def test_with_no_profile_name_the_name_is_asked_first(world) -> None:
    first = await world.j.handle_unregistered(_message("JOIN ACME-4821", profile=None))
    assert first.startswith("Welcome! What's your name?")
    assert world.sender.buttons == []

    second = await world.j.handle_unregistered(_message("Biju", profile=None))
    assert second.startswith("Thanks Biju!")
    assert "*Biju* (+919876500001)" in world.sender.buttons[0][1]


async def test_other_messages_are_left_to_signup(world) -> None:
    assert await world.j.handle_unregistered(_message("hi")) is None
    assert await world.j.handle_unregistered(_message("I want to join")) is None


# -- the admin --------------------------------------------------------------------


async def test_approve_goes_on_through_the_contact_share_steps(world) -> None:
    await world.j.handle_unregistered(_message("JOIN ACME-4821"))

    reply = await world.j.handle_tap(_message(tap=f"{jj.APPROVE_PREFIX}{_ref(world)}"), _actor())

    assert reply.text.startswith("*Confirm this action?*")
    assert world.state["joins"] == [("Ravi Kumar", NEWCOMER, "15550001111")]
    assert world.state["requests"][-1]["status"] == rules.APPROVED


async def test_reject_tells_the_newcomer(world) -> None:
    await world.j.handle_unregistered(_message("JOIN ACME-4821"))
    world.sender.texts.clear()

    reply = await world.j.handle_tap(_message(tap=f"{jj.REJECT_PREFIX}{_ref(world)}"), _actor())

    assert reply.text == "Okay, *Ravi Kumar* won't be added."
    assert world.sender.texts == [(NEWCOMER, jj.REJECTED_NOTICE.format(company="Acme Builders"))]
    assert world.state["joins"] == []


async def test_only_this_companys_admin_can_decide_and_only_once(world) -> None:
    await world.j.handle_unregistered(_message("JOIN ACME-4821"))
    tap = _message(tap=f"{jj.APPROVE_PREFIX}{_ref(world)}")

    pm = await world.j.handle_tap(tap, _actor(role="PROJECT_MANAGER"))
    other_company = await world.j.handle_tap(tap, _actor(org=uuid.uuid4()))
    assert pm.text == other_company.text == jj.NOT_ALLOWED_TO_DECIDE
    assert world.state["requests"][-1]["status"] == rules.OPEN

    await world.j.handle_tap(tap, _actor())
    twice = await world.j.handle_tap(_message(tap=f"{jj.REJECT_PREFIX}{_ref(world)}"), _actor())
    assert twice.text == "That request was already approved."
    assert len(world.state["joins"]) == 1


async def test_other_taps_are_not_ours(world) -> None:
    assert await world.j.handle_tap(_message(tap="contact_project:x"), _actor()) is None


# -- sharing the code ------------------------------------------------------------


async def test_admin_gets_a_message_to_forward_with_the_link(world) -> None:
    reply = await world.j.handle_code_request(_message("Join code?", wa_id="919876500099"), _actor())

    assert "https://wa.me/15550001111?text=JOIN%20ACME-4821" in reply.text
    assert "*JOIN ACME-4821*" in reply.text
    [(to, intro)] = world.sender.texts
    assert to == "919876500099" and intro.startswith("Forward the next message")


async def test_new_join_code_replaces_it(world) -> None:
    reply = await world.j.handle_code_request(_message("new join code"), _actor(role="PROJECT_MANAGER"))

    assert "ACME-1111" in reply.text
    assert "The old code no longer works." in world.sender.texts[0][1]


async def test_a_site_engineer_cannot_share_the_code(world) -> None:
    reply = await world.j.handle_code_request(_message("join code"), _actor(role="SITE_ENGINEER"))
    assert reply.text == jj.NOT_ALLOWED_TO_SHARE
    assert await world.j.handle_code_request(_message("good morning"), _actor()) is None


# -- once added -------------------------------------------------------------------


async def test_the_newcomer_is_told_directly_once_added(monkeypatch) -> None:
    async def fake_plan(**kwargs):
        return ReplySpec(text="*Confirm this action?* create user")

    monkeypatch.setattr(cs, "start_member_create_plan", fake_plan)
    sent: list[tuple[str, str]] = []

    async def send_text(to, body):
        sent.append((to, body))

    share = cs.ContactShareJourney(
        redis=FakeRedis(), db=None, plan_store=None, workflow_runtime=None, send_text=send_text
    )

    async def nobody(phone):
        return None

    share._find_user = nobody  # type: ignore[method-assign]
    actor = _actor()
    await share.start_join(actor, name="Ravi Kumar", phone=NEWCOMER, business_number="15550001111")

    to_owner = await share.invite_after_member_added(
        action_type=DraftActionType.ADD_PROJECT_MEMBER, member_name="Ravi Kumar", actor=actor
    )

    assert to_owner == ["✅ *Ravi Kumar* can now report on *Green Villa*. I've told them they're in."]
    [(to, body)] = sent
    assert to == NEWCOMER
    assert body.startswith("✅ You're in, Ravi! *Acme Builders* added you to *Green Villa*")
