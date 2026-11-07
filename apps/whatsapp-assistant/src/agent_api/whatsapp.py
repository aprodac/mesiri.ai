"""WA-119 / WA-124: the API agent on WhatsApp (``assistant_mode`` = ``api``).

For a company in this mode, a message from a known sender comes here after the journey has
resolved the sender and checked the company (unknown number, suspended company and trial cap
keep their own replies): text, a voice note (transcribed first), a photo or document (read by
the vision step first, e.g. a bill), and its own button taps.

Fewest taps: everything prepared in a turn goes into one ready list under the reply with ONE
Save button; a question the model must ask comes with its options as buttons (one tap). Facts
the model needs to start (the person's projects and sites, the materials and units) are given
up front, read through the API before the model runs, so it never spends a round looking them up
or asks "which site?" when there is one.

Memory: today and the two days before (``memory.DayMemory``), written after the reply is sent.
The waiting entries are kept per person in Redis for a day.
"""

from __future__ import annotations

import asyncio
import dataclasses
import datetime as dt
import json
import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from agent_api.feedback import TELL_THE_TEAM
from channel.replies import ListRow, ReplySpec
from mesiri_ai.greeting_classifier import is_greeting_trigger
from mesiri_ai.models import ToolSpec
from mesiri_contracts.assistant.enums import InputModality
from runtime.agent.reply_text import without_save_prompt
from runtime.ai_outage import (
    BUDGET_REPLY,
    GAVE_UP_REPLY,
    QUEUED_REPLY,
    QUICK_RETRY_PAUSE_SECONDS,
    RESEND_REPLY,
    AIUnavailableError,
    FallBackToClassic,
    is_budget_error,
    is_outage_error,
    reply_for_attempt,
    retry_attempt,
)
from runtime.release_notes import request_ref
from runtime.team_notify import poke_watch_soon

from . import bill_photo
from .agent import (
    DONT_KNOW,
    LANGUAGE_LINES,
    PERSON_TOOL,
    SAVE_AS_SAID,
    SIZE_UNKNOWN,
    SIZE_WAY_OUT,
    SOP,
    TELL_SIZE,
    UNIT_UNSETTLED,
    UPDATE_MATERIAL_TOOL,
    ApiAgent,
    PendingWrite,
    Places,
    WriteResult,
    _amount,
    _detail,
    _place_names,
    confirm,
    held,
    last_reported,
    question_left_open,
    remember_saves,
    size_question,
)
from .app import build_api_app
from .client import Actor, ApiClient, new_idempotency_key
from .memory import DayMemory, tools_version
from .receipts import preview_card
from .record_links import record_link, with_links
from .reply_guard import without_ids
from .tools import build_tools
from .units import is_stock_unit_refusal, plain_refusal, unit_rows

_log = logging.getLogger(__name__)

#: WA-136: the journey's step timer for the message being handled (``StepTimer.lap``), so v3's own
#: steps show in the perf report instead of one "_unaccounted_ms". Per message (concurrent turns).
_LAP: ContextVar[Callable[[str], None] | None] = ContextVar("agent_api_lap", default=None)
#: [221]: True while a kept message (one the AI pause made Mesiri give up on) is answered before the new one.
_REPLAYING: ContextVar[bool] = ContextVar("agent_api_replaying", default=False)
#: [221]: messages kept per person after an AI pause (oldest first); more are not kept.
KEPT_MAX = 5


def _lap(name: str) -> None:
    lap = _LAP.get()
    if lap is not None:
        try:
            lap(name)
        except Exception:  # noqa: BLE001 -- timing never breaks a message
            pass

MODE = "api"
EVENT_SOURCE = "agent_api"
STATE_TTL_SECONDS = 24 * 3600
#: [267]: a message answered here is marked by its WhatsApp id for this long. A worker restart (a deploy) re-runs a job
#: that was cut off after its reply went out; the re-run finds the mark and stays quiet, so one tap is answered once.
ANSWERED_TTL_SECONDS = 6 * 3600
#: WA-166: a person's own sizes outlive the day's state; renewed whenever they tell another.
SIZES_TTL_SECONDS = 180 * 24 * 3600
SAVE_PREFIX = "apiag:save:"
CANCEL_PREFIX = "apiag:cancel:"
#: WA-208: "✏️ Edit" on a ready list ("apiag:edit:<batch>"), and the line picked from a longer list
#: ("apiag:editline:<batch>:<number>").
EDIT_PREFIX = "apiag:edit:"
EDIT_LINE_PREFIX = "apiag:editline:"
#: WA-210: "🗑️ Remove" one line of a ready list ("apiag:remove:<batch>:<number>"), offered with its Edit question.
REMOVE_PREFIX = "apiag:remove:"
OPTION_PREFIX = "apiag:opt:"
#: WA-168: an admin's one tap confirming a size proposed for the company ("apiag:size:<request id>").
SIZE_PREFIX = "apiag:size:"
#: WA-146: one tap on why a ready list was cancelled ("apiag:why:<reason>").
WHY_PREFIX = "apiag:why:"
CANCEL_REASONS = {"site": "wrong site", "amount": "wrong amount or quantity", "other": "something else"}
#: Button titles (WhatsApp: at most 3 buttons, 20 characters each), per language; English otherwise.
_REASON_TITLES = {
    "english": {"site": "Wrong site", "amount": "Wrong amount", "other": "Something else"},
    "manglish": {"site": "Site thettu", "amount": "Ennam thettu", "other": "Vere enthenkilum"},
    "malayalam": {"site": "സൈറ്റ് തെറ്റ്", "amount": "എണ്ണം തെറ്റ്", "other": "വേറെ എന്തെങ്കിലും"},
    "hindi": {"site": "गलत साइट", "amount": "गलत मात्रा", "other": "कुछ और"},
    "hinglish": {"site": "Site galat", "amount": "Quantity galat", "other": "Kuch aur"},
}
#: A tool round can read several things; a mixed voice note needs room.
MAX_STEPS = 10
#: The SAVED card is drawn within this many seconds, or left out (as classic's RECEIPT_TIMEOUT_S).
RECEIPT_SECONDS = 4.0
#: WA-210: the TO SAVE preview card is drawn within this many seconds, or the list goes out as text (it sits on the
#: reply path, so it gets less time than the SAVED card, which went after the reply).
PREVIEW_SECONDS = 3.0
#: Today's recorded entries given to the model up front (WA-127).
TODAY_ENTRIES = 40
#: The materials and units of a company, read once per this many seconds.
CATALOG_SECONDS = 300
#: WA-118: a call is a live conversation, so fewer rounds and a shorter wait than a message.
CALL_MAX_STEPS = 5
CALL_TIMEOUT_SECONDS = 12.0
CALL_RULES = """

This is a live phone call, not WhatsApp. What you write is spoken aloud. One or two short spoken
sentences, no lists, no symbols, no formatting, no ids. Prepare entries as usual: they go to their
WhatsApp with a Save button, so say in one line that it is ready on WhatsApp to save; nothing saves
on the call, and you cannot save or cancel entries here. When they ask for a list or report as a
PDF or on WhatsApp, look it up, call send_pdf, then say it is sent."""
SEND_PDF = "send_pdf"
PDF_MAX_ROWS = 200
_SEND_PDF_TOOL = ToolSpec(name=SEND_PDF, description=(
    "Send a list or report to the person's WhatsApp as a PDF, from what the tools returned. "
    "Write the title, columns and rows in English."), parameters={
    "type": "object", "required": ["title", "columns", "rows"],
    "properties": {"title": {"type": "string"},
                   "columns": {"type": "array", "items": {"type": "string"}},
                   "rows": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}}},
})
#: The speech-to-text gives script; a reply in Latin letters would be read badly aloud.
SPOKEN_LANGUAGE = {"manglish": "malayalam", "hinglish": "hindi"}

COULD_NOT_HEAR = "I couldn't hear that voice note. Please send it again or type it."
#: WA-208: the Edit button and its questions.
EDIT_TITLE = "✏️ Edit"
EDIT_WHICH = "Which line do you want to change?"
EDIT_PICK = "Choose the line"
EDIT_ASK = "What should *{item}* be? Send the right figure, typed or as a voice note."
#: WA-210: delete one line from the ready list (the Edit question offers it).
REMOVE_TITLE = "🗑️ Remove"
REMOVED = "Removed *{item}*."
REMOVED_ALL = "Removed *{item}*. Nothing is waiting to save now."
#: WA-210: after a Save of a list shown on the preview card, all saved: the card already showed every line.
SAVED_SHORT = "✅ Saved."
COULD_NOT_READ = "I couldn't read that photo. Please send it again, or type what it is."
NOT_NOW = "I couldn't work on that just now. Please send it again in a minute."
NOTHING_WAITING = "There is nothing waiting to save."
#: [267]: a button on a card that was already saved (the same tap run again after a restart, or a second tap):
#: what happened, with the record links, never "nothing waiting to save" (it read as "it saved without me").
ALREADY_SAVED = "✅ Already saved."
CANCELLED = "Cancelled. Nothing was saved."
#: WA-169: the chosen-language read never holds a reply up longer than this (it runs beside the facts).
CHOSEN_LANGUAGE_TIMEOUT_S = 0.8
#: The chosen language could not be read this turn: the last one known stands.
_UNREAD = object()
#: TM-69: the open-requests read never holds a reply up longer than this.
OPEN_REQUESTS_TIMEOUT_S = 0.8
#: WA-148: how much of the facts a turn's trace keeps (for replays on the real model).
FACTS_IN_TRACE = 6000
CANCELLED_WHY = "Cancelled. Nothing was saved. What was wrong? (one tap helps us fix it)"


class _Answered(Exception):
    """The outage reply was already sent and the message closed (no retry left): nothing more to send."""


#: The outage wording by its English text (``reply_for_attempt`` picks the text).
#: [221]: v3 keeps a message it could not do and answers it before the person's next one.
KEPT_REPLY = ("Sorry, I couldn't do that message yet — nothing was saved. I've kept it: I'll do it as soon as you send "
              "your next message.")
_OUTAGE_LINES = {QUEUED_REPLY: "outage.queued", BUDGET_REPLY: "outage.budget", GAVE_UP_REPLY: "outage.gave_up",
                 RESEND_REPLY: "outage.resend", KEPT_REPLY: "outage.kept"}


NOTHING_HELD = "I haven't got anything ready to save yet. Please send it again, with what's missing."
PRESS_SAVE = "Tap *Save* to record these."
READY_HEADING = "*Ready to save:*"
#: [264]: a card that holds only a report send says Send, not Save.
READY_SEND_HEADING = "*Ready to send:*"
PRESS_SEND = "Tap *Send* and it goes out in about a minute."
LATE_ANSWER = "⏱️ Your {kind} from {time}:"
REPORT_SENT = "📤 Report sent: {line}. It reaches the people who get the daily report in about a minute."
SEND_TITLE = "Send"


def _in_with(language: str | None, key: str, english: str, **values: str) -> str:
    """``_in`` for a line with blanks ({item}), filled in."""
    if not language or language == "english":
        return english.format(**values)
    from runtime.agent.wording import say

    return say(key, language, **values)


def _in(language: str | None, key: str, english: str) -> str:
    """The line in the person's language (the English constant for English or unknown)."""
    if not language or language == "english":
        return english
    from runtime.agent.wording import say

    return say(key, language)


