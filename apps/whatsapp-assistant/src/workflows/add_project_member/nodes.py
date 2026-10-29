"""Add-project-member workflow nodes — pure functions, no LangGraph, no I/O, no SQL.

Mirrors workflows/site_create/nodes.py's build_draft/request_confirmation
shape, with one addition: which project the member is added to comes from
`state["project_id"]`, resolved by the ordinary context pipeline the same
way every other project-scoped workflow already relies on, never from
`collected_fields`. If that resolution came up empty, build_draft asks
instead of building a draft with no project, mirroring site_create's own
missing-project check.

`member_name` is only a best-effort hint at this point -- turning it into a
real user_id is a DB round trip (application/projects/name_resolution.py),
which cannot happen in a pure node (workflows/runtime.py's rule); it travels
untouched on the draft and is resolved by the backend Handler right before
persist, exactly as automation_setup's audience_names are (see
application/automations/handlers.py).

`role` is normalized here (pure string matching, no I/O) into the same
closed vocabulary users.role/project_members.role already use, defaulting
to SITE_ENGINEER -- the same default project_members.role's own column
default applies when nothing is added via the dashboard either.
"""

from __future__ import annotations

import re

from mesiri_contracts.assistant.draft_action import DraftActionType
from mesiri_contracts.assistant.v2.draft_action import DraftActionV2
from mesiri_contracts.common.ids import new_id

from ..role_words import ROLE_DISPLAY, normalize_role, role_not_allowed_reply
from ..state import WorkflowGraphState

_MISSING_PROJECT_PROMPT = "Which project should I add this member to?"
_MISSING_NAME_PROMPT = "Who should I add to this project?"


def build_draft(state: WorkflowGraphState) -> dict:
    """Map collected fields + the context-resolved project into a
    DraftAction, or -- if the project isn't resolved or AI extraction never
    filled in a member name -- complete with a clarifying reply and no draft
    at all (see WorkflowDefinition.allows_completion_without_draft in
    workflows/registry.py, which permits WorkflowKey.ADD_PROJECT_MEMBER to
    complete without a draft for exactly this case)."""
    project_id = state.get("project_id")
    if not project_id:
        return {"pending_prompt": _MISSING_PROJECT_PROMPT}
    fields = dict(state.get("collected_fields") or {})
    member_name = str(fields.get("member_name") or "").strip()
    if not member_name:
        return {"pending_prompt": _MISSING_NAME_PROMPT}
    role = normalize_role(fields.get("role"))
    refused = role_not_allowed_reply(fields.get("created_by_role"), role)
    if refused:
        return {"pending_prompt": refused}
    draft = DraftActionV2(
        draft_id=new_id("draft"),
        correlation_id=state["correlation_id"],
        workflow_instance_id=state["workflow_instance_id"],
        action_type=DraftActionType.ADD_PROJECT_MEMBER,
        organization_id=state["organization_id"],
        user_id=state["user_id"],
        project_id=project_id,
        site_id=None,
        fields={
            "member_name": member_name,
            "role": role,
            "created_by_role": fields.get("created_by_role"),
        },
    )
    return {"draft_action": draft}


def request_confirmation(state: WorkflowGraphState) -> dict:
    """Compose the confirmation prompt. Deterministic formatting only — no
    localization/templates/AI generation here (see workflows/material/nodes.py)."""
    draft: DraftActionV2 = state["draft_action"]
    member_name = draft.fields.get("member_name")
    code = str(draft.fields.get("role") or "")
    role = ROLE_DISPLAY.get(code, "Site Engineer")
    # WA-84 (live 27 Oct): "Site B-il Rajesh-ine supervisor aakku" read "Add Rajesh to this
    # project as Site Engineer": which project, why that role, and that the site named
    # does not limit what they see were all unsaid. Shown only; the draft is unchanged.
    said = dict(state.get("collected_fields") or {})
    project = str(said.get("project_label") or "").strip()
    lines = [
        "*Confirm this action?*",
        "",
        f"👤 Add *{member_name}* to {f'*{project}*' if project else 'this project'} as *{role}*",
    ]
    if code == "SITE_ENGINEER" and re.search(r"supervis|maistr|mestri|foreman", str(said.get("role_said") or ""), re.I):
        lines.append("(Mesiri has no Supervisor role; Site Engineer is the nearest.)")
    site = str(said.get("site_said") or "").strip()
    if site:
        lines.append(f"They will see every site of {project or 'the project'}, not only {site}.")
    lines += ["", "Reply YES to confirm or NO to cancel."]
    return {"pending_prompt": "\n".join(lines)}
