"""Adding to the draft, and the Save / Cancel / answer taps (request 124, P1).

``JourneyGateway`` hands its save tools here when the company's ``draft_v2``
setting is on (ADR-draft-per-message section 2):

- ``add``: the entry prepares the workflow's event exactly as before (the
  lookups, the checks that can ask a question) but NOTHING is started or written;
  the prepared event becomes an item of the sender's one open draft. A tool call
  that cannot become a line is kept as ``unreadable`` so the card says so;
- ``save``: every ready item is written through the existing path (start the
  workflow, ``save_now``, confirm the draft) inside ONE transaction. Any failure
  rolls the lot back and says which item failed; a second tap finds the draft
  already taken and writes nothing;
- ``cancel``: the draft is discarded. Nothing was ever written, so the words
  say so;
- ``answer``: the tap on a question of the card (labour: replace or add?).

Pending actions of request 104 (a question for the engineer, the day's
conditions, issues to close) keep their own store; the draft holds their ids and
runs them after the transaction has committed, because a message that was sent
cannot be rolled back.
"""

from __future__ import annotations

import contextlib
import logging
import uuid
from types import SimpleNamespace
from typing import Any

from canonicalization.occurred_date import today_for
from channel.receipt.data import company_zone
from channel.replies import ReplySpec
from mesiri_contracts.assistant.v2.canonical_event import CanonicalEventV2
from mesiri_contracts.assistant.v2.planner_decision import PlannerDecisionV2
from workflows import WorkflowRunStatus

from . import draft as dr
from .cards import SAVED as CARD_SAVED
from .cards import CardItem, merge_changes, new_card
from .entry_base import Ready, Say, tool_understanding
from .gateway import StepResult
from .save_button import SAVED_DONE, fact_of
from .tools import ScopeLookup, to_candidate

_log = logging.getLogger("mesiri.agent")

#: The card holds this many entries; the reply says so rather than drop one.
TOO_MANY = "That is more than one card holds. Save or cancel this card first, then send the rest."


# -- Ready <-> JSON -------------------------------------------------------------


def ready_to_json(ready: Ready) -> dict[str, Any]:
    return {
        "decision": ready.decision.model_dump(mode="json"),
        "event": ready.event.model_dump(mode="json"),
        "scope": list(ready.scope) if ready.scope else None,
    }


def ready_from_json(raw: dict[str, Any]) -> Ready:
    scope = raw.get("scope")
    return Ready(
        decision=PlannerDecisionV2.model_validate(raw["decision"]),
        event=CanonicalEventV2.model_validate(raw["event"]),
        scope=tuple(scope) if scope else None,
    )


# -- helpers --------------------------------------------------------------------


def _today(gw: Any) -> Any:
    try:
        return today_for(str(company_zone(getattr(gw.actor, "timezone", None))))
    except Exception:  # noqa: BLE001 -- the day only words an issue's date
        return None


def _scope(gw: Any) -> ScopeLookup:
    actor = gw.actor
    return ScopeLookup(
        projects=tuple((p.id, p.name) for p in getattr(actor, "projects", None) or []),
        sites=tuple((s.id, s.name, s.project_id) for s in getattr(actor, "sites", None) or []),
    )


def _site_name(gw: Any, site_id: Any) -> str:
    if not site_id or len(getattr(gw.actor, "sites", None) or []) < 2:
        return ""
    from .work_site import short_site_label

    return short_site_label(gw.actor, str(site_id)) or ""


def _owner(gw: Any) -> tuple[str, str]:
    return str(gw.actor.organization_id), str(gw.actor.user_id)


async def load(gw: Any) -> dr.MessageDraft | None:
    """The sender's open draft (once per turn)."""
    if not gw.draft_loaded:
        gw.draft_loaded = True
        org, user = _owner(gw)
        gw.draft = await gw.drafts.open_for(org, user)
    return gw.draft


def _keep(gw: Any, draft: dr.MessageDraft) -> None:
    gw.draft, gw.draft_loaded = draft, True


