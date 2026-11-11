"""PRC-51 (covers PRC-15): a supplier's price list -- per material, what it last quoted and what we last paid it.

Read only, nothing stored. **Quoted**: the supplier's newest quote line for the material (``rfq_quote_lines`` of an
``rfq_vendors`` row it answered, the RFQ not cancelled), per the material's stock unit, its GST as said; live while its
``valid_until`` has not passed, or, when the quote gave no date, for ``UNDATED_DAYS`` after it was recorded. **Paid**:
the supplier's last delivery with a rate, by the Rates rule (``rates.fetch_purchases`` / ``cost_rate``), so the price
list and the Rates page never disagree. Both rates are compared as they cost the company (D-CC8, ``gst.split``); the
quote's rate as entered and its GST travel with it so the order dialog can fill both.
"""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.domains.procurement import gst
from mesiri.domains.procurement import rates as rate_store
from mesiri.domains.procurement.orders import ref as order_ref
from mesiri.domains.procurement.rfqs import ref as rfq_ref

#: A quote without a "valid until" is taken as live this many days after it was recorded.
UNDATED_DAYS = 30

_QUOTES = """
    SELECT DISTINCT ON (l.material_id)
           l.material_id, m.name AS material_name, un.code AS unit, ql.id AS quote_line_id,
           ql.rate, ql.gst_percent, ql.rate_includes_gst, ql.brand, v.gstin AS vendor_gstin,
           rv.valid_until, rv.quoted_at, q.id AS rfq_id, q.number AS rfq_number, q.project_id, q.site_id
      FROM rfq_quote_lines ql
      JOIN rfq_vendors rv ON rv.id = ql.rfq_vendor_id
      JOIN rfq_lines l ON l.id = ql.rfq_line_id
      JOIN rfqs q ON q.id = rv.rfq_id
      JOIN vendors v ON v.id = rv.vendor_id
      JOIN materials_catalog m ON m.id = l.material_id
      JOIN units_of_measure un ON un.id = l.unit_id
     WHERE rv.organization_id = :org AND rv.vendor_id = :vendor AND rv.status = 'quoted'
       AND q.status <> 'cancelled'
     ORDER BY l.material_id, rv.quoted_at DESC NULLS LAST, q.number DESC
"""


async def fetch_quotes(conn: AsyncConnection, org: uuid.UUID, vendor_id: uuid.UUID) -> list[dict]:
    """The supplier's newest quote line per material."""
    return [dict(r) for r in (await conn.execute(text(_QUOTES), {"org": org, "vendor": vendor_id})).mappings().all()]


def is_live(quote: dict, today: datetime.date) -> bool:
    if quote["valid_until"] is not None:
        return quote["valid_until"] >= today
    quoted = quote["quoted_at"]
    return quoted is not None and (today - quoted.date()).days <= UNDATED_DAYS


def quote_out(quote: dict, today: datetime.date) -> dict:
    g = gst.split(quote["rate"], quote["gst_percent"], quote["rate_includes_gst"], supplier_gstin=quote["vendor_gstin"])
    valid = quote["valid_until"]
    return {
        "rate": gst.money(g.cost), **gst.out(g),
        "brand": quote["brand"],
        "valid_until": valid.isoformat() if valid else None,
        "quoted_on": quote["quoted_at"].date().isoformat() if quote["quoted_at"] else None,
        "live": is_live(quote, today),
        "rfq_id": str(quote["rfq_id"]), "rfq_ref": rfq_ref(quote["rfq_number"]),
        "quote_line_id": str(quote["quote_line_id"]),
    }


def paid_out(row: dict) -> dict:
    return {
        "rate": gst.money(rate_store.cost_rate(row)), **gst.out(rate_store.gst_of(row)),
        "date": row["occurred_date"].isoformat(),
        "order_id": str(row["order_id"]) if row.get("order_id") else None,
        "order_ref": order_ref(row["order_number"]) if row.get("order_number") else None,
    }


def build(quotes: list[dict], purchases: list[dict], today: datetime.date) -> list[dict]:
    """One row per material the supplier quoted or delivered: live quotes first, then by name. ``purchases`` oldest
    first (as ``fetch_purchases`` returns them), so the last one per material wins."""
    rows: dict[str, dict] = {}
    for p in purchases:
        key = str(p["material_id"])
        rows[key] = {"material_id": key, "material_name": p["material_name"], "unit": p["unit"],
                     "quoted": rows.get(key, {}).get("quoted"), "paid": paid_out(p)}
    for q in quotes:
        key = str(q["material_id"])
        row = rows.setdefault(key, {"material_id": key, "material_name": q["material_name"], "unit": q["unit"],
                                    "paid": None})
        row["quoted"] = quote_out(q, today)
    for row in rows.values():
        row.setdefault("quoted", None)
    return sorted(rows.values(), key=lambda r: (not (r["quoted"] and r["quoted"]["live"]), r["material_name"].lower()))
