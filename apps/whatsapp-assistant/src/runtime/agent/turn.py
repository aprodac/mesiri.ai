"""One inbound message through the agent, from words to the sent reply.

`message_journey` calls this for every text, voice, photo or document message
(ARCH-06: there is no other route). It gathers the context, runs the
`AgentRunner`, sends the one reply, records the turn, and handles an AI outage
(queue + retry).
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import Any

from backend.ports import ActorIdentity
from channel.replies import ReplySpec
from mesiri_contracts.assistant.enums import InputModality
from mesiri_contracts.assistant.normalized_message import NormalizedMessage
from runtime.ai_outage import (
    QUICK_RETRY_PAUSE_SECONDS,
    AIUnavailableError,
    reply_for_attempt,
    retry_attempt,
)
from runtime.persona import guard, is_what_can_you_do, what_can_you_do

from . import later
from .left_it import LEFT_IT, is_drop_word, question_is_open
from .prompt import AgentContext, Turn, preferred_language
from .runner import AgentResult, AgentRunner, default_now
from .stale_questions import close_stale_questions
from .stock_question import is_stock_question
from .tools import QUERY_MATERIALS, ScopeLookup

_log = logging.getLogger("mesiri.agent")

#: A reply saying the message was not understood (English, Manglish, Malayalam, Hindi).
_NOT_UNDERSTOOD = re.compile(
    r"(?:could ?n[o']?t|did ?n[o']?t|do ?n[o']?t|cannot|can't) (?:quite )?understand|not sure what you mean"
    r"|manass?ilaay?illa|manass?ilaay?ittilla|മനസ്സിലായില്ല|samajh nahi",
    re.IGNORECASE,
)

CANT_HEAR_REPLY = "I couldn't hear that clearly. Could you send it again?"
UNREADABLE_REPLY = "Sorry, I couldn't make out that message. Please type it or send a voice note."
CANT_READ_REPLY = "I couldn't read that. Could you send a clearer photo, or type the details?"


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
    #: photo/document -> what it shows, in words (None: unreadable); None when not wired.
    describe: Callable[[NormalizedMessage, str | None], Awaitable[str | None]] | None = None
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
    #: B-7: the journey's lap stopwatch (runtime/step_timing.py), so the
    #: prepipeline trace says where an agent turn's time went.
    lap: Callable[[str], None] | None = None
    #: B-7: run after each tool call (the receipt card starts early).
    after_tool: Callable[[], None] | None = None
    #: [68]: ``(actor) -> "Today so far: ..." | None``, read-only context for the
    #: reply writer (runtime/today_context.py); None leaves it out.
    today_line: Callable[[ActorIdentity], Awaitable[str | None]] | None = None
    #: WA-36: ``(actor) -> "Stock now at ...: ..." | None``, read-only context
    #: (runtime/today_context.py's build_stock_line); None leaves it out.
    stock_line: Callable[[ActorIdentity], Awaitable[str | None]] | None = None
    #: WA-45: ``(actor) -> "Site B (Project B)" | None``, where they work today
    #: (runtime/agent/work_site.py); None leaves it out.
    work_site_line: Callable[[ActorIdentity], Awaitable[str | None]] | None = None
    #: ``(actor) -> "Open work at Site A1: ..." | None``: the sender's open
    #: activities, so the model can say which one a message continues
    #: (runtime/today_context.py's render_open_work_line); None leaves it out.
    open_work_line: Callable[[ActorIdentity], Awaitable[str | None]] | None = None
    #: Request 88: ``(actor) -> "Their open card ..." | None``: the latest card,
    #: with the ids the model may name (runtime/agent/cards.py).
    card_line: Callable[[ActorIdentity], Awaitable[str | None]] | None = None
    #: [68]: called when the reply saved nothing (a question or small talk), so
    #: the journey holds setup nudges ("add another site?") for after a save.
    on_conversational: Callable[[], None] | None = None
    #: [68]: journey traces; guardrail hits are logged as stage "persona_guard".
    trace_logger: Any | None = None
    #: WA-57: the sender's parts still to do (runtime/agent/later.py's
    #: LaterStore); None keeps no list.
    later: Any | None = None
    #: [111]: saves waiting on the site answer (runtime/agent/site_wait.py's
    #: SiteWaitStore); None keeps none.
    site_wait: Any | None = None
    #: Request 132: ``(actor) -> the company's switched-on modules``, so the help
    #: lists only what they have; None lists the general help.
    enabled_modules: Callable[[ActorIdentity], Awaitable[list[str] | None]] | None = None


def _scope_of(actor: ActorIdentity) -> ScopeLookup:
    return ScopeLookup(
        projects=tuple((p.id, p.name) for p in actor.projects),
        sites=tuple((s.id, s.name, s.project_id) for s in actor.sites),
    )


def _context_of(
    actor: ActorIdentity, deps: AgentTurnDeps, pack: Any | None, language: str | None,
    menu_hint: str | None,
    script: str | None = None,
    draft_mode: bool = False,
) -> AgentContext:
    project_names = {p.id: p.name for p in actor.projects}
    return AgentContext(
        user_name=actor.full_name,
        role=actor.role,
        company=actor.org_name or "their company",
        now=deps.now(),
        projects=tuple((p.name, p.location) for p in actor.projects),
        sites=tuple((s.name, project_names.get(s.project_id or "")) for s in actor.sites),
        turns=_turns_for_model(
            tuple(
                Turn(t.user_text, t.assistant_reply, getattr(t, "at", 0.0))
                for t in (getattr(pack, "recent_turns", ()) or ())
            ),
            deps.now().timestamp(),
            draft_mode,
        ),
        last_language=language,
        last_script=script,
        has_pending_confirmation=bool(getattr(pack, "has_pending_confirmation", False)),
        menu_hint=menu_hint,
    )


def _turns_for_model(turns: tuple[Turn, ...], now: float, draft_mode: bool) -> tuple[Turn, ...]:
    """Request 132: on a draft card the model is shown the sender's words and a
    short gist of each answer (the state is one block, ``card_line``); otherwise the
    turns as they were, each stale question marked closed."""
    if draft_mode:
        from .history import for_model

        return for_model(turns)
    return close_stale_questions(turns, now)


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
    (an unheard voice note, answered already). The reply language the sender
    set (``set_reply_language``) holds for every reply of this turn."""
    preference = None
    if deps.user_language_store is not None and hasattr(deps.user_language_store, "get_preference"):
        try:
            preference = await deps.user_language_store.get_preference(user_id=actor.user_id)
        except Exception:  # noqa: BLE001 -- the message's own language then decides
            preference = None
    token = preferred_language.set(preference)
    try:
        return await _run_agent_turn(message, actor, deps, menu_hint=menu_hint)
    finally:
        preferred_language.reset(token)


