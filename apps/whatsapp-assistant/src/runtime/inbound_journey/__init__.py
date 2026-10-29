"""What is left of the classic inbound journey (ARCH-06, 22 Oct 2026).

The pipeline itself (understanding -> canonicalization -> planner -> graph,
the gates, the multi-message plans and their picker taps) is gone: every
message goes to the tool-calling agent, whose entries (runtime/agent/*_entry.py)
start the workflows directly. Kept here: the seed functions those entries
call (seeding.py), the reply rendering of a workflow run (reply.py), and a few
shared helpers (_shared.py).
"""

from __future__ import annotations

from runtime.inbound_journey._shared import _log
from runtime.inbound_journey.reply import (
    _safe,
    render_workflow_run_reply_spec,
)
from runtime.inbound_journey.seeding import (
    _MATERIAL_EVENT_TYPES,
    _QUERY_PDF_WORKFLOW_KEYS,
    _WHATSAPP_MATERIAL_CREATE_ROLES,
    _build_query_pdf,
    _create_promoted_workers,
    _inject_inventory_context,
    _may_create_material,
    _maybe_trigger_worker_promotion,
    _offer_project_setup,
    _offer_team_photo,
    _project_setup_offer_target,
    _promotion_just_finished,
    _recorded_attendance_report_id,
    _seed_account_candidates,
    _seed_activity_search,
    _seed_duplicate_check,
    _seed_existing_attendance,
    _seed_finance_query_context,
    _seed_labour_query,
    _seed_open_activity,
    _seed_project_create_role,
    _seed_project_detail_query,
    _seed_reversal_target,
    _seed_vendor_check,
    _seed_worker_candidates,
    start_project_setup_followup,
)

__all__ = [
    "_MATERIAL_EVENT_TYPES",
    "_QUERY_PDF_WORKFLOW_KEYS",
    "_WHATSAPP_MATERIAL_CREATE_ROLES",
    "_build_query_pdf",
    "_create_promoted_workers",
    "_inject_inventory_context",
    "_log",
    "_may_create_material",
    "_maybe_trigger_worker_promotion",
    "_offer_project_setup",
    "_offer_team_photo",
    "_project_setup_offer_target",
    "_promotion_just_finished",
    "_recorded_attendance_report_id",
    "_safe",
    "_seed_account_candidates",
    "_seed_activity_search",
    "_seed_duplicate_check",
    "_seed_existing_attendance",
    "_seed_finance_query_context",
    "_seed_labour_query",
    "_seed_open_activity",
    "_seed_project_create_role",
    "_seed_project_detail_query",
    "_seed_reversal_target",
    "_seed_vendor_check",
    "_seed_worker_candidates",
    "render_workflow_run_reply_spec",
    "start_project_setup_followup",
]