class ApiWhatsApp:
    def __init__(self, *, provider: Any, database: Any, redis: Any,
                 send: Callable[[ReplySpec, str], Awaitable[Any]],
                 transcribe: Callable[[Any], Awaitable[tuple[str, str | None, str | None]]] | None,
                 message_logger: Any, trace_logger: Any | None = None, app: Any | None = None,
                 describe: Callable[..., Awaitable[str | None]] | None = None,
                 sessions: Any | None = None, send_document: Callable[..., Awaitable[Any]] | None = None,
                 receipt_builder: Any | None = None, send_image: Callable[..., Awaitable[Any]] | None = None) -> None:
        self._redis = redis
        #: TM-69: read for the person's open requests (the team is fixing what they told us).
        self._database = database
        #: WA-132: the SAVED card after a Save (the channel.receipt builder classic uses).
        self._receipts = receipt_builder
        self._send_image = send_image
        #: TM-28: messages that passed a request on; poked after they are answered.
        self._requested: set[str] = set()
        self._just_saved: dict[str, list[WriteResult]] = {}
        #: WA-210: Save taps whose list was on a preview card: no SAVED card after them.
        self._previewed_saves: dict[str, bool] = {}
        self._send_document = send_document
        self._send = send
        self._transcribe = transcribe
        self._describe = describe
        self._log_store = message_logger
        self._trace = trace_logger
        self._app = app if app is not None else build_api_app(database)
        tools = build_tools(self._app.openapi())
        # WA-157: replies are remembered with the tools Mesiri had; an older tool set's "I can't" is read as possibly stale.
        self._memory = DayMemory(sessions, redis, version=tools_version(tools))
        self._agent = ApiAgent(provider, tools, max_steps=MAX_STEPS, capability="api_agent")
        self._call_agent = ApiAgent(provider, tools, sop=SOP + CALL_RULES, max_steps=CALL_MAX_STEPS,
                                    timeout_seconds=CALL_TIMEOUT_SECONDS, capability="api_agent")
        self._catalog: dict[str, tuple[float, str]] = {}
        self._material_names_by_org: dict[str, list[str]] = {}
        #: [221]: per new message, the times of the kept messages answered just before it.
        self._kept_answered: dict[str, list[str]] = {}
        #: WA-246: per voice note, whether its reply starts with what was heard (from the same preferences read).
        self._heard_shown: dict[str, bool] = {}

    # -- entry point -----------------------------------------------------------------------

    async def handle(self, message: Any, ctx: Any, *, lap: Callable[[str], None] | None = None) -> bool:
        """True when the message was answered here; False leaves it to the journey. Raises
        ``AIUnavailableError`` (the worker retries) or ``FallBackToClassic`` (the journey runs classic).
        ``lap``: the journey's step timer (WA-136); v3's steps are recorded as ``v3_*`` laps."""
        token = _LAP.set(lap)
        try:
            return await self._handle(message, ctx)
        except _Answered:
            return True
        finally:
            _LAP.reset(token)

    async def _handle(self, message: Any, ctx: Any) -> bool:
        tap = str((message.metadata or {}).get("interactive_reply_id") or "")
        if (retry_attempt.get() or 1) > 1 and not _REPLAYING.get() and await self._was_answered(message):
            # [267] (6 Nov 13:10, Ilan: Save tapped once during a deploy; it saved and "Saved" went out, the worker was
            # restarted before the job ended, and the re-run answered the same tap "There is nothing waiting to save").
            _log.info("agent_api.rerun_already_answered message_id=%s", getattr(message, "message_id", None))
            await _safe(self._log_store.mark_completed(correlation_id=message.correlation_id))
            return True
        if not tap and not _REPLAYING.get() and (retry_attempt.get() or 1) == 1:
            await self._answer_kept(ctx, message.correlation_id)
        said = (message.text or "").strip()
        if tap.startswith(WHY_PREFIX):
            said = "(tapped why it was cancelled)"
            reply = await self._on_why(tap[len(WHY_PREFIX):], message, ctx)
        elif tap.startswith((SAVE_PREFIX, CANCEL_PREFIX)):
            said = "(tapped Save)" if tap.startswith(SAVE_PREFIX) else "(tapped Cancel)"
            started = time.monotonic()
            reply = await self._on_tap(tap, ctx, message.correlation_id)
            if tap.startswith(SAVE_PREFIX):
                # 2 Nov (Ilan's loop: three refused Saves left no trace at all): every Save's outcome is traced, so
                # the team bot sees the same line refused twice and looks at once (TM-45).
                results = self._just_saved.get(message.correlation_id) or []
                await self._trace_turn(message, {"text": said, "calls": [], "save_results": [
                    {"summary": r.pending.summary, "tool": r.pending.tool, "status": r.status,
                     **({} if r.ok else {"reason": _detail(r.body)[:300]})} for r in results]}, started)
            if tap.startswith(CANCEL_PREFIX) and reply.buttons:
                # WA-147: every Cancel is counted (the weekly digest, the production watch), reason or not.
                cancelled = (await self._state(ctx)).get("cancelled") or []
                await self._trace_turn(message, {"text": said, "calls": [], "cancelled": cancelled}, started)
        elif tap.startswith((EDIT_PREFIX, EDIT_LINE_PREFIX)):
            said = "(tapped Edit)"
            reply = await self._on_edit(tap, ctx)
        elif tap.startswith(REMOVE_PREFIX):
            said = "(tapped Remove)"
            reply = await self._on_remove(tap, ctx)
        elif tap.startswith(SIZE_PREFIX):
            said = "(tapped to confirm a size)"
            reply = await self._on_size_tap(tap[len(SIZE_PREFIX):], ctx)
        elif tap.startswith(OPTION_PREFIX) and said:
            reply = await self._on_words(said, message, ctx)
        elif message.modality is InputModality.TEXT and said:
            reply = await self._on_words(said, message, ctx)
        elif message.modality is InputModality.VOICE and self._transcribe is not None:
            said = await self._voice(message, ctx)
            _lap("v3_transcribe")
            reply = (await self._on_words(said, message, ctx) if said
                     else ReplySpec(text=_in(await self._language_of_sender(ctx), "voice.cant_hear", COULD_NOT_HEAR)))
        elif message.modality in (InputModality.IMAGE, InputModality.DOCUMENT) and self._describe is not None:
            said = await self._photo(message, ctx)
            _lap("v3_vision")
            key = getattr(getattr(message, "media", None), "object_key", None)
            if said:
                reply = await self._on_words(said, message, ctx, photo_key=key)
            else:
                reply = ReplySpec(text=_in(await self._language_of_sender(ctx), "photo.cant_read", COULD_NOT_READ))
                # A screenshot captioned "mesiri bad ux" still reaches the team when the photo can't be read.
                if calls := command_call("", message, ""):
                    await self._trace_turn(message, {"text": f"(sent a photo: {message.text})", "calls": calls},
                                           time.monotonic())
                    self._requested.add(message.correlation_id)
        else:
            return False
        # WA-210: a ready list goes out on its TO SAVE card (the header of the Save / Edit / Cancel message).
        reply = await self._with_preview(reply, ctx, message.correlation_id)
        _lap("v3_preview")
        heard_shown = self._heard_shown.pop(message.correlation_id, False)
        if message.modality is InputModality.VOICE and said and heard_shown:
            # WA-209 (4 Nov: "5 chaak" heard as 30, unseen until Save): what was heard comes first, so a misheard
            # number is caught on the list, where Edit fixes it. WA-246 (Ilan, 5 Nov): only where it is switched
            # on (the person's own switch, else the company's; off by default), read with the reply language.
            reply = dataclasses.replace(reply, text=heard_line(said) + reply.text)
        if (retry_attempt.get() or 1) > 1 or _REPLAYING.get():
            # [221] (5 Nov 12:36 and 12:38: Ilan's voice notes from 12:15 and 12:18, kept through the AI pause, were
            # answered 20 minutes later with no sign of what the answer was about): a late answer says which message.
            reply = dataclasses.replace(reply, text=late_line(message, ctx, await self._reply_language(ctx))
                                        + reply.text)
        reply = latin_reply(reply, await self._reply_language(ctx))
        await self._send(reply, message.sender.wa_id)
        await self._mark_answered(message)  # [267]: a re-run of this job (a restart) never answers it again
        _lap("v3_send")
        await self._send_saved_card(message, ctx)  # after the "Saved" line: the reply never waits for it
        _lap("v3_saved_card")
        for invite in person_invites(self._just_saved.get(message.correlation_id) or [], ctx, message):
            # WEB-71: someone added by number never messaged Mesiri, so WhatsApp won't let Mesiri write first: the
            # owner gets the message to forward, on its own so it forwards cleanly.
            await _safe(self._send(ReplySpec(text=invite), message.sender.wa_id))
        await _safe(self._log_store.log_reply(correlation_id=message.correlation_id, reply=reply.text))
        await _safe(self._log_store.mark_completed(correlation_id=message.correlation_id))
        _lap("v3_log")
        if message.correlation_id in self._requested:
            # TM-28: after the reply and the "answered" mark, so the team bot can read this request at once.
            self._requested.discard(message.correlation_id)
            poke_watch_soon(message.correlation_id)
        if said:
            await self._memory.remember(ctx, said, for_memory(reply.text, await self._card_lines(reply, ctx)))
            _lap("v3_memory_write")
        return True

    @staticmethod
    def _answered_key(message: Any) -> str | None:
        message_id = str(getattr(message, "message_id", "") or "")
        return f"agent_api_answered:{message_id}" if message_id else None

    async def _was_answered(self, message: Any) -> bool:
        """[267]: this WhatsApp message was already answered by an earlier run of its job."""
        key = self._answered_key(message)
        if key is None:
            return False
        try:
            return bool(await self._redis.get_json(key))
        except Exception:  # noqa: BLE001 -- unreadable: run it (a tap's batch check still stops a second save)
            return False

    async def _mark_answered(self, message: Any) -> None:
        key = self._answered_key(message)
        if key is None:
            return
        try:
            await self._redis.set_json(key, {"at": time.time()}, ttl_seconds=ANSWERED_TTL_SECONDS)
        except Exception:  # noqa: BLE001 -- the reply already went out
            _log.warning("agent_api.answered_unmarked message_id=%s", key, exc_info=True)

    async def _send_saved_card(self, message: Any, ctx: Any) -> None:
        """WA-132: the green SAVED card of what this message saved (a Save tap, or "save it"), as
        classic sends it after the "Saved" line. Never raises."""
        results = self._just_saved.pop(message.correlation_id, None)
        if self._previewed_saves.pop(message.correlation_id, False):
            return  # WA-210: they saw the list on its preview card before Save; a second card adds nothing
        if not results or self._receipts is None or self._send_image is None:
            return
        from .receipts import saved_card

        client = ApiClient(_actor(ctx), app=self._app)
        try:
            image = await asyncio.wait_for(
                saved_card(self._receipts, results, ctx, client, message.correlation_id), timeout=RECEIPT_SECONDS)
            if image:
                await self._send_image(message.sender.wa_id, image,
                                       shows="Saved card: what was just saved (green SAVED card)")
        except Exception:  # noqa: BLE001 -- the Save and its line already went through
            _log.warning("agent_api.saved_card_not_sent user=%s", ctx.user_id, exc_info=True)
        finally:
            await client.close()

    async def _voice(self, message: Any, ctx: Any) -> str:
        hint = await self._speech_hint(ctx)
        try:
            transcript, translated, _ = await self._transcribe(message, hint=hint)  # type: ignore[misc,call-arg]
        except Exception as exc:  # noqa: BLE001 -- said plainly, never silence
            _log.exception("agent_api.transcribe_failed user=%s", ctx.user_id)
            if is_outage_error(exc):
                await self._outage(message, ctx, "", exc)
            return ""
        words = (transcript or translated or "").strip()
        english = (translated or "").strip()
        if words:
            # WEB-58 (5 Nov: 0 of 53 voice notes had their words or English kept): the speech step already gives both
            # (one call); they go on the message, as classic kept them, for the dashboard's Live and message log. In the
            # background: nothing waits for it, and a failed write is only logged.
            _in_background(self._log_store.update_body_text(
                correlation_id=message.correlation_id, body_text=words,
                translated_text=english if english and english.casefold() != words.casefold() else None))
        return words

    async def _speech_hint(self, ctx: Any) -> str:
        """[258] (5 Nov, Adarsh: Manglish voice notes heard as "for lab as itra lab as work you end"): the speaker's
        language and the words they are likely to say, for the transcription itself (same call). Only this company's
        names: its projects, sites and materials (cached; never waits more than HINT_SECONDS for them), and the
        trades every site uses. Never raises; "" when nothing is known."""
        try:
            language = await self._reply_language(ctx)
            names = [str(p.name) for p in getattr(ctx, "projects", None) or []]
            names += [str(s.name) for s in getattr(ctx, "sites", None) or []]
            client = ApiClient(_actor(ctx), app=self._app)
            try:
                names += await asyncio.wait_for(self._material_names(ctx, client), timeout=HINT_SECONDS)
            except Exception:  # noqa: BLE001 -- the hint goes without the materials
                pass
            finally:
                await client.close()
        except Exception:  # noqa: BLE001
            _log.warning("agent_api.speech_hint_failed", exc_info=True)
            return ""
        return speech_hint(language, names)

    async def _material_names(self, ctx: Any, client: ApiClient) -> list[str]:
        await self._catalog_for(ctx, client)
        return list(self._material_names_by_org.get(str(ctx.organization_id), []))

    async def _photo(self, message: Any, ctx: Any) -> str:
        caption = (message.text or "").strip()
        try:
            seen = await self._describe(message, hint=caption or None)  # type: ignore[misc]
        except Exception as exc:  # noqa: BLE001
            _log.exception("agent_api.photo_unreadable user=%s", ctx.user_id)
            if is_outage_error(exc):
                await self._outage(message, ctx, caption, exc)
            return ""
        if not seen:
            return ""
        return f"(sent a photo{': ' + caption if caption else ''})\nWhat the photo shows: {seen}"

    # -- a message ---------------------------------------------------------------------------

    async def _on_words(self, text: str, message: Any, ctx: Any, *, photo_key: str | None = None) -> ReplySpec:
        started = time.monotonic()
        client = ApiClient(_actor(ctx), app=self._app)
        state: dict = {}
        try:
            state, history, facts, sizes, open_requests, chosen = await asyncio.gather(
                self._state(ctx), self._memory.load(ctx), self._facts(ctx, client), self._sizes(ctx),
                self._open_requests(message), self._preferences(client))
            if message.modality is InputModality.VOICE:
                self._heard_shown[message.correlation_id] = (chosen is not _UNREAD
                                                             and chosen.get("voice_transcript") is True)
            chosen = _chosen_of(chosen)
            if chosen is not _UNREAD:
                state["chosen_language"] = chosen  # WA-169: the database decides; kept for the lines that don't read it
            facts = f"{facts}\n\n{open_requests}" if open_requests else facts
            _lap("v3_facts_memory")
            if state.get("pending") and state.get("pending_at") and time.time() - float(state["pending_at"]) > PENDING_MAX_AGE_S:
                state["pending"], state["batch"] = [], None  # waiting for hours: never rides on a new card
            ready = dropping_stale_sends([PendingWrite.from_json(e) for e in state.get("pending") or []])
            needs = list(state.get("size_needed") or [])
            if needs and is_dont_know(text):
                # [232]: nobody knows: a material with no stock yet can be counted in the unit they said (a way out for
                # the admin too); else the line is held (for the admin, or until the admin themself sets the size).
                if any(n.get("no_stock") for n in needs):
                    return await self._size_way_out(ctx, state, ready, next(n for n in needs if n.get("no_stock")))
                return await self._hold_for_size(ctx, client, state, ready)  # WA-168: no model turn
            choices = state.get("size_choices") or {}
            if needs and choices and text.strip() == choices.get("unit"):
                return await self._save_in_said_unit(ctx, state, ready, next(
                    (n for n in needs if n.get("key") == choices.get("key")), needs[0]))
            if needs and choices and text.strip() == choices.get("tell"):
                return await self._ask_size_again(ctx, state, ready, needs[0])
            state.pop("size_choices", None)
            last = next((m.text for m in reversed(history) if m.role == "model"), "")
            if calls := command_call(text, message, last):
                # 2 Nov (Ilan, Paraclette: "mesiri fix it" came back with the same "Ready to save" list, twice): the
                # explicit command is the whole message, so the code answers it at once (no model turn) and asks
                # how it should be instead; the waiting list is kept as it is, not drawn again.
                return await self._feedback_only(message, ctx, state, calls, text, started)
            # WEB-65: a bill photo stays with its expense whichever message the expense is made in (bill_photo.py).
            photo_now = photo_key
            photo_key = photo_key or bill_photo.carried(state, time.time())
            if photo_now and (unbilled := bill_photo.unbilled_fact(state, time.time())):
                facts = f"{facts}\n\n{unbilled}"
            places = _places(ctx, state.get("working_site"))
            # WA-208: after Edit, this message is the right figure for one line: the model is told which, and the
            # code makes sure that line is the one changed (below).
            editing = _editing(state, ready)
            state.pop("editing", None)
            answered = self._kept_answered.pop(message.correlation_id, [])
            run = dict(
                text=(_edit_note(editing) if editing else "") + kept_note(answered) + text,
                history=history, ready=ready, sender_name=ctx.full_name or "",
                timezone=getattr(ctx, "timezone", None) or "Asia/Kolkata", correlation_id=message.correlation_id,
                facts=facts + _working_fact(places), photo_key=photo_key, language=_turn_language(text, state),
                language_chosen=bool(_chosen(state)),
                channel=_channel(message),
                # WA-154: the person's creates of the last day, and the ones they were just asked about.
                recent_saves=state.get("recent_saves") or [], repeat_ok=state.get("repeat_asked") or [],
                places=places,  # [213]: the code decides the site of a report
                open_question=state.get("asked"),  # [219]: a message that doesn't answer it drops it
                sizes=sizes, may_set_sizes=_may_set_sizes(ctx),  # WA-166: who may set a size for the company
                size_open=needs,  # [232]: a number answers the open size question, however long the message
            )
            try:
                turn = await self._agent.run(client, **run)
                _lap("v3_model_tools")
            except Exception as exc:  # noqa: BLE001
                _lap("v3_model_tools")
                if not is_outage_error(exc) or is_budget_error(exc) or is_greeting_trigger(text):
                    raise  # WA-143: a used-up budget is not a blip: no quick second try
                # One quick second try before the sender hears anything (request 57, A5).
                _log.warning("agent_api.quick_retry user=%s error=%r", ctx.user_id, exc)
                await asyncio.sleep(QUICK_RETRY_PAUSE_SECONDS)
                turn = await self._agent.run(client, **run)
                _lap("v3_model_retry")
        except Exception as exc:  # noqa: BLE001 -- the model or a tool failed
            _log.exception("agent_api.run_failed user=%s", ctx.user_id)
            return await self._failed(exc, text, message, ctx, state, started)
        finally:
            await client.close()
        if editing:
            turn = dataclasses.replace(turn, pending=edited_list(ready, turn.pending, editing["number"]))
        if photo_key and not bill_photo.photo_on([*turn.pending, *(r.pending for r in turn.saved)], photo_key):
            if (billed := bill_photo.on_waiting_expense(turn.pending, photo_key)) is not None:
                turn = dataclasses.replace(turn, pending=billed)  # WEB-65 case 2: the expense waiting on the card
            elif photo_now and (turn.question or turn.options):
                state["photo"] = {"key": photo_key, "at": time.time()}  # case 1: the answer makes the expense
        calls = [{**c, "args": c.get("arguments")} for c in turn.calls]
        unchanged = not turn.saved and [e.summary for e in turn.pending] == [e.summary for e in ready]
        awaiting = state.pop("awaiting_why", None)
        got_why = bool(awaiting and time.time() - float(awaiting.get("at") or 0) < AWAIT_WHY_SECONDS
                       and not calls and unchanged and not turn.question)
        if got_why:
            # The answer to "how should it be instead?": a message that made Mesiri do nothing else is the
            # person's preferred experience, and goes to the same request (the team bot adds it to the plan).
            calls.append({"tool": TELL_THE_TEAM, "by": "code", "args": {
                "kind": awaiting.get("kind") or "bad_ux",
                "about": f"their answer to 'how should it be instead?' for request {awaiting.get('ref') or ''}".strip(),
                "why": text[:500]}})
        await self._trace_turn(message, {
            # `args` as the old v2 trace had it: the team bot's watch reads tell_the_team from it (TM-18).
            "text": text, "calls": calls,
            # WA-148: what the model started from, so a replay on the real model sees the same sites and materials.
            "facts": facts[:FACTS_IN_TRACE],
            "stop_reason": turn.stop_reason,
            "saved": [{"summary": r.pending.summary, "status": r.status,
                       **({} if r.ok else {"reason": _detail(r.body)[:300]})} for r in turn.saved],
            "pending": [e.summary for e in turn.pending], "asked": turn.question,
            **({"dropped_question": turn.dropped_question} if turn.dropped_question else {}),
            **({"reply_fixed": turn.reply_fixed} if turn.reply_fixed else {}),
        }, started)
        if turn.language_set:  # [243]: set by the code this turn, so this reply already follows it
            state["chosen_language"] = turn.language_set  # WA-207: "auto" is kept as the choice to follow each message
        state["language"] = _turn_language(text, state)  # WA-165: "Tower A" keeps it; WA-169: their choice wins
        if turn.sizes_said:
            await self._remember_sizes(ctx, turn.sizes_said)
        if turn.size_needed:
            state["size_needed"] = turn.size_needed  # WA-168: "Don't know" next holds them for the admin
        else:
            state.pop("size_needed", None)  # [232]: the size question is answered, let go, or its line is gone
        state["repeat_asked"] = list(turn.repeat_asked)  # the yes comes in the next message only
        state["asked"] = question_left_open(turn.question, turn.options, turn.reply)  # [219]: answered next, or dropped
        state["recent_saves"] = remember_saves(state.get("recent_saves"), turn.saved, time.time())
        bill_photo.remember_unbilled(state, turn.saved, time.time())  # WEB-65 case 3
        state["working_site"] = last_reported(turn.saved, state.get("working_site"), _today(ctx))
        if turn.saved:
            self._just_saved[message.correlation_id] = list(turn.saved)
        saved_words = _saved_text(turn.saved, state.get("language"), today=_today(ctx), admin=_may_set_sizes(ctx)) if turn.saved else ""
        words = without_heard_echo(turn.reply or turn.question or saved_words)  # [258]: the code draws "🎤 ..." once
        if got_why:
            words = _in(state.get("language"), "api.feedback_got_why", FEEDBACK_GOT_WHY)
        passed_on = any(c.get("tool") == TELL_THE_TEAM for c in calls)
        if passed_on:
            self._requested.add(message.correlation_id)  # TM-22 / TM-28: the team bot is poked once it is answered
            # TM-21: the request's reference, the same one the team group sees, so both can talk about it.
            ref = request_ref(message.correlation_id)
            words = without_refs(words)  # [231]: a Ref of an older turn the model copied from the history
            if ref:
                words = f"{words}\n\nRef {ref}".strip()  # [205]: a bare "#8fa51b" read as internal text
        if passed_on and unchanged and not turn.options:
            # Feedback only: the waiting list (and its buttons) stays as it was; drawing it again under "passed to
            # the team" read as Mesiri ignoring the complaint (2 Nov).
            from runtime.agent.reply_clean import whatsapp_bold

            await self._save_state(ctx, state)
            return ReplySpec(text=without_ready_block(whatsapp_bold(words)) or "OK.")
        if turn.nothing_held:
            words = _in(state.get("language"), "api.nothing_held", NOTHING_HELD)  # [229]: nothing is held: say so
        if turn.not_held:  # [248]: lines that are not on the card are said, never left to look "ready"
            from runtime.agent.wording import say

            words = f"{words}\n\n{say('api.not_held', state.get('language') or 'english', lines=' · '.join(turn.not_held))}"
        reply = self._reply(words, turn.pending, state, turn.options, state.get("language"))
        await self._save_state(ctx, state)
        return reply

    async def _size_way_out(self, ctx: Any, state: dict, ready: list[PendingWrite], need: dict) -> ReplySpec:
        """[232]: "don't know" for a material with no stock records yet: no dead end, two taps (no model turn): tell the
        size, or save the line in the unit they said (the material is then counted in it). Never a made-up size."""
        language = state.get("language") or "english"
        quantity = _amount(Decimal(str(need.get("quantity") or 0))) if need.get("quantity") else ""
        unit = str(need.get("said_unit") or "")
        save_title = SAVE_AS_SAID.get(language, SAVE_AS_SAID["english"]).format(q=quantity, u=unit).replace("  ", " ")
        if len(save_title) > 20:
            save_title = SAVE_AS_SAID["english"].format(q="", u=unit).replace("  ", " ")[:20]
        tell_title = TELL_SIZE.get(language, TELL_SIZE["english"])
        state["size_choices"] = {"tell": tell_title, "unit": save_title, "key": need.get("key")}
        words = SIZE_WAY_OUT.get(language, SIZE_WAY_OUT["english"]).format(q=quantity, u=unit).replace("  ", " ")
        reply = self._reply(words, ready, state, [tell_title, save_title], language)
        state["asked"] = {"question": words, "options": [tell_title, save_title]}
        await self._save_state(ctx, state)
        return reply

    async def _ask_size_again(self, ctx: Any, state: dict, ready: list[PendingWrite], need: dict) -> ReplySpec:
        """[232]: "Tell the size" tapped: the one question again (code-drawn, bigger unit first), the line still waiting."""
        language = state.get("language") or "english"
        question = size_question(need, language)
        dont_know = DONT_KNOW.get(language, DONT_KNOW["english"])
        state.pop("size_choices", None)
        reply = self._reply(question, ready, state, [dont_know], language)
        state["asked"] = {"question": question, "options": [dont_know]}
        await self._save_state(ctx, state)
        return reply

    async def _save_in_said_unit(self, ctx: Any, state: dict, ready: list[PendingWrite], need: dict) -> ReplySpec:
        """[232]: "Save as 30 nos": the material has no stock records, so its Stock Unit becomes the unit they said (the
        existing material update, saved with the card, before the line), and the line is held in that unit as said:
        no size is needed."""
        language = state.get("language") or "english"
        line = next((e for e in ready if e.idempotency_key == need.get("key")), None)
        state.pop("size_needed", None)
        state.pop("size_choices", None)
        if line is None:
            reply = self._reply(plain_refusal("", language), ready, state, [], language)
            await self._save_state(ctx, state)
            return reply
        unit_id = str(line.body.get("unit_id") or "")
        material = str(need.get("material") or "")
        update = PendingWrite(
            tool=UPDATE_MATERIAL_TOOL, method="PATCH", path=f"/materials/{need['material_id']}", params={},
            body={"default_unit_id": unit_id},
            summary=f"📏 {material} is counted in {need.get('said_unit') or 'this unit'} from now (no stock recorded yet)",
            idempotency_key=uuid.uuid4().hex)
        fixed = dataclasses.replace(line, summary=SIZE_UNKNOWN.sub("", line.summary))
        rest = [fixed if e is line else e for e in ready]
        pending = [update, *rest]
        words = {"english": "Done: it will be saved as it is, counted in {u}.",
                 "manglish": "Sheri: ithu {u}-il thanne save aakum.",
                 "malayalam": "ശരി: ഇത് {u}-ൽ തന്നെ സേവ് ആകും.",
                 "hinglish": "Theek hai: yeh {u} mein hi save hoga.",
                 "hindi": "ठीक है: यह {u} में ही सेव होगा।"}.get(language, "Done: it will be saved as it is, counted in {u}.").format(
            u=need.get("said_unit") or "")
        state["asked"] = None
        reply = self._reply(words, pending, state, [], language)
        await self._save_state(ctx, state)
        return reply

    async def _hold_for_size(self, ctx: Any, client: ApiClient, state: dict, ready: list[PendingWrite]) -> ReplySpec:
        """WA-168: nobody on site knows the size: each line that needs one is held for the company's admin (asked once
        a day; it saves by itself when they answer), and the rest of the list stays as it was."""
        held = []
        examples: list[str] = []
        for need in state.pop("size_needed", None) or []:
            # WA-197: the line is on the list (held with its size asked): it leaves the list, held for the admin.
            line = next((e for e in ready if e.idempotency_key == need.get("key")), None)
            if line is not None:
                ready = [e for e in ready if e is not line]
                need = {**need, "path": line.path, "body": line.body, "summary": SIZE_UNKNOWN.sub("", line.summary)}
            try:
                response = await client.call("POST", "/materials/size-requests", json={
                    "material_id": need["material_id"], "from_unit_id": need["from_unit_id"],
                    "line_path": need["path"], "line_body": need["body"], "line_summary": need["summary"],
                    "line_key": need["key"]})
            except Exception:  # noqa: BLE001
                _log.warning("agent_api.size_hold_failed user=%s", ctx.user_id, exc_info=True)
                continue
            if response.ok:
                held.append(str(need["summary"]).rstrip(". "))
                if need.get("big") and need.get("small"):
                    examples.append(f"1 {need['big']} = … {need['small']}")  # [271]: the line's own question
        language = state.get("language") or "english"
        table = _HELD_SELF if _may_set_sizes(ctx) else _HELD
        words = (table.get(language, table["english"]).format(
            lines="; ".join(held), example=(examples or ["1 load = … bags"])[0]) if held
                 else plain_refusal("", language))
        reply = self._reply(words, ready, state, [], state.get("language"))
        await self._save_state(ctx, state)
        return reply

    async def _on_size_tap(self, request_id: str, ctx: Any) -> ReplySpec:
        """WA-168: an admin's one tap on a proposed size: set for the company as they (the API checks they may), and
        the lines that waited for it saved."""
        client = ApiClient(_actor(ctx), app=self._app)
        try:
            listed = await client.call("GET", "/materials/size-requests", params={"status": "open"})
            request = next((r for r in (listed.body or {}).get("items", []) if str(r.get("id")) == request_id), None)
            if request is None or not request.get("proposed_one_unit_equals"):
                return ReplySpec(text="This size was already answered 👍")
            answer = await client.call("POST", f"/materials/size-requests/{request_id}/answer",
                                       json={"one_unit_equals": request["proposed_one_unit_equals"]})
        finally:
            await client.close()
        if not answer.ok:
            return ReplySpec(text=plain_refusal(_detail(answer.body), (await self._state(ctx)).get("language")))
        return ReplySpec(text=f"✅ {answer.body.get('message')}")

    async def _feedback_only(self, message: Any, ctx: Any, state: dict, calls: list[dict[str, Any]], text: str,
                             started: float) -> ReplySpec:
        """"mesiri bad ux / fix it": passed to the team by the code, no model turn. Without a reason, the person is
        asked how it should be instead (their next message goes to the same request); the waiting list is kept."""
        kept = [e.get("summary") for e in state.get("pending") or []]
        await self._trace_turn(message, {"text": text, "calls": calls, "feedback_only": True, "saved": [],
                                         "pending": kept, "asked": None}, started)
        self._requested.add(message.correlation_id)
        language = _chosen(state) or state.get("language") or _language(text)
        ref = request_ref(message.correlation_id)
        if calls[0]["args"].get("why"):
            words = _in(language, "api.feedback_noted", FEEDBACK_NOTED)
        else:
            words = _in(language, "api.feedback_ask", FEEDBACK_ASK)
            state["awaiting_why"] = {"kind": calls[0]["args"].get("kind"), "at": time.time(), "ref": ref}
        await self._save_state(ctx, state)
        return ReplySpec(text=f"{without_refs(words)}\n\nRef {ref}".strip() if ref else words)

    async def _failed(self, exc: Exception, text: str, message: Any, ctx: Any, state: dict,
                      started: float) -> ReplySpec:
        """request 204: a v3 failure is queued on an outage or answered by classic, never a bare "send it again".

        - a greeting is answered by the code (the greeting menu): it never needs the model;
        - a provider outage (quota, auth, timeout): queued in their language + an ARQ retry;
        - anything else (a bug in v3 or a tool): the message is answered by classic instead (WA-134; v2 before).
        Whatever was waiting to save is kept (state is untouched here)."""
        outage = is_outage_error(exc)
        greeting = is_greeting_trigger(text)
        handled = "greeting" if greeting else "queued" if outage else "classic_fallback"
        # 2 Nov: "mesiri fix it" reaches the team even when the model failed (an outage, a bug): the code
        # passes it on, so the trace carries it and the team bot is poked as for any request.
        calls = command_call(text, message, "")
        await self._trace_turn(message, {"error": type(exc).__name__, "text": text, "handled": handled,
                                         "outage": outage, "calls": calls}, started)
        if calls:
            poke_watch_soon(message.correlation_id)
        if greeting:
            from channel.replies import render_greeting_menu

            return render_greeting_menu(timezone=getattr(ctx, "timezone", None))
        if outage:
            await self._outage(message, ctx, text, exc, state=state)
        raise FallBackToClassic(type(exc).__name__) from exc

    async def _language_of_sender(self, ctx: Any, text: str = "") -> str | None:
        """The language of their words, else the last one they used (kept with the waiting list)."""
        state = await self._state(ctx)
        usual = _chosen(state) or state.get("language")
        return _turn_language(text, state) if text else usual

    async def _outage(self, message: Any, ctx: Any, text: str, error: BaseException, *,
                      state: dict | None = None) -> None:
        """The provider is down: say it is queued (their language) and raise, so the worker retries
        the message (runtime/ai_outage.py). The last try says plainly it could not be processed."""
        attempt = retry_attempt.get()
        budget = is_budget_error(error)
        english, will_retry = reply_for_attempt(attempt, budget=budget)
        if not will_retry:
            english = KEPT_REPLY  # [221]: the message is kept (below) and answered with their next one: never "send it again"
        _log.error("agent_api.outage correlation_id=%s attempt=%s error=%r", message.correlation_id, attempt,
                   error, exc_info=error)
        if english:
            known = state if state and (state.get("language") or _chosen(state)) else await self._state(ctx)
            usual = _chosen(known) or known.get("language")
            language = _turn_language(text, known) if text else usual
            line = _in(language, _OUTAGE_LINES[english], english)
            await self._send(ReplySpec(text=line), message.sender.wa_id)
            await _safe(self._log_store.log_reply(correlation_id=message.correlation_id, reply=line))
        if will_retry:
            await _safe(self._log_store.mark_failed(correlation_id=message.correlation_id,
                                                    error_code="AI_UNAVAILABLE"))
            raise AIUnavailableError(f"agent_api: the AI is unavailable for {message.correlation_id}",
                                     budget_exhausted=budget) from error
        await self._keep(ctx, message)  # [221]: given up on, but never lost: answered before their next message
        await _safe(self._log_store.mark_completed(correlation_id=message.correlation_id))
        raise _Answered

    async def _keep(self, ctx: Any, message: Any) -> None:
        """[221]: a message Mesiri gave up on (the AI paused past its last try) is kept with the person's state."""
        try:
            state = await self._state(ctx)
            kept = [k for k in state.get("kept") or [] if isinstance(k, dict)]
            state["kept"] = (kept + [message.model_dump(mode="json")])[-KEPT_MAX:]
            await self._save_state(ctx, state)
        except Exception:  # noqa: BLE001 -- the "send it again" line already went
            _log.warning("agent_api.keep_failed user=%s", getattr(ctx, "user_id", None), exc_info=True)

    async def _answer_kept(self, ctx: Any, correlation_id: str) -> None:
        """[221] (3 Nov: "try again" after the AI pause re-ran an old request from the history): the person's kept
        messages are answered first, oldest first, each its own reply headed with its time; the new message then
        runs as usual, and the model is told what was just answered, so a bare "try again" needs nothing more.
        If the AI is still down, they stay kept (and the new message is retried as usual)."""
        state = await self._state(ctx)
        kept = [k for k in state.get("kept") or [] if isinstance(k, dict)]
        if not kept:
            return
        state.pop("kept", None)
        await self._save_state(ctx, state)
        from mesiri_contracts.assistant.normalized_message import NormalizedMessage

        token = _REPLAYING.set(True)
        try:
            for i, raw in enumerate(kept):
                try:
                    old = NormalizedMessage.model_validate(raw)
                except Exception:  # noqa: BLE001 -- an unreadable kept message is dropped, never blocks
                    _log.warning("agent_api.kept_unreadable", exc_info=True)
                    continue
                try:
                    await self.handle(old, ctx)
                except AIUnavailableError:
                    state = await self._state(ctx)
                    state["kept"] = kept[i:] + [k for k in state.get("kept") or [] if k not in kept]
                    await self._save_state(ctx, state)
                    raise
                stamp = old.timestamp.isoformat() if isinstance(old.timestamp, dt.datetime) else ""
                clock = local_clock(stamp, ZoneInfo(getattr(ctx, "timezone", None) or "Asia/Kolkata"))
                self._kept_answered.setdefault(correlation_id, []).append(clock or "earlier")
        finally:
            _REPLAYING.reset(token)

    async def on_call(self, text: str, ctx: Any, correlation_id: str, wa_id: str) -> str:
        """WA-118: one turn of a phone call. Entries join the ready list and go to the chat as the
        usual Save card; the agent is not given that list, so nothing saves from speech alone."""
        client = ApiClient(_actor(ctx), app=self._app)

        async def send_pdf(arguments: dict) -> dict:
            return await self._call_pdf(wa_id, arguments)

        try:
            history, facts = await asyncio.gather(self._memory.load(ctx), self._facts(ctx, client))
            language = _language(text)
            turn = await self._call_agent.run(
                client, text, history=history, sender_name=ctx.full_name or "",
                timezone=getattr(ctx, "timezone", None) or "Asia/Kolkata", correlation_id=correlation_id,
                facts=facts, language=SPOKEN_LANGUAGE.get(language or "", language),
                actions={SEND_PDF: (_SEND_PDF_TOOL, send_pdf)},
            )
        finally:
            await client.close()
        words = turn.reply or turn.question
        if turn.pending:
            state = await self._state(ctx)
            waiting = [PendingWrite.from_json(e) for e in state.get("pending") or []]
            card = self._reply(words, [*waiting, *turn.pending], state, [], state.get("language"))
            await self._save_state(ctx, state)
            await self._send(card, wa_id)
        if words:
            await self._memory.remember(ctx, text, words)
        return words

    async def _call_pdf(self, wa_id: str, arguments: dict) -> dict:
        """The table the model read out, as a PDF in the caller's chat."""
        from mesiri.domains.reports.pdf_table import render_table_pdf

        title = str(arguments.get("title") or "Mesiri report")
        columns = [str(c) for c in arguments.get("columns") or []]
        rows = [[str(v) for v in row] for row in (arguments.get("rows") or [])[:PDF_MAX_ROWS]]
        try:
            data = await asyncio.to_thread(render_table_pdf, title=title, subtitle=None, columns=columns, rows=rows)
            sent = await self._send_document(wa_id, data, filename=f"{title.replace(' ', '_')[:40]}.pdf",  # type: ignore[misc]
                                             shows=f"PDF list {title}")
        except Exception:  # noqa: BLE001 -- the model tells them it did not go
            _log.exception("agent_api.call_pdf_failed")
            sent = False
        return {"status": "sent to their WhatsApp"} if sent else {"status": "not sent; tell them to ask again"}

    async def _preferences(self, client: ApiClient) -> Any:
        """WA-169 / WA-246: this person's ``GET /me/preferences`` (the reply language they chose, whether a voice
        note's reply shows what was heard), ``_UNREAD`` when it could not be read. In parallel with the facts, at
        most ``CHOSEN_LANGUAGE_TIMEOUT_S``."""
        try:
            response = await asyncio.wait_for(client.call("GET", "/me/preferences"), timeout=CHOSEN_LANGUAGE_TIMEOUT_S)
        except Exception:  # noqa: BLE001 -- a reply in the detected language is still a reply
            _log.warning("agent_api.chosen_language_unreadable", exc_info=True)
            return _UNREAD
        if not response.ok or not isinstance(response.body, dict):
            return _UNREAD
        return response.body

    async def _open_requests(self, message: Any) -> str:
        """TM-69: what this person told the team about and is being fixed, so "is the primer thing fixed?" or the same
        complaint again is answered as someone who knows (SOP "Open requests"). One indexed read, in parallel with the
        facts, at most ``OPEN_REQUESTS_TIMEOUT_S``; anything wrong is simply no block."""
        if self._database is None or not hasattr(self._database, "transaction"):
            return ""
        from runtime import request_progress

        try:
            rows = await asyncio.wait_for(request_progress.open_requests(self._database, str(message.sender.wa_id)),
                                          timeout=OPEN_REQUESTS_TIMEOUT_S)
        except Exception:  # noqa: BLE001 -- a reply without the block is still a reply
            _log.warning("agent_api.open_requests_unreadable", exc_info=True)
            return ""
        return request_progress.context_block(rows)

    async def _facts(self, ctx: Any, client: ApiClient) -> str:
        """What the model starts from: the sender's projects and sites, the company's materials
        and units (read through the API as the sender, cached a few minutes per company)."""
        projects = list(getattr(ctx, "projects", None) or [])
        sites = list(getattr(ctx, "sites", None) or [])
        lines = ["The person's projects and sites (use these ids):"]
        for project in projects:
            lines.append(f"- project {project.name} (project_id {project.id})")
            lines += [f"  - site {s.name} (site_id {s.id})" for s in sites if s.project_id == project.id]
        lines += [f"- site {s.name} (site_id {s.id}, project_id {s.project_id})"
                  for s in sites if s.project_id not in {p.id for p in projects}]
        bare = [p for p in projects if not any(s.project_id == p.id for s in sites)]
        lines += [f"  ({p.name} has no site yet: a report for it goes on {p.name}; Save adds its site.)" for p in bare]
        if len(sites) == 1 and not bare:  # [265]: a project with no site is a place too (the code asks which)
            lines.append(f"Only one site: {sites[0].name}. Use it; never ask which site.")
        catalog, today = await asyncio.gather(self._catalog_for(ctx, client), self._today(ctx, client, sites))
        return "\n".join(lines) + "\n\n" + catalog + "\n\n" + today

    async def _today(self, ctx: Any, client: ApiClient, sites: list[Any]) -> str:
        """WA-127: what is already recorded today (the timeline, newest last), so "did anyone report
        X?" needs no lookup and a second entry of the same delivery can be pointed out. Never cached."""
        zone = ZoneInfo(getattr(ctx, "timezone", None) or "Asia/Kolkata")
        now = dt.datetime.now(zone)
        day = now.date().isoformat()
        # WA-209 (4 Nov: 12:27 pm read as "yesterday morning"): the model is told the company's time, and every time
        # it reads in a tool result is UTC, to be said in this time.
        clock = now_line(now, zone)
        try:
            got = await client.call("GET", "/timeline", params={"date_from": day, "date_to": day, "limit": TODAY_ENTRIES})
        except Exception:  # noqa: BLE001 -- the model can still look it up
            return clock
        rows = got.body.get("items") if got.ok and isinstance(got.body, dict) else None
        if rows is None:
            return clock
        if not rows:
            return f"{clock}\nRecorded today ({day}) so far: nothing yet."
        site_name = {str(s.id): s.name for s in sites}
        lines = []
        for row in sorted(rows, key=lambda r: str(r.get("occurred_at") or ""))[-TODAY_ENTRIES:]:
            at = local_clock(row.get("occurred_at"), zone)
            where = site_name.get(str(row.get("site_id")), "")
            lines.append(f"- {at} {where + ' · ' if where else ''}{row.get('event_type')}: {row.get('summary')}")
        return (f"{clock}\nRecorded today ({day}) so far, oldest first, in that time (answer 'did anyone report X' "
                "from this; if a new entry repeats one of these, say so before preparing it):\n" + "\n".join(lines))

    async def _catalog_for(self, ctx: Any, client: ApiClient) -> str:
        org = str(ctx.organization_id)
        cached = self._catalog.get(org)
        if cached and time.monotonic() - cached[0] < CATALOG_SECONDS:
            return cached[1]
        try:
            materials, units = await asyncio.gather(
                client.call("GET", "/materials", params={"limit": 200, "is_active": True}),
                client.call("GET", "/materials/units-of-measure"))
        except Exception:  # noqa: BLE001 -- the model can still search
            return ""
        unit_name = {}
        lines = []
        if units.ok:  # the API answers {"items": [...]} (request 203: a bare-list check read it as empty)
            unit_name = {u.get("id"): u.get("code") for u in unit_rows(units.body)}
            lines.append("Units (unit_id): " + ", ".join(f"{code} ({uid})" for uid, code in unit_name.items()))
        if materials.ok and isinstance(materials.body, dict):
            items = materials.body.get("items") or []
            # [258]: the names (and what people call them) also go to the voice transcription as likely words.
            self._material_names_by_org[org] = [str(n) for m in items if isinstance(m, dict)
                                                for n in (m.get("name"), *(m.get("aliases") or [])) if n]
            lines.append("Materials (material_id, default unit):")
            lines += [f"- {m.get('name')} ({m.get('id')}, {unit_name.get(m.get('default_unit_id'), '?')})"
                      + (f" also called: {', '.join(m['aliases'])}" if m.get("aliases") else "")
                      for m in items if isinstance(m, dict)]
        text = "\n".join(lines)
        self._catalog[org] = (time.monotonic(), text)
        return text

    # -- a tap -------------------------------------------------------------------------------

    async def _on_tap(self, tap: str, ctx: Any, correlation_id: str | None = None) -> ReplySpec:
        state = await self._state(ctx)
        batch = tap.split(":", 2)[2]
        if not state.get("pending") or state.get("batch") != batch:
            return already_saved(state, batch) or ReplySpec(text=NOTHING_WAITING)
        entries = [PendingWrite.from_json(e) for e in state["pending"]]
        entries = _without_stale_sends(entries)
        if tap.startswith(CANCEL_PREFIX):
            state["pending"], state["batch"] = [], None
            # WA-146: what was cancelled, so a reason tapped next tells the team which entries and tools.
            state["cancelled"] = [{"tool": e.tool, "summary": e.summary} for e in entries][:10]
            await self._save_state(ctx, state)
            titles = _REASON_TITLES.get(state.get("language") or "english", _REASON_TITLES["english"])
            return ReplySpec(text=_in(state.get("language"), "api.cancelled_why", CANCELLED_WHY), buttons=tuple(
                ListRow(id=f"{WHY_PREFIX}{code}", title=titles[code]) for code in CANCEL_REASONS))
        client = ApiClient(_actor(ctx), app=self._app)
        try:
            results = await confirm(client, entries, _place_names(_places(ctx, state.get("working_site"))))
        finally:
            await client.close()
        self._just_saved[correlation_id] = results
        if any(r.ok and not held(r) for r in results):
            # [267]: a later tap on this card (or this tap run again) is told it is saved, with the links.
            state["saved_batch"] = {"batch": batch, "links": saved_links(
                [r for r in results if r.ok and not held(r)], today=_today(ctx)), "at": time.time()}
        state["recent_saves"] = remember_saves(state.get("recent_saves"), results, time.time())  # WA-154
        bill_photo.remember_unbilled(state, results, time.time())  # WEB-65 case 3
        state["working_site"] = last_reported(results, state.get("working_site"), _today(ctx))  # [213]
        # Refused entries stay waiting (they can be corrected and saved); saved ones go.
        # A line whose unit nobody could settle comes off the list (it would ride along on every new
        # card for hours, 2 Nov): the text below says so and asks for it again with the unit.
        left, dropped = _refused_to_keep(results, state)  # [233]: a refused line is never carried on unchanged
        previewed = state.pop("previewed", None) == batch
        state["pending"] = [e.to_json() for e in left]
        state["batch"] = uuid.uuid4().hex[:8] if left else None
        if previewed and results and all(r.ok and not held(r) and not order_note(r, None) for r in results):
            # WA-210: every line was on the preview card and all of them saved: "✅ Saved." and the links, no list.
            self._previewed_saves[correlation_id] = True
            text = _saved_short(results, state.get("language"), today=_today(ctx))
        else:
            text = _saved_text(results, state.get("language"), today=_today(ctx), admin=_may_set_sizes(ctx))
        if dropped:
            text += "\n\n" + _in(state.get("language"), "api.refused_dropped", REFUSED_DROPPED)
        if any(confirm_field(r) for r in results):
            text += "\n\n" + _in(state.get("language"), "api.extra_ask", EXTRA_ASK)  # PRC-32: Save = it is extra
        sizes = [r for r in results if not r.ok and is_stock_unit_refusal(_detail(r.body))]
        if left and len(sizes) == len(left):
            # WA-165 (3 Nov, Paraclette: Save tapped twice, refused twice): Save cannot work until they say the size,
            # so it is not offered. The line waits; their next short reply answers the question (it is the open one).
            state["asked"] = {"question": plain_refusal(_detail(sizes[0].body), state.get("language")), "options": []}
            await self._save_state(ctx, state)
            return ReplySpec(text=text, buttons=(ListRow(id=f"{CANCEL_PREFIX}{state['batch']}", title="Cancel"),))
        await self._save_state(ctx, state)
        return _save_buttons(text, state["batch"], send=only_sends(left)) if left else ReplySpec(text=text)

    async def _on_edit(self, tap: str, ctx: Any) -> ReplySpec:
        """WA-208: "✏️ Edit" on a ready list. One line: ask its right figure at once; several: pick the line first.
        The next message (typed or a voice note) changes only that line."""
        state = await self._state(ctx)
        batch, _, number = tap.split(":", 2)[2].partition(":")
        if not state.get("pending") or state.get("batch") != batch:
            return already_saved(state, batch) or ReplySpec(text=NOTHING_WAITING)
        entries = [PendingWrite.from_json(e) for e in state["pending"]]
        language = state.get("language")
        if not number and len(entries) > 1:
            rows = tuple(
                ListRow(id=f"{EDIT_LINE_PREFIX}{batch}:{i}", title=_row_title(i, e.summary),
                        description=without_ids(e.summary)[:72])
                for i, e in enumerate(entries[:10], 1)
            )
            return ReplySpec(text=_in(language, "api.edit_which", EDIT_WHICH),
                             list_button_label=_in(language, "api.edit_pick", EDIT_PICK), list_rows=rows)
        line = int(number) if number.isdigit() else 1
        if not 1 <= line <= len(entries):
            return ReplySpec(text=NOTHING_WAITING)
        state["editing"] = {"batch": batch, "number": line, "summary": entries[line - 1].summary, "at": time.time()}
        await self._save_state(ctx, state)
        item = without_ids(entries[line - 1].summary)
        if language and language != "english":
            from runtime.agent.wording import say

            ask = say("api.edit_ask", language, item=item)
        else:
            ask = EDIT_ASK.format(item=item)
        return ReplySpec(text=ask, buttons=(ListRow(id=f"{REMOVE_PREFIX}{batch}:{line}", title=REMOVE_TITLE),
                                            ListRow(id=f"{CANCEL_PREFIX}{batch}", title="Cancel")))

    async def _on_remove(self, tap: str, ctx: Any) -> ReplySpec:
        """WA-210: "🗑️ Remove" under an Edit question: that one line comes off the ready list; the rest stays,
        on a new card with its own buttons."""
        state = await self._state(ctx)
        batch, _, number = tap[len(REMOVE_PREFIX):].partition(":")
        if not state.get("pending") or state.get("batch") != batch or not number.isdigit():
            return already_saved(state, batch) or ReplySpec(text=NOTHING_WAITING)
        entries = [PendingWrite.from_json(e) for e in state["pending"]]
        line = int(number)
        if not 1 <= line <= len(entries):
            return ReplySpec(text=NOTHING_WAITING)
        gone = entries.pop(line - 1)
        state.pop("editing", None)
        language = state.get("language")
        item = without_ids(gone.summary)
        if not entries:
            state["pending"], state["batch"] = [], None
            state.pop("pending_at", None)
            await self._save_state(ctx, state)
            return ReplySpec(text=_in_with(language, "api.removed_all", REMOVED_ALL, item=item))
        reply = self._reply(_in_with(language, "api.removed", REMOVED, item=item), entries, state, [], language)
        await self._save_state(ctx, state)
        return reply

    async def _card_lines(self, reply: ReplySpec, ctx: Any) -> list[str]:
        """PRC-32: the lines a reply's TO SAVE card showed (its text has only the caption), for the conversation."""
        if reply.header_image is None:
            return []
        try:
            state = await self._state(ctx)
            if state.get("previewed") != state.get("batch"):
                return []
            return [without_ids(PendingWrite.from_json(e).summary) for e in state.get("pending") or []]
        except Exception:  # noqa: BLE001 -- the memory keeps the words as before
            return []

    async def _with_preview(self, reply: ReplySpec, ctx: Any, correlation_id: str | None) -> ReplySpec:
        """WA-210 / WA-215: the reply that carries the ready list's Save button gets the list's draft slip as its header
        image, and its text loses the list (the slip shows every line, numbered) and the "tap Save" line (the button
        is under the card). Drawn within
        PREVIEW_SECONDS; when it can't be, the reply goes out exactly as before. Never raises."""
        if self._receipts is None or reply.header_image is not None or not reply.buttons:
            return reply
        try:
            state = await self._state(ctx)
            batch = state.get("batch")
            if not batch or not state.get("pending") or not any(
                    b.id == f"{SAVE_PREFIX}{batch}" for b in reply.buttons):
                return reply
            entries = [PendingWrite.from_json(e) for e in state["pending"]]
            client = ApiClient(_actor(ctx), app=self._app)
            try:
                image = await asyncio.wait_for(
                    preview_card(self._receipts, entries, ctx, client, correlation_id), timeout=PREVIEW_SECONDS)
            finally:
                await client.close()
            if not image:
                return reply
            state["previewed"] = batch
            await self._save_state(ctx, state)
            return dataclasses.replace(reply, header_image=image,
                                       text=without_listed_lines(reply.text, entries, state.get("language")))
        except Exception:  # noqa: BLE001 -- the list goes out as text
            _log.warning("agent_api.preview_not_sent user=%s", getattr(ctx, "user_id", None), exc_info=True)
            return reply

    async def _on_why(self, code: str, message: Any, ctx: Any) -> ReplySpec:
        """WA-146: the reason for a Cancel, as feedback to the team bot (the shape its watch reads)."""
        started = time.monotonic()
        state = await self._state(ctx)
        cancelled = state.pop("cancelled", None) or []
        await self._save_state(ctx, state)
        reason = CANCEL_REASONS.get(code)
        if reason is None or not cancelled:
            return ReplySpec(text=_in(state.get("language"), "api.thanks", "Thanks 👍"))
        what = "; ".join(f"{c.get('summary') or c.get('tool')} ({c.get('tool')})" for c in cancelled)[:300]
        call = {"tool": TELL_THE_TEAM, "by": "code", "args": {
            "kind": "wrong_reply", "about": f"cancelled the ready list ({what}): {reason}"}}
        await self._trace_turn(message, {"text": f"(cancel reason: {reason})", "calls": [call],
                                         "cancel_reason": code, "cancelled": cancelled}, started)
        self._requested.add(message.correlation_id)  # TM-22 / TM-28: poked once it is answered
        if code == "other":
            return ReplySpec(text=_in(state.get("language"), "api.cancel_other",
                                      "Thanks. What was wrong? Send it as a message or a voice note."))
        return ReplySpec(text=_in(state.get("language"), "api.cancel_noted",
                                  "Thanks 👍 I've told the team. Send it again the right way and I'll get it ready."))

    # -- helpers -----------------------------------------------------------------------------

    def _reply(self, words: str, pending: list[PendingWrite], state: dict, options: list[str],
               language: str | None = None) -> ReplySpec:
        """The model's words, the ready list under them, and the buttons: the question's options
        when it asked one (one tap answers it), else Save / Cancel for the list."""
        had = bool(state.get("pending"))
        pending = _distinct(pending)
        state["pending"] = [e.to_json() for e in pending]
        if pending and not (had and state.get("pending_at")):
            state["pending_at"] = time.time()
        elif not pending:
            state.pop("pending_at", None)
        state["batch"] = uuid.uuid4().hex[:8] if pending else None  # a new list: older buttons no longer act
        from runtime.agent.reply_clean import whatsapp_bold

        text = whatsapp_bold(words) or "OK."
        # The list is drawn here; a copy the model wrote itself (it echoed the history) is cut.
        text = without_ready_block(text) or "OK."
        # [229]: only the code tells them to tap Save, and only under a list it holds with the button sent with it.
        text = without_save_prompt(text) or ("OK." if not pending else "")
        sending = only_sends(pending)
        if pending:
            text = without_numbered_lines(without_copied_lines(text, [e.summary for e in pending]))
            # [264]: a bare "OK." says nothing above a held list: the list and the Save / Send line speak instead.
            text = "" if text.strip(" .").casefold() in ("", "ok") else text
            listed = "\n".join(f"{i}. {without_ids(e.summary)}" for i, e in enumerate(pending, 1))
            text = f"{text}\n\n{READY_SEND_HEADING if sending else READY_HEADING}\n{listed}".strip()
            if not options:
                text = f"{text}\n\n{press_line(pending, language)}"
        if options:
            rows = [ListRow(id=f"{OPTION_PREFIX}{i}", title=o) for i, o in enumerate(options[:3])]
            if pending and len(rows) < 3:  # WA-197: a size question too: the line is on the list, Save holds it
                # [229]: one line waits for an answer, the others are held: Save stays on the same reply
                # (last, so the option taps keep their numbers; WhatsApp allows 3 buttons).
                rows.append(ListRow(id=f"{SAVE_PREFIX}{state['batch']}", title="Save"))
            return ReplySpec(text=text, buttons=tuple(rows))
        return _save_buttons(text, state["batch"], send=sending) if pending else ReplySpec(text=text)

    async def _reply_language(self, ctx: Any) -> str | None:
        state = await self._state(ctx)
        return _chosen(state) or state.get("language")

    def _key(self, ctx: Any) -> str:
        return state_key(ctx.organization_id, ctx.user_id)

    def _sizes_key(self, ctx: Any) -> str:
        return f"agent_api_sizes:{ctx.organization_id}:{ctx.user_id}"

    async def _sizes(self, ctx: Any) -> dict[str, float]:
        """WA-166: the sizes this person told ("1 load M-sand = 60 bags") when they may not set one for the company."""
        try:
            return dict(await self._redis.get_json(self._sizes_key(ctx)) or {})
        except Exception:  # noqa: BLE001 -- asked again rather than no reply
            return {}

    async def _remember_sizes(self, ctx: Any, said: dict[str, float]) -> None:
        try:
            sizes = {**await self._sizes(ctx), **said}
            await self._redis.set_json(self._sizes_key(ctx), sizes, ttl_seconds=SIZES_TTL_SECONDS)
        except Exception:  # noqa: BLE001
            _log.warning("agent_api.sizes_unsaved user=%s", ctx.user_id, exc_info=True)

    async def _state(self, ctx: Any) -> dict:
        try:
            return dict(await self._redis.get_json(self._key(ctx)) or {})
        except Exception:  # noqa: BLE001 -- a fresh list rather than no reply
            _log.warning("agent_api.state_unreadable user=%s", ctx.user_id, exc_info=True)
            return {}

    async def _save_state(self, ctx: Any, state: dict) -> None:
        try:
            await self._redis.set_json(self._key(ctx), {k: state[k] for k in ("pending", "batch", "language", "chosen_language", "cancelled", "pending_at", "awaiting_why", "recent_saves", "repeat_asked", "working_site", "asked", "size_needed", "size_choices", "retried", "editing", "previewed", "kept", "photo", "unbilled",
                                                               "saved_batch")
                                    if state.get(k) is not None},
                                       ttl_seconds=STATE_TTL_SECONDS)
        except Exception:  # noqa: BLE001
            _log.warning("agent_api.state_unsaved user=%s", ctx.user_id, exc_info=True)

    async def _trace_turn(self, message: Any, payload: dict, started: float) -> None:
        if self._trace is None:
            return
        try:
            await self._trace.log_stage(
                correlation_id=message.correlation_id, stage="agent_api_turn",
                stage_payload=json.loads(json.dumps(payload, default=str)),
                duration_ms=int((time.monotonic() - started) * 1000), succeeded="error" not in payload,
                event_source=EVENT_SOURCE,
            )
        except Exception:  # noqa: BLE001 -- diagnostics never break a message
            _log.warning("agent_api.trace_failed", exc_info=True)


