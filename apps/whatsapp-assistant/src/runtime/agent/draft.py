"""One draft per open card, written only on the Save tap (request 124, P1;
docs/architecture/ADR-draft-per-message.md).

With a company's ``draft_v2`` setting on, the agent's save tools no longer start
a workflow and nothing is written when a message arrives. Each call ADDS an item
to the sender's one open draft; one card shows the whole draft; the Save tap
writes every ready item through the existing services in one transaction, and
Cancel throws the draft away -- so nothing was ever written, and the words say so.

This module is the draft itself and its card, with no I/O:

- ``DraftItem`` / ``MessageDraft``: typed items with a validation state
  (``ok`` | ``needs_answer`` | ``unreadable``), kept as JSON;
- the checks a workflow makes before it can save, as pure functions over the
  prepared event: the card line (``preview``) and the labour "replace or add?"
  question for a day that already has a count;
- the card text, its buttons and the tap ids (``agd:<action>:<draft id>``).

The store is ``draft_store.py``; adding and saving is ``journey_gateway.py``.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from types import SimpleNamespace
from typing import Any

from channel.replies import ListRow, ReplySpec
from interactions.saved_summary import render_saved, summarise_draft
from mesiri_contracts.assistant.draft_action import DraftActionType
from mesiri_contracts.assistant.planner_decision import WorkflowKey
from runtime.reply_composer import pick_form
from runtime.save_first import _headcount, _replaces
from trade_label import trade_label

from .cards import CARD_TTL_SECONDS
from .save_button import CANCEL_TITLE, SAVE_TITLE, TO_SAVE_HEADER
from .tools import (
    REPORT_ISSUE,
    SAVE_LABOUR,
    SAVE_MATERIAL_RECEIPT,
    SAVE_MATERIAL_USAGE,
    SAVE_WORK_DONE,
)

OK = "ok"
NEEDS_ANSWER = "needs_answer"
UNREADABLE = "unreadable"

OPEN = "open"
SAVED = "saved"
DISCARDED = "discarded"

#: As the card: the longest an open draft is kept without a new item (the
#: existing card expiry, runtime/agent/cards.py).
DRAFT_TTL_SECONDS = CARD_TTL_SECONDS
#: One tap holds this many entries today (save_button.MAX_ITEMS); the draft keeps it.
MAX_ITEMS = 7

TAP_PREFIX = "agd:"
SAVE = "save"
CANCEL = "cancel"
ANSWER = "ans"
#: Request 129: "📍 Change site" opens the sender's sites; a pick moves every
#: item of the card there.
CHANGE_SITE = "chsite"
MOVE_SITE = "chto"
CHANGE_SITE_TITLE = "📍 Change site"

KIND_LABOUR = "labour"
KIND_WORK = "work"
KIND_MATERIAL_IN = "material_in"
KIND_MATERIAL_OUT = "material_out"
KIND_ISSUE_OPEN = "issue_open"
#: A pending action of request 104 (engineer question, day's conditions, issues to
#: close): it keeps its own store, the draft holds its id and runs it on Save.
KIND_ACTION = "action"
#: A correction of something already saved (request 127, P2): the Save tap takes
#: the saved entry back and writes the corrected one, in the one transaction.
KIND_CHANGE = "change"

#: The tools that add to a draft, and what kind of item each makes.
KIND_BY_TOOL = {
    SAVE_LABOUR: KIND_LABOUR,
    SAVE_WORK_DONE: KIND_WORK,
    SAVE_MATERIAL_RECEIPT: KIND_MATERIAL_IN,
    SAVE_MATERIAL_USAGE: KIND_MATERIAL_OUT,
    REPORT_ISSUE: KIND_ISSUE_OPEN,
}
DRAFT_TOOLS = frozenset(KIND_BY_TOOL)

REPLACE = "Replace"
ADD = "Add"

CANT_READ = "Couldn't read: "
CANCELLED = "❌ Okay, nothing saved. Send it again whenever you're ready."
ALREADY_DONE = "That one is already done."
EXPIRED = "That card has expired. Please send it again."
NOTHING_READY = "Nothing on the card is ready to save yet. Answer the question on it, or send the missing detail."


@dataclass(slots=True)
class DraftItem:
    kind: str
    tool: str
    args: dict[str, Any]
    #: The card line, from the prepared data (what the Save will write).
    summary: str = ""
    state: str = OK
    question: str = ""
    options: list[str] = field(default_factory=list)
    #: The workflow's decision and event as the entry prepared them
    #: (``journey_gateway.ready_to_json``); None for a pending action.
    ready: dict[str, Any] | None = None
    #: ``unreadable`` only: why, in a few words.
    reason: str = ""
    #: What was said, for "Couldn't read: ..." when there is no summary.
    label: str = ""
    #: The site the entry is for (its id and short name), for a card of several.
    site_id: str = ""
    site: str = ""
    #: ``action`` only: the id of the pending action (runtime/agent/actions.py).
    action_id: str = ""
    #: A line waiting on a question (request 127): what its answer fills in
    #: (``material``, ``unit``, ``new_material``...), from the entry's ``Say``.
    awaiting: str = ""
    #: ``change`` only: the saved entry it replaces (``fact_type``, ``fact_id``
    #: of its card item, and its tool arguments as saved).
    target: dict[str, Any] | None = None
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

    @property
    def line(self) -> str:
        return self.summary or self.label

    @property
    def pending_answer(self) -> bool:
        """A line that waits on a question and cannot be saved or edited until
        it is answered (its tool is called again with the answer): no prepared
        event behind it, only what the answer fills in."""
        return self.state == NEEDS_ANSWER and self.ready is None and bool(self.awaiting)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, raw: Any) -> DraftItem | None:
        try:
            return cls(
                kind=str(raw["kind"]),
                tool=str(raw.get("tool") or ""),
                args=dict(raw.get("args") or {}),
                summary=str(raw.get("summary") or ""),
                state=str(raw.get("state") or OK),
                question=str(raw.get("question") or ""),
                options=[str(o) for o in raw.get("options") or []],
                ready=raw.get("ready") if isinstance(raw.get("ready"), dict) else None,
                reason=str(raw.get("reason") or ""),
                label=str(raw.get("label") or ""),
                site_id=str(raw.get("site_id") or ""),
                site=str(raw.get("site") or ""),
                action_id=str(raw.get("action_id") or ""),
                target=raw.get("target") if isinstance(raw.get("target"), dict) else None,
                awaiting=str(raw.get("awaiting") or ""),
                id=str(raw.get("id") or uuid.uuid4().hex[:8]),
            )
        except Exception:  # noqa: BLE001 -- an unreadable item is no item
            return None


@dataclass(slots=True)
class MessageDraft:
    id: str
    organization_id: str
    user_id: str
    items: list[DraftItem] = field(default_factory=list)
    project_id: str | None = None
    site_id: str | None = None
    source_message_id: str | None = None
    status: str = OPEN
    created: float = field(default_factory=time.time)
    updated: float = field(default_factory=time.time)
    #: Whether the row exists in the store (set by the store; not saved).
    persisted: bool = False

    @classmethod
    def new(cls, *, organization_id: str, user_id: str, source_message_id: str | None = None) -> MessageDraft:
        return cls(
            id=uuid.uuid4().hex,
            organization_id=str(organization_id),
            user_id=str(user_id),
            source_message_id=source_message_id,
        )

    def item(self, item_id: str) -> DraftItem | None:
        return next((i for i in self.items if i.id == item_id), None)

    @property
    def ready_items(self) -> list[DraftItem]:
        return [i for i in self.items if i.state == OK]

    @property
    def waiting_items(self) -> list[DraftItem]:
        return [i for i in self.items if i.state == NEEDS_ANSWER]

    @property
    def unreadable_items(self) -> list[DraftItem]:
        return [i for i in self.items if i.state == UNREADABLE]

    @property
    def live(self) -> bool:
        """Something on it can still be saved or answered; a draft of only
        unreadable items is never kept."""
        return any(i.state in (OK, NEEDS_ANSWER) for i in self.items)

    @property
    def full(self) -> bool:
        return len(self.items) >= MAX_ITEMS

    def expired(self, now: float | None = None) -> bool:
        return (now if now is not None else time.time()) - self.updated > DRAFT_TTL_SECONDS


# -- taps ---------------------------------------------------------------------


def tap_id(action: str, draft_id: str, *extra: str) -> str:
    return ":".join([f"{TAP_PREFIX}{action}", draft_id, *extra])


def parse_tap(value: str) -> tuple[str, str, tuple[str, ...]] | None:
    """(action, draft id, extra parts) from a tap id; None when it is not a
    draft tap or is malformed."""
    if not value.startswith(TAP_PREFIX):
        return None
    action, _, rest = value[len(TAP_PREFIX) :].partition(":")
    draft_id, *extra = rest.split(":")
    if action not in (SAVE, CANCEL, ANSWER, CHANGE_SITE, MOVE_SITE) or len(draft_id) != 32:
        return None
    try:
        uuid.UUID(hex=draft_id)
    except ValueError:
        return None
    if (action == ANSWER and len(extra) != 2) or (action == MOVE_SITE and len(extra) != 1):
        return None
    if action in (SAVE, CANCEL, CHANGE_SITE) and extra:
        return None
    return action, draft_id, tuple(extra)


# -- what a prepared event says -------------------------------------------------


def _action_type(workflow_key: Any, fields: dict[str, Any]) -> DraftActionType | None:
    key = getattr(workflow_key, "value", workflow_key)
    if key == WorkflowKey.LABOUR_ATTENDANCE.value:
        return DraftActionType.RECORD_LABOUR_ATTENDANCE
    if key == WorkflowKey.MATERIAL_RECEIPT.value:
        return DraftActionType.RECORD_MATERIAL_RECEIPT
    if key == WorkflowKey.MATERIAL_USAGE.value:
        return DraftActionType.RECORD_MATERIAL_USAGE
    if key == WorkflowKey.SITE_ISSUE_REPORT.value:
        return DraftActionType.RECORD_SITE_ISSUE
    if key == WorkflowKey.SITE_UPDATE.value:
        # Work on an open activity is a progress update; else new work: the two
        # read the same on the card, bar the "(completed)" a new activity shows
        # only when it is finished (saved_summary.summarise_draft).
        return DraftActionType.ADD_PROGRESS_UPDATE if fields.get("activity_id") else DraftActionType.CREATE_ACTIVITY
    return None


def preview(workflow_key: Any, fields: dict[str, Any], *, today: Any = None) -> str | None:
    """The card line for what the workflow would save, by the same function
    that words a saved record (``summarise_draft``), or None when it says
    nothing readable."""
    action = _action_type(workflow_key, fields)
    if action is None:
        return None
    return summarise_draft(SimpleNamespace(action_type=action, fields=dict(fields)), today=today)


# -- labour: a day that already has a count ------------------------------------


def _lines(value: Any) -> list[dict[str, Any]]:
    return [line for line in value if isinstance(line, dict)] if isinstance(value, list) else []


def _total(lines: list[dict[str, Any]]) -> int:
    return sum(_headcount(line) for line in lines)


def _crew_summary(lines: list[dict[str, Any]]) -> str:
    return summarise_draft(
        SimpleNamespace(action_type=DraftActionType.RECORD_LABOUR_ATTENDANCE, fields={"lines": lines})
    ) or f"{_total(lines)} workers"


def labour_question(fields: dict[str, Any]) -> tuple[str, list[str]] | None:
    """BE-10 made a second count for a day replace the figures it repeats,
    without asking. On the card that is a question first: "Today already 13
    workers (8 mason, 5 helper). Replace with 8 workers (8 mason), or add?".
    None when the day has no count, or the new one repeats nothing of it, or
    repeats it exactly (nothing would change)."""
    new = _lines(fields.get("lines"))
    old = _lines(fields.get("day_counted_lines"))
    if not new or not old:
        return None
    replaced = [o for o in old if any(_replaces(n, o) for n in new)]
    if not replaced:
        return None
    repeating = [n for n in new if any(_replaces(n, o) for o in old)]
    if _total(repeating) == _total(replaced) and len(repeating) == len(replaced):
        return None
    return (
        f"Today already {_crew_summary(old)}. Replace it with {_crew_summary(new)}, or add to it?",
        [REPLACE, ADD],
    )


def add_to_day(fields: dict[str, Any]) -> dict[str, Any]:
    """``fields`` with each repeated line raised by what the day already
    counts for it ("add"): a line that replaces today's 8 mason with 5 more
    becomes 13 mason, written as the day's new latest figure. Lines that repeat
    nothing are untouched."""
    new = [dict(line) for line in _lines(fields.get("lines"))]
    old = _lines(fields.get("day_counted_lines"))
    for line in new:
        before = sum(_headcount(o) for o in old if _replaces(line, o))
        if before:
            line["headcount"] = _headcount(line) + before
    return {**fields, "lines": new}


def apply_answer(item: DraftItem, choice: int, *, today: Any = None) -> bool:
    """The sender's tap on the item's question. True when it settled the item.
    Replace keeps the figures as sent; Add raises them by today's."""
    if item.state != NEEDS_ANSWER or not item.ready or not 0 <= choice < len(item.options):
        return False
    answer = item.options[choice]
    event = item.ready.get("event") or {}
    fields = dict(event.get("fields") or {})
    if item.kind == KIND_LABOUR:
        if answer == ADD:
            fields = add_to_day(fields)
            item.ready = {**item.ready, "event": {**event, "fields": fields}}
        key = (item.ready.get("decision") or {}).get("workflow_key")
        item.summary = preview(key, fields, today=today) or item.summary
    item.state = OK
    item.question, item.options = "", []
    return True


