"""Site Issue Report workflow nodes — pure functions, no LangGraph, no I/O, no SQL, no domain rules.

Mirrors workflows/material/nodes.py's simplest shape (build_draft ->
request_confirmation, no slot-filling): issue_type/severity are closed enums
(site_issue_type/site_issue_status, migration 0430) the AI extraction picks
directly, unlike Expense's category_text/vendor_text or Material's
account/duplicate/vendor slots -- there is nothing here that needs seeding
from a repository before the draft can be shown, so this graph has no
conditional edges at all (see graph.py).
"""

from __future__ import annotations

from datetime import date

from mesiri_contracts.assistant.draft_action import DraftActionType
from mesiri_contracts.assistant.v2.draft_action import DraftActionV2
from mesiri_contracts.common.ids import new_id

from ..readable import field_lines
from ..state import WorkflowGraphState

# occurred_date/occurred_date_source are rendered by _date_line instead of as
# raw lines, same reasoning as expense_capture/nodes.py's identical set.
_DISPLAY_HIDDEN_FIELD_KEYS = frozenset({"occurred_date", "occurred_date_source"})


def build_draft(state: WorkflowGraphState) -> dict:
    """Map collected fields into a DraftAction. Shape-mapping only — no
    validation (that's domains/progress/validation.py, run by the Handler)."""
    fields = dict(state.get("collected_fields") or {})
    draft = DraftActionV2(
        draft_id=new_id("draft"),
        correlation_id=state["correlation_id"],
        workflow_instance_id=state["workflow_instance_id"],
        action_type=DraftActionType.RECORD_SITE_ISSUE,
        organization_id=state["organization_id"],
        user_id=state["user_id"],
        project_id=state.get("project_id"),
        site_id=state.get("site_id"),
        fields=fields,
    )
    return {"draft_action": draft}


def _date_line(fields: dict) -> str | None:
    """The day being recorded, marked when Mesiri guessed it. Same pattern as
    expense_capture/nodes.py's _date_line."""
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
    localization/templates/AI generation here (see workflows/material/nodes.py)."""
    draft: DraftActionV2 = state["draft_action"]
    lines = ["*Confirm this record?*", "", "🚧 Site Issue"]
    date_line = _date_line(draft.fields)
    if date_line:
        lines.append(date_line)
    lines.extend(field_lines(draft.fields, skip=_DISPLAY_HIDDEN_FIELD_KEYS))
    lines.append("")
    lines.append("Reply YES to confirm or NO to cancel.")
    return {"pending_prompt": "\n".join(lines)}