async def _persist(gw: Any, draft: dr.MessageDraft) -> None:
    """Keep the draft when something on it can still be saved or answered; a
    card of only unreadable lines is shown once and never kept."""
    if draft.live:
        first = next((i for i in draft.items if i.state != dr.UNREADABLE and i.site_id), None)
        if first is not None:
            draft.site_id = first.site_id
            ready = (first.ready or {}).get("event") or {}
            draft.project_id = str(ready.get("project_id") or "") or draft.project_id
        await gw.drafts.put(draft)


def _item_for(gw: Any, tool: str, args: dict[str, Any], ready: Ready) -> dr.DraftItem:
    fields = ready.event.fields
    summary = dr.preview(ready.decision.workflow_key, fields, today=_today(gw))
    site_id = str(ready.event.site_id or "")
    item = dr.DraftItem(
        kind=dr.KIND_BY_TOOL[tool],
        tool=tool,
        args=dict(args),
        summary=summary or "",
        ready=ready_to_json(ready),
        label=dr.label_for(tool, args),
        site_id=site_id,
        site=_site_name(gw, site_id),
    )
    if not summary:
        item.state, item.reason = dr.UNREADABLE, "nothing readable in it"
        return item
    if item.kind == dr.KIND_LABOUR and (asked := dr.labour_question(fields)) is not None:
        item.state, (item.question, item.options) = dr.NEEDS_ANSWER, asked
    return item


def _unreadable(tool: str, args: dict[str, Any], reason: str) -> dr.DraftItem:
    return dr.DraftItem(
        kind=dr.KIND_BY_TOOL.get(tool, dr.KIND_ACTION),
        tool=tool,
        args=dict(args),
        state=dr.UNREADABLE,
        reason=reason,
        label=dr.label_for(tool, args),
    )


async def _add_item(gw: Any, item: dr.DraftItem, *, source: str | None) -> dr.MessageDraft:
    org, user = _owner(gw)
    draft = await load(gw) or dr.MessageDraft.new(organization_id=org, user_id=user, source_message_id=source)
    draft.items.append(item)
    _log.info(
        "draft.item_added draft=%s kind=%s state=%s items=%s correlation_id=%s",
        draft.id, item.kind, item.state, len(draft.items), getattr(gw.message, "correlation_id", None),
    )
    gw.draft_new.append(item.id)
    _keep(gw, draft)
    await _persist(gw, draft)
    return draft


async def note_lost(gw: Any, tool: str, args: dict[str, Any], reason: str) -> None:
    """A write call that never became a line (refused before the entry, or it
    failed): on the card as "Couldn't read: ..." so nothing is dropped silently
    (ADR section 2.6)."""
    await _add_item(gw, _unreadable(tool, args, reason), source=gw.message.message_id)


# -- add ------------------------------------------------------------------------