# -- the card -----------------------------------------------------------------


def _line(item: DraftItem, *, show_site: bool) -> str:
    line = item.line
    return f"{line} · {item.site}" if show_site and item.site else line


def card_text(draft: MessageDraft, *, site: str | None = None) -> str:
    """The whole draft as one card: a line per ready item (under "To save:"),
    each open question, and what could not be read."""
    ready = draft.ready_items
    asking = [i for i in draft.waiting_items if i.pending_answer]
    sites = {i.site_id or i.site for i in draft.items if i.state != UNREADABLE and (i.site_id or i.site)}
    show_site = len(sites) > 1
    parts: list[str] = []
    if ready or asking:
        header = f"{TO_SAVE_HEADER[:-1]} · {site}:" if site and not show_site else TO_SAVE_HEADER
        # Request 127: an item waiting for its answer is a line of the card, with
        # its question beside it ("Steel used: 20 rod (❓ how many kg?)").
        lines = [_line(i, show_site=show_site) for i in ready]
        lines += [f"{_line(i, show_site=show_site)} (❓ {i.question})" for i in asking]
        parts.append(render_saved(lines, header))
    parts.extend(f"❓ {i.question}" for i in draft.waiting_items if not i.pending_answer)
    if draft.unreadable_items:
        parts.append(CANT_READ + "; ".join(i.label or i.summary or i.tool for i in draft.unreadable_items))
    return "\n".join(parts)


