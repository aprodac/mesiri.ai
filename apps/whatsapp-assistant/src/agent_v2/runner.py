"""The v2 runners (request 174): same ``run`` as ``runtime.agent.runner.AgentRunner``, so the
journey swaps one object and everything around the turn (context, gateway, the reply, the
Save card, outage handling) stays today's.

- ``V2Runner`` (``assistant_mode = v2``, alias ``v2_materials``): request 180. ONE agent reads
  EVERY eligible message (plain text or voice), decides and writes its own reply. There is no
  routing and no hand-back: the old code is only tools (materials, the existing record tools,
  reads). The reply is still composed by the same code as today's (honest wording, number guard,
  the card). Today's agent runs only if v2 fails before any action (an outage), never as "not
  my topic".
- ``ShadowRunner`` (``assistant_mode = v2_shadow``): today's agent answers as usual; v2 then
  runs in the background on the same message with the draft tools stubbed (nothing is
  drafted, nothing is saved) and its proposed lines are logged next to what today's agent did.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import replace
from typing import Any

from channel.replies import ReplySpec
from runtime.agent import runner as classic_runner
from runtime.agent.runner import AgentResult, AgentRunner
from runtime.agent.wording import language_of, say, usual_from

from .agents.main import MainAgent, V2Run
from .skills.materials import tools as skill

_log = logging.getLogger("mesiri.agent_v2")

SHADOW_STAGE = "agent_v2_shadow"
LIVE_STAGE = "agent_v2_live"
EVENT_SOURCE = "agent_v2"
#: Loop guard: sender -> (fingerprint of the last reply text, monotonic time).
REPEAT_WINDOW_SECONDS = 600.0
_LAST_REPLY: dict[str, tuple[str, float]] = {}


def _fingerprint(text: str) -> str:
    return " ".join((text or "").casefold().split())


def _eligible(gateway: Any, ctx: Any, site_queue: Any, look_at_photo: Any) -> str | None:
    """Why v2 must not read this message (None: it may). Each reason is a state where the
    message is an answer to, or a step of, something today's agent owns."""
    if getattr(gateway, "draft_mode", False) is not True:
        return "not_draft_mode"  # v2 only ever adds card lines; without a card it could not hold back a save
    if site_queue:
        return "site_question_waiting"
    if getattr(ctx, "has_pending_confirmation", False):
        return "pending_confirmation"
    if look_at_photo is not None:
        return "photo_held"
    return None


def _organization_id(gateway: Any) -> str | None:
    actor = getattr(gateway, "actor", None)
    org = getattr(actor, "organization_id", None)
    return str(org) if org else None


def _language(ctx: Any, user_text: str) -> str:
    return language_of(user_text, usual_from(getattr(ctx, "last_language", None), getattr(ctx, "last_script", None)))


def _summary(result: AgentResult) -> dict[str, Any]:
    """What today's agent did, for the side-by-side."""
    calls = [{"tool": c.name, "args": c.arguments} for c in (result.run.calls if result.run else [])]
    return {
        "outcome": result.outcome,
        "calls": calls,
        "lines": [s.summary for s in result.toolbox.saved if getattr(s, "summary", None)],
        "reply": (result.reply.text if result.reply else None),
    }


