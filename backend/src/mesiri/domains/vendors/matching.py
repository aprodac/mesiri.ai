"""PRC-11: a supplier's bill matched to the deliveries the site already recorded -- the one rule.

A bill usually comes days after the material. The site recorded the delivery (often without a rate); then the office
records the bill: as a material bill with lines (dashboard), or as an expense from a bill photo (WhatsApp). Without a
match both count: stock twice, and the supplier owed twice. This module finds, for a bill, the deliveries it is for:

- the same supplier (the vendor, or a delivery whose supplier was typed with the same name and no vendor),
- the same project (and site when the bill says one), not billed yet, not taken back, not a move between sites,
- from ``WINDOW_DAYS`` before the bill's date up to ``AFTER_DAYS`` after it (a delivery saved a day late).

Per bill line (material, quantity): one delivery of that material with the same quantity; else several whose quantities
add up to it (oldest first); else the closest single one within half to double the quantity, flagged. Each delivery
is used once. A matched delivery keeps what the site counted; what the bill said (quantity, rate) is kept beside it
(``billed_quantity``, ``billed_rate``) so a difference is shown, never overwritten.

For a bill typed as an expense (an amount, no lines): its deliveries are found the same way; they are linked by the
code only when they are certain -- every unbilled delivery of that supplier in the project, all with a rate, adding up
to the bill within ₹1 -- otherwise they are offered ("Malabar has 2 deliveries not billed: on this bill?").
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.domains.procurement.rates import BILLED_SQL

WINDOW_DAYS = 45
AFTER_DAYS = 7
_ONE_RUPEE = Decimal("1")


async def unbilled_for(
    conn: AsyncConnection, org: uuid.UUID, *, vendor_id: uuid.UUID | None, supplier: str | None,
    project_id: uuid.UUID, site_id: uuid.UUID | None, bill_date: datetime.date,
) -> list[dict]:
    """The deliveries a bill of this supplier, project (and site) and date may be for, oldest first."""
    if vendor_id is None and not (supplier or "").strip():
        return []
    who = []
    params: dict = {"org": org, "p": project_id, "from": bill_date - datetime.timedelta(days=WINDOW_DAYS),
                    "to": bill_date + datetime.timedelta(days=AFTER_DAYS)}
    if vendor_id is not None:
        who.append("r.vendor_id = :v")
        params["v"] = vendor_id
    if (supplier or "").strip():
        who.append("(r.vendor_id IS NULL AND lower(trim(r.supplier)) = lower(trim(:name)))")
        params["name"] = supplier
    sql = (
        "SELECT r.id, r.material_id, mc.name AS material, COALESCE(u.code, r.unit) AS unit, r.quantity, r.unit_cost, "
        "r.total_cost, r.occurred_date, r.site_id, s.name AS site, r.vendor_id, r.purchase_order_line_id "
        "FROM material_receipts r JOIN materials_catalog mc ON mc.id = r.material_id "
        "LEFT JOIN units_of_measure u ON u.id = mc.default_unit_id LEFT JOIN sites s ON s.id = r.site_id "
        "WHERE r.organization_id = :org AND r.project_id = :p AND (" + " OR ".join(who) + ") "
        "AND r.quantity > 0 AND r.movement_reason = 'RECEIVED' AND r.transfer_id IS NULL "
        "AND r.reverses_movement_id IS NULL "
        "AND NOT EXISTS (SELECT 1 FROM material_usage x WHERE x.reverses_movement_id = r.id) "
        "AND NOT EXISTS (SELECT 1 FROM material_receipts y WHERE y.reverses_movement_id = r.id) "
        "AND NOT " + BILLED_SQL + " AND r.occurred_date BETWEEN :from AND :to"
    )
    if site_id is not None:
        sql += " AND (r.site_id = :site OR r.site_id IS NULL)"
        params["site"] = site_id
    sql += " ORDER BY r.occurred_date, r.created_at"
    return [dict(r) for r in (await conn.execute(text(sql), params)).mappings()]


def value(d: dict) -> Decimal | None:
    """What a delivery is worth at the site's rate (None: recorded without one)."""
    if d.get("total_cost") is not None:
        return Decimal(d["total_cost"])
    if d.get("unit_cost") is not None:
        return Decimal(d["unit_cost"]) * Decimal(d["quantity"])
    return None