def movable_items(draft: MessageDraft) -> list[DraftItem]:
    """The items "Change site" moves: new entries of a sender with several sites
    (their line names the site). A pending action or a correction of a saved
    entry stays where it is."""
    return [i for i in draft.items if i.state != UNREADABLE and i.site and i.kind not in (KIND_ACTION, KIND_CHANGE)]


def card_rows(draft: MessageDraft) -> list[ListRow]:
    """Save (when something is ready), Cancel, the options of the first open
    question, and Change site (a sender with several sites, something to save).
    The tap ids name the draft, so a tap can only act on it."""
    rows: list[ListRow] = []
    if draft.ready_items:
        rows.append(ListRow(tap_id(SAVE, draft.id), SAVE_TITLE))
    if draft.live:
        rows.append(ListRow(tap_id(CANCEL, draft.id), CANCEL_TITLE))
    asking = next(iter(draft.waiting_items), None)
    if asking is not None:
        rows.extend(
            ListRow(tap_id(ANSWER, draft.id, asking.id, str(n)), option)
            for n, option in enumerate(asking.options)
        )
    if draft.ready_items and movable_items(draft):
        rows.append(ListRow(tap_id(CHANGE_SITE, draft.id), CHANGE_SITE_TITLE))
    return rows


def card_reply(draft: MessageDraft, words: str = "", *, site: str | None = None) -> ReplySpec:
    """``words`` above the card, with its buttons (a list when more than three)."""
    text = "\n\n".join(p for p in (words.strip(), card_text(draft, site=site)) if p)
    rows = card_rows(draft)
    return pick_form(text, rows) if rows else ReplySpec(text=text)


