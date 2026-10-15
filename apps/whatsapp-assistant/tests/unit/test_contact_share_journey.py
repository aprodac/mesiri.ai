"""SS-13: add a teammate by sharing their WhatsApp contact."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from backend.ports import ActorIdentity, ProjectSummary
from channel.replies import ReplySpec
from ingress.normalization import MessageNormalizer
from mesiri.infrastructure.redis.client import FakeRedis
from mesiri_contracts.assistant.draft_action import DraftActionType
from runtime import contact_share_journey as cs

ORG = str(uuid.uuid4())
P1 = ProjectSummary(id=str(uuid.uuid4()), name="Green Villa")
P2 = ProjectSummary(id=str(uuid.uuid4()), name="Lake View")


def _actor(role="ADMIN", projects=(P1,)) -> ActorIdentity:
    return ActorIdentity(
        user_id=str(uuid.uuid4()),
        full_name="Suresh",
        role=role,
        organization_id=ORG,
        org_name="Suresh Builders",
        org_active=True,
        projects=list(projects),
    )


def _card(*people, business="15550001111"):
    return SimpleNamespace(
        metadata={
            "raw_type": "contacts",
            "display_phone_number": business,
            "shared_contacts": [{"name": n, "phone": p} for n, p in people],
        }
    )


def _tap(reply_id):
    return SimpleNamespace(metadata={"interactive_reply_id": reply_id})


@pytest.fixture
def journey(monkeypatch):
    calls: dict = {"create_plan": [], "add_member": [], "existing": None}

    async def fake_plan(**kwargs):
        calls["create_plan"].append(kwargs)
        return ReplySpec(text="*Confirm this action?* create user")

    monkeypatch.setattr(cs, "start_member_create_plan", fake_plan)
    j = cs.ContactShareJourney(redis=FakeRedis(), db=None, plan_store=None, workflow_runtime=None)

    async def fake_find(phone):
        return calls["existing"]

    async def fake_add(actor, event):
        calls["add_member"].append(event)
        return ReplySpec(text="*Confirm this action?* add member")

    j._find_user = fake_find  # type: ignore[method-assign]
    j._start_add_member = fake_add  # type: ignore[method-assign]
    return SimpleNamespace(j=j, calls=calls)


# -- reading the card -----------------------------------------------------------


def test_normalizer_keeps_name_and_whatsapp_id() -> None:
    message = {
        "type": "contacts",
        "contacts": [
            {
                "name": {"formatted_name": "Biju Site", "first_name": "Biju"},
                "phones": [{"phone": "+91 98765 11122", "wa_id": "919876511122", "type": "CELL"}],
            },
            {
                "name": {"first_name": "Anil", "last_name": "K"},
                "phones": [{"phone": "98765 33344"}],
            },
            {"name": {"formatted_name": "No Number"}, "phones": []},
        ],
    }
    people = MessageNormalizer._resolve_shared_contacts(message)
    assert people == [
        {"name": "Biju Site", "phone": "919876511122"},
        {"name": "Anil K", "phone": "98765 33344"},
    ]


# -- starting the add -------------------------------------------------------------


async def test_new_number_starts_the_create_user_chain(journey) -> None:
    actor = _actor()
    reply = await journey.j.handle_contacts(_card(("Biju Site", "98765 11122")), actor)

    assert "create user" in reply.text
    call = journey.calls["create_plan"][0]
    assert call["name_hint"] == "Biju Site"
    assert call["whatsapp_number"] == "919876511122"
    event = call["original_event"]
    assert event.project_id == P1.id
    assert event.fields["role"] == "SITE_ENGINEER"
    assert event.fields["member_name"] == "Biju Site"


async def test_existing_teammate_is_just_added_to_the_project(journey) -> None:
    journey.calls["existing"] = SimpleNamespace(
        id=uuid.uuid4(), organization_id=ORG, full_name="Biju S"
    )
    reply = await journey.j.handle_contacts(_card(("Biju", "919876511122")), _actor())
    assert "add member" in reply.text
    assert journey.calls["create_plan"] == []
    assert journey.calls["add_member"][0].fields["member_name"] == "Biju S"


async def test_number_in_another_company_is_refused(journey) -> None:
    journey.calls["existing"] = SimpleNamespace(
        id=uuid.uuid4(), organization_id=str(uuid.uuid4()), full_name="X"
    )
    reply = await journey.j.handle_contacts(_card(("Biju", "919876511122")), _actor())
    assert reply.text == cs.OTHER_COMPANY
    assert journey.calls["create_plan"] == [] and journey.calls["add_member"] == []


@pytest.mark.parametrize("role", ["SITE_ENGINEER", "FINANCE", ""])
async def test_only_admins_and_pms_can_add(journey, role) -> None:
    reply = await journey.j.handle_contacts(_card(("Biju", "9876511122")), _actor(role=role))
    assert reply.text == cs.NOT_ALLOWED


async def test_bad_number_and_no_project(journey) -> None:
    assert (await journey.j.handle_contacts(_card(("Biju", "123")), _actor())).text == cs.NO_NUMBER
    reply = await journey.j.handle_contacts(_card(("Biju", "9876511122")), _actor(projects=()))
    assert reply.text == cs.NO_PROJECT


async def test_several_contacts_adds_the_first_and_says_so(journey) -> None:
    reply = await journey.j.handle_contacts(
        _card(("Biju", "9876511122"), ("Anil", "9876533344")), _actor()
    )
    assert "Share the others one at a time" in reply.text
    assert journey.calls["create_plan"][0]["whatsapp_number"] == "919876511122"


async def test_several_projects_asks_which_then_starts(journey) -> None:
    actor = _actor(projects=(P1, P2))
    picker = await journey.j.handle_contacts(_card(("Biju", "9876511122")), actor)
    assert [r.id for r in picker.list_rows] == [
        f"contact_project:{P1.id}",
        f"contact_project:{P2.id}",
    ]
    assert journey.calls["create_plan"] == []

    await journey.j.handle_project_tap(_tap(f"contact_project:{P2.id}"), actor)
    assert journey.calls["create_plan"][0]["original_event"].project_id == P2.id

    # The pick is used once.
    again = await journey.j.handle_project_tap(_tap(f"contact_project:{P2.id}"), actor)
    assert again.text == cs.EXPIRED


async def test_other_taps_are_not_ours(journey) -> None:
    assert await journey.j.handle_project_tap(_tap("setup_add_site"), _actor()) is None


# -- the invite ------------------------------------------------------------------


async def test_invite_after_the_member_is_added(journey) -> None:
    actor = _actor()
    await journey.j.handle_contacts(_card(("Biju Site", "9876511122")), actor)

    texts = await journey.j.invite_after_member_added(
        action_type=DraftActionType.ADD_PROJECT_MEMBER, member_name="biju  site", actor=actor
    )
    assert "can now report on *Green Villa*" in texts[0]
    assert "Hi biju, Suresh Builders uses Mesiri" in texts[1]
    assert "https://wa.me/15550001111?text=Hi" in texts[1]

    # Sent once.
    assert (
        await journey.j.invite_after_member_added(
            action_type=DraftActionType.ADD_PROJECT_MEMBER, member_name="Biju Site", actor=actor
        )
        == []
    )


async def test_no_invite_for_other_confirmations_or_people(journey) -> None:
    actor = _actor()
    await journey.j.handle_contacts(_card(("Biju Site", "9876511122")), actor)
    assert (
        await journey.j.invite_after_member_added(
            action_type=DraftActionType.CREATE_USER, member_name="Biju Site", actor=actor
        )
        == []
    )
    assert (
        await journey.j.invite_after_member_added(
            action_type=DraftActionType.ADD_PROJECT_MEMBER, member_name="Someone Else", actor=actor
        )
        == []
    )


async def test_invite_without_business_number_has_no_link(journey) -> None:
    actor = _actor()
    await journey.j.handle_contacts(_card(("Biju", "9876511122"), business=None), actor)
    texts = await journey.j.invite_after_member_added(
        action_type=DraftActionType.ADD_PROJECT_MEMBER, member_name="Biju", actor=actor
    )
    assert "wa.me" not in texts[1] and "Save this number" in texts[1]
