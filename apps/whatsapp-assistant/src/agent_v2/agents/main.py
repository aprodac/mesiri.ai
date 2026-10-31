"""The v2 main agent (request 174).

One model run per message: it is given the sender's context (their sites, today's saved
records, the open card, the last turns) plus the material catalog, the materials SKILL.md
as its rules, and the skill's tools. It either takes the message (draft lines, a question,
a stock answer) or hands it back untouched, and the caller then runs today's agent in the
same turn. It never writes: the draft tools add lines to the card, the Save tap writes.

The framework is the existing ``ToolCallingProvider`` (google-genai function calling), see
docs/agents/ADR-v2-agent-framework.md.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mesiri_ai.models import ChatMessage, ToolOutcome, ToolRunResult
from runtime.agent.prompt import MESIRI_VOICE, AgentContext, build_messages
from runtime.agent.toolbox import AgentToolbox
from runtime.agent.tools import ScopeLookup

from ..skills.materials import tools as skill

_log = logging.getLogger("mesiri.agent_v2")

SKILL_PATH = Path(__file__).resolve().parent.parent / "skills" / "materials" / "SKILL.md"

#: v2 gets less time than today's agent, so a fallback (v2 first, then today's agent) stays
#: inside one reply's budget. A 3-line message is one model round plus its saves.
MAX_STEPS = 3
TIMEOUT_SECONDS = 9.0
#: How many catalog materials go into the prompt (the rest are reachable by catalog_match).
CATALOG_IN_PROMPT = 60


def system_prompt() -> str:
    return f"{SKILL_PATH.read_text(encoding='utf-8')}\n{MESIRI_VOICE}"


@dataclass(slots=True)
class V2Run:
    """What one v2 run did."""

    toolbox: AgentToolbox
    run: ToolRunResult | None = None
    #: The model's reason for handing the message back, when it did.
    handed_back: str | None = None
    error: BaseException | None = None
    #: ``(v2 tool name, arguments)`` in call order.
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    @property
    def took_message(self) -> bool:
        """v2 did something with the message: a line, a question, a stock answer. Then it
        is v2's alone; today's agent never runs for it (a message is never handled twice)."""
        if self.toolbox.attempted_writes or self.toolbox.parked is not None:
            return True
        return any(name in skill.TAKES_THE_MESSAGE for name, _ in self.calls)

    @property
    def asked(self) -> str:
        return " ".join(str(a.get("question") or "") for n, a in self.calls if n == skill.ASK)


class MainAgent:
    def __init__(self, provider: Any, *, catalog: Any | None = None) -> None:
        self._provider = provider
        self._catalog = catalog

    async def catalog_line(self, organization_id: str | None) -> str | None:
        if self._catalog is None or not organization_id:
            return None
        try:
            rows = await self._catalog.list_active_materials(organization_id=organization_id)
        except Exception:  # noqa: BLE001 -- the catalog line is context; catalog_match still works
            _log.warning("agent_v2.catalog_unreadable", exc_info=True)
            return None
        names = [str(r["name"]) for r in rows[:CATALOG_IN_PROMPT] if r.get("name")]
        return ("Material catalog: " + "; ".join(names) + ".") if names else "Material catalog: (empty)."

    async def match(self, organization_id: str | None, word: str) -> dict[str, Any]:
        """catalog_match: the materials this word means, by name, alias, then closeness."""
        if self._catalog is None or not organization_id:
            return {"status": "unavailable", "materials": []}
        word = (word or "").strip()
        if not word:
            return {"status": "no_word", "materials": []}
        try:
            found = await self._catalog.find_materials(organization_id=organization_id, name=word)
            if not found and hasattr(self._catalog, "find_by_alias"):
                aliased = await self._catalog.find_by_alias(organization_id=organization_id, alias=word)
                found = [aliased] if aliased else []
        except Exception:  # noqa: BLE001 -- told to the model, which then asks
            _log.warning("agent_v2.catalog_match_failed", exc_info=True)
            return {"status": "error", "materials": []}
        names = [str(r["name"]) for r in found if r.get("name")]
        status = "none" if not names else "one" if len(names) == 1 else "several"
        return {"status": status, "materials": names}

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

        async def handle(name: str, args: dict[str, Any]) -> ToolOutcome:
            state.calls.append((name, dict(args)))
            if name == skill.HAND_BACK:
                if state.took_message:
                    return ToolOutcome(content={"status": "refused", "why": "you already took this message"})
                state.handed_back = str(args.get("reason") or "not materials")
                return ToolOutcome(content={"status": "ok"}, stop=True)
            if name == skill.CATALOG_MATCH:
                return ToolOutcome(content=await self.match(organization_id, str(args.get("word") or "")))
            if shadow and name in skill.TAKES_THE_MESSAGE:
                # Shadow: the proposed call is recorded (state.calls); nothing is drafted,
                # asked or read. A draft ends the run; the rest of the message follows.
                if name == skill.ASK:
                    return ToolOutcome(content={"status": "shadow"}, stop=True)
                return ToolOutcome(content={"status": "drafted"}, done=True)
            classic_name = skill.CLASSIC_NAME.get(name)
            if classic_name is None:
                return ToolOutcome(content={"status": "unknown_tool", "name": name})
            return await toolbox.handle(classic_name, args)

        messages = [ChatMessage(role=r, text=t) for r, t in build_messages(ctx, user_text)]
        if (line := await self.catalog_line(organization_id)) and messages:
            messages[0] = ChatMessage(role=messages[0].role, text=f"{messages[0].text}\n{line}")
        try:
            state.run = await self._provider.run_tools(
                system_prompt(),
                messages,
                skill.specs(),
                handle,
                max_steps=MAX_STEPS,
                timeout_seconds=TIMEOUT_SECONDS,
                correlation_id=correlation_id,
            )
        except Exception as exc:  # noqa: BLE001 -- the caller decides: fall back, or degrade after a write
            state.error = exc
        await toolbox.settle()
        return state
