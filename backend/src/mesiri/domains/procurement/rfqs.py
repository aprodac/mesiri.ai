"""PRC-40..43: requests for quotation -- ask several suppliers, record what each quoted, compare, award into orders.

Storage and the rules that decide what an RFQ shows; the routes are in ``rfqs_router.py``. An RFQ is for one site (where
it is delivered), with lines in each material's stock unit, and the suppliers asked. A supplier's answer is its quote:
a rate per stock unit per line (with GST said as on a delivery, PRC-34), its terms, or a refusal.

**The comparison** (one rule, read by the page, the WhatsApp answer and the award): every quoted rate becomes what a unit
costs the company (``gst.split``, D-CC8: before GST from a supplier with a GSTIN, with GST from one without), so
quotes with and without GST, from registered and unregistered shops, compare as they really cost. Per line the
cheapest is marked; per supplier the total of what it quoted. Two ways to buy are priced:

- **one supplier** (``lowest_total``): the cheapest supplier among those who quoted every line;
- **cheapest per line** (``lowest_per_line``): each line from its cheapest supplier; the saving against one supplier
  and how many deliveries that means are said, so the person weighs it.

Stored status: open, awarded (orders placed from it), closed (no order), cancelled. Shown status adds what the quotes
say: ``open`` (waiting for quotes), ``ready`` (every asked supplier answered, or the due date passed with a quote in).
"""

from __future__ import annotations

import datetime
import uuid
from collections import defaultdict
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.domains.procurement import gst

STATUSES = ("open", "awarded", "closed", "cancelled")


def ref(number: int) -> str:
    return f"RFQ-{number:04d}"


def _num(value: Any) -> str:
    return f"{Decimal(value).normalize():f}" if value is not None else "0"


async def next_number(conn: AsyncConnection, organization_id: uuid.UUID) -> int:
    await conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                       {"key": f"rfqs:{organization_id}"})
    row = (await conn.execute(text("SELECT COALESCE(MAX(number), 0) + 1 FROM rfqs WHERE organization_id = :org"),
                              {"org": organization_id})).first()
    return int(row[0])  # type: ignore[index]


async def insert_rfq(conn: AsyncConnection, organization_id: uuid.UUID, *, project_id: uuid.UUID, site_id: uuid.UUID,
                     request_id: uuid.UUID | None, due_date: datetime.date | None, needed_by: datetime.date | None,
                     terms: str | None, notes: str | None, created_by: uuid.UUID, lines: list[dict],
                     vendor_ids: list[uuid.UUID]) -> uuid.UUID:
    number = await next_number(conn, organization_id)
    rfq_id = uuid.uuid4()
    await conn.execute(text(
        """
        INSERT INTO rfqs (id, organization_id, number, project_id, site_id, request_id, due_date, needed_by, terms,
                          notes, created_by)
        VALUES (:id, :org, :number, :project, :site, :request, :due, :needed, :terms, :notes, :by)
        """), {"id": rfq_id, "org": organization_id, "number": number, "project": project_id, "site": site_id,
               "request": request_id, "due": due_date, "needed": needed_by, "terms": terms, "notes": notes,
               "by": created_by})
    await insert_lines(conn, organization_id, rfq_id, lines)
    for vendor_id in vendor_ids:
        await add_vendor(conn, organization_id, rfq_id, vendor_id)
    return rfq_id


async def insert_lines(conn: AsyncConnection, organization_id: uuid.UUID, rfq_id: uuid.UUID, lines: list[dict]) -> None:
    for position, line in enumerate(lines):
        await conn.execute(text(
            """
            INSERT INTO rfq_lines (organization_id, rfq_id, material_id, unit_id, quantity, said, request_line_id, position)
            VALUES (:org, :rfq, :material, :unit, :quantity, :said, :request_line, :position)
            """), {"org": organization_id, "rfq": rfq_id, "material": line["material_id"], "unit": line["unit_id"],
                   "quantity": line["quantity"], "said": line.get("said"), "request_line": line.get("request_line_id"),
                   "position": position})


async def add_vendor(conn: AsyncConnection, organization_id: uuid.UUID, rfq_id: uuid.UUID,
                     vendor_id: uuid.UUID) -> uuid.UUID:
    """The supplier on the RFQ (once): its row, new or the one already there."""
    row = (await conn.execute(text(
        "INSERT INTO rfq_vendors (organization_id, rfq_id, vendor_id) VALUES (:org, :rfq, :vendor) "
        "ON CONFLICT (rfq_id, vendor_id) DO UPDATE SET vendor_id = EXCLUDED.vendor_id RETURNING id"),
        {"org": organization_id, "rfq": rfq_id, "vendor": vendor_id})).first()
    return row[0]  # type: ignore[index]


