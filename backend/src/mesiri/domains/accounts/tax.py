"""Phase C (ACC-10, ACC-11): GST and TDS, the figures the CA files from. The government filing stays the CA's.

**GST (ACC-10).** From the records, with their GSTINs and rates, and tied to the books:

- *Outward* (output tax): RA bills sent (submitted or certified, by bill date): taxable value (gross), GST at the
  bill's rate.
- *Inward* (input tax): confirmed expenses that carry GST (``tax_amount``). The GST is **claimable** when the
  supplier has a GSTIN and the bill says its GST is included (D-CC8, the same rule the books and the cost use);
  otherwise it stays in the cost and is listed as credit **missed**, with the reason, so the office can fix the
  supplier's GSTIN or the bill before the return.
- *Place of supply* (D-ACC7): the company's GSTIN (Settings › branding) and the other party's share their first two
  digits (the state) → CGST + SGST, half each; different → IGST. Without the company's GSTIN, the tax is shown whole.
- **Net payable** = output − claimable input, per month, in GSTR-3B's terms (3.1(a), 4(A)(5)).
- **Tie to the books**: the register's totals against the Output GST and Input GST ledgers for the period.

**TDS (ACC-11).**

- *Deducted by us* (194C) from subcontractors' bills: the payments from the TDS payable account (that is how a bill's
  TDS is held, ``subcontracts/store.tds_account``), each with its bill and the subcontractor's PAN (from the GSTIN).
  *Deposited*: money moved into the TDS payable account. Due on the 7th of the next month (March: 30 April).
- *Deducted by clients* from our RA bills: per bill, for matching with 26AS (Form 16A).
"""

from __future__ import annotations

import datetime
import uuid
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.domains.finance.costs import CLAIMABLE_GST_SQL

_ZERO = Decimal(0)
_C = Decimal("0.01")


def _m(v: Any) -> Decimal:
    return Decimal(v or 0).quantize(_C, rounding=ROUND_HALF_UP)


def state_of(gstin: str | None) -> str | None:
    g = (gstin or "").strip().upper()
    return g[:2] if len(g) == 15 and g[:2].isdigit() else None


def pan_of(gstin: str | None) -> str | None:
    g = (gstin or "").strip().upper()
    return g[2:12] if len(g) == 15 else None


def split(tax: Decimal, ours: str | None, theirs: str | None) -> dict[str, Decimal | None]:
    """CGST + SGST within the state, IGST across states; unknown (no GSTIN on either side): all in ``gst``."""
    tax = _m(tax)
    if ours and theirs:
        if ours == theirs:
            half = _m(tax / 2)
            return {"igst": _ZERO, "cgst": half, "sgst": tax - half, "unknown": _ZERO}
        return {"igst": tax, "cgst": _ZERO, "sgst": _ZERO, "unknown": _ZERO}
    return {"igst": _ZERO, "cgst": _ZERO, "sgst": _ZERO, "unknown": tax}


