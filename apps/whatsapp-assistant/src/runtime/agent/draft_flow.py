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
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

from canonicalization.occurred_date import today_for
from channel.receipt.data import company_zone
from channel.replies import ListRow, ReplySpec
from mesiri_contracts.assistant.v2.canonical_event import CanonicalEventV2
from mesiri_contracts.assistant.v2.planner_decision import PlannerDecisionV2
from runtime.day_facts import PROGRESS_UPDATE
from workflows import WorkflowRunStatus

from . import draft as dr
from . import draft_site
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


def _many_sites(gw: Any) -> bool:
    return len(getattr(gw.actor, "sites", None) or []) > 1


def _site_name(gw: Any, site_id: Any) -> str:
    """The line's site, for every sender: a card and a saved line always say
    where (a sender with one site too; only "Change site" needs several)."""
    if not site_id:
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
        many_sites=_many_sites(gw),
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


def _message(gw: Any, text: str) -> Any:
    """The inbound message carrying the sender's words, as the entries read it."""
    update: dict[str, Any] = {"text": text}
    from mesiri_contracts.assistant.enums import InputModality

    if gw.message.modality not in (InputModality.IMAGE, InputModality.DOCUMENT):
        update["modality"] = InputModality.TEXT
    return gw.message.model_copy(update=update)


#: What an answer fills in when the question is about WHERE (the site queue of
#: [111] holds those calls): no line of the card waits for them.
_SCOPE_QUESTIONS = ("site", "project", "to_site")

#: The one note when an old-style Yes / No question is still waiting while the
#: sender's message went onto a draft card (request 127).
PENDING_YES_NO = (
    "Note: you still have a Yes / No question waiting above. Answer it first; a card cannot be saved while it waits."
)
#: The same, in the language of the sender's message (request 129: second person, not "of theirs").
_PENDING_YES_NO_IN = {
    "manglish": (
        "Note: mukalil oru Yes / No question baakiyundu. Aadyam athinu answer cheyyuka; athu theerunnath vare "
        "ee card save cheyyaan pattilla."
    ),
    "malayalam": (
        "ശ്രദ്ധിക്കുക: മുകളിൽ ഒരു Yes / No ചോദ്യം ബാക്കിയുണ്ട്. ആദ്യം അതിന് ഉത്തരം നൽകൂ; "
        "അത് തീരുന്നതുവരെ ഈ കാർഡ് സേവ് ചെയ്യാൻ കഴിയില്ല."
    ),
    "hindi": (
        "ध्यान दें: ऊपर आपका एक Yes / No सवाल बाकी है। पहले उसका जवाब दें; जब तक वह बाकी है, यह कार्ड सेव नहीं हो सकता।"
    ),
}


async def _pending_note(gw: Any) -> str:
    """``PENDING_YES_NO`` when a workflow still waits for its Yes / No (a team
    member to add, an expense...): the new card is not made silently beside it."""
    if gw.pending_confirmation is None:
        return ""
    try:
        if not await gw.pending_confirmation():
            return ""
        from .work_site import _language_of

        return _PENDING_YES_NO_IN.get(_language_of(getattr(gw.message, "text", None)), PENDING_YES_NO)
    except Exception:  # noqa: BLE001 -- the note is wording only
        _log.warning("draft.pending_check_failed", exc_info=True)
        return ""


