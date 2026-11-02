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
import datetime as dt
import json
import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any
from zoneinfo import ZoneInfo

from channel.replies import ListRow, ReplySpec
from mesiri_ai.greeting_classifier import is_greeting_trigger
from mesiri_ai.models import ToolSpec
from mesiri_contracts.assistant.enums import InputModality
from runtime.ai_outage import (
    GAVE_UP_REPLY,
    QUEUED_REPLY,
    QUICK_RETRY_PAUSE_SECONDS,
    RESEND_REPLY,
    AIUnavailableError,
    FallBackToV2,
    is_outage_error,
    reply_for_attempt,
    retry_attempt,
)

from .agent import SOP, ApiAgent, PendingWrite, WriteResult, _detail, confirm
from .app import build_api_app
from .client import Actor, ApiClient
from .memory import DayMemory
from .tools import build_tools
from .units import plain_refusal, unit_rows

_log = logging.getLogger(__name__)

MODE = "api"
EVENT_SOURCE = "agent_api"
STATE_TTL_SECONDS = 24 * 3600
SAVE_PREFIX = "apiag:save:"
CANCEL_PREFIX = "apiag:cancel:"
OPTION_PREFIX = "apiag:opt:"
#: A tool round can read several things; a mixed voice note needs room.
MAX_STEPS = 10
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


class _Answered(Exception):
    """The outage reply was already sent and the message closed (no retry left): nothing more to send."""


