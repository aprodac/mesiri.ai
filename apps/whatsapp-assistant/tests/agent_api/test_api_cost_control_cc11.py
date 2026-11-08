"""CC-11 (8 Nov 2026): cost control on WhatsApp is the dashboard's own routes (v3: ALLOWED lines + an SOP rule), never a
new workflow. Guards: the reads are GETs, putting labour on a line waits for Save, nothing on WhatsApp changes a BOQ
rate or a cost centre (those stay on the dashboard)."""

from __future__ import annotations

import uuid
from pathlib import Path

from agent_api.app import API_ROUTERS
from agent_api.record_links import record_link
from agent_api.tools import ALLOWED

SOP = (Path(__file__).resolve().parents[2] / "src/agent_api/SOP.md").read_text(encoding="utf-8")


def test_reads_are_gets_on_the_cost_routes_and_the_router_is_mounted() -> None:
    by = {a.name: a for a in ALLOWED}
    assert (by["cost_today"].method, by["cost_today"].path) == ("GET", "/cost/projects/{project_id}/variance")
    assert (by["budget_vs_actual"].method, by["budget_vs_actual"].path) == ("GET", "/cost/projects/{project_id}/budget")
    assert (by["labour_not_on_boq"].method, by["labour_not_on_boq"].path) == ("GET", "/cost/projects/{project_id}/labour")
    assert (by["materials_vs_boq"].method, by["materials_vs_boq"].path) == ("GET", "/cost/projects/{project_id}/materials")
    assert "mesiri.domains.costing.router" in API_ROUTERS


def test_putting_labour_on_a_line_waits_for_save_and_links_to_budget_vs_actual() -> None:
    put = {a.name: a for a in ALLOWED}["put_labour_on_boq"]
    assert (put.method, put.path) == ("PUT", "/cost/projects/{project_id}/labour")
    assert "Saved only after the person confirms." in put.description
    project = str(uuid.uuid4())
    url = record_link("put_labour_on_boq", f"/cost/projects/{project}/labour", {"lines": []}, {}, today="2026-11-08")
    assert url and url.endswith(f"/cost/budget?project={project}")


def test_the_sop_says_how_to_answer_and_never_to_make_up_a_colour() -> None:
    rule = SOP[SOP.index("20. Cost:"):]
    for tool in ("`cost_today`", "`budget_vs_actual`", "`labour_not_on_boq`", "`put_labour_on_boq`", "`materials_vs_boq`"):
        assert tool in rule
    assert "never coloured" in rule and "never make up a figure, a rate or a colour" in rule
    assert "after the attendance is saved" in rule  # attendance is still record_attendance first


def test_guard_rates_centres_and_categories_are_not_changed_on_whatsapp() -> None:
    paths = {(a.method, a.path) for a in ALLOWED}
    assert ("PATCH", "/cost/categories/{category_id}") not in paths
    assert not any(p.startswith("/projects/{project_id}/boq") and m != "GET" for m, p in paths)


def test_sec04_a_new_category_is_for_money_roles_and_an_unknown_one_is_uncategorized() -> None:
    assert "`add_expense_category`" in SOP and "only the owner, an admin or finance may" in SOP
    assert "a category it does not know is kept under Uncategorized" in SOP


def test_dcc4_a_site_engineer_gets_colours_never_money() -> None:
    rule = SOP[SOP.index("20. Cost:"):]
    assert "`money_hidden`" in rule and "never a rupee, rate or percentage" in rule


def test_nxt03_money_from_clients_is_the_billing_routes_and_waits_for_save() -> None:
    by = {a.name: a for a in ALLOWED}
    assert (by["receivables"].method, by["receivables"].path) == ("GET", "/billing/receivables")
    assert (by["ra_bills"].method, by["ra_bills"].path) == ("GET", "/billing/ra-bills")
    record = by["record_client_receipt"]
    assert (record.method, record.path) == ("POST", "/billing/receipts")
    assert "Saved only after the person confirms." in record.description
    assert "mesiri.domains.billing.router" in API_ROUTERS
    rule = SOP[SOP.index("21. Money from a client"):]
    assert "never put on a bill" in rule and "offer the rest on account" in rule
    url = record_link("record_client_receipt", "/billing/receipts", {"amount": "500000"}, {}, today="2026-11-08")
    assert url and url.endswith("/accounts/receivables")
    # Guard: submitting, certifying, cancelling or deleting an RA bill and taking a receipt back stay on the dashboard.
    assert not any(a.path.startswith("/billing/ra-bills/") and a.method != "GET" for a in ALLOWED)
    assert not any(a.path.endswith("/cancel") and a.path.startswith("/billing/receipts") for a in ALLOWED)
