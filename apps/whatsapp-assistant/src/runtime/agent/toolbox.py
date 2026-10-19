"""Runs the model's tool calls and remembers what happened.

One `AgentToolbox` lives for one inbound message. It turns each call into a
`StepResult` through the `WorkflowGateway`, answers the model with a short
result, and keeps what the reply needs: what was saved, which answer a query
gave, and the one question (if any) the conversation is now parked on.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from channel.replies import ListRow, ReplySpec
from mesiri_ai.models import ToolOutcome

from .gateway import StepResult, WorkflowGateway
from .tools import (
    ASK_USER,
    UNDO_LAST,
    WRITE_TOOLS,
    ScopeLookup,
    to_candidate,
)

_log = logging.getLogger("mesiri.agent")

#: Most tool calls one message may make in total (steps are bounded separately
#: by the provider loop). A note with many parts is still a handful of calls.
MAX_CALLS = 8

#: WhatsApp reply buttons: three at most. More options go in a list.
MAX_BUTTONS = 3
MAX_LIST_ROWS = 10
_TITLE_MAX = 24  # WhatsApp button/row title limit


_RECORDED = re.compile(r"^\W*recorded\.?(\s+thank you\.?)?\s*$", re.IGNORECASE)


def _without_recorded(text: str) -> str:
    """A saved step's words without the bare "Recorded. Thank you." line:
    what is left (the draft note, a stock warning) is worth the model knowing."""
    kept = [p for p in (text or "").split("\n\n") if p.strip() and not _RECORDED.match(p.strip())]
    return "\n\n".join(kept)


def _title(option: str) -> str:
    option = " ".join(str(option).split())
    return option if len(option) <= _TITLE_MAX else option[: _TITLE_MAX - 1] + "…"


def question_reply(question: str, options: list[str]) -> ReplySpec:
    """The one question as a message: buttons for up to three options, a list
    for up to ten, plain text otherwise."""
    options = [o for o in (str(o).strip() for o in options) if o][:MAX_LIST_ROWS]
    rows = tuple(ListRow(f"agent_opt_{i}", _title(o)) for i, o in enumerate(options, 1))
    if 0 < len(rows) <= MAX_BUTTONS:
        return ReplySpec(text=question, buttons=rows)
    if rows:
        return ReplySpec(text=question, list_button_label="Choose one", list_rows=rows)
    return ReplySpec(text=question)


@dataclass(slots=True)
class SavedItem:
    tool: str
    text: str


@dataclass(slots=True)
class AgentToolbox:
    gateway: WorkflowGateway
    scope: ScopeLookup
    user_text: str
    saved: list[SavedItem] = field(default_factory=list)
    answers: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    #: The one question the conversation is parked on, if any.
    parked: ReplySpec | None = None
    #: "gate": the pipeline itself needs an answer or a Yes/No before it can go
    #: on, so no further record may be filed this turn (it keeps ONE waiting
    #: state per sender). "ask": the model's own question -- the message's other
    #: parts are independent and still get saved.
    parked_by: str | None = None
    #: Tool calls not run because a gate was waiting (named for the reply).
    held: list[str] = field(default_factory=list)
    attempted_writes: int = 0
    calls: int = 0
    _seen: set[str] = field(default_factory=set)
    _inflight: set[asyncio.Task[Any]] = field(default_factory=set)

    async def handle(self, name: str, args: dict[str, Any]) -> ToolOutcome:
        """The provider's tool handler. Shielded: if the run's deadline cancels
        the model loop while a save is in flight, the save still finishes and
        is recorded here, so the reply never forgets (or repeats) it."""
        task = asyncio.ensure_future(self._dispatch(name, args))
        self._inflight.add(task)
        task.add_done_callback(self._inflight.discard)
        return await asyncio.shield(task)

    async def settle(self, timeout: float = 5.0) -> None:
        """Wait for tool calls still running after the model loop was cut off."""
        if self._inflight:
            await asyncio.wait(list(self._inflight), timeout=timeout)

    async def _dispatch(self, name: str, args: dict[str, Any]) -> ToolOutcome:
        if self.parked_by == "gate":
            self.held.append(name)
            return ToolOutcome(
                content={
                    "status": "held",
                    "reason": (
                        "waiting for the user's answer to another question first; "
                        "tell them this part still needs doing afterwards"
                    ),
                }
            )
        self.calls += 1
        if self.calls > MAX_CALLS:
            return ToolOutcome(
                content={"status": "skipped", "reason": "too many actions in one message"}
            )
        if name == ASK_USER:
            return self._ask(args)
        signature = f"{name}:{json.dumps(args, sort_keys=True, default=str)}"
        if signature in self._seen and name in WRITE_TOOLS:
            return ToolOutcome(
                content={"status": "duplicate_ignored", "reason": "already done in this message"}
            )
        self._seen.add(signature)
        if name in WRITE_TOOLS:
            self.attempted_writes += 1
        try:
            step = await self._run(name, args)
        except Exception:  # noqa: BLE001 — the model is told; the trace keeps the cause
            _log.exception("agent.tool_failed tool=%s", name)
            return ToolOutcome(content={"status": "error", "message": "that action failed"})
        return self._outcome(name, step)

    def _ask(self, args: dict[str, Any]) -> ToolOutcome:
        question = str(args.get("question") or "").strip()
        if not question:
            return ToolOutcome(content={"status": "error", "message": "no question given"})
        if self.parked is not None:
            return ToolOutcome(
                content={"status": "skipped", "reason": "one question per message"}
            )
        options = args.get("options") or []
        self.parked = question_reply(question, options if isinstance(options, list) else [])
        self.parked_by = "ask"
        return ToolOutcome(
            content={
                "status": "question_sent",
                "instruction": "Your final message must end with this question.",
            }
        )

    async def _run(self, name: str, args: dict[str, Any]) -> StepResult:
        if name == UNDO_LAST and str(args.get("what") or "latest_update") == "latest_update":
            return await self.gateway.undo_latest_draft()
        candidate = to_candidate(name, args, self.scope)
        if candidate is None:
            return StepResult(status="error", text=f"unknown tool {name}")
        return await self.gateway.run(candidate, text=self.user_text)

    def _outcome(self, name: str, step: StepResult) -> ToolOutcome:
        if step.status == "saved":
            self.saved.append(SavedItem(name, step.text))
            content: dict[str, Any] = {"status": "saved"}
            # B-9: not the pipeline's "✅ Recorded. Thank you." -- the model
            # copied it onto every line ("Recorded 12 masons present today.")
            # or sent it alone, without saying what was saved.
            note = _without_recorded(step.text)
            if note:
                content["note"] = note
            return ToolOutcome(content=content)
        if step.status in ("needs_confirmation", "needs_answer"):
            question = step.reply or ReplySpec(text=step.text)
            if self.parked is None or self.parked_by == "ask":
                # The pipeline's own question replaces the model's: its answer
                # is what the stored waiting state expects.
                self.parked = question
                self.parked_by = "gate"
            return ToolOutcome(
                content={
                    "status": "waiting_for_user",
                    "question": question.text,
                    "instruction": "Your final message must end with this question.",
                }
            )
        if step.status == "answer":
            self.answers.append(step.text)
            return ToolOutcome(content={"status": "answer", "text": step.text})
        if step.text:
            self.notes.append(step.text)
        return ToolOutcome(content={"status": step.status, "message": step.text})
