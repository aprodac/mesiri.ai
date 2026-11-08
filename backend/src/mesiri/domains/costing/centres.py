"""Cost centres (CC-01): where a period's money went, from the one cost read model.

Every figure starts from ``finance.costs.project_costs`` (expenses, priced deliveries without a bill, labour,
machines), so this page and the Expenses page's "Full cost" never disagree. Only the expenses are split further,
by the cost centre of their category:

- materials  = priced deliveries + expenses in a materials category
- labour     = attendance at its wage + expenses in a labour category
- subcontract= expenses in a subcontract category, and every subcontract bill whatever its category
- equipment  = machine hire earned + expenses in an equipment category
- fuel       = machine diesel + expenses in a fuel category
- overhead, other = expenses in those categories
- not set    = expenses whose category has no centre (or no category): said, never guessed

The centres and "not set" always add up to the read model's total (a test holds it).
"""

from __future__ import annotations

import datetime
import uuid
from collections import defaultdict
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.domains.finance.costs import EXPENSE_COST_SQL, project_costs

CENTRES: dict[str, str] = {
    "materials": "Materials",
    "labour": "Labour",
    "subcontract": "Subcontract",
    "equipment": "Equipment",
    "fuel": "Fuel",
    "overhead": "Site overhead",
    "other": "Other",
}
NOT_SET = "not_set"
_C = Decimal("0.01")


def _m(v: Decimal) -> str:
    return str(Decimal(v).quantize(_C))


async def expenses_by_category(
    conn: AsyncConnection,
    org: uuid.UUID,
    *,
    project_ids: set[uuid.UUID] | None,
    site_id: uuid.UUID | None,
    date_from: datetime.date,
    date_to: datetime.date,
    visible,
) -> list[dict]:
    """Confirmed expenses in the period per category, with the category's centre and whether it is a subcontract
    bill. The same filter and the same cost of an expense as ``finance.costs`` (confirmed, by occurred date, project,
    site, the caller's scope; ``EXPENSE_COST_SQL``: before claimable GST, D-CC8)."""
    where = ["e.organization_id = :org", "e.workflow_status = 'confirmed'", "e.occurred_date BETWEEN :f AND :t"]
    params: dict = {"org": org, "f": date_from, "t": date_to}
    if project_ids is not None:
        where.append("e.project_id = ANY(:projects)")
        params["projects"] = list(project_ids)
    if site_id is not None:
        where.append("e.site_id = :site")
        params["site"] = site_id
    rows = (await conn.execute(text(
        "SELECT e.project_id, e.site_id, c.id AS category_id, c.name AS category, c.cost_centre, "
        "EXISTS (SELECT 1 FROM work_order_bills b WHERE b.expense_id = e.id) AS subcontract_bill, "
        f"COUNT(*) AS n, SUM({EXPENSE_COST_SQL}) AS amount FROM expenses e "
        "LEFT JOIN expense_categories c ON c.id = e.category_id "
        f"WHERE {' AND '.join(where)} GROUP BY 1, 2, 3, 4, 5, 6"), params)).mappings().all()  # noqa: S608
    return [dict(r) for r in rows if r["site_id"] is None or visible(r["project_id"], r["site_id"])]


def split(costs: dict, expense_rows: list[dict]) -> dict:
    """The read model's total, split into centres. Pure: ``costs`` is ``project_costs``' answer."""
    amount: dict[str, Decimal] = defaultdict(Decimal)
    parts: dict[str, list[dict]] = defaultdict(list)

    def add(centre: str, source: str, value: Decimal, **extra) -> None:
        if value:
            amount[centre] += value
            parts[centre].append({"source": source, "amount": _m(value), **extra})

    add("materials", "Deliveries (priced, not on a bill)", Decimal(costs["materials"]["amount"]),
        count=costs["materials"]["deliveries"])
    add("labour", "Attendance at its wage", Decimal(costs["labour"]["amount"]), man_days=costs["labour"]["man_days"])
    add("equipment", "Machine hire", Decimal(costs["machines"]["hire"]))
    add("fuel", "Machine diesel", Decimal(costs["machines"]["fuel"]))

    by_category: dict[tuple, dict] = {}
    for r in expense_rows:
        centre = "subcontract" if r["subcontract_bill"] else (r["cost_centre"] or NOT_SET)
        key = (centre, r["category_id"], bool(r["subcontract_bill"]))
        row = by_category.setdefault(key, {"amount": Decimal(0), "count": 0, "category": r["category"]})
        row["amount"] += Decimal(r["amount"] or 0)
        row["count"] += int(r["n"])
    for (centre, category_id, bill), row in sorted(by_category.items(), key=lambda kv: -kv[1]["amount"]):
        source = "Subcontract bills" if bill else f"Expenses: {row['category'] or 'no category'}"
        add(centre, source, row["amount"], count=row["count"], category_id=str(category_id) if category_id else None)

    centres = [{"key": k, "label": label, "amount": _m(amount[k]), "parts": parts[k]} for k, label in CENTRES.items()]
    return {
        "total": costs["total"],
        "gst": costs.get("gst"),
        "centres": centres,
        "not_set": {"amount": _m(amount[NOT_SET]), "parts": parts[NOT_SET]},
        "unpriced_deliveries": costs["materials"]["unpriced"],
        "man_days": costs["labour"]["man_days"],
        "priced_man_days": costs["labour"]["priced_man_days"],
    }


async def cost_centres(conn: AsyncConnection, org: uuid.UUID, **scope) -> dict:
    costs = await project_costs(conn, org, **scope)
    rows = await expenses_by_category(conn, org, **scope)
    return {"date_from": costs["date_from"], "date_to": costs["date_to"], **split(costs, rows)}
