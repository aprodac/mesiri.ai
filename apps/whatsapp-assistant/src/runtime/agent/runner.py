"""The agent loop for one message: run the model with the tools, then turn
what happened into the ONE reply.

Failure policy (writes make a retry unsafe):
- the model/provider fails before any record was attempted -> "outage": the
  caller says it will process this in a few minutes and retries the message
  (the classic outage path, runtime/ai_outage.py);
- it fails after a record was attempted -> never retried; the sender gets what
  was saved and is told to check the rest;
- a deadline that passes mid-save lets the save finish first (the toolbox
  shields it), so the reply never forgets or repeats it.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from channel.replies import ReplySpec
from interactions.saved_summary import QUESTION_PREFIX, render_saved
from mesiri_ai.models import ChatMessage, ToolRunResult
from mesiri_ai.ports.tool_calling import ToolCallingProvider

from .gateway import WorkflowGateway
from .prompt import SYSTEM_PROMPT, AgentContext, build_messages
from .toolbox import AgentToolbox
from .tools import ScopeLookup, tool_specs

_log = logging.getLogger("mesiri.agent")

#: Per message: tool rounds, and the overall deadline (request [40]).
MAX_STEPS = 3
TIMEOUT_SECONDS = 25.0  # a 4-part note is ~2 model rounds + 4 saves; 12s cut it off (request [43])

UNDO_LINE = "Wrong? Reply UNDO."
CHECK_LINE = (
    "I couldn't finish the rest of your message, so please check what is saved and "
    "send anything missing again."
)
NOTHING_LINE = "Sorry, I couldn't work that out. Could you say it again in a few words?"


@dataclass(slots=True)
class AgentResult:
    #: "ok" | "outage" | "degraded"
    outcome: str
    reply: ReplySpec | None
    toolbox: AgentToolbox
    run: ToolRunResult | None = None
    error: BaseException | None = None

    @property
    def saved_count(self) -> int:
        return len(self.toolbox.saved)


class AgentRunner:
    def __init__(
        self,
        provider: ToolCallingProvider,
        *,
        max_steps: int = MAX_STEPS,
        timeout_seconds: float = TIMEOUT_SECONDS,
    ) -> None:
        self._provider = provider
        self._max_steps = max_steps
        self._timeout = timeout_seconds

    async def run(
        self,
        *,
        ctx: AgentContext,
        user_text: str,
        gateway: WorkflowGateway,
        scope: ScopeLookup,
        correlation_id: str | None = None,
        lap: Callable[[str], None] | None = None,
        after_tool: Callable[[], None] | None = None,
    ) -> AgentResult:
        toolbox = AgentToolbox(
            gateway=gateway, scope=scope, user_text=user_text, lap=lap, after_tool=after_tool
        )
        messages = [ChatMessage(role=r, text=t) for r, t in build_messages(ctx, user_text)]
        try:
            run = await self._provider.run_tools(
                SYSTEM_PROMPT,
                messages,
                tool_specs(),
                toolbox.handle,
                max_steps=self._max_steps,
                timeout_seconds=self._timeout,
                correlation_id=correlation_id,
            )
        except Exception as exc:  # noqa: BLE001 — every provider/model failure lands here
            await toolbox.settle()
            if toolbox.attempted_writes == 0 and toolbox.parked is None:
                _log.warning("agent.outage correlation_id=%s error=%r", correlation_id, exc)
                return AgentResult("outage", None, toolbox, error=exc)
            _log.exception("agent.degraded correlation_id=%s", correlation_id)
            return AgentResult(
                "degraded", self._fallback(toolbox, partial=True), toolbox, error=exc
            )
        await toolbox.settle()
        return AgentResult("ok", self._compose(run, toolbox), toolbox, run=run)

    # -- the one reply -----------------------------------------------------

    def _compose(self, run: ToolRunResult, toolbox: AgentToolbox) -> ReplySpec:
        text = saved_list(_unique_paragraphs((run.text or "").strip()))
        block = _saved_block(toolbox)
        if block:
            # The "Saved:" list is the system's, built from what was saved
            # (request 57, B3): the model's own list echoed the sender's raw
            # words ("6 mason, 10 helper vannu"). What it adds is the rest.
            rest = _without_echoed_questions(_without_saved_block(text), toolbox)
            if not rest and run.stop_reason == "max_steps":
                rest = CHECK_LINE
            text = f"{block}\n\n{rest}".strip() if rest else block
        if not text:
            return self._fallback(toolbox, partial=run.stop_reason == "max_steps")
        if toolbox.saved and "undo" not in text.casefold():
            text = f"{text}\n\n{UNDO_LINE}"
        parked = toolbox.parked
        if parked is None:
            return ReplySpec(text=text)
        if "?" not in text and "？" not in text:
            # The model left the question out: the buttons would hang in the air.
            text = f"{text}\n\n{parked.text}"
        return ReplySpec(
            text=text,
            list_button_label=parked.list_button_label,
            list_rows=parked.list_rows,
            buttons=parked.buttons,
        )

    def _fallback(self, toolbox: AgentToolbox, *, partial: bool) -> ReplySpec:
        """The reply when the model gave no usable text: the pipeline's own
        words for what it did."""
        block = _saved_block(toolbox)
        parts = [block] if block else [item.text for item in toolbox.saved]
        parts.extend(toolbox.answers)
        parked = toolbox.parked
        if parked is not None:
            parts.append(parked.text)
        elif not parts:
            parts.extend(toolbox.notes[:1] or [NOTHING_LINE])
        if partial and (toolbox.saved or toolbox.attempted_writes):
            parts.append(CHECK_LINE)
        text = _unique_paragraphs("\n\n".join(p for p in parts if p))
        if parked is None:
            return ReplySpec(text=text)
        return ReplySpec(
            text=text,
            list_button_label=parked.list_button_label,
            list_rows=parked.list_rows,
            buttons=parked.buttons,
        )


def _saved_block(toolbox: AgentToolbox) -> str:
    """The deterministic "Saved:" block, when every saved item has a summary
    (else the model's own wording stands, as before)."""
    if not toolbox.saved or not all(item.summary for item in toolbox.saved):
        return ""
    return render_saved([item.summary for item in toolbox.saved if item.summary])


def _normalized(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE).split()).casefold()


