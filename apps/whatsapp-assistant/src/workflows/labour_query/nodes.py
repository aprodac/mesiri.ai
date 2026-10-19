"""Node for the labour-query workflow.

Reads `collected_fields['labour_results']`, seeded by the caller (see
runtime/labour_query_service.py) before this graph runs. Mirrors
workflows/expense_query/nodes.py's shape and reasoning.

The reply deliberately echoes attendance back the way it was reported: named
workers by name, groups as counts. That is principle P10 carried through to
the read side — a supervisor who wrote "Ravi mason, 12 helpers" should
recognise the answer at a glance rather than having to decode a total.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from trade_label import trade_label

from ..state import WorkflowGraphState


def _fmt_amount(value: object) -> str:
    """Render an amount without a noisy trailing .00. Mirrors the helper in
    workflows/labour_update/nodes.py."""
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return str(value)
    if number == number.to_integral_value():
        return f"{int(number):,}"
    return f"{number:,.2f}"


def _pretty_trade(trade: str) -> str:
    return trade_label(trade)


def generate_labour_query_reply(state: WorkflowGraphState) -> dict:
    """No draft_action -- this is read-only, so WorkflowRuntime completes it
    without a confirmation."""
    fields = state.get("collected_fields", {})
    results = fields.get("labour_results") or {}
    date_range_label = results.get("date_range_label", "today")
    trade_filter = fields.get("trade")

    headcount = results.get("headcount", 0)
    total_cost = results.get("total_cost", "0")
    named: list[str] = results.get("named") or []
    named_total = results.get("named_total", len(named))
    trades: list[str] = results.get("trades") or []
    days = results.get("days", 0)

    scope = f" — {_pretty_trade(trade_filter)}" if trade_filter else ""

    if not headcount:
        return {
            "pending_prompt": f"No attendance recorded for {date_range_label}{scope}."
        }

    worker_word = "worker" if headcount == 1 else "workers"
    lines = [f"👷 *Labour{scope} — {date_range_label}*", ""]

    # Over a multi-day range the headcount is worker-days, not people, and
    # saying "14 workers" for a week would be read as 14 individuals. Naming
    # it avoids a number that quietly means something else than it appears to.
    if days > 1:
        lines.append(f"{headcount} worker-days across {days} days")
    else:
        lines.append(f"{headcount} {worker_word}")

    try:
        if Decimal(str(total_cost)) > 0:
            lines.append(f"Cost: ₹{_fmt_amount(total_cost)}")
    except (InvalidOperation, ValueError):
        pass

    if trades:
        lines.append(f"Trades: {', '.join(_pretty_trade(t) for t in trades)}")

    if named:
        lines.append("")
        lines.append(", ".join(named))
        if named_total > len(named):
            lines.append(f"... and {named_total - len(named)} more named")

    return {"pending_prompt": "\n".join(lines)}
