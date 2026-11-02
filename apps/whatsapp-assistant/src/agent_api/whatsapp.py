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
import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from channel.replies import ListRow, ReplySpec
from mesiri_contracts.assistant.enums import InputModality

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
#: The materials and units of a company, read once per this many seconds.
CATALOG_SECONDS = 300
#: WA-118: a call is a live conversation, so fewer rounds and a shorter wait than a message.
CALL_MAX_STEPS = 4
CALL_TIMEOUT_SECONDS = 10.0
CALL_RULES = """

This is a live phone call, not WhatsApp. What you write is spoken aloud. One or two short spoken
sentences, no lists, no symbols, no formatting, no ids. On a call you can only look things up: to
record or send anything, tell them to send it as a WhatsApp message."""
#: The speech-to-text gives script; a reply in Latin letters would be read badly aloud.
SPOKEN_LANGUAGE = {"manglish": "malayalam", "hinglish": "hindi"}

COULD_NOT_HEAR = "I couldn't hear that voice note. Please send it again or type it."
COULD_NOT_READ = "I couldn't read that photo. Please send it again, or type what it is."
NOT_NOW = "I couldn't work on that just now. Please send it again in a minute."
NOTHING_WAITING = "There is nothing waiting to save."
CANCELLED = "Cancelled. Nothing was saved."


class ApiWhatsApp:
    def __init__(self, *, provider: Any, database: Any, redis: Any,
                 send: Callable[[ReplySpec, str], Awaitable[Any]],
                 transcribe: Callable[[Any], Awaitable[tuple[str, str | None, str | None]]] | None,
                 message_logger: Any, trace_logger: Any | None = None, app: Any | None = None,
                 describe: Callable[..., Awaitable[str | None]] | None = None,
                 sessions: Any | None = None) -> None:
        self._redis = redis
        self._send = send
        self._transcribe = transcribe
        self._describe = describe
        self._log_store = message_logger
        self._trace = trace_logger
        self._memory = DayMemory(sessions, redis)
        self._app = app if app is not None else build_api_app(database)
        tools = build_tools(self._app.openapi())
        self._agent = ApiAgent(provider, tools, max_steps=MAX_STEPS, capability="api_agent")
        self._call_agent = ApiAgent(provider, {n: t for n, t in tools.items() if not t.is_write}, sop=SOP + CALL_RULES,
                                    max_steps=CALL_MAX_STEPS, timeout_seconds=CALL_TIMEOUT_SECONDS,
                                    capability="api_agent")
        self._catalog: dict[str, tuple[float, str]] = {}

    # -- entry point -----------------------------------------------------------------------

    async def handle(self, message: Any, ctx: Any) -> bool:
        """True when the message was answered here; False leaves it to the journey."""
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
            reply = await self._on_words(said, message, ctx) if said else ReplySpec(text=COULD_NOT_HEAR)
        elif message.modality in (InputModality.IMAGE, InputModality.DOCUMENT) and self._describe is not None:
            said = await self._photo(message, ctx)
            key = getattr(getattr(message, "media", None), "object_key", None)
            reply = (await self._on_words(said, message, ctx, photo_key=key) if said
                     else ReplySpec(text=COULD_NOT_READ))
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
        except Exception:  # noqa: BLE001 -- said plainly, never silence
            _log.exception("agent_api.transcribe_failed user=%s", ctx.user_id)
            return ""
        return (transcript or translated or "").strip()

    async def _photo(self, message: Any, ctx: Any) -> str:
        caption = (message.text or "").strip()
        try:
            seen = await self._describe(message, hint=caption or None)  # type: ignore[misc]
        except Exception:  # noqa: BLE001
            _log.exception("agent_api.photo_unreadable user=%s", ctx.user_id)
            return ""
        if not seen:
            return ""
        return f"(sent a photo{': ' + caption if caption else ''})\nWhat the photo shows: {seen}"

    # -- a message ---------------------------------------------------------------------------

    async def _on_words(self, text: str, message: Any, ctx: Any, *, photo_key: str | None = None) -> ReplySpec:
        started = time.monotonic()
        client = ApiClient(_actor(ctx), app=self._app)
        try:
            state, history, facts = await asyncio.gather(
                self._state(ctx), self._memory.load(ctx), self._facts(ctx, client))
            ready = [PendingWrite.from_json(e) for e in state.get("pending", [])]
            turn = await self._agent.run(
                client, text, history=history, ready=ready, sender_name=ctx.full_name or "",
                timezone=getattr(ctx, "timezone", None) or "Asia/Kolkata", correlation_id=message.correlation_id,
                facts=facts, photo_key=photo_key, language=_language(text),
            )
        except Exception as exc:  # noqa: BLE001 -- the model or a tool failed: say so, keep what was waiting
            _log.exception("agent_api.run_failed user=%s", ctx.user_id)
            await self._trace_turn(message, {"error": type(exc).__name__, "text": text}, started)
            return ReplySpec(text=NOT_NOW)
        finally:
            await client.close()
        await self._trace_turn(message, {
            "text": text, "calls": turn.calls, "stop_reason": turn.stop_reason,
            "saved": [{"summary": r.pending.summary, "status": r.status} for r in turn.saved],
            "pending": [e.summary for e in turn.pending], "asked": turn.question,
        }, started)
        state["language"] = _language(text)
        words = turn.reply or turn.question or (_saved_text(turn.saved, state.get("language")) if turn.saved else "")
        reply = self._reply(words, turn.pending, state, turn.options)
        await self._save_state(ctx, state)
        return reply

    async def on_call(self, text: str, ctx: Any, correlation_id: str) -> str:
        """WA-118: one turn of a phone call. The agent here has no write tool and no ready list."""
        client = ApiClient(_actor(ctx), app=self._app)
        try:
            history, facts = await asyncio.gather(self._memory.load(ctx), self._facts(ctx, client))
            language = _language(text)
            turn = await self._call_agent.run(
                client, text, history=history, sender_name=ctx.full_name or "",
                timezone=getattr(ctx, "timezone", None) or "Asia/Kolkata", correlation_id=correlation_id,
                facts=facts, language=SPOKEN_LANGUAGE.get(language or "", language),
            )
        finally:
            await client.close()
        words = turn.reply or turn.question
        if words:
            await self._memory.remember(ctx, text, words)
        return words

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
        return "\n".join(lines) + "\n\n" + await self._catalog_for(ctx, client)

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