async def add(gw: Any, candidate: Any, *, text: str) -> StepResult:
    tool, args = gw.current_call or ("", {})
    message = _message(gw, text)
    entry = gw._entry_for(getattr(candidate, "semantic_type", None))
    if entry is None:
        await note_lost(gw, tool, args, "that can't be done here yet")
        return StepResult("error", text="Not saved: that can't be done here yet.")
    decided(gw, "item", ITEM_FROM_TOOL, tool)
    # Request 136: THE site resolver decides the line's site before the entry runs, so
    # the entry's own fallbacks (today's site, the context layer's default) never do.
    choice = None if tool in dr.SITELESS_TOOLS else await _resolve_site(gw, args, text)
    if choice is not None and choice.kind == draft_site.ASK:
        return await _add_waiting(gw, tool, args, _site_question(gw, message, choice))
    if choice is not None:
        args = {**args, "site": draft_site.label(gw.actor, choice.site)}
    candidate = to_candidate(tool, args, _scope(gw)) or candidate
    prepared = await entry.prepare(message, tool_understanding(candidate, message, language=gw.language), candidate)
    if prepared is None:
        await note_lost(gw, tool, args, "it could not be looked up")
        return StepResult("error", text="Not saved: the system could not look this up just now. Send it again.")
    if _asks_where(prepared):
        # The entry could not place the site the resolver gave (no longer theirs):
        # "which site?" is a question of the card (WA-81), never of a separate queue.
        return await _add_waiting(gw, tool, args, prepared)
    if choice is not None and isinstance(prepared, Ready) and str(prepared.event.site_id or "") != str(choice.site.id):
        _log.warning(
            "draft.site_mismatch decided=%s entry=%s correlation_id=%s",
            choice.site.id, prepared.event.site_id, getattr(gw.message, "correlation_id", None),
        )
    if isinstance(prepared, Say):
        from .toolbox import question_reply

        if prepared.status == "error":
            await note_lost(gw, tool, args, prepared.text)
        elif prepared.question and prepared.awaiting and prepared.awaiting not in _SCOPE_QUESTIONS:
            # A line of the card with its question and the answers as buttons.
            return await _add_waiting(gw, tool, args, prepared)
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
    if draft is not None and (waiting := dr.waiting_for(draft, item)) is not None:
        # Its question was answered: the line that waited on it becomes this one.
        draft.items[draft.items.index(waiting)] = item
        gw.draft_new.append(item.id)
        _keep(gw, draft)
        await _persist(gw, draft)
        return _drafted(item, prepared, note=await _pending_note(gw))

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
            return _drafted(item, prepared, note=await _pending_note(gw))
    if draft is not None:
        if (same := dr.duplicate_of(draft, item)) is not None:
            return _drafted(same, prepared, repeated=True)
        if (older := dr.same_work(draft, item)) is not None and older.id not in gw.draft_new:
            # WA-82: a new figure for the same work and place replaces its line.
            draft.items[draft.items.index(older)] = item
            gw.draft_new.append(item.id)
            _keep(gw, draft)
            await _persist(gw, draft)
            return _drafted(item, prepared, note=await _pending_note(gw))
        if draft.full:
            await note_lost(gw, tool, args, "the card is full")
            return StepResult("error", text=TOO_MANY)
    await _add_item(gw, item, source=message.message_id)
    return _drafted(item, prepared, note=await _pending_note(gw))


#: Request 136 (C): a line made from a save tool call (the model's extraction, or the
#: code's own call from the message's words: ``runner._problem_part`` and the like).
ITEM_FROM_TOOL = "tool_call"


def decided(gw: Any, what: str, by: str, kind: str = "") -> None:
    """Request 136 (C): note which component decided ``what`` (the site, the items,
    the reply) this turn; the journey writes the list as the "draft_decisions" stage."""
    decisions = getattr(gw, "decisions", None)
    if isinstance(decisions, list):
        decisions.append({"what": what, "by": by, **({"kind": kind} if kind else {})})


def _card_site_id(draft: dr.MessageDraft | None) -> str | None:
    ids = {i.site_id for i in (draft.items if draft else []) if i.state != dr.UNREADABLE and i.site_id}
    return next(iter(ids)) if len(ids) == 1 else None


async def _resolve_site(gw: Any, args: dict[str, Any], text: str) -> draft_site.SiteChoice:
    """The line's site by ``draft_site.resolve``: the one site, the one the call or
    the message names, the open card's, the one saved to in the window, else ask."""
    saved = None
    if getattr(gw, "get_today_site", None) is not None:
        try:
            saved = await gw.get_today_site()
        except Exception:  # noqa: BLE001 -- without it the card asks
            _log.warning("draft.saved_site_unreadable", exc_info=True)
    project = str(args.get("project") or "").strip()
    choice = draft_site.resolve(
        gw.actor,
        text,
        said=str(args.get("site") or ""),
        project_id=_scope(gw).project_id(project) if project else None,
        card_site_id=_card_site_id(await load(gw)),
        saved_site_id=saved,
    )
    decided(gw, "site", draft_site.DECIDER, choice.kind)
    return choice


def _site_question(gw: Any, message: Any, choice: draft_site.SiteChoice) -> Say:
    """The card's "which site?" with the sites the resolver left to choose from."""
    from .entry_base import choose, site_words
    from .site_match import options

    projects = {str(p.id): p.name for p in getattr(gw.actor, "projects", None) or []}
    labels, _cut = options(list(choice.options), projects, choice.unknown)
    if choice.unknown:
        question = site_words(message, "no_site", said=choice.unknown)
    else:
        question = site_words(message, "site_q")
    return choose(question, labels, "site")


def _asks_where(prepared: Any) -> bool:
    return isinstance(prepared, Say) and bool(prepared.question) and prepared.awaiting in dr.WHERE_QUESTIONS


def _bare(args: dict[str, Any]) -> dict[str, Any]:
    """A call's arguments without where it is for: the same call asked again after
    its site was answered is the same line, not a second one (live 27 Oct: the
    steel line was shown twice)."""
    return {k: v for k, v in args.items() if k not in ("site", "project")}


def _place(gw: Any, item: dr.DraftItem) -> None:
    """The line's site, from the site its arguments name (one of the sender's)."""
    name = str(item.args.get("site") or "").strip()
    if not name or item.site_id:
        return
    site_id = _scope(gw).site_id(name)
    if site_id:
        item.site_id, item.site, item.many_sites = site_id, _site_name(gw, site_id), _many_sites(gw)


