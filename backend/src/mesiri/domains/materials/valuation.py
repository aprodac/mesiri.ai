"""PRC-49: what the stock on site is worth. Read only, no table.

Value = quantity on hand x the **weighted average rate** of the material's deliveries (D-P2-4): every delivery with a
rate, not taken back, not a move between sites (the Rates rule, ``procurement/rates.py``), each at what a unit cost
the company (D-CC8, ``procurement/gst.py``: before GST when the supplier has a GSTIN, with GST when not), weighted by
its quantity, company-wide up to the day. A material never bought with a rate has no value (``unpriced``), never zero.

**Slow-moving:** something on hand that was not used in the last ``SLOW_DAYS`` days. Quantities come from the stock
summary (``stock_summary`` / the repository's ``get_stock_summary``), so this page, Stock and the period report agree.
The stock count (PRC-48) prices its differences with the same rates.
"""

from __future__ import annotations

import datetime
import uuid
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.domains.procurement import rates as rate_store

SLOW_DAYS = 30
TOP = 10
_C = Decimal("0.01")


def money(v: Decimal | None) -> str | None:
    return None if v is None else str(Decimal(v).quantize(_C, rounding=ROUND_HALF_UP))


def weighted(rows: list[dict[str, Any]]) -> dict[str, Decimal]:
    """Per material: sum(quantity x cost rate) / sum(quantity) over its deliveries with a rate."""
    amount: dict[str, Decimal] = defaultdict(Decimal)
    qty: dict[str, Decimal] = defaultdict(Decimal)
    for r in rows:
        q = Decimal(r["quantity"])
        if q <= 0:
            continue
        key = str(r["material_id"])
        amount[key] += q * rate_store.cost_rate(r)
        qty[key] += q
    return {k: amount[k] / qty[k] for k in qty if qty[k] > 0}


async def average_rates(conn: AsyncConnection, organization_id: uuid.UUID, until: datetime.date,
                        material_id: uuid.UUID | None = None) -> dict[str, Decimal]:
    rows = await rate_store.fetch_purchases(conn, organization_id, project_ids=None, date_from=None, date_to=until,
                                            material_id=material_id)
    return weighted(rows)


def value_rows(summary: list[dict[str, Any]], avg: dict[str, Decimal]) -> list[dict[str, Any]]:
    """One row per site and material held: on hand, average rate, value, slow-moving (``summary`` covers the last
    ``SLOW_DAYS`` days, so its ``used`` is that window's use)."""
    out = []
    for r in summary:
        on_hand = Decimal(str(r["closing"]))
        if on_hand <= 0:
            continue
        rate = avg.get(str(r["material_id"]))
        out.append({
            "site_id": str(r["site_id"]) if r.get("site_id") else None, "project_id": str(r["project_id"]),
            "material_id": str(r["material_id"]), "material": r["material_name"], "unit": r["unit"],
            "category": r.get("category"), "main_category": r.get("main_category") or "No category",
            "on_hand": f"{on_hand.normalize():f}", "rate": money(rate),
            "value": money(on_hand * rate) if rate is not None else None,
            "used_30d": f"{Decimal(str(r['used'])).normalize():f}",
            "slow_moving": Decimal(str(r["used"])) <= 0,
        })
    out.sort(key=lambda x: -Decimal(x["value"] or 0))
    return out


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_cat: dict[str, Decimal] = defaultdict(Decimal)
    for r in rows:
        by_cat[r["main_category"]] += Decimal(r["value"] or 0)
    total = sum(by_cat.values(), Decimal(0))
    slow = [r for r in rows if r["slow_moving"]]
    return {
        "total": money(total),
        "items": len(rows),
        "unpriced": sum(1 for r in rows if r["value"] is None),
        "slow_moving": len(slow),
        "slow_moving_value": money(sum((Decimal(r["value"] or 0) for r in slow), Decimal(0))),
        "by_category": [{"category": k, "value": money(v)} for k, v in sorted(by_cat.items(), key=lambda kv: -kv[1])],
        "top": rows[:TOP],
    }


async def stock_value(conn: AsyncConnection, organization_id: uuid.UUID, *, as_of: datetime.date,
                      project_ids: set[uuid.UUID] | None, site_id: uuid.UUID | None = None) -> dict[str, Any]:
    from mesiri.infrastructure.postgres.repositories.materials import PostgresMaterialReadRepository

    summary = await PostgresMaterialReadRepository(conn).get_stock_summary(
        organization_id, date_from=as_of - datetime.timedelta(days=SLOW_DAYS - 1), date_to=as_of,
        project_ids=project_ids, site_id=site_id)
    rows = value_rows(summary, await average_rates(conn, organization_id, as_of))
    return {"as_of": as_of.isoformat(), **summarise(rows), "rows": rows}