async def add(gw: Any, candidate: Any, *, text: str) -> StepResult:
    tool, args = gw.current_call or ("", {})
    update: dict[str, Any] = {"text": text}
    from mesiri_contracts.assistant.enums import InputModality

    if gw.message.modality not in (InputModality.IMAGE, InputModality.DOCUMENT):
        update["modality"] = InputModality.TEXT
    message = gw.message.model_copy(update=update)
    entry = gw._entry_for(getattr(candidate, "semantic_type", None))
    if entry is None:
        await note_lost(gw, tool, args, "that can't be done here yet")
        return StepResult("error", text="Not saved: that can't be done here yet.")
    prepared = await entry.prepare(message, tool_understanding(candidate, message, language=gw.language), candidate)
    if prepared is None:
        await note_lost(gw, tool, args, "it could not be looked up")
        return StepResult("error", text="Not saved: the system could not look this up just now. Send it again.")
    if isinstance(prepared, Say):
        from .toolbox import question_reply

        if prepared.status == "error":
            await note_lost(gw, tool, args, prepared.text)
        reply = (
            question_reply(prepared.question, list(prepared.options), awaiting=prepared.awaiting)
            if prepared.question
            else None
        )
        return StepResult(prepared.status, text=prepared.text, reply=reply, awaiting=prepared.awaiting)

    draft = await load(gw)
    item = _item_for(gw, tool, args, prepared)
    if item.state == dr.UNREADABLE:
        await _add_item(gw, item, source=message.message_id)
        return StepResult("error", text=f"Couldn't read it: {item.label}. Nothing was added to the card.")

    # A later labour count for the same site and day merges into the one on the
    # card (the same trade replaces, another trade adds), as a card edit did.
    old = dr.same_day_labour(draft, item) if draft is not None else None
    if old is not None:
        merged = merge_changes(tool, old.args, args)
        again = to_candidate(tool, merged, _scope(gw))
        redone = (
            await entry.prepare(message, tool_understanding(again, message, language=gw.language), again)
            if again is not None
            else None
        )
        if isinstance(redone, Ready):
            item = _item_for(gw, tool, merged, redone)
            draft.items[draft.items.index(old)] = item
            gw.draft_new.append(item.id)
            _keep(gw, draft)
            await _persist(gw, draft)
            return _drafted(item, prepared)
    if draft is not None:
        if (same := dr.duplicate_of(draft, item)) is not None:
            return _drafted(same, prepared, repeated=True)
        if draft.full:
            await note_lost(gw, tool, args, "the card is full")
            return StepResult("error", text=TOO_MANY)
    await _add_item(gw, item, source=message.message_id)
    return _drafted(item, prepared)


def _drafted(item: dr.DraftItem, prepared: Ready, *, repeated: bool = False) -> StepResult:
    key = getattr(prepared.decision.workflow_key, "value", None)
    return StepResult(
        "drafted",
        text="already on the card" if repeated else "",
        workflow_key=key,
        summary=item.summary or item.label,
        awaiting="answer" if item.state == dr.NEEDS_ANSWER else "",
        reply=ReplySpec(text=item.question) if item.state == dr.NEEDS_ANSWER else None,
    )


async def add_action(gw: Any, tool: str, args: dict[str, Any], prepared: list[Any]) -> None:
    """The pending actions a tool call made (their store holds what the Save
    tap runs): one card line each, so the one Save tap covers them too."""
    for action in prepared:
        item = dr.DraftItem(
            kind=dr.KIND_ACTION,
            tool=tool,
            args=dict(args),
            summary=action.summary,
            action_id=uuid.UUID(action.id).hex,
            label=action.summary,
        )
        await _add_item(gw, item, source=gw.message.message_id)


# -- cancel / answer --------------------------------------------------------------


async def cancel(gw: Any, draft: dr.MessageDraft) -> ReplySpec:
    """Discard the draft. Nothing was ever written, so there is nothing to undo."""
    if not await gw.drafts.discard(draft.id):
        return ReplySpec(text=dr.ALREADY_DONE)
    _log.info("draft.cancelled draft=%s items=%s", draft.id, len(draft.items))
    if gw.actions is not None:
        for item in draft.items:
            if item.kind == dr.KIND_ACTION and item.action_id:
                await gw.actions.store.drop(gw.actor, item.action_id)
    gw.draft = None
    return ReplySpec(text=dr.CANCELLED)


async def answer(gw: Any, draft: dr.MessageDraft, item_id: str, choice: int) -> ReplySpec:
    item = draft.item(item_id)
    if item is None or not dr.apply_answer(item, choice, today=_today(gw)):
        return ReplySpec(text=dr.ALREADY_DONE)
    await gw.drafts.put(draft)
    return dr.card_reply(draft, site=_card_site(gw, draft))


def _card_site(gw: Any, draft: dr.MessageDraft) -> str | None:
    names = {i.site for i in draft.items if i.state != dr.UNREADABLE and i.site}
    return next(iter(names)) if len(names) == 1 else None


# -- save -------------------------------------------------------------------------


class _Failed(Exception):
    def __init__(self, item: dr.DraftItem | None, reason: str) -> None:
        super().__init__(reason)
        self.item = item
        self.reason = reason