async def _replying_to(message: NormalizedMessage) -> tuple[str, str] | None:
    """Live 29 Oct: the words of the message the sender swiped and replied to
    (channel/whatsapp/sent_text.py), or None. Never raises."""
    from channel.whatsapp import sent_text

    reply_context = getattr(message, "reply_context", None)
    quoted_id = getattr(reply_context, "replied_to_message_id", None)
    if not quoted_id:
        return None
    if getattr(reply_context, "replied_to_text", None):
        return str(reply_context.replied_to_text), "mesiri"
    try:
        return await sent_text.text_of(quoted_id)
    except Exception:  # noqa: BLE001 -- read as a plain message
        return None


async def _run_agent_turn(
    message: NormalizedMessage,
    actor: ActorIdentity,
    deps: AgentTurnDeps,
    *,
    menu_hint: str | None = None,
) -> AgentResult | None:
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
        # WEB-37: the English too, for the Live report (when it says something else).
        english = (translated or "").strip()
        await _safe(
            deps.message_logger.update_body_text(
                correlation_id=correlation_id,
                body_text=user_text,
                translated_text=english if english and english != user_text else None,
            )
        )
        if deps.user_language_store is not None and language:
            await _safe(
                deps.user_language_store.remember(
                    user_id=actor.user_id, detected_language=language, text=user_text
                )
            )

    if message.modality in (InputModality.IMAGE, InputModality.DOCUMENT):
        # ARCH-06: a photo or a bill is read by the vision model and the agent
        # reads what it shows as the message; the entries attach the file.
        if deps.describe is None:
            return None
        try:
            shown = await deps.describe(message, menu_hint)
        except Exception as exc:  # noqa: BLE001 — a vision outage is an outage
            await _outage(message, None, deps, exc)
            return None
        if not shown:
            await deps.send_spec(ReplySpec(text=CANT_READ_REPLY), wa_id)
            await _safe(deps.message_logger.log_reply(correlation_id=correlation_id, reply=CANT_READ_REPLY))
            await _safe(deps.message_logger.mark_completed(correlation_id=correlation_id))
            return None
        kind = "photo" if message.modality is InputModality.IMAGE else "document"
        caption = f' with the words "{user_text}"' if user_text else ""
        user_text = f"(They sent a {kind}{caption}. It shows: {shown})"

    script: str | None = None
    if deps.user_language_store is not None:
        try:
            stored_language, script = await deps.user_language_store.get_profile(user_id=actor.user_id)
            if language is None or preferred_language.get() is not None:
                # The language they set wins over the one this voice note was in.
                language = stored_language
        except Exception:  # noqa: BLE001
            script = None

    # Live 29 Oct: a later swipe-reply to this message reads its words.
    from channel.whatsapp import sent_text

    await _safe(sent_text.remember(wamid=str(getattr(message, "message_id", "") or ""), text=user_text, by="sender"))
    replying_to = await _replying_to(message)

    if is_what_can_you_do(user_text):
        # [68]: the commonest question has a fixed 3-line answer, no model needed.
        modules = await _context_line(deps.enabled_modules, actor)
        reply = ReplySpec(text=what_can_you_do(language, script, user_text, modules))
        await deps.send_spec(reply, wa_id)
        if deps.on_conversational is not None:
            deps.on_conversational()
        await _safe(deps.message_logger.log_reply(correlation_id=correlation_id, reply=reply.text))
        await _safe(deps.message_logger.mark_completed(correlation_id=correlation_id))
        if deps.memory_coordinator is not None:
            await _safe(
                deps.memory_coordinator.record_turn(
                    user_id=actor.user_id,
                    user_text=user_text,
                    assistant_reply=reply.text,
                    correlation_id=correlation_id,
                )
            )
        return None

    pack = None
    if deps.memory_loader is not None and actor.organization_id:
        try:
            pack = await deps.memory_loader.load(
                organization_id=actor.organization_id, user_id=actor.user_id
            )
        except Exception:  # noqa: BLE001 — memory is a hint
            _log.warning("agent.memory_load_failed user=%s", actor.user_id)

    if is_drop_word(user_text) and question_is_open(pack) and not getattr(pack, "has_pending_confirmation", False):
        # [103]: "cancel that" answers the open question; it is not an undo.
        reply = ReplySpec(text=LEFT_IT)
        await deps.send_spec(reply, wa_id)
        if deps.on_conversational is not None:
            deps.on_conversational()
        await _safe(deps.message_logger.log_reply(correlation_id=correlation_id, reply=reply.text))
        await _safe(deps.message_logger.mark_completed(correlation_id=correlation_id))
        if deps.memory_coordinator is not None:
            await _safe(
                deps.memory_coordinator.record_turn(
                    user_id=actor.user_id,
                    user_text=user_text,
                    assistant_reply=reply.text,
                    correlation_id=correlation_id,
                )
            )
        return None

    gateway = deps.make_gateway(message, language)
    context = _context_of(actor, deps, pack, language, menu_hint, script, getattr(gateway, "draft_mode", False) is True)
    # [68] / WA-36: read-only context lines, fetched together; a failure leaves one out.
    lines = await asyncio.gather(
        *(
            _context_line(fetch, actor)
            for fetch in (
                deps.today_line, deps.stock_line, deps.work_site_line, deps.open_work_line, deps.card_line
            )
        )
    )
    context = replace(
        context,
        today_line=lines[0],
        stock_line=lines[1],
        work_site=lines[2],
        open_work_line=lines[3],
        card_line=lines[4],
        replying_to=replying_to,
    )
    setter = _language_setter(deps, actor)
    # Request 136 (B): with draft cards what is still to do is a waiting line of the
    # card, so the old "later" list is neither shown nor kept.
    keeps_later = deps.later is not None and getattr(gateway, "draft_mode", False) is not True
    later_items = await deps.later.get(actor) if keeps_later else []
    later_line = later.context_line(later_items)
    if later_line:
        context = replace(context, notes=[*context.notes, later_line])
    _lap(deps, "agent_context")
    site_queue = await deps.site_wait.get(actor) if deps.site_wait is not None else []
    if site_queue and getattr(gateway, "draft_mode", False) is True:
        # WA-81: with draft cards "which site?" of a draft line is a question of the
        # card; such a line is never held in the [111] queue (only what a card cannot
        # hold, e.g. a transfer, still is), so nothing can be dropped there, or come back.
        from .draft import DRAFT_TOOLS

        kept = [item for item in site_queue if item.get("tool") not in DRAFT_TOOLS]
        if kept != site_queue:
            await _safe(deps.site_wait.put(actor, kept))
            site_queue = kept
    result = await deps.runner.run(
        ctx=context,
        user_text=user_text,
        gateway=gateway,
        scope=_scope_of(actor),
        correlation_id=correlation_id,
        **({"site_queue": site_queue} if site_queue else {}),
        **({"lap": deps.lap} if deps.lap is not None else {}),
        **({"after_tool": deps.after_tool} if deps.after_tool is not None else {}),
        **({"reply_language_setter": setter} if setter is not None else {}),
    )
    _lap(deps, "agent_model")
    if result.outcome == "outage":
        # One quick second try before telling the sender anything (request 57,
        # A5). An "outage" outcome means no record was attempted, so running
        # the message again cannot double-write.
        await asyncio.sleep(QUICK_RETRY_PAUSE_SECONDS)
        result = await deps.runner.run(
            ctx=replace(
                _context_of(
                    actor, deps, pack, language, menu_hint, script, getattr(gateway, "draft_mode", False) is True
                ),
                replying_to=replying_to,
            ),
            user_text=user_text,
            gateway=gateway,
            scope=_scope_of(actor),
            correlation_id=correlation_id,
            **({"site_queue": site_queue} if site_queue else {}),
            **({"lap": deps.lap} if deps.lap is not None else {}),
            **({"after_tool": deps.after_tool} if deps.after_tool is not None else {}),
            **({"reply_language_setter": setter} if setter is not None else {}),
        )
        _lap(deps, "agent_model_retry")
    if result.outcome == "outage" or result.reply is None:
        await _outage(message, language, deps, result.error or RuntimeError("no reply"), actor.user_id)
        return result

    reply = await _stock_lookup(result, user_text) or result.reply
    if _is_conversational(result):
        reply = await _guarded(reply, result, deps, message, user_text, context, gateway, actor, language, script)
        if getattr(gateway, "draft_mode", False) is True and _NOT_UNDERSTOOD.search(reply.text or ""):
            # WA-83 (live 27 Oct, M25): "I couldn't understand that" and nothing to copy.
            # The one help follows it: the company's modules, examples in their language.
            modules = await _context_line(deps.enabled_modules, actor)
            reply = replace(reply, text=f"{reply.text}\n\n{what_can_you_do(language, script, user_text, modules)}")
        if deps.on_conversational is not None:
            deps.on_conversational()
    if deps.attach_receipt is not None:
        try:
            reply = await deps.attach_receipt(reply, gateway)
        except Exception:  # noqa: BLE001 — the reply goes out without the card
            _log.exception("agent.receipt_attach_failed")
    _lap(deps, "agent_receipt")
    if deps.send_agent_reply is not None and result.toolbox.parked is None:
        await deps.send_agent_reply(reply, wa_id, gateway)
    else:
        await deps.send_spec(reply, wa_id)
    _lap(deps, "agent_send")
    await _audit(message, gateway, reply, deps)
    await _trace_tools(message.correlation_id, result, deps)
    await _trace_decisions(message.correlation_id, gateway, deps)
    if deps.site_wait is not None and hasattr(result.toolbox, "site_queue_after"):
        waiting = result.toolbox.site_queue_after()
        if waiting != site_queue:
            await _safe(deps.site_wait.put(actor, waiting))
    if keeps_later:
        box = result.toolbox
        after = later.merged(
            later_items,
            saved=[(i.tool, i.summary or i.text) for i in box.saved if not i.carried],
            added=box.later,
            drop=getattr(box, "later_drop", set()),
        )
        if after != later_items:
            await _safe(deps.later.put(actor, after))
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
    _lap(deps, "agent_audit")
    if result.toolbox.parked is None:
        await gateway.finish()
        _lap(deps, "agent_followups")
    return result