def context_line(draft: MessageDraft | None) -> str | None:
    """What the model is told about the sender's open card: its lines, and that
    what it saves is added to it (nothing is written until they tap Save)."""
    if draft is None or not draft.live:
        return None
    listed = "; ".join(f"{n}. {i.line}" for n, i in enumerate(draft.items, 1) if i.state != UNREADABLE)
    return (
        f"Their open card {draft.id[:6]} (Save / Cancel not tapped yet, nothing is written): {listed}. What you "
        "save now is added to it. If they correct a figure on it ('alla, 8 mason aanu'), call "
        f"update_pending_card with card_id {draft.id[:6]}, the item's number and only the fields that change: "
        "the card is shown again with the change. Say a change was made only when the tool says so. "
        "undo_last cancels the whole card."
    )


def saved_context_line(items: list[str], card_id: str) -> str | None:
    """What the model is told about the sender's latest SAVED card (request 127):
    its lines, and that a correction on one is a new card with a change line,
    which they save by tap."""
    if not items:
        return None
    listed = "; ".join(f"{n}. {text}" for n, text in enumerate(items, 1))
    return (
        f"Their latest saved card {card_id}: {listed}. If they correct a figure on it ('alla, 5 mason aanu'), call "
        f"update_pending_card with card_id {card_id}, the item's number and only the fields that change: it shows a "
        "'Change ...' card that they save by tap; nothing changes before that. undo_last removes the saved card."
    )