async def _add_waiting(gw: Any, tool: str, args: dict[str, Any], asked: Say) -> StepResult:
    """The system asked something before this call could become a line (a unit,
    which material, add it as new?): it is a line of the card all the same, with
    the question beside it and the answers as the card's buttons. A tap answers
    it (``answer``); a typed answer reaches the same tool again and the line
    becomes the entry (``dr.waiting_for``). Asked again, it is the same line."""
    draft = await load(gw)
    item = dr.DraftItem(
        kind=dr.KIND_BY_TOOL[tool],
        tool=tool,
        args=dict(args),
        summary=dr.waiting_line(tool, args),
        state=dr.NEEDS_ANSWER,
        question=" ".join(str(asked.question or "").split()),
        options=[str(o) for o in asked.options],
        label=dr.label_for(tool, args),
        awaiting=asked.awaiting,
        answer_unit=asked.answer_unit,
    )
    _place(gw, item)
    same = (
        next((i for i in draft.items if i.pending_answer and i.tool == tool and _bare(i.args) == _bare(item.args)), None)
        if draft
        else None
    )
    if same is not None:
        same.question, same.options, same.awaiting = item.question, item.options, item.awaiting
        same.answer_unit = item.answer_unit or same.answer_unit
        if item.args.get("site") and not same.args.get("site"):
            same.args, same.site_id, same.site, same.many_sites = item.args, item.site_id, item.site, item.many_sites
        item = same
        gw.draft_new.append(same.id)
        _keep(gw, draft)
        await _persist(gw, draft)
    elif draft is not None and draft.full:
        await note_lost(gw, tool, args, "the card is full")
        return StepResult("error", text=TOO_MANY)
    else:
        await _add_item(gw, item, source=gw.message.message_id)
    hint = (
        "It is on their card; the card asks which site with buttons. Do not ask it yourself."
        if item.needs_site
        else asked.text
    )
    return StepResult(
        "drafted",
        text=await _pending_note(gw),
        summary=item.line,
        awaiting="answer",
        hint=hint,
    )


def _drafted(item: dr.DraftItem, prepared: Ready, *, repeated: bool = False, note: str = "") -> StepResult:
    key = getattr(prepared.decision.workflow_key, "value", None)
    return StepResult(
        "drafted",
        text="already on the card" if repeated else note,
        workflow_key=key,
        summary=item.summary or item.label,
        awaiting="answer" if item.state == dr.NEEDS_ANSWER else "",
        reply=ReplySpec(text=item.question) if item.state == dr.NEEDS_ANSWER else None,
    )


async def add_action(gw: Any, tool: str, args: dict[str, Any], prepared: list[Any]) -> None:
    """The pending actions a tool call made (their store holds what the Save
    tap runs): one card line each, so the one Save tap covers them too."""
    for action in prepared:
        # Request 142 (E): "Close: Mixer ippo work · Green Villa" -- what it does, and where.
        summary = action.summary.replace("To close: ", "Close: ", 1)
        site_id = str((action.payload or {}).get("site_id") or "")
        item = dr.DraftItem(
            kind=dr.KIND_ACTION,
            tool=tool,
            args=dict(args),
            summary=summary,
            action_id=uuid.UUID(action.id).hex,
            label=summary,
            site_id=site_id,
            site=_site_name(gw, site_id),
        )
        await _add_item(gw, item, source=gw.message.message_id)


# -- corrections (request 127, P2) --------------------------------------------------


def _as_change(
    gw: Any, item: dr.DraftItem, *, target: dict[str, Any], old_args: dict[str, Any], old_summary: str, day: str
) -> dr.DraftItem:
    """``item`` (a prepared entry for the corrected figures) as the correction of
    the saved entry ``target``: it asks nothing (a correction is the sender's
    explicit replacement) and, written on Save, takes the saved one back first."""
    item.kind = dr.KIND_CHANGE
    item.target = {**target, "old_args": dict(old_args), "old_summary": old_summary, "day": day}
    item.state, item.question, item.options = dr.OK, "", []
    ready = dict(item.ready or {})
    event = dict(ready.get("event") or {})
    # The day's earlier count is what this replaces: it must not read as "already counted".
    event["fields"] = {**(event.get("fields") or {}), "day_counted_lines": []}
    item.ready = {**ready, "event": event}
    from .work_site import short_site_label

    site = (short_site_label(gw.actor, item.site_id) if item.site_id else "") or ""
    item.summary = dr.change_line(
        item.tool, old_args, item.args, old_summary=old_summary, new_summary=item.summary, site=site, day=day
    )
    return item


