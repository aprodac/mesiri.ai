"""NXT-12 (8 Nov 2026): the company's expenses and payments as Tally vouchers (XML), for the CA. One way only.

Built from the records the supplier ledger (CC-09, ``domains/vendors/ledger.py``) reads, in the same terms, so Tally
and Mesiri's supplier balances agree:

- **An expense** (confirmed) is a *Journal*: debit its category's ledger, credit who is owed it: the supplier, the
  staff member who paid from their own pocket (``reimbursable``, "<name> (reimbursable)"), or "Expenses payable"
  when there is neither. When the expense says its GST is included (``is_tax_inclusive`` with a ``tax_amount``), the
  tax goes to "Input GST" and the category gets the rest; GST said as *not* included is only named in the narration
  (the amount Mesiri holds is what is owed; it is never grossed up here).
- **A payment** with money of its own (``expense_payments`` with an account, not a part of an advance applied to a
  bill) is a *Payment*: debit the same party, credit the bank or cash account it left.
- **Ledgers** used are listed first as masters (suppliers under Sundry Creditors, categories under Indirect Expenses,
  accounts under Bank Accounts or Cash-in-Hand, the others under Current Liabilities / Duties & Taxes) so an import
  into a company that lacks one does not fail on it. The CA can move a ledger to another group in Tally.

Not included yet: client RA bills and money received (NXT-03, waiting for D-N3), deliveries not billed (no bill yet,
nothing to book), opening balances (Tally holds its own). Each voucher carries Mesiri's id (``REMOTEID``) and its
number, so the CA can tell what was imported. Tally's sign convention: a debit is ``ISDEEMEDPOSITIVE Yes`` with a
negative amount.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal
from typing import Any
from xml.sax.saxutils import escape

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

EXPENSES_PAYABLE = "Expenses payable"
INPUT_GST = "Input GST"
UNCATEGORISED = "Site expenses (no category)"
_CASH_TYPES = frozenset({"cash", "employee_advance"})


def _amt(v: Decimal) -> str:
    return f"{v.quantize(Decimal('0.01'))}"


def _entry(ledger: str, amount: Decimal, debit: bool) -> str:
    signed = -amount if debit else amount
    return ("<ALLLEDGERENTRIES.LIST>"
            f"<LEDGERNAME>{escape(ledger)}</LEDGERNAME>"
            f"<ISDEEMEDPOSITIVE>{'Yes' if debit else 'No'}</ISDEEMEDPOSITIVE>"
            f"<AMOUNT>{_amt(signed)}</AMOUNT>"
            "</ALLLEDGERENTRIES.LIST>")


def _voucher(kind: str, remote_id: str, day: datetime.date, number: str, party: str, narration: str,
             entries: list[str]) -> str:
    return (f'<TALLYMESSAGE xmlns:UDF="TallyUDF"><VOUCHER REMOTEID="{escape(remote_id)}" VCHTYPE="{kind}" '
            'ACTION="Create">'
            f"<DATE>{day:%Y%m%d}</DATE><VOUCHERTYPENAME>{kind}</VOUCHERTYPENAME>"
            f"<VOUCHERNUMBER>{escape(number)}</VOUCHERNUMBER><PARTYLEDGERNAME>{escape(party)}</PARTYLEDGERNAME>"
            f"<NARRATION>{escape(narration)}</NARRATION>" + "".join(entries) + "</VOUCHER></TALLYMESSAGE>")


def _ledger(name: str, parent: str) -> str:
    return (f'<TALLYMESSAGE xmlns:UDF="TallyUDF"><LEDGER NAME="{escape(name)}" ACTION="Create">'
            f"<NAME.LIST><NAME>{escape(name)}</NAME></NAME.LIST><PARENT>{escape(parent)}</PARENT>"
            "</LEDGER></TALLYMESSAGE>")


def party_of(row: dict[str, Any]) -> str:
    """Who an expense is owed to (and so who its payments pay): one rule for both voucher kinds."""
    if row.get("vendor"):
        return row["vendor"]
    if (row.get("payment_status") or "").lower() in ("reimbursable", "reimbursed") and row.get("staff"):
        return f"{row['staff']} (reimbursable)"
    return EXPENSES_PAYABLE


def build(company: str, expenses: list[dict[str, Any]], payments: list[dict[str, Any]]) -> tuple[str, dict]:
    """The XML and a count of what is in it. ``expenses`` / ``payments`` as ``fetch`` returns them."""
    ledgers: dict[str, str] = {}
    vouchers: list[str] = []
    split, not_split = 0, 0
    for e in expenses:
        amount = Decimal(e["amount"])
        if amount <= 0:
            continue
        party = party_of(e)
        ledgers[party] = "Sundry Creditors" if e.get("vendor") else "Current Liabilities"
        category = e.get("category") or UNCATEGORISED
        ledgers[category] = "Indirect Expenses"
        tax = Decimal(e["tax_amount"]) if e.get("tax_amount") else Decimal(0)
        narration = " · ".join(x for x in (e.get("description"), e.get("project"), e.get("site")) if x)
        if tax > 0 and e.get("is_tax_inclusive", True) and tax < amount:
            ledgers[INPUT_GST] = "Duties & Taxes"
            debits = [_entry(category, amount - tax, True), _entry(INPUT_GST, tax, True)]
            split += 1
        else:
            debits = [_entry(category, amount, True)]
            if tax > 0:
                narration += f" · GST ₹{_amt(tax)} said as not included"
                not_split += 1
        number = f"EXP-{e['expense_number']}" if e.get("expense_number") else str(e["id"])[:8]
        vouchers.append(_voucher("Journal", f"mesiri-expense-{e['id']}", e["occurred_date"], number, party,
                                 narration or "Expense", [*debits, _entry(party, amount, False)]))
    for p in payments:
        amount = Decimal(p["amount"])
        if amount <= 0:
            continue
        party = party_of(p)
        ledgers.setdefault(party, "Sundry Creditors" if p.get("vendor") else "Current Liabilities")
        account = p["account"]
        ledgers[account] = "Cash-in-Hand" if p.get("account_type") in _CASH_TYPES else "Bank Accounts"
        what = f"against EXP-{p['expense_number']}" if p.get("expense_number") else "on account (advance)"
        narration = " · ".join(x for x in (f"Paid {what}", p.get("payment_method"), p.get("reference_number"),
                                           p.get("project")) if x)
        number = p.get("reference_number") or str(p["id"])[:8]
        vouchers.append(_voucher("Payment", f"mesiri-payment-{p['id']}", p["paid_date"], number, party, narration,
                                 [_entry(party, amount, True), _entry(account, amount, False)]))
    masters = [_ledger(name, parent) for name, parent in sorted(ledgers.items())]
    xml = ("<ENVELOPE><HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER><BODY><IMPORTDATA>"
           "<REQUESTDESC><REPORTNAME>All Masters</REPORTNAME>"
           f"<STATICVARIABLES><SVCURRENTCOMPANY>{escape(company)}</SVCURRENTCOMPANY></STATICVARIABLES></REQUESTDESC>"
           "<REQUESTDATA>" + "".join(masters) + "".join(vouchers) + "</REQUESTDATA></IMPORTDATA></BODY></ENVELOPE>")
    return xml, {"ledgers": len(masters), "journals": sum(1 for e in expenses if Decimal(e["amount"]) > 0),
                 "payments": sum(1 for p in payments if Decimal(p["amount"]) > 0),
                 "gst_split": split, "gst_not_split": not_split}


async def fetch(conn: AsyncConnection, org: uuid.UUID, date_from: datetime.date, date_to: datetime.date
                ) -> tuple[list[dict], list[dict]]:
    """Confirmed expenses (by their date) and payments with money (by the day paid) in the period."""
    expenses = (await conn.execute(text(
        "SELECT e.id, e.expense_number, e.occurred_date, e.amount, e.tax_amount, e.is_tax_inclusive, e.description, "
        "e.payment_status, c.name AS category, v.name AS vendor, pr.name AS project, s.name AS site, "
        "u.full_name AS staff FROM expenses e LEFT JOIN expense_categories c ON c.id = e.category_id "
        "LEFT JOIN vendors v ON v.id = e.vendor_id LEFT JOIN projects pr ON pr.id = e.project_id "
        "LEFT JOIN sites s ON s.id = e.site_id LEFT JOIN users u ON u.id = e.created_by "
        "WHERE e.organization_id = :org AND e.workflow_status = 'confirmed' "
        "AND e.occurred_date BETWEEN :f AND :t ORDER BY e.occurred_date, e.created_at"),
        {"org": org, "f": date_from, "t": date_to})).mappings().all()
    payments = (await conn.execute(text(
        "SELECT p.id, p.paid_date, p.amount, p.payment_method, p.reference_number, a.name AS account, a.account_type, "
        "COALESCE(pv.name, ev.name) AS vendor, e.expense_number, e.payment_status, u.full_name AS staff, "
        "pr.name AS project FROM expense_payments p JOIN money_accounts a ON a.id = p.account_id "
        "LEFT JOIN expenses e ON e.id = p.expense_id LEFT JOIN vendors pv ON pv.id = p.vendor_id "
        "LEFT JOIN vendors ev ON ev.id = e.vendor_id LEFT JOIN users u ON u.id = e.created_by "
        "LEFT JOIN projects pr ON pr.id = COALESCE(p.project_id, e.project_id) "
        "WHERE p.organization_id = :org AND p.status = 'confirmed' AND p.advance_id IS NULL "
        "AND p.paid_date BETWEEN :f AND :t ORDER BY p.paid_date, p.created_at"),
        {"org": org, "f": date_from, "t": date_to})).mappings().all()
    return [dict(r) for r in expenses], [dict(r) for r in payments]
