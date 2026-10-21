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
    "ready": "{The_dpr}{code_suffix} attached.{unconfirmed_note}",
    "pending_confirmation": (
        "{site_prefix}{updates}, not confirmed yet. "
        "The report goes out once the day is confirmed."
    ),
    "pending_render": "{The_report} is being prepared. Please ask again in a few minutes.",
    "unavailable": "I can't look up {the_report} right now. Please try again in a minute.",
    "pdf_unavailable": (
        "{The_dpr}{code_suffix} is ready, but I couldn't fetch the PDF just now. "
        "Please ask again in a minute."
    ),
    "not_generated": (
        "No DPR has been generated for today yet. Log an activity first, "
        "or check back once today's report has run."
    ),
    # WA-40: asked during the day, before the evening cutoff builds it.
    "preview": (
        "Today's report is made this evening. So far today{site_at}:\n{preview}\n"
        "This is a draft: not final, and not sent to anyone."
    ),
    "bad_date": (
        "Which day's report do you want? Say \"yesterday\" or a date like 12 Oct 2026."
    ),
}

#: A past day: nothing is "yet" about it, so the wording is its own.
_PAST_NOT_GENERATED = (
    "There is no DPR for {day}: nothing was logged that day, or its report "
    "was never generated."
)


def _updates(count: int) -> str:
    return f"{count} update{'' if count == 1 else 's'}"


def generate_dpr_request_reply(state: WorkflowGraphState) -> dict:
    """No draft_action -- this is read-only, so WorkflowRuntime completes it
    without a confirmation."""
    fields = state.get("collected_fields", {})
    status = fields.get("dpr_status", "not_generated")
    code = fields.get("dpr_code")
    site_name = fields.get("dpr_site_name")
    confirmed = fields.get("dpr_confirmed", True)
    day = str(fields.get("dpr_day") or "")

    if status == "not_generated" and day:
        return {"pending_prompt": _PAST_NOT_GENERATED.format(day=day)}
    template = _STATUS_TEXT.get(status, _STATUS_TEXT["not_generated"])
    the_dpr = f"the DPR for {day}" if day else "today's DPR"
    the_report = f"the report for {day}" if day else "today's report"
    return {
        "pending_prompt": template.format(
            the_dpr=the_dpr,
            the_report=the_report,
            The_dpr=the_dpr[:1].upper() + the_dpr[1:],
            The_report=the_report[:1].upper() + the_report[1:],
            code_suffix=f" ({code})" if code and status in ("ready", "pdf_unavailable") else "",
            unconfirmed_note="" if confirmed else " Not confirmed yet.",
            site_prefix=f"{site_name}: " if site_name else "",
            updates=_updates(int(fields.get("dpr_update_count") or 0)),
            site_at=f" at {site_name}" if site_name else "",
            preview=fields.get("dpr_preview") or "",
        )
    }