async def _prepare_changed(gw: Any, tool: str, merged: dict[str, Any], candidate: Any, text: str) -> Ready | StepResult:
    """The corrected figures, prepared as any entry is (the same lookups and
    checks), or the StepResult that says why nothing changed."""
    entry = gw._entry_for(getattr(candidate, "semantic_type", None))
    if entry is None:
        return StepResult("error", text="That can't be changed here, so nothing was changed.")
    message = _message(gw, text)
    prepared = await entry.prepare(message, tool_understanding(candidate, message, language=gw.language), candidate)
    if prepared is None:
        return StepResult("error", text="The system could not look this up just now, so nothing was changed.")
    if isinstance(prepared, Say):
        from .toolbox import question_reply

        reply = (
            question_reply(prepared.question, list(prepared.options), awaiting=prepared.awaiting)
            if prepared.question
            else None
        )
        return StepResult(prepared.status, text=prepared.text, reply=reply, awaiting=prepared.awaiting)
    return prepared


async def edit_item(
    gw: Any, draft: dr.MessageDraft, item: dr.DraftItem, changes: dict[str, Any], *, text: str
) -> StepResult:
    """A correction on the open card ("alla, 5 mason aanu" before Save): the
    line is redone with the changed figures, in place, and the card is shown
    again. Nothing is written either way. A change is claimed only when this
    says so."""
    merged = merge_changes(item.tool, item.args, changes)
    if merged == item.args:
        return StepResult("info", text="That is already how it is on the card, so nothing was changed.")
    candidate = to_candidate(item.tool, merged, _scope(gw))
    if candidate is None:
        return StepResult("error", text="That item cannot be changed here, so nothing was changed.")
    prepared = await _prepare_changed(gw, item.tool, merged, candidate, text)
    if isinstance(prepared, StepResult):
        return prepared
    new = _item_for(gw, item.tool, merged, prepared)
    if new.state == dr.UNREADABLE:
        return StepResult("error", text=f"Couldn't read it: {new.label}. The card is as it was.")
    if item.kind == dr.KIND_CHANGE and item.target:
        target = item.target
        new = _as_change(
            gw, new, target=target, old_args=dict(target.get("old_args") or {}),
            old_summary=str(target.get("old_summary") or ""), day=str(target.get("day") or "today"),
        )
    draft.items[draft.items.index(item)] = new
    gw.draft_new.append(new.id)
    _keep(gw, draft)
    await _persist(gw, draft)
    _log.info("draft.item_edited draft=%s kind=%s state=%s", draft.id, new.kind, new.state)
    return replace(_drafted(new, prepared, note=await _pending_note(gw)), changed=True)


async def change_saved(gw: Any, card_item: CardItem, changes: dict[str, Any], *, text: str) -> StepResult:
    """A correction on an entry that is already saved: a new item on the open
    card (made if there is none), "Change today's labour at Green Villa: mason
    6 → 5 (total 7)", saved by tap like anything else. Until then the saved
    entry stands. A second correction of the same entry edits that item."""
    draft = await load(gw)
    existing = dr.change_for(draft, card_item.fact_id) if draft is not None else None
    if existing is not None:
        # Corrections add up: the second one starts from the first's figures.
        return await edit_item(gw, draft, existing, changes, text=text)
    base = dict(card_item.args)
    merged = merge_changes(card_item.tool, base, changes)
    if merged == base:
        return StepResult("info", text="That is already how it is saved, so nothing was changed.")
    candidate = to_candidate(card_item.tool, merged, _scope(gw))
    if candidate is None:
        return StepResult("error", text="That item cannot be changed here, so nothing was changed.")
    prepared = await _prepare_changed(gw, card_item.tool, merged, candidate, text)
    if isinstance(prepared, StepResult):
        return prepared
    _not_continuing_replaced(prepared, card_item)
    item = _item_for(gw, card_item.tool, merged, prepared)
    if item.state == dr.UNREADABLE:
        return StepResult("error", text=f"Couldn't read it: {item.label}. Nothing was changed.")
    item = _as_change(
        gw, item,
        target={"fact_type": card_item.fact_type, "fact_id": card_item.fact_id},
        old_args=base, old_summary=card_item.summary, day=card_item.day,
    )
    if draft is not None and draft.full:
        await note_lost(gw, card_item.tool, merged, "the card is full")
        return StepResult("error", text=TOO_MANY)
    await _add_item(gw, item, source=gw.message.message_id)
    return replace(_drafted(item, prepared, note=await _pending_note(gw)), changed=True)


def _not_continuing_replaced(prepared: Ready, card_item: CardItem) -> None:
    """Request 137: a correction of the activity itself (its first entry) takes that
    activity back on Save, so the corrected entry must not continue it: it was
    found as open work while preparing, before the take-back (the corrected
    amount was written onto the removed activity)."""
    if card_item.fact_type != "activity":
        return
    fields = prepared.event.fields
    replaced = str(card_item.fact_id)
    if str(fields.get("activity_id") or "") == replaced:
        fields.pop("activity_id", None)
        fields.pop("activity_summary", None)
    candidates = fields.get("_open_activity_candidates")
    if isinstance(candidates, list):
        fields["_open_activity_candidates"] = [c for c in candidates if str(c.get("activity_id")) != replaced]