async def save_quote(conn: AsyncConnection, organization_id: uuid.UUID, rfq_vendor_id: uuid.UUID, *, lines: list[dict],
                     valid_until: datetime.date | None, delivery_days: int | None, payment_days: int | None,
                     their_ref: str | None, notes: str | None, source: str, user_id: uuid.UUID,
                     photo_key: str | None = None) -> None:
    """A supplier's quote: its lines replace any said before (a revised quote), its terms are kept."""
    await conn.execute(text(
        """
        UPDATE rfq_vendors SET status = 'quoted', decline_reason = NULL, quoted_at = now(), quoted_by = :by,
               valid_until = :valid, delivery_days = :delivery, payment_days = :payment, their_ref = :ref,
               quote_notes = :notes, quote_source = :source, quote_photo_key = COALESCE(:photo, quote_photo_key)
         WHERE id = :id
        """), {"id": rfq_vendor_id, "by": user_id, "valid": valid_until, "delivery": delivery_days,
               "payment": payment_days, "ref": their_ref, "notes": notes, "source": source, "photo": photo_key})
    for line in lines:
        await conn.execute(text(
            """
            INSERT INTO rfq_quote_lines (organization_id, rfq_vendor_id, rfq_line_id, rate, gst_percent,
                                         rate_includes_gst, brand, remark)
            VALUES (:org, :rv, :line, :rate, :gst, :incl, :brand, :remark)
            ON CONFLICT (rfq_vendor_id, rfq_line_id) DO UPDATE SET rate = EXCLUDED.rate,
                gst_percent = EXCLUDED.gst_percent, rate_includes_gst = EXCLUDED.rate_includes_gst,
                brand = EXCLUDED.brand, remark = EXCLUDED.remark
            """), {"org": organization_id, "rv": rfq_vendor_id, "line": line["rfq_line_id"], "rate": line["rate"],
                   "gst": line.get("gst_percent"), "incl": line.get("rate_includes_gst"), "brand": line.get("brand"),
                   "remark": line.get("remark")})


async def set_status(conn: AsyncConnection, rfq_id: uuid.UUID, status: str, user_id: uuid.UUID, note: str | None) -> None:
    await conn.execute(text(
        "UPDATE rfqs SET status = :status, status_note = :note, status_by = :user, status_at = now(), "
        "updated_at = now() WHERE id = :id"), {"status": status, "note": note, "user": user_id, "id": rfq_id})


async def fetch_rfqs(conn: AsyncConnection, organization_id: uuid.UUID, *, project_ids: set[uuid.UUID] | None,
                     rfq_id: uuid.UUID | None = None, lock: bool = False) -> list[dict]:
    """RFQs with their lines, suppliers and quote lines, newest first."""
    sql = """
        SELECT q.*, p.name AS project_name, s.name AS site_name, u.full_name AS created_by_name,
               sb.full_name AS status_by_name, r.number AS request_number
          FROM rfqs q JOIN projects p ON p.id = q.project_id JOIN sites s ON s.id = q.site_id
          LEFT JOIN users u ON u.id = q.created_by LEFT JOIN users sb ON sb.id = q.status_by
          LEFT JOIN material_requests r ON r.id = q.request_id
         WHERE q.organization_id = :org"""
    params: dict = {"org": organization_id}
    if rfq_id is not None:
        sql += " AND q.id = :id"
        params["id"] = rfq_id
    if project_ids is not None:
        sql += " AND q.project_id = ANY(:projects)"
        params["projects"] = list(project_ids)
    sql += " ORDER BY q.number DESC"
    if lock:
        sql += " FOR UPDATE OF q"
    rows = [dict(r) for r in (await conn.execute(text(sql), params)).mappings().all()]
    if not rows:
        return []
    ids = [r["id"] for r in rows]
    lines = (await conn.execute(text(
        """
        SELECT l.*, m.name AS material, un.code AS unit,
               COALESCE(pc.name, c.name) AS main_category, rl.request_id
          FROM rfq_lines l JOIN materials_catalog m ON m.id = l.material_id
          JOIN units_of_measure un ON un.id = l.unit_id
          LEFT JOIN material_categories c ON c.id = m.category_id
          LEFT JOIN material_categories pc ON pc.id = c.parent_id
          LEFT JOIN material_request_lines rl ON rl.id = l.request_line_id
         WHERE l.rfq_id = ANY(:ids) ORDER BY l.position
        """), {"ids": ids})).mappings().all()
    vendors = (await conn.execute(text(
        """
        SELECT rv.*, v.name AS vendor_name, v.phone AS vendor_phone, v.gstin AS vendor_gstin
          FROM rfq_vendors rv JOIN vendors v ON v.id = rv.vendor_id
         WHERE rv.rfq_id = ANY(:ids) ORDER BY rv.created_at, v.name
        """), {"ids": ids})).mappings().all()
    quotes = (await conn.execute(text(
        """
        SELECT ql.*, rv.rfq_id FROM rfq_quote_lines ql JOIN rfq_vendors rv ON rv.id = ql.rfq_vendor_id
         WHERE rv.rfq_id = ANY(:ids)
        """), {"ids": ids})).mappings().all()
    orders = (await conn.execute(text(
        "SELECT id, number, vendor_id, rfq_id, status FROM purchase_orders WHERE rfq_id = ANY(:ids) ORDER BY number"),
        {"ids": ids})).mappings().all()
    by: dict[str, dict[Any, list]] = {"lines": defaultdict(list), "vendors": defaultdict(list),
                                      "quotes": defaultdict(list), "orders": defaultdict(list)}
    for line in lines:
        by["lines"][line["rfq_id"]].append(dict(line))
    for v in vendors:
        by["vendors"][v["rfq_id"]].append(dict(v))
    for q in quotes:
        by["quotes"][q["rfq_id"]].append(dict(q))
    for o in orders:
        by["orders"][o["rfq_id"]].append(dict(o))
    for r in rows:
        r["lines"], r["vendors"] = by["lines"][r["id"]], by["vendors"][r["id"]]
        r["quotes"], r["orders"] = by["quotes"][r["id"]], by["orders"][r["id"]]
    return rows


