"""PRC-22: material requests -- what a site asks for, before anyone orders it.

Storage and the rules that decide what a request shows; the routes are in ``router.py``. One request
holds one or more lines; each line's quantity is in the material's stock unit (another unit is
converted the way a delivery is, and what was said is kept in ``said``).

What each line shows is worked out here, once, for the dashboard and the assistant alike:

* ``at_site``: the site's stock now (the movement ledger, the same figure as Materials > Stock);
* ``on_order``: what other requests for the same site and material already have ordered or on its way;
* ``to_buy``: what is still missing (asked - at site - on order, never below zero);
* ``elsewhere``: other sites, within what the caller can see, that hold some;
* ``duplicates``: other open requests in the same project for the same material.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

#: Waiting for someone in the office to act.
WAITING = "waiting"
#: Still to arrive at the site: ordered from a supplier, or sent from another site.
IN_FLIGHT = ("ordered", "sent")
#: Not closed: a duplicate of one of these is worth a warning.
OPEN = (WAITING, *IN_FLIGHT)
CLOSED = ("done", "rejected", "cancelled")
STATUSES = (*OPEN, *CLOSED)

#: What an office decision moves a request to, and from where.
DECISIONS: dict[str, tuple[str, tuple[str, ...]]] = {
    "ordered": ("ordered", (WAITING,)),
    "sent": ("sent", (WAITING,)),
    "rejected": ("rejected", (WAITING,)),
    "done": ("done", IN_FLIGHT),
}

#: "Due soon" when the date the site needs it is this many days away or fewer.
SOON_DAYS = 2


def ref(number: int) -> str:
    return f"REQ-{number:04d}"


def _num(value: Any) -> str:
    return f"{Decimal(value).normalize():f}" if value is not None else "0"


def urgency(status: str, needed_by: datetime.date | None, today: datetime.date) -> str:
    """late / soon / later for a request still open; closed otherwise."""
    if status in CLOSED:
        return "closed"
    if needed_by is None:
        return "later"
    if needed_by < today:
        return "late"
    if (needed_by - today).days <= SOON_DAYS:
        return "soon"
    return "later"


async def next_number(conn: AsyncConnection, organization_id: uuid.UUID) -> int:
    """The company's next request number (REQ-0001, REQ-0002 ...), serialised per company."""
    await conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                       {"key": f"material_requests:{organization_id}"})
    row = (await conn.execute(text(
        "SELECT COALESCE(MAX(number), 0) + 1 FROM material_requests WHERE organization_id = :org"),
        {"org": organization_id})).first()
    return int(row[0])  # type: ignore[index]


async def insert_request(conn: AsyncConnection, organization_id: uuid.UUID, *, project_id: uuid.UUID,
                         site_id: uuid.UUID, requested_by: uuid.UUID, source: str, needed_by: datetime.date | None,
                         purpose: str | None, raised_over_duplicate: bool, lines: list[dict]) -> uuid.UUID:
    number = await next_number(conn, organization_id)
    request_id = uuid.uuid4()
    await conn.execute(text(
        """
        INSERT INTO material_requests (id, organization_id, number, project_id, site_id, requested_by, source,
                                       needed_by, purpose, raised_over_duplicate)
        VALUES (:id, :org, :number, :project, :site, :user, :source, :needed_by, :purpose, :dup)
        """), {"id": request_id, "org": organization_id, "number": number, "project": project_id, "site": site_id,
               "user": requested_by, "source": source, "needed_by": needed_by, "purpose": purpose,
               "dup": raised_over_duplicate})
    for position, line in enumerate(lines):
        await conn.execute(text(
            """
            INSERT INTO material_request_lines (organization_id, request_id, material_id, unit_id, quantity, said,
                                                position)
            VALUES (:org, :request, :material, :unit, :quantity, :said, :position)
            """), {"org": organization_id, "request": request_id, "material": line["material_id"],
                   "unit": line["unit_id"], "quantity": line["quantity"], "said": line.get("said"),
                   "position": position})
    return request_id


async def set_status(conn: AsyncConnection, request_id: uuid.UUID, status: str, user_id: uuid.UUID,
                     note: str | None) -> None:
    if status == "done":
        await conn.execute(text(
            "UPDATE material_requests SET status = 'done', done_at = now(), updated_at = now() WHERE id = :id"),
            {"id": request_id})
        return
    await conn.execute(text(
        "UPDATE material_requests SET status = :status, decision_note = :note, decided_by = :user, "
        "decided_at = now(), updated_at = now() WHERE id = :id"),
        {"status": status, "note": note, "user": user_id, "id": request_id})