def tds_due(month_start: datetime.date) -> datetime.date:
    """TDS deducted in a month is deposited by the 7th of the next; March's by 30 April."""
    if month_start.month == 3:
        return datetime.date(month_start.year, 4, 30)
    nxt = (month_start.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
    return nxt.replace(day=7)


def _month(d: datetime.date) -> str:
    return d.strftime("%Y-%m")


async def company_gstin(conn: AsyncConnection, org: uuid.UUID) -> str | None:
    from mesiri.domains.organizations.branding import branding_values
    from mesiri.infrastructure.postgres.repositories.organization_settings import (
        PostgresOrganizationSettingsRepository,
    )

    try:
        stored = await PostgresOrganizationSettingsRepository(conn).get(org, "branding")
        return (branding_values(stored).get("gstin") or None) if stored is not None else None
    except Exception:  # noqa: BLE001 -- no branding saved: GST shown whole
        return None


def summarise_gst(sales: list[dict], purchases: list[dict]) -> dict[str, Any]:
    """Totals, per month, the missed credit and the warnings (pure, for tests)."""
    keys = ("taxable", "gst", "igst", "cgst", "sgst", "unknown")
    out_t = {k: sum((Decimal(r[k]) for r in sales), _ZERO) for k in keys}
    claim = [r for r in purchases if r["claimable"]]
    in_t = {k: sum((Decimal(r[k]) for r in claim), _ZERO) for k in keys}
    missed = [r for r in purchases if not r["claimable"]]
    months: dict[str, dict[str, Decimal]] = defaultdict(lambda: {"output": _ZERO, "input": _ZERO, "missed": _ZERO})
    for r in sales:
        months[_month(r["date"])]["output"] += Decimal(r["gst"])
    for r in purchases:
        months[_month(r["date"])]["input" if r["claimable"] else "missed"] += Decimal(r["gst"])
    by_supplier: dict[str, dict[str, Any]] = {}
    for r in purchases:
        key = r["gstin"] or f"no-gstin:{r['supplier'] or '—'}"
        s = by_supplier.setdefault(key, {"supplier": r["supplier"] or "No supplier", "gstin": r["gstin"], "bills": 0,
                                         "taxable": _ZERO, "gst": _ZERO, "claimable": _ZERO})
        s["bills"] += 1
        s["taxable"] += Decimal(r["taxable"])
        s["gst"] += Decimal(r["gst"])
        if r["claimable"]:
            s["claimable"] += Decimal(r["gst"])
    warnings = []
    no_gstin = [r for r in missed if r["reason"] == "no_gstin"]
    if no_gstin:
        warnings.append({"key": "supplier_no_gstin", "count": len(no_gstin),
                         "amount": sum((Decimal(r["gst"]) for r in no_gstin), _ZERO),
                         "words": "from suppliers with no GSTIN: their GST cannot be claimed until the GSTIN is added"})
    not_inc = [r for r in missed if r["reason"] == "not_included"]
    if not_inc:
        warnings.append({"key": "gst_not_included", "count": len(not_inc),
                         "amount": sum((Decimal(r["gst"]) for r in not_inc), _ZERO),
                         "words": "with GST said as not included in the amount: check the bill"})
    client_no = [r for r in sales if not r["gstin"]]
    if client_no:
        warnings.append({"key": "client_no_gstin", "count": len(client_no),
                         "amount": sum((Decimal(r["gst"]) for r in client_no), _ZERO),
                         "words": "to clients with no GSTIN: B2C in GSTR-1, or add the client's GSTIN"})
    return {
        "output": out_t, "input": in_t,
        "payable": out_t["gst"] - in_t["gst"],
        "missed": sum((Decimal(r["gst"]) for r in missed), _ZERO),
        "months": [{"month": k, **v, "payable": v["output"] - v["input"]} for k, v in sorted(months.items())],
        "by_supplier": sorted(by_supplier.values(), key=lambda s: -s["gst"]),
        "warnings": warnings,
    }


async def gst(conn: AsyncConnection, org: uuid.UUID, date_from: datetime.date, date_to: datetime.date) -> dict[str, Any]:
    from mesiri.domains.billing.bills import ref as bill_ref

    ours = await company_gstin(conn, org)
    our_state = state_of(ours)
    sales = []
    for r in (await conn.execute(text(
            "SELECT b.id, b.number, b.bill_date AS date, b.gross, b.gst, b.gst_pct, p.name AS project, cl.name AS client, "
            "cl.gstin FROM ra_bills b JOIN projects p ON p.id = b.project_id "
            "LEFT JOIN project_contracts pc ON pc.project_id = b.project_id AND pc.organization_id = b.organization_id "
            "LEFT JOIN clients cl ON cl.id = COALESCE(b.client_id, pc.client_id) "
            "WHERE b.organization_id = :org AND b.status IN ('submitted', 'certified') AND b.bill_date BETWEEN :f AND :t "
            "ORDER BY b.bill_date, b.number"), {"org": org, "f": date_from, "t": date_to})).mappings():
        gstin = (r["gstin"] or "").strip().upper() or None
        sales.append({"id": str(r["id"]), "ref": bill_ref(r["number"]), "date": r["date"], "client": r["client"],
                      "gstin": gstin, "project": r["project"], "rate": r["gst_pct"], "taxable": _m(r["gross"]),
                      "gst": _m(r["gst"]), **split(_m(r["gst"]), our_state, state_of(gstin))})
    purchases = []
    for r in (await conn.execute(text(
            f"SELECT e.id, e.expense_number, e.occurred_date AS date, e.amount, e.tax_amount, e.tax_rate, "
            f"COALESCE(e.is_tax_inclusive, true) AS inclusive, ({CLAIMABLE_GST_SQL}) AS claimable, v.name AS supplier, "
            "v.gstin, p.name AS project, c.name AS category FROM expenses e LEFT JOIN vendors v ON v.id = e.vendor_id "
            "LEFT JOIN projects p ON p.id = e.project_id LEFT JOIN expense_categories c ON c.id = e.category_id "
            "WHERE e.organization_id = :org AND e.workflow_status = 'confirmed' AND e.tax_amount > 0 "
            "AND e.occurred_date BETWEEN :f AND :t ORDER BY e.occurred_date, e.created_at"),
            {"org": org, "f": date_from, "t": date_to})).mappings():
        gstin = (r["gstin"] or "").strip().upper() or None
        tax = _m(r["tax_amount"])
        claimable = Decimal(r["claimable"] or 0) > 0
        reason = None if claimable else ("no_gstin" if not gstin else "not_included" if not r["inclusive"]
                                         else "tax_not_below_amount")
        taxable = _m(r["amount"]) - tax if r["inclusive"] else _m(r["amount"])
        purchases.append({"id": str(r["id"]), "number": r["expense_number"], "date": r["date"],
                          "supplier": r["supplier"], "gstin": gstin, "project": r["project"], "category": r["category"],
                          "rate": r["tax_rate"], "taxable": taxable, "gst": tax, "claimable": claimable,
                          "reason": reason, **split(tax, our_state, state_of(gstin))})
    out = summarise_gst(sales, purchases)
    books = (await conn.execute(text(
        "SELECT COALESCE(SUM(CASE WHEN l.code = 'output_gst' THEN jl.credit - jl.debit END), 0), "
        "COALESCE(SUM(CASE WHEN l.code = 'input_gst' THEN jl.debit - jl.credit END), 0) FROM journal_lines jl "
        "JOIN ledgers l ON l.id = jl.ledger_id WHERE jl.organization_id = :org AND jl.entry_date BETWEEN :f AND :t"),
        {"org": org, "f": date_from, "t": date_to})).one()
    tie = {"output_books": _m(books[0]), "input_books": _m(books[1]),
           "agrees": _m(books[0]) == out["output"]["gst"] and _m(books[1]) == out["input"]["gst"]}
    return {"company_gstin": ours, "company_state": our_state, "sales": sales, "purchases": purchases, **out, "tie": tie}


async def tds(conn: AsyncConnection, org: uuid.UUID, date_from: datetime.date, date_to: datetime.date,
              today: datetime.date) -> dict[str, Any]:
    from mesiri.domains.billing.bills import ref as bill_ref
    from mesiri.domains.subcontracts.store import TDS_ACCOUNT

    acc = (await conn.execute(text("SELECT id FROM money_accounts WHERE organization_id = :org AND name = :n"),
                              {"org": org, "n": TDS_ACCOUNT})).scalar()
    deducted, deposits = [], []
    if acc is not None:
        for r in (await conn.execute(text(
                "SELECT p.id, p.paid_date AS date, p.amount, p.reference_number, e.expense_number, e.amount AS bill, "
                "v.name AS party, v.gstin, pr.name AS project FROM expense_payments p "
                "JOIN expenses e ON e.id = p.expense_id LEFT JOIN vendors v ON v.id = COALESCE(p.vendor_id, e.vendor_id) "
                "LEFT JOIN projects pr ON pr.id = e.project_id WHERE p.organization_id = :org AND p.account_id = :a "
                "AND p.status = 'confirmed' AND p.paid_date <= :t ORDER BY p.paid_date, p.created_at"),
                {"org": org, "a": acc, "t": date_to})).mappings():
            deducted.append({"id": str(r["id"]), "date": r["date"], "party": r["party"], "pan": pan_of(r["gstin"]),
                             "section": "194C", "bill": r["expense_number"], "reference": r["reference_number"],
                             "bill_amount": _m(r["bill"]), "amount": _m(r["amount"]), "project": r["project"]})
        for r in (await conn.execute(text(
                "SELECT m.id, m.occurred_date AS date, m.amount, m.description, a.name AS source FROM money_transactions m "
                "LEFT JOIN money_accounts a ON a.id = m.from_account_id WHERE m.organization_id = :org "
                "AND m.to_account_id = :a AND m.transaction_type = 'transfer' AND m.occurred_date <= :t ORDER BY 2"),
                {"org": org, "a": acc, "t": date_to})).mappings():
            deposits.append({"id": str(r["id"]), "date": r["date"], "amount": _m(r["amount"]), "from": r["source"],
                             "words": r["description"]})
    # Months: deducted, deposited (paid against the oldest month first), what is left, due date, late or not.
    months: dict[str, dict[str, Any]] = {}
    for d in deducted:
        m = months.setdefault(_month(d["date"]), {"deducted": _ZERO, "deposited": _ZERO})
        m["deducted"] += d["amount"]
    pool = sum((d["amount"] for d in deposits), _ZERO)
    rows = []
    for key in sorted(months):
        m = months[key]
        start = datetime.date.fromisoformat(f"{key}-01")
        paid = min(pool, m["deducted"])
        pool -= paid
        due = tds_due(start)
        left = m["deducted"] - paid
        rows.append({"month": key, "deducted": m["deducted"], "deposited": paid, "left": left, "due": due,
                     "status": "deposited" if not left else ("overdue" if today > due else "due")})
    in_period = [r for r in rows if date_from.strftime("%Y-%m") <= r["month"] <= date_to.strftime("%Y-%m")]
    by_party: dict[str, dict[str, Any]] = {}
    for d in deducted:
        if not (date_from <= d["date"] <= date_to):
            continue
        p = by_party.setdefault(d["party"] or "—", {"party": d["party"] or "—", "pan": d["pan"], "bills": 0,
                                                     "bill_amount": _ZERO, "amount": _ZERO})
        p["bills"] += 1
        p["bill_amount"] += d["bill_amount"]
        p["amount"] += d["amount"]
    by_clients = []
    for r in (await conn.execute(text(
            "SELECT b.id, b.number, b.bill_date AS date, b.gross, b.tds, b.tds_pct, cl.name AS client, cl.gstin, "
            "p.name AS project FROM ra_bills b JOIN projects p ON p.id = b.project_id "
            "LEFT JOIN project_contracts pc ON pc.project_id = b.project_id AND pc.organization_id = b.organization_id "
            "LEFT JOIN clients cl ON cl.id = COALESCE(b.client_id, pc.client_id) WHERE b.organization_id = :org "
            "AND b.status IN ('submitted', 'certified') AND COALESCE(b.tds, 0) > 0 AND b.bill_date BETWEEN :f AND :t "
            "ORDER BY b.bill_date"), {"org": org, "f": date_from, "t": date_to})).mappings():
        by_clients.append({"id": str(r["id"]), "ref": bill_ref(r["number"]), "date": r["date"], "client": r["client"],
                           "pan": pan_of(r["gstin"]), "project": r["project"], "gross": _m(r["gross"]),
                           "rate": r["tds_pct"], "amount": _m(r["tds"])})
    period_deducted = [d for d in deducted if date_from <= d["date"] <= date_to]
    return {
        "deducted": period_deducted,
        "deposits": [d for d in deposits if date_from <= d["date"] <= date_to],
        "months": in_period,
        "by_party": sorted(by_party.values(), key=lambda p: -p["amount"]),
        "to_deposit": sum((r["left"] for r in rows), _ZERO),
        "overdue": sum((r["left"] for r in rows if r["status"] == "overdue"), _ZERO),
        "next_due": min((r["due"] for r in rows if r["left"] and r["due"] >= today), default=None),
        "by_clients": by_clients,
        "by_clients_total": sum((r["amount"] for r in by_clients), _ZERO),
        "missing_pan": sorted({d["party"] or "—" for d in period_deducted if not d["pan"]}),
    }
