"""PRC-35 (approved in session by the owner, 7 Nov 2026): paying an expense, or repaying someone, on WhatsApp is the
dashboard's route (v3: an ALLOWED line + an SOP rule), never a new workflow."""

from __future__ import annotations

from pathlib import Path

from agent_api.app import API_ROUTERS
from agent_api.tools import ALLOWED

SOP = (Path(__file__).resolve().parents[2] / "src/agent_api/SOP.md").read_text(encoding="utf-8")


def test_pay_expense_is_a_write_that_waits_for_save_and_the_read_is_a_get() -> None:
    by_name = {a.name: a for a in ALLOWED}
    pay, read = by_name["pay_expense"], by_name["expense_payments"]
    assert (pay.method, pay.path) == ("POST", "/expenses/{expense_id}/payments")
    assert "Saved only after the person confirms." in pay.description
    assert (read.method, read.path) == ("GET", "/expenses/{expense_id}/payments")
    assert "mesiri.domains.expenses.router" in API_ROUTERS  # the route is served to the agent


def test_the_sop_says_how_and_who() -> None:
    assert "`pay_expense`" in SOP and "own_pocket" in SOP
    assert "Only the owner, an admin or finance may" in SOP


def test_guard_undoing_a_payment_is_not_on_the_list() -> None:
    # A payment made by mistake is undone on the dashboard (it moves money back); not by the model.
    assert not any(a.path.endswith("/payments/{payment_id}/reverse") for a in ALLOWED)


def test_after_save_the_link_opens_the_expense_it_paid() -> None:
    import uuid

    from agent_api.record_links import record_link

    expense = str(uuid.uuid4())
    url = record_link("pay_expense", f"/expenses/{expense}/payments", {"account_id": str(uuid.uuid4())}, {"id": "p"}, today="2026-11-07")
    assert url and url.endswith(f"/finance/expenses/{expense}")