def match_lines(candidates: list[dict], lines: list[tuple[uuid.UUID, Decimal]]) -> list[list[dict]]:
    """For each bill line (material_id, quantity), the deliveries it is for ([] for none). Each delivery used once."""
    used: set = set()
    out: list[list[dict]] = []
    for material_id, qty in lines:
        same = [c for c in candidates if c["material_id"] == material_id and c["id"] not in used]
        pick: list[dict] = []
        exact = [c for c in same if Decimal(c["quantity"]) == qty]
        if exact:
            pick = [exact[0]]
        elif same and sum((Decimal(c["quantity"]) for c in same), Decimal(0)) == qty:
            pick = same
        else:
            run, total = [], Decimal(0)
            for c in same:
                run.append(c)
                total += Decimal(c["quantity"])
                if total == qty:
                    pick = run
                    break
                if total > qty:
                    break
            if not pick:
                near = [c for c in same if qty / 2 <= Decimal(c["quantity"]) <= qty * 2]
                if near:
                    pick = [min(near, key=lambda c: (abs(Decimal(c["quantity"]) - qty), -c["occurred_date"].toordinal()))]
        used.update(c["id"] for c in pick)
        out.append(pick)
    return out


def flags(delivered_qty: Decimal, billed_qty: Decimal | None, site_rate: Decimal | None, bill_rate: Decimal | None,
          unit: str | None) -> list[str]:
    """What differs between the bill and what the site recorded, in words."""
    out = []
    if billed_qty is not None and billed_qty != delivered_qty:
        diff = billed_qty - delivered_qty
        out.append(f"billed {_n(abs(diff))} {unit or ''} {'more' if diff > 0 else 'less'} than delivered".replace("  ", " "))
    if bill_rate is not None and site_rate is not None and bill_rate != site_rate:
        out.append(f"rate ₹{_n(bill_rate)} on the bill, ₹{_n(site_rate)} on site")
    return out


def _n(v: Decimal) -> str:
    return format(Decimal(v).normalize(), "f")


async def link(conn: AsyncConnection, org: uuid.UUID, invoice_id: uuid.UUID, deliveries: list[dict],
               vendor_id: uuid.UUID | None, billed_quantity: Decimal | None, billed_rate: Decimal | None) -> None:
    """Put deliveries on a bill (material invoice). A single delivery keeps the bill's quantity beside its own; several
    for one line each keep their own quantity as billed. A delivery saved by supplier name gets the vendor."""
    single = len(deliveries) == 1
    said = billed_quantity is not None or billed_rate is not None  # a bill typed as one amount says neither
    for d in deliveries:
        await conn.execute(text(
            "UPDATE material_receipts SET invoice_id = :inv, billed_quantity = :bq, billed_rate = :br, "
            "vendor_id = COALESCE(vendor_id, :v) WHERE id = :id AND organization_id = :org"),
            {"inv": invoice_id, "bq": (billed_quantity if single else d["quantity"]) if said else None, "br": billed_rate,
             "v": vendor_id, "id": d["id"], "org": org})


