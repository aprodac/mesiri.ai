"""CC-09 / CC-10 (8 Nov 2026): what is owed to suppliers and paying one, on WhatsApp, is the dashboard's routes (v3: ALLOWED
lines + an SOP rule), never a new workflow. Guards: undoing a supplier payment, merging and deleting stay on the
dashboard (they move money back or rewrite records)."""

from __future__ import annotations

import uuid
from pathlib import Path

from agent_api.app import API_ROUTERS
from agent_api.record_links import record_link
from agent_api.tools import ALLOWED

SOP = (Path(__file__).resolve().parents[2] / "src/agent_api/SOP.md").read_text(encoding="utf-8")


def test_reads_are_gets_and_paying_waits_for_save() -> None:
    by = {a.name: a for a in ALLOWED}
    assert (by["supplier_payables"].method, by["supplier_payables"].path) == ("GET", "/finance/vendors/payables")
    assert (by["supplier_account"].method, by["supplier_account"].path) == ("GET", "/finance/vendors/{vendor_id}/ledger")
    pay = by["pay_supplier"]
    assert (pay.method, pay.path) == ("POST", "/finance/vendors/{vendor_id}/payments")
    assert "Saved only after the person confirms." in pay.description and "advance" in pay.description
    assert "mesiri.domains.vendors.router" in API_ROUTERS


def test_the_sop_says_when_to_pay_a_supplier_and_when_one_bill() -> None:
    assert "`pay_supplier`" in SOP and "`supplier_payables`" in SOP and "`supplier_account`" in SOP
    # one named bill stays pay_expense; a supplier with no bill named is pay_supplier
    assert SOP.index("`pay_expense`") < SOP.index("`pay_supplier`")


def test_guard_undo_merge_and_delete_are_not_tools() -> None:
    paths = {(a.method, a.path) for a in ALLOWED}
    assert not any(p.startswith("/finance/vendors/") and (p.endswith("/reverse") or p.endswith("/merge")) for _, p in paths)
    assert not any(m == "DELETE" and p.startswith("/finance/vendors") for m, p in paths)


def test_after_save_the_link_opens_the_supplier_account() -> None:
    vendor = str(uuid.uuid4())
    url = record_link("pay_supplier", f"/finance/vendors/{vendor}/payments", {"account_id": str(uuid.uuid4()), "amount": "50000"},
                      {"payment_id": "p"}, today="2026-11-08")
    assert url and url.endswith(f"/finance/vendors/{vendor}")


def test_prc11_a_bill_saved_as_an_expense_offers_its_deliveries_and_links_on_yes() -> None:
    by = {a.name: a for a in ALLOWED}
    link = by["link_bill_deliveries"]
    assert (link.method, link.path) == ("POST", "/finance/vendors/{vendor_id}/bills/{expense_id}/deliveries")
    assert "Saved only after the person confirms." in link.description
    assert "`unbilled_deliveries`" in SOP and "`link_bill_deliveries`" in SOP and "Never a second expense" in SOP
    vendor, bill = str(uuid.uuid4()), str(uuid.uuid4())
    url = record_link("link_bill_deliveries", f"/finance/vendors/{vendor}/bills/{bill}/deliveries", {"receipt_ids": []}, {}, today="2026-11-08")
    assert url and url.endswith(f"/finance/expenses/{bill}")


def test_prc11_guard_taking_a_delivery_off_a_bill_stays_on_the_dashboard() -> None:
    assert not any(a.method == "DELETE" and "/deliveries/" in a.path for a in ALLOWED)