def _money(v: Decimal | None) -> str | None:
    return gst.money(v)


def compare(row: dict, *, last_paid: dict[str, dict] | None = None) -> dict:
    """The comparison sheet of one RFQ (see the module): per line each supplier's quote and the cheapest, per supplier
    its total, and the two ways to buy. ``last_paid``: per material id, the last delivery's cost rate (Rates)."""
    vendors = {str(v["id"]): v for v in row["vendors"]}
    quotes: dict[tuple[str, str], dict] = {}
    for q in row["quotes"]:
        v = vendors.get(str(q["rfq_vendor_id"]))
        if v is None or v["status"] != "quoted":
            continue
        g = gst.split(q["rate"], q["gst_percent"], q["rate_includes_gst"], supplier_gstin=v["vendor_gstin"])
        quotes[(str(q["rfq_line_id"]), str(q["rfq_vendor_id"]))] = {"row": q, "gst": g}
    lines_out = []
    best_per_line: dict[str, tuple[str, Decimal]] = {}
    totals: dict[str, dict] = {key: {"cost": Decimal(0), "with_gst": Decimal(0), "lines": 0, "lowest": 0}
                               for key, v in vendors.items() if v["status"] == "quoted"}
    for line in row["lines"]:
        lid, qty = str(line["id"]), Decimal(line["quantity"])
        cells = []
        for key in totals:
            q = quotes.get((lid, key))
            if q is None:
                continue
            g = q["gst"]
            cells.append({"rfq_vendor_id": key, "quote_line_id": str(q["row"]["id"]), "cost": g.cost,
                          "amount": g.cost * qty, **gst.out(g),
                          "brand": q["row"]["brand"], "remark": q["row"]["remark"]})
            totals[key]["cost"] += g.cost * qty
            totals[key]["with_gst"] += g.with_gst * qty
            totals[key]["lines"] += 1
        cells.sort(key=lambda c: c["cost"])
        if cells:
            best_per_line[lid] = (cells[0]["rfq_vendor_id"], cells[0]["cost"])
            totals[cells[0]["rfq_vendor_id"]]["lowest"] += 1
        top = cells[-1]["cost"] if len(cells) > 1 else None
        paid = (last_paid or {}).get(str(line["material_id"]))
        lines_out.append({
            "id": lid, "material_id": str(line["material_id"]), "material": line["material"], "unit": line["unit"],
            "unit_id": str(line["unit_id"]), "quantity": _num(qty), "said": line["said"],
            "main_category": line["main_category"],
            "request_line_id": str(line["request_line_id"]) if line["request_line_id"] else None,
            "awarded_quote_line_id": str(line["awarded_quote_line_id"]) if line["awarded_quote_line_id"] else None,
            "award_reason": line["award_reason"],
            "quotes": [{**c, "cost": _money(c["cost"]), "amount": _money(c["amount"]),
                        "lowest": i == 0 and len(cells) > 1, "highest": top is not None and c["cost"] == top and i > 0,
                        "vs_last_paid_pct": None if not paid or not Decimal(paid["rate"]) else
                        str(((c["cost"] - Decimal(paid["rate"])) / Decimal(paid["rate"]) * 100).quantize(Decimal("0.1")))}
                       for i, c in enumerate(cells)],
            "last_paid": paid,
        })
    n_lines = len(row["lines"])
    complete = {k: t for k, t in totals.items() if t["lines"] == n_lines and n_lines}
    one = min(complete.items(), key=lambda kv: kv[1]["cost"]) if complete else None
    per_line_total = sum((cost * Decimal(next(x["quantity"] for x in row["lines"] if str(x["id"]) == lid))
                          for lid, (_, cost) in best_per_line.items()), Decimal(0))
    per_line_vendors = {k for k, _ in best_per_line.values()}
    suppliers = []
    for key, v in vendors.items():
        t = totals.get(key)
        suppliers.append({
            "rfq_vendor_id": key, "vendor_id": str(v["vendor_id"]), "name": v["vendor_name"], "phone": v["vendor_phone"],
            "gstin": v["vendor_gstin"], "status": v["status"], "sent_at": v["sent_at"].isoformat() if v["sent_at"] else None,
            "decline_reason": v["decline_reason"],
            "quoted_at": v["quoted_at"].isoformat() if v["quoted_at"] else None,
            "valid_until": v["valid_until"].isoformat() if v["valid_until"] else None,
            "delivery_days": v["delivery_days"], "payment_days": v["payment_days"], "their_ref": v["their_ref"],
            "notes": v["quote_notes"], "source": v["quote_source"], "has_photo": bool(v["quote_photo_key"]),
            "lines_quoted": t["lines"] if t else 0, "lines_lowest": t["lowest"] if t else 0,
            "total": _money(t["cost"]) if t else None, "total_with_gst": _money(t["with_gst"]) if t else None,
            "complete": key in complete, "best_total": one is not None and key == one[0],
        })
    suppliers.sort(key=lambda s: (s["status"] != "quoted", not s["complete"], Decimal(s["total"] or 0)))
    return {
        "lines": lines_out,
        "suppliers": suppliers,
        "lowest_total": None if one is None else {"rfq_vendor_id": one[0], "name": vendors[one[0]]["vendor_name"],
                                                  "total": _money(one[1]["cost"])},
        "lowest_per_line": None if not best_per_line else {
            "total": _money(per_line_total), "suppliers": len(per_line_vendors),
            "complete": len(best_per_line) == n_lines,
            "saves": _money(one[1]["cost"] - per_line_total) if one is not None and len(best_per_line) == n_lines else None,
        },
    }


