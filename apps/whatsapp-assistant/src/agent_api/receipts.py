"""WA-132: the green SAVED card after a v3 Save, the same card classic and v2 send.

The card is drawn by the existing ``channel.receipt`` builder (``RecordReceiptBuilder.build_combined``)
from a draft action and the saved row's id. v3's entries are API requests, so this turns each saved
one into the draft action the builder reads (type, project / site, the fields its card shows): the
material and unit by name (read through the API as the sender), the site names from the sender's
sites. Entries with no card in classic either (a site's conditions, sending the DPR, closing an
issue) are left out. Never raises: the Save and its line already went through.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from mesiri_contracts.application.results.execution_result import ExecutionResult, ExecutionStatus
from mesiri_contracts.assistant.draft_action import DraftActionType
from mesiri_contracts.assistant.v2.confirmed_action import ConfirmedActionV2
from mesiri_contracts.assistant.v2.draft_action import DraftActionV2

from .agent import PendingWrite, WriteResult
from .client import ApiClient
from .materials import NEW
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
    """WA-210: the entry is drawn on the card (receipt, usage, transfer, expense, attendance, work, issue)."""
    return entry.tool in CARD_TYPES


async def preview_card(builder: Any, entries: list[PendingWrite], ctx: Any, client: ApiClient,
                       correlation_id: str | None) -> bytes | None:
    """WA-210 (Ilan, 5 Nov: "before saving itself you get the image card, and you save after that"): the TO SAVE
    card of the ready list, sent as the header of the Save / Edit / Cancel message. Not translated (the record is
    kept in English, [243], and a translation call would sit on the reply path). None when no entry has a card,
    there is no builder, or drawing failed: the list then goes out as text, as before."""
    if builder is None:
        return None
    carded = [e for e in entries if has_card(e)]
    if not carded:
        return None
    try:
        names = await _names(client) if any(e.tool in _MATERIAL_TOOLS for e in carded) else ({}, {})
        pairs = [pair for e in carded if (pair := _pair(e, PREVIEW_ROW, ctx, names, correlation_id)) is not None]
        return await builder.build_combined(pairs, ctx, kept=False, localize=False) if pairs else None
    except Exception:  # noqa: BLE001 -- the list still goes out as text
        _log.exception("agent_api.preview_card_failed user=%s", getattr(ctx, "user_id", None))
        return None


#: WA-210: the preview card's row id: nothing is saved yet, so the card's reference reads "...-PREV".
PREVIEW_ROW = "preview"


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
