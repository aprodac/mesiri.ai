"""WA-132: the green SAVED card after a v3 Save, the same card classic and v2 send.

The card is drawn by the existing ``channel.receipt`` builder (``RecordReceiptBuilder.build_combined``)
from a draft action and the saved row's id. v3's entries are API requests, so this turns each saved
one into the draft action the builder reads (type, project / site, the fields its card shows): the
material and unit by name (read through the API as the sender), the site names from the sender's
sites. Entries with no card in classic either (a site's conditions, sending the DPR, closing an
issue) are left out. Never raises: the Save and its line already went through.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
import uuid
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from channel.receipt.draft_slip import Slip, SlipLine
from mesiri_contracts.application.results.execution_result import ExecutionResult, ExecutionStatus
from mesiri_contracts.assistant.draft_action import DraftActionType
from mesiri_contracts.assistant.v2.confirmed_action import ConfirmedActionV2
from mesiri_contracts.assistant.v2.draft_action import DraftActionV2

from .agent import PendingWrite, WriteResult
from .client import ApiClient
from .materials import NEW
from .reply_guard import without_ids
from .units import unit_rows

_log = logging.getLogger(__name__)

#: v3 tool -> the record type its card shows.
CARD_TYPES: dict[str, DraftActionType] = {
    "record_receipt": DraftActionType.RECORD_MATERIAL_RECEIPT,
    "record_usage": DraftActionType.RECORD_MATERIAL_USAGE,
    "record_transfer": DraftActionType.TRANSFER_MATERIAL,
    "record_expense": DraftActionType.RECORD_EXPENSE,
    "record_attendance": DraftActionType.RECORD_LABOUR_ATTENDANCE,
    "record_work": DraftActionType.CREATE_ACTIVITY,
    "report_issue": DraftActionType.RECORD_SITE_ISSUE,
}
_MATERIAL_TOOLS = {"record_receipt", "record_usage", "record_transfer"}


def has_card(entry: PendingWrite) -> bool:
    """WA-210: the entry has a SAVED receipt card (receipt, usage, transfer, expense, attendance, work, issue)."""
    return entry.tool in CARD_TYPES


async def preview_card(builder: Any, entries: list[PendingWrite], ctx: Any, client: ApiClient,
                       correlation_id: str | None) -> bytes | None:
    """WA-210 / WA-215: the draft slip of the ready list (every line, numbered as the ✏️ Edit list numbers them), sent
    as the header of the Save / Edit / Cancel message. Not translated (records are kept in English, [243]; a
    translation call would sit on the reply path). None when there is nothing to draw, no builder, or drawing failed:
    the list then goes out as text, as before."""
    if builder is None or not entries or not hasattr(builder, "build_slip"):
        return None
    try:
        return await builder.build_slip(await preview_slip(entries, ctx, client))
    except Exception:  # noqa: BLE001 -- the list still goes out as text
        _log.exception("agent_api.preview_card_failed user=%s", getattr(ctx, "user_id", None))
        return None


async def preview_slip(entries: list[PendingWrite], ctx: Any, client: ApiClient) -> Slip:
    """The slip of the ready list: material and unit names, and (WA-259) the records a line acts on by their name
    ("Close issue · Leak · water tank leak"), looked up only when a line needs them."""
    plain = all(e.tool in _MATERIAL_TOOLS or e.tool in CARD_TYPES for e in entries)
    names = ({}, {}) if plain and not any(e.tool in _MATERIAL_TOOLS for e in entries) else await _names(client)
    return slip_for(entries, ctx, names, targets=await _targets(client, entries))


#: WA-259: the lists a line's record is named from (by the path it acts on) and how a row is named.
_TARGET_LISTS = (("/progress/issues/", "/progress/issues", lambda r: _clean(r.get("narrative"), 40) or str(
                     r.get("issue_type") or "").replace("_", " ").title()),
                 ("/procurement/requests/", "/procurement/requests", lambda r: str(r.get("ref") or "")),
                 ("/procurement/orders/", "/procurement/orders", lambda r: " · ".join(
                     p for p in (str(r.get("ref") or ""), str(r.get("vendor_name") or "")) if p)))


async def _targets(client: ApiClient, entries: list[PendingWrite]) -> dict[str, str]:
    found: dict[str, str] = {}
    for prefix, path, label in _TARGET_LISTS:
        if not any(e.path.startswith(prefix) for e in entries):
            continue
        listed = await client.call("GET", path, params={"limit": 100})
        rows = listed.body.get("items", []) if listed.ok and isinstance(listed.body, dict) else []
        found |= {str(r.get("id")): label(r) for r in rows if isinstance(r, dict) and r.get("id") and label(r)}
    return found


def _amount(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value or "")
    return f"{number:,.2f}".rstrip("0").rstrip(".") if number % 1 else f"{int(number):,}"


def _clean(value: Any, limit: int = 60) -> str:
    text = " ".join(without_ids(str(value or "")).split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def slip_for(entries: list[PendingWrite], ctx: Any, names: tuple[dict, dict], now: dt.datetime | None = None,
             targets: dict[str, str] | None = None) -> Slip:
    """WA-215: the slip's rows from the entries Save will send, in list order: what each one is, in plain words,
    and its quantity. Lines with no receipt card (a new material, a size, a project) get a row too, so the card
    is the whole list."""
    material, unit = names
    sites = {str(s.id): s.name for s in (getattr(ctx, "sites", None) or [])}
    projects = {str(p.id): p.name for p in (getattr(ctx, "projects", None) or [])}
    lines = [_line(i, e, material, unit, sites, targets) for i, e in enumerate(entries, 1)]
    places = {str(e.body.get("site_id") or e.body.get("from_site_id") or "") for e in entries} - {""}
    if len(places) == 1:
        site = sites.get(next(iter(places)), "")
    elif len(places) > 1:
        site = f"{len(places)} sites"
    else:
        site = next((projects[str(e.body["project_id"])] for e in entries
                     if str(e.body.get("project_id") or "") in projects), "")
    try:
        zone = ZoneInfo(str(getattr(ctx, "timezone", None) or "Asia/Kolkata"))
    except (ZoneInfoNotFoundError, ValueError):
        zone = ZoneInfo("Asia/Kolkata")
    local = (now or dt.datetime.now(dt.UTC)).astimezone(zone)
    when = f"{local.day} {local:%b}, {local:%I:%M %p}".replace(" 0", " ").replace("AM", "am").replace("PM", "pm")
    return Slip(site=site, when=when, lines=lines)


def _plural(trade: str, count: int) -> str:
    """"Helper" -> "Helpers" for more than one ("Mason" -> "Masons"); a word already plural stays."""
    return trade if count == 1 or trade.endswith("s") else f"{trade}s"


def _line(number: int, entry: PendingWrite, material: dict[str, str], unit: dict[str, str],
          sites: dict[str, str], targets: dict[str, str] | None = None) -> SlipLine:
    body, tool = entry.body, entry.tool
    if tool in _MATERIAL_TOOLS:
        raw = str(body.get("material_id") or "")
        note = ""  # WA-262: the row's tag says delivery / used / transfer
        if tool == "record_receipt" and body.get("supplier"):
            note = f"from {_clean(body['supplier'], 30)}"
        elif tool == "record_usage" and body.get("work_item"):
            note = f"used for {_clean(body['work_item'], 30)}"
        elif tool == "record_transfer":
            note = f"to {sites.get(str(body.get('to_site_id')), 'another site')}"
        return SlipLine(number, kind_of(tool), _material_name(raw, material), note, _amount(body.get("quantity")),
                        unit.get(str(body.get("unit_id")), ""), new=raw.startswith(NEW))
    if tool == "record_attendance":
        rows = [ln for ln in body.get("lines") or [] if isinstance(ln, dict)]
        total = sum(int(ln.get("headcount") or 1) for ln in rows)
        trades = [str(ln.get("worker_name") or ln.get("trade") or "worker").strip() for ln in rows]
        if len(rows) == 1:
            title = trades[0] if rows[0].get("worker_name") else _plural(trades[0].title(), total)
            return SlipLine(number, "labour", title, "at work", str(total))
        detail = " · ".join(f"{t.title()} {int(ln.get('headcount') or 1)}" for t, ln in zip(trades, rows, strict=True))
        return SlipLine(number, "labour", "Workers", _clean(detail), str(total))
    if tool == "record_work":
        quantities = [q for q in body.get("quantities") or [] if isinstance(q, dict)]
        title = _clean(body.get("work_type") or body.get("narrative") or entry.summary, 40)
        narrative = _clean(body.get("narrative"))
        note = narrative if narrative and narrative.casefold() != title.casefold() else "work done"
        if quantities:
            return SlipLine(number, "work", title, note, _amount(quantities[0].get("quantity")),
                            str(quantities[0].get("unit") or ""))
        return SlipLine(number, "work", title, note)
    if tool == "report_issue":
        title = _clean(body.get("title") or body.get("narrative") or body.get("summary") or entry.summary, 40)
        severity = str(body.get("severity") or "").title()
        return SlipLine(number, "issue", title, f"{severity} issue".strip() if severity else "issue")
    if tool == "record_expense":
        title = _clean(body.get("description") or body.get("category_text") or "Expense", 40)
        note = _clean(body.get("vendor_text") or body.get("category_text") or "expense", 30)
        return SlipLine(number, "expense", title, note, f"₹{_amount(body.get('amount'))}")
    if tool == "add_material":
        return SlipLine(number, "list", _clean(body.get("name") or entry.summary, 40), "new on your material list",
                        new=True)
    return _structured(number, entry, material, unit, sites, targets or {})


#: WA-259 (Ilan, 8 Nov: a material request's slip showed the model's Manglish sentence): what a list line does, in
#: English, for every write without its own row above. One entry per tool; the line's details come from the body
#: (material, quantity, site, vendor, the record it acts on), never from the model's sentence.
TITLES: dict[str, str] = {
    "ask_for_material": "Material request", "change_material_request": "Change request",
    "cancel_material_request": "Cancel request", "decide_material_request": "Decide request",
    "place_order": "Purchase order", "change_order": "Change order", "cancel_order": "Cancel order",
    "close_order": "Close order", "delivery_order": "Order for delivery",
    "resolve_issue": "Close issue", "acknowledge_issue": "Issue seen", "wont_fix_issue": "Won't fix issue",
    "send_dpr": "Send today's report", "correct_work": "Correct work",
    "send_report_to": "Send report", "schedule_report": "Report every week / month",
    "undo_receipt": "Take back delivery", "undo_usage": "Take back usage", "undo_transfer": "Take back transfer",
    "undo_expense": "Take back expense", "pay_expense": "Pay expense",
    "update_material": "Change material", "add_standard_categories": "Standard categories",
    "set_unit_conversion": "Material size", "answer_size_request": "Material size",
    "set_reply_language": "Reply language", "add_expense_category": "New expense category",
    "create_project": "New project", "update_project": "Change project", "add_site": "New site",
    "update_site": "Change site", "add_project_member": "Add to project", "add_material_alias": "Other name",
    "add_person": "Add person",
}
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
#: WA-262: each tool's look on the slip (channel/receipt/draft_slip.KINDS): its own colour, icon and label.
_KIND_BY_TOOL = {
    "record_receipt": "receipt", "record_usage": "usage", "record_transfer": "transfer",
    "ask_for_material": "request", "change_material_request": "request", "cancel_material_request": "request",
    "decide_material_request": "request", "place_order": "order", "change_order": "order", "cancel_order": "order",
    "close_order": "order", "delivery_order": "order", "report_issue": "issue", "acknowledge_issue": "issue",
    "wont_fix_issue": "issue", "resolve_issue": "issue_close", "record_expense": "expense",
    "pay_expense": "payment", "pay_supplier": "payment", "send_dpr": "send",
    "send_report_to": "send", "schedule_report": "send", "record_attendance": "labour",
    "record_work": "work", "correct_work": "work",
    "log_machines": "machine", "add_machine": "machine", "move_machine": "machine", "off_hire_machine": "machine",
    "update_schedule_activity": "schedule",
}


def kind_of(tool: str) -> str:
    """WA-262: the slip kind of a tool; a take-back has its own; anything else is a setting."""
    return _KIND_BY_TOOL.get(tool) or ("undo" if tool.startswith("undo_") else "list")


#: Lines the CODE wrote in English (a size, a correction): their own words are already structured.
_CODE_DRAWN = ("📏", "✏️", "📤")
#: Body fields that say which / who / why, in the order shown.
_DETAILS = ("supplier", "vendor_name", "name", "full_name", "language", "reason", "resolution_notes", "purpose", "notes")


def _structured(number: int, entry: PendingWrite, material: dict[str, str], unit: dict[str, str],
                sites: dict[str, str], targets: dict[str, str]) -> SlipLine:
    body, tool = entry.body, entry.tool
    title = TITLES.get(tool) or tool.replace("_", " ").capitalize()
    summary = without_ids(entry.summary or "").strip()
    if summary.startswith(_CODE_DRAWN):
        return SlipLine(number, kind_of(tool), title, _clean(summary.lstrip("".join(_CODE_DRAWN)).strip(), 70))
    place = sites.get(str(body.get("site_id") or ""), "")
    items = [ln for ln in body.get("lines") or [] if isinstance(ln, dict) and ln.get("material_id")]
    if body.get("material_id") and body.get("quantity") is not None:
        items = [body]
    details = [targets[v] for v in _UUID.findall(entry.path or "") if v in targets]
    details += [targets[str(v)] for k, v in body.items() if k.endswith("_id") and str(v) in targets]
    details += [_clean(body[k], 30) for k in _DETAILS if isinstance(body.get(k), str) and body.get(k).strip()]
    if body.get("rate") is not None:
        details.append(f"₹{_amount(body.get('rate'))} each")
    if body.get("needed_by"):
        details.append(f"by {body['needed_by']}")
    if place:
        details.append(place)
    # WA-262: the row's tag says what it is (REQUEST, ORDER, ISSUE CLOSED): the note keeps only which / who / where.
    note = " · ".join(dict.fromkeys(d for d in details if d))
    kind = kind_of(tool)
    target = next((targets[v] for v in _UUID.findall(entry.path or "") if v in targets), "")
    if target and not items:
        rest = [d for d in dict.fromkeys(details) if d and d != target]
        return SlipLine(number, kind, _clean(target, 40), _clean(" · ".join(rest), 70))
    if len(items) == 1:
        one = items[0]
        return SlipLine(number, kind, _material_name(one.get("material_id"), material), _clean(note, 70),
                        _amount(one.get("quantity")), unit.get(str(one.get("unit_id")), ""))
    if items:
        listed = ", ".join(f"{_material_name(i.get('material_id'), material)} {_amount(i.get('quantity'))} "
                           f"{unit.get(str(i.get('unit_id')), '')}".strip() for i in items[:3])
        return SlipLine(number, kind, title, _clean(" · ".join([listed, *details]), 70))
    return SlipLine(number, kind, title, _clean(" · ".join(dict.fromkeys(details)), 70))


def caption_lines(slip: Slip) -> list[str]:
    """WA-259: the slip's lines as text, the same structured words the picture shows (English, numbered as ✏️ Edit
    numbers them), for the message the picture rides on."""
    from channel.receipt.draft_slip import KINDS

    out = []
    for line in slip.lines:
        amount = " ".join(p for p in (line.quantity, line.unit) if p)
        label = KINDS.get(line.kind, KINDS["list"])[3].capitalize()
        parts = [f"*{line.title}*", line.note, amount]
        # WA-262: the kind first, as on the picture ("📝 Request: *Cement* · Main block · 50 bags").
        out.append(f"{line.number}. {KIND_EMOJI.get(line.kind, '⚙️')} {label}: " + " · ".join(p for p in parts if p))
    return out


#: WA-262: each kind's mark in the text lines (the picture has its colour and icon).
KIND_EMOJI = {"receipt": "📥", "usage": "🏗️", "transfer": "🔁", "request": "📝", "order": "🛒", "labour": "👷",
              "work": "🛠️", "issue": "⚠️", "issue_close": "✔️", "expense": "💸", "payment": "💰", "undo": "↩️",
              "send": "📤", "list": "⚙️", "material": "📦"}

#: WA-286: a line of the card as the code writes it ("1. 📥 Delivery: *Cement* · 10 bags"): its number, a kind's mark,
#: the kind and a colon. Only the code draws these; one written by the model is a copy of an earlier card.
CARD_LINE = re.compile(
    r"^[ \t]*\d+\.[ \t]*(?:" + "|".join(re.escape(m) for m in sorted(set(KIND_EMOJI.values()), key=len, reverse=True))
    + r")[ \t\ufe0f]*[^:\n]{1,30}:[^\n]*$", re.MULTILINE)


async def saved_card(builder: Any, results: list[WriteResult], ctx: Any, client: ApiClient,
                     correlation_id: str | None) -> bytes | None:
    """The PNG of what was saved, or None (nothing with a card, no builder, or it failed)."""
    if builder is None:
        return None
    saved = [r for r in results if r.ok and r.pending.tool in CARD_TYPES]
    if not saved:
        return None
    try:
        names = await _names(client) if any(r.pending.tool in _MATERIAL_TOOLS for r in saved) else ({}, {})
        pairs = [pair for r in saved if (pair := _saved_pair(r, ctx, names, correlation_id)) is not None]
        return await builder.build_combined(pairs, ctx, kept=True) if pairs else None
    except Exception:  # noqa: BLE001 -- the card is a picture of what is already saved
        _log.exception("agent_api.saved_card_failed user=%s", getattr(ctx, "user_id", None))
        return None


async def _names(client: ApiClient) -> tuple[dict[str, str], dict[str, str]]:
    materials, units = await client.call("GET", "/materials", params={"limit": 200}), await client.call(
        "GET", "/materials/units-of-measure")
    items = materials.body.get("items", []) if materials.ok and isinstance(materials.body, dict) else []
    return ({str(m.get("id")): str(m.get("name")) for m in items if isinstance(m, dict)},
            {str(u.get("id")): str(u.get("code")) for u in (unit_rows(units.body) if units.ok else [])})


def _saved_pair(result: WriteResult, ctx: Any, names: tuple[dict, dict], correlation_id: str | None
                ) -> tuple[ConfirmedActionV2, ExecutionResult] | None:
    row_id = None
    if isinstance(result.body, dict):
        row_id = result.body.get("id") or result.body.get("transfer_id")
    return _pair(result.pending, str(row_id), ctx, names, correlation_id) if row_id else None


def _material_name(material_id: Any, names: dict[str, str]) -> str:
    """The material's name; a material waiting to be added in the same list (``new:<name>``) by that name."""
    value = str(material_id or "")
    if value.startswith(NEW):
        return value[len(NEW):].strip() or "Material"
    return names.get(value, "Material")


