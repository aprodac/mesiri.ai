"""Node for the expense-query workflow.

Reads `collected_fields['expense_results']`, seeded by the caller (see
runtime/expense_query_service.py) before this graph runs. Mirrors
workflows/material_inventory_query/nodes.py's shape and reasoning exactly.
"""

from __future__ import annotations

from ..state import WorkflowGraphState

#: SEC-01: the reply to someone whose role does not see the company's expenses.
EXPENSES_NOT_FOR_YOU = (
    "Expense totals are only for the owner, finance and project managers. "
    "You can still send me an expense to record."
)


def _fmt_amount(value: str) -> str:
    number = float(value)
    if number == int(number):
        return str(int(number))
    return f"{number:.2f}"


def _generate_missing_receipts_reply(fields: dict, results: dict) -> dict:
    """Finance Module Slice 6's missing-receipt nudge -- same expense_results
    shape as the regular query, just phrased as a nudge rather than a total:
    the point is which expenses need a receipt, not how much was spent."""
    date_range_label = results.get("date_range_label", "this month")
    count = results.get("count", 0)
    items: list[dict] = results.get("items") or []

    if count == 0:
        return {
            "pending_prompt": f"📎 No missing receipts for {date_range_label} — you're all caught up!"
        }

    lines = [f"📎 *Missing receipts — {date_range_label}*", "", f"{count} expense(s) with no receipt attached:"]
    for item in items[:5]:
        desc = item.get("description") or "—"
        lines.append(f"{item['occurred_date']}  ₹{_fmt_amount(item['amount'])}  {desc}")
    if count > len(items[:5]):
        lines.append(f"... and {count - len(items[:5])} more")
    return {"pending_prompt": "\n".join(lines)}


def generate_expense_query_reply(state: WorkflowGraphState) -> dict:
    """No draft_action -- this is read-only, so WorkflowRuntime completes it
    without a confirmation."""
    fields = state.get("collected_fields", {})
    results = fields.get("expense_results") or {}
    category_name = fields.get("category_name")
    date_range_label = results.get("date_range_label", "this month")
    total = results.get("total", "0")
    count = results.get("count", 0)
    items: list[dict] = results.get("items") or []

    if fields.get("expense_denied"):
        # SEC-01: who may read expenses (mesiri.authorization.roles).
        return {"pending_prompt": EXPENSES_NOT_FOR_YOU}
    if fields.get("missing_receipts"):
        return _generate_missing_receipts_reply(fields, results)

    scope = f" on {category_name}" if category_name else ""

    if count == 0:
        return {"pending_prompt": f"No expenses{scope} found for {date_range_label}."}

    lines = [f"💸 *Expenses{scope} — {date_range_label}*", "", f"Total: ₹{_fmt_amount(total)} ({count})"]
    if items:
        lines.append("")
        for item in items[:5]:
            desc = item.get("description") or "—"
            lines.append(f"{item['occurred_date']}  ₹{_fmt_amount(item['amount'])}  {desc}")
        if count > len(items[:5]):
            lines.append(f"... and {count - len(items[:5])} more")
    return {"pending_prompt": "\n".join(lines)}