SEND_TOOLS = ("send_dpr",)
PENDING_MAX_AGE_S = 4 * 3600  # a ready list nobody saved in four hours is dropped, not carried


def state_key(organization_id: Any, user_id: Any) -> str:
    """The Redis key of one person's v3 state: their ready list, language, last reply."""
    return f"agent_api:{organization_id}:{user_id}"


def has_ready_entries(state: Any) -> bool:
    """WA-176: entries wait for this person's Save (a list older than PENDING_MAX_AGE_S is dropped
    on their next message, so it no longer counts). Other messages hold back while this is true."""
    if not isinstance(state, dict) or not state.get("pending"):
        return False
    at = state.get("pending_at")
    return not at or time.time() - float(at) <= PENDING_MAX_AGE_S


def dropping_stale_sends(entries: list[PendingWrite]) -> list[PendingWrite]:
    """A DPR send waits only for the reply to the message that prepared it: a later message
    (a question, a new entry) drops it, so a Save tap never sends a report nobody asked for."""
    return [e for e in entries if e.tool not in SEND_TOOLS]


def _without_stale_sends(entries: list[PendingWrite]) -> list[PendingWrite]:
    """A Save tap saves records; a send goes out only when it is the only thing waiting."""
    if len(entries) > 1:
        return [e for e in entries if e.tool not in SEND_TOOLS]
    return entries


