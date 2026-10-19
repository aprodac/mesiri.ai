"""One inbound message through the agent, from words to the sent reply.

`message_journey` calls this for a free-text or voice message when the
company's `assistant_mode` is "agent". It gathers the context, runs the
`AgentRunner`, sends the one reply, records the turn, and handles an AI outage
the way the classic path does (queue + retry).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from backend.ports import ActorIdentity
from channel.replies import ReplySpec
from mesiri_contracts.assistant.enums import InputModality
from mesiri_contracts.assistant.normalized_message import NormalizedMessage
from runtime.ai_outage import AIUnavailableError, reply_for_attempt, retry_attempt

from .prompt import AgentContext, Turn
from .runner import AgentResult, AgentRunner, default_now
from .tools import ScopeLookup

_log = logging.getLogger("mesiri.agent")

CANT_HEAR_REPLY = "I couldn't hear that clearly. Could you send it again?"


@dataclass(slots=True)
class AgentTurnDeps:
    """Everything the turn needs from the journey, as small callables."""

    runner: AgentRunner
    #: ``(message, gateway) `` is built by the caller per turn; see ``make_gateway``.
    make_gateway: Callable[[NormalizedMessage, str | None], Any]
    send_spec: Callable[[ReplySpec, str], Awaitable[None]]
    #: voice -> (transcript, translated, language); None when not wired.
    transcribe: Callable[[NormalizedMessage], Awaitable[tuple[str, str | None, str | None]]] | None
    message_logger: Any
    memory_loader: Any | None = None
    memory_coordinator: Any | None = None
    user_language_store: Any | None = None
    reply_composer: Any | None = None
    #: ``(reply, wa_id, gateway)``: sends the reply with the saved items' offers
    #: (team photo, undo) folded in; None sends the reply alone.
    send_agent_reply: Callable[[ReplySpec, str, Any], Awaitable[None]] | None = None
    #: ``(reply, gateway) -> reply``: renders the receipt card of what the turn
    #: saved and returns the reply carrying it as ``header_image``.
    attach_receipt: Callable[[ReplySpec, Any], Awaitable[ReplySpec]] | None = None
    now: Callable[[], Any] = default_now


def _scope_of(actor: ActorIdentity) -> ScopeLookup:
    return ScopeLookup(
        projects=tuple((p.id, p.name) for p in actor.projects),
        sites=tuple((s.id, s.name, s.project_id) for s in actor.sites),
    )


def _context_of(
    actor: ActorIdentity, deps: AgentTurnDeps, pack: Any | None, language: str | None,
    menu_hint: str | None,
) -> AgentContext:
    project_names = {p.id: p.name for p in actor.projects}
    return AgentContext(
        user_name=actor.full_name,
        role=actor.role,
        company=actor.org_name or "their company",
        now=deps.now(),
        projects=tuple((p.name, p.location) for p in actor.projects),
        sites=tuple((s.name, project_names.get(s.project_id or "")) for s in actor.sites),
        turns=tuple(
            Turn(t.user_text, t.assistant_reply) for t in (getattr(pack, "recent_turns", ()) or ())
        ),
        last_language=language,
        has_pending_confirmation=bool(getattr(pack, "has_pending_confirmation", False)),
        menu_hint=menu_hint,
    )


async def _outage(
    message: NormalizedMessage,
    language: str | None,
    deps: AgentTurnDeps,
    error: BaseException,
    user_id: str | None = None,
) -> None:
    """Every AI call failed before anything was saved: tell the sender it is
    queued and raise, so the worker retries the message (runtime/ai_outage.py)."""
    attempt = retry_attempt.get()
    text, will_retry = reply_for_attempt(attempt)
    correlation_id = message.correlation_id
    # error level, with the cause: this is the line an alert watches (request [43]).
    _log.error(
        "agent.outage correlation_id=%s attempt=%s error=%r",
        correlation_id, attempt, error, exc_info=error,
    )
    if text:
        if deps.reply_composer is not None and language:
            script = None
            if deps.user_language_store is not None and user_id:
                try:
                    script = await deps.user_language_store.get_script(user_id=user_id)
                except Exception:  # noqa: BLE001 — wording never costs the reply
                    script = None
            text = await deps.reply_composer.compose(
                text, language=language, correlation_id=correlation_id, script=script
            )
        await deps.send_spec(ReplySpec(text=text), message.sender.wa_id)
        await _safe(deps.message_logger.log_reply(correlation_id=correlation_id, reply=text))
    if will_retry:
        await _safe(deps.message_logger.mark_failed(correlation_id=correlation_id, error_code="AI_UNAVAILABLE"))
        raise AIUnavailableError(f"agent: every AI call failed for {correlation_id}") from error
    await _safe(deps.message_logger.mark_completed(correlation_id=correlation_id))


async def _safe(coro: Awaitable[Any]) -> None:
    try:
        await coro
    except Exception:  # noqa: BLE001 — logging/memory are best-effort
        _log.warning("agent.best_effort_failed", exc_info=True)


def _as_text(reply: ReplySpec) -> str:
    options = [r.title for r in (reply.buttons or reply.list_rows or ())]
    return f"{reply.text}\n[options: {' / '.join(options)}]" if options else reply.text


async def run_agent_turn(
    message: NormalizedMessage,
    actor: ActorIdentity,
    deps: AgentTurnDeps,
    *,
    menu_hint: str | None = None,
) -> AgentResult | None:
    """Returns the result, or None when nothing could be read from the message
    (an unheard voice note, answered already)."""
    wa_id = message.sender.wa_id
    correlation_id = message.correlation_id
    language: str | None = None
    user_text = (message.text or "").strip()

    if message.modality is InputModality.VOICE:
        if deps.transcribe is None:
            return None
        try:
            transcript, translated, language = await deps.transcribe(message)
        except Exception as exc:  # noqa: BLE001 — a speech outage is an outage
            await _outage(message, None, deps, exc)
            return None
        user_text = (transcript or translated or "").strip()
        if not user_text:
            await deps.send_spec(ReplySpec(text=CANT_HEAR_REPLY), wa_id)
            await _safe(deps.message_logger.log_reply(correlation_id=correlation_id, reply=CANT_HEAR_REPLY))
            await _safe(deps.message_logger.mark_completed(correlation_id=correlation_id))
            return None
        await _safe(deps.message_logger.update_body_text(correlation_id=correlation_id, body_text=user_text))
        if deps.user_language_store is not None and language:
            await _safe(
                deps.user_language_store.remember(
                    user_id=actor.user_id, detected_language=language, text=user_text
                )
            )

    if language is None and deps.user_language_store is not None:
        try:
            language = await deps.user_language_store.get(user_id=actor.user_id)
        except Exception:  # noqa: BLE001
            language = None

    pack = None
    if deps.memory_loader is not None and actor.organization_id:
        try:
            pack = await deps.memory_loader.load(
                organization_id=actor.organization_id, user_id=actor.user_id
            )
        except Exception:  # noqa: BLE001 — memory is a hint
            _log.warning("agent.memory_load_failed user=%s", actor.user_id)

    gateway = deps.make_gateway(message, language)
    result = await deps.runner.run(
        ctx=_context_of(actor, deps, pack, language, menu_hint),
        user_text=user_text,
        gateway=gateway,
        scope=_scope_of(actor),
        correlation_id=correlation_id,
    )
    if result.outcome == "outage" or result.reply is None:
        await _outage(message, language, deps, result.error or RuntimeError("no reply"), actor.user_id)
        return result

    reply = result.reply
    if deps.attach_receipt is not None:
        try:
            reply = await deps.attach_receipt(reply, gateway)
        except Exception:  # noqa: BLE001 — the reply goes out without the card
            _log.exception("agent.receipt_attach_failed")
    if deps.send_agent_reply is not None and result.toolbox.parked is None:
        await deps.send_agent_reply(reply, wa_id, gateway)
    else:
        await deps.send_spec(reply, wa_id)
    await _audit(message, gateway, reply, deps)
    if deps.memory_coordinator is not None:
        await _safe(
            deps.memory_coordinator.record_turn(
                user_id=actor.user_id,
                user_text=user_text,
                assistant_reply=_as_text(reply),
                correlation_id=correlation_id,
            )
        )
    # Follow-ups (worker promotion, team-photo offer...) only when nothing else
    # is waiting on the sender: they are questions too.
    if result.toolbox.parked is None:
        await gateway.finish()
    return result


async def _audit(
    message: NormalizedMessage, gateway: Any, reply: ReplySpec, deps: AgentTurnDeps
) -> None:
    correlation_id = message.correlation_id
    log = deps.message_logger
    tasks = [log.log_reply(correlation_id=correlation_id, reply=reply.text)]
    for handled in getattr(gateway, "handled", []):
        instance = getattr(handled.result, "workflow_instance_id", None)
        if instance:
            tasks.append(
                log.link_workflow_instance(
                    correlation_id=correlation_id, workflow_instance_id=instance
                )
            )
        tasks.append(
            log.update_context(
                correlation_id=correlation_id,
                project_id=handled.project_id,
                site_id=handled.site_id,
            )
        )
    tasks.append(log.mark_completed(correlation_id=correlation_id))
    await asyncio.gather(*tasks, return_exceptions=True)
