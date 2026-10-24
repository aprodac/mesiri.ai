"""Material workflow nodes — pure functions, no LangGraph, no I/O, no SQL, no domain rules.

Each node takes the graph's working state and returns the partial update
LangGraph merges in. Shape-mapping only: quantity>0 and other business rules
belong to the Domain layer, not here (architecture: "no business logic in
workflow nodes").
"""

from __future__ import annotations

from datetime import date

from mesiri_contracts.assistant.draft_action import DraftActionType
from mesiri_contracts.assistant.planner_decision import WorkflowKey
from mesiri_contracts.assistant.v2.draft_action import DraftActionV2
from mesiri_contracts.common.ids import new_id

from ..readable import field_lines
from ..state import WorkflowGraphState

_ACTION_TYPE_BY_WORKFLOW_KEY: dict[WorkflowKey, DraftActionType] = {
    WorkflowKey.MATERIAL_RECEIPT: DraftActionType.RECORD_MATERIAL_RECEIPT,
    WorkflowKey.MATERIAL_USAGE: DraftActionType.RECORD_MATERIAL_USAGE,
    WorkflowKey.MATERIAL_TRANSFER: DraftActionType.TRANSFER_MATERIAL,
}

_ACTION_LABEL: dict[DraftActionType, str] = {
    DraftActionType.RECORD_MATERIAL_RECEIPT: "Material Receipt",
    DraftActionType.RECORD_MATERIAL_USAGE: "Material Usage",
    DraftActionType.TRANSFER_MATERIAL: "Material Transfer",
}


def build_draft(state: WorkflowGraphState) -> dict:
    """Map collected fields into a DraftAction. Shape-mapping only — no validation."""
    workflow_key = WorkflowKey(state["workflow_key"])
    action_type = _ACTION_TYPE_BY_WORKFLOW_KEY[workflow_key]
    fields = dict(state.get("collected_fields") or {})
    # available_stock is a runtime hint for request_confirmation's low-stock
    # warning (see runtime/inbound_journey.py's injection) -- not a real
    # business field, so it must never appear as a line in the saved draft
    # or the confirmation text's field list.
    fields.pop("available_stock", None)
    fields.pop("no_opening_stock", None)
    draft = DraftActionV2(
        draft_id=new_id("draft"),
        correlation_id=state["correlation_id"],
        workflow_instance_id=state["workflow_instance_id"],
        action_type=action_type,
        organization_id=state["organization_id"],
        user_id=state["user_id"],
        project_id=state.get("project_id"),
        site_id=state.get("site_id"),
        fields=fields,
    )
    return {"draft_action": draft}


def _low_stock_warning(state: WorkflowGraphState, draft: DraftActionV2) -> str | None:
    if draft.action_type is not DraftActionType.RECORD_MATERIAL_USAGE:
        return None
    available = state.get("collected_fields", {}).get("available_stock")
    if available is None:
        return None
    try:
        requested = float(draft.fields.get("quantity"))
        available = float(available)
    except (TypeError, ValueError):
        return None
    if requested <= available:
        return None
    unit = draft.fields.get("unit", "")
    return f"⚠️ Only {available:g} {unit} in stock — you're reporting {requested:g}."


# Rendered by _date_line below, not as a raw key:value line -- shown as
# "occurred_date: 2026-07-20" it would be meaningless to a site engineer.
_DISPLAY_HIDDEN_FIELD_KEYS = frozenset({"occurred_date", "occurred_date_source"})


def _date_line(fields: dict) -> str | None:
    """The day being recorded, marked when Mesiri guessed it. Backported from
    Labour's workflows/labour_update/nodes.py (STA-166) -- same reasoning:
    material corrections are new opposite-direction movements, never edits,
    so a wrong date has the same permanence problem attendance does, and
    confirmation is the only cheap moment to catch it."""
    raw = str(fields.get("occurred_date") or "").strip()
    if not raw:
        return None
    try:
        shown = date.fromisoformat(raw).strftime("%d %b %Y")
    except ValueError:
        shown = raw
    if str(fields.get("occurred_date_source") or "") == "inferred_at_confirmation":
        return f"   • Date: {shown} (assumed today)"
    return f"   • Date: {shown}"


def request_confirmation(state: WorkflowGraphState) -> dict:
    """Compose the confirmation prompt. Deterministic formatting only — no
    localization/templates/AI generation here (that moves to a rendering
    boundary once those requirements arrive)."""
    draft: DraftActionV2 = state["draft_action"]
    label = _ACTION_LABEL[draft.action_type]
    if draft.fields.get("movement_reason") == "OPENING_STOCK":
        label = "Opening Stock"
    lines = ["*Confirm this record?*", "", f"📦 {label}"]
    date_line = _date_line(draft.fields)
    if date_line:
        lines.append(date_line)
    shown = {
        key: value
        for key, value in draft.fields.items()
        if key not in _DISPLAY_HIDDEN_FIELD_KEYS and key != "direction"
    }
    quantity, unit = shown.get("quantity"), shown.pop("unit", None)
    if quantity is not None and unit:
        if isinstance(quantity, float) and quantity == int(quantity):
            quantity = int(quantity)
        shown["quantity"] = f"{quantity} {unit}"
    lines.extend(field_lines(shown))
    if draft.action_type is DraftActionType.TRANSFER_MATERIAL:
        lines.append(f"   • From: {draft.fields.get('from_site_name') or 'this site'}")
        lines.append(f"   • To: {draft.fields.get('to_site_name') or ''}")
    warning = _low_stock_warning(state, draft)
    if warning:
        lines.append("")
        lines.append(warning)
    lines.append("")
    lines.append("Reply YES to confirm or NO to cancel.")
    return {"pending_prompt": "\n".join(lines)}