def for_memory(sent: str, listed: list[str] | tuple[str, ...] = ()) -> str:
    """What the conversation keeps of a reply (WA-130): the words, and the drawn list only as a
    short note. Kept whole, the model saw the list's format in the history and wrote it again
    itself (Paraclette 2 Nov 10:52: the list twice). ``listed``: the lines a TO SAVE card showed (WA-210: the text is
    then only its caption); they get the same note, else the conversation held request -> "tap Save" and the model
    copied that reply for the next request with no tool called (PRC-32, 7 Nov)."""
    sent = without_heard_echo(sent)  # [258]: the model never sees the "🎤 heard" line, so it never writes one
    words = without_ready_block(sent)
    items: list[str] = []
    if words != sent.strip():
        parts = re.split(r"[\s*_]*Ready to (?:save|send)[:*_ \t]*\n", sent, maxsplit=1, flags=re.IGNORECASE)
        if len(parts) < 2:
            return words
        items = [re.sub(r"^\d+\.\s*", "", line).strip() for line in parts[1].splitlines() if line.strip()]
    items = items or [line.strip() for line in listed if line.strip()]
    if not items:
        return sent
    return f"{words}\n(under this reply, waiting for the Save button: {'; '.join(items)})".strip()


#: How long Mesiri waits for the answer to "how should it be instead?" after a feedback command.
AWAIT_WHY_SECONDS = 30 * 60
FEEDBACK_ASK = ("Sorry 🙏 I've passed it to the team. How should it be instead? Send it as a message or a voice note; "
                "you'll see how it will look before it changes.")