def _pair(entry: PendingWrite, row_id: str, ctx: Any, names: tuple[dict, dict], correlation_id: str | None
          ) -> tuple[ConfirmedActionV2, ExecutionResult] | None:
    body = entry.body
    material, unit = names
    sites = {str(s.id): s.name for s in (getattr(ctx, "sites", None) or [])}
    tool = entry.tool
    fields: dict[str, Any]
    site_id = body.get("site_id") or body.get("from_site_id")
    if tool in _MATERIAL_TOOLS:
        fields = {"material_name": _material_name(body.get("material_id"), material),
                  "quantity": body.get("quantity"), "unit": unit.get(str(body.get("unit_id")), "")}
        if tool == "record_receipt":
            fields |= {"supplier": body.get("supplier"), "movement_reason": body.get("movement_reason") or "RECEIVED"}
        elif tool == "record_usage":
            fields |= {"work_item": body.get("work_item"), "movement_reason": body.get("movement_reason") or "CONSUMED"}
        else:
            fields |= {"from_site_name": sites.get(str(body.get("from_site_id")), ""),
                       "to_site_name": sites.get(str(body.get("to_site_id")), "")}
    elif tool == "record_expense":
        fields = {"amount": body.get("amount"), "category": body.get("category_text") or "",
                  # [243]: the record's own English words, never the card line (that is in their language).
                  "description": body.get("description") or body.get("vendor_text") or body.get("category_text") or ""}
    elif tool == "record_attendance":
        fields = {"lines": [{"worker_name": ln.get("worker_name"), "trade": ln.get("trade"),
                             "headcount": ln.get("headcount", 1)} for ln in body.get("lines") or []]}
    elif tool == "record_work":
        quantities = [{"quantity": q.get("quantity"), "unit": q.get("unit")} for q in body.get("quantities") or []]
        fields = {"work_type": body.get("work_type") or "", "narrative": body.get("narrative"),
                  "contractor": body.get("contractor"), "quantities": quantities,
                  **({"quantity": quantities[0]["quantity"], "unit": quantities[0]["unit"]} if quantities else {})}
    else:  # report_issue
        fields = {"issue_type": body.get("issue_type"), "severity": body.get("severity"),
                  "narrative": body.get("narrative") or body.get("title") or body.get("summary") or body.get("description") or ""}
    key = entry.idempotency_key
    draft = DraftActionV2(
        draft_id=f"api-{uuid.uuid4().hex[:12]}", correlation_id=correlation_id or key, workflow_instance_id=key,
        action_type=CARD_TYPES[tool], organization_id=str(ctx.organization_id), user_id=str(ctx.user_id),
        project_id=body.get("project_id"), site_id=site_id, fields=fields,
    )
    confirmed = ConfirmedActionV2(confirmed_action_id=f"api-{uuid.uuid4().hex[:12]}", workflow_instance_id=key,
                                  correlation_id=correlation_id or key, draft_action=draft,
                                  confirmed_by_user_id=str(ctx.user_id))
    return confirmed, ExecutionResult(status=ExecutionStatus.SUCCEEDED, idempotency_key=key,
                                      material_row_id=str(row_id))
