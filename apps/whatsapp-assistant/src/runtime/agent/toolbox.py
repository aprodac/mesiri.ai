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
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from channel.replies import ListRow, ReplySpec
from mesiri_ai.models import ToolOutcome
from runtime.save_first import DRAFT_NOTE

from .gateway import StepResult, WorkflowGateway
from .tools import (
    ASK_USER,
    NOTE_FOR_ENGINEER,
    REQUEST_DPR,
    SET_UNIT_CONVERSION,
    SET_WORK_SITE,
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


_RECORDED = re.compile(
    r"^\W*(?:recorded\.?(?:\s+thank you\.?)?|saved\s*:.*)\s*$", re.IGNORECASE | re.DOTALL
)


def _without_recorded(text: str) -> str:
    """A saved step's words without the bare "Recorded. Thank you." line or
    the "confirm it with tonight's report" draft note -- the reply's Save
    button says how it is kept (WA-35); what is left (a stock warning, a late
    entry) is worth the model knowing."""
    text = (text or "").replace(DRAFT_NOTE, "")
    kept = [p.strip() for p in text.split("\n\n") if p.strip() and not _RECORDED.match(p.strip())]
    return "\n\n".join(kept)


#: The sender asking for their engineer, in the languages the sites write in.
_ENGINEER = re.compile(r"engin|\bengg?\b|എഞ്ചിനീ|എൻജിനീ|ഇഞ്ചിനീ|इंजीनियर|इंजिनियर", re.IGNORECASE)


def asks_for_engineer(text: str) -> bool:
    """Whether the message mentions their engineer ("engineer-inodu chodikku",
    "ask the engineer"): the only case a question is passed on."""
    return bool(_ENGINEER.search(text or ""))


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
    #: What was saved in a few words, from the saved data; the reply's
    #: "Saved:" list is built from these, never from the user's own words.
    summary: str | None = None


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
    #: The parked question is a record waiting on Yes/No (confirm-first): its
    #: details are always shown with the buttons, whatever the model wrote.
    parked_confirm: bool = False
    #: Tool calls not run because a gate was waiting (named for the reply).
    held: list[str] = field(default_factory=list)
    attempted_writes: int = 0
    calls: int = 0
    #: B-7: the journey's lap stopwatch; time before a tool call is the
    #: model's ("agent_model"), time in it is the tool's ("agent_tools").
    lap: Callable[[str], None] | None = None
    #: B-7: called after every tool call, so the receipt card can be made
    #: while the model writes the reply.
    after_tool: Callable[[], None] | None = None
    failed: int = 0
    #: Request 83: what request_dpr answered, for the one "draft so far" line a
    #: message that also saves entries gets under its card.
    report_text: str | None = None
    #: The last reply offered to ask their engineer, so a bare "yes" asks it.
    engineer_offered: bool = False
    _seen: set[str] = field(default_factory=set)
    _inflight: set[asyncio.Task[Any]] = field(default_factory=set)

    async def handle(self, name: str, args: dict[str, Any]) -> ToolOutcome:
        """The provider's tool handler. Shielded: if the run's deadline cancels
        the model loop while a save is in flight, the save still finishes and
        is recorded here, so the reply never forgets (or repeats) it."""
        if self.lap is not None:
            self.lap("agent_model")
        task = asyncio.ensure_future(self._dispatch(name, args))
        self._inflight.add(task)
        task.add_done_callback(self._inflight.discard)
        try:
            return await asyncio.shield(task)
        finally:
            if self.lap is not None:
                self.lap("agent_tools")
            if self.after_tool is not None:
                try:
                    self.after_tool()
                except Exception:  # noqa: BLE001 -- a speed-up, never a failure
                    _log.warning("agent.after_tool_failed", exc_info=True)

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
        if name == SET_WORK_SITE:
            return await self._set_work_site(args)
        if name == NOTE_FOR_ENGINEER and not (self.engineer_offered or asks_for_engineer(self.user_text)):
            # Ilan, 21 Oct: a question goes to the engineer ONLY when the
            # sender asks for that. The live model passed "is there enough
            # cement for tomorrow's slab?" on instead of answering it.
            return ToolOutcome(
                content={
                    "status": "not_asked_to_pass_on",
                    "instruction": (
                        "They did not ask you to ask their engineer, so answer it yourself: "
                        "use the facts you were given or the query tools (query_materials for "
                        "stock). If the records cannot answer it, say so plainly in one line "
                        "and offer to ask their engineer."
                    ),
                }
            )
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
            self.failed += 1
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

    async def _set_work_site(self, args: dict[str, Any]) -> ToolOutcome:
        """WA-45: "now at Site B". One of their sites -> today's site; anything
        else -> their sites as the one question (never a guess)."""
        project = str(args.get("project") or "").strip()
        project_id = self.scope.project_id(project) if project else None
        site_id = self.scope.site_id(str(args.get("site") or ""), project_id)
        if site_id is None:
            names = [name for _sid, name, pid in self.scope.sites if project_id in (None, pid)]
            if self.parked is None and names:
                self.parked = question_reply("Which site are you at?", names)
                self.parked_by = "ask"
            return ToolOutcome(
                content={
                    "status": "choose",
                    "message": "That is not one of their sites.",
                    "instruction": (
                        "Nothing was changed. End your message asking which of their sites they are "
                        "at (the options are shown as buttons). If it is a new site, they can ask you "
                        "to create it."
                    ),
                }
            )
        try:
            label = await self.gateway.set_work_site(project_id=project_id, site_id=site_id)
        except Exception:  # noqa: BLE001 -- the model is told; the trace keeps the cause
            _log.exception("agent.set_work_site_failed")
            self.failed += 1
            return ToolOutcome(content={"status": "error", "message": "could not switch the site"})
        return ToolOutcome(
            content={
                "status": "work_site_set",
                "site": label,
                "instruction": (
                    f"Say in one short line that you will use {label} for the rest of today. "
                    "Nothing needs saving for this."
                ),
            }
        )

    async def _run(self, name: str, args: dict[str, Any]) -> StepResult:
        if name == UNDO_LAST and str(args.get("what") or "latest_update") == "latest_update":
            return await self.gateway.undo_latest_draft()
        if name == SET_UNIT_CONVERSION:
            return await self.gateway.set_unit_conversion(
                material=str(args.get("material") or ""),
                unit=str(args.get("unit") or ""),
                count=args.get("count"),
            )
        candidate = to_candidate(name, args, self.scope)
        if candidate is None:
            return StepResult(status="error", text=f"unknown tool {name}")
        return await self.gateway.run(candidate, text=self.user_text)

    def _outcome(self, name: str, step: StepResult) -> ToolOutcome:
        if step.status == "saved" and name == NOTE_FOR_ENGINEER:
            # Passed on, not an entry: nothing for the sender to check or save.
            self.saved.append(SavedItem(name, step.text, step.summary))
            return ToolOutcome(
                content={
                    "status": "passed_to_engineer",
                    "instruction": (
                        "Say in one short line that you passed it to their engineer. Do not "
                        "repeat the question and do not ask them to tap Save for it."
                    ),
                }
            )
        if step.status == "saved":
            self.saved.append(SavedItem(name, step.text, step.summary))
            content: dict[str, Any] = {"status": "saved"}
            if step.summary:
                content["saved_as"] = step.summary
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
                self.parked_confirm = step.status == "needs_confirmation"
            return ToolOutcome(
                content={
                    "status": "waiting_for_user",
                    "question": question.text,
                    "instruction": "Your final message must end with this question.",
                }
            )
        if step.status == "choose" and step.reply is not None:
            # ARCH-04: the sender must pick (material, project, site, add it?).
            # The options go out as buttons whatever the model writes; its
            # own ask_user, if it also calls one, is the one question.
            if self.parked is None:
                self.parked = step.reply
                self.parked_by = "ask"
            return ToolOutcome(
                content={
                    "status": "choose",
                    "message": step.text,
                    "instruction": (
                        "Nothing was saved. End your message with this question; its options are "
                        f"shown as buttons: {step.reply.text}"
                    ),
                }
            )
        if step.status == "answer" and name == REQUEST_DPR:
            self.report_text = step.text
            self.answers.append(step.text)
            return ToolOutcome(
                content={
                    "status": "answer",
                    "text": step.text,
                    "instruction": (
                        "If this same message also saves entries, the system adds one 'Today's draft so "
                        "far' line under them: do not describe this report, do not list any items, and "
                        "do not ask for details that are already in the entries."
                    ),
                }
            )
        if step.status == "answer":
            self.answers.append(step.text)
            return ToolOutcome(content={"status": "answer", "text": step.text})
        if step.status == "error":
            self.failed += 1
        if step.text and step.text not in self.notes:
            self.notes.append(step.text)
        return ToolOutcome(content={"status": step.status, "message": step.text})