FEEDBACK_NOTED = "Thanks 🙏 I've passed it to the team. You'll see how it will look, and I'll tell you here when it's fixed."
FEEDBACK_GOT_WHY = "Thanks 👍 Added to your request. You'll see how it will look before it changes."


def _distinct(pending: list[PendingWrite]) -> list[PendingWrite]:
    """The same entry prepared twice (2 Nov: "10 TMT steel bars used at Tower A" listed as 1. and 2.) is one entry."""
    seen: set[str] = set()
    out: list[PendingWrite] = []
    for e in pending:
        key = json.dumps([e.tool, e.method, e.path, e.params, e.body, e.summary], sort_keys=True, default=str)
        if key not in seen:
            seen.add(key)
            out.append(e)
    return out


def without_refs(text: str) -> str:
    """[231]: the text without any "Ref #abc123" (the model copies the one of an earlier turn from the history)."""
    cleaned = re.sub(r"[ \t]*\bRef\s*#[0-9a-f]{6}\b", "", text, flags=re.IGNORECASE)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def latin_reply(reply: ReplySpec, language: str | None) -> ReplySpec:
    """[231]: the last step before a reply goes out. For Manglish or Hinglish no Malayalam or Devanagari letter may
    reach the person (model words, code-drawn lines, card summaries, button titles): each word in script is
    transliterated. Malayalam, Hindi and English replies, names in Latin letters, emoji and numbers are untouched."""
    if language not in ("manglish", "hinglish"):
        return reply
    from runtime.agent.material_names import to_latin

    def rows(items: Any) -> Any:
        return tuple(dataclasses.replace(r, title=to_latin(r.title), description=to_latin(r.description))
                     for r in items) if items else items

    return dataclasses.replace(reply, text=to_latin(reply.text), buttons=rows(reply.buttons),
                               list_rows=rows(reply.list_rows),
                               list_button_label=to_latin(reply.list_button_label) if reply.list_button_label else None)


