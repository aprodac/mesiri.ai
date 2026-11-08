"""NXT-05/06/07 (8 Nov 2026): subcontracts on WhatsApp are the dashboard's routes (v3: ALLOWED lines + one SOP rule):
a work order, work measured on it, a subcontractor's bill checked by the API, approve / reject with a reason. Guards:
a subcontractor's bill is never an expense; releasing retention and status changes stay on the dashboard."""

from __future__ import annotations

import uuid
from pathlib import Path

from agent_api.app import API_ROUTERS
from agent_api.record_links import record_link
from agent_api.tools import ALLOWED

SOP = (Path(__file__).resolve().parents[2] / "src/agent_api/SOP.md").read_text(encoding="utf-8")
BY = {a.name: a for a in ALLOWED}


def test_the_routes_and_writes_wait_for_save() -> None:
    assert "mesiri.domains.subcontracts.router" in API_ROUTERS
    for name, method, path in (
        ("create_work_order", "POST", "/subcontracts/work-orders"),
        ("measure_work", "POST", "/subcontracts/work-orders/{wo_id}/measurements"),
        ("record_subcontract_bill", "POST", "/subcontracts/work-orders/{wo_id}/bills"),
        ("approve_subcontract_bill", "POST", "/subcontracts/bills/{bill_id}/approve"),
        ("reject_subcontract_bill", "POST", "/subcontracts/bills/{bill_id}/reject"),
        ("give_subcontract_advance", "POST", "/subcontracts/work-orders/{wo_id}/advance"),
    ):
        assert (BY[name].method, BY[name].path) == (method, path)
        assert "Saved only after the person confirms." in BY[name].description
    for name in ("list_work_orders", "work_order", "subcontract_bills_waiting", "subcontractor_statement"):
        assert BY[name].method == "GET"


def test_the_sop_routes_work_and_bills_to_the_work_order_never_an_expense() -> None:
    assert "`create_work_order`" in SOP and "`measure_work`" in SOP and "`record_subcontract_bill`" in SOP
    assert "never `record_expense`" in SOP
    assert "only with the reason the person" in SOP


def test_guard_retention_and_status_changes_stay_on_the_dashboard() -> None:
    paths = [a.path for a in ALLOWED]
    assert not any(p.endswith("/retention/release") for p in paths)
    assert not any(p.endswith("/{move}") or p.endswith("/cancel") or p.endswith("/close") for p in paths if p.startswith("/subcontracts"))


def test_after_save_the_link_opens_the_work_order() -> None:
    wo = str(uuid.uuid4())
    made = record_link("create_work_order", "/subcontracts/work-orders", {"vendor_name": "Ravi"}, {"id": wo}, today="2026-11-08")
    assert made and made.endswith(f"/subcontract/work-orders/{wo}")
    measured = record_link("measure_work", f"/subcontracts/work-orders/{wo}/measurements", {"line_id": "x", "quantity": "40"}, {}, today="2026-11-08")
    assert measured and measured.endswith(f"/subcontract/work-orders/{wo}")
