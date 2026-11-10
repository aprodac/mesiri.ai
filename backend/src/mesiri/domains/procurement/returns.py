"""PRC-46: material sent back to the supplier, and the debit note that says what they now owe the company.

A return is one supplier, one site, one or more lines; its number is the debit note's (DN-0001 per company). Lines
start from:

- **a GRN's rejected quantity** (``grn_line_id``): turned away at the gate, so never in stock: nothing leaves stock;
- **a delivery** (``receipt_id``, from Movements or the supplier page): it was in stock, so it leaves stock as a
  ``RETURN_TO_VENDOR`` use, posted by ``materials.router.record_outflow`` (the one posting path);
- **the supplier page / WhatsApp** with just the material: taken from the site's stock as above, linked to the last
  delivery of it from that supplier at that site when there is one (its rate is the default).

**The debit note** lowers what the company owes the supplier at once (D-P2-3): a ``debit_note`` line on the supplier
ledger (``vendors/ledger.py``), worth each line's quantity x rate with GST as the delivery had it (PRC-34; GST not
known: the rate as recorded). Settled later by a replacement delivery or by credit on the next bill or payment; the
note itself stays.

**Status:** waiting (for pickup) -> sent (back) -> settled; cancelled only while waiting (the stock it took is put
back by the existing reversal, ``reverse_material_record``).
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.domains.procurement import gst

REASONS: dict[str, str] = {
    "damaged": "Damaged",
    "short": "Short",
    "wrong_size": "Wrong size",
    "excess": "Excess",
    "quality_failed": "Quality failed",
}
STATUSES = ("waiting", "sent", "settled", "cancelled")
LOOK = {"waiting": "Waiting for pickup", "sent": "Sent back", "settled": "Settled", "cancelled": "Cancelled"}


def ref(number: int) -> str:
    return f"DN-{number:04d}"


def num(value: Any) -> str:
    return f"{Decimal(value).normalize():f}" if value is not None else "0"


def line_money(quantity: Decimal, rate: Decimal | None, percent: Decimal | None, includes: bool | None,
               supplier_gstin: str | None) -> dict[str, Decimal] | None:
    """What one returned line is worth on the debit note: before GST, the GST and the total the supplier charged.
    None without a rate. GST not known: the rate as recorded is the total (and no GST is shown)."""
    if rate is None:
        return None
    g = gst.split(rate, percent, includes, supplier_gstin=supplier_gstin)
    before, total = g.before_gst * quantity, g.with_gst * quantity
    return {"before": before, "gst": total - before, "total": total}


async def next_number(conn: AsyncConnection, organization_id: uuid.UUID) -> int:
    await conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                       {"key": f"material_returns:{organization_id}"})
    return int((await conn.execute(text(
        "SELECT COALESCE(MAX(number), 0) + 1 FROM material_returns WHERE organization_id = :org"),
        {"org": organization_id})).scalar_one())


async def returned_from(conn: AsyncConnection, *, receipt_ids: list[uuid.UUID] | None = None,
                        grn_line_ids: list[uuid.UUID] | None = None) -> dict[str, Decimal]:
    """What is already on returns (not cancelled), per delivery or per GRN line: a line can't go back twice."""
    column, ids = ("receipt_id", receipt_ids) if receipt_ids is not None else ("grn_line_id", grn_line_ids)
    if not ids:
        return {}
    rows = (await conn.execute(text(
        f"SELECT l.{column} AS id, SUM(l.quantity) AS q FROM material_return_lines l "  # noqa: S608 -- fixed names
        f"JOIN material_returns r ON r.id = l.return_id WHERE l.{column} = ANY(:ids) AND r.status <> 'cancelled' "
        f"GROUP BY l.{column}"), {"ids": list(ids)})).all()
    return {str(r.id): Decimal(r.q) for r in rows}


_SELECT = """
    SELECT r.id, r.number, r.vendor_id, v.name AS vendor_name, v.phone AS vendor_phone, v.gstin AS vendor_gstin,
           v.address AS vendor_address, r.project_id, p.name AS project_name, r.site_id, s.name AS site_name,
           r.goods_receipt_id, g.number AS grn_number, po.id AS order_id, po.number AS order_number,
           r.status, r.returned_on, r.notes, r.photo_keys, r.source, r.sent_on, r.collected_by, r.settled_how,
           r.settled_receipt_id, r.settled_expense_id, e.expense_number AS settled_expense_number,
           r.settled_payment_id, r.settled_note, r.settled_on, r.cancel_reason, r.status_at,
           sb.full_name AS status_by_name, cb.full_name AS created_by_name, r.created_at
      FROM material_returns r
      JOIN vendors v ON v.id = r.vendor_id
      JOIN projects p ON p.id = r.project_id
      JOIN sites s ON s.id = r.site_id
      LEFT JOIN goods_receipts g ON g.id = r.goods_receipt_id
      LEFT JOIN purchase_orders po ON po.id = g.purchase_order_id
      LEFT JOIN expenses e ON e.id = r.settled_expense_id
      LEFT JOIN users sb ON sb.id = r.status_by
      LEFT JOIN users cb ON cb.id = r.created_by
     WHERE r.organization_id = :org
"""