def command_call(text: str, message: Any, last_reply: str) -> list[dict[str, Any]]:
    """The code's ``tell_the_team`` call for an explicit "mesiri bad ux / fix it" command, or none.

    Checked on what the person typed or said, and on a photo's or document's caption (2 Nov: a screenshot
    captioned "mesiri bad ux" reached the model as "(sent a photo: mesiri bad ux) ...", which the command
    did not match, so it depended on the model passing it on)."""
    command = feedback_command(text) or feedback_command(getattr(message, "text", None) or "")
    if command is None:
        return []
    kind, why = command
    about = f"Mesiri's reply before this: {without_ready_block(last_reply)[:200]}" if last_reply else "the last reply"
    if getattr(message, "modality", None) in (InputModality.IMAGE, InputModality.DOCUMENT):
        seen = text.split("What the photo shows:", 1)[1].strip()[:300] if "What the photo shows:" in text else ""
        about = f"{about} (they sent a screenshot with it{': ' + seen if seen else ''})"
    return [{"tool": TELL_THE_TEAM, "by": "code", "args": {"kind": kind, "about": about, **({"why": why} if why else {})}}]


def feedback_command(text: str) -> tuple[str, str] | None:
    """WA-130 (approved by Ilan, 2 Nov: an explicit command, like "undo"): "mesiri bad ux ..." /
    "mesiri fix this ..." is passed to the team by the code whatever the model does. Returns
    ``(kind, why)``; anything softer ("this is confusing") stays the model's judgement."""
    m = _FEEDBACK_COMMAND.match(text or "")
    if m is None:
        return None
    kind = "bad_ux" if m.group(1).lower().startswith("bad") else "wrong_reply"
    return kind, m.group(2).strip(" :,-.")


#: The whole list of explicit feedback commands. Not a word list for understanding messages:
#: these are commands to Mesiri, as "undo" is.
_FEEDBACK_COMMAND = re.compile(r"^\s*mesiri\b[\s,:.-]*(bad\s*ux|bad\s*ui|fix\s+this|fix\s+it)\b(.*)$",
                               re.IGNORECASE | re.DOTALL)


def without_ready_block(text: str) -> str:
    """The model's words without a "Ready to save:" list it wrote itself (the code draws the list), and without
    the memory's own note about that list ([205], 2 Nov: Ilan was shown "(under this reply, waiting for the Save
    button: ...)", copied by the model from the conversation)."""
    words = re.split(r"[\s*_]*Ready to (?:save|send)[:*_ \t]*\n", text, maxsplit=1, flags=re.IGNORECASE)[0]
    return re.sub(r"\s*\(under this reply, waiting for the Save button[^)]*\)?", "", words).strip()


_SENTENCE_END = re.compile(r"[.!?।\n]")