class V2Runner:
    def __init__(self, provider: Any, classic: AgentRunner, *, catalog: Any | None = None, trace_logger: Any | None = None) -> None:
        self._classic = classic
        self._agent = MainAgent(provider, catalog=catalog)
        self._trace = trace_logger

    async def run(self, *, ctx, user_text, gateway, scope, correlation_id=None, lap=None, after_tool=None,  # noqa: ANN001
                  site_queue=None, reply_language_setter=None, look_at_photo=None) -> AgentResult:
        async def classic() -> AgentResult:
            return await self._classic.run(
                ctx=ctx, user_text=user_text, gateway=gateway, scope=scope, correlation_id=correlation_id,
                lap=lap, after_tool=after_tool, site_queue=site_queue,
                reply_language_setter=reply_language_setter, look_at_photo=look_at_photo,
            )

        if (why := _eligible(gateway, ctx, site_queue, look_at_photo)) is not None:
            await self._log(correlation_id, "classic", why, None, 0)
            return await classic()
        started = time.perf_counter()
        v2 = await self._agent.run(
            ctx=ctx, user_text=user_text, gateway=gateway, scope=scope, organization_id=_organization_id(gateway),
            correlation_id=correlation_id, lap=lap, after_tool=after_tool, language=_language(ctx, user_text),
        )
        ms = int((time.perf_counter() - started) * 1000)
        if v2.error is not None and not v2.took_message:
            # The ONLY way today's agent runs for an eligible message (request 180): v2 failed
            # before any action (a model outage), so nothing is on the card and nothing was said.
            await self._log(correlation_id, "classic", f"error:{type(v2.error).__name__}", v2, ms)
            return await classic()
        await self._log(correlation_id, "v2", "took_message" if v2.took_message else "answered", v2, ms)
        if v2.error is not None:
            # A failure after v2 began (a line is on the card, or a question is parked): never
            # run today's agent on top of it; say what is on the card, as today's runner does.
            _log.exception("agent_v2.degraded correlation_id=%s", correlation_id, exc_info=v2.error)
            return AgentResult("degraded", self._classic._fallback(v2.toolbox, partial=True), v2.toolbox, error=v2.error)
        result = await self._finish(v2, user_text, correlation_id)
        return self._no_repeat(result, v2, gateway, ctx, user_text)

    def _no_repeat(self, result: AgentResult, v2: V2Run, gateway: Any, ctx: Any, user_text: str) -> AgentResult:
        """Loop guard (request 180): the same reply is never sent twice in a row to a sender
        within 10 minutes. Only a words-only reply is guarded (no tool was called): a card or a
        stock answer may legitimately read the same twice. The second one says so and asks for
        the need in a few words."""
        if v2.calls:
            return result
        reply = result.reply
        sender = str(getattr(getattr(gateway, "actor", None), "user_id", "") or "")
        if reply is None or not sender or not (reply.text or "").strip():
            return result
        now = time.monotonic()
        key = _fingerprint(reply.text)
        last = _LAST_REPLY.get(sender)
        _LAST_REPLY[sender] = (key, now)
        if len(_LAST_REPLY) > 2000:
            for who in [w for w, (_, at) in _LAST_REPLY.items() if now - at > REPEAT_WINDOW_SECONDS]:
                del _LAST_REPLY[who]
        if last is None or last[0] != key or now - last[1] > REPEAT_WINDOW_SECONDS:
            return result
        _log.warning("agent_v2.repeat_reply_blocked sender=%s", sender)
        language = _language(ctx, user_text)
        return AgentResult(result.outcome, replace(reply, text=say("v2.repeat_reply", language)), result.toolbox,
                           run=result.run, error=result.error)


    async def _finish(self, v2: V2Run, user_text: str, correlation_id: str | None) -> AgentResult:
        """The same closing steps as today's runner, over the same toolbox."""
        toolbox, run = v2.toolbox, v2.run
        assert run is not None  # took_message without a run only after an error, handled above
        if v2.request_not_built:
            # Request 178: "cement venam" is a request for material, which is not built. One fast,
            # honest line (not 35 s and "I'll process this in a few minutes"). When the message also
            # put lines on the card, the line goes under the card.
            line = say("material_request.not_built", toolbox.language)
            if not toolbox.attempted_writes and toolbox.parked is None:
                return AgentResult("ok", ReplySpec(text=line), toolbox, run=run)
            toolbox.system_lines.append(line)
        await toolbox.finish_site_queue()
        run = AgentRunner._one_script(run, user_text, correlation_id)
        classic_runner._park_plain_question(run, toolbox)
        # Request 178: the figures are the model's own account (what each call places, what it left
        # off and why); the code asks only about a figure neither placed nor explained. A turn that
        # drafted nothing (a lookup) has no card to put figures on.
        drafted = any(name in skill.DRAFT_TOOLS for name, _ in v2.calls)
        missing = skill.unplaced_figures(user_text, v2.calls, v2.asked) if drafted else []
        if missing and toolbox.parked is None and toolbox.language in ("english", "manglish", "hinglish"):
            # Every number in the message must end up on the card or be asked about.
            toolbox.system_lines.append("I did not put " + ", ".join(missing) + " on the card. What is it for?")
        sources = [user_text]
        for call in run.calls:
            sources.append(json.dumps(call.arguments, ensure_ascii=False, default=str))
            sources.append(json.dumps(call.outcome.content, ensure_ascii=False, default=str))
        if not classic_runner.unbacked_numbers(run.text or "", sources):
            run = AgentRunner._covering(run, toolbox, correlation_id)
        return AgentResult("ok", self._classic._compose(run, toolbox, sources, correlation_id), toolbox, run=run)

    async def _log(self, correlation_id: str | None, handled_by: str, why: str, v2: V2Run | None, ms: int) -> None:
        payload = {
            "handled_by": handled_by,
            "why": why,
            "calls": [{"tool": n, "args": a} for n, a in (v2.calls if v2 else [])],
            "ms": ms,
        }
        _log.info("agent_v2.live correlation_id=%s %s", correlation_id, json.dumps(payload, ensure_ascii=False, default=str))
        await _trace(self._trace, correlation_id, LIVE_STAGE, payload, ms)


