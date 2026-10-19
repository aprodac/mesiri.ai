"""Joining a company with its code on WhatsApp (SS-05).

    admin / PM:   "join code"        -> a message to forward to the team, with
                                        a link that opens "JOIN ACME-4821"
                  "new join code"    -> a new code; the old one stops working
    newcomer:     "JOIN ACME-4821"   -> each admin is asked [Approve] [Reject]
    admin:        Approve            -> the same steps as sharing a contact
                                        (SS-13): project, then add them
                  Reject             -> the newcomer is told

**A code adds nobody by itself.** Only an admin's Approve starts adding the
person, and that goes through the existing CREATE_USER / ADD_PROJECT_MEMBER
workflows with their own confirmations (runtime/contact_share_journey.py),
so nothing here writes users or memberships. A number already on Mesiri is
a registered sender and never reaches this journey; one in another company
is refused by those steps (BE-04).

Guardrails: a number gets MAX_WRONG_CODES_PER_DAY wrong codes a day; asking
again while a request is open sends no second alert; a company holds at
most MAX_OPEN open requests (domains/organizations/team_join.py).

Messages to the admins are sent free-form, which WhatsApp only delivers
inside 24 hours of the admin's own last message; the "join request"
template that covers the rest is SS-12.
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Protocol
from urllib.parse import quote

from channel.replies import ListRow, ReplySpec
from mesiri.application.organizations import team_join
from mesiri.domains.organizations import team_join as rules
from mesiri_contracts.assistant.enums import InputModality

if TYPE_CHECKING:
    from backend.ports import ActorIdentity
    from channel.whatsapp.outbound import WhatsAppSender
    from mesiri.infrastructure.postgres.database import PostgresDatabase
    from runtime.contact_share_journey import ContactShareJourney

_log = logging.getLogger("mesiri.team_join")

APPROVE_PREFIX = "join:approve:"
REJECT_PREFIX = "join:reject:"
_CODE_WORDS = frozenset(
    {"join code", "invite code", "team code", "joining code", "join link", "invite link"}
)
_NEW_CODE_WORDS = frozenset({"new join code", "new invite code", "change join code"})
_SHARERS = frozenset({"ADMIN", "PROJECT_MANAGER"})
_APPROVER = "ADMIN"
_NAME_MAX = 120
_NAME_TTL_SECONDS = 60 * 60
_WRONG_TTL_SECONDS = 24 * 60 * 60

# To the newcomer
ASK_NAME = "Welcome! What's your name? I'll send it to *{company}* so they know who's asking."
ASKED = (
    "Thanks {name}! I've asked *{company}* to approve you. You'll get a message here "
    "as soon as they do."
)
ALREADY_ASKED = (
    "Your request to join *{company}* is already with them. You'll get a message here "
    "as soon as they approve it."
)
WRONG_CODE = (
    "I don't know that code. Check it with whoever sent it to you, then send "
    "*JOIN* and the code, e.g. *JOIN ACME-4821*."
)
TOO_MANY_TRIES = "Too many wrong codes today. Ask your company's admin for the code and try tomorrow."
BUSY = (
    "*{company}* has a lot of requests waiting. Ask their admin to approve them, "
    "then try again."
)
FAILED = "Sorry, something went wrong. Please send your JOIN message again."
REJECTED_NOTICE = "*{company}* didn't approve your request to join. If that's a mistake, talk to their admin."

# To an admin
APPROVAL_REQUEST = (
    "👤 *{name}* (+{phone}) wants to join *{company}* on Mesiri with your join code. "
    "Approve them?"
)
NOT_ALLOWED_TO_DECIDE = "Only your company's admin can approve people who ask to join."
ALREADY_DECIDED = "That request was already {outcome}."
EXPIRED = "That request has expired. They can send their JOIN message again."
REJECTED_DONE = "Okay, *{name}* won't be added."
NOT_ALLOWED_TO_SHARE = "Only your company's admin or project manager can share the join code."
CODE_INTRO = (
    "Forward the next message to your team. Whoever sends it is asked to you to approve "
    "before they're added.{rotated}\n\nCode leaked? Send *new join code* to replace it."
)
CODE_ROTATED = "\n\nThe old code no longer works."
CODE_FORWARD = (
    "Join *{company}* on Mesiri for daily site reports on WhatsApp: tap {link} and send "
    "the message.\n\nOr send *JOIN {code}* to +{number}."
)
CODE_FORWARD_NO_NUMBER = (
    "Join *{company}* on Mesiri for daily site reports on WhatsApp: send *JOIN {code}* "
    "to this Mesiri number."
)


class _RedisLike(Protocol):
    async def set_json(self, key: str, value: Any, *, ttl_seconds: int | None = None) -> None: ...
    async def get_json(self, key: str) -> Any | None: ...


def _digits(value: object) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def _clean_name(value: object) -> str | None:
    name = " ".join(str(value or "").split())
    if not name or len(name) > _NAME_MAX or not any(ch.isalpha() for ch in name):
        return None
    return name


def _text(message: Any) -> str:
    if message.modality is not InputModality.TEXT:
        return ""
    return " ".join(str(message.text or "").split())


class JoinJourney:
    def __init__(
        self,
        *,
        sender: WhatsAppSender,
        db: PostgresDatabase,
        redis: _RedisLike,
        contact_share: ContactShareJourney | None,
        now: Callable[[], dt.datetime] | None = None,
    ) -> None:
        self._sender = sender
        self._db = db
        self._redis = redis
        self._contact_share = contact_share
        self._now = now or (lambda: dt.datetime.now(dt.UTC))

    # -- a number Mesiri doesn't know ----------------------------------------

    async def handle_unregistered(self, message: Any) -> str | None:
        """The reply sent to a newcomer's JOIN message (or their name, when
        it was asked), or None when this message isn't about joining."""
        wa_id = _digits(message.sender.wa_id)
        text = _text(message)
        pending = await self._redis.get_json(self._name_key(wa_id))
        code = rules.code_in_message(text)
        if code is None and isinstance(pending, dict) and text:
            name = _clean_name(text)
            if name is None:
                return await self._say(wa_id, ASK_NAME.format(company=pending.get("company")))
            await self._redis.set_json(self._name_key(wa_id), None, ttl_seconds=60)
            return await self._request(
                wa_id,
                team_join.Company(
                    organization_id=uuid.UUID(pending["organization_id"]),
                    name=str(pending.get("company") or ""),
                ),
                name,
            )
        if code is None:
            return None

        wrong_key = self._wrong_key(wa_id)
        wrong = await self._redis.get_json(wrong_key)
        wrong = int(wrong) if isinstance(wrong, int) else 0
        if wrong >= rules.MAX_WRONG_CODES_PER_DAY:
            return await self._say(wa_id, TOO_MANY_TRIES)
        try:
            async with self._db.transaction() as conn:
                company = await team_join.company_for_code(conn, code)
        except Exception:  # noqa: BLE001
            _log.exception("team_join.lookup_failed wa_id=%s", wa_id)
            return await self._say(wa_id, FAILED)
        if company is None:
            await self._redis.set_json(wrong_key, wrong + 1, ttl_seconds=_WRONG_TTL_SECONDS)
            _log.info("team_join.wrong_code wa_id=%s tries=%s", wa_id, wrong + 1)
            return await self._say(wa_id, WRONG_CODE)

        name = _clean_name(message.sender.profile_name)
        if name is None:
            await self._redis.set_json(
                self._name_key(wa_id),
                {"organization_id": str(company.organization_id), "company": company.name},
                ttl_seconds=_NAME_TTL_SECONDS,
            )
            return await self._say(wa_id, ASK_NAME.format(company=company.name))
        return await self._request(wa_id, company, name)

    async def _request(self, wa_id: str, company: team_join.Company, name: str) -> str:
        try:
            async with self._db.transaction() as conn:
                try:
                    request, is_new = await team_join.request_to_join(
                        conn, company.organization_id, phone=wa_id, name=name, now=self._now()
                    )
                except rules.TooManyRequests:
                    return await self._say(wa_id, BUSY.format(company=company.name))
                admins = await team_join.approvers(conn, company.organization_id) if is_new else []
        except Exception:  # noqa: BLE001
            _log.exception("team_join.request_failed wa_id=%s org=%s", wa_id, company.organization_id)
            return await self._say(wa_id, FAILED)
        if not is_new:
            return await self._say(wa_id, ALREADY_ASKED.format(company=company.name))

        body = APPROVAL_REQUEST.format(name=name, phone=wa_id, company=company.name)
        ref = f"{company.organization_id}:{request['id']}"
        asked = 0
        for admin in admins:
            try:
                await self._sender.send_button(
                    _digits(admin.whatsapp_number),
                    body=body,
                    buttons=[
                        ListRow(id=f"{APPROVE_PREFIX}{ref}", title="Approve"),
                        ListRow(id=f"{REJECT_PREFIX}{ref}", title="Reject"),
                    ],
                )
                asked += 1
            except Exception:  # noqa: BLE001 -- e.g. outside the admin's 24 h window
                _log.warning("team_join.admin_not_reached org=%s admin=%s", company.organization_id, admin.user_id)
        _log.info(
            "team_join.requested org=%s wa_id=%s admins=%s reached=%s",
            company.organization_id,
            wa_id,
            len(admins),
            asked,
        )
        return await self._say(wa_id, ASKED.format(name=name.split()[0], company=company.name))

    # -- a registered admin or project manager --------------------------------

    async def handle_code_request(self, message: Any, actor: ActorIdentity) -> ReplySpec | None:
        """"join code" / "new join code": the code to share, or None when
        the message isn't asking for it."""
        words = _text(message).lower().rstrip("?.!")
        rotate = words in _NEW_CODE_WORDS
        if not rotate and words not in _CODE_WORDS:
            return None
        if str(actor.role or "").upper() not in _SHARERS:
            return ReplySpec(text=NOT_ALLOWED_TO_SHARE)
        async with self._db.transaction() as conn:
            code = await team_join.join_code(
                conn,
                uuid.UUID(str(actor.organization_id)),
                rotate=rotate,
                now=self._now(),
                updated_by=_uuid(actor.user_id),
            )
        number = _digits((message.metadata or {}).get("display_phone_number"))
        company = actor.org_name or "your company"
        await self._sender.send_text(
            _digits(message.sender.wa_id),
            CODE_INTRO.format(rotated=CODE_ROTATED if rotate else ""),
        )
        if number:
            link = f"https://wa.me/{number}?text={quote(rules.join_text(code))}"
            forward = CODE_FORWARD.format(company=company, link=link, code=code, number=number)
        else:
            forward = CODE_FORWARD_NO_NUMBER.format(company=company, code=code)
        _log.info("team_join.code_shared org=%s rotated=%s", actor.organization_id, rotate)
        return ReplySpec(text=forward)

    async def handle_tap(self, message: Any, actor: ActorIdentity) -> ReplySpec | None:
        """An admin's Approve / Reject, or None when the tap isn't one."""
        tap = str((message.metadata or {}).get("interactive_reply_id") or "")
        if tap.startswith(APPROVE_PREFIX):
            approve, ref = True, tap[len(APPROVE_PREFIX) :]
        elif tap.startswith(REJECT_PREFIX):
            approve, ref = False, tap[len(REJECT_PREFIX) :]
        else:
            return None
        org_text, _, request_id = ref.partition(":")
        if (
            str(actor.organization_id) != org_text
            or str(actor.role or "").upper() != _APPROVER
            or not request_id
        ):
            return ReplySpec(text=NOT_ALLOWED_TO_DECIDE)
        organization_id = uuid.UUID(org_text)
        async with self._db.transaction() as conn:
            request, decided = await team_join.decide_request(
                conn,
                organization_id,
                request_id=request_id,
                approve=approve,
                by=str(actor.user_id),
                now=self._now(),
            )
        if request is None:
            return ReplySpec(text=EXPIRED)
        if not decided:
            status = request.get("status")
            if status in (rules.APPROVED, rules.REJECTED):
                return ReplySpec(text=ALREADY_DECIDED.format(outcome=status))
            return ReplySpec(text=EXPIRED)

        name, phone = str(request.get("name") or ""), str(request.get("phone") or "")
        company = actor.org_name or "The company"
        _log.info("team_join.decided org=%s approved=%s by=%s", organization_id, approve, actor.user_id)
        if not approve:
            try:
                await self._sender.send_text(phone, REJECTED_NOTICE.format(company=company))
            except Exception:  # noqa: BLE001 -- the decision stands either way
                _log.warning("team_join.reject_notice_failed org=%s", organization_id)
            return ReplySpec(text=REJECTED_DONE.format(name=name or "They"))

        if self._contact_share is None:
            return ReplySpec(text=FAILED)
        return await self._contact_share.start_join(
            actor,
            name=name,
            phone=phone,
            business_number=_digits((message.metadata or {}).get("display_phone_number")),
        )

    # -- internals ------------------------------------------------------------

    @staticmethod
    def _name_key(wa_id: str) -> str:
        return f"team_join:{wa_id}:name"

    def _wrong_key(self, wa_id: str) -> str:
        return f"team_join:{wa_id}:wrong:{self._now().date().isoformat()}"

    async def _say(self, wa_id: str, body: str) -> str:
        await self._sender.send_text(wa_id, body)
        return body


def _uuid(value: object) -> uuid.UUID | None:
    text = str(value or "")
    if text.startswith("ctx_user_"):
        text = text[len("ctx_user_") :]
    try:
        return uuid.UUID(text)
    except ValueError:
        return None