def without_copied_lines(words: str, lines: list[str]) -> str:
    """[210] (3 Nov: "…ലഭിച്ചു. നിങ്ങൾ സേവ് ചെയ്യുമ്പോൾ… Paint Green Villa, Kakkanad സൈറ്റിൽ ലഭിച്ചു)"): the model's
    words without a sentence that copies a waiting line (its memory note, translated, with its stray ")"). The
    line itself is drawn under the words by the code, from the entry."""
    for line in (s.strip() for s in lines):
        while len(line) >= 6 and (at := words.find(line)) >= 0:
            starts = [m.end() for m in _SENTENCE_END.finditer(words, 0, at)]
            start = starts[-1] if starts else 0
            end_m = _SENTENCE_END.search(words, at + len(line))
            end = end_m.end() if end_m else len(words)
            words = (words[:start] + words[end:]).strip()
    while words.count(")") > words.count("("):  # a dangling ")" left of a copied note
        words = words[::-1].replace(")", "", 1)[::-1].strip()
    return words.strip()


#: A numbered item ("1.", "3. 2 drum…", "1.2. 1 drum = 20 litres") at the start of a line, or right after a ":".
_ITEM = re.compile(r"^\s*\d{1,2}\.(?:\d{1,2}\.)*(?:\s|$)")
_LEAD_IN = re.compile(r":\s*\d{1,2}\.(?:\d{1,2}\.)*(?:\s|$)")


def without_numbered_lines(words: str) -> str:
    """[217] (3 Nov: "Njan ippo cheyyunnavayum…: 1." then "1.2. 1 drum = 20 litres… 3. 2 drum Primer…"): when the
    ready list is drawn under the words, the model's own numbered list of lines goes, with the sentence that
    leads into it. The list the code draws is the one that saves."""
    kept = []
    for line in words.split("\n"):
        if _ITEM.match(line):
            continue
        lead = _LEAD_IN.search(line)
        if lead:
            starts = [m.end() for m in _SENTENCE_END.finditer(line, 0, lead.start())]
            line = line[: starts[-1] if starts else 0].rstrip()
            if not line:
                continue
        kept.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()


def _language(text: str, usual: str | None = None) -> str | None:
    """The person's language and script, decided by the code (the shared detector). ``usual``: the one they last
    used; a message that does not tell ("Tower A", "20", a site name tapped) keeps it. WA-165 (3 Nov, Paraclette):
    without it the detector's fallback made a Malayalam speaker's next line English after he tapped "Tower A"."""
    try:
        from runtime.agent.wording import language_of

        return language_of(text.split("What the photo shows:", 1)[0], usual)
    except Exception:  # noqa: BLE001 -- the model decides then
        return None


#: WA-207 (5 Nov 2026, set in session): everyone is answered in Manglish unless they chose otherwise.
DEFAULT_REPLY_LANGUAGE = "manglish"
#: The choice "reply in my language again": follow the language of each message.
FOLLOW_EACH = "auto"


def _chosen(state: dict) -> str | None:
    """WA-169: the reply language this person gets, as last read from the database: the one they chose; None when
    they chose to follow each message ("auto"); Manglish when they chose nothing (WA-207, also before it was read)."""
    value = state.get("chosen_language")
    if value == FOLLOW_EACH:
        return None
    return value if value in LANGUAGE_LINES else DEFAULT_REPLY_LANGUAGE


def _turn_language(text: str, state: dict) -> str | None:
    """WA-169: the one decision of a turn's reply language: the language they chose always wins ("always reply in
    Manglish" stays Manglish after an English or Malayalam-script message); else their words decide (``_language``)."""
    return _chosen(state) or _language(text, state.get("language"))


def _today(ctx: Any) -> str:
    return dt.datetime.now(ZoneInfo(getattr(ctx, "timezone", None) or "Asia/Kolkata")).date().isoformat()


def _places(ctx: Any, working: dict[str, Any] | None) -> Places:
    """[213]: the sender's projects and sites, and the site they last reported to TODAY ([215]; kept in the
    conversation state). Yesterday's site is not a default: with several sites, the next update asks."""
    places = Places(
        projects=tuple((str(p.id), str(p.name)) for p in getattr(ctx, "projects", None) or []),
        sites=tuple((str(s.id), str(s.name), str(s.project_id)) for s in getattr(ctx, "sites", None) or []))
    today = bool(working) and working.get("date") == _today(ctx)  # type: ignore[union-attr]
    found = places.place(working.get("site_id"), working.get("project_id")) if working and today else None
    return Places(places.projects, places.sites, found, tuple((working or {}).get("recent") or ()))


def _working_fact(places: Places) -> str:
    """[215]: the model is told where today's updates go, so it prepares instead of asking "which project?"."""
    if places.working is None:
        return ""
    return (f"\nTheir site today: {places.working.name} (an update that names no site goes there; never ask which "
            "site for it).")


#: WA-168: what someone who did not know the size is told (their line waits for the admin; nothing is lost).
_HELD = {
    "english": "👍 Held: {lines}. I've asked your admin for the size; it saves by itself when they answer.",
    "manglish": "👍 Maatti vechu: {lines}. Size admin-nodu chodichittundu; avar paranjaal ithu thaane save aakum.",
    "malayalam": "👍 മാറ്റിവെച്ചു: {lines}. സൈസ് അഡ്മിനോട് ചോദിച്ചിട്ടുണ്ട്; അവർ പറഞ്ഞാൽ ഇത് തനിയെ സേവ് ആകും.",
    "hinglish": "👍 Rok ke rakha: {lines}. Size admin se poocha hai; unke batate hi yeh apne aap save ho jayega.",
    "hindi": "👍 रोक के रखा: {lines}। साइज़ एडमिन से पूछा है; उनके बताते ही यह अपने आप सेव हो जाएगा।",
}


#: [232] (6 Nov, Adarsh, the company's admin: "Size admin-nodu chodichittundu", asked of himself): when the person IS
#: the one who sets sizes, nobody else is asked; the line waits until they set it.
_HELD_SELF = {
    "english": "👍 Held: {lines}. It stays held until you set the size (send it, e.g. '{example}'); then it saves by itself.",
    "manglish": "👍 Maatti vechu: {lines}. Nee size set cheyyunnathu vare ithu maatti vekkum (ayakkuka, ex: '{example}'); appol thaane save aakum.",
    "malayalam": "👍 മാറ്റിവെച്ചു: {lines}. നിങ്ങൾ സൈസ് സെറ്റ് ചെയ്യുന്നത് വരെ ഇത് മാറ്റിവെക്കും (അയക്കൂ, ഉദാ: '{example}'); അപ്പോൾ തനിയെ സേവ് ആകും.",
    "hinglish": "👍 Rok ke rakha: {lines}. Jab tak aap size set nahi karte tab tak ruka rahega (bhejiye, jaise '{example}'); phir apne aap save ho jayega.",
    "hindi": "👍 रोक के रखा: {lines}। जब तक आप साइज़ सेट नहीं करते, यह रुका रहेगा (भेजिए, जैसे '{example}'); फिर अपने आप सेव हो जाएगा।",
}


_SIZE_SIDES = re.compile(r"\(1 ([^()]*?) = how many ([^()]*?)\?\)")


def size_example(waiting: list[WriteResult]) -> str:
    """[271] (6 Nov: Ilan was told "send it, e.g. '1 load = 60 bags'" for M Sand in bags against cubic metres, sent
    "1 load = 50 bags", and nothing settled): the example is the held line's own question, its units, no number."""
    for r in waiting:
        if found := _SIZE_SIDES.search(r.pending.summary):
            return f"1 {found.group(1)} = … {found.group(2)}"
    return "1 load = … bags"


def is_dont_know(text: str) -> bool:
    """WA-168: "Don't know" tapped or typed, in any of the button's languages."""
    said = re.sub(r"[^\w\s]", "", (text or "").casefold()).strip()
    return any(said == re.sub(r"[^\w\s]", "", t.casefold()).strip() for t in DONT_KNOW.values())


def _may_set_sizes(ctx: Any) -> bool:
    """WA-166: whether this person may set a size for the whole company (the API's own rule)."""
    from mesiri.authorization.roles import may_set_unit_conversions

    return may_set_unit_conversions(getattr(ctx, "role", None))


def _actor(ctx: Any) -> Actor:
    return Actor(user_id=str(ctx.user_id), organization_id=str(ctx.organization_id),
                 role=str(ctx.role or ""), name=ctx.full_name or "")


REFUSED_DROPPED = "I've taken the lines that could not be saved off the list. Send them again with what's missing."


def _refused_to_keep(results: list[WriteResult], state: dict) -> tuple[list[PendingWrite], bool]:
    """[233] (4 Nov, asus): a line the API refused came back unchanged on every following card. A refusal the person
    must fix (4xx) takes the line off the list, and the reply says so; only a failure that may pass on a retry
    (the API down, a new material that did not add) keeps it, once: refused twice, it goes too. A size question
    (WA-165) keeps its line: the person's next words answer it. Returns (lines kept, whether any was dropped)."""
    once = set(state.get("retried") or [])
    keep: list[PendingWrite] = []
    dropped = False
    for r in results:
        if r.ok or r.body == {"detail": UNIT_UNSETTLED}:
            continue
        if field := confirm_field(r):
            # PRC-32 (7 Nov 22:51: an order for cement a site had already asked for was refused at Save and dropped,
            # "send it again"): the API's duplicate / more-than-ordered check is a question, not an error. The line
            # stays, marked confirmed (a new key: the refused one is spent), so Save records it as extra.
            keep.append(dataclasses.replace(r.pending, body={**r.pending.body, field: True},
                                            idempotency_key=new_idempotency_key()))
            continue
        key = r.pending.idempotency_key
        transient = r.status >= 500 or r.status == 424
        if is_stock_unit_refusal(_detail(r.body)) or (transient and key not in once):
            keep.append(r.pending)
            once.add(key)
        else:
            dropped = True
    state["retried"] = sorted(once)[-20:] if keep else []
    return keep, dropped


#: PRC-32: the API's 409 codes that ask whether something is extra, and the field that says it is.
CONFIRM_BY_CODE = {"possible_duplicate": "confirm_duplicate", "more_than_ordered": "confirm_extra"}
EXTRA_ASK = "If it is extra, tap *Save* and it is recorded anyway; if not, tap *Cancel*."


def confirm_field(result: WriteResult) -> str:
    """PRC-32: for a line the API refused as a possible duplicate or more than ordered, the body field that confirms
    it is extra (never already set: refused once confirmed, it is a real refusal); "" otherwise."""
    detail = result.body.get("detail") if isinstance(result.body, dict) else None
    code = detail.get("code") if isinstance(detail, dict) else None
    field = CONFIRM_BY_CODE.get(str(code)) if result.status == 409 else None
    return field if field and not result.pending.body.get(field) else ""


#: WEB-71: the line before the invite, and the invite to forward to someone added by number.
PERSON_ADDED = "✅ *{name}* is on *{project}*. Forward the next message to them so they can start:"
PERSON_INVITE = ("Hi {first}, {company} uses Mesiri for daily site reports on WhatsApp. "
                 "Tap this link and send *Hi* to start: https://wa.me/{number}?text=Hi")
PERSON_INVITE_NO_LINK = ("Hi {first}, {company} uses Mesiri for daily site reports on WhatsApp. "
                         "Save this number and send *Hi* to it to start.")


def person_invites(results: list[WriteResult], ctx: Any, message: Any) -> list[str]:
    """WEB-71: for each person a Save just added by number (`add_person`), the line and the invite to forward."""
    number = "".join(ch for ch in str((getattr(message, "metadata", None) or {}).get("display_phone_number") or "")
                     if ch.isdigit())
    company = getattr(ctx, "org_name", None) or "Your company"
    projects = {str(p.id): p.name for p in getattr(ctx, "projects", None) or []}
    out: list[str] = []
    for r in results:
        if not r.ok or r.pending.tool != PERSON_TOOL:
            continue
        name = str((r.body or {}).get("fullName") if isinstance(r.body, dict) else "") or str(
            r.pending.body.get("fullName") or "")
        project_id = r.pending.path.split("/")[2] if r.pending.path.count("/") >= 2 else ""
        first = (name.split() or ["there"])[0]
        out.append(PERSON_ADDED.format(name=name or "They", project=projects.get(project_id, "the project")))
        out.append(PERSON_INVITE.format(first=first, company=company, number=number) if number
                   else PERSON_INVITE_NO_LINK.format(first=first, company=company))
    return out


def only_sends(entries: list[PendingWrite]) -> bool:
    """[264]: everything waiting is a send (today's report), nothing to record: the card says Send."""
    return bool(entries) and all(e.tool in SEND_TOOLS for e in entries)


def press_line(entries: list[PendingWrite], language: str | None) -> str:
    """The code's one line under a held list: "Tap Save to record these", or for a report send "Tap Send ..."."""
    if only_sends(entries):
        return _in(language, "api.press_send", PRESS_SEND)
    return _in(language, "api.press_save", PRESS_SAVE)


def _save_buttons(text: str, batch: str, *, send: bool = False) -> ReplySpec:
    # WA-208: Edit between them: fix one line (a misheard number, a wrong material) without cancelling it all.
    return ReplySpec(text=text, buttons=(ListRow(id=f"{SAVE_PREFIX}{batch}", title=SEND_TITLE if send else "Save"),
                                          ListRow(id=f"{EDIT_PREFIX}{batch}", title=EDIT_TITLE),
                                          ListRow(id=f"{CANCEL_PREFIX}{batch}", title="Cancel")))


