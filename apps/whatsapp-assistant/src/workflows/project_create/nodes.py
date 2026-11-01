"""Project create workflow nodes — pure functions, no LangGraph, no I/O, no SQL.

Mirrors workflows/account_admin/nodes.py's build_draft/request_confirmation
shape, simplified to a single action (create-only -- no rename/archive
companion the way account_admin has create/rename/deactivate). `name` is the
only required field; `location`/`client` are optional hints passed straight
through to application/projects/validation.py, which owns the real checks.
"""

from __future__ import annotations

from mesiri_contracts.assistant.draft_action import DraftActionType
from mesiri_contracts.assistant.v2.draft_action import DraftActionV2
from mesiri_contracts.common.ids import new_id

from ..state import WorkflowGraphState

_MISSING_NAME_PROMPT = "What should the new project be called?"


def build_draft(state: WorkflowGraphState) -> dict:
    """Map collected fields into a DraftAction, or -- if AI extraction never
    filled in a project name -- complete with a clarifying reply and no
    draft at all, mirroring account_admin/nodes.py's own completeness check
    (see WorkflowDefinition.allows_completion_without_draft in
    workflows/registry.py, which permits WorkflowKey.PROJECT_CREATE to
    complete without a draft for exactly this case)."""
    fields = dict(state.get("collected_fields") or {})
    if not str(fields.get("name") or "").strip():
        return {"pending_prompt": _MISSING_NAME_PROMPT}
    draft = DraftActionV2(
        draft_id=new_id("draft"),
        correlation_id=state["correlation_id"],
        workflow_instance_id=state["workflow_instance_id"],
        action_type=DraftActionType.CREATE_PROJECT,
        organization_id=state["organization_id"],
        user_id=state["user_id"],
        project_id=state.get("project_id"),
        site_id=state.get("site_id"),
        fields=fields,
    )
    return {"draft_action": draft}


def request_confirmation(state: WorkflowGraphState) -> dict:
    """Compose the confirmation prompt. Deterministic formatting only — no
    localization/templates/AI generation here (see workflows/material/nodes.py)."""
    draft: DraftActionV2 = state["draft_action"]
    name = draft.fields.get("name")
    location = draft.fields.get("location")
    client = draft.fields.get("client")
    description = draft.fields.get("description")
    lines = ["*Confirm this action?*", "", f"🏗️ Create a new project: *{name}*"]
    if location:
        lines.append(f"📍 Location: {location}")
    if description:
        lines.append(f"📐 {description}")
    if client:
        lines.append(f"🤝 Client: {client}")
    lines.extend(["", "Reply YES to confirm or NO to cancel."])
    return {"pending_prompt": "\n".join(lines)}