def _without_echoed_questions(text: str, toolbox: AgentToolbox) -> str:
    """A question saved for the engineer is in the "Saved:" list; the model
    repeating it back, or any other line that only plays back the sender's own
    words, adds nothing (request 57, B2/B3)."""
    asked = {
        _normalized(item.summary[len(QUESTION_PREFIX):])
        for item in toolbox.saved
        if item.summary and item.summary.startswith(QUESTION_PREFIX)
    }
    spoken = _normalized(toolbox.user_text)
    if not text:
        return text
    kept = []
    for line in text.split("\n"):
        norm = _normalized(line)
        # The sender's own words played back ("6 mason, 10 helper vannu") say
        # nothing the "Saved:" list does not, whatever else the line is.
        echo = len(norm.split()) >= 3 and norm in spoken
        if norm in asked or echo:
            continue
        kept.append(line)
    return "\n".join(kept).strip("\n").strip()


_SAVED_HEAD = re.compile(r"^\s*✅")
_BULLET = re.compile(r"^\s*[•\-\*]\s")


def _without_saved_block(text: str) -> str:
    """The model's text minus any "✅ Saved:" header (with an inline item) and
    the bullets under it, whatever language the model wrote it in."""
    kept: list[str] = []
    dropping = False
    for line in text.split("\n"):
        if _SAVED_HEAD.match(line):
            dropping = True
            continue
        if dropping and _BULLET.match(line):
            continue
        dropping = False
        kept.append(line)
    return "\n".join(kept).strip("\n").strip()


_SAVED_LINE = re.compile(r"^\s*(?:✅\s*)?(?:recorded|saved)\s*:?\s+(?P<what>\S.*)$", re.IGNORECASE)
_TODAY_END = re.compile(r"[\s,]+(?:for\s+|from\s+)?today\s*[.!]?\s*$", re.IGNORECASE)


def saved_list(text: str) -> str:
    """B-9: "Recorded 12 masons present today. / Recorded 5 bags ... today."
    as one header and short bullets, when the model wrote one such line per
    thing despite the prompt. Two or more such lines only; anything else
    (one line, another language) is left as written."""
    lines = text.split("\n")
    hits = [i for i, line in enumerate(lines) if _SAVED_LINE.match(line)]
    if len(hits) < 2:
        return text
    out: list[str] = []
    for i, line in enumerate(lines):
        match = _SAVED_LINE.match(line) if i in hits else None
        if match is None:
            out.append(line)
            continue
        if i == hits[0]:
            out.append("✅ Saved:")
        what = _TODAY_END.sub("", match.group("what")).rstrip(" .")
        out.append(f"• {what[:1].upper()}{what[1:]}")
    return "\n".join(out)


def _unique_paragraphs(text: str) -> str:
    """The same paragraph twice in one reply (a note the model quoted and the
    pipeline's own words) is said once."""
    seen: set[str] = set()
    kept: list[str] = []
    for part in text.split("\n\n"):
        key = " ".join(part.split()).casefold()
        if key and key in seen:
            continue
        seen.add(key)
        kept.append(part)
    return "\n\n".join(kept)


def default_now() -> datetime:
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("Asia/Kolkata"))
