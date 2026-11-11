"""PRC-14: what each item cost, from which supplier, over time.

Read-only over deliveries (``material_receipts``): every delivery with a rate, not taken back, not a move between
sites. A delivery's rate is per the material's stock unit already (a rate said per load or per bar is converted when
it is saved, ``materials.router._convert_to_stock_unit``), so rates of one item compare as they are. The rate is the
one recorded, compared as it costs the company (PRC-34, ``gst.py``): before GST when the supplier has a GSTIN, with GST
when not; a delivery whose GST is not known is compared as entered and counted in ``gst_unknown``.

A supplier is the vendor record when the delivery has one, else the supplier name as typed (trimmed, any case), so
"Malabar" typed on WhatsApp and the vendor "Malabar" picked on the dashboard stay two rows until the name is linked.
"""

from __future__ import annotations

import datetime
import uuid
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.domains.procurement import gst
from mesiri.domains.procurement.orders import ref as order_ref

#: A rate change smaller than this (per cent) is "about the same", not a rise or a fall.
STEADY_PCT = Decimal("2")

#: CC-09 (D-CC3): a delivery is *billed* when its supplier bill made an expense that still stands. Until then the
#: delivery itself is what the company owes (the supplier ledger) and what it cost (CC-01). One rule, read by the
#: ledger, the cost page and here; a bill recorded without a price (no expense) or taken back leaves it unbilled.
BILLED_SQL = (
    "EXISTS (SELECT 1 FROM material_invoices bi JOIN expenses be ON be.id = bi.expense_id "
    "WHERE bi.id = r.invoice_id AND be.workflow_status = 'confirmed')"
)

_PURCHASES = """
    SELECT r.id, r.material_id, mc.name AS material_name, COALESCE(u.code, r.unit) AS unit,
           mc.category_id::text AS category_id,
           CASE WHEN parent.name IS NOT NULL THEN parent.name || ' › ' || cat.name ELSE cat.name END AS category,
           COALESCE(parent.name, cat.name) AS main_category,
           r.project_id, p.name AS project_name, r.site_id, s.name AS site_name,
           r.occurred_date, r.created_at, r.quantity, r.unit_cost, r.total_cost,
           r.gst_percent, r.rate_includes_gst, v.gstin AS vendor_gstin,
           r.vendor_id, v.name AS vendor_record_name, NULLIF(trim(r.supplier), '') AS supplier,
           r.invoice_id, inv.invoice_number, r.purchase_order_line_id,
           po.id AS order_id, po.number AS order_number, pol.rate AS ordered_rate, r.source,
           """ + BILLED_SQL + """ AS billed
      FROM material_receipts r
      JOIN materials_catalog mc ON mc.id = r.material_id
      LEFT JOIN units_of_measure u ON u.id = mc.default_unit_id
      LEFT JOIN material_categories cat ON cat.id = mc.category_id
      LEFT JOIN material_categories parent ON parent.id = cat.parent_id
      LEFT JOIN projects p ON p.id = r.project_id
      LEFT JOIN sites s ON s.id = r.site_id
      LEFT JOIN vendors v ON v.id = r.vendor_id
      LEFT JOIN material_invoices inv ON inv.id = r.invoice_id
      LEFT JOIN purchase_order_lines pol ON pol.id = r.purchase_order_line_id
      LEFT JOIN purchase_orders po ON po.id = pol.purchase_order_id
     WHERE r.organization_id = :org
       AND r.unit_cost IS NOT NULL AND r.quantity > 0
       AND r.movement_reason = 'RECEIVED'
       AND r.transfer_id IS NULL
       AND r.reverses_movement_id IS NULL
       AND NOT EXISTS (SELECT 1 FROM material_usage x WHERE x.reverses_movement_id = r.id)
       AND NOT EXISTS (SELECT 1 FROM material_receipts y WHERE y.reverses_movement_id = r.id)
"""


