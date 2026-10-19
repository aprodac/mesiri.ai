"""WhatsApp signup for numbers Mesiri doesn't know (SS-04).

Replaces the "this number isn't registered" dead end, when self-serve
signup is switched on (platform setting `self_serve.signup_enabled`, off by
default), with a one-minute conversation:

    Hi                       -> welcome  [Start free trial] [I'm in a company]
    Start free trial         -> "What's your company name?"
    Suresh Builders          -> "Which site are you working on now?"
    Green Villa, Kakkanad    -> company created, trial started, "send today's work"

The owner's name comes from their WhatsApp profile; only when the profile
has none is it asked. The company is created through the one create-company
step (application/organizations/create_company.py) with `start_as="trial"`,
`signup_source="whatsapp"` and the first site's automatic DPR on, then
projected so the owner's next message goes down the normal path.

"I'm in a company" points the person at their admin's join code (SS-05,
runtime/join_journey.py), or at being added by number.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from channel.replies import ListRow
from interactions.signup_state import SignupState, SignupStateStore
from mesiri.application.organizations.create_company import (
    CompanyCreationError,
    CreatedCompany,
    NewCompany,
    create_company,
)
from mesiri.application.organizations.signup_guard import (
    SignupAttempt,
    SignupRefused,
    check_signup,
)
from mesiri.domains.organizations.platform_settings import SELF_SERVE
from mesiri.infrastructure.postgres.repositories.platform_settings import (
    PostgresPlatformSettingsRepository,
)
from mesiri_contracts.assistant.enums import InputModality

if TYPE_CHECKING:
    from channel.whatsapp.outbound import WhatsAppSender
    from mesiri.infrastructure.postgres.database import PostgresDatabase

_log = logging.getLogger("mesiri.signup")

START_TRIAL_ID = "signup:start_trial"
IN_COMPANY_ID = "signup:in_company"

_CANCEL_WORDS = frozenset({"cancel", "stop", "exit", "quit"})
_NAME_MAX = 120

WELCOME_MESSAGE = (
    "👋 Hi{name}! Mesiri turns your site's WhatsApp updates into a daily progress "
    "report for you and your client.\n\n"
    "Want to try it free for your company?"
)
ASK_COMPANY = "Great! What's your company name?"
ASK_SITE = (
    "Which site are you working on now? A name and place is enough, e.g. *Green Villa, Kakkanad*."
)
ASK_OWNER_NAME = "And your name?"
IN_COMPANY_MESSAGE = (
    "Ask your company's Mesiri admin for their *join code*, then send it here, e.g. "
    "*JOIN ACME-4821*. Or ask them to add your number *+{wa_id}*."
)
TYPE_IT_MESSAGE = "Please type the answer as a message. {question}"
TOO_LONG_MESSAGE = "That's a bit long. Please keep it under {limit} characters. {question}"
CANCELLED_MESSAGE = "No problem, nothing was set up. Message *Hi* any time to start again."
ALREADY_SET_UP_MESSAGE = "This number is already set up on Mesiri. Send your update any time."
FAILED_MESSAGE = (
    "Sorry, something went wrong setting up your company. Please message *Hi* to try again."
)
DONE_MESSAGE = (
    "✅ *{company}* is set up on Mesiri, with your site *{site}*.\n\n"
    "Your free trial runs until *{trial_end}*.\n\n"
    "Send today's work here now, the way you'd tell your office, e.g. "
    "*10 masons, slab shuttering 2nd floor, 20 bags cement*. Text, voice notes and "
    "photos all work. Your daily report comes this evening."
)

_QUESTION = {"company": ASK_COMPANY, "site": ASK_SITE, "owner_name": ASK_OWNER_NAME}


class SignupJourney:
    def __init__(
        self,
        *,
        sender: WhatsAppSender,
        store: SignupStateStore,
        db: PostgresDatabase,
        now: Callable[[], dt.datetime] | None = None,
    ) -> None:
        self._sender = sender
        self._store = store
        self._db = db
        self._now = now or (lambda: dt.datetime.now(dt.UTC))

    async def signup_enabled(self) -> bool:
        """Fails closed: a settings read error keeps the old dead-end reply."""
        try:
            async with self._db.transaction() as conn:
                value = await PostgresPlatformSettingsRepository(conn).get(SELF_SERVE)
            return bool(value.get("signup_enabled"))
        except Exception:  # noqa: BLE001
            _log.exception("signup.settings_read_failed")
            return False

    async def handle(self, message: Any) -> str | None:
        """Answer an unregistered sender. Returns the reply text sent (for
        the message log), or None when signup is off and the caller should
        send its usual "not registered" reply."""
        if not await self.signup_enabled():
            return None

        wa_id = message.sender.wa_id
        tap = str((message.metadata or {}).get("interactive_reply_id") or "")
        text = (
            " ".join(str(message.text or "").split())
            if message.modality is InputModality.TEXT
            else ""
        )
        state = await self._store.get(wa_id)

        if tap == START_TRIAL_ID:
            # SS-09: refuse up front (an earlier trial, a foreign number, the
            # daily limit) rather than after three questions.
            refusal = await self._refusal(wa_id)
            if refusal is not None:
                await self._store.clear(wa_id)
                return await self._say(wa_id, refusal)
            await self._store.set(wa_id, SignupState(stage="company"))
            return await self._say(wa_id, ASK_COMPANY)
        if tap == IN_COMPANY_ID:
            await self._store.clear(wa_id)
            return await self._say(wa_id, IN_COMPANY_MESSAGE.format(wa_id=wa_id))

        if state is None or state.stage == "welcome":
            return await self._welcome(wa_id, message.sender.profile_name)

        if text.lower() in _CANCEL_WORDS:
            await self._store.clear(wa_id)
            return await self._say(wa_id, CANCELLED_MESSAGE)

        question = _QUESTION[state.stage]
        if not text:
            return await self._say(wa_id, TYPE_IT_MESSAGE.format(question=question))
        if len(text) > _NAME_MAX:
            return await self._say(
                wa_id, TOO_LONG_MESSAGE.format(limit=_NAME_MAX, question=question)
            )

        if state.stage == "company":
            await self._store.set(wa_id, SignupState(stage="site", company_name=text))
            return await self._say(wa_id, ASK_SITE)

        if state.stage == "site":
            state = SignupState(stage="site", company_name=state.company_name, site_name=text)
            owner_name = _clean_profile_name(message.sender.profile_name)
            if owner_name is None:
                await self._store.set(
                    wa_id,
                    SignupState(
                        stage="owner_name", company_name=state.company_name, site_name=text
                    ),
                )
                return await self._say(wa_id, ASK_OWNER_NAME)
            return await self._create(wa_id, state, owner_name)

        # owner_name
        return await self._create(wa_id, state, text)

    async def _refusal(self, wa_id: str) -> str | None:
        """The guardrails' refusal message for this number, or None to go
        ahead (SS-09). Fails closed, like signup_enabled."""
        try:
            async with self._db.transaction() as conn:
                try:
                    await check_signup(
                        conn, SignupAttempt(phone=wa_id, signup_source="whatsapp"), now=self._now()
                    )
                except SignupRefused as exc:
                    return str(exc)
        except Exception:  # noqa: BLE001
            _log.exception("signup.guard_failed wa_id=%s", wa_id)
            return FAILED_MESSAGE
        return None

    async def _welcome(self, wa_id: str, profile_name: str | None) -> str:
        await self._store.set(wa_id, SignupState(stage="welcome"))
        name = _clean_profile_name(profile_name)
        body = WELCOME_MESSAGE.format(name=f" {name}" if name else "")
        await self._sender.send_button(
            wa_id,
            body=body,
            buttons=[
                ListRow(id=START_TRIAL_ID, title="Start free trial"),
                ListRow(id=IN_COMPANY_ID, title="I'm in a company"),
            ],
        )
        return body

    async def _create(self, wa_id: str, state: SignupState, owner_name: str) -> str:
        new = NewCompany(
            name=state.company_name or "",
            owner_name=owner_name,
            owner_phone=wa_id,
            project_name=state.site_name,
            site_name=state.site_name,
            auto_dpr=True,
            start_as="trial",
            signup_source="whatsapp",
        )
        created: CreatedCompany | None = None
        refused: CompanyCreationError | None = None
        guard_refusal: SignupRefused | None = None
        try:
            async with self._db.transaction() as conn:
                try:
                    # SS-09 guardrails, in the same transaction as the create.
                    await check_signup(
                        conn, SignupAttempt(phone=wa_id, signup_source="whatsapp"), now=self._now()
                    )
                    created = await create_company(conn, new, now=self._now())
                except SignupRefused as exc:
                    # Caught inside, so the transaction commits the attempt row.
                    guard_refusal = exc
                except CompanyCreationError as exc:
                    # Raised before anything is written (validation and the
                    # taken-number check come first), so letting the empty
                    # transaction commit is safe -- and raising out of it
                    # would be mapped to a database error.
                    refused = exc
        except Exception:  # noqa: BLE001
            _log.exception("signup.create_failed wa_id=%s", wa_id)
            await self._store.clear(wa_id)
            return await self._say(wa_id, FAILED_MESSAGE)

        await self._store.clear(wa_id)
        if guard_refusal is not None:
            return await self._say(wa_id, str(guard_refusal))
        if refused is not None:
            _log.info("signup.refused wa_id=%s reason=%s", wa_id, refused)
            if refused.conflict:
                return await self._say(wa_id, ALREADY_SET_UP_MESSAGE)
            return await self._say(wa_id, FAILED_MESSAGE)

        assert created is not None
        _log.info(
            "signup.company_created org=%s owner=%s", created.organization_id, created.owner_user_id
        )
        return await self._say(
            wa_id,
            DONE_MESSAGE.format(
                company=created.name,
                site=state.site_name,
                trial_end=_format_day(created.trial_ends_at, created.timezone),
            ),
        )

    async def _say(self, wa_id: str, body: str) -> str:
        await self._sender.send_text(wa_id, body)
        return body


def _clean_profile_name(value: str | None) -> str | None:
    name = " ".join(str(value or "").split())
    if not name or len(name) > _NAME_MAX or not any(ch.isalpha() for ch in name):
        return None
    return name


def _format_day(moment: dt.datetime | None, timezone: str) -> str:
    if moment is None:
        return "further notice"
    try:
        local = moment.astimezone(ZoneInfo(timezone))
    except Exception:  # noqa: BLE001
        local = moment
    return f"{local.day} {local:%b}"