class ShadowRunner:
    """Today's agent answers; v2 runs afterwards, in the background, saving nothing."""

    def __init__(self, provider: Any, classic: AgentRunner, *, catalog: Any | None = None, trace_logger: Any | None = None) -> None:
        self._classic = classic
        self._agent = MainAgent(provider, catalog=catalog)
        self._trace = trace_logger
        self._tasks: set[asyncio.Task[None]] = set()

    async def run(self, *, ctx, user_text, gateway, scope, correlation_id=None, **kw) -> AgentResult:  # noqa: ANN001, ANN003
        result = await self._classic.run(
            ctx=ctx, user_text=user_text, gateway=gateway, scope=scope, correlation_id=correlation_id, **kw
        )
        task = asyncio.ensure_future(self._shadow(ctx, user_text, gateway, scope, correlation_id, _summary(result)))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return result

    async def _shadow(self, ctx, user_text, gateway, scope, correlation_id, old) -> None:  # noqa: ANN001
        started = time.perf_counter()
        try:
            v2 = await self._agent.run(
                ctx=ctx, user_text=user_text, gateway=gateway, scope=scope, organization_id=_organization_id(gateway),
                correlation_id=correlation_id, language=_language(ctx, user_text), shadow=True,
            )
        except Exception:  # noqa: BLE001 -- a shadow never disturbs a message
            _log.warning("agent_v2.shadow_failed correlation_id=%s", correlation_id, exc_info=True)
            return
        ms = int((time.perf_counter() - started) * 1000)
        payload = {
            "message": user_text,
            "v2": {
                "took_message": v2.took_message,
                "handed_back": v2.handed_back,
                "error": type(v2.error).__name__ if v2.error else None,
                "calls": [{"tool": n, "args": a} for n, a in v2.calls],
                "unplaced_figures": skill.unplaced_figures(user_text, v2.calls, v2.asked),
                "reply": (v2.run.text if v2.run else None),
                "ms": ms,
            },
            "classic": old,
        }
        await _trace(self._trace, correlation_id, SHADOW_STAGE, payload, ms)


async def _trace(trace_logger: Any | None, correlation_id: str | None, stage: str, payload: dict[str, Any], ms: int) -> None:
    if trace_logger is None or not correlation_id:
        return
    try:
        await trace_logger.log_stage(
            correlation_id=correlation_id, stage=stage, stage_payload=payload, duration_ms=ms,
            succeeded=True, event_source=EVENT_SOURCE,
        )
    except Exception:  # noqa: BLE001 -- diagnostics never break a message
        _log.warning("agent_v2.trace_failed stage=%s", stage, exc_info=True)