def _money(value: Decimal | None) -> str | None:
    return None if value is None else str(Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _qty(value: Decimal) -> str:
    return format(Decimal(value).normalize(), "f")


def gst_of(row: dict) -> gst.GstRate:
    return gst.split(row["unit_cost"], row.get("gst_percent"), row.get("rate_includes_gst"),
                     supplier_gstin=row.get("vendor_gstin"))


def cost_rate(row: dict) -> Decimal:
    """The rate every comparison here uses: what one unit costs the company (D-CC8)."""
    return gst_of(row).cost


def vendor_key(row: dict) -> str:
    if row.get("vendor_id"):
        return str(row["vendor_id"])
    name = (row.get("supplier") or "").strip().lower()
    return f"name:{name}" if name else "unknown"


def vendor_name(row: dict) -> str:
    return row.get("vendor_record_name") or row.get("supplier") or "Supplier not recorded"


def source_of(row: dict) -> str:
    if row.get("invoice_id"):
        return "bill"
    if row.get("purchase_order_line_id"):
        return "order"
    return "delivery"


async def fetch_purchases(
    conn: AsyncConnection,
    org: uuid.UUID,
    *,
    project_ids: set[uuid.UUID] | None,
    date_from: datetime.date | None,
    date_to: datetime.date,
    material_id: uuid.UUID | None = None,
    category_id: uuid.UUID | None = None,
    vendor_id: uuid.UUID | None = None,
) -> list[dict]:
    """Deliveries with a rate, oldest first. ``date_from`` None: everything up to ``date_to``. ``vendor_id``: only
    that supplier's deliveries (PRC-51 price list, PRC-50 performance)."""
    sql = _PURCHASES + " AND r.occurred_date <= :date_to"
    params: dict = {"org": org, "date_to": date_to}
    if date_from is not None:
        sql += " AND r.occurred_date >= :date_from"
        params["date_from"] = date_from
    if project_ids is not None:
        sql += " AND r.project_id = ANY(:projects)"
        params["projects"] = list(project_ids)
    if material_id is not None:
        sql += " AND r.material_id = :material"
        params["material"] = material_id
    if category_id is not None:
        sql += " AND (cat.id = :category OR cat.parent_id = :category)"
        params["category"] = category_id
    if vendor_id is not None:
        sql += " AND r.vendor_id = :vendor"
        params["vendor"] = vendor_id
    sql += " ORDER BY r.occurred_date, r.created_at"
    rows = (await conn.execute(text(sql), params)).mappings().all()
    return [dict(r) for r in rows]


async def fetch_before(
    conn: AsyncConnection, org: uuid.UUID, *, project_ids: set[uuid.UUID] | None, before: datetime.date,
    material_ids: list[uuid.UUID],
) -> dict[uuid.UUID, dict]:
    """The last delivery with a rate before the period, per material: what a rise or fall is measured from when an
    item was bought only once in the period."""
    if not material_ids:
        return {}
    sql = "SELECT DISTINCT ON (q.material_id) q.* FROM (" + _PURCHASES + " AND r.occurred_date < :before"
    params: dict = {"org": org, "before": before, "materials": material_ids}
    sql += " AND r.material_id = ANY(:materials)"
    if project_ids is not None:
        sql += " AND r.project_id = ANY(:projects)"
        params["projects"] = list(project_ids)
    sql += ") q ORDER BY q.material_id, q.occurred_date DESC, q.created_at DESC"
    rows = (await conn.execute(text(sql), params)).mappings().all()
    return {r["material_id"]: dict(r) for r in rows}


def _pct(new: Decimal, old: Decimal | None) -> str | None:
    if old is None or old <= 0:
        return None
    return str(((new - old) / old * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def purchase_out(row: dict) -> dict:
    g = gst_of(row)
    rate = g.cost
    ordered = row.get("ordered_rate")
    return {
        "id": str(row["id"]),
        "date": row["occurred_date"].isoformat(),
        "vendor_key": vendor_key(row),
        "vendor_id": str(row["vendor_id"]) if row.get("vendor_id") else None,
        "vendor_name": vendor_name(row),
        "project_id": str(row["project_id"]),
        "project_name": row.get("project_name") or "",
        "site_id": str(row["site_id"]) if row.get("site_id") else None,
        "site_name": row.get("site_name") or "",
        "quantity": _qty(row["quantity"]),
        "unit": row["unit"],
        "rate": _money(rate),
        "amount": _money(row["total_cost"] if row.get("total_cost") is not None else g.entered * Decimal(row["quantity"])),
        **gst.out(g),
        "source": source_of(row),
        "order_id": str(row["order_id"]) if row.get("order_id") else None,
        "order_ref": order_ref(row["order_number"]) if row.get("order_number") else None,
        "ordered_rate": _money(ordered),
        #: The delivery's rate is not what the order said (both known).
        "differs_from_order": ordered is not None and Decimal(ordered) != g.entered,
        "invoice_number": row.get("invoice_number"),
    }


def summarise(rows: list[dict], before: dict[uuid.UUID, dict]) -> list[dict]:
    """One entry per material: its rates in the period, per supplier, the trend, and what was paid above the
    cheapest supplier's average. ``rows`` oldest first."""
    by_material: dict[uuid.UUID, list[dict]] = defaultdict(list)
    for r in rows:
        by_material[r["material_id"]].append(r)
    out = []
    for material_id, list_ in by_material.items():
        first = list_[0]
        quantity = sum((Decimal(r["quantity"]) for r in list_), Decimal(0))
        spend = sum((cost_rate(r) * Decimal(r["quantity"]) for r in list_), Decimal(0))
        rates = [cost_rate(r) for r in list_]
        last = list_[-1]
        prev = list_[-2] if len(list_) > 1 else before.get(material_id)
        last_rate = cost_rate(last)
        prev_rate = cost_rate(prev) if prev else None

        vendors: dict[str, dict] = {}
        for r in list_:
            key = vendor_key(r)
            v = vendors.setdefault(key, {
                "key": key, "vendor_id": str(r["vendor_id"]) if r.get("vendor_id") else None, "name": vendor_name(r),
                "purchases": 0, "quantity": Decimal(0), "spend": Decimal(0), "min": None, "max": None})
            rate, q = cost_rate(r), Decimal(r["quantity"])
            v["purchases"] += 1
            v["quantity"] += q
            v["spend"] += rate * q
            v["min"] = rate if v["min"] is None else min(v["min"], rate)
            v["max"] = rate if v["max"] is None else max(v["max"], rate)
            v["last_rate"], v["last_date"] = rate, r["occurred_date"]
        for v in vendors.values():
            v["avg"] = v["spend"] / v["quantity"]
        ranked = sorted(vendors.values(), key=lambda v: (v["avg"], -v["purchases"]))
        best = ranked[0] if len(ranked) > 1 else None
        saving = max(Decimal(0), spend - quantity * best["avg"]) if best else Decimal(0)

        out.append({
            "material_id": str(material_id),
            "material_name": first["material_name"],
            "unit": first["unit"],
            "category_id": first.get("category_id"),
            "category": first.get("category"),
            "main_category": first.get("main_category"),
            "purchases": len(list_),
            #: PRC-34: deliveries compared as entered because their GST is not known.
            "gst_unknown": sum(1 for r in list_ if not gst_of(r).known),
            "quantity": _qty(quantity),
            "spend": _money(spend),
            "avg_rate": _money(spend / quantity),
            "min_rate": _money(min(rates)),
            "max_rate": _money(max(rates)),
            "last": {
                "rate": _money(last_rate), "date": last["occurred_date"].isoformat(), "vendor_key": vendor_key(last),
                "vendor_name": vendor_name(last), "site_name": last.get("site_name") or ""},
            "previous": None if prev is None else {
                "rate": _money(prev_rate), "date": prev["occurred_date"].isoformat(), "vendor_name": vendor_name(prev),
                "in_period": prev is not before.get(material_id)},
            "change_pct": _pct(last_rate, prev_rate),
            "trend": _trend(last_rate, prev_rate),
            "best": None if best is None else {"vendor_key": best["key"], "vendor_name": best["name"], "avg_rate": _money(best["avg"])},
            "above_best": _money(saving),
            "vendors": [
                {"key": v["key"], "vendor_id": v["vendor_id"], "name": v["name"], "purchases": v["purchases"],
                 "quantity": _qty(v["quantity"]), "spend": _money(v["spend"]), "avg_rate": _money(v["avg"]),
                 "min_rate": _money(v["min"]), "max_rate": _money(v["max"]), "last_rate": _money(v["last_rate"]),
                 "last_date": v["last_date"].isoformat(), "best": best is not None and v["key"] == best["key"]}
                for v in ranked
            ],
            "points": [{"date": r["occurred_date"].isoformat(), "rate": _money(cost_rate(r)),
                        "vendor_key": vendor_key(r)} for r in list_],
        })
    return out


def _trend(new: Decimal, old: Decimal | None) -> str | None:
    if old is None or old <= 0:
        return None
    pct = (new - old) / old * 100
    if pct > STEADY_PCT:
        return "up"
    if pct < -STEADY_PCT:
        return "down"
    return "same"
