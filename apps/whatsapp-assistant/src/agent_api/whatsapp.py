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

from .agent import (
    LANGUAGE_LINES,
    SOP,
    UNIT_UNSETTLED,
    ApiAgent,
    PendingWrite,
    Places,
    WriteResult,
    _detail,
    _place_names,
    confirm,
    last_reported,
    question_left_open,
    remember_saves,
)
from .app import build_api_app
from .client import Actor, ApiClient
from .memory import DayMemory, tools_version
from .record_links import record_link, with_links
from .reply_guard import without_ids
from .tools import build_tools
from .units import is_stock_unit_refusal, plain_refusal, unit_rows

_log = logging.getLogger(__name__)

#: WA-136: the journey's step timer for the message being handled (``StepTimer.lap``), so v3's own
#: steps show in the perf report instead of one "_unaccounted_ms". Per message (concurrent turns).
_LAP: ContextVar[Callable[[str], None] | None] = ContextVar("agent_api_lap", default=None)


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
#: WA-166: a person's own sizes outlive the day's state; renewed whenever they tell another.
SIZES_TTL_SECONDS = 180 * 24 * 3600
SAVE_PREFIX = "apiag:save:"
CANCEL_PREFIX = "apiag:cancel:"
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
COULD_NOT_READ = "I couldn't read that photo. Please send it again, or type what it is."
NOT_NOW = "I couldn't work on that just now. Please send it again in a minute."
NOTHING_WAITING = "There is nothing waiting to save."
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
_OUTAGE_LINES = {QUEUED_REPLY: "outage.queued", BUDGET_REPLY: "outage.budget", GAVE_UP_REPLY: "outage.gave_up", RESEND_REPLY: "outage.resend"}


