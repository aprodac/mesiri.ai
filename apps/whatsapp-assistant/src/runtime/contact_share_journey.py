"""Add a teammate by sharing their WhatsApp contact (SS-13).

An owner or project manager shares a contact card; Mesiri adds that person
to a project through the SAME workflows a typed "add Rajesh, 98765..., as
site engineer" uses -- nothing here writes users or memberships itself:

    new number            CREATE_USER -> ADD_PROJECT_MEMBER, as one Plan
                          (start_member_create_plan, the entity-resolution
                          chain), name and number taken from the card
    already in this org   ADD_PROJECT_MEMBER alone
    in another company    refused (one number = one person, BE-04)

Each workflow keeps its own confirmation, so the person is never added
without a tap. Several projects: a list picker first. One contact per share:
the Plan store holds one plan per user.

Once ADD_PROJECT_MEMBER succeeds, the owner gets a message to forward to the
new person with a wa.me link to Mesiri's number. Mesiri can't message them
first: WhatsApp allows free-form messages only within 24 h of the person's
own last message, and the invite template isn't approved yet (SS-12). When
they tap and say Hi, they're already a user, and the existing first-message
intro (channel/replies.py's render_greeting_menu) welcomes them.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, Protocol

import sqlalchemy as sa

from channel.replies import ListRow, ReplySpec
from mesiri.application.dpr.recipients import RecipientError, normalize_phone
from mesiri.infrastructure.postgres.tenant import unscoped
from mesiri_contracts.assistant.canonical_event import CanonicalEventType, IntentCompleteness
from mesiri_contracts.assistant.draft_action import DraftActionType
from mesiri_contracts.assistant.planner_decision import PlannerDecisionType, WorkflowKey
from mesiri_contracts.assistant.v2.canonical_event import CanonicalEventV2
from mesiri_contracts.assistant.v2.planner_decision import PlannerDecisionV2
from runtime.inbound_journey.reply import render_workflow_run_reply_spec
from runtime.member_create_plan import start_member_create_plan

if TYPE_CHECKING:
    from backend.ports import ActorIdentity
    from mesiri.infrastructure.postgres.database import PostgresDatabase
    from planning.plan_store import PlanStore
    from workflows import WorkflowRuntime

_log = logging.getLogger("mesiri.contact_share")

PROJECT_TAP_PREFIX = "contact_project:"
_MANAGER_ROLES = frozenset({"ADMIN", "PROJECT_MANAGER"})
_NEW_MEMBER_ROLE = "SITE_ENGINEER"
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
PICK_PROJECT = "Which project should *{name}* report on?"
EXPIRED = "That choice has expired. Share the contact again."
FAILED = "Sorry, I couldn't start adding them. Please try again."
ADDED = (
    "✅ *{name}* can now report on *{project}*. Forward the next message to them so they can start:"
)
INVITE = (
    "Hi {first}, {company} uses Mesiri for daily site reports on WhatsApp. "
    "Tap this link and send *Hi* to start: https://wa.me/{number}?text=Hi"
)
ADDED_JOINER = "✅ *{name}* can now report on *{project}*. I've told them they're in."
JOINED = (
    "✅ You're in, {first}! *{company}* added you to *{project}* on Mesiri.\n\n"
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


_users = sa.Table(
    "users",
    sa.MetaData(),
    sa.Column("id", sa.UUID(as_uuid=True)),
    sa.Column("organization_id", sa.UUID(as_uuid=True)),
    sa.Column("full_name", sa.String),
    sa.Column("whatsapp_number", sa.String),
)


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
    ) -> None:
        self._redis = redis
        self._db = db
        self._plan_store = plan_store
        self._runtime = workflow_runtime
        # SS-05: tells someone who asked to join that they're in.
        self._send_text = send_text

    # -- entry points ---------------------------------------------------------

    async def handle_contacts(self, message: Any, actor: ActorIdentity) -> ReplySpec:
        """A shared contact card from a registered sender."""
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

        pending = {
            "name": name,
            "phone": phone,
            "business_number": _digits((message.metadata or {}).get("display_phone_number")),
            "note": note,
        }
        return await self._begin(actor, pending)

    async def start_join(
        self, actor: ActorIdentity, *, name: str, phone: str, business_number: str
    ) -> ReplySpec:
        """SS-05: an admin approved someone who asked to join with the
        company's code. The same steps as sharing their contact; once they're
        on the project they are told directly (they messaged Mesiri moments
        ago, so WhatsApp lets us), instead of the owner forwarding an invite."""
        return await self._begin(
            actor,
            {
                "name": name,
                "phone": phone,
                "business_number": business_number,
                "note": "",
                "join_phone": phone,
            },
        )

    async def _begin(self, actor: ActorIdentity, pending: dict) -> ReplySpec:
        """Pick the project (a list when there are several), then start."""
        name = pending.get("name") or ""
        note = pending.get("note") or ""
        projects = list(actor.projects or [])
        if not projects:
            return ReplySpec(text=NO_PROJECT)
        if len(projects) > 1:
            await self._redis.set_json(
                _key(actor.user_id, "pending"), pending, ttl_seconds=_PENDING_TTL_SECONDS
            )
            return ReplySpec(
                text=PICK_PROJECT.format(name=name or "them") + note,
                list_button_label="Choose project",
                list_rows=[
                    ListRow(id=f"{PROJECT_TAP_PREFIX}{p.id}", title=p.name)
                    for p in projects[:_LIST_MAX]
                ],
            )
        return await self._start(actor, pending, projects[0].id, projects[0].name)

    async def handle_project_tap(self, message: Any, actor: ActorIdentity) -> ReplySpec | None:
        """The project picked for a pending contact, or None if this tap isn't one."""
        tap = str((message.metadata or {}).get("interactive_reply_id") or "")
        if not tap.startswith(PROJECT_TAP_PREFIX):
            return None
        pending = await self._redis.get_json(_key(actor.user_id, "pending"))
        await self._redis.set_json(_key(actor.user_id, "pending"), None, ttl_seconds=60)
        project_id = tap[len(PROJECT_TAP_PREFIX) :]
        project = next((p for p in actor.projects or [] if str(p.id) == project_id), None)
        if not isinstance(pending, dict) or project is None:
            return ReplySpec(text=EXPIRED)
        return await self._start(actor, pending, project.id, project.name)

    async def invite_after_member_added(
        self, *, action_type: object, member_name: object, actor: ActorIdentity
    ) -> list[str]:
        """The messages to send once ADD_PROJECT_MEMBER has succeeded for the
        person whose contact was shared; [] for any other confirmation."""
        if action_type is not DraftActionType.ADD_PROJECT_MEMBER:
            return []
        invite = await self._redis.get_json(_key(actor.user_id, "invite"))
        if not isinstance(invite, dict):
            return []
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
            try:
                await self._send_text(
                    str(join_phone), JOINED.format(first=first, company=company, project=project)
                )
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

    async def _start(
        self, actor: ActorIdentity, pending: dict, project_id: str, project_name: str
    ) -> ReplySpec:
        phone = pending["phone"]
        existing = await self._find_user(phone)
        if existing is not None and str(existing.organization_id) != str(actor.organization_id):
            return ReplySpec(text=OTHER_COMPANY)

        name = existing.full_name if existing is not None else pending.get("name") or ""
        await self._redis.set_json(
            _key(actor.user_id, "invite"),
            {
                "name": name,
                "project_name": project_name,
                "business_number": pending.get("business_number"),
                "join_phone": pending.get("join_phone"),
            },
            ttl_seconds=_INVITE_TTL_SECONDS,
        )
        original = self._add_member_event(actor, project_id, name)
        try:
            if existing is not None:
                spec = await self._start_add_member(actor, original)
            else:
                spec = await start_member_create_plan(
                    name_hint=name,
                    original_event=original,
                    actor=actor,
                    plan_store=self._plan_store,
                    workflow_runtime=self._runtime,
                    whatsapp_number=phone,
                )
        except Exception:  # noqa: BLE001
            _log.exception("contact_share.start_failed user=%s", actor.user_id)
            spec = None
        if spec is None:
            return ReplySpec(text=FAILED)
        note = pending.get("note") or ""
        if note:
            spec = ReplySpec(
                text=spec.text + note,
                list_button_label=spec.list_button_label,
                list_rows=spec.list_rows,
                buttons=spec.buttons,
            )
        _log.info("contact_share.started user=%s existing=%s", actor.user_id, existing is not None)
        return spec

    async def _find_user(self, phone: str) -> Any | None:
        async with self._db.transaction() as conn:
            # Every company: a number held elsewhere is refused (BE-03 unscoped).
            async with unscoped(conn):
                row = (
                    await conn.execute(
                        sa.select(_users.c.id, _users.c.organization_id, _users.c.full_name).where(
                            sa.func.regexp_replace(_users.c.whatsapp_number, r"\D", "", "g") == phone
                        )
                    )
                ).first()
        return row

    @staticmethod
    def _add_member_event(actor: ActorIdentity, project_id: str, name: str) -> CanonicalEventV2:
        corr = f"contact_share_{uuid.uuid4().hex[:12]}"
        return CanonicalEventV2(
            event_id=corr,
            correlation_id=corr,
            source_message_id=corr,
            event_type=CanonicalEventType.ADD_PROJECT_MEMBER_REQUESTED,
            completeness=IntentCompleteness.ACTIONABLE,
            organization_id=str(actor.organization_id),
            user_id=str(actor.user_id),
            project_id=str(project_id),
            fields={
                "member_name": name,
                "role": _NEW_MEMBER_ROLE,
                "created_by_role": actor.role,
            },
        )

    async def _start_add_member(
        self, actor: ActorIdentity, event: CanonicalEventV2
    ) -> ReplySpec | None:
        decision = PlannerDecisionV2(
            correlation_id=event.correlation_id,
            source_message_id=event.source_message_id,
            decision_type=PlannerDecisionType.START_WORKFLOW,
            workflow_key=WorkflowKey.ADD_PROJECT_MEMBER,
            reason=CanonicalEventType.ADD_PROJECT_MEMBER_REQUESTED,
            organization_id=event.organization_id,
            user_id=event.user_id,
            project_id=event.project_id,
        )
        await self._runtime.abandon_optional_question(str(actor.user_id))
        run = await self._runtime.start(decision, event)
        if not run.pending_prompt:
            return None
        return render_workflow_run_reply_spec(run)