async def fetch(conn: AsyncConnection, organization_id: uuid.UUID, *, project_ids: set[uuid.UUID] | None = None,
                return_id: uuid.UUID | None = None, vendor_id: uuid.UUID | None = None, lock: bool = False,
                until: datetime.date | None = None) -> list[dict[str, Any]]:
    """Returns with their lines, newest first (rows as stored, ``describe`` makes the API's shape)."""
    sql, params = _SELECT, {"org": organization_id}
    if return_id is not None:
        sql += " AND r.id = :id"
        params["id"] = return_id
    if vendor_id is not None:
        sql += " AND r.vendor_id = :vendor"
        params["vendor"] = vendor_id
    if project_ids is not None:
        sql += " AND r.project_id = ANY(:projects)"
        params["projects"] = list(project_ids)
    if until is not None:
        sql += " AND r.returned_on <= :until"
        params["until"] = until
    sql += " ORDER BY r.returned_on DESC, r.number DESC"
    if lock:
        sql += " FOR UPDATE OF r"
    rows = [dict(r) for r in (await conn.execute(text(sql), params)).mappings().all()]
    if not rows:
        return []
    lines = (await conn.execute(text(
        """
        SELECT l.id, l.return_id, l.material_id, m.name AS material, u.code AS unit, l.unit_id, l.quantity, l.rate,
               l.gst_percent, l.rate_includes_gst, l.reason, l.receipt_id, mr.occurred_date AS receipt_date,
               l.grn_line_id, l.usage_id, COALESCE(parent.name, cat.name) AS main_category
          FROM material_return_lines l
          JOIN materials_catalog m ON m.id = l.material_id
          JOIN units_of_measure u ON u.id = l.unit_id
          LEFT JOIN material_receipts mr ON mr.id = l.receipt_id
          LEFT JOIN material_categories cat ON cat.id = m.category_id
          LEFT JOIN material_categories parent ON parent.id = cat.parent_id
         WHERE l.return_id = ANY(:ids)
         ORDER BY l.position
        """), {"ids": [r["id"] for r in rows]})).mappings().all()
    by: dict[uuid.UUID, list[dict]] = {}
    for line in lines:
        by.setdefault(line["return_id"], []).append(dict(line))
    for r in rows:
        r["lines"] = by.get(r["id"], [])
    return rows


def totals(row: dict[str, Any]) -> dict[str, Decimal]:
    """The debit note's money: before GST, GST, total (lines without a rate count as nothing, ``unpriced``)."""
    out = {"before": Decimal(0), "gst": Decimal(0), "total": Decimal(0), "unpriced": Decimal(0)}
    for line in row["lines"]:
        m = line_money(Decimal(line["quantity"]), line["rate"], line["gst_percent"], line["rate_includes_gst"],
                       row.get("vendor_gstin"))
        if m is None:
            out["unpriced"] += 1
            continue
        for k in ("before", "gst", "total"):
            out[k] += m[k]
    return out


def what(row: dict[str, Any]) -> str:
    """The lines in words: "12 nos TMT bar 12 mm (damaged), 3 bags Cement (short)"."""
    return ", ".join(f"{num(x['quantity'])} {x['unit']} {x['material']} ({REASONS[x['reason']].lower()})"
                     for x in row["lines"])


