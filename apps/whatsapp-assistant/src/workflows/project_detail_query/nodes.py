"""Project detail query workflow nodes — pure functions, no LangGraph, no
I/O, no SQL, no domain rules.

Mirrors workflows/activity_query/nodes.py's shape: read the seeded answer
out of `collected_fields`, format a reply, return it. No draft_action ever
-- this is read-only, so WorkflowRuntime completes it without a
confirmation.
"""

from __future__ import annotations

from typing import Any

from ..state import WorkflowGraphState

#: Individual entries listed before the reply summarises. Mirrors
#: activity_query/nodes.py's identical constant/reasoning.
_MAX_ENTRIES_SHOWN = 8

_UNRESOLVED_PROMPT = (
    "Which project or site would you like details for? You can name it, "
    "e.g. \"details of Skyline Towers\" or \"details of Block A\"."
)
_NOT_FOUND_PROMPT = "I couldn't find that project or site."


def _pretty(label: str | None) -> str:
    return (label or "").replace("_", " ").title()


def _record_card_lines(project: dict[str, Any] | None, site: dict[str, Any] | None) -> list[str]:
    if site is not None:
        parent = f" (part of {project['name']})" if project else ""
        lines = [f"🏢 *{site['name']}*{parent}"]
        if project is not None:
            subtitle = " · ".join(
                p for p in [project.get("location"), _pretty(project.get("status")) or None] if p
            )
            if subtitle:
                lines.append(subtitle)
        return lines

    name = project["name"] if project else "Unknown"
    code = project.get("code") if project else None
    title = f"🏗 *{name}*" + (f" ({code})" if code else "")
    lines = [title]
    if project is not None:
        subtitle = " · ".join(
            p for p in [project.get("location"), _pretty(project.get("status")) or None] if p
        )
        if subtitle:
            lines.append(subtitle)
    return lines


def generate_project_detail_reply(state: WorkflowGraphState) -> dict:
    fields = state.get("collected_fields", {})

    if fields.get("project_detail_unresolved"):
        return {"pending_prompt": _UNRESOLVED_PROMPT}

    results = fields.get("project_detail_results") or {}
    project = results.get("project")
    site = results.get("site")
    if project is None and site is None:
        return {"pending_prompt": _NOT_FOUND_PROMPT}

    lines = _record_card_lines(project, site)

    sites = results.get("sites")
    if sites is not None:
        lines.append("")
        if sites:
            shown = sites[:_MAX_ENTRIES_SHOWN]
            names = ", ".join(s["name"] for s in shown)
            remainder = len(sites) - len(shown)
            if remainder > 0:
                names += f", and {remainder} more"
            lines.append(f"📍 Sites ({len(sites)}): {names}")
        else:
            lines.append("📍 No sites yet.")
        member_count = results.get("member_count")
        if member_count is not None:
            lines.append(f"👥 Team: {member_count} member(s)")

    lines.append("")
    lines.append("*Today:*")
    lines.append(f"🧾 {results.get('activity_count', 0)} activities logged")

    open_issue_count = results.get("open_issue_count", 0)
    lines.append(f"⚠️ {open_issue_count} open issue(s)")
    for issue in (results.get("open_issues") or [])[:_MAX_ENTRIES_SHOWN]:
        lines.append(f"   • {_pretty(issue.get('issue_type'))} ({_pretty(issue.get('severity'))})")

    # DPR-06: V1 records no wages; a cost of 0 is not shown.
    cost = results.get("labour_cost", "0")
    shown_cost = f" (cost: {cost})" if str(cost).strip() not in ("", "0", "0.0", "0.00") else ""
    lines.append(f"👷 {results.get('headcount', 0)} workers{shown_cost}")

    finance = results.get("finance")
    if finance is not None:
        lines.append("")
        lines.append(f"*{finance.get('date_range_label') or 'This Month'}:*")
        lines.append(f"💰 Spend: {finance.get('total', '0')} ({finance.get('count', 0)} expenses)")

    stock_levels = results.get("stock_levels") or []
    if stock_levels:
        lines.append("")
        shown_stock = stock_levels[:_MAX_ENTRIES_SHOWN]
        stock_bits = [
            f"{lvl.get('material_name')} {lvl.get('current_stock')} {lvl.get('unit')}"
            for lvl in shown_stock
        ]
        lines.append(f"📦 Stock: {' · '.join(stock_bits)}")

    return {"pending_prompt": "\n".join(lines)}
