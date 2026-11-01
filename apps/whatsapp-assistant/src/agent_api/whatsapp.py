"""WA-119: the API agent on WhatsApp (``assistant_mode`` = ``api``).

For a company in this mode, a text or voice message from a known sender goes
here, after the journey has resolved the sender and checked the company
(unknown number, suspended company and trial cap keep their own replies). A
photo or document is not handled here yet: it returns ``False`` and the
journey carries on as before.

Per person, kept for a day: the last turns of the conversation and the entries
waiting for confirmation. Every reply that leaves entries waiting lists them
(drawn from their confirm lines) with Save / Cancel buttons; a tap on Save
sends them to the API as the sender. The person can also just say "save it":
the model then calls ``save_ready_entries`` and says what the API answered.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from channel.replies import ListRow, ReplySpec
from mesiri_contracts.assistant.enums import InputModality

from .agent import ApiAgent, PendingWrite, WriteResult, _detail, confirm
from .app import build_api_app
from .client import Actor, ApiClient
from .tools import build_tools

_log = logging.getLogger(__name__)

MODE = "api"
EVENT_SOURCE = "agent_api"
STATE_TTL_SECONDS = 24 * 3600
KEEP_TURNS = 12
SAVE_PREFIX = "apiag:save:"
CANCEL_PREFIX = "apiag:cancel:"
#: A tool round can read several things; a mixed voice note needs room.
MAX_STEPS = 10

COULD_NOT_HEAR = "I couldn't hear that voice note. Please send it again or type it."
NOT_NOW = "I couldn't work on that just now. Please send it again in a minute."
NOTHING_WAITING = "There is nothing waiting to save."
CANCELLED = "Cancelled. Nothing was saved."


class ApiWhatsApp:
    def __init__(self, *, provider: Any, database: Any, redis: Any,
                 send: Callable[[ReplySpec, str], Awaitable[Any]],
                 transcribe: Callable[[Any], Awaitable[tuple[str, str | None, str | None]]] | None,
                 message_logger: Any, trace_logger: Any | None = None, app: Any | None = None) -> None:
        self._redis = redis
        self._send = send
        self._transcribe = transcribe
        self._log_store = message_logger
        self._trace = trace_logger
        self._app = app if app is not None else build_api_app(database)
        self._agent = ApiAgent(provider, build_tools(self._app.openapi()), max_steps=MAX_STEPS,
                               capability="api_agent")

    # -- entry point -----------------------------------------------------------------------

    async def handle(self, message: Any, ctx: Any) -> bool:
        """True when the message was answered here; False leaves it to the journey."""
        tap = str((message.metadata or {}).get("interactive_reply_id") or "")
        if tap.startswith((SAVE_PREFIX, CANCEL_PREFIX)):
            reply = await self._on_tap(tap, ctx)
        elif message.modality is InputModality.TEXT and (message.text or "").strip():
            reply = await self._on_words(message.text.strip(), message, ctx)
        elif message.modality is InputModality.VOICE and self._transcribe is not None:
            try:
                transcript, translated, _ = await self._transcribe(message)
            except Exception:  # noqa: BLE001 -- said plainly, never silence
                _log.exception("agent_api.transcribe_failed user=%s", ctx.user_id)
                transcript, translated = "", None
            words = (transcript or translated or "").strip()
            reply = await self._on_words(words, message, ctx) if words else ReplySpec(text=COULD_NOT_HEAR)
        else:
            return False
        await self._send(reply, message.sender.wa_id)
        await _safe(self._log_store.log_reply(correlation_id=message.correlation_id, reply=reply.text))
        await _safe(self._log_store.mark_completed(correlation_id=message.correlation_id))
        return True

    # -- a message ---------------------------------------------------------------------------

    async def _on_words(self, text: str, message: Any, ctx: Any) -> ReplySpec:
        from mesiri_ai.models import ChatMessage

        state = await self._state(ctx)
        ready = [PendingWrite.from_json(e) for e in state.get("pending", [])]
        history = [ChatMessage(role=t["role"], text=t["text"]) for t in state.get("turns", [])]
        client = ApiClient(_actor(ctx), app=self._app)
        started = time.monotonic()
        try:
            turn = await self._agent.run(
                client, text, history=history, ready=ready, sender_name=ctx.full_name or "",
                timezone=getattr(ctx, "timezone", None) or "Asia/Kolkata", correlation_id=message.correlation_id,
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
            "pending": [e.summary for e in turn.pending],
        }, started)
        words = turn.reply or (_saved_text(turn.saved) if turn.saved else "")
        reply = self._with_ready(words, turn.pending, state)
        state["turns"] = [*state.get("turns", []), {"role": "user", "text": text},
                          {"role": "model", "text": reply.text}][-KEEP_TURNS:]
        await self._save_state(ctx, state)
        return reply

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
        text = _saved_text(results)
        state["turns"] = [*state.get("turns", []), {"role": "user", "text": "(tapped Save)"},
                          {"role": "model", "text": text}][-KEEP_TURNS:]
        await self._save_state(ctx, state)
        return _buttons(text, state["batch"]) if left else ReplySpec(text=text)

    # -- helpers -----------------------------------------------------------------------------

    def _with_ready(self, words: str, pending: list[PendingWrite], state: dict) -> ReplySpec:
        state["pending"] = [e.to_json() for e in pending]
        if not pending:
            state["batch"] = None
            return ReplySpec(text=words or "OK.")
        state["batch"] = uuid.uuid4().hex[:8]  # a new list: older buttons no longer act
        listed = "\n".join(f"{i}. {e.summary}" for i, e in enumerate(pending, 1))
        text = f"{words}\n\n*Ready to save:*\n{listed}" if words else f"*Ready to save:*\n{listed}"
        return _buttons(text, state["batch"])

    def _key(self, ctx: Any) -> str:
        return f"agent_api:{ctx.organization_id}:{ctx.user_id}"

    async def _state(self, ctx: Any) -> dict:
        try:
            return dict(await self._redis.get_json(self._key(ctx)) or {})
        except Exception:  # noqa: BLE001 -- a fresh conversation rather than no reply
            _log.warning("agent_api.state_unreadable user=%s", ctx.user_id, exc_info=True)
            return {}

    async def _save_state(self, ctx: Any, state: dict) -> None:
        try:
            await self._redis.set_json(self._key(ctx), state, ttl_seconds=STATE_TTL_SECONDS)
        except Exception:  # noqa: BLE001
            _log.warning("agent_api.state_unsaved user=%s", ctx.user_id, exc_info=True)

    async def _trace_turn(self, message: Any, payload: dict, started: float) -> None:
        if self._trace is None:
            return
        try:
            await self._trace.log_stage(
                correlation_id=message.correlation_id, stage="agent_api_turn", stage_payload=payload,
                duration_ms=int((time.monotonic() - started) * 1000), succeeded="error" not in payload,
                event_source=EVENT_SOURCE,
            )
        except Exception:  # noqa: BLE001 -- diagnostics never break a message
            _log.warning("agent_api.trace_failed", exc_info=True)


def _actor(ctx: Any) -> Actor:
    return Actor(user_id=str(ctx.user_id), organization_id=str(ctx.organization_id),
                 role=str(ctx.role or ""), name=ctx.full_name or "")


def _buttons(text: str, batch: str) -> ReplySpec:
    return ReplySpec(text=text, buttons=(ListRow(id=f"{SAVE_PREFIX}{batch}", title="Save"),
                                          ListRow(id=f"{CANCEL_PREFIX}{batch}", title="Cancel")))


def _saved_text(results: list[WriteResult]) -> str:
    lines = [f"✅ {r.pending.summary}" if r.ok else f"❌ {r.pending.summary}: {_detail(r.body)}" for r in results]
    head = "Saved." if all(r.ok for r in results) else "Not everything could be saved:"
    return head + "\n" + "\n".join(lines)


async def _safe(awaitable: Awaitable[Any]) -> None:
    try:
        await awaitable
    except Exception:  # noqa: BLE001 -- logging never breaks the reply
        _log.warning("agent_api.log_failed", exc_info=True)
