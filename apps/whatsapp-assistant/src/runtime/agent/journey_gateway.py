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
from mesiri_contracts.assistant.draft_action import DraftActionType
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


#: Request 136: the reads of a day's figures whose site comes from the site resolver.
_DAY_READS = frozenset({SemanticType.ACTIVITY_QUERY, SemanticType.LABOUR_QUERY, SemanticType.INVENTORY_QUERY})

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
    #: WEB-38: the lookups this turn answered, as (workflow instance, project,
    #: site), so the message log ties the question to what answered it (the
    #: Live page shows questions and Mesiri's answers from that link).
    answered: list[tuple[str | None, str | None, str | None]] = field(default_factory=list)
    #: WA-41: ``(material, unit, count) -> line to say``; None when not wired.
    set_conversion: Callable[[str, str, Any], Awaitable[str]] | None = None
    #: SET-07: sends the join code and the message to forward (join_journey.share_code).
    share_code: Callable[[], Awaitable[str]] | None = None
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
    #: ``(project_id, site_id)``: a confirmed site update was saved there; the
    #: site is preselected for the next unnamed update for a short window
    #: (work_site.remember_saved_site, request 129).
    remember_saved_site: Callable[[str | None, str], Awaitable[None]] | None = None
    #: Request 132: ``(project_id, site_id) -> label``: "now at Site B" on a draft
    #: card preselects that site for the save window only (work_site.WorkSite.preselect).
    preselect_site: Callable[[str | None, str], Awaitable[str]] | None = None
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
    #: Request 116 H: the join code and the message to forward went out, so the
    #: model's closing line would be a third, redundant message.
    code_shared: bool = False
    carry_before: list[CardItem] = field(default_factory=list)
    carry_after: list[CardItem] = field(default_factory=list)
    #: Request 124 (P1), the company's ``draft_v2`` setting: the save tools add
    #: to ONE open draft (``drafts``, runtime/agent/draft_store.py) instead of
    #: starting a workflow, and the Save tap writes it (``save_draft``). Off:
    #: none of the draft code below runs.
    draft_v2: bool = False
    drafts: Any | None = None
    #: Request 142 (B): the save journal (runtime/agent/journal.py): each Save
    #: writes one entry; undo and change of anything saved read it.
    journal: Any | None = None
    #: The sender's open draft, loaded on first use; ``draft_new`` are the item
    #: ids this turn added.
    draft: Any | None = None
    draft_loaded: bool = False
    draft_new: list[str] = field(default_factory=list)
    #: Request 136 (C): which component decided the site, the items and the reply
    #: of this turn (``draft_flow.decided``), written as the "draft_decisions" stage.
    decisions: list[dict[str, str]] = field(default_factory=list)
    #: ``() -> InteractionHandled | None``: confirm the waiting draft like a
    #: Yes (work on an open activity cannot be saved first, so the Save tap is
    #: its confirmation).
    confirm_now: Callable[[], Awaitable[Any]] | None = None
    #: ``() -> None``: drop the question a workflow was left asking.
    abandon_question: Callable[[], Awaitable[Any]] | None = None
    #: ``(facts) -> settled``: confirm the saved drafts (the Save tap's own step).
    settle_facts: Callable[[list[Any]], Awaitable[Any]] | None = None
    #: ``() -> async context manager``: one transaction for the whole Save.
    transaction: Callable[[], Any] | None = None
    #: Request 137: the day's saved work (runtime/day_facts.DayFactsReader): the
    #: fact a continued activity's Save wrote, and what a correction targets.
    day_facts: Any | None = None
    #: Progress update id -> its activity id, for the updates this Save wrote.
    continued: dict[str, Any] = field(default_factory=dict)
    #: ``() -> text | None``: the Yes / No question of an old-style workflow that
    #: still waits for its answer (request 127: said, not silently ignored).
    pending_confirmation: Callable[[], Awaitable[Any]] | None = None
    #: The WhatsApp sender, for the pending actions a Save runs (actions.run).
    sender: Any | None = None

    async def run(self, candidate: Candidate, *, text: str) -> StepResult:
        if self.draft_mode and self._drafted(candidate):
            return await self._draft_add(candidate, text=text)
        if self.draft_mode and getattr(candidate, "semantic_type", None) in _DAY_READS:
            candidate = await self._reading_site(candidate, text)
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

    async def _reading_site(self, candidate: Candidate, text: str) -> Candidate:
        """Request 136: a question about the day's figures ("innu enthokke cheythu?",
        "innu ethra labour?") reads the site the site resolver gives (the one named, the
        one saved to in the window), else every site of theirs: never the site the
        context layer defaults to, which is how a saved Green Villa update read as
        "no work recorded"."""
        from . import draft_site
        from .draft_flow import decided
        from .entry_base import ALL_SITES

        fields = dict(getattr(candidate, "fields", None) or {})
        said = str(fields.get("site_name") or "")
        if fields.get("site_id"):
            decided(self, "read_site", draft_site.DECIDER, draft_site.NAMED)
            return candidate
        saved = None
        if self.get_today_site is not None:
            try:
                saved = await self.get_today_site()
            except Exception:  # noqa: BLE001 -- then every site is read
                _log.warning("agent.saved_site_unreadable", exc_info=True)
        choice = draft_site.resolve(self.actor, text, said=said, saved_site_id=saved)
        site = choice.site if choice.kind != draft_site.ASK else None
        if site is None and said:
            return candidate  # a name that is none of theirs: the entry asks, as before
        decided(self, "read_site", draft_site.DECIDER, choice.kind if site is not None else ALL_SITES)
        if site is None:
            fields[ALL_SITES] = True
        else:
            fields.pop("site_name", None)
            fields["site_id"] = str(site.id)
        return candidate.model_copy(update={"fields": fields})

    @property
    def draft_mode(self) -> bool:
        """Whether this sender's company holds messages as one draft card."""
        return bool(self.draft_v2) and self.drafts is not None

    def _drafted(self, candidate: Candidate) -> bool:
        """A save tool whose call becomes a line on the card. What is not one
        (an expense, a transfer, opening stock...) runs as it always did."""
        from .draft import DRAFT_TOOLS

        tool = self.current_call[0] if self.current_call else ""
        return tool in DRAFT_TOOLS and not (getattr(candidate, "fields", None) or {}).get("_action")

    async def _draft_add(self, candidate: Candidate, *, text: str) -> StepResult:
        from . import draft_flow

        return await draft_flow.add(self, candidate, text=text)

    @property
    def journal_mode(self) -> bool:
        """Whether undo and change of saved entries go through the journal."""
        return self.draft_mode and self.journal is not None

    async def change_or_undo(self, ref: str, changes: dict[str, Any] | None = None) -> StepResult:
        from . import undo_flow

        return await undo_flow.request(self, ref, changes)

    async def journal_tap(self, action: str, entry_id: str, numbers: list[int] | None) -> ReplySpec:
        from . import undo_flow

        return await undo_flow.confirm(self, action, entry_id, numbers)

    async def pick_issues(self, tap: str) -> ReplySpec:
        """Request 142: the tap on a row of "which issue is fixed?". The row names its
        issues; they become the "Close: ..." line of the card, with Save. No model is
        asked to match a title again, so a tap can never ask the same question twice."""
        from . import draft as dr
        from . import issue_match

        refs = issue_match.parse_tap(tap)
        if refs is None:
            return ReplySpec(text="That choice has expired. Tell me which issue is fixed.")
        if not refs:
            return ReplySpec(text=issue_match.ELSE_TEXT)
        fields = {"_action": "close_issues", "issue_refs": refs}
        candidate = Candidate(semantic_type=SemanticType.SITE_ISSUE_UPDATE, fields=fields)
        self.current_call = ("update_issue", {"action": "resolve", "issue_refs": refs})
        message = self.message.model_copy(update={"text": self.message.text or "", "modality": InputModality.TEXT})
        step = await self._run_action(candidate, message)
        if step.status != "saved":
            return step.reply or ReplySpec(text=step.text)
        draft = await self.open_draft()
        if draft is None or not draft.live:
            return ReplySpec(text=step.text)
        from . import draft_flow

        return dr.card_reply(draft, "", site=draft_flow._card_site(self, draft))

    async def open_draft(self) -> Any | None:
        from . import draft_flow

        return await draft_flow.load(self) if self.draft_mode else None

    async def save_draft(self, draft: Any) -> ReplySpec:
        """The Save tap (runtime/agent/draft_flow.py): the draft written in one transaction."""
        from . import draft_flow

        return await draft_flow.save(self, draft)

    async def cancel_draft(self, draft: Any) -> ReplySpec:
        from . import draft_flow

        return await draft_flow.cancel(self, draft)

    async def edit_draft_item(self, draft: Any, item: Any, changes: dict[str, Any]) -> StepResult:
        """A correction of a line of the open card (request 127)."""
        from . import draft_flow

        return await draft_flow.edit_item(self, draft, item, changes, text=self.message.text or "")

    async def change_saved_item(self, card_item: CardItem, changes: dict[str, Any]) -> StepResult:
        """A correction of an entry already saved: a change line on the card."""
        from . import draft_flow

        return await draft_flow.change_saved(self, card_item, changes, text=self.message.text or "")

    async def saved_card(self) -> Card | None:
        from . import draft_flow

        return await draft_flow.saved_card(self) if self.draft_mode else None

    async def saved_work_today(self) -> list[Any]:
        """Request 137 (C): the sender's own saved work facts of today, from the
        database (runtime/day_facts.py), oldest first. Empty when not wired."""
        from . import draft_flow

        return await draft_flow.saved_work_today(self) if self.draft_mode else []

    def change_site_draft(self, draft: Any) -> ReplySpec:
        """The "📍 Change site" tap: the sites to pick from (request 129)."""
        from . import draft_flow

        return draft_flow.change_site_list(self, draft)

    async def move_draft_site(self, draft: Any, site_id: str) -> ReplySpec:
        """A site picked for the whole card (request 129)."""
        from . import draft_flow

        return await draft_flow.move_site(self, draft, site_id)

    async def answer_draft_typed(self, draft: Any, text: str) -> ReplySpec | None:
        """WA-81: a typed answer to the open card's question, read by code; None when
        the message is not one (the model reads it)."""
        from . import draft_flow

        return await draft_flow.answer_typed(self, draft, text)

    async def answer_draft(self, draft: Any, item_id: str, choice: int) -> ReplySpec:
        from . import draft_flow

        return await draft_flow.answer(self, draft, item_id, choice)

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
        if self.set_today_site is None and self.remember_saved_site is None:
            return
        try:
            from .work_site import SITE_UPDATE_ACTIONS

            confirmed = getattr(handled.result, "confirmed_action", None)
            draft = confirmed.draft_action if confirmed is not None else None
            site_id = getattr(draft, "site_id", None)
            if site_id and getattr(draft, "action_type", None) in SITE_UPDATE_ACTIONS:
                if self.remember_saved_site is not None:
                    await self.remember_saved_site(getattr(draft, "project_id", None), str(site_id))
                    return
                if self.get_today_site is not None:
                    current = await self.get_today_site()
                    if current and str(current) != str(site_id):
                        return
                await self.set_today_site(getattr(draft, "project_id", None), str(site_id))
        except Exception:  # noqa: BLE001 -- a missed hint only costs one question
            _log.warning("agent.remember_site_failed", exc_info=True)

    async def set_work_site(self, *, project_id: str | None, site_id: str) -> str:
        if self.draft_mode and self.preselect_site is not None:
            # Request 132: on a draft card "now at Site B" preselects for the save
            # window (3 h), like a save does; it no longer pins the site until midnight.
            return await self.preselect_site(project_id, site_id)
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
        if self.draft_mode:
            # Request 142: an ambiguous pick (which issue?) offers rows whose ids name the thing.
            candidate = candidate.model_copy(update={"fields": {**candidate.fields, "pick_ids": True}})
        understanding = tool_understanding(candidate, message, language=self.language)
        prepared = await self.action_entry.prepare(message, understanding, candidate)
        if isinstance(prepared, Say):
            from .toolbox import question_reply

            reply = (
                question_reply(prepared.question, list(prepared.options), awaiting=prepared.awaiting, rows=prepared.rows)
                if prepared.question
                else None
            )
            return StepResult(prepared.status, text=prepared.text, reply=reply, awaiting=prepared.awaiting)
        prepared_list = prepared if isinstance(prepared, list) else [prepared]
        tool = self.current_call[0] if self.current_call else prepared_list[0].kind
        args = dict(self.current_call[1]) if self.current_call else {}
        for action in prepared_list:
            if not await self.actions.store.put(self.actor, action):
                return StepResult("error", text="Not done: the card could not be prepared. Please send it again.")
        if self.draft_mode:
            # One card for the whole message: the action is a line of the draft,
            # and the one Save tap runs it (after everything else is written).
            from . import draft_flow

            await draft_flow.add_action(self, tool, args, prepared_list)
        else:
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

            reply = question_reply(prepared.question, list(prepared.options), awaiting=prepared.awaiting) if prepared.question else None
            return StepResult(prepared.status, text=prepared.text, reply=reply, awaiting=prepared.awaiting)
        run = await self.start_workflow(prepared.decision, prepared.event)
        _log.info("agent.direct correlation_id=%s kind=%s route=direct", message.correlation_id, kind)
        journey = SimpleNamespace(workflow_run=run, planner_decision=prepared.decision)
        step = await self._after_run(journey, candidate)
        if step.status == "answer":
            # A lookup usually finishes without a workflow row (WEB-46): its
            # project and site are still recorded on the message.
            instance = getattr(run, "workflow_instance_id", None)
            event = prepared.event
            project = getattr(event, "project_id", None)
            site = getattr(event, "site_id", None)
            self.answered.append(
                (str(instance) if instance else None, str(project) if project else None, str(site) if site else None)
            )
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
            card = self._work_card(run)
            if card is not None:
                return StepResult("needs_confirmation", text=card.text, reply=card, workflow_key=key)
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

    def _work_card(self, run: Any) -> ReplySpec | None:
        """Request 114: work done on an open activity is held for its answer
        (the review log has no place for a progress update, so it cannot be
        saved first). It is shown as the same "To save" card as everything
        else, with Save / Cancel (the Yes / No ids, so the answer is the same
        confirmation), never a bare Yes / No under words that say "Saved"."""
        draft = run.draft_action
        if draft is None or draft.action_type is not DraftActionType.ADD_PROGRESS_UPDATE:
            return None
        from canonicalization.occurred_date import today_for
        from channel.receipt.data import company_zone
        from interactions.saved_summary import render_saved

        from .save_button import CANCEL_TITLE, SAVE_TITLE, TO_SAVE_HEADER
        from .work_site import short_site_label

        try:
            today = today_for(str(company_zone(getattr(self.actor, "timezone", None))))
            summary = summarise_draft(draft, today=today)
        except Exception:  # noqa: BLE001 -- the card is wording only
            _log.warning("agent.work_card_failed", exc_info=True)
            return None
        if not summary:
            return None
        site = short_site_label(self.actor, draft.site_id) if draft.site_id else None
        header = f"{TO_SAVE_HEADER[:-1]} · {site}:" if site else TO_SAVE_HEADER
        return ReplySpec(
            text=render_saved([summary], header),
            buttons=(ListRow("confirm_yes", SAVE_TITLE), ListRow("confirm_no", CANCEL_TITLE)),
        )

    async def share_join_code(self) -> StepResult:
        if self.share_code is None:
            return StepResult("info", text="I can't share the join code here.")
        refusal = await self.share_code()
        if refusal:
            return StepResult("info", text=refusal)
        self.code_shared = True
        return StepResult(
            "info",
            text=(
                "The join code and a message to forward were already sent as separate messages. "
                "Reply with one short line at most; do not repeat the code."
            ),
        )

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