async def saved_work_today(gw: Any) -> list[Any]:
    """The sender's own saved work facts of their project's today (Day Facts)."""
    day = _today(gw)
    if gw.day_facts is None or gw.actor is None or day is None:
        return []
    try:
        return await gw.day_facts.work(
            organization_id=str(gw.actor.organization_id), start=day, end=day,
            reported_by_user_id=str(gw.actor.user_id),
        )
    except Exception:  # noqa: BLE001 -- a correction then resolves against the saved card only
        _log.warning("agent.day_facts_failed", exc_info=True)
        return []


async def saved_card(gw: Any) -> Any | None:
    """The sender's latest card when it is saved (what a correction targets)."""
    if gw.cards is None or gw.actor is None:
        return None
    card = await gw.cards.get(gw.actor)
    return card if card is not None and card.state == CARD_SAVED and card.items else None


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
    if item is not None and item.pending_answer and 0 <= choice < len(item.options):
        return await _answer_waiting(gw, draft, item, item.options[choice])
    if item is None or not dr.apply_answer(item, choice, today=_today(gw)):
        return ReplySpec(text=dr.ALREADY_DONE)
    await gw.drafts.put(draft)
    return dr.card_reply(draft, site=_card_site(gw, draft))


#: The answers a tap cannot give: the sender types them.
_TYPE_IT = {"Other": "Please type the number.", "Something else": "Please type the material name."}


async def _answer_waiting(gw: Any, draft: dr.MessageDraft, item: dr.DraftItem, option: str) -> ReplySpec:
    """A tap on the question of a waiting line: the answer is put into the
    line's own tool arguments (a unit conversion is set for the company first,
    as the typed answer does) and the entry is prepared again, with every check
    it runs. Ready: the line becomes the entry. Asked again: the new question
    replaces the old. Nothing is written to a domain table here."""
    from .material_entry import ADD_IT, AWAIT_NEW_MATERIAL, AWAIT_UNIT
    from .toolbox import per_stock_unit

    site = _card_site(gw, draft)
    if option in _TYPE_IT:
        return dr.card_reply(draft, _TYPE_IT[option], site=site)
    if item.needs_site:
        return await _answer_where(gw, draft, item.awaiting, option)
    args = dict(item.args)
    if item.awaiting == AWAIT_NEW_MATERIAL:
        if option != ADD_IT:
            draft.items.remove(item)
            if draft.live:
                await gw.drafts.put(draft)
            else:
                await gw.drafts.discard(draft.id)
            words = f"Okay, {item.line} is off the card. Send it again with a material from your list."
            return dr.card_reply(draft, words, site=site) if draft.live else ReplySpec(text=words)
        args["new_material"] = True
    elif item.awaiting == AWAIT_UNIT:
        # "1 load = how many cum?" answered 3: one cum is a third of a load.
        count = per_stock_unit({"unit_amount": 1, "stock_amount": option})
        if count is None:
            return dr.card_reply(draft, _TYPE_IT["Other"], site=site)
        said = await gw.set_unit_conversion(
            material=str(args.get("material") or ""), unit=str(args.get("unit") or ""), count=count
        )
        if said.status != "answer":
            return dr.card_reply(draft, said.text, site=site)
    else:
        args[item.awaiting] = option
    candidate = to_candidate(item.tool, args, _scope(gw))
    entry = gw._entry_for(getattr(candidate, "semantic_type", None)) if candidate is not None else None
    if entry is None:
        return dr.card_reply(draft, "That can't be answered here; send it again.", site=site)
    message = _message(gw, gw.message.text or option)
    prepared = await entry.prepare(message, tool_understanding(candidate, message, language=gw.language), candidate)
    if isinstance(prepared, Ready):
        new = _item_for(gw, item.tool, args, prepared)
    elif isinstance(prepared, Say) and prepared.question and prepared.awaiting not in _SCOPE_QUESTIONS:
        item.args = args
        item.question = " ".join(str(prepared.question).split())
        item.options, item.awaiting = [str(o) for o in prepared.options], prepared.awaiting
        new = item
    else:
        reason = prepared.text if isinstance(prepared, Say) else "it could not be looked up"
        new = _unreadable(item.tool, args, _clean(reason))
    draft.items[draft.items.index(item)] = new
    await _persist(gw, draft)
    _log.info("draft.waiting_answered draft=%s kind=%s state=%s", draft.id, new.kind, new.state)
    return dr.card_reply(draft, site=site)


