"""What was actually saved, in a few words, from the saved data (request 57).

Every reply used to say "✅ Recorded. Thank you." or echo the worker's raw
words ("6 mason, 10 helper vannu"). A worker standing on a site needs to see
what Mesiri understood, so each saved record is summarised from its draft
fields -- the data that was written, not the message that was typed:

    16 workers (6 mason, 10 helper)      Plastering, 2nd floor: 40%
    Cement in: 25 bags                   Cement used: 5 bags
    Expense ₹4,500 (Transport)          Issue: Out of 8mm bars
    Question for your engineer: ...

Pure: no I/O, English. ``runtime/reply_language.py`` swaps the few label words
for Malayalam / Hindi senders, the same way it does the other fixed sentences,
and numbers, names and units are never touched. The shapes here are what that
swap looks for: change one, change both.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from mesiri_contracts.assistant.draft_action import DraftActionType
from mesiri_contracts.assistant.v2.draft_action import DraftActionV2
from trade_label import trade_label

SAVED_HEADER = "✅ Saved:"
QUESTION_PREFIX = "Question for your engineer: "  # canonicalization/question_note.py


def _text(value: Any) -> str:
    return " ".join(str(value).split()) if value is not None else ""


def _num(value: Any) -> str:
    """"25", "2.5", "4,500": a quantity as a person writes it."""
    raw = _text(value)
    if not raw:
        return ""
    try:
        number = Decimal(raw.replace(",", ""))
    except InvalidOperation:
        return raw
    if number == number.to_integral_value():
        return f"{int(number):,}" if abs(number) >= 10000 else str(int(number))
    return f"{number.normalize():f}"


def _title(value: Any) -> str:
    text = _text(value).replace("_", " ")
    return text[:1].upper() + text[1:]


def _labour(fields: dict[str, Any]) -> str | None:
    raw = fields.get("lines")
    lines = [line for line in raw if isinstance(line, dict)] if isinstance(raw, list) else []
    if not lines:
        return None
    per_trade: dict[str, int] = {}
    total = 0
    for line in lines:
        try:
            count = int(line.get("headcount", 1))
        except (TypeError, ValueError):
            count = 1
        total += count
        trade = trade_label(line.get("trade")).lower() or "worker"
        per_trade[trade] = per_trade.get(trade, 0) + count
    word = "worker" if total == 1 else "workers"
    breakdown = ", ".join(f"{n} {trade}" for trade, n in per_trade.items())
    if len(per_trade) == 1 and "worker" in per_trade:
        return f"{total} {word}"
    return f"{total} {word} ({breakdown})"


def _activity(fields: dict[str, Any]) -> str | None:
    work = _title(fields.get("work_type") or fields.get("activity_summary"))
    place = _text(fields.get("location"))
    head = ", ".join(p for p in (work, place) if p)
    pct = _text(fields.get("progress_percent"))
    quantity = ""
    quantities = fields.get("quantities")
    if isinstance(quantities, list) and quantities and isinstance(quantities[0], dict):
        first = quantities[0]
        quantity = " ".join(p for p in (_num(first.get("quantity")), _text(first.get("unit"))) if p)
    elif fields.get("quantity") is not None:
        quantity = " ".join(p for p in (_num(fields.get("quantity")), _text(fields.get("unit"))) if p)
    detail = f"{pct}%" if pct else quantity
    if not head and not detail:
        narrative = _text(fields.get("narrative"))
        return narrative[:80] or None
    if not head:
        return detail
    return f"{head}: {detail}" if detail else head


def summarise_draft(draft: DraftActionV2 | Any) -> str | None:
    """One short line for a saved record, or None when the type has no
    summary (the reply then keeps its generic wording)."""
    fields = dict(getattr(draft, "fields", None) or {})
    action = getattr(draft, "action_type", None)
    if action is DraftActionType.RECORD_LABOUR_ATTENDANCE:
        return _labour(fields)
    if action in (DraftActionType.CREATE_ACTIVITY, DraftActionType.ADD_PROGRESS_UPDATE):
        # New work and a continuation read the same: request 83 -- "3rd floor
        # slab concreting finished" (a new activity) lost its "(completed)".
        line = _activity(fields)
        kind = _title(fields.get("update_kind")).lower()
        shown = kind != "progress" if action is DraftActionType.ADD_PROGRESS_UPDATE else kind == "completed"
        if line and not _text(fields.get("progress_percent")) and kind and shown:
            return f"{line} ({kind})"
        return line
    if action is DraftActionType.TRANSFER_MATERIAL:
        material = _title(fields.get("material_name")) or "Material"
        qty = " ".join(p for p in (_num(fields.get("quantity")), _text(fields.get("unit"))) if p)
        sites = " → ".join(p for p in (_text(fields.get("from_site_name")), _text(fields.get("to_site_name"))) if p)
        head = f"Transfer: {material} {qty}".strip()
        return f"{head} · {sites}" if sites else head
    if action is DraftActionType.RECORD_MATERIAL_RECEIPT and fields.get("movement_reason") == "OPENING_STOCK":
        material = _title(fields.get("material_name")) or "Material"
        qty = " ".join(p for p in (_num(fields.get("quantity")), _text(fields.get("unit"))) if p)
        site = _text(fields.get("site_label"))
        line = f"Opening stock: {material} {qty}".strip()
        return f"{line} ({site})" if site else line
    if action in (DraftActionType.RECORD_MATERIAL_RECEIPT, DraftActionType.RECORD_MATERIAL_USAGE):
        material = _title(fields.get("material_name")) or "Material"
        qty = " ".join(p for p in (_num(fields.get("quantity")), _text(fields.get("unit"))) if p)
        verb = "in" if action is DraftActionType.RECORD_MATERIAL_RECEIPT else "used"
        line = f"{material} {verb}: {qty}" if qty else f"{material} {verb}"
        # WA-41: converted into the stock unit -> what they actually said, so
        # the conversion is checked before Save. WA-37: who it came from /
        # what it was for, as the sender said it.
        reported = " ".join(
            p for p in (_num(fields.get("reported_quantity")), _text(fields.get("reported_unit"))) if p
        )
        extras = [e for e in (reported, _text(fields.get("supplier") if verb == "in" else fields.get("work_item"))) if e]
        return f"{line} ({'; '.join(extras)})" if extras else line
    if action is DraftActionType.RECORD_EXPENSE:
        amount = _num(fields.get("amount"))
        category = _title(fields.get("category"))
        what = f"Expense ₹{amount}" if amount else "Expense"
        return f"{what} ({category})" if category else what
    if action is DraftActionType.RECORD_SITE_ISSUE:
        narrative = _text(fields.get("narrative"))
        if narrative.startswith(QUESTION_PREFIX.strip()):
            return narrative[:160]
        issue = _title(fields.get("issue_type")).lower() or "issue"
        return f"Issue ({issue}): {narrative[:80]}" if narrative else f"Issue ({issue})"
    if action is DraftActionType.TRANSFER_MONEY:
        amount = _num(fields.get("amount"))
        return f"Transfer ₹{amount}" if amount else None
    return None


def render_saved(summaries: list[str]) -> str:
    """The "Saved:" block: one line for one thing, a header and bullets for
    several. Empty when there is nothing to say."""
    items = [s for s in (summaries or []) if s]
    if not items:
        return ""
    if len(items) == 1:
        return f"{SAVED_HEADER} {items[0]}"
    return "\n".join([SAVED_HEADER, *(f"• {s}" for s in items)])
