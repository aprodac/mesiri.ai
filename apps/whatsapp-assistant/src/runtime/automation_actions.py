"""Builds the notification payload for one due automation -- one payload
per automation, queued identically for every resolved recipient (unlike
audience resolution, the message content does not vary per person).

Each action returns a plain JSON-safe dict written to
`notifications.payload`; `runtime/send_pending_notifications.py`'s render
step reads it back. Two conventional keys: `message` (always present, the
text fallback) and `document_object_key` (SEND_DPR only, present when a
rendered PDF already exists in storage -- the sender fetches and sends it
as a document instead of/alongside the text).
"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING, Any

from mesiri.application.automations.scheduling import local_now

if TYPE_CHECKING:
    from .dpr_request_query import DprRequestQueryService
    from .reporting_compliance_query import ReportingComplianceQueryService


def _local_today(automation: dict[str, Any]) -> datetime.date:
    return local_now(
        timezone_name=automation.get("timezone") or "UTC",
        now_utc=datetime.datetime.now(datetime.UTC),
    ).date()


async def _build_send_dpr_payload(
    dpr_query: DprRequestQueryService, automation: dict[str, Any]
) -> dict[str, Any]:
    site_id = automation.get("site_id")
    project_id = automation.get("project_id")
    if not site_id or not project_id:
        return {"message": "This automation has no site configured to send a DPR for."}

    report_date = _local_today(automation)
    result = await dpr_query.find_report(
        organization_id=str(automation["organization_id"]),
        project_id=str(project_id),
        site_id=str(site_id),
        report_date=report_date,
    )
    status = result["status"]
    if status == "ready":
        return {
            "message": f"Today's DPR ({result.get('code') or ''}) is attached.",
            "document_object_key": result["object_key"],
        }
    if status == "pending_render":
        return {"message": f"Today's DPR ({result.get('code') or ''}) is generated but not yet rendered as a PDF."}
    if status == "pending_confirmation":
        return {"message": "Today's updates are saved but not confirmed yet, so there is no report to send."}
    return {"message": f"No DPR has been generated yet for {report_date.isoformat()}."}


async def _build_compliance_summary_payload(
    compliance_query: ReportingComplianceQueryService, automation: dict[str, Any]
) -> dict[str, Any]:
    project_id = automation.get("project_id")
    report_date = _local_today(automation)
    result = await compliance_query.check(
        organization_id=str(automation["organization_id"]),
        project_id=str(project_id) if project_id else None,
        report_date=report_date,
    )
    not_reported = [s["site_name"] for s in result["sites"] if not s["reported"]]
    total = len(result["sites"])
    reported = result["reported_count"]
    if total == 0:
        return {"message": "No active sites to check."}
    if not not_reported:
        return {"message": f"✅ All {total} site(s) reported for {report_date.isoformat()}."}
    names = ", ".join(not_reported[:10])
    if len(not_reported) > 10:
        names += f", and {len(not_reported) - 10} more"
    return {
        "message": (
            f"📋 {reported}/{total} site(s) reported for {report_date.isoformat()}. "
            f"Not yet reported: {names}."
        )
    }


async def build_payload(
    *,
    dpr_query: DprRequestQueryService,
    compliance_query: ReportingComplianceQueryService,
    automation: dict[str, Any],
) -> dict[str, Any]:
    """Never returns None -- an action with nothing interesting to say
    (e.g. every site reported) still gets a real, honest payload rather
    than silently queuing nothing, so REMINDER/SEND_DPR/COMPLIANCE_SUMMARY
    all behave the same way from the runner's point of view."""
    action = automation["action"]
    if action == "SEND_DPR":
        return await _build_send_dpr_payload(dpr_query, automation)
    if action == "COMPLIANCE_SUMMARY":
        return await _build_compliance_summary_payload(compliance_query, automation)
    # REMINDER
    return {"message": automation.get("message") or "This is a reminder."}
