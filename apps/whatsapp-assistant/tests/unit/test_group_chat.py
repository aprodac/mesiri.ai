"""WA-87: Mesiri inside a site's WhatsApp group (runtime/group_chat.py)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from runtime.group_chat import (
    ALLOW_PREFIX,
    DENY_PREFIX,
    GroupChat,
    GroupReplySender,
    current_turn,
    parse_group_events,
)

ORG = "00000000-0000-0000-0000-0000000000a1"
OTHER_ORG = "00000000-0000-0000-0000-0000000000b2"
PROJECT = "00000000-0000-0000-0000-0000000000c3"
SITE_A = "00000000-0000-0000-0000-0000000000d4"
SITE_B = "00000000-0000-0000-0000-0000000000e5"
OWNER = "00000000-0000-0000-0000-0000000000f6"
ENGINEER = "00000000-0000-0000-0000-0000000000f7"
GROUP_WA = "120363000000000001"


# -- fakes ---------------------------------------------------------------------


class FakeGroups:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.requests: dict[str, dict[str, Any]] = {}
        self.team = [
            {"user_id": OWNER, "name": "Anil Kumar", "wa_id": "919800000001", "role": "ADMIN"},
            {"user_id": ENGINEER, "name": "Ravi", "wa_id": "919800000002", "role": "SITE_ENGINEER"},
        ]
        self.sites = [
            {"site_id": SITE_A, "site_name": "Block A", "project_id": PROJECT, "project_name": "Green Villa"},
            {"site_id": SITE_B, "site_name": "Block B", "project_id": PROJECT, "project_name": "Green Villa"},
        ]
        self.super_admins = {"919999999999": {"user_id": "sa-1", "name": "Ops"}}

    def _full(self, row: dict[str, Any]) -> dict[str, Any]:
        site = next(s for s in self.sites if s["site_id"] == row["site_id"])
        return {**row, "site_name": site["site_name"], "org_name": "Alpha Builders"}

    async def start(self, *, organization_id, project_id, site_id, subject, created_by_user_id):
        if any(r["site_id"] == site_id and r["status"] in ("creating", "active") for r in self.rows.values()):
            return None
        row_id = str(uuid.uuid4())
        self.rows[row_id] = {
            "id": row_id, "organization_id": organization_id, "project_id": project_id, "site_id": site_id,
            "subject": subject, "created_by_user_id": created_by_user_id, "status": "creating",
            "wa_group_id": None, "create_request_id": None, "invite_link": None,
        }
        return self._full(self.rows[row_id])

    async def live_for_site(self, *, organization_id, site_id):
        for r in self.rows.values():
            if r["site_id"] == site_id and r["status"] in ("creating", "active"):
                return self._full(r)
        return None

    async def update(self, group_id, **values):
        self.rows[group_id].update({k: v for k, v in values.items()})

    async def by_wa_group_id(self, wa_group_id):
        row = next((r for r in self.rows.values() if r["wa_group_id"] == wa_group_id), None)
        return self._full(row) if row else None

    async def by_request_id(self, request_id):
        row = next((r for r in self.rows.values() if r["create_request_id"] == request_id), None)
        return self._full(row) if row else None

    async def creating_by_subject(self, subject):
        rows = [r for r in self.rows.values() if r["subject"] == subject and r["status"] == "creating"]
        return self._full(rows[-1]) if rows else None

    async def by_id(self, group_id):
        return self._full(self.rows[group_id]) if group_id in self.rows else None

    async def site_team(self, *, organization_id, site_id):
        return list(self.team)

    async def company_sites(self, *, organization_id):
        return list(self.sites)

    async def companies(self):
        return [
            {"organization_id": ORG, "name": "Alpha Builders"},
            {"organization_id": OTHER_ORG, "name": "Beta Homes"},
        ]

    async def is_super_admin(self, wa_id):
        return self.super_admins.get(wa_id)

    async def record_join_request(self, *, group, join_request_id, wa_id, status):
        if any(r["group_id"] == group["id"] and r["join_request_id"] == join_request_id for r in self.requests.values()):
            return None
        row_id = str(uuid.uuid4())
        self.requests[row_id] = {
            "id": row_id, "organization_id": group["organization_id"], "group_id": group["id"],
            "join_request_id": join_request_id, "wa_id": wa_id, "status": status,
        }
        return dict(self.requests[row_id])

    async def join_request(self, request_row_id):
        row = self.requests.get(request_row_id)
        return dict(row) if row else None

    async def decide_join_request(self, request_row_id, *, status, user_id):
        row = self.requests[request_row_id]
        if row["status"] != "pending":
            return False
        row["status"] = status
        return True


class FakeClient:
    def __init__(self, answer: dict[str, Any] | None = None, approve_ok: bool = True) -> None:
        self.answer = {"request_id": "req-1"} if answer is None else answer
        self.refuse = False
        self.approve_ok = approve_ok
        self.created: list[str] = []
        self.approved: list[tuple[str, list[str]]] = []
        self.rejected: list[tuple[str, list[str]]] = []

    async def create_group(self, subject, *, description=None):
        self.created.append(subject)
        return None if self.refuse else dict(self.answer)

    async def invite_link(self, group_id):
        return "https://chat.whatsapp.com/Fetched"

    async def approve_join_requests(self, group_id, ids):
        self.approved.append((group_id, ids))
        return self.approve_ok

    async def reject_join_requests(self, group_id, ids):
        self.rejected.append((group_id, ids))
        return True


class FakeSender:
    def __init__(self, fail_to: set[str] | None = None) -> None:
        self.sent: list[tuple[str, str, Any]] = []
        self.fail_to = fail_to or set()

    async def send_text(self, to, body):
        self.sent.append(("text", to, body))
        return to not in self.fail_to

    async def send_reaction(self, to, message_id, emoji="✅"):
        self.sent.append(("reaction", to, message_id))
        return True

    async def send_button(self, to, **kwargs):
        self.sent.append(("button", to, kwargs))
        return to not in self.fail_to


class FakeOutbox:
    def __init__(self) -> None:
        self.sent: list[tuple[str, list[dict[str, Any]]]] = []

    async def send(self, group, *, kind, messages):
        self.sent.append((kind, messages))
        return {}


class FakeActors:
    def __init__(self, actors: dict[str, Any]) -> None:
        self.actors = actors

    async def resolve_by_whatsapp_id(self, wa_id):
        return self.actors.get(wa_id)


class FakeWorkSite:
    def __init__(self) -> None:
        self.preselected: list[tuple[str, str | None, str]] = []

    async def preselect(self, actor, *, project_id, site_id):
        self.preselected.append((actor.user_id, project_id, site_id))


def _actor(user_id: str, *, role: str = "SITE_ENGINEER", org: str = ORG, sites: tuple[str, ...] = (SITE_A,)):
    return SimpleNamespace(
        user_id=user_id, role=role, organization_id=org, org_name="Alpha Builders", org_active=True,
        full_name="Ravi Menon", sites=[SimpleNamespace(id=s, project_id=PROJECT) for s in sites],
    )


def _chat(**overrides: Any) -> tuple[GroupChat, dict[str, Any]]:
    parts: dict[str, Any] = {
        "groups": FakeGroups(),
        "client": FakeClient(),
        "sender": FakeSender(),
        "actor_reader": FakeActors({
            "919800000001": _actor(OWNER, role="ADMIN", sites=(SITE_A, SITE_B)),
            "919800000002": _actor(ENGINEER),
        }),
        "outbox": FakeOutbox(),
        "work_site": FakeWorkSite(),
    }
    parts.update(overrides)
    return GroupChat(enabled=True, lookup_retry_seconds=0, **parts), parts


def _message(text: str = "", *, wa_id: str = "919800000001", metadata: dict[str, Any] | None = None):
    return SimpleNamespace(
        text=text, metadata=metadata or {}, sender=SimpleNamespace(wa_id=wa_id), message_id="wamid.in.1",
    )


async def _active_group(chat: GroupChat, parts: dict[str, Any]) -> dict[str, Any]:
    await chat.create_for_site(
        organization_id=ORG, org_name="Alpha Builders", project_id=PROJECT, site_id=SITE_A,
        site_name="Block A", created_by_user_id=OWNER,
    )
    await chat.handle_event(
        "group_lifecycle_update",
        {"groups": [{"type": "group_create", "request_id": "req-1", "group_id": GROUP_WA,
                     "invite_link": "https://chat.whatsapp.com/Ab"}]},
    )
    return await parts["groups"].by_wa_group_id(GROUP_WA)


# -- Meta's webhooks -----------------------------------------------------------


def test_parse_lifecycle_and_join_request_events() -> None:
    created, failed = parse_group_events(
        "group_lifecycle_update",
        {"groups": [
            {"type": "group_create", "group_id": "g1", "request_id": "r1", "invite_link": "https://chat.whatsapp.com/x"},
            {"type": "group_create", "request_id": "r2", "errors": [{"code": 131000}]},
        ]},
    )
    assert (created.kind, created.group_id, created.request_id, created.invite_link) == (
        "created", "g1", "r1", "https://chat.whatsapp.com/x",
    )
    assert failed.kind == "create_failed"
    (deleted,) = parse_group_events("group_lifecycle_update", {"type": "group_delete", "group_id": "g1"})
    assert deleted.kind == "deleted"

    first, second = parse_group_events(
        "group_participants_update",
        {"groups": [{"type": "group_join_request_created", "group_id": "g1", "join_requests": [
            {"join_request_id": "jr1", "wa_id": "919800000009"}, {"join_request_id": "jr2", "wa_id": "9198"},
        ]}]},
    )
    assert (first.kind, first.group_id, first.join_request_id, first.wa_id) == ("join_request", "g1", "jr1", "919800000009")
    assert second.join_request_id == "jr2"
    (revoked,) = parse_group_events(
        "group_participants_update", {"type": "group_join_request_revoked", "group_id": "g1"}
    )
    assert revoked.kind == "other"
    assert parse_group_events("group_settings_update", {"group_id": "g1"})[0].kind == "other"


# -- creating a group ----------------------------------------------------------


async def test_create_sends_invites_once_meta_names_the_group() -> None:
    chat, parts = _chat()
    result = await chat.create_for_site(
        organization_id=ORG, org_name="Alpha Builders", project_id=PROJECT, site_id=SITE_A,
        site_name="Block A", created_by_user_id=OWNER,
    )
    assert result.status == "creating"
    assert parts["client"].created == ["Block A · Mesiri"]
    row = next(iter(parts["groups"].rows.values()))
    assert row["create_request_id"] == "req-1" and row["status"] == "creating"
    assert parts["outbox"].sent == []  # nothing until Meta names the group

    await chat.handle_event(
        "group_lifecycle_update",
        {"groups": [{"type": "group_create", "request_id": "req-1", "group_id": GROUP_WA,
                     "invite_link": "https://chat.whatsapp.com/Ab"}]},
    )
    assert row["status"] == "active" and row["wa_group_id"] == GROUP_WA
    welcome = parts["sender"].sent[0]
    assert welcome[:2] == ("text", f"group:{GROUP_WA}") and "Block A" in welcome[2]
    ((kind, messages),) = parts["outbox"].sent
    assert kind == "group_invite"
    invite, creator = messages
    assert invite["user_id"] == ENGINEER  # the creator gets their own message instead
    assert invite["template"] == {
        "name": "mesiri_group_invite",
        "body_params": ["Ravi", "Alpha Builders", "Block A", "https://chat.whatsapp.com/Ab"],
    }
    assert invite["message"].endswith("Join: https://chat.whatsapp.com/Ab")
    assert creator["user_id"] == OWNER and "Forward this link" in creator["message"]

    # The same webhook again sends nothing twice.
    await chat.handle_event(
        "group_lifecycle_update",
        {"groups": [{"type": "group_create", "request_id": "req-1", "group_id": GROUP_WA,
                     "invite_link": "https://chat.whatsapp.com/Ab"}]},
    )
    assert len(parts["outbox"].sent) == 1 and len(parts["sender"].sent) == 1


async def test_create_when_meta_names_the_group_at_once_and_when_it_refuses() -> None:
    chat, parts = _chat(client=FakeClient({"group_id": GROUP_WA}))
    assert (await chat.create_for_site(
        organization_id=ORG, org_name="A", project_id=PROJECT, site_id=SITE_A, site_name="Block A", created_by_user_id=OWNER,
    )).status == "creating"
    row = next(iter(parts["groups"].rows.values()))
    assert row["status"] == "active" and row["invite_link"] == "https://chat.whatsapp.com/Fetched"

    # The site has its group: a second create makes nothing.
    again = await chat.create_for_site(
        organization_id=ORG, org_name="A", project_id=PROJECT, site_id=SITE_A, site_name="Block A", created_by_user_id=OWNER,
    )
    assert again.status == "exists" and again.group["invite_link"].endswith("Fetched")

    refused = FakeClient()
    refused.refuse = True
    chat, parts = _chat(client=refused)
    result = await chat.create_for_site(
        organization_id=ORG, org_name="A", project_id=PROJECT, site_id=SITE_B, site_name="Block B", created_by_user_id=OWNER,
    )
    assert result.status == "failed"
    assert next(iter(parts["groups"].rows.values()))["status"] == "failed"


async def test_switched_off_creates_nothing() -> None:
    chat, parts = _chat()
    chat.enabled = False
    result = await chat.create_for_site(
        organization_id=ORG, org_name="A", project_id=PROJECT, site_id=SITE_A, site_name="Block A", created_by_user_id=OWNER,
    )
    assert result.status == "disabled" and parts["client"].created == []
    assert await chat.handle_private(_message("make a group for Block A"), _actor(OWNER, role="ADMIN")) is None


# -- joining -------------------------------------------------------------------


async def test_a_team_member_is_let_in_and_anyone_else_waits_for_the_owner() -> None:
    chat, parts = _chat()
    await _active_group(chat, parts)
    await chat.handle_event(
        "group_participants_update",
        {"type": "group_join_request_created", "group_id": GROUP_WA,
         "join_requests": [{"join_request_id": "jr-team", "wa_id": "919800000002"}]},
    )
    assert parts["client"].approved == [(GROUP_WA, ["jr-team"])]

    await chat.handle_event(
        "group_participants_update",
        {"type": "group_join_request_created", "group_id": GROUP_WA,
         "join_requests": [{"join_request_id": "jr-client", "wa_id": "919811111111"}]},
    )
    assert len(parts["client"].approved) == 1  # the client is not let in by itself
    kind, (ask,) = parts["outbox"].sent[-1]
    assert kind == "group_join" and ask["user_id"] == OWNER
    assert "+919811111111" in ask["message"]
    allow, deny = ask["buttons"]
    assert allow["id"].startswith(ALLOW_PREFIX) and deny["id"].startswith(DENY_PREFIX)

    # Delivered twice: asked once.
    await chat.handle_event(
        "group_participants_update",
        {"type": "group_join_request_created", "group_id": GROUP_WA,
         "join_requests": [{"join_request_id": "jr-client", "wa_id": "919811111111"}]},
    )
    assert sum(1 for k, _ in parts["outbox"].sent if k == "group_join") == 1

    # The engineer can't decide; the owner can, once.
    tap = {"interactive_reply_id": allow["id"]}
    refused = await chat.handle_private(_message(wa_id="919800000002", metadata=tap), _actor(ENGINEER))
    assert "Only the company owner" in refused
    owner = _actor(OWNER, role="ADMIN", sites=(SITE_A, SITE_B))
    assert "can join" in await chat.handle_private(_message(metadata=tap), owner)
    assert parts["client"].approved[-1] == (GROUP_WA, ["jr-client"])
    assert "answered already" in await chat.handle_private(_message(metadata=tap), owner)


async def test_dont_allow_and_a_full_group() -> None:
    chat, parts = _chat(client=FakeClient(approve_ok=False))
    group = await _active_group(chat, parts)
    stored = await parts["groups"].record_join_request(group=group, join_request_id="jr-9", wa_id="919822222222", status="pending")
    owner = _actor(OWNER, role="ADMIN", sites=(SITE_A, SITE_B))
    full = await chat.handle_private(_message(metadata={"interactive_reply_id": ALLOW_PREFIX + stored["id"]}), owner)
    assert "may be full" in full
    assert parts["groups"].requests[stored["id"]]["status"] == "pending"
    denied = await chat.handle_private(_message(metadata={"interactive_reply_id": DENY_PREFIX + stored["id"]}), owner)
    assert "won't be let" in denied
    assert parts["client"].rejected == [(GROUP_WA, ["jr-9"])]
    gone = await chat.handle_private(_message(metadata={"interactive_reply_id": ALLOW_PREFIX + "nope"}), owner)
    assert "isn't there" in gone


# -- "make a group for <site>" -------------------------------------------------


async def test_the_create_command() -> None:
    chat, parts = _chat()
    owner = _actor(OWNER, role="ADMIN", sites=(SITE_A, SITE_B))
    assert await chat.handle_private(_message("how many workers today"), owner) is None

    engineer_reply = await chat.handle_private(_message("make a group for Block A", wa_id="919800000002"), _actor(ENGINEER))
    assert "Only the company owner" in engineer_reply and parts["client"].created == []

    which = await chat.handle_private(_message("make a group for Block"), owner)
    assert which.startswith("Which site?") and "Block A" in which and "Block B" in which

    made = await chat.handle_private(_message("Create a WhatsApp group for block a."), owner)
    assert made.startswith("Making the WhatsApp group for Block A")
    assert parts["client"].created == ["Block A · Mesiri"]

    exists = await chat.handle_private(_message("make a group for Block A"), owner)
    assert "has a WhatsApp group already" in exists

    # Not a group message: a group's own text is never a command.
    assert await chat.handle_private(_message("make a group for Block B", metadata={"group_id": GROUP_WA}), owner) is None


async def test_a_super_admin_names_the_company() -> None:
    chat, parts = _chat()
    # Not a super admin and in no company: the usual reply for a stranger.
    assert await chat.handle_private(_message("make a group for Alpha Builders, Block A", wa_id="917000000000"), None) is None

    made = await chat.handle_private(_message("make a group for Alpha Builders, Block B", wa_id="919999999999"), None)
    assert made.startswith("Making the WhatsApp group for Block B")
    row = next(iter(parts["groups"].rows.values()))
    assert row["organization_id"] == ORG and row["site_id"] == SITE_B and row["created_by_user_id"] == "sa-1"

    no_comma = await chat.handle_private(_message("make a group for Alpha Builders Block A", wa_id="919999999999"), None)
    assert no_comma.startswith("Making the WhatsApp group for Block A")

    unknown = await chat.handle_private(_message("make a group for Gamma, Block A", wa_id="919999999999"), None)
    assert "couldn't find that company" in unknown


# -- a group message -----------------------------------------------------------


async def test_only_the_site_team_is_heard_in_the_group() -> None:
    chat, parts = _chat()
    parts["actor_reader"].actors["919833333333"] = _actor("other-site", sites=(SITE_B,))
    parts["actor_reader"].actors["919844444444"] = _actor("other-co", org=OTHER_ORG)
    await _active_group(chat, parts)
    seen: list[tuple[str, Any]] = []

    async def inner(message, raw, retry=None):
        seen.append((message.sender.wa_id, current_turn()))

    handler = chat.wrap(inner)
    group = {"group_id": GROUP_WA}
    for outsider in ("919811111111", "919833333333", "919844444444"):
        await handler(_message("10 masons today", wa_id=outsider, metadata=group), {})
    await handler(_message("10 masons", wa_id="919800000002", metadata={"group_id": "unknown-group"}), {})
    assert seen == []

    seen_marks = [s for s in parts["sender"].sent if s[0] == "reaction"]
    assert seen_marks == []  # outsiders get no sign either

    await handler(_message("10 masons today", wa_id="919800000002", metadata=group), {})
    assert [s for s in parts["sender"].sent if s[0] == "reaction"] == [("reaction", f"group:{GROUP_WA}", "wamid.in.1")]
    ((wa_id, turn),) = seen
    assert wa_id == "919800000002" and turn.group_wa_id == GROUP_WA and turn.first_name == "Ravi"
    assert parts["work_site"].preselected == [(ENGINEER, PROJECT, SITE_A)]
    assert current_turn() is None  # reset after the message

    # A 1-on-1 message passes straight through.
    await handler(_message("hi", wa_id="919800000002"), {})
    assert seen[-1] == ("919800000002", None)


async def test_the_check_mark_goes_into_the_group_and_replies_stay_private() -> None:
    chat, parts = _chat()
    await _active_group(chat, parts)
    raw = FakeSender(fail_to={"919800000002"})
    sender = GroupReplySender(raw)

    async def inner(message, _raw, retry=None):
        await sender.send_reaction(message.sender.wa_id, message.message_id, "✅")
        await sender.send_text(message.sender.wa_id, "Saved: 10 masons")
        await sender.send_button(message.sender.wa_id, body="Save?", buttons=[])

    await chat.wrap(inner)(_message("10 masons", wa_id="919800000002", metadata={"group_id": GROUP_WA}), {})
    reaction, private_text, nudge, private_card = raw.sent
    assert reaction == ("reaction", f"group:{GROUP_WA}", "wamid.in.1")
    assert private_text[:2] == ("text", "919800000002")
    # Meta refused the private reply: one line in the group, not one per send.
    assert nudge[:2] == ("text", f"group:{GROUP_WA}") and nudge[2].startswith("Ravi,")
    assert private_card[:2] == ("button", "919800000002")

    # Outside a group message the wrapper changes nothing.
    raw.sent.clear()
    await sender.send_reaction("919800000002", "wamid.x")
    await sender.send_text("919800000002", "hi")
    assert [s[1] for s in raw.sent] == ["919800000002", "919800000002"]


@pytest.fixture(autouse=True)
def _no_tenant_scope(monkeypatch):
    """The super admin path binds the named company; nothing to bind here."""
    import contextlib

    import mesiri.infrastructure.postgres.tenant as tenant

    monkeypatch.setattr(tenant, "tenant_scope", lambda *_a, **_k: contextlib.nullcontext())


async def test_a_created_event_that_beats_the_stored_request_id() -> None:
    """Meta's webhook can arrive before Meta's answer to the create call was
    stored: found again a moment later, or by the group's name."""
    chat, parts = _chat(client=FakeClient({}))  # Meta's answer names nothing
    await chat.create_for_site(
        organization_id=ORG, org_name="Alpha Builders", project_id=PROJECT, site_id=SITE_A,
        site_name="Block A", created_by_user_id=OWNER,
    )
    await chat.handle_event(
        "group_lifecycle_update",
        {"groups": [{"type": "group_create", "request_id": "unknown", "group_id": GROUP_WA,
                     "subject": "Block A · Mesiri", "invite_link": "https://chat.whatsapp.com/Ab"}]},
    )
    row = next(iter(parts["groups"].rows.values()))
    assert row["status"] == "active" and row["wa_group_id"] == GROUP_WA

    # With nothing to go on, it is left alone.
    chat, parts = _chat(client=FakeClient({}))
    await chat.handle_event(
        "group_lifecycle_update", {"groups": [{"type": "group_create", "group_id": "120363999"}]}
    )
    assert parts["outbox"].sent == [] and parts["sender"].sent == []
