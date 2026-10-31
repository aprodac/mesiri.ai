"""v2's main agent, run by Google ADK, with the conversation kept whole (request 185).

Everything that decides and acts is ``MainAgent``'s: the tool specs, the handler (card lines,
reads, guards), the rule files, the catalog line and the after-run steps. What changes:

- the loop is ADK's ``Runner`` over an ``LlmAgent`` (tools: ``SpecTool``);
- the model sees the WHOLE conversation of today (``memory``): its own replies as they were
  sent, the questions it asked, the tool results, the message they swiped; not a 10-turn gist;
- the state of the day (sites, records, open card, catalog) is in the instructions, fresh each
  turn, never in the conversation.

Same ``run`` signature and ``V2Run`` result as ``MainAgent``, so ``V2Runner`` (the reply, the
Save card, the honesty guards, outage fallback) is unchanged.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import replace
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.agents.run_config import RunConfig
from google.adk.events import Event
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.sessions.base_session_service import BaseSessionService, GetSessionConfig
from google.genai import types

from mesiri_ai.models import ToolRunResult
from runtime.agent.prompt import AgentContext, build_messages
from runtime.agent.toolbox import AgentToolbox
from runtime.agent.tools import ScopeLookup

from ..agents.main import (
    MAX_STEPS,
    TIMEOUT_SECONDS,
    MainAgent,
    V2Run,
    all_specs,
    system_prompt,
    v2_card_words,
)
from . import memory
from .models import content_config, current_correlation_id
from .tools import RunState, SpecTool

_log = logging.getLogger("mesiri.agent_v2.adk")

AGENT_NAME = "mesiri"
#: How a code-drawn part of the sent reply is kept in the conversation (the model wrote the rest).
SHOWN_PREFIX = "[Shown to them under my words]"


def _words(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


class AdkAgent(MainAgent):
    """``MainAgent`` with ADK as the engine and ``memory`` as the conversation."""

    def __init__(
        self,
        model: Any,
        *,
        catalog: Any | None = None,
        sessions: BaseSessionService | None = None,
        clock: Any = None,
    ) -> None:
        super().__init__(provider=None, catalog=catalog)
        self._model = model
        self._sessions = sessions or InMemorySessionService()
        self._clock = clock

    @property
    def sessions(self) -> BaseSessionService:
        return self._sessions

    def _keys(self, gateway: Any, ctx: AgentContext) -> tuple[str, str]:
        actor = getattr(gateway, "actor", None)
        return memory.session_keys(
            getattr(actor, "organization_id", "-"), getattr(actor, "user_id", "-"), getattr(ctx, "now", None)
        )

    async def _session(self, user_id: str, session_id: str) -> Any:
        found = await self._sessions.get_session(
            app_name=memory.APP_NAME, user_id=user_id, session_id=session_id,
            config=GetSessionConfig(num_recent_events=0),
        )
        if found is None:
            found = await self._sessions.create_session(app_name=memory.APP_NAME, user_id=user_id, session_id=session_id)
        return found

    async def _prompt(self, ctx: AgentContext, user_text: str, organization_id: str | None, language: str) -> tuple[str, str]:
        """``(instruction, message)``: the rules + today's state, and the sender's words as the
        conversation keeps them (with the message they swiped, and the reply-letters rule)."""
        from runtime.agent.prompt import render_context, reply_letters_rule
        from runtime.agent.wording import usual_from

        # build_messages joins the context and the message into one user turn when there are no
        # turns; the context block is cut off exactly (the same rule decides its language lines).
        rule = reply_letters_rule(user_text, usual_from(ctx.last_language, ctx.last_script))
        block = f"[context]\n{render_context(replace(ctx, last_language=None, last_script=None) if rule else ctx)}"
        full = build_messages(replace(ctx, turns=()), user_text)[-1][1]
        message = full.removeprefix(block).lstrip("\n") if full.startswith(block) else full
        context = v2_card_words(block)
        if (line := await self.catalog_line(organization_id)):
            context = f"{context}\n{line}"
        instruction = (
            f"{system_prompt(language)}\n\n"
            "The conversation below is today's, in full: what they said and what you answered "
            "(your answers include the lines shown under your words). Never say you did not say "
            "something that is in it, and never ask again what they already answered in it.\n\n"
            f"{context}"
        )
        return instruction, message.replace("User message:\n", "", 1)

    async def run(
        self,
        *,
        ctx: AgentContext,
        user_text: str,
        gateway: Any,
        scope: ScopeLookup,
        organization_id: str | None,
        correlation_id: str | None = None,
        lap: Any = None,
        after_tool: Any = None,
        language: str = "english",
        shadow: bool = False,
    ) -> V2Run:
        toolbox = AgentToolbox(
            gateway=gateway, scope=scope, user_text=user_text, language=language, lap=lap, after_tool=after_tool
        )
        state = V2Run(toolbox=toolbox)
        run_state = RunState(handle=self.handler(state, organization_id, shadow=shadow), max_steps=MAX_STEPS)
        instruction, message = await self._prompt(ctx, user_text, organization_id, language)
        agent = LlmAgent(
            name=AGENT_NAME,
            model=self._model,
            instruction=lambda _ctx: instruction,  # a provider: no {placeholder} templating of the rule files
            tools=[SpecTool(spec, run_state) for spec in all_specs()],
            before_model_callback=run_state.before_model,
            generate_content_config=content_config(getattr(self._model, "model", "")),
        )
        runner = Runner(app_name=memory.APP_NAME, agent=agent, session_service=self._sessions)
        user_id, session_id = self._keys(gateway, ctx)
        texts: list[str] = []
        token = current_correlation_id.set(correlation_id)
        try:
            await self._session(user_id, session_id)

            async def _loop() -> None:
                async for event in runner.run_async(
                    user_id=user_id,
                    session_id=session_id,
                    new_message=types.Content(role="user", parts=[types.Part(text=message)]),
                    run_config=RunConfig(get_session_config=GetSessionConfig(num_recent_events=memory.RECENT_EVENTS)),
                ):
                    if event.error_code and not event.get_function_calls():
                        raise RuntimeError(f"model error {event.error_code}: {event.error_message}")
                    if event.author == AGENT_NAME and event.content and not event.get_function_calls():
                        texts.extend(p.text for p in event.content.parts or [] if p.text and not p.thought)

            await asyncio.wait_for(_loop(), timeout=TIMEOUT_SECONDS)
        except Exception as exc:  # noqa: BLE001 -- the caller decides: fall back, or degrade after a write
            state.error = exc
        finally:
            current_correlation_id.reset(token)
        state.run = ToolRunResult(
            text="\n".join(t.strip() for t in texts if t.strip()),
            calls=run_state.records,
            steps=max(0, run_state.model_calls - 1),
            stop_reason=run_state.stop_reason,
            model=getattr(self._model, "model", None),
        )
        await self.settle(state, user_text, shadow=shadow)
        return state

    async def remember(self, *, ctx: AgentContext, gateway: Any, v2: V2Run, sent: str) -> None:
        """After the reply went out: the lines the code drew under the model's words (the card,
        a stock answer, a note) are added to the conversation, so next turn the model knows
        exactly what they saw. Never raises: memory must not break a reply."""
        try:
            model_words = _words(v2.run.text if v2.run else "")
            shown = [ln for ln in (sent or "").splitlines() if ln.strip() and _words(ln) not in model_words]
            if not shown:
                return
            user_id, session_id = self._keys(gateway, ctx)
            session = await self._sessions.get_session(
                app_name=memory.APP_NAME, user_id=user_id, session_id=session_id,
                config=GetSessionConfig(num_recent_events=1),
            )
            if session is None:
                return
            last = session.events[-1] if session.events else None
            await self._sessions.append_event(
                session,
                Event(
                    author=AGENT_NAME,
                    invocation_id=getattr(last, "invocation_id", "") or "",
                    content=types.Content(role="model", parts=[types.Part(text=f"{SHOWN_PREFIX}\n" + "\n".join(shown))]),
                ),
            )
        except Exception:  # noqa: BLE001
            _log.warning("agent_v2.adk.remember_failed", exc_info=True)