@contextlib.asynccontextmanager
async def _no_transaction():
    yield


def _clean(text: str) -> str:
    return " ".join((text or "").split())[:160]


async def _write(gw: Any, item: dr.DraftItem) -> tuple[StepResult, tuple[str, uuid.UUID] | None]:
    """One item through the path a message took before drafts: start its
    workflow, save it as a draft (save-first) -- or, for what the review log
    does not cover (work on an open activity), confirm it, as the Save tap is
    its Yes."""
    from .journey_gateway import _saved_summary, _succeeded

    ready = ready_from_json(item.ready or {})
    candidate = to_candidate(item.tool, item.args, _scope(gw))
    entry = gw._entry_for(getattr(candidate, "semantic_type", None))
    if candidate is None or entry is None or gw.start_workflow is None:
        raise _Failed(item, "that can't be saved here yet")
    run = await gw.start_workflow(ready.decision, ready.event)
    if run is not None and run.status is WorkflowRunStatus.BLOCKED_PENDING_CONFIRMATION:
        raise _Failed(item, "an earlier question is still waiting for its answer")
    journey = SimpleNamespace(workflow_run=run, planner_decision=ready.decision)
    step = await gw._after_run(journey, candidate)
    if step.status == "needs_confirmation" and gw.confirm_now is not None:
        confirmed = await gw.confirm_now()
        if confirmed is not None and _succeeded(confirmed):
            gw.handled.append(confirmed)
            step = StepResult(
                "saved",
                text=confirmed.reply_text,
                workflow_key=step.workflow_key,
                summary=_saved_summary(confirmed, getattr(gw.actor, "timezone", None)),
            )
        else:
            step = StepResult("error", text=getattr(confirmed, "reply_text", "") or step.text)
    if step.status != "saved":
        if gw.abandon_question is not None:
            with contextlib.suppress(Exception):
                await gw.abandon_question()
        raise _Failed(item, _clean(step.text))
    await entry.remember(ready, correlation_id=gw.message.correlation_id)
    if gw.handled:
        await gw._remember_site(gw.handled[-1])
    fact = fact_of(gw.handled[-1]) if gw.handled else None
    return step, fact


async def save(gw: Any, draft: dr.MessageDraft) -> ReplySpec:
    """The Save tap: every ready item written in one transaction."""
    ready = draft.ready_items
    if not ready:
        return dr.card_reply(draft, dr.NOTHING_READY, site=_card_site(gw, draft)) if draft.live else ReplySpec(
            text=dr.NOTHING_READY
        )
    work = [i for i in ready if i.kind != dr.KIND_ACTION]
    actions = [i for i in ready if i.kind == dr.KIND_ACTION]
    waiting = draft.waiting_items
    gone = draft.unreadable_items
    transaction = gw.transaction or _no_transaction
    saved: list[tuple[dr.DraftItem, StepResult]] = []
    facts: list[tuple[str, uuid.UUID]] = []
    gw.handled = []
    try:
        async with transaction():
            if not await gw.drafts.claim(draft.id):
                return ReplySpec(text=dr.ALREADY_DONE)
            for item in work:
                step, fact = await _write(gw, item)
                saved.append((item, step))
                if fact is not None:
                    facts.append(fact)
            if facts and gw.settle_facts is not None:
                settled = await gw.settle_facts(facts)
                refused = list(getattr(settled, "refused", None) or [])
                if settled is None or refused:
                    raise _Failed(None, f"the entries could not be confirmed ({refused[0] if refused else 'not wired'})")
            if waiting:
                rest = dr.MessageDraft.new(
                    organization_id=draft.organization_id,
                    user_id=draft.user_id,
                    source_message_id=draft.source_message_id,
                )
                rest.items = list(waiting)
                rest.project_id, rest.site_id = draft.project_id, draft.site_id
                await gw.drafts.put(rest)
                draft_rest = rest
            else:
                draft_rest = None
    except _Failed as failed:
        gw.handled = []
        return await _failed_reply(gw, draft, failed)
    except Exception:  # noqa: BLE001 -- nothing was written; the card stays as it was
        _log.exception("agent.draft_save_failed draft=%s", draft.id)
        gw.handled = []
        return ReplySpec(text="Nothing was saved: something went wrong on our side. Please tap Save again.")

    _log.info(
        "draft.saved draft=%s written=%s actions=%s left=%s unreadable=%s",
        draft.id, len(saved), len(actions), len(waiting), len(gone),
    )
    lines = [step.summary or item.summary for item, step in saved]
    notes = [n for n in (_note(step) for _item, step in saved) if n]
    await _remember_saved(gw, saved, facts)
    ran: list[str] = []
    for item in actions:
        ran.append(await _run_action(gw, item))
    gw.draft = draft_rest
    return _saved_reply(gw, draft, lines + [r for r in ran if r], notes, draft_rest, gone)


