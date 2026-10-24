"""Node for the activity-search workflow (#17 Search / Ask Mesiri).

Reads `collected_fields['activity_search_results']`, seeded by the caller
(see runtime/activity_search_service.py) before this graph runs. Mirrors
workflows/labour_query/nodes.py's shape and reasoning.

Answers with what was actually logged -- work type and narrative, the way a
site engineer would recognise their own entries -- plus a separate count of
open issues, since "what happened" and "what's blocking us" are two
different questions a supervisor asks.
"""

from __future__ import annotations

from ..state import WorkflowGraphState

#: Individual entries listed before the reply summarises. Mirrors labour_
#: query's _MAX_NAMES_SHOWN reasoning: past this, a WhatsApp message becomes
#: a wall of text and the count is the useful part.
_MAX_ENTRIES_SHOWN = 8
#: Open issues listed (request 104, D4): the service reads at most this many
#: and the reply says how many more there are.
_MAX_ISSUES_SHOWN = 20


def _pretty(label: str) -> str:
    return label.replace("_", " ").title()


def generate_activity_search_reply(state: WorkflowGraphState) -> dict:
    """No draft_action -- this is read-only, so WorkflowRuntime completes it
    without a confirmation."""
    fields = state.get("collected_fields", {})
    results = fields.get("activity_search_results") or {}
    date_range_label = results.get("date_range_label", "today")
    work_type_filter = fields.get("work_type")

    activities: list[dict] = results.get("activities") or []
    activity_count = results.get("activity_count", len(activities))
    open_issues: list[dict] = results.get("open_issues") or []
    open_issue_count = results.get("open_issue_count", len(open_issues))

    scope = f" — {_pretty(work_type_filter)}" if work_type_filter else ""

    if not activity_count and not open_issue_count:
        return {"pending_prompt": f"Nothing logged for {date_range_label}{scope}."}

    lines = [f"📋 *Site log{scope} — {date_range_label}*", ""]

    if activity_count:
        entry_word = "entry" if activity_count == 1 else "entries"
        lines.append(f"{activity_count} {entry_word}")
        for activity in activities[:_MAX_ENTRIES_SHOWN]:
            work_type = activity.get("work_type")
            narrative = activity.get("narrative")
            status = activity.get("status")
            label = _pretty(work_type) if work_type else "Update"
            detail = f" — {narrative}" if narrative else ""
            status_tag = f" [{_pretty(status)}]" if status else ""
            lines.append(f"• {label}{detail}{status_tag}")
        if activity_count > len(activities[:_MAX_ENTRIES_SHOWN]):
            lines.append(f"... and {activity_count - _MAX_ENTRIES_SHOWN} more")
    else:
        lines.append(f"No activity logged{scope}.")

    if open_issue_count:
        lines.append("")
        issue_word = "issue" if open_issue_count == 1 else "issues"
        lines.append(f"⚠️ {open_issue_count} open {issue_word}")
        shown = open_issues[:_MAX_ISSUES_SHOWN]
        for issue in shown:
            issue_type = issue.get("issue_type")
            narrative = issue.get("narrative")
            severity = issue.get("severity")
            label = _pretty(issue_type) if issue_type else "Issue"
            detail = f" — {narrative}" if narrative else ""
            tags = [t for t in (_pretty(severity) if severity else "", "being handled" if issue.get("status") == "ACKNOWLEDGED" else "") if t]
            severity_tag = f" ({', '.join(tags)})" if tags else ""
            lines.append(f"• {label}{detail}{severity_tag}")
        if open_issue_count > len(shown):
            lines.append(f"+{open_issue_count - len(shown)} more")

    return {"pending_prompt": "\n".join(lines)}