NOTHING_HELD = "I haven't got anything ready to save yet. Please send it again, with what's missing."
PRESS_SAVE = "Tap *Save* to record these."


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
        reply = latin_reply(reply, await self._reply_language(ctx))
        await self._send(reply, message.sender.wa_id)
        _lap("v3_send")
        await self._send_saved_card(message, ctx)  # after the "Saved" line: the reply never waits for it
        _lap("v3_saved_card")
        await _safe(self._log_store.log_reply(correlation_id=message.correlation_id, reply=reply.text))
        await _safe(self._log_store.mark_completed(correlation_id=message.correlation_id))
        _lap("v3_log")
        if message.correlation_id in self._requested:
            # TM-28: after the reply and the "answered" mark, so the team bot can read this request at once.
            self._requested.discard(message.correlation_id)
            poke_watch_soon(message.correlation_id)
        if said:
            await self._memory.remember(ctx, said, for_memory(reply.text))  # after the send: never on the wait
            _lap("v3_memory_write")
        return True

    async def _send_saved_card(self, message: Any, ctx: Any) -> None:
        """WA-132: the green SAVED card of what this message saved (a Save tap, or "save it"), as
        classic sends it after the "Saved" line. Never raises."""
        results = self._just_saved.pop(message.correlation_id, None)
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
        try:
            transcript, translated, _ = await self._transcribe(message)  # type: ignore[misc]
        except Exception as exc:  # noqa: BLE001 -- said plainly, never silence
            _log.exception("agent_api.transcribe_failed user=%s", ctx.user_id)
            if is_outage_error(exc):
                await self._outage(message, ctx, "", exc)
            return ""
        return (transcript or translated or "").strip()

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
                self._open_requests(message), self._chosen_language(client))
            if chosen is not _UNREAD:
                state["chosen_language"] = chosen  # WA-169: the database decides; kept for the lines that don't read it
            facts = f"{facts}\n\n{open_requests}" if open_requests else facts
            _lap("v3_facts_memory")
            if state.get("pending") and state.get("pending_at") and time.time() - float(state["pending_at"]) > PENDING_MAX_AGE_S:
                state["pending"], state["batch"] = [], None  # waiting for hours: never rides on a new card
            ready = dropping_stale_sends([PendingWrite.from_json(e) for e in state.get("pending") or []])
            if state.get("size_needed") and is_dont_know(text):
                return await self._hold_for_size(ctx, client, state, ready)  # WA-168: no model turn
            state.pop("size_needed", None)  # anything else: the size question is let go
            last = next((m.text for m in reversed(history) if m.role == "model"), "")
            if calls := command_call(text, message, last):
                # 2 Nov (Ilan, Paraclette: "mesiri fix it" came back with the same "Ready to save" list, twice): the
                # explicit command is the whole message, so the code answers it at once (no model turn) and asks
                # how it should be instead; the waiting list is kept as it is, not drawn again.
                return await self._feedback_only(message, ctx, state, calls, text, started)
            places = _places(ctx, state.get("working_site"))
            run = dict(
                text=text, history=history, ready=ready, sender_name=ctx.full_name or "",
                timezone=getattr(ctx, "timezone", None) or "Asia/Kolkata", correlation_id=message.correlation_id,
                facts=facts + _working_fact(places), photo_key=photo_key, language=_turn_language(text, state),
                language_chosen=bool(_chosen(state)),
                channel=_channel(message),
                # WA-154: the person's creates of the last day, and the ones they were just asked about.
                recent_saves=state.get("recent_saves") or [], repeat_ok=state.get("repeat_asked") or [],
                places=places,  # [213]: the code decides the site of a report
                open_question=state.get("asked"),  # [219]: a message that doesn't answer it drops it
                sizes=sizes, may_set_sizes=_may_set_sizes(ctx),  # WA-166: who may set a size for the company
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
            state["chosen_language"] = None if turn.language_set == "auto" else turn.language_set
        state["language"] = _turn_language(text, state)  # WA-165: "Tower A" keeps it; WA-169: their choice wins
        if turn.sizes_said:
            await self._remember_sizes(ctx, turn.sizes_said)
        if turn.size_needed:
            state["size_needed"] = turn.size_needed  # WA-168: "Don't know" next holds them for the admin
        state["repeat_asked"] = list(turn.repeat_asked)  # the yes comes in the next message only
        state["asked"] = question_left_open(turn.question, turn.options, turn.reply)  # [219]: answered next, or dropped
        state["recent_saves"] = remember_saves(state.get("recent_saves"), turn.saved, time.time())
        state["working_site"] = last_reported(turn.saved, state.get("working_site"), _today(ctx))
        if turn.saved:
            self._just_saved[message.correlation_id] = list(turn.saved)
        saved_words = _saved_text(turn.saved, state.get("language"), today=_today(ctx)) if turn.saved else ""
        words = turn.reply or turn.question or saved_words
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
        reply = self._reply(words, turn.pending, state, turn.options, state.get("language"))
        await self._save_state(ctx, state)
        return reply

    async def _hold_for_size(self, ctx: Any, client: ApiClient, state: dict, ready: list[PendingWrite]) -> ReplySpec:
        """WA-168: nobody on site knows the size: each line that needs one is held for the company's admin (asked once
        a day; it saves by itself when they answer), and the rest of the list stays as it was."""
        held = []
        for need in state.pop("size_needed", None) or []:
            try:
                response = await client.call("POST", "/materials/size-requests", json={
                    "material_id": need["material_id"], "from_unit_id": need["from_unit_id"],
                    "line_path": need["path"], "line_body": need["body"], "line_summary": need["summary"],
                    "line_key": need["key"]})
            except Exception:  # noqa: BLE001
                _log.warning("agent_api.size_hold_failed user=%s", ctx.user_id, exc_info=True)
                continue
            if response.ok:
                held.append(need["summary"])
        language = state.get("language") or "english"
        words = (_HELD.get(language, _HELD["english"]).format(lines="; ".join(held)) if held
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
        await _safe(self._log_store.mark_completed(correlation_id=message.correlation_id))
        raise _Answered

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

    async def _chosen_language(self, client: ApiClient) -> Any:
        """WA-169: the reply language this person chose (``users.reply_language`` via ``GET /me/preferences``), None
        when they chose none, ``_UNREAD`` when it could not be read (the last known choice then stands). In parallel
        with the facts, at most ``CHOSEN_LANGUAGE_TIMEOUT_S``."""
        try:
            response = await asyncio.wait_for(client.call("GET", "/me/preferences"), timeout=CHOSEN_LANGUAGE_TIMEOUT_S)
        except Exception:  # noqa: BLE001 -- a reply in the detected language is still a reply
            _log.warning("agent_api.chosen_language_unreadable", exc_info=True)
            return _UNREAD
        if not response.ok or not isinstance(response.body, dict):
            return _UNREAD
        value = response.body.get("reply_language")
        return value if value in LANGUAGE_LINES else None

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
        if len(sites) == 1:
            lines.append(f"Only one site: {sites[0].name}. Use it; never ask which site.")
        catalog, today = await asyncio.gather(self._catalog_for(ctx, client), self._today(ctx, client, sites))
        return "\n".join(lines) + "\n\n" + catalog + "\n\n" + today

    async def _today(self, ctx: Any, client: ApiClient, sites: list[Any]) -> str:
        """WA-127: what is already recorded today (the timeline, newest last), so "did anyone report
        X?" needs no lookup and a second entry of the same delivery can be pointed out. Never cached."""
        day = dt.datetime.now(ZoneInfo(getattr(ctx, "timezone", None) or "Asia/Kolkata")).date().isoformat()
        try:
            got = await client.call("GET", "/timeline", params={"date_from": day, "date_to": day, "limit": TODAY_ENTRIES})
        except Exception:  # noqa: BLE001 -- the model can still look it up
            return ""
        rows = got.body.get("items") if got.ok and isinstance(got.body, dict) else None
        if rows is None:
            return ""
        if not rows:
            return f"Recorded today ({day}) so far: nothing yet."
        site_name = {str(s.id): s.name for s in sites}
        lines = []
        for row in sorted(rows, key=lambda r: str(r.get("occurred_at") or ""))[-TODAY_ENTRIES:]:
            at = str(row.get("occurred_at") or "")[11:16]
            where = site_name.get(str(row.get("site_id")), "")
            lines.append(f"- {at} {where + ' · ' if where else ''}{row.get('event_type')}: {row.get('summary')}")
        return (f"Recorded today ({day}) so far, oldest first (answer 'did anyone report X' from this; if a new "
                "entry repeats one of these, say so before preparing it):\n" + "\n".join(lines))

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
            return ReplySpec(text=NOTHING_WAITING)
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
        state["recent_saves"] = remember_saves(state.get("recent_saves"), results, time.time())  # WA-154
        state["working_site"] = last_reported(results, state.get("working_site"), _today(ctx))  # [213]
        # Refused entries stay waiting (they can be corrected and saved); saved ones go.
        # A line whose unit nobody could settle comes off the list (it would ride along on every new
        # card for hours, 2 Nov): the text below says so and asks for it again with the unit.
        left, dropped = _refused_to_keep(results, state)  # [233]: a refused line is never carried on unchanged
        state["pending"] = [e.to_json() for e in left]
        state["batch"] = uuid.uuid4().hex[:8] if left else None
        text = _saved_text(results, state.get("language"), today=_today(ctx))
        if dropped:
            text += "\n\n" + _in(state.get("language"), "api.refused_dropped", REFUSED_DROPPED)
        sizes = [r for r in results if not r.ok and is_stock_unit_refusal(_detail(r.body))]
        if left and len(sizes) == len(left):
            # WA-165 (3 Nov, Paraclette: Save tapped twice, refused twice): Save cannot work until they say the size,
            # so it is not offered. The line waits; their next short reply answers the question (it is the open one).
            state["asked"] = {"question": plain_refusal(_detail(sizes[0].body), state.get("language")), "options": []}
            await self._save_state(ctx, state)
            return ReplySpec(text=text, buttons=(ListRow(id=f"{CANCEL_PREFIX}{state['batch']}", title="Cancel"),))
        await self._save_state(ctx, state)
        return _save_buttons(text, state["batch"]) if left else ReplySpec(text=text)

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
        if pending:
            text = without_numbered_lines(without_copied_lines(text, [e.summary for e in pending])) or "OK."
            listed = "\n".join(f"{i}. {without_ids(e.summary)}" for i, e in enumerate(pending, 1))
            text = f"{text}\n\n*Ready to save:*\n{listed}".strip()
            if not options:
                text = f"{text}\n\n{_in(language, 'api.press_save', PRESS_SAVE)}"
        if options:
            rows = [ListRow(id=f"{OPTION_PREFIX}{i}", title=o) for i, o in enumerate(options[:3])]
            if pending and len(rows) < 3 and not state.get("size_needed"):
                # [229]: one line waits for an answer, the others are held: Save stays on the same reply
                # (last, so the option taps keep their numbers; WhatsApp allows 3 buttons).
                rows.append(ListRow(id=f"{SAVE_PREFIX}{state['batch']}", title="Save"))
            return ReplySpec(text=text, buttons=tuple(rows))
        return _save_buttons(text, state["batch"]) if pending else ReplySpec(text=text)

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
            await self._redis.set_json(self._key(ctx), {k: state[k] for k in ("pending", "batch", "language", "chosen_language", "cancelled", "pending_at", "awaiting_why", "recent_saves", "repeat_asked", "working_site", "asked", "size_needed", "retried")
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


def for_memory(sent: str) -> str:
    """What the conversation keeps of a reply (WA-130): the words, and the drawn list only as a
    short note. Kept whole, the model saw the list's format in the history and wrote it again
    itself (Paraclette 2 Nov 10:52: the list twice)."""
    words = without_ready_block(sent)
    if words == sent.strip():
        return sent
    parts = re.split(r"[\s*_]*Ready to save[:*_ \t]*\n", sent, maxsplit=1, flags=re.IGNORECASE)
    if len(parts) < 2:
        return words
    items = [re.sub(r"^\d+\.\s*", "", line).strip() for line in parts[1].splitlines() if line.strip()]
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
    words = re.split(r"[\s*_]*Ready to save[:*_ \t]*\n", text, maxsplit=1, flags=re.IGNORECASE)[0]
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


def _chosen(state: dict) -> str | None:
    """WA-169: the reply language this person chose, as last read from the database (None: none chosen)."""
    value = state.get("chosen_language")
    return value if value in LANGUAGE_LINES else None


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


def is_dont_know(text: str) -> bool:
    """WA-168: "Don't know" tapped or typed, in any of the button's languages."""
    from .agent import DONT_KNOW

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
        key = r.pending.idempotency_key
        transient = r.status >= 500 or r.status == 424
        if is_stock_unit_refusal(_detail(r.body)) or (transient and key not in once):
            keep.append(r.pending)
            once.add(key)
        else:
            dropped = True
    state["retried"] = sorted(once)[-20:] if keep else []
    return keep, dropped


def _save_buttons(text: str, batch: str) -> ReplySpec:
    return ReplySpec(text=text, buttons=(ListRow(id=f"{SAVE_PREFIX}{batch}", title="Save"),
                                          ListRow(id=f"{CANCEL_PREFIX}{batch}", title="Cancel")))


def _saved_text(results: list[WriteResult], language: str | None = None, *, today: str | None = None) -> str:
    def converted(r: WriteResult) -> str:
        # WA-151: a line saved in another unit says what went into stock ("10 Numbers = 0.5 load").
        note = r.body.get("converted") if isinstance(r.body, dict) else None
        return f" ({note} in stock)" if note else ""

    lines = [f"✅ {r.pending.summary}{converted(r)}" if r.ok
             else f"❌ {r.pending.summary}: {plain_refusal(_detail(r.body), language)}" for r in results]
    if today:  # [228]: a link to each saved record's dashboard page, built from ids already returned
        urls = [record_link(r.pending.tool, r.pending.path, r.pending.body, r.body, today=today) if r.ok else None
                for r in results]
        lines = with_links(lines, urls, today=today)
    head = "Saved." if all(r.ok for r in results) else "Not everything could be saved:"
    return head + "\n" + "\n".join(lines)


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