def without_listed_lines(text: str, entries: list[PendingWrite], language: str | None) -> str:
    """WA-210 / WA-215: the reply text once the draft slip shows the list: every listed line comes out (the slip has
    them all, numbered), with the "Ready to save:" heading and the "tap Save" line (the button is under the card)."""
    listed = {f"{i}. {without_ids(e.summary)}" for i, e in enumerate(entries, 1)}
    press = press_line(entries, language)
    kept = [line for line in text.split("\n")
            if line not in listed and line.strip() not in (press, READY_HEADING, READY_SEND_HEADING)]
    words = re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()
    # [264]: with no words of its own, the card's caption is the Save / Send line, never a bare "OK.".
    return words or press


def order_note(result: WriteResult, language: str | None) -> str:
    """PRC-23: under a saved delivery, the purchase order it filled ("📦 On PO-0003 (Malabar): 150 of 160 bags
    came"), or the open orders at the site it may belong to (offered, never filled silently). "" otherwise."""
    from runtime.agent.wording import say

    body = result.body if result.ok and isinstance(result.body, dict) else {}
    lang = language or "english"
    order = body.get("order")
    if isinstance(order, dict) and order.get("ref"):
        return say("api.delivery_on_order", lang, ref=str(order["ref"]), vendor=str(order.get("vendor_name") or ""),
                   received=str(order.get("received")), quantity=str(order.get("quantity")),
                   unit=str(order.get("unit") or ""))
    offered = [o for o in body.get("open_orders") or [] if isinstance(o, dict) and o.get("ref")]
    if offered:
        orders = ", ".join(f"{o['ref']} ({o.get('vendor_name')}, {o.get('pending')} {o.get('unit')})" for o in offered[:3])
        return say("api.delivery_open_orders", lang, orders=orders)
    return ""


def _saved_short(results: list[WriteResult], language: str | None, *, today: str) -> str:
    """WA-210: everything on the preview card saved: one line, then the record links (no repeat of the list)."""
    links = [line for line in saved_links(results, today=today).split("\n") if line]
    sent = [sent_line(r, language) for r in results if r.pending.tool in SEND_TOOLS]
    saved = [] if len(sent) == len(results) else [_in(language, "api.saved_short", SAVED_SHORT)]
    return "\n".join([*saved, *sent, *links])


def saved_links(results: list[WriteResult], *, today: str) -> str:
    """[267]: the record links of what a Save saved, one per line (as under "✅ Saved.")."""
    urls = [record_link(r.pending.tool, r.pending.path, r.pending.body, r.body, today=today) for r in results]
    return "\n".join(line for line in with_links([""] * len(results), urls, today=today) if line)


def already_saved(state: dict, batch: str) -> ReplySpec | None:
    """[267]: a Save / Cancel / Edit tap on a card whose lines were already saved: "✅ Already saved." and their links.
    None when that card was not saved (it was cancelled, or replaced by a newer card)."""
    done = state.get("saved_batch") or {}
    if not batch or done.get("batch") != batch:
        return None
    links = str(done.get("links") or "")
    return ReplySpec(text=_in(state.get("language"), "api.already_saved", ALREADY_SAVED) + (f"\n{links}" if links else ""))


def sent_line(result: WriteResult, language: str | None) -> str:
    """[264]: what a Send tap did: "📤 Report sent: today's report for X. ...", never "Saved"."""
    line = without_ids(result.pending.summary).removeprefix("📤").strip().rstrip(".") or "today's report"
    return _in_with(language, "api.report_sent", REPORT_SENT, line=line)


#: WA-208: an Edit answered within this long changes the line; later it is an ordinary message.
EDIT_SECONDS = 15 * 60


def _editing(state: dict, ready: list[PendingWrite]) -> dict | None:
    """The line an Edit tap asked about, while it is still on the list and the tap is recent."""
    editing = state.get("editing")
    if not isinstance(editing, dict) or time.time() - float(editing.get("at") or 0) > EDIT_SECONDS:
        return None
    if editing.get("batch") != state.get("batch"):
        return None
    number = int(editing.get("number") or 0)
    if not 1 <= number <= len(ready) or ready[number - 1].summary != editing.get("summary"):
        return None
    return editing


def kept_note(times: list[str]) -> str:
    """[221]: what the model is told when kept messages were just answered above this one."""
    if not times:
        return ""
    return (f"(Their message(s) from {', '.join(times)}, kept while the AI was paused, were just answered above, each "
            "with its own reply. If this message only asks to try again, that is done: say so in one line and prepare "
            "nothing.)\n")


def _edit_note(editing: dict) -> str:
    return (f"(They tapped Edit on ready entry {editing['number']}: \"{without_ids(editing['summary'])}\". "
            "This message is its right value: change ONLY that entry with change_ready_entry; "
            "prepare nothing new.)\n")


def edited_list(ready: list[PendingWrite], pending: list[PendingWrite], number: int) -> list[PendingWrite]:
    """WA-208: after an Edit the list keeps its lines, with only line `number` changed. The model reads the
    figure; the code decides where it goes: a new entry it prepared instead of changing the line takes the
    line's place, and nothing else is added or lost."""
    kept = {e.idempotency_key for e in ready}
    new = [e for e in pending if e.idempotency_key not in kept]  # a changed line is a new write (new key)
    by_key = {e.idempotency_key: e for e in pending}
    out: list[PendingWrite] = []
    for i, old in enumerate(ready, 1):
        if i == number:
            # The changed line (or the one prepared instead); gone when they said to remove it.
            line = new[0] if new else by_key.get(old.idempotency_key)
            if line is not None:
                out.append(line)
        else:
            out.append(old)  # the other lines stay exactly as they were, whatever the model did to them
    return out


def _row_title(number: int, summary: str) -> str:
    """A list row's title is at most 24 characters: "1. Cement in: 10 bags"."""
    title = f"{number}. {without_ids(summary)}"
    return title if len(title) <= 24 else title[:23].rstrip() + "…"


def _saved_text(results: list[WriteResult], language: str | None = None, *, today: str | None = None,
                admin: bool = False) -> str:
    def converted(r: WriteResult) -> str:
        # WA-151: a line saved in another unit says what went into stock ("10 Numbers = 0.5 load").
        note = r.body.get("converted") if isinstance(r.body, dict) else None
        if isinstance(r.body, dict) and r.body.get("already_listed"):
            return " (already in your list)"  # [246]: added elsewhere first; its lines went on it
        tail = f" ({note} in stock)" if note else ""
        on_order = order_note(r, language)  # PRC-23
        return f"{tail}\n{on_order}" if on_order else tail

    waiting = [r for r in results if held(r)]  # WA-197: held for the admin's size: never called saved
    results = [r for r in results if not held(r)]
    lines = [(sent_line(r, language) if r.pending.tool in SEND_TOOLS else f"✅ {r.pending.summary}{converted(r)}")
             if r.ok else f"❌ {r.pending.summary}: {plain_refusal(_detail(r.body), language)}" for r in results]
    if today:  # [228]: a link to each saved record's dashboard page, built from ids already returned
        urls = [record_link(r.pending.tool, r.pending.path, r.pending.body, r.body, today=today) if r.ok else None
                for r in results]
        lines = with_links(lines, urls, today=today)
    head = ("Saved." if all(r.ok for r in results) else "Not everything could be saved:") if results else ""
    if results and all(r.ok and r.pending.tool in SEND_TOOLS for r in results):
        head = ""  # [264]: a send is not a save: its own line says what happened
    text = (head + "\n" + "\n".join(lines)).strip()
    if waiting:
        lang = language if language in _HELD else "english"
        later = (_HELD_SELF if admin else _HELD)[lang].format(lines="; ".join(SIZE_UNKNOWN.sub("", r.pending.summary).rstrip(". ")
                                                     for r in waiting), example=size_example(waiting))
        text = f"{text}\n\n{later}".strip()
    return text


#: Writes nothing waits for (WEB-58), held until they finish so none is dropped half-way.
_BACKGROUND: set[asyncio.Task[None]] = set()


def _in_background(awaitable: Awaitable[Any]) -> None:
    """Runs a write the reply does not wait for; a failure is logged, never raised."""
    task = asyncio.get_running_loop().create_task(_safe(awaitable))
    _BACKGROUND.add(task)
    task.add_done_callback(_BACKGROUND.discard)


async def _safe(awaitable: Awaitable[Any]) -> None:
    try:
        await awaitable
    except Exception:  # noqa: BLE001 -- logging never breaks the reply
        _log.warning("agent_api.log_failed", exc_info=True)


def _channel(message: Any) -> str:
    """WA-135: how the message came, as the API records it (``recorded_via`` / ``source``)."""
    modality = getattr(message, "modality", None)
    if modality is InputModality.VOICE:
        return "whatsapp_voice"
    if modality in (InputModality.IMAGE, InputModality.DOCUMENT):
        return "whatsapp_image"
    return "whatsapp_text"


#: WA-209: the transcript above a voice note's reply is cut here (a long note is still read in full).
HEARD_MAX = 200


_HEARD = re.compile(r"^[ \t]*🎤[^\n]*(?:\n|$)", re.MULTILINE)


def without_heard_echo(text: str) -> str:
    """[258] (5 Nov 13:07: the transcript shown twice): the text without a "🎤 _what was heard_" line. Only the code
    draws that line (``heard_line``), once, on a voice note's reply; a copy the model wrote from the history goes."""
    return re.sub(r"\n{3,}", "\n\n", _HEARD.sub("", text)).strip()


#: [258]: the speech hint never waits longer than this for the company's material list (cached after the first read).
HINT_SECONDS = 0.6
#: At most this many of the company's own names go in the hint (the prompt stays short).
HINT_NAMES = 60
#: Words every site says, in English, mixed into Malayalam or Hindi.
SITE_WORDS = ("labour", "labourers", "helper", "helpers", "mason", "masons", "carpenter", "bar bender", "plumber",
              "electrician", "attendance", "site", "load", "bags", "cement", "sand", "steel", "slab", "shuttering",
              "concrete", "plastering", "today", "came", "used")
_SPEAKS = {
    "manglish": "Speaker uses Manglish: Malayalam with English words mixed in (site, material and trade words in "
                "English).",
    "malayalam": "Speaker speaks Malayalam, often with English words for site, material and trade words.",
    "hinglish": "Speaker uses Hinglish: Hindi with English words mixed in.",
    "hindi": "Speaker speaks Hindi, often with English words for site, material and trade words.",
    "english": "Speaker speaks Indian English, sometimes with Malayalam or Hindi words.",
}


def speech_hint(language: str | None, names: list[str]) -> str:
    """[258]: "Speaker uses Manglish ... Likely words: Green Villa, Cement, ..., helper, mason." for the transcription."""
    own = list(dict.fromkeys(n.strip() for n in names if n and n.strip()))[:HINT_NAMES]
    words = ", ".join([*own, *SITE_WORDS])
    return f"{_SPEAKS.get(language or '', _SPEAKS['manglish'])} Construction site update. Likely words: {words}."


_KINDS = {InputModality.VOICE: "voice note", InputModality.IMAGE: "photo", InputModality.DOCUMENT: "document"}


def late_line(message: Any, ctx: Any, language: str | None) -> str:
    """[221]: "⏱️ Your voice note from 12:15:" and a blank line, on top of an answer that comes after an AI pause."""
    zone = ZoneInfo(getattr(ctx, "timezone", None) or "Asia/Kolkata")
    sent = getattr(message, "timestamp", None)
    clock = local_clock(sent.isoformat(), zone) if isinstance(sent, dt.datetime) else ""
    kind = _KINDS.get(getattr(message, "modality", None), "message")
    if not clock:
        return ""
    return _in_with(language, "api.late_answer", LATE_ANSWER, kind=kind, time=clock) + "\n\n"


def _chosen_of(preferences: Any) -> Any:
    """WA-169: the reply language chosen, None when none, ``_UNREAD`` when the preferences could not be read (the
    last known choice then stands)."""
    if preferences is _UNREAD:
        return _UNREAD
    value = preferences.get("reply_language")
    return value if value in LANGUAGE_LINES or value == FOLLOW_EACH else None


def heard_line(said: str) -> str:
    """WA-209: "🎤 _what was heard_" and a blank line, for the top of a voice note's reply."""
    text = " ".join(said.split())
    if len(text) > HEARD_MAX:
        text = text[: HEARD_MAX - 1].rstrip() + "…"
    return f"🎤 _{text}_\n\n"


def local_clock(value: Any, zone: dt.tzinfo) -> str:
    """WA-209: an API time ("2026-11-05T06:57:00+00:00") as the company's clock ("12:27"); "" when unreadable."""
    try:
        moment = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return ""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.UTC)
    return moment.astimezone(zone).strftime("%H:%M")


def now_line(now: dt.datetime, zone: dt.tzinfo) -> str:
    """WA-209: the company's date and time now, and how to read the times tools return."""
    offset = now.strftime("%z")
    return (f"It is now {now:%A %d %b %Y, %H:%M} in the company's time (UTC{offset[:3]}:{offset[3:]}). Every time "
            "in a tool result is UTC (+00:00): turn it into the company's time before you say it, and say "
            "today / yesterday from the company's date.")
