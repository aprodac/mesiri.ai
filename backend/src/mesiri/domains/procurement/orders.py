"""PRC-06 / PRC-08: purchase orders -- what the office ordered from a supplier, and what has come against it.

Storage and the rules that decide what an order shows; the routes are in ``orders_router.py``. An order is for one
site, from one vendor. Each line's quantity is in the material's stock unit and its rate is per stock unit. A
delivery fills a line (``material_receipts.purchase_order_line_id``); what was received is always read from those
deliveries (a delivery taken back no longer counts), never typed, so the order can never disagree with stock.

Stored status: open, closed (the rest will not come), cancelled. Shown status adds what the deliveries say:
open (nothing yet), part (some), received (every line in full).
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

SOON_DAYS = 2


class OrderRuleError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def ref(number: int) -> str:
    return f"PO-{number:04d}"


def _num(value: Any) -> str:
    return f"{Decimal(value).normalize():f}" if value is not None else "0"


def _money(value: Decimal | None) -> str | None:
    return None if value is None else f"{value.quantize(Decimal('0.01')):f}"


async def check_delivery_line(conn: AsyncConnection, organization_id: uuid.UUID, line_id: uuid.UUID, *,
                              site_id: uuid.UUID | None, material_id: Any, reason: str) -> uuid.UUID:
    """A delivery may fill this order line: the company's, the same material and site, a receipt, the order still
    open. Returns the order's vendor (the delivery's supplier unless they named another)."""
    row = (await conn.execute(text(
        """
        SELECT l.material_id, o.site_id, o.status, o.vendor_id, o.number
          FROM purchase_order_lines l JOIN purchase_orders o ON o.id = l.purchase_order_id
         WHERE l.id = :id AND l.organization_id = :org
        """), {"id": line_id, "org": organization_id})).first()
    if row is None:
        raise OrderRuleError(404, "That order line was not found.")
    if reason != "RECEIVED":
        raise OrderRuleError(422, "Only a delivery (RECEIVED) can fill an order line.")
    if str(row.material_id) != str(material_id):
        raise OrderRuleError(422, f"{ref(row.number)}'s line is for another material.")
    if site_id is None or str(row.site_id) != str(site_id):
        raise OrderRuleError(422, f"{ref(row.number)} is for another site.")
    if row.status != "open":
        raise OrderRuleError(409, f"{ref(row.number)} is {row.status}; it takes no more deliveries.")
    return row.vendor_id


async def next_number(conn: AsyncConnection, organization_id: uuid.UUID) -> int:
    await conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                       {"key": f"purchase_orders:{organization_id}"})
    row = (await conn.execute(text(
        "SELECT COALESCE(MAX(number), 0) + 1 FROM purchase_orders WHERE organization_id = :org"),
        {"org": organization_id})).first()
    return int(row[0])  # type: ignore[index]


async def insert_order(conn: AsyncConnection, organization_id: uuid.UUID, *, project_id: uuid.UUID,
                       site_id: uuid.UUID, vendor_id: uuid.UUID, expected_date: datetime.date | None,
                       notes: str | None, created_by: uuid.UUID, raised_over_duplicate: bool,
                       lines: list[dict]) -> uuid.UUID:
    number = await next_number(conn, organization_id)
    order_id = uuid.uuid4()
    await conn.execute(text(
        """
        INSERT INTO purchase_orders (id, organization_id, number, project_id, site_id, vendor_id, expected_date, notes,
                                     created_by, raised_over_duplicate)
        VALUES (:id, :org, :number, :project, :site, :vendor, :expected, :notes, :by, :dup)
        """), {"id": order_id, "org": organization_id, "number": number, "project": project_id, "site": site_id,
               "vendor": vendor_id, "expected": expected_date, "notes": notes, "by": created_by,
               "dup": raised_over_duplicate})
    await insert_lines(conn, organization_id, order_id, lines)
    return order_id


async def insert_lines(conn: AsyncConnection, organization_id: uuid.UUID, order_id: uuid.UUID, lines: list[dict]) -> None:
    for position, line in enumerate(lines):
        await conn.execute(text(
            """
            INSERT INTO purchase_order_lines (organization_id, purchase_order_id, material_id, unit_id, quantity, rate,
                                              said, request_line_id, position)
            VALUES (:org, :order, :material, :unit, :quantity, :rate, :said, :request_line, :position)
            """), {"org": organization_id, "order": order_id, "material": line["material_id"],
                   "unit": line["unit_id"], "quantity": line["quantity"], "rate": line.get("rate"),
                   "said": line.get("said"), "request_line": line.get("request_line_id"), "position": position})


async def set_status(conn: AsyncConnection, order_id: uuid.UUID, status: str, user_id: uuid.UUID,
                     note: str | None) -> None:
    await conn.execute(text(
        "UPDATE purchase_orders SET status = :status, status_note = :note, status_by = :user, status_at = now(), "
        "updated_at = now() WHERE id = :id"), {"status": status, "note": note, "user": user_id, "id": order_id})


_SELECT = """
    SELECT o.id, o.number, o.project_id, p.name AS project_name, o.site_id, s.name AS site_name, o.vendor_id,
           v.name AS vendor_name, v.phone AS vendor_phone, o.status, o.expected_date, o.notes, o.status_note,
           o.raised_over_duplicate, o.created_by, cu.full_name AS created_by_name, o.created_at, o.updated_at,
           su.full_name AS status_by_name, o.status_at
      FROM purchase_orders o
      JOIN projects p ON p.id = o.project_id
      JOIN sites s ON s.id = o.site_id
      JOIN vendors v ON v.id = o.vendor_id
      LEFT JOIN users cu ON cu.id = o.created_by
      LEFT JOIN users su ON su.id = o.status_by