def _note(step: StepResult) -> str:
    from .toolbox import _without_recorded

    return _without_recorded(step.text)


async def _run_action(gw: Any, item: dr.DraftItem) -> str:
    from .actions import GONE_LINE

    if gw.actions is None:
        return GONE_LINE
    waiting = await gw.actions.store.take(gw.actor, item.action_id)
    if waiting is None:
        return GONE_LINE
    return await gw.actions.run(waiting, gw.actor, gw.sender)


async def _remember_saved(gw: Any, saved: list[tuple[dr.DraftItem, StepResult]], facts: list[Any]) -> None:
    """Keep the saved card where "undo that" looks for it (runtime/agent/cards.py),
    so an undo after the Save works as it did."""
    if gw.cards is None or gw.actor is None or not facts:
        return
    items = []
    for (item, step), fact in zip(saved, facts, strict=False):
        items.append(CardItem(item.tool, dict(item.args), fact[0], str(fact[1]), step.summary or item.summary))
    try:
        await gw.cards.put(gw.actor, new_card(CARD_SAVED, items))
    except Exception:  # noqa: BLE001 -- the card only enables undo
        _log.warning("agent.draft_card_remember_failed", exc_info=True)


def _saved_reply(
    gw: Any,
    draft: dr.MessageDraft,
    lines: list[str],
    notes: list[str],
    rest: dr.MessageDraft | None,
    gone: list[dr.DraftItem],
) -> ReplySpec:
    site = _card_site(gw, draft)
    what = "; ".join(line for line in lines if line)
    if rest is None:
        head = f"{SAVED_DONE[:-1]} · {site}: {what}" if site else f"{SAVED_DONE[:-1]}: {what}"
        if not what:
            head = SAVED_DONE
    else:
        needs = "; ".join(i.line for i in rest.items if i.line)
        head = f"{SAVED_DONE[:-1]} {len(lines)} · still need: {needs}"
    parts = [head, *notes]
    if gone:
        parts.append(dr.CANT_READ + "; ".join(i.label or i.summary or i.tool for i in gone) + ". Send it again.")
    text = "\n".join(p for p in parts if p)
    if rest is not None:
        return dr.card_reply(rest, text, site=_card_site(gw, rest))
    return ReplySpec(text=text)


async def _failed_reply(gw: Any, draft: dr.MessageDraft, failed: _Failed) -> ReplySpec:
    """Nothing was written. The item that failed stays on the card, marked, so
    the rest can still be saved or the card cancelled."""
    item = failed.item
    _log.warning(
        "draft.save_failed draft=%s kind=%s reason=%s", draft.id, item.kind if item is not None else "-", failed.reason
    )
    if item is not None:
        item.state, item.reason = dr.UNREADABLE, failed.reason
        item.label = item.summary or item.label
    _keep(gw, draft)
    await _persist(gw, draft)
    what = f" Couldn't save {item.label}: {failed.reason}." if item is not None else f" {failed.reason}."
    words = f"Nothing was saved.{what} It is marked on the card; tap Save to save the rest, or Cancel."
    return dr.card_reply(draft, words, site=_card_site(gw, draft))