# -- what the model said it understood, against the card ------------------------


def label_for(tool: str, args: dict[str, Any]) -> str:
    """A few words for one tool call, as the sender would say it: the line for
    "Couldn't read: ...". Never raises."""
    try:
        if tool == SAVE_LABOUR:
            parts = [
                f"{w.get('headcount', 1)} {trade_label(w.get('trade')).lower() or w.get('name') or 'worker'}"
                for w in _lines(args.get("workers"))
            ]
            return ", ".join(parts) or "labour"
        if tool == SAVE_WORK_DONE:
            quantities = _lines(args.get("quantities"))
            said = ", ".join(
                " ".join(str(p) for p in (q.get("quantity"), q.get("unit"), q.get("work_type")) if p not in (None, ""))
                for q in quantities
            )
            return said or str(args.get("narrative") or args.get("work_type") or "work done")[:60]
        if tool in (SAVE_MATERIAL_RECEIPT, SAVE_MATERIAL_USAGE):
            return (
                " ".join(
                    str(p) for p in (args.get("quantity"), args.get("unit"), args.get("material")) if p not in (None, "")
                )
                or "material"
            )
        if tool == REPORT_ISSUE:
            return str(args.get("narrative") or args.get("issue_type") or "issue")[:60]
    except Exception:  # noqa: BLE001 -- a label is wording only
        pass
    return tool


def duplicate_of(draft: MessageDraft, item: DraftItem) -> DraftItem | None:
    """The item already on the draft that this one repeats exactly (the same
    tool, scope and arguments): the model calling twice for one part."""
    for other in draft.items:
        if other.kind == item.kind and other.tool == item.tool and other.site_id == item.site_id and other.args == item.args:
            return other
    return None


