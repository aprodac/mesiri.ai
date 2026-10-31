"""The v2 main agent (request 174).

One model run per message (request 180): it is given the sender's context (their sites,
today's saved records, the open card, the last turns incl. Mesiri's own replies), the material
catalog, the rule files (skills/general + skills/materials) and the tools: the materials
tools, the existing record tools and the read tools. It decides, calls what the message needs
and writes its own reply. It never writes a record: the draft tools add lines to the card, the
Save tap writes.

The framework is the existing ``ToolCallingProvider`` (google-genai function calling), see
docs/agents/ADR-v2-agent-framework.md.
"""

from __future__ import annotations

import inspect
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mesiri_ai.models import ChatMessage, ToolOutcome, ToolRunResult
from runtime.agent import tools as classic
from runtime.agent.entry_base import ALL_SITES
from runtime.agent.prompt import MESIRI_VOICE, AgentContext, build_messages
from runtime.agent.toolbox import AgentToolbox
from runtime.agent.tools import ScopeLookup
from runtime.agent.wording import say

from ..skills.materials import tools as skill

_log = logging.getLogger("mesiri.agent_v2")

SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"
SKILL_PATH = SKILLS_DIR / "materials" / "SKILL.md"
GENERAL_SKILL_PATH = SKILLS_DIR / "general" / "SKILL.md"
#: Plain-English rule files, in the order the model reads them.
SKILL_FILES = (GENERAL_SKILL_PATH, SKILL_PATH)

#: Request 180: the EXISTING toolbox tools v2 gets for the other record kinds, unchanged (same
#: specs, same draft card, same Save tap), and the read tools. Anything not listed (creating
#: sites, members, join codes, settings) stays with the classic agent. Labour is included by the
#: owner's decision on plan 180; its data paths and rules are not touched.
GENERAL_WRITE_TOOLS = frozenset({
    classic.SAVE_LABOUR, classic.SAVE_WORK_DONE, classic.SAVE_EXPENSE, classic.REPORT_ISSUE,
    classic.UPDATE_ISSUE, classic.CORRECT_WORK_QUANTITY, classic.NOTE_FOR_ENGINEER,
    classic.SET_SITE_CONDITIONS, classic.REQUEST_DPR, classic.SET_WORK_SITE,
})
GENERAL_READ_TOOLS = frozenset({
    classic.QUERY_LABOUR, classic.QUERY_WORK_LOG, classic.QUERY_PROJECT, classic.QUERY_EXPENSES,
    classic.QUERY_OPEN_NEEDS, classic.MY_SCOPE,
})
GENERAL_TOOLS = GENERAL_WRITE_TOOLS | GENERAL_READ_TOOLS


def general_specs() -> list[Any]:
    """Today's specs of the tools above, in today's order."""
    return [spec for spec in classic.tool_specs() if spec.name in GENERAL_TOOLS]


def all_specs() -> list[Any]:
    return [*skill.specs(), *general_specs()]

#: Request 178: the budget of a v2 run. A message v2 takes is never run by today's agent too, so
#: more room here does not double the time; only a hand-back (one quick round) or a failure
#: before any action falls back to today's agent (25 s). 6 rounds fit a 4-line message plus a
#: lookup or a correction.
MAX_STEPS = 6
TIMEOUT_SECONDS = 20.0
#: The v2 brain is the control panel's "agent_v2" route (Providers page); with none set the
#: provider uses the "agent" route, as today's agent does. Measure with the live eval
#: (tests/agent_v2/test_evals.py, ``GEMINI_MODEL=...``) and record the numbers in the ADR.
CAPABILITY = "agent_v2"
#: A company's catalog is a few dozen materials; this is a ceiling, not a cut (request 178:
#: the old first-names line left out the names and aliases a message actually used).
CATALOG_IN_PROMPT = 400


def system_prompt() -> str:
    rules = "\n\n".join(path.read_text(encoding="utf-8").strip() for path in SKILL_FILES)
    return f"{rules}\n\n{MESIRI_VOICE}"


@dataclass(slots=True)
class V2Run:
    """What one v2 run did."""

    toolbox: AgentToolbox
    run: ToolRunResult | None = None
    #: Kept for the shadow report's older rows; v2 no longer hands a message back.
    handed_back: str | None = None
    #: Set when they asked for material to be sent or ordered (a request: not built yet).
    request_not_built: bool = False
    error: BaseException | None = None
    #: ``(v2 tool name, arguments)`` in call order.
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    @property
    def took_message(self) -> bool:
        """v2 did something with the message: any tool call, a line, a question. Then it is
        v2's alone; today's agent never runs for it (a message is never handled twice)."""
        if self.toolbox.attempted_writes or self.toolbox.parked is not None:
            return True
        return self.request_not_built or bool(self.calls)

    @property
    def answered(self) -> bool:
        """v2 produced its own reply text (a chat answer, an honest 'no data')."""
        return bool(self.run is not None and (self.run.text or "").strip())

    @property
    def asked(self) -> str:
        return " ".join(str(a.get("question") or "") for n, a in self.calls if n == skill.ASK)


def v2_card_words(text: str) -> str:
    """The context's open-card paragraph names today's tools; v2's are ``change_line`` and
    ``remove_line`` (one place writes that paragraph: runtime/agent/draft.py)."""
    return (
        text.replace("update_pending_card", "change_line")
        .replace("undo_last cancels the whole card.", "remove_line takes one line off the open card.")
        .replace("undo_last removes the saved card.", "")
    )


def _words(name: str) -> frozenset[str]:
    return frozenset(re.findall(r"[a-z0-9]+", str(name).casefold()))


