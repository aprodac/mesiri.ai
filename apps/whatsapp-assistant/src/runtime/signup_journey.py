"""WhatsApp signup for numbers Mesiri doesn't know (SS-04).

Replaces the "this number isn't registered" dead end, when self-serve
signup is switched on (platform setting `self_serve.signup_enabled`, off by
default), with a one-minute conversation:

    Hi                       -> welcome  [Set up my company] [Join my team] [What is Mesiri?]
    Set up my company        -> "What's your company name?"
    Suresh Builders          -> "Which site are you working on now?"
    Green Villa, Kakkanad    -> confirm (company, site, your name) -> company created, trial started

The owner's name comes from their WhatsApp profile; only when the profile
has none (or they tapped Edit) is it asked. The company is created through the
one create-company step (application/organizations/create_company.py) with
`start_as="trial"`, `signup_source="whatsapp"` and the first site's automatic
DPR on, then projected so the owner's next message goes down the normal path.

"Join my team" points the person at their admin's join code (SS-05,
runtime/join_journey.py), or at being added by number, and keeps "Set up my
company" one tap away for an owner who tapped it by mistake.

SS-22, so a stranger is never stuck: the buttons say who they are for (everyone
is "in a company"); a reply that answers nothing gets a short nudge, not the
welcome again, and after NUDGE_LIMIT of those Mesiri goes quiet until a
greeting; "stop" works at every step; a number whose user is deactivated or
suspended hears that its access is paused, not the trial offer; a refused trial
offers "Join my team"; and a first message that was real work is told it was
not saved, so it is sent again once they are in.

SS-23, no loop after a refused trial: "Set up my company" is never offered
again to that number (it could only be refused again); "Talk to our team"
posts to the Mesiri team's WhatsApp group (once a day) so they can continue
the plan or fix the details, and the reply says plainly when that post failed.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from channel.onboarding_cards import (
    build_ready_card,
    build_welcome_card,
    detect_lang,
    render_card_png,
)
from channel.replies import ListRow
from interactions.signup_state import SignupState, SignupStateStore
from mesiri.application.identity.phone_numbers import whatsapp_number_taken
from mesiri.application.organizations.companies_overview import DEFAULT_SEND_TIME
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
from mesiri.domains.organizations.guardrails import PREVIOUS_TRIAL
from mesiri.domains.organizations.platform_settings import SELF_SERVE
from mesiri.infrastructure.postgres.repositories.platform_settings import (
    PostgresPlatformSettingsRepository,
)
from mesiri_contracts.assistant.enums import InputModality

if TYPE_CHECKING:
    from channel.receipt import ReceiptRenderer
    from channel.whatsapp.outbound import WhatsAppSender
    from mesiri.infrastructure.postgres.database import PostgresDatabase
    from runtime.team_notify import TeamNotifier

_log = logging.getLogger("mesiri.signup")

START_TRIAL_ID = "signup:start_trial"
IN_COMPANY_ID = "signup:in_company"
ABOUT_ID = "signup:about"
TEAM_ID = "signup:team"
CONFIRM_ID = "signup:confirm"
EDIT_ID = "signup:edit"

#: Typed stand-ins for the welcome buttons (SET-03): people type instead of tapping.
#: No bare "yes" / "ok": with three choices on the welcome, it answers none of them.
_START_WORDS = frozenset(
    {"start", "start free trial", "free trial", "start trial", "try", "trial", "set up", "setup",
     "set up my company", "setup my company", "new company", "my own company"}
)  # fmt: skip
_START_FIRST_WORDS = frozenset(
    {"start free trial", "free trial", "start trial", "set up my company", "setup my company"}
)
_IN_COMPANY_WORDS = frozenset(
    {"i'm in a company", "im in a company", "in a company", "join", "join my team", "join team"}
)
_ABOUT_WORDS = frozenset({"what is mesiri", "what is mesiri?", "what is this", "what is this?", "info"})
_TEAM_WORDS = frozenset(
    {"talk to our team", "talk to team", "talk to the team", "contact", "contact us", "support"}
)
#: A greeting at the welcome starts it again, even after Mesiri went quiet.
_GREETINGS = frozenset(
    {"hi", "hii", "hiii", "hello", "helo", "hlo", "hey", "hai", "namaste", "namaskaram"}
)
#: Replies at the welcome that answered nothing before Mesiri stops answering.
NUDGE_LIMIT = 2
_CONFIRM_WORDS = frozenset({"yes", "y", "ok", "okay", "confirm", "correct", "looks good", "create"})
_EDIT_WORDS = frozenset({"edit", "change", "no", "wrong", "redo"})
#: Greetings, answers and commands that are never a company or site name.
_NOT_A_NAME = frozenset(
    {
        "hi", "hii", "hello", "hey", "hai", "namaste", "namaskaram", "ok", "okay", "yes", "no",
        "y", "n", "start", "help", "test", "testing", "thanks", "thank you", "menu", "stop",
        "start free trial", "free trial", "trial", "join", "what", "why", "how", "who", "none",
        "na", "n/a", "nil", "company", "site", "my company", "my site", "name", "skip",
    }
)  # fmt: skip
_NAME_MAX_WORDS = 8

_CANCEL_WORDS = frozenset({"cancel", "stop", "exit", "quit"})
_NAME_MAX = 120

WELCOME_MESSAGE = (
    "👋 Hi{name}! Mesiri turns your site's WhatsApp updates into a daily progress "
    "report for you and your client.\n\n"
    "What brings you here?\n"
    "• *Set up my company*: you run the company; try Mesiri free.\n"
    "• *Join my team*: your company already uses Mesiri."
)
#: SS-22: a first message that was real work is not lost silently.
NOT_SAVED_NOTE = (
    "\n\n_Your message isn't saved yet. Once you're set up or added to your team, send it again._"
)
NUDGE_MESSAGE = "Please tap one of these, so I know how to help."
ABOUT_MESSAGE = (
    "Mesiri is for construction companies. Your site team sends updates here (text, voice "
    "notes or photos) and Mesiri keeps the records: labour, materials, work done and issues. "
    "Every evening you and your client get the daily report as a PDF.\n\n"
    "It's free to try."
)
ASK_COMPANY = "*Step 1 of 2*\nGreat! What's your company name?"
ASK_SITE = (
    "*Step 2 of 2*\nWhich site are you working on now? "
    "A name and place is enough, e.g. *Green Villa, Kakkanad*."
)
ASK_OWNER_NAME = "And your name?"
IN_COMPANY_MESSAGE = (
    "To join your company's team on Mesiri:\n"
    "• Send the *join code* your admin shares, e.g. *JOIN ACME-4821*, or\n"
    "• Ask your admin to add your number *+{wa_id}*.\n\n"
    "Once you're added, just message here."
)
NOT_A_NAME_MESSAGE = (
    "That doesn't look like a {what} name. Please send just the name, e.g. *{example}*. {question}"
)
CONFIRM_MESSAGE = (
    "Please check:\n*Company:* {company}\n*Site:* {site}\n*Your name:* {owner}\n\n"
    "This creates a *new* company on Mesiri. Shall I set it up?"
)
CONFIRM_REMINDER = "Tap *Looks good* to set this up, or *Edit* to change the names."
PAUSED_MESSAGE = (
    "This number's Mesiri access is paused. Please ask your company's admin to turn it back on."
)
#: SS-23: the guardrails' "Message us" sent people round in a loop; this says what can happen.
TRIAL_USED_MESSAGE = (
    "This number already used its free trial. Our team can help you continue with Mesiri or fix "
    "your company details. If your company already uses Mesiri, join its team instead."
)
TEAM_ASKED_MESSAGE = (
    "Done, I've told the Mesiri team. Someone will message you here soon. "
    "You can keep this chat open."
)
TEAM_ALREADY_MESSAGE = "Our team already has your request and will message you here soon."
TEAM_UNREACHABLE_MESSAGE = (
    "Sorry, I couldn't reach our team just now. Please tap *Talk to our team* again in a few minutes."
)
TEAM_POST = (
    "🙋 *+{wa_id}* ({name}) wants help on WhatsApp: {why}. "
    "Please message them back in their chat."
)
EDIT_MESSAGE = "No problem, let's redo it."
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

TRIAL_CAPTION = "Your free trial runs until *{trial_end}*."
#: Nothing is sent (logged as the reply): Mesiri waits for a greeting.
QUIET = ""

# WhatsApp buttons: at most 3, titles at most 20 characters.
_SETUP_BUTTON = ListRow(id=START_TRIAL_ID, title="Set up my company")
_JOIN_BUTTON = ListRow(id=IN_COMPANY_ID, title="Join my team")
_ABOUT_BUTTON = ListRow(id=ABOUT_ID, title="What is Mesiri?")
_TEAM_BUTTON = ListRow(id=TEAM_ID, title="Talk to our team")
_WELCOME_BUTTONS = [_SETUP_BUTTON, _JOIN_BUTTON, _ABOUT_BUTTON]
#: SS-23: after a refused trial "Set up my company" could only be refused again.
_REFUSED_BUTTONS = [_TEAM_BUTTON, _JOIN_BUTTON, _ABOUT_BUTTON]


def _refused(state: SignupState | None) -> bool:
    return bool(state and state.trial_refused)


def _at_welcome(state: SignupState | None, **changes: Any) -> SignupState:
    """Back at the welcome (nudges reset), keeping what SS-23 remembers about this number."""
    kept = {
        "trial_refused": _refused(state),
        "asked_team": bool(state and state.asked_team),
    }
    return SignupState(stage="welcome", **{**kept, **changes})

_QUESTION = {"company": ASK_COMPANY, "site": ASK_SITE, "owner_name": ASK_OWNER_NAME, "confirm": ""}
_NAME_KIND = {
    "company": ("company", "Suresh Builders"),
    "site": ("site", "Green Villa, Kakkanad"),
    "owner_name": ("person", "Suresh Kumar"),
}


def _not_a_name(text: str) -> bool:
    """SET-03: a greeting, a command, a question or a sentence is not a name."""
    plain = " ".join(text.lower().strip(" .!,;:-").split())
    return (
        sum(ch.isalpha() for ch in text) < 2
        or plain in _NOT_A_NAME
        or "?" in text
        or len(text.split()) > _NAME_MAX_WORDS
    )


def _looks_like_work(message: Any, lowered: str) -> bool:
    """SS-22: a first message that is more than a greeting (a site update, a voice
    note, a photo) gets told it was not saved, so it is sent again once they are in."""
    if message.modality is not InputModality.TEXT:
        return True
    return lowered not in _GREETINGS and len(lowered.split()) >= 2


class SignupJourney:
    def __init__(
        self,
        *,
        sender: WhatsAppSender,
        store: SignupStateStore,
        db: PostgresDatabase,
        renderer: ReceiptRenderer | None = None,
        notifier: TeamNotifier | None = None,
        now: Callable[[], dt.datetime] | None = None,
    ) -> None:
        # The onboarding cards' renderer; without one signup is all text.
        self._renderer = renderer
        # SS-23: "Talk to our team" posts to the Mesiri team's WhatsApp group.
        self._notifier = notifier
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
        lowered = text.lower().strip(" .!")
        state = await self._store.get(wa_id)

        # SS-22: a deactivated or suspended person is not a stranger: no trial offer
        # (their number is still theirs, so a trial would be refused at the end anyway).
        if await self._number_paused(wa_id):
            await self._store.clear(wa_id)
            return await self._say(wa_id, PAUSED_MESSAGE)

        if not tap and (state is None or state.stage == "welcome"):
            if lowered in (_START_WORDS if state is not None else _START_FIRST_WORDS):
                tap = START_TRIAL_ID
            elif lowered in _IN_COMPANY_WORDS:
                tap = IN_COMPANY_ID
            elif lowered in _ABOUT_WORDS:
                tap = ABOUT_ID
            elif lowered in _TEAM_WORDS:
                tap = TEAM_ID
        if not tap and state is not None and state.stage == "confirm":
            if lowered in _CONFIRM_WORDS:
                tap = CONFIRM_ID
            elif lowered in _EDIT_WORDS:
                tap = EDIT_ID

        if tap == START_TRIAL_ID:
            # SS-09: refuse up front (an earlier trial, a foreign number, the
            # daily limit) rather than after three questions.
            refusal = await self._refusal(wa_id)
            if refusal is not None:
                # SS-22 / SS-23: no dead end and no loop: the person may be joining a team,
                # or need the team (continue, fix details); setup is not offered again.
                text, reason = refusal
                await self._store.set(wa_id, _at_welcome(state, trial_refused=True))
                body = TRIAL_USED_MESSAGE if reason == PREVIOUS_TRIAL else text
                return await self._buttons(wa_id, body, [_TEAM_BUTTON, _JOIN_BUTTON])
            await self._store.set(wa_id, SignupState(stage="company"))
            return await self._say(wa_id, ASK_COMPANY)
        if tap == IN_COMPANY_ID:
            # Kept at the welcome, so an owner who tapped it by mistake is one tap from setup
            # (or from the team, once a trial was refused).
            await self._store.set(wa_id, _at_welcome(state))
            other = _TEAM_BUTTON if _refused(state) else _SETUP_BUTTON
            return await self._buttons(wa_id, IN_COMPANY_MESSAGE.format(wa_id=wa_id), [other])
        if tap == ABOUT_ID:
            await self._store.set(wa_id, _at_welcome(state))
            first = _TEAM_BUTTON if _refused(state) else _SETUP_BUTTON
            return await self._buttons(wa_id, ABOUT_MESSAGE, [first, _JOIN_BUTTON])
        if tap == TEAM_ID:
            return await self._ask_team(wa_id, state, message.sender.profile_name)

        if tap in (CONFIRM_ID, EDIT_ID):
            if state is None or state.stage != "confirm":
                return await self._welcome(wa_id, message.sender.profile_name)
            if tap == EDIT_ID:
                # The name is asked too: the WhatsApp profile's may be a nickname.
                await self._store.set(wa_id, SignupState(stage="company", ask_name=True))
                await self._say(wa_id, EDIT_MESSAGE)
                return await self._say(wa_id, ASK_COMPANY)
            return await self._create(wa_id, state, state.owner_name or "")

        # SS-22: "stop" works at every step, the welcome included.
        if lowered in _CANCEL_WORDS:
            await self._store.clear(wa_id)
            return await self._say(wa_id, CANCELLED_MESSAGE)

        if state is None:
            note = NOT_SAVED_NOTE if _looks_like_work(message, lowered) else ""
            return await self._welcome(wa_id, message.sender.profile_name, note=note, said=text)
        if state.stage == "welcome":
            # SS-22: a reply that answers nothing gets a nudge, never the whole welcome
            # again; after NUDGE_LIMIT of them Mesiri waits for a greeting.
            if lowered in _GREETINGS:
                return await self._welcome(wa_id, message.sender.profile_name, said=text, state=state)
            if state.nudges >= NUDGE_LIMIT:
                return QUIET
            await self._store.set(wa_id, _at_welcome(state, nudges=state.nudges + 1))
            buttons = _REFUSED_BUTTONS if _refused(state) else _WELCOME_BUTTONS
            return await self._buttons(wa_id, NUDGE_MESSAGE, buttons)

        if state.stage == "confirm":
            return await self._confirm_prompt(wa_id, state, reminder=True)

        question = _QUESTION[state.stage]
        if not text:
            return await self._say(wa_id, TYPE_IT_MESSAGE.format(question=question))
        if len(text) > _NAME_MAX:
            return await self._say(
                wa_id, TOO_LONG_MESSAGE.format(limit=_NAME_MAX, question=question)
            )

        what, example = _NAME_KIND[state.stage]
        if _not_a_name(text):
            return await self._say(
                wa_id,
                NOT_A_NAME_MESSAGE.format(what=what, example=example, question=question),
            )

        if state.stage == "company":
            await self._store.set(
                wa_id, SignupState(stage="site", company_name=text, ask_name=state.ask_name)
            )
            return await self._say(wa_id, ASK_SITE)

        if state.stage == "site":
            owner_name = None if state.ask_name else _clean_profile_name(message.sender.profile_name)
            if owner_name is None:
                await self._store.set(
                    wa_id,
                    SignupState(
                        stage="owner_name", company_name=state.company_name, site_name=text
                    ),
                )
                return await self._say(wa_id, ASK_OWNER_NAME)
        else:  # owner_name
            owner_name = text
        return await self._confirm_prompt(
            wa_id,
            SignupState(
                stage="confirm",
                company_name=state.company_name,
                site_name=state.site_name if state.stage == "owner_name" else text,
                owner_name=owner_name,
            ),
        )

    async def _confirm_prompt(
        self, wa_id: str, state: SignupState, *, reminder: bool = False
    ) -> str:
        """SET-03: show what will be created and let them fix it before it is."""
        await self._store.set(wa_id, state)
        body = CONFIRM_MESSAGE.format(
            company=state.company_name, site=state.site_name, owner=state.owner_name
        )
        if reminder:
            body = f"{CONFIRM_REMINDER}\n\n{body}"
        await self._sender.send_button(
            wa_id,
            body=body,
            buttons=[
                ListRow(id=CONFIRM_ID, title="Looks good"),
                ListRow(id=EDIT_ID, title="Edit"),
            ],
        )
        return body

    async def _refusal(self, wa_id: str) -> tuple[str, str] | None:
        """The guardrails' refusal for this number as (message, reason), or None
        to go ahead (SS-09). Fails closed, like signup_enabled."""
        try:
            async with self._db.transaction() as conn:
                try:
                    await check_signup(
                        conn, SignupAttempt(phone=wa_id, signup_source="whatsapp"), now=self._now()
                    )
                except SignupRefused as exc:
                    return str(exc), exc.reason
        except Exception:  # noqa: BLE001
            _log.exception("signup.guard_failed wa_id=%s", wa_id)
            return FAILED_MESSAGE, "error"
        return None

    async def _ask_team(self, wa_id: str, state: SignupState | None, profile_name: str | None) -> str:
        """SS-23: tell the Mesiri team in their WhatsApp group; they reply in this chat (the
        person just messaged, so WhatsApp lets them). Once a day; an unsent post says so."""
        if state is not None and state.asked_team:
            return await self._say(wa_id, TEAM_ALREADY_MESSAGE)
        why = "this number already used its free trial" if _refused(state) else "asked for help at signup"
        name = _clean_profile_name(profile_name) or "no WhatsApp name"
        sent = self._notifier is not None and await self._notifier.post(
            TEAM_POST.format(wa_id=wa_id, name=name, why=why)
        )
        if not sent:
            _log.warning("signup.team_unreachable wa_id=%s", wa_id)
            return await self._say(wa_id, TEAM_UNREACHABLE_MESSAGE)
        _log.info("signup.team_asked wa_id=%s refused=%s", wa_id, _refused(state))
        await self._store.set(wa_id, _at_welcome(state, asked_team=True))
        return await self._say(wa_id, TEAM_ASKED_MESSAGE)

    async def _number_paused(self, wa_id: str) -> bool:
        """SS-22: this number belongs to a user Mesiri didn't resolve as a sender, i.e.
        one who is deactivated or suspended (an active one never reaches signup).
        Fails open: a read error shows the usual welcome, as before."""
        try:
            async with self._db.transaction() as conn:
                return await whatsapp_number_taken(conn, wa_id)
        except Exception:  # noqa: BLE001
            _log.exception("signup.paused_check_failed wa_id=%s", wa_id)
            return False

    async def _buttons(self, wa_id: str, body: str, buttons: list[ListRow]) -> str:
        await self._sender.send_button(wa_id, body=body, buttons=buttons)
        return body

    async def _welcome(
        self,
        wa_id: str,
        profile_name: str | None,
        *,
        note: str = "",
        said: str = "",
        state: SignupState | None = None,
    ) -> str:
        if _refused(state):
            # SS-23: a greeting after a refused trial is not offered setup again.
            await self._store.set(wa_id, _at_welcome(state))
            return await self._buttons(wa_id, TRIAL_USED_MESSAGE, _REFUSED_BUTTONS)
        await self._store.set(wa_id, SignupState(stage="welcome"))
        name = _clean_profile_name(profile_name)
        body = WELCOME_MESSAGE.format(name=f" {name}" if name else "") + note
        buttons = _WELCOME_BUTTONS
        # Card 1 rides as the buttons' header image; if it can't be made or
        # sent, the same message goes out as text and buttons. Malayalam when they wrote it.
        card = await render_card_png(self._renderer, build_welcome_card(detect_lang(said)))
        if card is None or not await self._sender.send_button(
            wa_id, body=body, buttons=buttons, header_image=card, shows="Welcome card: set up Mesiri for your company"
        ):
            await self._sender.send_button(wa_id, body=body, buttons=buttons)
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
        trial_end = _format_day(created.trial_ends_at, created.timezone)
        done = DONE_MESSAGE.format(company=created.name, site=state.site_name, trial_end=trial_end)
        # Card 2 replaces the plain text; the text is the fallback.
        card = await render_card_png(
            self._renderer,
            build_ready_card(
                company=created.name,
                site_name=state.site_name or "",
                report_time=_clock_label(DEFAULT_SEND_TIME),
                lang=detect_lang(state.company_name, state.site_name),
            ),
        )
        if card is not None and await self._sender.send_image(
            wa_id,
            card,
            caption=TRIAL_CAPTION.format(trial_end=trial_end),
            shows=f"Ready card: {created.name} is set up, trial until {trial_end}",
        ):
            return done
        return await self._say(wa_id, done)

    async def _say(self, wa_id: str, body: str) -> str:
        await self._sender.send_text(wa_id, body)
        return body


def _clean_profile_name(value: str | None) -> str | None:
    name = " ".join(str(value or "").split())
    if not name or len(name) > _NAME_MAX or not any(ch.isalpha() for ch in name):
        return None
    return name


def _clock_label(hhmm: str) -> str:
    """"21:00" -> "9 pm"."""
    hour, _, minute = hhmm.partition(":")
    h = int(hour)
    suffix = "am" if h < 12 else "pm"
    return f"{h % 12 or 12}{'' if minute in ('', '00') else ':' + minute} {suffix}"


def _format_day(moment: dt.datetime | None, timezone: str) -> str:
    if moment is None:
        return "further notice"
    try:
        local = moment.astimezone(ZoneInfo(timezone))
    except Exception:  # noqa: BLE001
        local = moment
    return f"{local.day} {local:%b}"
