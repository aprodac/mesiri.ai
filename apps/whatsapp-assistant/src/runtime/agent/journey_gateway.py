"""The real `WorkflowGateway`: hands a tool's arguments to its direct entry
(material, site, labour, query), starts the workflow and saves like a "YES"
would (ARCH-06: there is no classic route behind it).

Built per message by `runtime.message_journey`, which owns every dependency the
journey needs; this class only holds the few callables the agent uses, so it
is testable without the whole container.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from channel.replies import (
    ListRow,
    ReplySpec,
    is_module_disabled_reply,
)
from interactions.saved_summary import summarise_draft
from mesiri_contracts.application.results.execution_result import ExecutionStatus
from mesiri_contracts.assistant.candidates import Candidate
from mesiri_contracts.assistant.enums import InputModality, SemanticType
from mesiri_contracts.assistant.normalized_message import NormalizedMessage
from workflows import WorkflowRunStatus

from .cards import LEGACY, OPEN, Card, CardItem, removed_line
from .gateway import StepResult

_log = logging.getLogger("mesiri.agent")

#: What only reads: its run ends with an answer, not a record.
_LOOKUPS = frozenset(
    {
        SemanticType.ACTIVITY_QUERY,
        SemanticType.DPR_REQUEST,
        SemanticType.FINANCE_QUERY,
        SemanticType.INVENTORY_QUERY,
        SemanticType.LABOUR_QUERY,
        SemanticType.PROJECT_DETAIL_QUERY,
    }
)


#: A WhatsApp list row: title 24, description 72; ids 200 (so "all of them" is
#: offered for up to five entries only).
_ROW_TITLE = 24
_ROW_DESC = 72
_ALL_MAX = 5


def undo_pick_list(card: Card) -> ReplySpec:
    """The one question when "undo that" meets a card of several entries: a
    list of them, each row removing exactly that entry ([46]). The row ids are
    made by the code from the card, so a tap can only name its entries."""
    from .save_button import UNDO, tap_id

    def cut(text: str, limit: int) -> str:
        text = " ".join(text.split())
        return text if len(text) <= limit else text[: limit - 1] + "…"

    rows = [
        ListRow(tap_id(UNDO, [i.fact]), cut(i.summary, _ROW_TITLE), cut(f"{i.summary} ({i.day})", _ROW_DESC))
        for i in card.items
    ]
    if len(card.items) <= _ALL_MAX:
        rows.append(ListRow(tap_id(UNDO, [i.fact for i in card.items]), "All of them", ""))
    return ReplySpec(text="Which one should I remove?", list_button_label="Choose one", list_rows=tuple(rows[:10]))


def undo_step(gone: list[CardItem], undone: Any) -> StepResult:
    """What an undo did, as a step: the removed entries by name, and why any
    was refused."""
    refused = list(getattr(undone, "refused", []) or [])
    if gone:
        text = removed_line(gone)
        if refused:
            text += f"\nCouldn't remove {len(refused)} more: {refused[0]}."
        return StepResult("undone", text=text)
    if refused:
        return StepResult("error", text=f"Couldn't remove it: {refused[0]}.")
    return StepResult("info", text="That is already removed. Nothing more to undo.")


NOTHING_TO_UNDO = "Nothing to undo from your last card."


async def undo_from_card(
    cards: Any, actor: Any, undo_facts: Any, refs: list[str], actions: Any | None = None
) -> StepResult:
    """Request 88/90: remove entries of the sender's latest card, and nothing
    else. The ids come from the card the code recorded; with no card (none
    made, expired, or a reply that had no Save card) there is nothing to undo
    -- it never falls back to "the latest record of any type" (22/23 Oct: the
    3 masons stayed and an unrelated issue was removed). An action still
    waiting on its tap (request 104) is dropped; one that ran stays done."""
    card = await cards.get(actor) if cards is not None and actor is not None else None
    if card is None or card.state == LEGACY or not card.items:
        return StepResult("info", text=NOTHING_TO_UNDO)
    if refs:
        items = card.by_ref(refs)
        if items is None:
            return StepResult("error", text="Those entries are not on their latest card, so nothing was removed.")
    elif len(card.items) > 1:
        return StepResult("choose", text="Which one should be removed?", reply=undo_pick_list(card))
    else:
        items = card.items
    from .actions import ACTION_FACT

    pending = [i for i in items if i.fact_type == ACTION_FACT]
    drafts = [i for i in items if i.fact_type != ACTION_FACT]
    gone: list[CardItem] = []
    refused: list[str] = []
    for item in pending:
        if card.state == OPEN and actions is not None:
            await actions.store.drop(actor, uuid.UUID(item.fact_id).hex)
            gone.append(item)
        else:
            refused.append("it has already been done, so it can't be taken back here")
    undone = None
    if drafts and undo_facts is None:
        return StepResult("info", text=NOTHING_TO_UNDO)
    if drafts:
        undone = await undo_facts([i.fact for i in drafts])
        if undone is None and not gone:
            return StepResult("info", text=NOTHING_TO_UNDO)
        if undone is not None:
            gone.extend(i for i in drafts if i.fact in set(undone.done))
            refused.extend(getattr(undone, "refused", []) or [])
    if gone:
        await cards.drop(actor, [i.fact for i in gone])
    summary = SimpleNamespace(done=[i.fact for i in gone], refused=refused)
    return undo_step(gone, summary)


def _without_menu(text: str) -> str:
    """A module-disabled reply is one line; older replies carried the
    capability list after it, which the agent never repeats (requests [43], [59])."""
    if is_module_disabled_reply(text):
        return text.split("\n\n", 1)[0]
    return text


def _saved_summary(handled: Any, timezone: str | None = None) -> str | None:
    """What the confirmed record says, from its own data. Never raises."""
    try:
        from canonicalization.occurred_date import today_for
        from channel.receipt.data import company_zone

        confirmed = getattr(handled.result, "confirmed_action", None)
        today = today_for(str(company_zone(timezone)))
        return summarise_draft(confirmed.draft_action, today=today) if confirmed is not None else None
    except Exception:  # noqa: BLE001 -- the summary is wording only
        _log.warning("agent.saved_summary_failed", exc_info=True)
        return None


def _succeeded(handled: Any) -> bool:
    """Whether the save behind ``handled`` actually wrote its record."""
    execution = getattr(handled, "execution_result", None)
    return execution is not None and execution.status is ExecutionStatus.SUCCEEDED


#: ``() -> InteractionHandled | None``: save the waiting capture draft.
SaveNowFn = Callable[[], Awaitable[Any]]
#: ``() -> str | None``: the classic UNDO of the latest saved draft.
UndoFn = Callable[[], Awaitable[str | None]]
#: ``(handled) -> None``: the follow-ups a saved confirmation triggers.
FollowupsFn = Callable[[Any], Awaitable[None]]
#: ``(journey_result) -> ReplySpec``: the confirm prompt the journey held back.
HeldPromptFn = Callable[[Any], ReplySpec]


@dataclass(slots=True)
class JourneyGateway:
    message: NormalizedMessage
    save_now: SaveNowFn
    undo: UndoFn
    followups: FollowupsFn
    held_prompt: HeldPromptFn
    language: str | None = None
    handled: list[Any] = field(default_factory=list)
    #: WA-41: ``(material, unit, count) -> line to say``; None when not wired.
    set_conversion: Callable[[str, str, Any], Awaitable[str]] | None = None
    #: ARCH-01: material receipts/usage straight to the workflow
    #: (runtime/agent/material_entry.py).
    material_entry: Any | None = None
    #: ARCH-02: work done, site issues and expenses straight to the workflow
    #: (runtime/agent/site_entry.py).
    site_entry: Any | None = None
    #: ARCH-03: labour attendance straight to its workflow
    #: (runtime/agent/labour_entry.py; Alan's approval, 22 Oct).
    labour_entry: Any | None = None
    #: ARCH-06 step 2: lookups, transfers, site/project create, money undo
    #: (runtime/agent/query_entry.py).
    query_entry: Any | None = None
    #: 22 Oct: add a team member, correct a work quantity, close a site issue
    #: (runtime/agent/change_entry.py).
    change_entry: Any | None = None
    #: Request 104: cards for what is not a record -- a question for the engineer,
    #: the day's conditions, issues to close (runtime/agent/actions.py). The
    #: store keeps what the Save tap runs; the entry places and prepares it.
    actions: Any | None = None
    action_entry: Any | None = None
    #: The pending actions this turn put on the card.
    action_items: list[CardItem] = field(default_factory=list)
    #: ``WorkflowRuntime.start``, for the direct routes.
    start_workflow: Callable[[Any, Any], Awaitable[Any]] | None = None
    #: WA-45: ``(project_id, site_id) -> label``: today's site is this one
    #: (runtime/agent/work_site.py); None when not wired.
    set_today_site: Callable[[str | None, str], Awaitable[str]] | None = None
    #: ``() -> site id`` the sender works at today, if set (SIT-05: a save at
    #: another site does not move it).
    get_today_site: Callable[[], Awaitable[str | None]] | None = None
    #: Request 88: the sender's latest card (runtime/agent/cards.py), who they
    #: are, and ``(facts) -> FactsUndone | None``: withdraw exactly those entries.
    cards: Any | None = None
    actor: Any | None = None
    undo_facts: Callable[[list[Any]], Awaitable[Any]] | None = None
    #: The tool and arguments of the call being run, set by the toolbox.
    current_call: tuple[str, dict[str, Any]] | None = None
    #: The entries this turn saved, with the call that made each; and, when an
    #: open card was changed, the items of that card before and after the new one.
    card_items: list[CardItem] = field(default_factory=list)
    carry_before: list[CardItem] = field(default_factory=list)
    carry_after: list[CardItem] = field(default_factory=list)

    async def run(self, candidate: Candidate, *, text: str) -> StepResult:
        step = await self._run(candidate, text=text)
        if step.status == "saved" and self.handled and not (getattr(candidate, "fields", None) or {}).get("_action"):
            await self._remember_site(self.handled[-1])
            self._note_card_item(self.handled[-1], step)
        return step

    def _note_card_item(self, handled: Any, step: StepResult) -> None:
        """Remember which call made this record, for its card."""
        from .save_button import fact_of

        fact = fact_of(handled)
        if fact is None or self.current_call is None:
            return
        tool, args = self.current_call
        self.card_items.append(CardItem(tool, dict(args), fact[0], str(fact[1]), step.summary or ""))

    def discard_actions(self) -> None:
        """The turn ended on a question, so its card is never shown: nothing
        pending may look as if it waits on a tap (they expire unread)."""
        gone = {i.fact_id for i in self.action_items}
        self.card_items = [i for i in self.card_items if i.fact_id not in gone]
        self.action_items = []

    def action_facts(self) -> list[tuple[str, Any]]:
        """The pending actions this turn put on its card (their tap ids)."""
        return [i.fact for i in self.action_items]

    def card_facts(self) -> list[tuple[str, Any]]:
        """Every entry of the card this turn shows: the items kept from the
        open card, then what this turn saved."""
        return [i.fact for i in (*self.carry_before, *self.card_items, *self.carry_after)]

    def carry_card_items(self, before: list[CardItem], after: list[CardItem]) -> None:
        self.carry_before, self.carry_after = list(before), list(after)

    async def open_card(self) -> Card | None:
        """The sender's card that still waits on Save / Cancel, or None."""
        card = await self._latest_card()
        return card if card is not None and card.state == OPEN else None

    async def _latest_card(self) -> Card | None:
        if self.cards is None or self.actor is None:
            return None
        return await self.cards.get(self.actor)

    async def withdraw_card_item(self, item: CardItem) -> bool:
        """Take one entry of the open card back (its draft), through its
        module's own undo. True when it is gone."""
        from .actions import ACTION_FACT

        if item.fact_type == ACTION_FACT:
            if self.actions is None:
                return False
            await self.actions.store.drop(self.actor, uuid.UUID(item.fact_id).hex)
            return True
        if self.undo_facts is None:
            return False
        undone = await self.undo_facts([item.fact])
        return bool(undone is not None and undone.done)

    async def undo_card(self, refs: list[str]) -> StepResult:
        """Request 88/90: "undo that" removes the entries of the sender's latest
        card -- never a record the code did not offer. ``refs`` are the ids the
        model named; one that is not on the card is refused."""
        return await undo_from_card(self.cards, self.actor, self.undo_facts, refs, self.actions)

    async def _remember_site(self, handled: Any) -> None:
        """WA-45: a save at a site keeps the sender there for the rest of the
        day, whatever module it was. Never raises."""
        if self.set_today_site is None:
            return
        try:
            confirmed = getattr(handled.result, "confirmed_action", None)
            draft = confirmed.draft_action if confirmed is not None else None
            site_id = getattr(draft, "site_id", None)
            if site_id:
                if self.get_today_site is not None:
                    current = await self.get_today_site()
                    if current and str(current) != str(site_id):
                        return
                await self.set_today_site(getattr(draft, "project_id", None), str(site_id))
        except Exception:  # noqa: BLE001 -- a missed hint only costs one question
            _log.warning("agent.remember_site_failed", exc_info=True)

    async def set_work_site(self, *, project_id: str | None, site_id: str) -> str:
        if self.set_today_site is None:
            raise RuntimeError("today's site is not wired")
        return await self.set_today_site(project_id, site_id)

    async def _run(self, candidate: Candidate, *, text: str) -> StepResult:
        # A text message carrying the user's words: the workflows' own checks
        # (duplicates, narrative, logging) read it. Voice was transcribed already;
        # a photo keeps its modality and media, so the entry attaches it.
        update: dict[str, Any] = {"text": text}
        if self.message.modality not in (InputModality.IMAGE, InputModality.DOCUMENT):
            update["modality"] = InputModality.TEXT
        message = self.message.model_copy(update=update)
        if (getattr(candidate, "fields", None) or {}).get("_action"):
            return await self._run_action(candidate, message)
        entry = self._entry_for(getattr(candidate, "semantic_type", None))
        if entry is None:
            kind = getattr(getattr(candidate, "semantic_type", None), "value", None)
            _log.warning("agent.no_entry correlation_id=%s kind=%s", message.correlation_id, kind)
            return StepResult("error", text="Not saved: that can't be done here yet.")
        return await self._direct(entry, candidate, message)

    async def _run_action(self, candidate: Candidate, message: Any) -> StepResult:
        """Request 104: a card for something that is not a record. Nothing is
        done here; the Save tap runs it (runtime/agent/actions.py)."""
        from .actions import ACTION_FACT
        from .entry_base import Say, tool_understanding

        if self.action_entry is None or self.actions is None:
            return StepResult("error", text="Not done: that can't be done here yet.")
        understanding = tool_understanding(candidate, message, language=self.language)
        prepared = await self.action_entry.prepare(message, understanding, candidate)
        if isinstance(prepared, Say):
            from .toolbox import question_reply

            reply = question_reply(prepared.question, list(prepared.options)) if prepared.question else None
            return StepResult(prepared.status, text=prepared.text, reply=reply)
        prepared_list = prepared if isinstance(prepared, list) else [prepared]
        tool = self.current_call[0] if self.current_call else prepared_list[0].kind
        args = dict(self.current_call[1]) if self.current_call else {}
        for action in prepared_list:
            if not await self.actions.store.put(self.actor, action):
                return StepResult("error", text="Not done: the card could not be prepared. Please send it again.")
        for action in prepared_list:
            item = CardItem(tool, args, ACTION_FACT, str(uuid.UUID(action.id)), action.summary)
            self.card_items.append(item)
            self.action_items.append(item)
        summaries = [a.summary for a in prepared_list]
        return StepResult(
            "saved",
            text="; ".join(summaries),
            workflow_key=prepared_list[0].kind,
            summary=summaries[0],
            summaries=summaries if len(summaries) > 1 else [],
        )

    def _entry_for(self, semantic_type: Any) -> Any | None:
        """The direct entry for this kind of record, or None (not wired)."""
        if self.start_workflow is None:
            return None
        if semantic_type is SemanticType.MATERIAL_UPDATE:
            return self.material_entry
        if semantic_type is SemanticType.LABOUR_UPDATE:
            return self.labour_entry
        from .site_entry import SITE_ENTRY_TYPES

        if semantic_type in SITE_ENTRY_TYPES:
            return self.site_entry
        from .query_entry import QUERY_ENTRY_TYPES

        if semantic_type in QUERY_ENTRY_TYPES:
            return self.query_entry
        from .change_entry import CHANGE_ENTRY_TYPES

        if semantic_type in CHANGE_ENTRY_TYPES:
            return self.change_entry
        return None

    async def _direct(self, entry: Any, candidate: Candidate, message: Any) -> StepResult | None:
        """ARCH-01/02: the tool's arguments as the workflow's event. Never the
        classic route (ARCH-06, Ilan 22 Oct): what the entry cannot place
        (a failed lookup) is said, not handed to the old pipeline."""
        from types import SimpleNamespace

        from .entry_base import Say, tool_understanding

        understanding = tool_understanding(candidate, message, language=self.language)
        prepared = await entry.prepare(message, understanding, candidate)
        kind = getattr(getattr(candidate, "semantic_type", None), "value", None)
        if prepared is None:
            _log.warning("agent.direct correlation_id=%s kind=%s route=unplaced", message.correlation_id, kind)
            return StepResult("error", text="Not saved: the system could not look this up just now. Send it again.")
        if isinstance(prepared, Say):
            from .toolbox import question_reply

            reply = question_reply(prepared.question, list(prepared.options)) if prepared.question else None
            return StepResult(prepared.status, text=prepared.text, reply=reply)
        run = await self.start_workflow(prepared.decision, prepared.event)
        _log.info("agent.direct correlation_id=%s kind=%s route=direct", message.correlation_id, kind)
        journey = SimpleNamespace(workflow_run=run, planner_decision=prepared.decision)
        step = await self._after_run(journey, candidate)
        if step.status in ("saved", "needs_confirmation"):
            await entry.remember(prepared, correlation_id=message.correlation_id)
        deliver = getattr(entry, "deliver", None)
        if deliver is not None:
            failed = await deliver(prepared, message)
            if failed:
                from dataclasses import replace

                step = replace(step, text=f"{step.text}\n\n{failed}".strip())
        return step

    async def _after_run(self, journey: Any, candidate: Candidate) -> StepResult:
        run = journey.workflow_run
        key = run.workflow_key.value if run is not None else None

        if run is not None and run.status is WorkflowRunStatus.STARTED:
            saved = await self.save_now()
            if saved is not None and not _succeeded(saved):
                # WA-37: the save was refused or failed (a repeat, a closed
                # day, a validation error). Its reply says why; it is never
                # "saved", or the model writes "Saved" for nothing.
                return StepResult("error", text=saved.reply_text, workflow_key=key)
            if saved is not None and getattr(candidate, "semantic_type", None) in _LOOKUPS:
                # A lookup ends through the same step as an entry (the answer
                # is that step's reply), but it keeps nothing: never "saved",
                # no Undo line, no part of the Save card (round 3b, 21 Oct).
                return StepResult("answer", text=saved.reply_text, workflow_key=key)
            if saved is not None:
                self.handled.append(saved)
                return StepResult(
                    "saved",
                    text=saved.reply_text,
                    workflow_key=key,
                    summary=_saved_summary(saved, getattr(self.actor, "timezone", None)),
                )
            # Confirm-first (expenses, transfers) or the save failed: the
            # prompt the sender must answer.
            prompt = self.held_prompt(journey)
            return StepResult("needs_confirmation", text=prompt.text, reply=prompt, workflow_key=key)

        if run is not None and run.status in (
            WorkflowRunStatus.AWAITING_INPUT,
            WorkflowRunStatus.BLOCKED_PENDING_CONFIRMATION,
        ):
            if run.status is WorkflowRunStatus.BLOCKED_PENDING_CONFIRMATION:
                # Nothing of this message was kept: an earlier entry waits for
                # its Yes/No. Said plainly, with no buttons, so a Yes is never
                # taken for this one (review, 22 Oct: the bare earlier card
                # went out and Yes confirmed the old entry instead).
                return StepResult(
                    "error",
                    text=(
                        "Not saved: an earlier entry is still waiting for Yes or No (its buttons are "
                        "above). Answer that one first, then send this again."
                    ),
                    workflow_key=key,
                )
            # The workflow's question, with its list or buttons.
            prompt = self.held_prompt(journey)
            return StepResult("needs_answer", text=prompt.text, reply=prompt, workflow_key=key)

        if run is not None and run.status is WorkflowRunStatus.COMPLETED:
            return StepResult("answer", text=run.pending_prompt or "", workflow_key=key)

        # FAILED / NO_GRAPH, or nothing started.
        return StepResult("error", text="Sorry, that didn't go through. Please try again.", workflow_key=key)

    async def set_unit_conversion(self, *, material: str, unit: str, count: Any) -> StepResult:
        if self.set_conversion is None:
            return StepResult("info", text="I can't remember unit conversions here yet.")
        line = await self.set_conversion(material, unit, count)
        status = "answer" if line.startswith("Saved for the company") else "info"
        return StepResult(status, text=line)

    async def undo_latest_draft(self) -> StepResult:
        reply = await self.undo()
        if reply:
            return StepResult("undone", text=reply)
        return StepResult("info", text="There is no recent saved update of theirs to undo.")

    async def finish(self) -> None:
        for handled in self.handled:
            try:
                await self.followups(handled)
            except Exception:  # noqa: BLE001 — a follow-up never disturbs a saved record
                _log.exception("agent.followup_failed")