def describe(row: dict[str, Any], *, with_money: bool) -> dict[str, Any]:
    t = totals(row)
    timeline = [{"on": row["returned_on"].isoformat(), "what": f"Return recorded{' from ' + _grn(row) if row['goods_receipt_id'] else ''}",
                 "by": row["created_by_name"]}]
    if row["sent_on"]:
        timeline.append({"on": row["sent_on"].isoformat(), "what": "Sent back"
                         + (f", collected by {row['collected_by']}" if row["collected_by"] else ""), "by": None})
    if row["status"] == "settled":
        how = "by a replacement delivery" if row["settled_how"] == "replacement" else (
            f"by credit on {row['settled_expense_number']}" if row["settled_expense_number"] else "by credit")
        timeline.append({"on": (row["settled_on"] or row["status_at"].date()).isoformat(),
                         "what": f"Settled {how}" + (f": {row['settled_note']}" if row["settled_note"] else ""),
                         "by": row["status_by_name"]})
    if row["status"] == "cancelled":
        timeline.append({"on": row["status_at"].date().isoformat(), "what": f"Cancelled: {row['cancel_reason']}",
                         "by": row["status_by_name"]})
    lines = []
    for x in row["lines"]:
        m = line_money(Decimal(x["quantity"]), x["rate"], x["gst_percent"], x["rate_includes_gst"], row["vendor_gstin"])
        lines.append({
            "id": str(x["id"]), "material_id": str(x["material_id"]), "material": x["material"], "unit": x["unit"],
            "unit_id": str(x["unit_id"]), "main_category": x["main_category"], "quantity": num(x["quantity"]),
            "reason": x["reason"], "reason_label": REASONS[x["reason"]],
            "receipt_id": str(x["receipt_id"]) if x["receipt_id"] else None,
            "receipt_date": x["receipt_date"].isoformat() if x["receipt_date"] else None,
            "grn_line_id": str(x["grn_line_id"]) if x["grn_line_id"] else None,
            "from_stock": x["usage_id"] is not None,
            **({"rate": gst.money(x["rate"]), "gst_percent": num(x["gst_percent"]) if x["gst_percent"] is not None else None,
                "rate_includes_gst": x["rate_includes_gst"],
                "amount": gst.money(m["total"]) if m else None} if with_money else {}),
        })
    return {
        "id": str(row["id"]), "number": row["number"], "ref": ref(row["number"]), "status": row["status"],
        "status_label": LOOK[row["status"]], "vendor_id": str(row["vendor_id"]), "vendor_name": row["vendor_name"],
        "vendor_phone": row["vendor_phone"], "vendor_gstin": row["vendor_gstin"], "vendor_address": row["vendor_address"],
        "project_id": str(row["project_id"]), "project_name": row["project_name"], "site_id": str(row["site_id"]),
        "site_name": row["site_name"], "grn_id": str(row["goods_receipt_id"]) if row["goods_receipt_id"] else None,
        "grn_ref": _grn(row) if row["goods_receipt_id"] else None,
        "order_id": str(row["order_id"]) if row["order_id"] else None,
        "order_ref": f"PO-{row['order_number']:04d}" if row["order_number"] else None,
        "returned_on": row["returned_on"].isoformat(), "notes": row["notes"], "source": row["source"],
        "photos": len(row["photo_keys"] or []), "sent_on": row["sent_on"].isoformat() if row["sent_on"] else None,
        "collected_by": row["collected_by"], "settled_how": row["settled_how"],
        "settled_receipt_id": str(row["settled_receipt_id"]) if row["settled_receipt_id"] else None,
        "settled_expense_id": str(row["settled_expense_id"]) if row["settled_expense_id"] else None,
        "settled_expense_number": row["settled_expense_number"],
        "settled_payment_id": str(row["settled_payment_id"]) if row["settled_payment_id"] else None,
        "settled_note": row["settled_note"], "settled_on": row["settled_on"].isoformat() if row["settled_on"] else None,
        "cancel_reason": row["cancel_reason"], "created_by_name": row["created_by_name"],
        "created_at": row["created_at"].isoformat(), "what": what(row), "lines": lines, "timeline": timeline,
        **({"before_gst": gst.money(t["before"]), "gst": gst.money(t["gst"]), "total": gst.money(t["total"]),
            "unpriced_lines": int(t["unpriced"])} if with_money else {}),
    }


def _grn(row: dict[str, Any]) -> str:
    return f"GRN-{row['grn_number']:04d}"


async def ledger_lines(conn: AsyncConnection, organization_id: uuid.UUID, *, vendor_id: uuid.UUID | None,
                       projects: set[uuid.UUID] | None, until: datetime.date | None) -> list[dict[str, Any]]:
    """Every debit note not cancelled, as the supplier ledger's lines (D-P2-3: it lowers what is owed at once)."""
    rows = await fetch(conn, organization_id, project_ids=projects, vendor_id=vendor_id, until=until)
    out = []
    for r in rows:
        if r["status"] == "cancelled":
            continue
        t = totals(r)
        if t["total"] <= 0:
            continue
        settled = {"replacement": "replaced", "credit": "credit given"}.get(r["settled_how"] or "", "")
        out.append({
            "id": f"debit_note:{r['id']}", "vendor_id": r["vendor_id"], "date": r["returned_on"],
            "created_at": r["created_at"], "kind": "debit_note", "title": f"Debit note {ref(r['number'])}",
            "detail": " · ".join(x for x in (f"Returned: {what(r)}", LOOK[r["status"]].lower() if not settled else settled)
                                 if x),
            "owe": Decimal(0), "paid": t["total"], "project_id": r["project_id"], "project": r["project_name"],
            "site": r["site_name"], "ref": ref(r["number"]), "links": {"return_id": str(r["id"])},
        })
    return out
