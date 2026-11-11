"""PRC-29: goods received notes -- an order's goods checked at the gate.

One GRN (GRN-0001 per company) per receiving of an order: the date, the supplier's challan number and photo, who
received it, and per order line what was accepted (into stock, as the delivery it records) and what was rejected
and why (not in stock; still to come on the order, a replacement is owed). The routes are in ``orders_router.py``
(receive, one order) and ``grn_router.py`` (the GRN page).
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

#: PRC-52: deliveries that usually come with a quality certificate (mill test, cement test, RMC batch / cube): items
#: in these sub-categories, or named cement. Only a hint ("No test certificate yet"), never a blocker.
CERTIFIED_CATEGORIES = frozenset({"steel", "concrete"})
#: Kinds of delivery certificate, as the GRN offers them; the title of the kept document starts with the label.
CERTIFICATE_KINDS = {"mill_test": "Mill test certificate", "cement_test": "Cement test certificate",
                     "rmc": "RMC batch / cube report", "other": "Test certificate"}


def needs_certificate(material: str, category: str | None) -> bool:
    return (category or "").strip().lower() in CERTIFIED_CATEGORIES or "cement" in material.lower()


def ref(number: int) -> str:
    return f"GRN-{number:04d}"


def _num(value: Any) -> str:
    return f"{Decimal(value).normalize():f}" if value is not None else "0"


async def insert(conn: AsyncConnection, organization_id: uuid.UUID, *, order_id: uuid.UUID,
                 received_on: datetime.date, challan_no: str | None, photo_key: str | None,
                 received_by_name: str | None, notes: str | None, created_by: uuid.UUID) -> tuple[uuid.UUID, int]:
    await conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                       {"key": f"goods_receipts:{organization_id}"})
    number = int((await conn.execute(text(
        "SELECT COALESCE(MAX(number), 0) + 1 FROM goods_receipts WHERE organization_id = :org"),
        {"org": organization_id})).scalar_one())
    grn_id = uuid.uuid4()
    await conn.execute(text(
        """
        INSERT INTO goods_receipts (id, organization_id, number, purchase_order_id, received_on, challan_no,
                                    challan_photo_key, received_by_name, notes, created_by)
        VALUES (:id, :org, :number, :order, :on, :challan, :photo, :by_name, :notes, :by)
        """), {"id": grn_id, "org": organization_id, "number": number, "order": order_id, "on": received_on,
               "challan": challan_no, "photo": photo_key, "by_name": received_by_name, "notes": notes, "by": created_by})
    return grn_id, number


async def insert_line(conn: AsyncConnection, organization_id: uuid.UUID, grn_id: uuid.UUID, *, line_id: uuid.UUID,
                      accepted: Decimal, rejected: Decimal, reason: str | None, receipt_id: Any) -> None:
    await conn.execute(text(
        """
        INSERT INTO goods_receipt_lines (organization_id, goods_receipt_id, purchase_order_line_id, accepted, rejected,
                                         rejected_reason, material_receipt_id)
        VALUES (:org, :grn, :line, :accepted, :rejected, :reason, :receipt)
        """), {"org": organization_id, "grn": grn_id, "line": line_id, "accepted": accepted, "rejected": rejected,
               "reason": reason, "receipt": uuid.UUID(str(receipt_id)) if receipt_id else None})


async def fetch(conn: AsyncConnection, organization_id: uuid.UUID, *, order_id: uuid.UUID | None = None,
                project_ids: set[uuid.UUID] | None = None, site_id: uuid.UUID | None = None,
                grn_id: uuid.UUID | None = None, limit: int = 300) -> list[dict[str, Any]]:
    """GRNs with their lines and certificates (PRC-52), newest first: for one order, one GRN, or the GRN page (within
    ``project_ids``)."""
    sql = """
        SELECT g.id, g.number, g.purchase_order_id, o.number AS order_number, o.project_id, p.name AS project_name,
               o.site_id, s.name AS site_name, v.name AS vendor_name, o.vendor_id, g.received_on, g.challan_no, g.challan_photo_key,
               g.received_by_name, g.notes, cu.full_name AS created_by_name, g.created_at
          FROM goods_receipts g
          JOIN purchase_orders o ON o.id = g.purchase_order_id
          JOIN projects p ON p.id = o.project_id
          JOIN sites s ON s.id = o.site_id
          JOIN vendors v ON v.id = o.vendor_id
          LEFT JOIN users cu ON cu.id = g.created_by
         WHERE g.organization_id = :org
    """
    params: dict[str, Any] = {"org": organization_id, "limit": limit}
    if order_id is not None:
        sql += " AND g.purchase_order_id = :order"
        params["order"] = order_id
    if project_ids is not None:
        sql += " AND o.project_id = ANY(:projects)"
        params["projects"] = list(project_ids)
    if site_id is not None:
        sql += " AND o.site_id = :site"
        params["site"] = site_id
    if grn_id is not None:
        sql += " AND g.id = :grn"
        params["grn"] = grn_id
    sql += " ORDER BY g.received_on DESC, g.number DESC LIMIT :limit"
    rows = [dict(r._mapping) for r in (await conn.execute(text(sql), params)).all()]
    if not rows:
        return []
    lines = (await conn.execute(text(
        """
        SELECT gl.goods_receipt_id, gl.purchase_order_line_id, m.name AS material, u.code AS unit, gl.accepted,
               gl.rejected, gl.rejected_reason, gl.material_receipt_id, c.name AS category
          FROM goods_receipt_lines gl
          JOIN purchase_order_lines l ON l.id = gl.purchase_order_line_id
          JOIN materials_catalog m ON m.id = l.material_id
          LEFT JOIN material_categories c ON c.id = m.category_id
          JOIN units_of_measure u ON u.id = l.unit_id
         WHERE gl.goods_receipt_id = ANY(:ids)
         ORDER BY l.position
        """), {"ids": [r["id"] for r in rows]})).all()
    by_grn: dict[uuid.UUID, list[dict]] = {}
    for line in lines:
        by_grn.setdefault(line.goods_receipt_id, []).append({
            "line_id": str(line.purchase_order_line_id), "material": line.material, "unit": line.unit,
            "accepted": _num(line.accepted), "rejected": _num(line.rejected), "rejected_reason": line.rejected_reason,
            "receipt_id": str(line.material_receipt_id) if line.material_receipt_id else None,
            "needs_certificate": needs_certificate(line.material, line.category)})
    certificates = await fetch_certificates(conn, organization_id, [r["id"] for r in rows])
    return [{
        "id": str(r["id"]), "ref": ref(r["number"]), "number": r["number"],
        "order_id": str(r["purchase_order_id"]), "order_ref": f"PO-{r['order_number']:04d}",
        "project_id": str(r["project_id"]), "project_name": r["project_name"], "site_id": str(r["site_id"]),
        "site_name": r["site_name"], "vendor_name": r["vendor_name"], "vendor_id": str(r["vendor_id"]), "received_on": str(r["received_on"]),
        "challan_no": r["challan_no"], "photo_key": r["challan_photo_key"], "received_by_name": r["received_by_name"],
        "notes": r["notes"], "created_by_name": r["created_by_name"], "created_at": r["created_at"].isoformat(),
        "lines": by_grn.get(r["id"], []),
        "certificates": certificates.get(str(r["id"]), []),
        "needs_certificate": any(x["needs_certificate"] for x in by_grn.get(r["id"], [])),
    } for r in rows]


async def fetch_certificates(conn: AsyncConnection, organization_id: uuid.UUID, grn_ids: list) -> dict[str, list[dict]]:
    """PRC-52: per GRN, its current certificates (project documents in the test-reports folder linked to it)."""
    if not grn_ids:
        return {}
    rows = (await conn.execute(text(
        """
        SELECT d.id, d.goods_receipt_id, d.title, d.notes, d.file_name, d.content_type, d.created_at,
               u.full_name AS uploaded_by_name
          FROM project_documents d LEFT JOIN users u ON u.id = d.uploaded_by
         WHERE d.organization_id = :org AND d.goods_receipt_id = ANY(:ids) AND d.status = 'current'
         ORDER BY d.created_at
        """), {"org": organization_id, "ids": grn_ids})).mappings().all()
    out: dict[str, list[dict]] = {}
    for d in rows:
        out.setdefault(str(d["goods_receipt_id"]), []).append({
            "id": str(d["id"]), "title": d["title"], "notes": d["notes"], "file_name": d["file_name"],
            "content_type": d["content_type"], "created_at": d["created_at"].isoformat(),
            "uploaded_by_name": d["uploaded_by_name"]})
    return out


async def rejected_by_line(conn: AsyncConnection, line_ids: list) -> dict[str, Decimal]:
    """What was turned away at the gate per order line (it is still to come)."""
    if not line_ids:
        return {}
    rows = (await conn.execute(text(
        "SELECT purchase_order_line_id, SUM(rejected) AS rejected FROM goods_receipt_lines "
        "WHERE purchase_order_line_id = ANY(:ids) GROUP BY purchase_order_line_id"), {"ids": line_ids})).all()
    return {str(r.purchase_order_line_id): Decimal(r.rejected) for r in rows if r.rejected}


def challan_key(organization_id: uuid.UUID, grn_id: uuid.UUID, extension: str) -> str:
    return f"org/{organization_id}/grn/{grn_id}/challan-{uuid.uuid4().hex}.{extension}"