async def _prepare_line(gw: Any, item: dr.DraftItem, args: dict[str, Any]) -> dr.DraftItem:
    """``item`` prepared again with ``args``: the entry, a line still waiting on a
    question, or unreadable with the reason. Nothing is written."""
    candidate = to_candidate(item.tool, args, _scope(gw))
    entry = gw._entry_for(getattr(candidate, "semantic_type", None)) if candidate is not None else None
    if entry is None:
        return _unreadable(item.tool, args, "that can't be answered here; send it again")
    message = _message(gw, item.label or item.tool)
    prepared = await entry.prepare(message, tool_understanding(candidate, message, language=gw.language), candidate)
    if isinstance(prepared, Ready):
        return _item_for(gw, item.tool, args, prepared)
    if isinstance(prepared, Say) and prepared.question and prepared.awaiting not in _SCOPE_QUESTIONS:
        waiting = replace(
            item,
            args=args,
            question=" ".join(str(prepared.question).split()),
            options=[str(o) for o in prepared.options],
            awaiting=prepared.awaiting,
            answer_unit=prepared.answer_unit,
            site_id="",
            site="",
        )
        _place(gw, waiting)
        return waiting
    reason = prepared.text if isinstance(prepared, Say) else "it could not be looked up"
    return _unreadable(item.tool, args, _clean(reason))


def _labour_line_for(draft: dr.MessageDraft, new: dr.DraftItem, skip: dr.DraftItem) -> dr.DraftItem | None:
    """The card's labour line for the same site and day as ``new`` (a labour line
    that has just got its site), which it joins, as ``add`` merges a later count."""
    if new.kind != dr.KIND_LABOUR or not new.ready or new.pending_answer:
        return None
    return next(
        (
            o
            for o in draft.items
            if o is not skip and o.kind == dr.KIND_LABOUR and o.ready and not o.pending_answer
            and o.site_id == new.site_id and dr._day(o) == dr._day(new)
        ),
        None,
    )


async def _answer_where(gw: Any, draft: dr.MessageDraft, awaiting: str, option: str) -> ReplySpec:
    """WA-81: the answer to the card's "which site?" (a tap, or the site's name
    typed): EVERY line waiting for it is prepared again for that site, in order.
    Labour joins the card's labour line of that site and day. Nothing is written."""
    waiting = [i for i in draft.items if i.needs_site and i.awaiting == awaiting]
    for item in waiting:
        new = await _prepare_line(gw, item, {**item.args, awaiting: option})
        old = _labour_line_for(draft, new, item)
        if old is not None:
            draft.items[draft.items.index(old)] = await _prepare_line(gw, old, merge_changes(old.tool, old.args, new.args))
            draft.items.remove(item)
            continue
        draft.items[draft.items.index(item)] = new
    await _persist(gw, draft)
    _log.info("draft.site_answered draft=%s lines=%s", draft.id, len(waiting))
    return dr.card_reply(draft, site=_card_site(gw, draft))


async def answer_typed(gw: Any, draft: dr.MessageDraft, text: str) -> ReplySpec | None:
    """WA-81: a typed answer to a question on the open card, read by code before the
    model runs: the site's name for "which site?", the amount for "How many kg is 20
    rod?" ("oru rod 12 kg", "240 kg"). None when the message is not such an answer
    (then the model reads it as usual)."""
    from . import draft_answer

    where = next((i for i in draft.items if i.needs_site), None)
    if where is not None:
        picked = draft_answer.site_answer(gw.actor, text, where.options)
        if picked is not None:
            return await _answer_where(gw, draft, where.awaiting, picked)
    from .material_entry import AWAIT_AMOUNT

    for item in [i for i in draft.items if i.pending_answer and i.awaiting == AWAIT_AMOUNT]:
        amount = draft_answer.amount_answer(text, item.args, item.answer_unit)
        if amount is None:
            continue
        plain = int(amount) if amount == amount.to_integral_value() else float(amount)
        new = await _prepare_line(gw, item, {**item.args, "quantity": plain, "unit": item.answer_unit})
        draft.items[draft.items.index(item)] = new
        await _persist(gw, draft)
        _log.info("draft.amount_answered draft=%s state=%s", draft.id, new.state)
        asked = draft_answer._number(str(item.args.get("quantity") or ""))
        shown = lambda n: format(n.normalize(), "f")  # noqa: E731 -- 20.0 -> "20", 2.4E+2 -> "240"
        said = f"{shown(asked)} {item.args.get('unit')} = {shown(amount)} {item.answer_unit}." if asked is not None else ""
        return dr.card_reply(draft, said if new.state == dr.OK else "", site=_card_site(gw, draft))
    return None


# -- change site (request 129) --------------------------------------------------------

#: WhatsApp lists hold ten rows.
_SITE_ROWS = 10


def change_site_list(gw: Any, draft: dr.MessageDraft) -> ReplySpec:
    """The "📍 Change site" tap: the sender's sites as a list. A pick moves every
    item of the card (``move_site``)."""
    from .site_match import labelled
    from .work_site import _DESC_MAX, _TITLE_MAX, _cut, _project_names, _sites

    current = {i.site for i in dr.movable_items(draft)}  # by label: the card's own words for a site
    sites = _sites(gw.actor)
    projects = _project_names(gw.actor)
    rows = [
        ListRow(
            dr.tap_id(dr.MOVE_SITE, draft.id, str(site.id)),
            _cut(label, _TITLE_MAX),
            _cut(projects.get(str(site.project_id or ""), ""), _DESC_MAX),
        )
        for site, label in labelled(sites, projects)
        if not (len(current) == 1 and label in current)
    ][:_SITE_ROWS]
    if not rows:
        return dr.card_reply(draft, "You have no other site to move this to.", site=_card_site(gw, draft))
    return ReplySpec(
        text="Which site is this card for? Everything on it moves there.",
        list_button_label="Choose site",
        list_rows=tuple(rows),
    )