async def bill_differences(conn: AsyncConnection, org: uuid.UUID, *, projects: set[uuid.UUID] | None,
                           since: datetime.date) -> list[dict]:
    """WEB-93: bills (confirmed, on or after ``since``) that do not agree with the deliveries they are for, biggest
    first. Two ways, both already kept on the records: the bill is for more than its deliveries come to at the
    site's rates (``value``; only when every delivery has a rate, and by more than a rupee), or a delivery's billed
    quantity or rate differs from the site's (``flags``). Reads only."""
    sql = (
        "SELECT e.id AS expense_id, e.amount, e.occurred_date, e.project_id, v.id AS vendor_id, v.name AS vendor, "
        "r.quantity, r.unit_cost, r.total_cost, r.billed_quantity, r.billed_rate, mc.name AS material, "
        "COALESCE(u.code, r.unit) AS unit FROM expenses e JOIN vendors v ON v.id = e.vendor_id "
        "JOIN material_invoices i ON i.expense_id = e.id JOIN material_receipts r ON r.invoice_id = i.id "
        "JOIN materials_catalog mc ON mc.id = r.material_id LEFT JOIN units_of_measure u ON u.id = mc.default_unit_id "
        "WHERE e.organization_id = :org AND e.workflow_status = 'confirmed' AND e.occurred_date >= :since")
    params: dict = {"org": org, "since": since}
    if projects is not None:
        sql += " AND e.project_id = ANY(:projects)"
        params["projects"] = list(projects)
    bills: dict = {}
    for r in (await conn.execute(text(sql), params)).mappings():
        b = bills.setdefault(r["expense_id"], {"expense_id": r["expense_id"], "vendor_id": r["vendor_id"],
                                               "vendor": r["vendor"], "date": r["occurred_date"],
                                               "amount": Decimal(r["amount"]), "rows": []})
        b["rows"].append(r)
    out = []
    for b in bills.values():
        values = [value(dict(r)) for r in b["rows"]]
        total = sum((x for x in values if x is not None), Decimal(0)) if all(x is not None for x in values) else None
        over = b["amount"] - total if total is not None and b["amount"] - total > _ONE_RUPEE else Decimal(0)
        said = [f"{r['material']}: {f}" for r in b["rows"] for f in flags(
            Decimal(r["quantity"]), Decimal(r["billed_quantity"]) if r["billed_quantity"] is not None else None,
            Decimal(r["unit_cost"]) if r["unit_cost"] is not None else None,
            Decimal(r["billed_rate"]) if r["billed_rate"] is not None else None, r["unit"])]
        if over > 0 or said:
            out.append({"expense_id": b["expense_id"], "vendor_id": b["vendor_id"], "vendor": b["vendor"],
                        "date": b["date"], "amount": b["amount"], "deliveries": len(b["rows"]),
                        "deliveries_total": total, "over": over, "flags": said})
    out.sort(key=lambda x: (-x["over"], -len(x["flags"]), x["vendor"]))
    return out


def delivery_out(d: dict) -> dict:
    v = value(d)
    return {"receipt_id": str(d["id"]), "date": d["occurred_date"].isoformat(), "material": d["material"],
            "quantity": _n(d["quantity"]), "unit": d["unit"], "site": d["site"],
            "rate": _n(d["unit_cost"]) if d.get("unit_cost") is not None else None,
            "amount": str(v.quantize(Decimal("0.01"))) if v is not None else None}


async def for_expense(conn: AsyncConnection, org: uuid.UUID, expense_id: uuid.UUID) -> dict | None:
    """After a bill is recorded as an expense: its deliveries not billed yet. Linked when certain (see the module),
    else offered. None when the expense has no supplier, or the supplier has nothing waiting."""
    e = (await conn.execute(text(
        "SELECT e.id, e.vendor_id, v.name AS vendor, e.project_id, e.site_id, e.amount, e.occurred_date, e.workflow_status "
        "FROM expenses e JOIN vendors v ON v.id = e.vendor_id WHERE e.id = :e AND e.organization_id = :org"),
        {"e": expense_id, "org": org})).mappings().first()
    if e is None or e["project_id"] is None or e["workflow_status"] != "confirmed":
        return None
    if (await conn.execute(text("SELECT 1 FROM material_invoices WHERE expense_id = :e LIMIT 1"), {"e": expense_id})).first():
        return None  # already a bill with its deliveries
    found = await unbilled_for(conn, org, vendor_id=e["vendor_id"], supplier=e["vendor"], project_id=e["project_id"],
                               site_id=None, bill_date=e["occurred_date"])
    if not found:
        return None
    values = [value(d) for d in found]
    total = sum((x for x in values if x is not None), Decimal(0))
    certain = all(x is not None for x in values) and abs(total - Decimal(e["amount"])) <= _ONE_RUPEE
    out = {"vendor_id": str(e["vendor_id"]), "vendor": e["vendor"], "count": len(found),
           "total": str(total.quantize(Decimal("0.01"))), "unpriced": sum(1 for x in values if x is None),
           "deliveries": [delivery_out(d) for d in found], "linked": False}
    if certain:
        inv = uuid.uuid4()
        await conn.execute(text(
            "INSERT INTO material_invoices (id, organization_id, project_id, site_id, vendor_id, supplier_name, "
            "invoice_date, invoice_total, expense_id, source, created_by, notes) SELECT :id, e.organization_id, "
            "e.project_id, e.site_id, e.vendor_id, :name, e.occurred_date, e.amount, e.id, 'web', e.created_by, "
            "'Matched to deliveries when the bill was recorded' FROM expenses e WHERE e.id = :e"),
            {"id": inv, "name": e["vendor"], "e": expense_id})
        await link(conn, org, inv, found, e["vendor_id"], None, None)
        out["linked"] = True
    return out