def likely_duplicates(names: list[str]) -> list[tuple[str, str]]:
    """Catalog names where one is wholly inside the other ("Steel" / "TMT Steel Bars") or that
    read the same: a word that fits both is ambiguous, and the owner may want them merged.
    Only listed, never merged here."""
    found = []
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            wa, wb = _words(a), _words(b)
            if wa and wb and (wa < wb or wb < wa or wa == wb):
                found.append((a, b))
    return found


def catalog_text(rows: list[dict[str, Any]]) -> str:
    """The catalog line of the prompt: every name, its aliases, and the overlapping names."""
    entries = []
    names = []
    for row in rows:
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        names.append(name)
        aliases = [str(a) for a in row.get("aliases") or [] if str(a).strip()]
        entries.append(f"{name} (also called: {', '.join(aliases)})" if aliases else name)
    if not entries:
        return "Material catalog: (empty)."
    text = "Material catalog (name, then what the company also calls it): " + "; ".join(entries) + "."
    overlaps = likely_duplicates(names)
    if overlaps:
        text += (
            " These catalog names overlap, so a word that fits both is a question, not a guess: "
            + "; ".join(f"{a} / {b}" for a, b in overlaps)
            + "."
        )
    return text


class MainAgent:
    def __init__(self, provider: Any, *, catalog: Any | None = None) -> None:
        self._provider = provider
        self._catalog = catalog

    async def catalog_line(self, organization_id: str | None) -> str | None:
        """ALL active materials, each with the words the company uses for it (request 178)."""
        if self._catalog is None or not organization_id:
            return None
        try:
            if hasattr(self._catalog, "catalog_with_aliases"):
                rows = await self._catalog.catalog_with_aliases(organization_id=organization_id)
            else:
                rows = await self._catalog.list_active_materials(organization_id=organization_id)
        except Exception:  # noqa: BLE001 -- the catalog line is context; catalog_match still works
            _log.warning("agent_v2.catalog_unreadable", exc_info=True)
            return None
        return catalog_text(rows[:CATALOG_IN_PROMPT])

    def _route_kwargs(self) -> dict[str, Any]:
        """The control-panel route of v2, for a provider that routes by capability (the resolver);
        a plain provider (a fake, a bare Gemini provider in the live eval) has one model."""
        try:
            takes = "capability" in inspect.signature(self._provider.run_tools).parameters
        except (TypeError, ValueError):
            takes = False
        return {"capability": CAPABILITY} if takes else {}

    @staticmethod
    def _name_the_site(toolbox: AgentToolbox, outcome: ToolOutcome) -> None:
        """Request 178: a stock answer says which site it is for, or that it covers all of them.
        The site is what ``JourneyGateway._reading_site`` decided; the line is the code's."""
        scope = getattr(toolbox.gateway, "read_scope", None)
        if not scope:
            return
        label = say("read.all_sites", toolbox.language) if scope == ALL_SITES else scope
        answer = toolbox.answers[-1]
        if answer.startswith("📍"):
            return
        named = f"📍 {label}\n{answer}"
        toolbox.answers[-1] = named
        if isinstance(outcome.content, dict) and "text" in outcome.content:
            outcome.content["text"] = named

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

        async def handle(name: str, raw_args: dict[str, Any]) -> ToolOutcome:
            state.calls.append((name, dict(raw_args)))  # with the account: the runner reads it
            args, _account = skill.split_account(raw_args)
            if name == skill.CATALOG_MATCH:
                return ToolOutcome(content=await self.match(organization_id, str(args.get("word") or "")))
            if name == skill.REQUEST_NOT_BUILT:
                state.request_not_built = True
                return ToolOutcome(
                    content={"status": "ok", "instruction": "Say nothing more about it: the system tells them."},
                    stop=not (toolbox.attempted_writes or toolbox.parked is not None),
                )
            if shadow and name in skill.TAKES_THE_MESSAGE:
                # Shadow: the proposed call is recorded (state.calls); nothing is drafted,
                # asked or read. A draft ends the run; the rest of the message follows.
                if name == skill.ASK:
                    return ToolOutcome(content={"status": "shadow"}, stop=True)
                return ToolOutcome(content={"status": "drafted"}, done=True)
            if name in GENERAL_TOOLS:
                if shadow and name in GENERAL_WRITE_TOOLS:
                    return ToolOutcome(content={"status": "drafted"})  # recorded in state.calls only
                return await toolbox.handle(name, args)
            classic_name = skill.CLASSIC_NAME.get(name)
            if classic_name is None:
                return ToolOutcome(content={"status": "unknown_tool", "name": name})
            if name == skill.CHANGE_LINE:
                args = {**args, "card_id": str(args.get("card_id") or "")}  # "" = the open card
            answered = len(toolbox.answers)
            outcome = await toolbox.handle(classic_name, args)
            if name == skill.STOCK_FOR and len(toolbox.answers) > answered:
                self._name_the_site(toolbox, outcome)
            return outcome

        messages = [ChatMessage(role=r, text=v2_card_words(t)) for r, t in build_messages(ctx, user_text)]
        if (line := await self.catalog_line(organization_id)) and messages:
            messages[0] = ChatMessage(role=messages[0].role, text=f"{messages[0].text}\n{line}")
        try:
            state.run = await self._provider.run_tools(
                system_prompt(),
                messages,
                all_specs(),
                handle,
                max_steps=MAX_STEPS,
                timeout_seconds=TIMEOUT_SECONDS,
                correlation_id=correlation_id,
                **self._route_kwargs(),
            )
        except Exception as exc:  # noqa: BLE001 -- the caller decides: fall back, or degrade after a write
            state.error = exc
        await toolbox.settle()
        return state
