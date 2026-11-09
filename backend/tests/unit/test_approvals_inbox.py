"""GM-01: the "Waiting for you" rows -- the deciding fact, the tone, money only when allowed, the order."""

from __future__ import annotations

import datetime

from mesiri.domains.approvals import inbox

NOW = datetime.datetime(2026, 11, 9, 9, 0, tzinfo=datetime.UTC)


def _req(**over):
    line = {"material": "Cement OPC 53", "quantity": "250", "unit": "bags", "at_site": "40", "on_order": "0",
            "to_buy": "210", "last_rate": {"unit_cost": "410"}}
    base = {"id": "r1", "ref": "REQ-0142", "project_id": "p1", "project_name": "Marina Heights", "site_id": "s1",
            "site_name": "Tower A", "requested_by_name": "Ravi", "created_at": "2026-11-09T07:00:00+00:00",
            "needed_by": None, "urgency": "later", "duplicates": [], "lines": [line]}
    return {**base, **over}


def test_material_request_says_what_is_at_site_and_to_buy():
    row = inbox.material_request_row(_req(), with_money=True)
    assert row["key"] == "material_request:r1" and row["title"] == "Cement OPC 53 × 250 bags"
    assert row["fact"] == "40 bags at site · 210 bags to buy" and row["tone"] == "warn"
    assert row["amount"] == "102500.00" and row["extra"]["amount_is_estimate"] is True
    assert row["actions"] == ["ordered", "sent", "rejected"] and row["link"] == "/materials/requests?id=r1"


def test_material_request_hides_money_from_roles_that_do_not_see_spending():
    assert inbox.material_request_row(_req(), with_money=False)["amount"] is None
    coming = _req()
    coming["lines"][0].update(on_order="100", to_buy="110")
    assert inbox.material_request_row(coming, with_money=False)["fact"] == "40 bags at site · 100 bags on order · 110 bags to buy"


def test_material_request_late_and_duplicate_and_covered():
    late = inbox.material_request_row(_req(urgency="late", needed_by="2026-11-08"), with_money=False)
    assert late["tone"] == "bad" and late["fact"].startswith("Needed by 2026-11-08, late")
    dup = inbox.material_request_row(_req(duplicates=[{"ref": "REQ-0139"}]), with_money=False)
    assert dup["fact"] == "Also asked in REQ-0139" and dup["tone"] == "warn"
    covered = _req()
    covered["lines"][0]["to_buy"] = "0"
    assert inbox.material_request_row(covered, with_money=False)["tone"] == "ok"
    two = _req()
    two["lines"].append({**two["lines"][0], "material": "Sand"})
    assert inbox.material_request_row(two, with_money=False)["title"].endswith("and 1 more")


def _bill(status="flagged", flags=None):
    return {"id": "b1", "ref": "RA-3", "check_status": status, "gross": "271400.00", "caught": "50600.00",
            "created_at": "2026-11-05T10:00:00+00:00", "submitted_by_name": None, "lines": [],
            "flags": flags if flags is not None else [{"words": "billed 220 sqm more than measured on Plastering"}]}


WO = {"id": "w1", "ref": "WO-0007", "vendor_name": "Sreedhar team", "project_id": "p1", "project_name": "Marina",
      "site_id": "s1", "site_name": "Tower A"}


def test_flagged_subcontract_bill_leads_with_its_flag_and_the_money_at_risk():
    row = inbox.subcontract_bill_row(_bill(), WO)
    assert row["flagged"] is True and row["tone"] == "bad"
    assert row["fact"] == "Billed 220 sqm more than measured on Plastering · ₹50,600 at risk"
    assert row["title"] == "Sreedhar team · RA-3 on WO-0007" and row["asked_by"] == "Sreedhar team"
    assert row["actions"] == ["approve", "reject"] and row["link"] == "/subcontract/work-orders/w1"


def test_waiting_bill_with_no_flag_is_not_flagged():
    row = inbox.subcontract_bill_row({**_bill("waiting", flags=[]), "caught": "0"}, WO)
    assert row["flagged"] is False and row["tone"] == "ok"


def test_measurement_over_the_agreed_quantity_is_bad():
    m = {"id": "m1", "work_order_id": "w1", "wo_number": 7, "quantity": "300", "measured": "800", "agreed": "1000",
         "unit": "sqm", "description": "Plastering", "measured_on": "2026-11-08", "project_id": "p1",
         "project_name": "Marina", "site_id": "s1", "site_name": "Tower A", "who": None, "vendor_name": "Sreedhar",
         "created_at": "2026-11-08T12:00:00+00:00"}
    row = inbox.measurement_row(m)
    assert row["tone"] == "bad" and row["fact"] == "Takes the line to 1100 sqm of 1000 sqm agreed"
    assert row["asked_by"] == "Sreedhar" and row["ref"] == "WO-0007" and row["title"] == "Plastering · 300 sqm on 8 Nov"
    ok = inbox.measurement_row({**m, "quantity": "100"})
    assert ok["tone"] == "info" and ok["fact"] == "800 sqm confirmed so far of 1000 sqm agreed"


def test_ra_bill_and_size_request():
    ra = inbox.ra_bill_row({"id": "a", "ref": "RA-05", "client_name": "Al Noor Trust", "project_id": "p", "project_name": "Al Noor",
                            "created_at": "2026-11-05T00:00:00+00:00", "gross": "2140000", "net": "1842000"})
    assert ra["title"] == "RA-05 to Al Noor Trust" and ra["fact"] == "Gross ₹21,40,000 · net ₹18,42,000 after deductions" and ra["actions"] == ["submit"]
    size = inbox.size_request_row({"id": "z", "material": "M-sand", "unit": "load", "stock_unit": "cft", "waiting": 2,
                                   "proposed_one_unit_equals": "150", "proposed_by_name": "Ravi",
                                   "requested_by_name": "Ravi", "created_at": "2026-11-09T06:00:00+00:00"})
    assert size["title"] == "How much is 1 load of M-sand?"
    assert size["fact"] == "2 lines held until the size is set · Ravi says 1 load = 150 cft" and size["project_id"] is None


def test_arrange_puts_flagged_first_then_the_oldest_worst_first_and_counts():
    fresh = inbox.material_request_row(_req(), with_money=False)                                   # recent, warn
    old = inbox.material_request_row(_req(id="r2", created_at="2026-11-05T07:00:00+00:00"), with_money=False)
    flagged = inbox.subcontract_bill_row(_bill(), WO)
    out = inbox.arrange([fresh, old, flagged], NOW)
    assert [r["key"] for r in out["items"]] == ["subcontract_bill:b1", "material_request:r2", "material_request:r1"]
    assert [r["group"] for r in out["items"]] == ["flagged", "older", "recent"]
    assert out["counts"] == {"total": 3, "flagged": 1, "older": 1, "recent": 1, "material_request": 2,
                             "subcontract_bill": 1, "measurement": 0, "ra_bill": 0, "size_request": 0}