async def move_site(gw: Any, draft: dr.MessageDraft, site_id: str) -> ReplySpec:
    """Every item of the card is prepared again for ``site_id`` (the same
    lookups and checks as when it was added: the day's labour count, for one,
    is that site's). All or none: an item that cannot be moved leaves the card
    as it was, and the reply says which. Nothing is written."""
    from .work_site import _project_names, _sites

    site = next((s for s in _sites(gw.actor) if str(s.id) == str(site_id)), None)
    if site is None:
        return dr.card_reply(draft, "That site isn't one of yours.", site=_card_site(gw, draft))
    movable = dr.movable_items(draft)
    if not movable or all(i.site == _site_name(gw, site.id) for i in movable):
        return dr.card_reply(draft, f"It is already for {site.name}.", site=_card_site(gw, draft))
    project = _project_names(gw.actor).get(str(site.project_id or ""), "")
    redone: list[tuple[dr.DraftItem, dr.DraftItem]] = []
    for item in movable:
        args = {**item.args, "site": site.name, **({"project": project} if project else {})}
        candidate = to_candidate(item.tool, args, _scope(gw))
        entry = gw._entry_for(getattr(candidate, "semantic_type", None)) if candidate is not None else None
        if entry is None:
            return dr.card_reply(draft, f"Couldn't move {item.label}: nothing was changed.", site=_card_site(gw, draft))
        message = _message(gw, item.label or item.tool)
        prepared = await entry.prepare(message, tool_understanding(candidate, message, language=gw.language), candidate)
        if not isinstance(prepared, Ready):
            why = _clean(prepared.text) if isinstance(prepared, Say) else "it could not be looked up"
            return dr.card_reply(
                draft, f"Couldn't move {item.label} to {site.name}: {why}. Nothing was changed.", site=_card_site(gw, draft)
            )
        new = _item_for(gw, item.tool, args, prepared)
        if new.state == dr.UNREADABLE or new.site != _site_name(gw, site.id):
            return dr.card_reply(
                draft, f"Couldn't move {item.label} to {site.name}. Nothing was changed.", site=_card_site(gw, draft)
            )
        redone.append((item, new))
    for old, new in redone:
        draft.items[draft.items.index(old)] = new
    await _persist(gw, draft)
    _log.info("draft.site_changed draft=%s items=%s site=%s", draft.id, len(redone), site.id)
    return dr.card_reply(draft, f"📍 Moved to {site.name}.", site=_card_site(gw, draft))


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
    if item.kind == dr.KIND_CHANGE:
        await _take_back(gw, item)
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
    if fact is None and gw.handled:
        fact = await _continued_fact(gw, gw.handled[-1])
    return step, fact


async def _settle_continued(gw: Any, facts: list[tuple[str, uuid.UUID]]) -> None:
    """Request 137 (F2): work continued on the sender's own activity that is still a
    draft (saved first by the old flow, not confirmed yet) counts once this Save
    confirms it: readers count an update through its activity. Best effort: an
    activity that is not the sender's draft is left as it is (``already`` / refused)."""
    parents = [p for f in facts if f[0] == PROGRESS_UPDATE and (p := gw.continued.get(str(f[1]))) is not None]
    if not parents or gw.settle_facts is None:
        return
    settled = await gw.settle_facts([("activity", p) for p in dict.fromkeys(parents)])
    if refused := list(getattr(settled, "refused", None) or []):
        _log.info("draft.continued_parent_not_settled reasons=%s", refused)


async def _continued_fact(gw: Any, handled: Any) -> tuple[str, uuid.UUID] | None:
    """Request 137 (B): work continuing an open activity is confirmed by the Save
    (its Yes), not saved first, so the review log has no fact for it. Its own
    progress update is its fact, read in the Save's transaction: the card keeps it,
    and "undo" or a correction targets that update, not the whole activity."""
    from mesiri_contracts.assistant.draft_action import DraftActionType

    confirmed = getattr(getattr(handled, "result", None), "confirmed_action", None)
    draft = getattr(confirmed, "draft_action", None)
    if gw.day_facts is None or draft is None or draft.action_type is not DraftActionType.ADD_PROGRESS_UPDATE:
        return None
    activity_id = draft.fields.get("activity_id") or getattr(getattr(handled, "execution_result", None), "material_row_id", None)
    update_id = await gw.day_facts.latest_update(str(activity_id)) if activity_id else None
    try:
        fact = (PROGRESS_UPDATE, uuid.UUID(str(update_id))) if update_id else None
        if fact is not None:
            gw.continued[str(fact[1])] = uuid.UUID(str(activity_id))
        return fact
    except ValueError:
        return None


