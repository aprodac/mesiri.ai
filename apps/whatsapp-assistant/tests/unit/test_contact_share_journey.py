"""SS-13: add a teammate by sharing their WhatsApp contact."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from backend.ports import ActorIdentity, ProjectSummary
from ingress.normalization import MessageNormalizer
from mesiri.application.identity.add_by_number import AddedToProject, MemberNotAdded
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
        sender=SimpleNamespace(wa_id="15550009999"),
        metadata={
            "raw_type": "contacts",
            "display_phone_number": business,
            "shared_contacts": [{"name": n, "phone": p} for n, p in people],
        }
    )


def _tap(reply_id):
    return SimpleNamespace(metadata={"interactive_reply_id": reply_id})


async def _share(j, card, actor, role="SITE_ENGINEER"):
    """Share the card and answer the role question (WA-67)."""
    asked = await j.handle_contacts(card, actor)
    if not asked.buttons:
        return asked
    return await j.handle_project_tap(_tap(f"contact_role:{role}"), actor)


@pytest.fixture
def journey():
    calls: dict = {"add": [], "notes": [], "sent": [], "refuse": None, "already": False, "created": True}

    async def send_text(to, body):
        calls["sent"].append((to, body))

    j = cs.ContactShareJourney(
        redis=FakeRedis(), db=None, plan_store=None, workflow_runtime=None, send_text=send_text
    )

    async def fake_add(actor, phone, name, role, project_id):
        calls["add"].append({"phone": phone, "name": name, "role": role, "project_id": project_id})
        if calls["refuse"]:
            raise MemberNotAdded(calls["refuse"])
        return AddedToProject(uuid.uuid4(), name, calls["created"], calls["already"])

    async def fake_note(actor, pending, **step):
        calls["notes"].append((pending.get("join_request_id"), step))

    j._add = fake_add  # type: ignore[method-assign]
    j._note_join_step = fake_note  # type: ignore[method-assign]
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


async def test_role_then_one_project_adds_them_at_once(journey) -> None:
    """Two taps are the confirmation: no Confirm card after them."""
    actor = _actor()
    reply = await _share(journey.j, _card(("Biju Site", "98765 11122")), actor)

    assert journey.calls["add"] == [
        {"phone": "919876511122", "name": "Biju Site", "role": "SITE_ENGINEER", "project_id": P1.id}
    ]
    # The line to the owner first, then the invite on its own to forward.
    assert journey.calls["sent"] == [
        ("15550009999", "✅ *Biju Site* can now report on *Green Villa*. Forward the next message to them so they can start:")
    ]
    assert reply.text.startswith("Hi Biju, Suresh Builders uses Mesiri")
    assert "https://wa.me/15550001111?text=Hi" in reply.text
    assert not reply.buttons


async def test_number_in_another_company_is_refused(journey) -> None:
    journey.calls["refuse"] = "That number is already used by someone in another company on Mesiri"
    reply = await _share(journey.j, _card(("Biju", "919876511122")), _actor())
    assert reply.text == cs.OTHER_COMPANY


async def test_other_refusals_are_said_plainly(journey) -> None:
    journey.calls["refuse"] = "Only an admin can give someone the admin or finance role"
    reply = await _share(journey.j, _card(("Biju", "919876511122")), _actor())
    assert reply.text == "I couldn't add *Biju*: only an admin can give someone the admin or finance role."


async def test_already_on_the_project_says_so(journey) -> None:
    journey.calls["already"] = True
    reply = await _share(journey.j, _card(("Biju", "919876511122")), _actor())
    assert reply.text == "*Biju* is already on *Green Villa*."
    assert journey.calls["sent"] == []


@pytest.mark.parametrize("role", ["SITE_ENGINEER", "FINANCE", ""])
async def test_only_admins_and_pms_can_add(journey, role) -> None:
    reply = await journey.j.handle_contacts(_card(("Biju", "9876511122")), _actor(role=role))
    assert reply.text == cs.NOT_ALLOWED


async def test_bad_number_and_no_project(journey) -> None:
    assert (await journey.j.handle_contacts(_card(("Biju", "123")), _actor())).text == cs.NO_NUMBER
    reply = await journey.j.handle_contacts(_card(("Biju", "9876511122")), _actor(projects=()))
    assert reply.text == cs.NO_PROJECT


async def test_several_contacts_adds_the_first_and_says_so(journey) -> None:
    actor = _actor()
    asked = await journey.j.handle_contacts(_card(("Biju", "9876511122"), ("Anil", "9876533344")), actor)
    assert "Share the others one at a time" in asked.text
    await journey.j.handle_project_tap(_tap("contact_role:SITE_ENGINEER"), actor)
    assert journey.calls["add"][0]["phone"] == "919876511122"


async def test_several_projects_asks_which_then_starts(journey) -> None:
    actor = _actor(projects=(P1, P2))
    picker = await _share(journey.j, _card(("Biju", "9876511122")), actor)
    assert picker.text == "Which project should *Biju* (Site Engineer) work on?"
    assert [r.id for r in picker.list_rows] == [
        f"contact_project:{P1.id}",
        f"contact_project:{P2.id}",
    ]
    assert journey.calls["add"] == []

    await journey.j.handle_project_tap(_tap(f"contact_project:{P2.id}"), actor)
    assert journey.calls["add"][0]["project_id"] == P2.id

    # The pick is used once.
    again = await journey.j.handle_project_tap(_tap(f"contact_project:{P2.id}"), actor)
    assert again.text == cs.EXPIRED


async def test_the_role_question_offers_what_the_sender_may_give(journey) -> None:
    # WA-67 (audit SET-06): a shared card is no longer always a Site Engineer.
    admin_q = await journey.j.handle_contacts(_card(("Biju", "9876511122")), _actor())
    assert [b.id for b in admin_q.buttons] == [
        "contact_role:SITE_ENGINEER",
        "contact_role:PROJECT_MANAGER",
        "contact_role:ADMIN",
    ]
    assert journey.calls["add"] == []
    pm = _actor(role="PROJECT_MANAGER")
    pm_q = await journey.j.handle_contacts(_card(("Biju", "9876511122")), pm)
    assert [b.title for b in pm_q.buttons] == ["Site Engineer", "Project Manager"]


async def test_the_chosen_role_is_what_the_person_gets(journey) -> None:
    await _share(journey.j, _card(("Biju", "9876511122")), _actor(), role="PROJECT_MANAGER")
    assert journey.calls["add"][0]["role"] == "PROJECT_MANAGER"


async def test_a_pm_cannot_tap_their_way_to_admin(journey) -> None:
    pm = _actor(role="PROJECT_MANAGER")
    reply = await _share(journey.j, _card(("Biju", "9876511122")), pm, role="ADMIN")
    assert reply.text == cs.NOT_ALLOWED
    assert journey.calls["add"] == []


async def test_a_late_role_tap_is_expired(journey) -> None:
    reply = await journey.j.handle_project_tap(_tap("contact_role:SITE_ENGINEER"), _actor())
    assert reply.text == cs.EXPIRED


async def test_other_taps_are_not_ours(journey) -> None:
    assert await journey.j.handle_project_tap(_tap("setup_add_site"), _actor()) is None


# -- the invite ------------------------------------------------------------------


async def test_invite_without_business_number_has_no_link(journey) -> None:
    reply = await _share(journey.j, _card(("Biju", "9876511122"), business=None), _actor())
    assert "wa.me" not in reply.text and "Save this number" in reply.text


async def test_no_invite_for_other_confirmations(journey) -> None:
    assert (
        await journey.j.invite_after_member_added(
            action_type=DraftActionType.CREATE_USER, member_name="Biju Site", actor=_actor(), project_id=P1.id
        )
        == []
    )


# -- someone who asked to join (SS-05) ----------------------------------------------


async def test_an_approved_joiner_is_asked_role_then_told_they_are_in(journey) -> None:
    actor = _actor(projects=(P1, P2))
    asked = await journey.j.start_join(
        actor, name="Ravi Kumar", phone="919811122233", business_number="15550001111", request_id="r1"
    )
    assert asked.text == "👍 Approved. What will *Ravi Kumar* do?"
    assert [b.title for b in asked.buttons] == ["Site Engineer", "Project Manager", "Admin"]

    picker = await journey.j.handle_project_tap(_tap("contact_role:PROJECT_MANAGER"), actor)
    assert picker.text == "Which project should *Ravi Kumar* (Project Manager) work on?"
    done = await journey.j.handle_project_tap(_tap(f"contact_project:{P2.id}"), actor)

    assert journey.calls["add"][0] == {
        "phone": "919811122233", "name": "Ravi Kumar", "role": "PROJECT_MANAGER", "project_id": P2.id,
    }
    assert done.text == "✅ *Ravi Kumar* is in: Project Manager on *Lake View*. I've told them."
    [(to, body)] = journey.calls["sent"]
    assert to == "919811122233"
    assert body.startswith("✅ You're in, Ravi! *Suresh Builders* added you to *Lake View* on Mesiri as Project Manager.")
    # Each step is noted on the request, for the Live screen.
    assert journey.calls["notes"] == [
        ("r1", {"role": "PROJECT_MANAGER"}),
        ("r1", {"project": "Lake View", "joined": True}),
    ]


async def test_a_joiner_with_no_project_to_go_to(journey) -> None:
    reply = await journey.j.start_join(
        _actor(projects=()), name="Ravi", phone="919811122233", business_number="", request_id="r1"
    )
    assert reply.text == cs.NO_PROJECT


async def test_typed_add_gets_the_same_invite_as_a_shared_contact(journey) -> None:
    """SET-04: "add Rajesh 98... as engineer" ends with ADDED + the invite link."""
    actor = _actor()
    texts = await journey.j.invite_after_member_added(
        action_type=DraftActionType.ADD_PROJECT_MEMBER,
        member_name="Rajesh",
        actor=actor,
        project_id=P1.id,
        business_number="+1 555 000 1111",
    )
    assert "*Rajesh* can now report on *Green Villa*" in texts[0]
    assert "Hi Rajesh, Suresh Builders uses Mesiri" in texts[1]
    assert "https://wa.me/15550001111?text=Hi" in texts[1]


async def test_typed_add_without_a_known_project_sends_nothing(journey) -> None:
    assert (
        await journey.j.invite_after_member_added(
            action_type=DraftActionType.ADD_PROJECT_MEMBER,
            member_name="Rajesh",
            actor=_actor(),
            project_id="not-a-project",
        )
        == []
    )