def _day(item: DraftItem) -> str:
    fields = ((item.ready or {}).get("event") or {}).get("fields") or {}
    return str(fields.get("occurred_date") or "")


def same_day_labour(draft: MessageDraft, item: DraftItem) -> DraftItem | None:
    """The labour item already on the draft for the same site and day: a later
    count merges into it (``cards.merge_changes``), as a card edit always did."""
    if item.kind != KIND_LABOUR:
        return None
    return next(
        (
            o
            for o in draft.items
            if o.kind == KIND_LABOUR and o.site_id == item.site_id and _day(o) == _day(item)
        ),
        None,
    )



# -- a correction of something already saved (request 127, P2) ------------------


def _worker_label(line: dict[str, Any]) -> str:
    return str(line.get("name") or "").strip() or trade_label(line.get("trade")).lower() or "worker"


def _worker_key(line: dict[str, Any]) -> str:
    from .cards import _worker_key as key

    return key(line)


def worker_moves(old: dict[str, Any], new: dict[str, Any]) -> str:
    """"mason 6 → 5, electrician 0 → 2": the trades whose figure differs
    between the saved entry's arguments and the corrected ones."""
    before = {_worker_key(w): w for w in _lines(old.get("workers"))}
    moves: list[str] = []
    for line in _lines(new.get("workers")):
        was = before.pop(_worker_key(line), None)
        a, b = (_headcount(was) if was else 0), _headcount(line)
        if a != b:
            moves.append(f"{_worker_label(line)} {a} → {b}")
    return ", ".join(moves)


def change_line(
    tool: str,
    old_args: dict[str, Any],
    new_args: dict[str, Any],
    *,
    old_summary: str,
    new_summary: str,
    site: str = "",
    day: str = "today",
) -> str:
    """The one card line of a correction: "Change today's labour at Green Villa:
    mason 6 → 5 (total 7)"; any other kind reads "Change <saved line> → <new line>"."""
    where = f" at {site}" if site else ""
    if tool == SAVE_LABOUR:
        when = "today's labour" if day in ("", "today") else f"labour for {day}"
        total = sum(_headcount(w) for w in _lines(new_args.get("workers")))
        moves = worker_moves(old_args, new_args) or "details"
        return f"Change {when}{where}: {moves} (total {total})"
    return f"Change{where}: {old_summary} → {new_summary}"


def change_for(draft: MessageDraft, fact_id: str) -> DraftItem | None:
    """The correction already on the card for this saved entry, if any."""
    return next(
        (i for i in draft.items if i.kind == KIND_CHANGE and (i.target or {}).get("fact_id") == fact_id), None
    )


# -- a question that waits on its answer, as a line of the card (request 127) -----


def waiting_line(tool: str, args: dict[str, Any]) -> str:
    """The card line of a call that could not become an item yet because the
    system asked something first: "Steel used: 20 rod", "Cement in: 50 bags"."""
    what = label_for(tool, args)
    material = str(args.get("material") or "").strip()
    if tool in (SAVE_MATERIAL_RECEIPT, SAVE_MATERIAL_USAGE) and material:
        rest = " ".join(
            str(p) for p in (args.get("quantity"), args.get("unit")) if p not in (None, "")
        )
        word = "in" if tool == SAVE_MATERIAL_RECEIPT else "used"
        return f"{material.capitalize()} {word}: {rest}".rstrip(": ") if rest else f"{material.capitalize()} {word}"
    return what


def waiting_for(draft: MessageDraft, item: DraftItem) -> DraftItem | None:
    """The line waiting on an answer that this item answers: the same kind of
    entry (and, for material, the same material)."""
    material = str(item.args.get("material") or "").strip().casefold()
    same = [i for i in draft.items if i.pending_answer and i.kind == item.kind]
    named = [i for i in same if material and str(i.args.get("material") or "").strip().casefold() == material]
    # "Which material?" is answered with another name: then the only waiting line of its kind is it.
    return named[0] if named else (same[0] if len(same) == 1 else None)