def _language_setter(
    deps: AgentTurnDeps, actor: ActorIdentity
) -> Callable[[str | None], Awaitable[bool]] | None:
    """``set_reply_language``'s keeper: the sender's reply language in the
    language store (runtime/reply_language.py); None when there is no store."""
    store = deps.user_language_store
    if store is None or not hasattr(store, "set_preference"):
        return None

    async def _set(preference: str | None) -> bool:
        return bool(await store.set_preference(user_id=actor.user_id, preference=preference))

    return _set


async def _context_line(
    fetch: Callable[[ActorIdentity], Awaitable[str | None]] | None, actor: ActorIdentity
) -> str | None:
    if fetch is None:
        return None
    try:
        return await fetch(actor)
    except Exception:  # noqa: BLE001 — context is a nicety
        return None


async def _stock_lookup(result: AgentResult, user_text: str) -> ReplySpec | None:
    """Request 93: a stock question the model answered in words without calling
    ``query_materials`` (from the stock line in its prompt) gets the lookup's
    own answer, so the Stock card is drawn every time. Only when the turn did
    nothing else: no save, no parked question, no lookup of its own."""
    box, run = result.toolbox, result.run
    if (
        result.outcome != "ok"
        or run is None
        or any(call.name == QUERY_MATERIALS for call in run.calls)
        or getattr(box, "saved", None)
        or getattr(box, "attempted_writes", 0)
        or getattr(box, "parked", None) is not None
        or not is_stock_question(user_text)
        or not hasattr(box, "look_up_stock")
    ):
        return None
    text = await box.look_up_stock()
    return ReplySpec(text=text) if text else None