def shown_status(row: dict, today: datetime.date) -> str:
    if row["status"] != "open":
        return row["status"]
    quoted = [v for v in row["vendors"] if v["status"] == "quoted"]
    waiting = [v for v in row["vendors"] if v["status"] == "invited"]
    if quoted and (not waiting or (row["due_date"] is not None and row["due_date"] < today)):
        return "ready"
    return "open"


def describe(row: dict, today: datetime.date, *, with_money: bool, last_paid: dict | None = None) -> dict:
    status = shown_status(row, today)
    sheet = compare(row, last_paid=last_paid)
    if not with_money:  # the people who do not see rates see who quoted, not what
        for line in sheet["lines"]:
            line["quotes"] = [{"rfq_vendor_id": q["rfq_vendor_id"], "lowest": q["lowest"]} for q in line["quotes"]]
            line["last_paid"] = None
        for s in sheet["suppliers"]:
            s["total"] = s["total_with_gst"] = None
        sheet["lowest_total"] = sheet["lowest_per_line"] = None
    counts = {k: sum(1 for v in row["vendors"] if v["status"] == k) for k in ("invited", "quoted", "declined")}
    due = row["due_date"]
    return {
        "id": str(row["id"]), "number": row["number"], "ref": ref(row["number"]),
        "project_id": str(row["project_id"]), "project_name": row["project_name"],
        "site_id": str(row["site_id"]), "site_name": row["site_name"],
        "request": None if not row["request_id"] else {"id": str(row["request_id"]),
                                                        "ref": f"REQ-{row['request_number']:04d}"},
        "status": status, "due_date": due.isoformat() if due else None,
        "due_days": (due - today).days if due else None,
        "needed_by": row["needed_by"].isoformat() if row["needed_by"] else None,
        "terms": row["terms"], "notes": row["notes"], "status_note": row["status_note"],
        "status_by_name": row["status_by_name"], "status_at": row["status_at"].isoformat() if row["status_at"] else None,
        "created_by_name": row["created_by_name"], "created_at": row["created_at"].isoformat(),
        "counts": counts,
        "orders": [{"id": str(o["id"]), "ref": f"PO-{o['number']:04d}", "status": o["status"]} for o in row["orders"]],
        **sheet,
    }