#: The outage wording by its English text (``reply_for_attempt`` picks the text).
_OUTAGE_LINES = {QUEUED_REPLY: "outage.queued", GAVE_UP_REPLY: "outage.gave_up", RESEND_REPLY: "outage.resend"}


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
                 sessions: Any | None = None, send_document: Callable[..., Awaitable[Any]] | None = None) -> None:
        self._redis = redis
        self._send_document = send_document
        self._send = send
        self._transcribe = transcribe
        self._describe = describe
        self._log_store = message_logger
        self._trace = trace_logger
        self._memory = DayMemory(sessions, redis)
        self._app = app if app is not None else build_api_app(database)
        tools = build_tools(self._app.openapi())
        self._agent = ApiAgent(provider, tools, max_steps=MAX_STEPS, capability="api_agent")
        self._call_agent = ApiAgent(provider, tools, sop=SOP + CALL_RULES, max_steps=CALL_MAX_STEPS,
                                    timeout_seconds=CALL_TIMEOUT_SECONDS, capability="api_agent")
        self._catalog: dict[str, tuple[float, str]] = {}

    # -- entry point -----------------------------------------------------------------------

    async def handle(self, message: Any, ctx: Any) -> bool:
        """True when the message was answered here; False leaves it to the journey. Raises
        ``AIUnavailableError`` (the worker retries) or ``FallBackToV2`` (the journey runs v2)."""
        try:
            return await self._handle(message, ctx)
        except _Answered:
            return True

    async def _handle(self, message: Any, ctx: Any) -> bool:
        tap = str((message.metadata or {}).get("interactive_reply_id") or "")
        said = (message.text or "").strip()
        if tap.startswith((SAVE_PREFIX, CANCEL_PREFIX)):
            said = "(tapped Save)" if tap.startswith(SAVE_PREFIX) else "(tapped Cancel)"
            reply = await self._on_tap(tap, ctx)
        elif tap.startswith(OPTION_PREFIX) and said:
            reply = await self._on_words(said, message, ctx)
        elif message.modality is InputModality.TEXT and said:
            reply = await self._on_words(said, message, ctx)
        elif message.modality is InputModality.VOICE and self._transcribe is not None:
            said = await self._voice(message, ctx)
            reply = (await self._on_words(said, message, ctx) if said
                     else ReplySpec(text=_in(await self._language_of_sender(ctx), "voice.cant_hear", COULD_NOT_HEAR)))
        elif message.modality in (InputModality.IMAGE, InputModality.DOCUMENT) and self._describe is not None:
            said = await self._photo(message, ctx)
            key = getattr(getattr(message, "media", None), "object_key", None)
            reply = (await self._on_words(said, message, ctx, photo_key=key) if said
                     else ReplySpec(text=_in(await self._language_of_sender(ctx), "photo.cant_read", COULD_NOT_READ)))
        else:
            return False
        await self._send(reply, message.sender.wa_id)
        await _safe(self._log_store.log_reply(correlation_id=message.correlation_id, reply=reply.text))
        await _safe(self._log_store.mark_completed(correlation_id=message.correlation_id))
        if said:
            await self._memory.remember(ctx, said, reply.text)  # after the send: never on the wait
        return True

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
            state, history, facts = await asyncio.gather(
                self._state(ctx), self._memory.load(ctx), self._facts(ctx, client))
            ready = [PendingWrite.from_json(e) for e in state.get("pending", [])]
            run = dict(
                text=text, history=history, ready=ready, sender_name=ctx.full_name or "",
                timezone=getattr(ctx, "timezone", None) or "Asia/Kolkata", correlation_id=message.correlation_id,
                facts=facts, photo_key=photo_key, language=_language(text),
            )
            try:
                turn = await self._agent.run(client, **run)
            except Exception as exc:  # noqa: BLE001
                if not is_outage_error(exc) or is_greeting_trigger(text):
                    raise
                # One quick second try before the sender hears anything (as v2: request 57, A5).
                _log.warning("agent_api.quick_retry user=%s error=%r", ctx.user_id, exc)
                await asyncio.sleep(QUICK_RETRY_PAUSE_SECONDS)
                turn = await self._agent.run(client, **run)
        except Exception as exc:  # noqa: BLE001 -- the model or a tool failed
            _log.exception("agent_api.run_failed user=%s", ctx.user_id)
            return await self._failed(exc, text, message, ctx, state, started)
        finally:
            await client.close()
        await self._trace_turn(message, {
            # `args` as v2's trace has it: the team bot's watch reads tell_the_team from it (TM-18).
            "text": text, "calls": [{**c, "args": c.get("arguments")} for c in turn.calls],
            "stop_reason": turn.stop_reason,
            "saved": [{"summary": r.pending.summary, "status": r.status} for r in turn.saved],
            "pending": [e.summary for e in turn.pending], "asked": turn.question,
        }, started)
        state["language"] = _language(text)
        words = turn.reply or turn.question or (_saved_text(turn.saved, state.get("language")) if turn.saved else "")
        reply = self._reply(words, turn.pending, state, turn.options)
        await self._save_state(ctx, state)
        return reply

    async def _failed(self, exc: Exception, text: str, message: Any, ctx: Any, state: dict,
                      started: float) -> ReplySpec:
        """request 204: a v3 failure goes through v2's outage handling, never a bare "send it again".

        - a greeting is answered by the code (the greeting menu): it never needs the model;
        - a provider outage (quota, auth, timeout): queued in their language + an ARQ retry;
        - anything else (a bug in v3 or a tool): the message is answered by v2 instead.
        Whatever was waiting to save is kept (state is untouched here)."""
        outage = is_outage_error(exc)
        greeting = is_greeting_trigger(text)
        handled = "greeting" if greeting else "queued" if outage else "v2_fallback"
        await self._trace_turn(message, {"error": type(exc).__name__, "text": text, "handled": handled,
                                         "outage": outage}, started)
        if greeting:
            from channel.replies import render_greeting_menu

            return render_greeting_menu(timezone=getattr(ctx, "timezone", None))
        if outage:
            await self._outage(message, ctx, text, exc, state=state)
        raise FallBackToV2(type(exc).__name__) from exc

    async def _language_of_sender(self, ctx: Any, text: str = "") -> str | None:
        """The language of their words, else the last one they used (kept with the waiting list)."""
        found = _language(text) if text else None
        if found:
            return found
        return (await self._state(ctx)).get("language")

    async def _outage(self, message: Any, ctx: Any, text: str, error: BaseException, *,
                      state: dict | None = None) -> None:
        """The provider is down: say it is queued (their language) and raise, so the worker retries
        the message (runtime/ai_outage.py). The last try says plainly it could not be processed."""
        attempt = retry_attempt.get()
        english, will_retry = reply_for_attempt(attempt)
        _log.error("agent_api.outage correlation_id=%s attempt=%s error=%r", message.correlation_id, attempt,
                   error, exc_info=error)
        if english:
            language = _language(text) if text else None
            language = language or (state or {}).get("language") or (await self._state(ctx)).get("language")
            line = _in(language, _OUTAGE_LINES[english], english)
            await self._send(ReplySpec(text=line), message.sender.wa_id)
            await _safe(self._log_store.log_reply(correlation_id=message.correlation_id, reply=line))
        if will_retry:
            await _safe(self._log_store.mark_failed(correlation_id=message.correlation_id,
                                                    error_code="AI_UNAVAILABLE"))
            raise AIUnavailableError(f"agent_api: the AI is unavailable for {message.correlation_id}") from error
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
            waiting = [PendingWrite.from_json(e) for e in state.get("pending", [])]
            card = self._reply(words, [*waiting, *turn.pending], state, [])
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

    async def _on_tap(self, tap: str, ctx: Any) -> ReplySpec:
        state = await self._state(ctx)
        batch = tap.split(":", 2)[2]
        if not state.get("pending") or state.get("batch") != batch:
            return ReplySpec(text=NOTHING_WAITING)
        entries = [PendingWrite.from_json(e) for e in state["pending"]]
        if tap.startswith(CANCEL_PREFIX):
            state["pending"], state["batch"] = [], None
            await self._save_state(ctx, state)
            return ReplySpec(text=CANCELLED)
        client = ApiClient(_actor(ctx), app=self._app)
        try:
            results = await confirm(client, entries)
        finally:
            await client.close()
        # Refused entries stay waiting (they can be corrected and saved); saved ones go.
        left = [r.pending for r in results if not r.ok]
        state["pending"] = [e.to_json() for e in left]
        state["batch"] = uuid.uuid4().hex[:8] if left else None
        text = _saved_text(results, state.get("language"))
        await self._save_state(ctx, state)
        return _save_buttons(text, state["batch"]) if left else ReplySpec(text=text)

    # -- helpers -----------------------------------------------------------------------------

    def _reply(self, words: str, pending: list[PendingWrite], state: dict, options: list[str]) -> ReplySpec:
        """The model's words, the ready list under them, and the buttons: the question's options
        when it asked one (one tap answers it), else Save / Cancel for the list."""
        state["pending"] = [e.to_json() for e in pending]
        state["batch"] = uuid.uuid4().hex[:8] if pending else None  # a new list: older buttons no longer act
        from runtime.agent.reply_clean import whatsapp_bold

        text = whatsapp_bold(words) or "OK."
        # The list is drawn here; a copy the model wrote itself (it echoed the history) is cut.
        text = without_ready_block(text) or "OK."
        if pending:
            listed = "\n".join(f"{i}. {e.summary}" for i, e in enumerate(pending, 1))
            text = f"{text}\n\n*Ready to save:*\n{listed}"
        if options:
            return ReplySpec(text=text, buttons=tuple(
                ListRow(id=f"{OPTION_PREFIX}{i}", title=o) for i, o in enumerate(options[:3])))
        return _save_buttons(text, state["batch"]) if pending else ReplySpec(text=text)

    def _key(self, ctx: Any) -> str:
        return f"agent_api:{ctx.organization_id}:{ctx.user_id}"

    async def _state(self, ctx: Any) -> dict:
        try:
            return dict(await self._redis.get_json(self._key(ctx)) or {})
        except Exception:  # noqa: BLE001 -- a fresh list rather than no reply
            _log.warning("agent_api.state_unreadable user=%s", ctx.user_id, exc_info=True)
            return {}

    async def _save_state(self, ctx: Any, state: dict) -> None:
        try:
            await self._redis.set_json(self._key(ctx), {k: state.get(k) for k in ("pending", "batch", "language")},
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


def without_ready_block(text: str) -> str:
    """The model's words without a "Ready to save:" list it wrote itself (the code draws the list)."""
    return re.split(r"[\s*_]*Ready to save[:*_ \t]*\n", text, maxsplit=1, flags=re.IGNORECASE)[0].strip()


def _language(text: str) -> str | None:
    """The person's language and script, decided by the code (the shared detector)."""
    try:
        from runtime.agent.wording import language_of

        return language_of(text.split("What the photo shows:", 1)[0])
    except Exception:  # noqa: BLE001 -- the model decides then
        return None


def _actor(ctx: Any) -> Actor:
    return Actor(user_id=str(ctx.user_id), organization_id=str(ctx.organization_id),
                 role=str(ctx.role or ""), name=ctx.full_name or "")


def _save_buttons(text: str, batch: str) -> ReplySpec:
    return ReplySpec(text=text, buttons=(ListRow(id=f"{SAVE_PREFIX}{batch}", title="Save"),
                                          ListRow(id=f"{CANCEL_PREFIX}{batch}", title="Cancel")))


def _saved_text(results: list[WriteResult], language: str | None = None) -> str:
    lines = [f"✅ {r.pending.summary}" if r.ok else f"❌ {r.pending.summary}: {plain_refusal(_detail(r.body), language)}"
             for r in results]
    head = "Saved." if all(r.ok for r in results) else "Not everything could be saved:"
    return head + "\n" + "\n".join(lines)


async def _safe(awaitable: Awaitable[Any]) -> None:
    try:
        await awaitable
    except Exception:  # noqa: BLE001 -- logging never breaks the reply
        _log.warning("agent_api.log_failed", exc_info=True)
