"""Activity Quantity Correction workflow nodes — pure functions, no LangGraph, no I/O, no SQL.

ADR-D14 (docs/execution/DAILY_REPORTING_PLAN.md): "make that 180 sqm" is a
correction, not a new measurement -- distinct from GENERAL_SITE_UPDATE's
"another 40 sqm done" (see canonicalization/mapping.py's REQUIRED_FIELDS and
platform/ai's extraction prompt for how that distinction is drawn).

No slot-filling here -- runtime/inbound_journey.py's seeding step
(`_seed_correction_target`) already resolved which progress_update_id this
correction targets before this graph ever runs (a node must never query a
repository itself, see workflows/runtime.py's docstring), same shape as
workflows/reverse/nodes.py's target resolution. Unlike Reverse, there is no
picker here: correction is deliberately scoped to the single Activity this
conversation just touched (same-session only, mirroring undo/ADR-D15), so
there is never more than one candidate to disambiguate.
"""

from __future__ import annotations

from mesiri_contracts.assistant.draft_action import DraftActionType
from mesiri_contracts.assistant.v2.draft_action import DraftActionV2
from mesiri_contracts.common.ids import new_id

from ..state import WorkflowGraphState

_NOTHING_TO_CORRECT = (
    "I don't see anything you just logged that I can correct right now. "
    "Describe the work again if you'd like to log it fresh."
)

#: Plumbing carried through collected_fields for the confirmation prompt --
#: never a real command field. old_unit_id/old_unit/correction_activity_
#: summary are display-only; CorrectActivityQuantityCommand only reads
#: progress_update_id/new_quantity/new_unit/reason (see
#: application/progress/mapper.py's build_correct_activity_quantity_command),
#: so leaving these in draft.fields is harmless -- the mapper simply never
#: looks at them, the same pattern reverse/nodes.py's reversal_* fields use.
_INTERNAL_FIELD_KEYS: frozenset[str] = frozenset()


def build_draft(state: WorkflowGraphState) -> dict:
    """Map already-resolved fields into a DraftAction, or -- if seeding
    found nothing to correct -- complete with a friendly reply and no draft
    at all (mirrors workflows/reverse/nodes.py's "nothing to reverse"
    shape, `WorkflowDefinition.allows_completion_without_draft` in
    workflows/registry.py allows this for the same reason).

    A new unit is optional -- "make that 180" with no restated unit reuses
    the unit the original quantity was stated in (old_unit), since a
    correction almost never also changes the unit of measure."""
    fields = dict(state.get("collected_fields") or {})
    # WRK-06: the target is a progress update, or the quantity the activity was started with.
    progress_update_id = fields.get("progress_update_id") or fields.get("activity_quantity_id")

    if not progress_update_id:
        return {"pending_prompt": _NOTHING_TO_CORRECT}

    draft_fields = {key: value for key, value in fields.items() if key not in _INTERNAL_FIELD_KEYS}
    if not draft_fields.get("unit"):
        draft_fields["unit"] = draft_fields.get("old_unit")

    draft = DraftActionV2(
        draft_id=new_id("draft"),
        correlation_id=state["correlation_id"],
        workflow_instance_id=state["workflow_instance_id"],
        action_type=DraftActionType.CORRECT_ACTIVITY_QUANTITY,
        organization_id=state["organization_id"],
        user_id=state["user_id"],
        project_id=state.get("project_id"),
        site_id=state.get("site_id"),
        fields=draft_fields,
    )
    return {"draft_action": draft}


def request_confirmation(state: WorkflowGraphState) -> dict:
    """Deterministic formatting only. Always shows old value -> new value --
    the one place a mis-resolved target or a misheard number is still
    catchable before anything is persisted (principle P2)."""
    draft: DraftActionV2 = state["draft_action"]
    fields = draft.fields

    summary = fields.get("correction_activity_summary")
    old_quantity = fields.get("old_quantity")
    old_unit = fields.get("old_unit") or ""
    new_quantity = fields.get("new_quantity")
    new_unit = fields.get("unit") or old_unit

    out = ["*Confirm this correction?*", ""]
    out.append(f"✏️ {summary}" if summary else "✏️ Quantity correction")
    out.append(f"   • Quantity: {old_quantity} {old_unit} → {new_quantity} {new_unit}".rstrip())

    reason = fields.get("reason")
    if reason:
        out.append("")
        out.append(f'   "{reason}"')

    out.append("")
    out.append("Reply YES to confirm or NO to cancel.")
    return {"pending_prompt": "\n".join(out)}
