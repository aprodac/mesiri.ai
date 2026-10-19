"""Node for the dpr-request workflow (#16 Daily Report Generation).

Reads `collected_fields['dpr_status']`/`dpr_code`, seeded by the caller
(see runtime/dpr_request_query.py) before this graph runs. Mirrors
workflows/labour_query/nodes.py's shape and reasoning.

The actual PDF bytes are NEVER read here -- a node must not fetch object
storage content, only text fields (see workflows/runtime.py). The document
send itself happens as a separate step in runtime/inbound_journey.py, after
this node's pending_prompt is sent, keyed off the same 'ready' status this
node also reads.
"""

from __future__ import annotations

from ..state import WorkflowGraphState

_STATUS_TEXT = {
    "ready": "📄 Here's today's DPR{code_suffix}.",
    "pending_render": (
        "Today's DPR is being prepared -- try again in a few minutes."
    ),
    "unavailable": "I can't look up today's report right now. Please try again in a minute.",
    "not_generated": (
        "No DPR has been generated for today yet. Log an activity first, "
        "or check back once today's report has run."
    ),
}


def generate_dpr_request_reply(state: WorkflowGraphState) -> dict:
    """No draft_action -- this is read-only, so WorkflowRuntime completes it
    without a confirmation."""
    fields = state.get("collected_fields", {})
    status = fields.get("dpr_status", "not_generated")
    code = fields.get("dpr_code")

    template = _STATUS_TEXT.get(status, _STATUS_TEXT["not_generated"])
    code_suffix = f" ({code})" if status == "ready" and code else ""
    return {"pending_prompt": template.format(code_suffix=code_suffix)}