def _is_conversational(result: AgentResult) -> bool:
    """The reply is the model's own words only: nothing saved or attempted, no
    parked question, and no tool answered anything (a query's answer is data)."""
    box = result.toolbox
    return (
        result.outcome == "ok"
        and result.reply is not None
        and hasattr(box, "saved")
        and not box.saved
        and "✅ Saved:" not in result.reply.text
        and not getattr(box, "attempted_writes", 0)
        and getattr(box, "parked", None) is None
        and not getattr(box, "answers", None)
        and not getattr(box, "notes", None)
    )


async def _guarded(
    reply: ReplySpec,
    result: AgentResult,
    deps: AgentTurnDeps,
    message: NormalizedMessage,
    user_text: str,
    context: AgentContext,
    gateway: Any,
    actor: ActorIdentity,
    language: str | None,
    script: str | None,
) -> ReplySpec:
    """[68] The deterministic voice check on a conversational reply: regenerate
    once with the broken rules named, else the localized fixed line."""

    async def _again(rules: list[str]) -> str | None:
        retry_ctx = replace(
            context,
            notes=[
                *context.notes,
                "Your previous reply was rejected for: "
                + ", ".join(rules)
                + ". Rewrite it: 1-2 short lines, name no company or model, and do not "
                "repeat any of your earlier replies.",
            ],
        )
        again = await deps.runner.run(
            ctx=retry_ctx,
            user_text=user_text,
            gateway=gateway,
            scope=_scope_of(actor),
            correlation_id=message.correlation_id,
        )
        return again.reply.text if again.outcome == "ok" and again.reply is not None else None

    guarded = await guard(
        reply.text,
        user_text=user_text,
        regenerate=_again,
        language=language,
        script=script,
        previous_replies=[t.assistant_reply for t in context.turns],
    )
    if deps.trace_logger is not None:
        await _safe(
            deps.trace_logger.log_stage(
                correlation_id=message.correlation_id,
                stage="persona_guard",
                stage_payload={
                    "reply_source": guarded.source,
                    "hits": [list(h) for h in guarded.hits],
                    "fell_back": guarded.fell_back,
                },
                duration_ms=None,
                succeeded=not guarded.fell_back,
            )
        )
    return reply if not guarded.hits else ReplySpec(text=guarded.text)