async def _take_back(gw: Any, item: dr.DraftItem) -> None:
    """The saved entry a correction replaces, taken back through its module's own
    undo (the same one "undo that" uses), inside the Save's transaction: if it
    cannot be taken back (its day was already confirmed) nothing is written."""
    target = item.target or {}
    try:
        fact = (str(target["fact_type"]), uuid.UUID(str(target["fact_id"])))
    except (KeyError, ValueError):
        raise _Failed(item, "the saved entry it changes is not known any more") from None
    if gw.undo_facts is None:
        raise _Failed(item, "that can't be changed here yet")
    undone = await gw.undo_facts([fact])
    if undone is None or fact not in set(getattr(undone, "done", None) or []):
        refused = list(getattr(undone, "refused", None) or [])
        already = int(getattr(undone, "already", 0) or 0)
        raise _Failed(
            item,
            _clean(refused[0]) if refused else "the saved entry was already removed" if already else "it could not be taken back",
        )


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
    #: One slot per saved item (request 137): work on an open activity records no
    #: fact, and pairing by position then shifted every later line onto the wrong fact.
    fact_of_item: list[tuple[str, uuid.UUID] | None] = []
    gw.handled = []
    try:
        async with transaction():
            if not await gw.drafts.claim(draft.id):
                return ReplySpec(text=dr.ALREADY_DONE)
            for item in work:
                step, fact = await _write(gw, item)
                saved.append((item, step))
                fact_of_item.append(fact)
                if fact is not None:
                    facts.append(fact)
            # A progress update has no review of its own: its activity's is confirmed.
            reviewed = [f for f in facts if f[0] != PROGRESS_UPDATE]
            if reviewed and gw.settle_facts is not None:
                settled = await gw.settle_facts(reviewed)
                refused = list(getattr(settled, "refused", None) or [])
                if settled is None or refused:
                    raise _Failed(None, f"the entries could not be confirmed ({refused[0] if refused else 'not wired'})")
            await _settle_continued(gw, facts)
            await _journal(gw, draft, saved, fact_of_item)
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
    await _remember_saved(gw, saved, fact_of_item)
    ran: list[str] = []
    for item in actions:
        ran.append(await _run_action(gw, item))
    gw.draft = draft_rest
    return _saved_reply(gw, draft, lines + [r for r in ran if r], notes, draft_rest, gone)


async def _journal(
    gw: Any,
    draft: dr.MessageDraft,
    saved: list[tuple[dr.DraftItem, StepResult]],
    facts: list[tuple[str, uuid.UUID] | None],
) -> None:
    """Request 142 (B): the one journal entry of this Save, written in the Save's
    transaction (company, sender, time, site, day, a reference to each fact)."""
    if getattr(gw, "journal", None) is None:
        return
    from . import journal as jr

    written = [
        jr.JournalFact(fact[0], str(fact[1]), item.tool, dict(item.args), step.summary or item.summary)
        for (item, step), fact in zip(saved, facts, strict=True)
        if fact is not None
    ]
    if not written:
        return
    first = next((i for i, f in zip((s[0] for s in saved), facts, strict=True) if f is not None), None)
    site_id = (first.site_id if first is not None else "") or draft.site_id or ""
    await gw.journal.record(
        jr.JournalEntry(
            organization_id=draft.organization_id,
            user_id=draft.user_id,
            facts=written,
            draft_id=draft.id,
            site_id=site_id,
            site=_site_name(gw, site_id) if site_id else "",
            day=(_day_of(first) if first is not None else "") or "",
        )
    )


def _day_of(item: dr.DraftItem) -> str:
    return dr._day(item) or ""


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


async def _remember_saved(
    gw: Any, saved: list[tuple[dr.DraftItem, StepResult]], facts: list[tuple[str, uuid.UUID] | None]
) -> None:
    """Keep the saved card where "undo that" looks for it (runtime/agent/cards.py),
    so an undo after the Save works as it did. ``facts`` has one slot per saved
    item (None where the write recorded no fact), so a line is never paired with
    another line's fact id."""
    if gw.cards is None or gw.actor is None or not any(f is not None for f in facts):
        return
    items = []
    for (item, step), fact in zip(saved, facts, strict=True):
        if fact is None:
            continue
        line = step.summary or item.summary
        items.append(CardItem(item.tool, dict(item.args), fact[0], str(fact[1]), line))
    try:
        kept: list[CardItem] = []
        if saved and all(i.kind == dr.KIND_CHANGE for i, _s in saved):
            # Only corrections: the rest of the card they correct still stands.
            old = await gw.cards.get(gw.actor)
            replaced = {str((i.target or {}).get("fact_id")) for i, _s in saved}
            if old is not None and old.state == CARD_SAVED:
                kept = [i for i in old.items if i.fact_id not in replaced]
        await gw.cards.put(gw.actor, new_card(CARD_SAVED, [*kept, *items]))
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