_SELECT = """
    SELECT r.id, r.number, r.project_id, p.name AS project_name, r.site_id, s.name AS site_name,
           r.requested_by, ru.full_name AS requested_by_name, ru.role AS requested_by_role, r.source, r.needed_by,
           r.purpose, r.status, r.raised_over_duplicate, r.decision_note, r.decided_by,
           du.full_name AS decided_by_name, r.decided_at, r.done_at, r.created_at, r.updated_at
      FROM material_requests r
      JOIN projects p ON p.id = r.project_id
      JOIN sites s ON s.id = r.site_id
      LEFT JOIN users ru ON ru.id = r.requested_by
      LEFT JOIN users du ON du.id = r.decided_by
"""


async def fetch_requests(conn: AsyncConnection, organization_id: uuid.UUID, *,
                         project_ids: set[uuid.UUID] | None, request_id: uuid.UUID | None = None,
                         lock: bool = False) -> list[dict[str, Any]]:
    """Requests with their lines (newest first, at most 500), within ``project_ids`` (None: every project)."""
    sql = _SELECT + " WHERE r.organization_id = :org"
    params: dict[str, Any] = {"org": organization_id}
    if project_ids is not None:
        sql += " AND r.project_id = ANY(:projects)"
        params["projects"] = list(project_ids)
    if request_id is not None:
        sql += " AND r.id = :id"
        params["id"] = request_id
    sql += " ORDER BY r.created_at DESC LIMIT 500"
    if lock:
        sql += " FOR UPDATE OF r"
    rows = [dict(r._mapping) for r in (await conn.execute(text(sql), params)).all()]
    if not rows:
        return []
    lines = (await conn.execute(text(
        """
        SELECT l.id, l.request_id, l.material_id, m.name AS material, l.unit_id, u.code AS unit,
               u.display_name AS unit_name, l.quantity, l.said, l.position,
               CASE WHEN pc.name IS NOT NULL THEN pc.name || ' › ' || c.name ELSE c.name END AS category,
               COALESCE(pc.name, c.name) AS main_category,
               COALESCE(pc.id, c.id) AS main_category_id, c.id AS category_id
          FROM material_request_lines l
          JOIN materials_catalog m ON m.id = l.material_id
          JOIN units_of_measure u ON u.id = l.unit_id
          LEFT JOIN material_categories c ON c.id = m.category_id
          LEFT JOIN material_categories pc ON pc.id = c.parent_id
         WHERE l.request_id = ANY(:ids)
         ORDER BY l.position
        """), {"ids": [r["id"] for r in rows]})).all()
    by_request: dict[uuid.UUID, list[dict]] = {}
    for line in lines:
        by_request.setdefault(line.request_id, []).append(dict(line._mapping))
    for row in rows:
        row["lines"] = by_request.get(row["id"], [])
    return rows