"""

#: A delivery counts unless it was taken back (a correction points at it, in either table).
_COUNTED = """
    NOT EXISTS (SELECT 1 FROM material_usage u WHERE u.reverses_movement_id = r.id)
    AND NOT EXISTS (SELECT 1 FROM material_receipts r2 WHERE r2.reverses_movement_id = r.id)
    AND r.reverses_movement_id IS NULL
"""


async def fetch_orders(conn: AsyncConnection, organization_id: uuid.UUID, *, project_ids: set[uuid.UUID] | None,
                       order_id: uuid.UUID | None = None, lock: bool = False) -> list[dict[str, Any]]:
    """Orders with their lines, what came against each line, and the deliveries (newest first, at most 500)."""
    sql = _SELECT + " WHERE o.organization_id = :org"
    params: dict[str, Any] = {"org": organization_id}
    if project_ids is not None:
        sql += " AND o.project_id = ANY(:projects)"
        params["projects"] = list(project_ids)
    if order_id is not None:
        sql += " AND o.id = :id"
        params["id"] = order_id
    sql += " ORDER BY o.created_at DESC LIMIT 500"
    if lock:
        sql += " FOR UPDATE OF o"
    rows = [dict(r._mapping) for r in (await conn.execute(text(sql), params)).all()]
    if not rows:
        return []
    ids = [r["id"] for r in rows]
    lines = (await conn.execute(text(
        f"""
        SELECT l.id, l.purchase_order_id, l.material_id, m.name AS material, l.unit_id, u.code AS unit,
               l.quantity, l.rate, l.said, l.request_line_id, l.position,
               COALESCE(pc.name, c.name) AS main_category, COALESCE(pc.id, c.id) AS main_category_id,
               c.id AS category_id, rq.id AS request_id, rq.number AS request_number, rq.status AS request_status,
               COALESCE((SELECT SUM(r.quantity) FROM material_receipts r WHERE r.purchase_order_line_id = l.id
                         AND {_COUNTED}), 0) AS received
          FROM purchase_order_lines l
          JOIN materials_catalog m ON m.id = l.material_id
          JOIN units_of_measure u ON u.id = l.unit_id
          LEFT JOIN material_categories c ON c.id = m.category_id
          LEFT JOIN material_categories pc ON pc.id = c.parent_id
          LEFT JOIN material_request_lines rl ON rl.id = l.request_line_id
          LEFT JOIN material_requests rq ON rq.id = rl.request_id
         WHERE l.purchase_order_id = ANY(:ids)
         ORDER BY l.position
        """), {"ids": ids})).all()
    deliveries = (await conn.execute(text(
        f"""
        SELECT l.purchase_order_id, r.id, r.purchase_order_line_id, r.quantity, r.occurred_date, r.created_at,
               uu.full_name AS by_name, m.name AS material, u.code AS unit
          FROM material_receipts r
          JOIN purchase_order_lines l ON l.id = r.purchase_order_line_id
          JOIN materials_catalog m ON m.id = l.material_id
          JOIN units_of_measure u ON u.id = l.unit_id
          LEFT JOIN users uu ON uu.id = r.created_by
         WHERE l.purchase_order_id = ANY(:ids) AND {_COUNTED}
         ORDER BY r.created_at
        """), {"ids": ids})).all()
    by_order: dict[uuid.UUID, list[dict]] = {}
    for line in lines:
        by_order.setdefault(line.purchase_order_id, []).append(dict(line._mapping))
    came: dict[uuid.UUID, list[dict]] = {}
    for d in deliveries:
        came.setdefault(d.purchase_order_id, []).append(dict(d._mapping))
    for row in rows:
        row["lines"] = by_order.get(row["id"], [])
        row["deliveries"] = came.get(row["id"], [])
    return rows


def shown_status(row: dict[str, Any]) -> str:
    """open / part / received from the deliveries; closed and cancelled as recorded."""
    if row["status"] != "open":
        return row["status"]
    lines = row["lines"]
    if lines and all(Decimal(line["received"]) >= Decimal(line["quantity"]) for line in lines):
        return "received"
    if any(Decimal(line["received"]) > 0 for line in lines):
        return "part"
    return "open"


def urgency(status: str, expected: datetime.date | None, today: datetime.date) -> str:
    if status not in ("open", "part"):
        return "closed"
    if expected is None:
        return "later"
    if expected < today:
        return "late"
    if (expected - today).days <= SOON_DAYS:
        return "soon"
    return "later"


def describe(rows: list[dict[str, Any]], *, today: datetime.date, with_money: bool,
             all_orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each order as the page (and later the assistant) shows it. Rates and amounts only ``with_money``."""
    open_by_material: dict[tuple, list[dict]] = {}
    for other in all_orders:
        if shown_status(other) in ("open", "part"):
            for line in other["lines"]:
                open_by_material.setdefault((other["project_id"], line["material_id"]), []).append(other)
    out = []
    for row in rows:
        status = shown_status(row)
        ordered_value = received_value = Decimal(0)
        priced = True
        lines = []
        for line in row["lines"]:
            qty, got = Decimal(line["quantity"]), Decimal(line["received"])
            rate = Decimal(line["rate"]) if line["rate"] is not None else None
            if rate is None:
                priced = False
            else:
                ordered_value += qty * rate
                received_value += min(got, qty) * rate
            lines.append({
                "id": str(line["id"]), "material_id": str(line["material_id"]), "material": line["material"],
                "main_category": line["main_category"],
                "category_id": str(line["category_id"]) if line["category_id"] else None,
                "main_category_id": str(line["main_category_id"]) if line["main_category_id"] else None,
                "unit": line["unit"], "unit_id": str(line["unit_id"]), "quantity": _num(qty), "said": line["said"],
                "received": _num(got), "pending": _num(max(qty - got, Decimal(0))), "extra": _num(max(got - qty, Decimal(0))),
                "rate": _money(rate) if with_money else None,
                "amount": _money(qty * rate) if with_money and rate is not None else None,
                "request": None if not line["request_id"] else {
                    "id": str(line["request_id"]), "ref": f"REQ-{line['request_number']:04d}",
                    "status": line["request_status"]},
            })
        duplicates: dict[uuid.UUID, dict] = {}
        if status in ("open", "part"):
            for line in row["lines"]:
                for other in open_by_material.get((row["project_id"], line["material_id"]), []):
                    if other["id"] != row["id"]:
                        duplicates[other["id"]] = other
        total_q = sum((Decimal(line["quantity"]) for line in row["lines"]), Decimal(0))
        total_got = sum((min(Decimal(line["received"]), Decimal(line["quantity"])) for line in row["lines"]), Decimal(0))
        out.append({
            "id": str(row["id"]), "number": row["number"], "ref": ref(row["number"]),
            "project_id": str(row["project_id"]), "project_name": row["project_name"],
            "site_id": str(row["site_id"]), "site_name": row["site_name"],
            "vendor_id": str(row["vendor_id"]), "vendor_name": row["vendor_name"], "vendor_phone": row["vendor_phone"],
            "status": status, "urgency": urgency(status, row["expected_date"], today),
            "expected_date": str(row["expected_date"]) if row["expected_date"] else None,
            "notes": row["notes"], "status_note": row["status_note"], "status_by_name": row["status_by_name"],
            "status_at": row["status_at"].isoformat() if row["status_at"] else None,
            "raised_over_duplicate": row["raised_over_duplicate"],
            "created_by": str(row["created_by"]) if row["created_by"] else None,
            "created_by_name": row["created_by_name"], "created_at": row["created_at"].isoformat(),
            "lines": lines,
            "progress": float(total_got / total_q) if total_q else 0.0,
            "value": _money(ordered_value) if with_money else None,
            "value_received": _money(received_value) if with_money else None,
            "value_complete": priced if with_money else None,
            "deliveries": [{"id": str(d["id"]), "line_id": str(d["purchase_order_line_id"]), "material": d["material"],
                            "quantity": _num(d["quantity"]), "unit": d["unit"], "date": str(d["occurred_date"]),
                            "by_name": d["by_name"], "at": d["created_at"].isoformat()} for d in row["deliveries"]],
            "duplicates": [{"id": str(d["id"]), "ref": ref(d["number"]), "vendor_name": d["vendor_name"],
                            "created_by_name": d["created_by_name"]} for d in duplicates.values()],
        })
    return out


def open_duplicates(orders: list[dict], project_id: uuid.UUID, material_ids: set) -> list[dict]:
    """Open orders in the project for any of these materials: what a new order may repeat (D2's default)."""
    found = []
    for other in orders:
        if other["project_id"] != project_id or shown_status(other) not in ("open", "part"):
            continue
        same = [line for line in other["lines"] if line["material_id"] in material_ids]
        if same:
            found.append({"id": str(other["id"]), "ref": ref(other["number"]), "vendor_name": other["vendor_name"],
                          "created_by_name": other["created_by_name"], "site_name": other["site_name"],
                          "lines": [{"material": line["material"], "quantity": _num(line["quantity"]),
                                     "pending": _num(max(Decimal(line["quantity"]) - Decimal(line["received"]), Decimal(0))),
                                     "unit": line["unit"]} for line in same]})
    return found
