"""Add a teammate by sharing their WhatsApp contact (SS-13), or let in
someone who asked to join with the company's code (SS-05).

Two taps, then they are in: what they will do (WA-67: Site Engineer,
Project Manager, or -- for an admin -- Admin, the roles the sender may
give), then the project (a list when there are several; one project is
picked by itself). The taps ARE the confirmation: the person goes onto the
project at once through the backend's one add-by-number step
(mesiri.application.identity.add_by_number.add_to_project_by_number), the
same step the dashboard and the v3 assistant's ``add_person`` use:

    new number            made in the company, then put on the project
    already in this org   put on the project
    in another company    refused (one number = one person, BE-04)

Someone who asked to join messaged Mesiri moments ago, so WhatsApp lets us
tell them directly (the Welcome card). A shared contact never messaged us:
WhatsApp allows free-form messages only within 24 h of the person's own
last message, so the owner gets a message to forward instead, with a wa.me
link to Mesiri's number. Each step of a join request (role, project,
joined) is noted on the request, for the company's Live screen.

Typed adds on classic ("add Rajesh 98... as engineer") still go through the
CREATE_USER / ADD_PROJECT_MEMBER workflows and end with the same invite
(``invite_after_member_added``).
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, Protocol

from channel.replies import ListRow, ReplySpec
from mesiri.application.dpr.recipients import RecipientError, normalize_phone
from mesiri.application.identity.add_by_number import (
    AddedToProject,
    MemberNotAdded,
    add_to_project_by_number,
)
from mesiri.authorization.roles import may_grant_role
from mesiri_contracts.assistant.draft_action import DraftActionType

if TYPE_CHECKING:
    from backend.ports import ActorIdentity
    from mesiri.infrastructure.postgres.database import PostgresDatabase
    from planning.plan_store import PlanStore
    from workflows import WorkflowRuntime

_log = logging.getLogger("mesiri.contact_share")

PROJECT_TAP_PREFIX = "contact_project:"
ROLE_TAP_PREFIX = "contact_role:"
_MANAGER_ROLES = frozenset({"ADMIN", "PROJECT_MANAGER"})
#: The role a typed add (classic) gives when none was said.
_NEW_MEMBER_ROLE = "SITE_ENGINEER"
#: The role question's buttons, in order (WhatsApp shows at most three).
_ROLE_CHOICES = (
    ("SITE_ENGINEER", "Site Engineer"),
    ("PROJECT_MANAGER", "Project Manager"),
    ("ADMIN", "Admin"),
)
_PENDING_TTL_SECONDS = 10 * 60
_INVITE_TTL_SECONDS = 60 * 60
_LIST_MAX = 10

NOT_ALLOWED = "Only your company's admin or project manager can add people to Mesiri."
NO_NUMBER = "That contact has no phone number. Share a contact that has their mobile number."
NO_PROJECT = "Create a project first, then share the contact again."
OTHER_COMPANY = (
    "That number is already used by someone in another company on Mesiri, so I can't add it here."
)
MORE_THAN_ONE = "\n\n(I'll add *{name}* first. Share the others one at a time after this.)"
PICK_PROJECT = "Which project should *{name}* ({role}) work on?"
PICK_ROLE = "What will *{name}* do?"
APPROVED_PICK_ROLE = "👍 Approved. What will *{name}* do?"
EXPIRED = "That choice has expired. Share the contact again."
FAILED = "Sorry, I couldn't add them. Please try again."
NOT_ADDED = "I couldn't add *{name}*: {reason}."
ALREADY_ON = "*{name}* is already on *{project}*."
ADDED = (
    "✅ *{name}* can now report on *{project}*. Forward the next message to them so they can start:"
)
INVITE = (
    "Hi {first}, {company} uses Mesiri for daily site reports on WhatsApp. "
    "Tap this link and send *Hi* to start: https://wa.me/{number}?text=Hi"
)
ADDED_JOINER = "✅ *{name}* is in: {role} on *{project}*. I've told them."
JOINED = (
    "✅ You're in, {first}! *{company}* added you to *{project}* on Mesiri as {role}.\n\n"
    "Send today's work here, the way you'd tell your office, e.g. *10 masons, plastering "
    "3rd floor*. Text, voice notes and photos all work."
)
INVITE_NO_LINK = (
    "Hi {first}, {company} uses Mesiri for daily site reports on WhatsApp. "
    "Save this number and send *Hi* to it to start."
)


class _RedisLike(Protocol):
    async def set_json(self, key: str, value: Any, *, ttl_seconds: int | None = None) -> None: ...
    async def get_json(self, key: str) -> Any | None: ...


_ROLE_TITLES = dict(_ROLE_CHOICES) | {"FINANCE": "Finance"}


def _role_title(role: object) -> str:
    return _ROLE_TITLES.get(str(role or "").upper(), "Site Engineer")


def _key(user_id: str, what: str) -> str:
    return f"user:{user_id}:contact_share_{what}"


def _first_name(name: str) -> str:
    return (name.split() or ["there"])[0]


def _digits(value: object) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


class ContactShareJourney:
    def __init__(
        self,
        *,
        redis: _RedisLike,
        db: PostgresDatabase,
        plan_store: PlanStore,
        workflow_runtime: WorkflowRuntime,
        send_text: Callable[[str, str], Awaitable[Any]] | None = None,
        send_image: Callable[..., Awaitable[Any]] | None = None,
        card_renderer: Any | None = None,
    ) -> None:
        self._redis = redis
        self._db = db
        self._plan_store = plan_store
        self._runtime = workflow_runtime
        # SS-05: tells someone who asked to join that they're in.
        self._send_text = send_text
        # Request 91: the Welcome card (image, JOINED text as its caption).
        self._send_image = send_image
        self._card_renderer = card_renderer

    # -- entry points ---------------------------------------------------------

    async def handle_contacts(self, message: Any, actor: ActorIdentity) -> ReplySpec:
        """A shared contact card from a registered sender: what will they do?"""
        if str(actor.role or "").upper() not in _MANAGER_ROLES:
            return ReplySpec(text=NOT_ALLOWED)
        people = list((message.metadata or {}).get("shared_contacts") or [])
        if not people:
            return ReplySpec(text=NO_NUMBER)
        person = people[0]
        try:
            phone = normalize_phone(person.get("phone"))
        except RecipientError:
            return ReplySpec(text=NO_NUMBER)
        name = " ".join(str(person.get("name") or "").split())
        note = MORE_THAN_ONE.format(name=name or "the first one") if len(people) > 1 else ""
        if not actor.projects:
            return ReplySpec(text=NO_PROJECT)
        pending = {
            "name": name,
            "phone": phone,
            "business_number": _digits((message.metadata or {}).get("display_phone_number")),
            "note": note,
            "owner_wa": _digits(getattr(getattr(message, "sender", None), "wa_id", "")),
        }
        return await self._ask_role(actor, pending, PICK_ROLE.format(name=name or "they"))

    async def start_join(
        self,
        actor: ActorIdentity,
        *,
        name: str,
        phone: str,
        business_number: str,
        request_id: str | None = None,
    ) -> ReplySpec:
        """SS-05: an admin approved someone who asked to join with the
        company's code. The same two taps as a shared contact (role, then
        project); once they're on the project they are told directly (they
        messaged Mesiri moments ago, so WhatsApp lets us)."""
        if not actor.projects:
            return ReplySpec(text=NO_PROJECT)
        pending = {
            "name": name,
            "phone": phone,
            "business_number": business_number,
            "note": "",
            "join_phone": phone,
            "join_request_id": request_id,
        }
        return await self._ask_role(actor, pending, APPROVED_PICK_ROLE.format(name=name or "them"))

    async def _ask_role(self, actor: ActorIdentity, pending: dict, question: str) -> ReplySpec:
        await self._redis.set_json(
            _key(actor.user_id, "pending"), pending, ttl_seconds=_PENDING_TTL_SECONDS
        )
        return ReplySpec(
            text=question + (pending.get("note") or ""),
            buttons=tuple(
                ListRow(id=f"{ROLE_TAP_PREFIX}{code}", title=title)
                for code, title in _ROLE_CHOICES
                if may_grant_role(actor.role, code)
            ),
        )

    async def _begin(self, actor: ActorIdentity, pending: dict) -> ReplySpec:
        """Pick the project (a list when there are several), then add."""
        name = pending.get("name") or ""
        projects = list(actor.projects or [])
        if not projects:
            return ReplySpec(text=NO_PROJECT)
        if len(projects) > 1:
            await self._redis.set_json(
                _key(actor.user_id, "pending"), pending, ttl_seconds=_PENDING_TTL_SECONDS
            )
            return ReplySpec(
                text=PICK_PROJECT.format(name=name or "them", role=_role_title(pending.get("role"))),
                list_button_label="Choose project",
                list_rows=tuple(
                    ListRow(id=f"{PROJECT_TAP_PREFIX}{p.id}", title=p.name[:24])
                    for p in projects[:_LIST_MAX]
                ),
            )
        return await self._start(actor, pending, projects[0].id, projects[0].name)

    async def handle_project_tap(self, message: Any, actor: ActorIdentity) -> ReplySpec | None:
        """The role or project picked for a pending contact, or None if this
        tap isn't one."""
        tap = str((message.metadata or {}).get("interactive_reply_id") or "")
        if tap.startswith(ROLE_TAP_PREFIX):
            return await self._role_tap(tap[len(ROLE_TAP_PREFIX) :], actor)
        if not tap.startswith(PROJECT_TAP_PREFIX):
            return None
        pending = await self._redis.get_json(_key(actor.user_id, "pending"))
        await self._redis.set_json(_key(actor.user_id, "pending"), None, ttl_seconds=60)
        project_id = tap[len(PROJECT_TAP_PREFIX) :]
        project = next((p for p in actor.projects or [] if str(p.id) == project_id), None)
        if not isinstance(pending, dict) or "role" not in pending or project is None:
            return ReplySpec(text=EXPIRED)
        return await self._start(actor, pending, project.id, project.name)

    async def _role_tap(self, role: str, actor: ActorIdentity) -> ReplySpec:
        pending = await self._redis.get_json(_key(actor.user_id, "pending"))
        if not isinstance(pending, dict) or "role" in pending:
            # Expired, or a second tap on the role question after the first
            # already moved on (its project choice is kept).
            return ReplySpec(text=EXPIRED)
        await self._redis.set_json(_key(actor.user_id, "pending"), None, ttl_seconds=60)
        if not may_grant_role(actor.role, role):
            return ReplySpec(text=NOT_ALLOWED)
        pending = {**pending, "role": role}
        if pending.get("join_request_id"):
            await self._note_join_step(actor, pending, role=role)
        return await self._begin(actor, pending)

    async def invite_after_member_added(
        self,
        *,
        action_type: object,
        member_name: object,
        actor: ActorIdentity,
        project_id: object = None,
        business_number: object = None,
    ) -> list[str]:
        """The messages to send once ADD_PROJECT_MEMBER has succeeded for the
        person whose contact was shared, or (SET-04) who was added by typing
        "add Rajesh 98... as engineer": the same ADDED + INVITE either way.
        [] for any other confirmation."""
        if action_type is not DraftActionType.ADD_PROJECT_MEMBER:
            return []
        invite = await self._redis.get_json(_key(actor.user_id, "invite"))
        if not isinstance(invite, dict):
            # Typed add: no contact card set the invite up, so build it from
            # what the confirmed action and the message carry.
            project = next(
                (p for p in actor.projects or [] if str(p.id) == str(project_id or "")), None
            )
            if project is None or not member_name:
                return []
            invite = {
                "name": str(member_name),
                "project_name": project.name,
                "business_number": _digits(business_number),
            }
        wanted = " ".join(str(invite.get("name") or "").lower().split())
        added = " ".join(str(member_name or "").lower().split())
        if wanted and wanted != added:
            return []
        await self._redis.set_json(_key(actor.user_id, "invite"), None, ttl_seconds=60)
        name = str(member_name or invite.get("name") or "")
        first = _first_name(name)
        company = actor.org_name or "Your company"
        project = invite.get("project_name") or "the project"
        join_phone = invite.get("join_phone")
        if join_phone and self._send_text is not None:
            # SS-05: they asked to join, so tell them directly.
            role = str(invite.get("role") or _NEW_MEMBER_ROLE)
            joined = JOINED.format(first=first, company=company, project=project, role=_role_title(role))
            try:
                if not await self._send_welcome_card(str(join_phone), joined, first, actor, company, role):
                    await self._send_text(str(join_phone), joined)
                return [ADDED_JOINER.format(name=name, project=project)]
            except Exception:  # noqa: BLE001 -- fall back to the invite to forward
                _log.warning("contact_share.joiner_not_told user=%s", actor.user_id)
        number = invite.get("business_number")
        invite_text = (
            INVITE.format(first=first, company=company, number=number)
            if number
            else INVITE_NO_LINK.format(first=first, company=company)
        )
        return [
            ADDED.format(name=name, project=invite.get("project_name") or "the project"),
            invite_text,
        ]

    # -- internals ------------------------------------------------------------

    async def _send_welcome_card(
        self,
        wa_id: str,
        caption: str,
        first: str,
        actor: ActorIdentity,
        company: str,
        role: str = _NEW_MEMBER_ROLE,
    ) -> bool:
        """Request 91: the Welcome card with the JOINED text as its caption.
        False (nothing sent) when there is no renderer or the card could not
        be made or sent: the caller then sends the text."""
        if self._send_image is None or self._card_renderer is None:
            return False
        from channel.cards import build_welcome_card, render_png, welcome_html

        card = build_welcome_card(
            first=first,
            role_code=role,
            added_by=actor.full_name or "",
            company=company,
        )
        png = await render_png(self._card_renderer, welcome_html(card), card="welcome")
        if png is None:
            return False
        try:
            sent = await self._send_image(
                wa_id, png, caption=caption, filename="welcome.png", shows=f"Welcome card for {first} at {company}"
            )
        except Exception:  # noqa: BLE001 -- the text goes instead
            _log.warning("contact_share.welcome_card_not_sent user=%s", actor.user_id, exc_info=True)
            return False
        return sent is not False

    async def _start(
        self, actor: ActorIdentity, pending: dict, project_id: str, project_name: str
    ) -> ReplySpec:
        """Put them on the project now (the role and project taps were the
        confirmation), then tell whoever needs telling."""
        name = str(pending.get("name") or "")
        role = str(pending.get("role") or _NEW_MEMBER_ROLE)
        try:
            added = await self._add(actor, pending["phone"], name, role, project_id)
        except MemberNotAdded as exc:
            reason = str(exc).rstrip(".")
            if "another company" in reason:
                return ReplySpec(text=OTHER_COMPANY)
            return ReplySpec(text=NOT_ADDED.format(name=name or "them", reason=reason[:1].lower() + reason[1:]))
        except Exception:  # noqa: BLE001
            _log.exception("contact_share.add_failed user=%s", actor.user_id)
            return ReplySpec(text=FAILED)
        _log.info(
            "contact_share.added user=%s created=%s already=%s join=%s",
            actor.user_id,
            added.created,
            added.already_on_project,
            bool(pending.get("join_phone")),
        )
        who = added.full_name or name
        if pending.get("join_request_id"):
            await self._note_join_step(actor, pending, project=project_name, joined=True)
        if added.already_on_project:
            return ReplySpec(text=ALREADY_ON.format(name=who, project=project_name))
        first = _first_name(who)
        company = actor.org_name or "Your company"
        join_phone = pending.get("join_phone")
        if join_phone and self._send_text is not None:
            joined = JOINED.format(first=first, company=company, project=project_name, role=_role_title(role))
            try:
                if not await self._send_welcome_card(str(join_phone), joined, first, actor, company, role):
                    await self._send_text(str(join_phone), joined)
                return ReplySpec(text=ADDED_JOINER.format(name=who, role=_role_title(role), project=project_name))
            except Exception:  # noqa: BLE001 -- fall back to the invite to forward
                _log.warning("contact_share.joiner_not_told user=%s", actor.user_id)
        number = pending.get("business_number")
        invite_text = (
            INVITE.format(first=first, company=company, number=number)
            if number
            else INVITE_NO_LINK.format(first=first, company=company)
        )
        owner = pending.get("owner_wa")
        if owner and self._send_text is not None:
            # The line first, then the invite on its own, so it forwards cleanly.
            try:
                await self._send_text(str(owner), ADDED.format(name=who, project=project_name))
                return ReplySpec(text=invite_text)
            except Exception:  # noqa: BLE001 -- both in one message instead
                _log.warning("contact_share.added_line_failed user=%s", actor.user_id)
        return ReplySpec(text=ADDED.format(name=who, project=project_name) + "\n\n" + invite_text)

    async def _add(
        self, actor: ActorIdentity, phone: str, name: str, role: str, project_id: str
    ) -> AddedToProject:
        async with self._db.transaction() as conn:
            return await add_to_project_by_number(
                conn,
                organization_id=str(actor.organization_id),
                project_id=str(project_id),
                created_by=str(actor.user_id).removeprefix("ctx_user_"),
                created_by_role=str(actor.role or ""),
                full_name=name or "Team member",
                whatsapp_number=phone,
                role=role,
            )

    async def _note_join_step(
        self,
        actor: ActorIdentity,
        pending: dict,
        *,
        role: str | None = None,
        project: str | None = None,
        joined: bool = False,
    ) -> None:
        """For the Live screen: the join request's role, project, joined.
        Best effort: the person is added whether or not this is noted."""
        from mesiri.application.organizations import team_join

        try:
            async with self._db.transaction() as conn:
                await team_join.note_step(
                    conn,
                    uuid.UUID(str(actor.organization_id)),
                    request_id=str(pending.get("join_request_id")),
                    role=role,
                    project=project,
                    joined_at=dt.datetime.now(dt.UTC) if joined else None,
                )
        except Exception:  # noqa: BLE001
            _log.warning("contact_share.join_step_not_noted user=%s", actor.user_id, exc_info=True)