async def _trace_tools(correlation_id: str, result: AgentResult, deps: AgentTurnDeps) -> None:
    """INF-14: what the model decided this turn, for `vps-agent-trace`: each
    tool call's name, the names of its arguments and its outcome. No values
    and no message text, so the trace never holds what the sender said."""
    if deps.trace_logger is None:
        return
    box = result.toolbox
    calls = [
        {
            "tool": call.name,
            "args": sorted(call.arguments),
            "status": str((call.outcome.content or {}).get("status") or ("error" if call.error else "")),
        }
        for call in getattr(result.run, "calls", None) or []
    ]
    await _safe(
        deps.trace_logger.log_stage(
            correlation_id=correlation_id,
            stage="agent_tools",
            stage_payload={
                "calls": calls,
                "parked_by": getattr(box, "parked_by", None),
                "held": list(getattr(box, "held", []) or []),
                "still_to_do": [i.tool or "?" for i in getattr(box, "later", []) or []],
                "saved": [i.tool for i in getattr(box, "saved", []) or []],
            },
            duration_ms=None,
            succeeded=result.outcome == "ok",
        )
    )


async def _trace_decisions(correlation_id: str, gateway: Any, deps: AgentTurnDeps) -> None:
    """Request 136 (C): for a draft_v2 turn, which component decided each line's
    site, the lines and the reply (``JourneyGateway.decisions``), so a turn whose
    site did not come from the site resolver, or whose words above a card were not
    the code's, shows in `vps-agent-trace`. Names only, no message text."""
    if deps.trace_logger is None or getattr(gateway, "draft_mode", False) is not True:
        return
    await _safe(
        deps.trace_logger.log_stage(
            correlation_id=correlation_id,
            stage="draft_decisions",
            stage_payload={"pipeline": "draft_v2", "decisions": list(getattr(gateway, "decisions", []) or [])},
            duration_ms=None,
            succeeded=True,
        )
    )


def _lap(deps: AgentTurnDeps, name: str) -> None:
    if deps.lap is not None:
        deps.lap(name)


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
    # WEB-38: a question answered by a lookup is tied to it too, with the
    # project and site it was about, so the Live page can show it.
    for instance, project_id, site_id in getattr(gateway, "answered", []) or []:
        if instance:
            tasks.append(log.link_workflow_instance(correlation_id=correlation_id, workflow_instance_id=instance))
        tasks.append(log.update_context(correlation_id=correlation_id, project_id=project_id, site_id=site_id))
    tasks.append(log.mark_completed(correlation_id=correlation_id))
    await asyncio.gather(*tasks, return_exceptions=True)