async def describe(conn: AsyncConnection, organization_id: uuid.UUID, rows: list[dict[str, Any]], *,
                   stock_rows: list[dict], all_requests: list[dict], today: datetime.date,
                   last_rates: dict[uuid.UUID, dict] | None) -> list[dict[str, Any]]:
    """Each request as the page and the assistant show it: its lines with stock at the site, on order, to buy,
    stock at other sites, duplicates, and the last rate (``last_rates`` only for the roles that see money)."""
    stock: dict[tuple, Decimal] = {}
    elsewhere: dict[uuid.UUID, list[dict]] = {}
    for s in stock_rows:
        stock[(s["site_id"], s["material_id"])] = Decimal(s["current_stock"] or 0)
        if Decimal(s["current_stock"] or 0) > 0:
            elsewhere.setdefault(s["material_id"], []).append(s)
    site_names = await _site_names(conn, organization_id, {s["site_id"] for s in stock_rows if s.get("site_id")})

    on_order: dict[tuple, list[tuple[uuid.UUID, Decimal]]] = {}
    open_by_material: dict[tuple, list[dict]] = {}
    for other in all_requests:
        for line in other["lines"]:
            if other["status"] in IN_FLIGHT:
                on_order.setdefault((other["site_id"], line["material_id"]), []).append(
                    (other["id"], Decimal(line["quantity"])))
            if other["status"] in OPEN:
                open_by_material.setdefault((other["project_id"], line["material_id"]), []).append(other)

    out = []
    for row in rows:
        lines = []
        duplicates: dict[uuid.UUID, dict] = {}
        for line in row["lines"]:
            key = (row["site_id"], line["material_id"])
            asked = Decimal(line["quantity"])
            here = stock.get(key, Decimal(0))
            ordered = sum((q for rid, q in on_order.get(key, []) if rid != row["id"]), Decimal(0))
            if row["status"] in IN_FLIGHT:
                # This request is the order: what it asked for is on its way, nothing left to buy for it.
                ordered += asked
            to_buy = max(asked - max(here, Decimal(0)) - ordered, Decimal(0)) if row["status"] in OPEN else Decimal(0)
            spare = [
                {"site_id": str(s["site_id"]), "site_name": site_names.get(s["site_id"], ""),
                 "project_id": str(s["project_id"]), "quantity": _num(s["current_stock"])}
                for s in elsewhere.get(line["material_id"], []) if s["site_id"] != row["site_id"]
            ]
            for other in open_by_material.get((row["project_id"], line["material_id"]), []):
                if other["id"] != row["id"]:
                    duplicates[other["id"]] = other
            rate = (last_rates or {}).get(line["material_id"])
            lines.append({
                "id": str(line["id"]), "material_id": str(line["material_id"]), "material": line["material"],
                "category": line["category"], "main_category": line["main_category"],
                "category_id": str(line["category_id"]) if line["category_id"] else None,
                "main_category_id": str(line["main_category_id"]) if line["main_category_id"] else None,
                "unit": line["unit"], "unit_name": line["unit_name"], "quantity": _num(asked), "said": line["said"],
                "at_site": _num(here), "on_order": _num(ordered), "to_buy": _num(to_buy), "elsewhere": spare,
                "last_rate": None if rate is None else {
                    "unit_cost": _num(rate["unit_cost"]), "unit": rate.get("unit"),
                    "occurred_date": str(rate["occurred_date"]) if rate.get("occurred_date") else None,
                    "supplier": rate.get("supplier")},
            })
        out.append({
            "id": str(row["id"]), "number": row["number"], "ref": ref(row["number"]),
            "project_id": str(row["project_id"]), "project_name": row["project_name"],
            "site_id": str(row["site_id"]), "site_name": row["site_name"],
            "requested_by": str(row["requested_by"]) if row["requested_by"] else None,
            "requested_by_name": row["requested_by_name"], "requested_by_role": row["requested_by_role"],
            "source": row["source"], "needed_by": str(row["needed_by"]) if row["needed_by"] else None,
            "purpose": row["purpose"], "status": row["status"],
            "urgency": urgency(row["status"], row["needed_by"], today),
            "raised_over_duplicate": row["raised_over_duplicate"], "decision_note": row["decision_note"],
            "decided_by_name": row["decided_by_name"],
            "decided_at": row["decided_at"].isoformat() if row["decided_at"] else None,
            "done_at": row["done_at"].isoformat() if row["done_at"] else None,
            "created_at": row["created_at"].isoformat(),
            "lines": lines,
            "duplicates": [{"id": str(d["id"]), "ref": ref(d["number"]), "status": d["status"],
                            "requested_by_name": d["requested_by_name"], "created_at": d["created_at"].isoformat()}
                           for d in duplicates.values()],
        })
    return out


async def _site_names(conn: AsyncConnection, organization_id: uuid.UUID, ids: set) -> dict:
    if not ids:
        return {}
    rows = (await conn.execute(text("SELECT id, name FROM sites WHERE organization_id = :org AND id = ANY(:ids)"),
                               {"org": organization_id, "ids": list(ids)})).all()
    return {r.id: r.name for r in rows}


def open_duplicates(all_requests: list[dict], project_id: uuid.UUID, material_ids: set[uuid.UUID]) -> list[dict]:
    """Open requests in ``project_id`` asking for any of ``material_ids``: what a new request may repeat."""
    found = []
    for other in all_requests:
        if other["status"] not in OPEN or other["project_id"] != project_id:
            continue
        same = [line for line in other["lines"] if line["material_id"] in material_ids]
        if same:
            found.append({
                "id": str(other["id"]), "ref": ref(other["number"]), "status": other["status"],
                "site_name": other["site_name"], "requested_by_name": other["requested_by_name"],
                "created_at": other["created_at"].isoformat(),
                "needed_by": str(other["needed_by"]) if other["needed_by"] else None,
                "lines": [{"material": line["material"], "quantity": _num(line["quantity"]), "unit": line["unit"]}
                          for line in same],
            })
    return found


def requester_message(item: dict[str, Any], status: str, note: str | None, by: str | None) -> str:
    """What the person who asked is told on WhatsApp when the office acts (plain words, one line)."""
    what = ", ".join(f"{line['quantity']} {line['unit']} {line['material']}" for line in item["lines"])
    who = f" by {by}" if by else ""
    tail = f" ({note})" if note else ""
    words = {
        "ordered": f"🛒 Ordered{who}: {what}{tail}. {item['ref']}",
        "sent": f"🚚 Being sent from another site{who}: {what}{tail}. {item['ref']}",
        "rejected": f"✖️ Not ordered{who}: {what}. Reason: {note}. {item['ref']}",
        "done": f"✅ Marked received: {what}. {item['ref']}",
    }
    return words[status]
