"""PRC-46: the debit note's money and words (no database)."""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

from mesiri.domains.procurement.returns import describe, line_money, ref, totals

D = Decimal


def test_a_line_is_worth_what_the_supplier_charged_gst_in() -> None:
    assert line_money(D(100), D(60), D(18), False, "32AAA") == {"before": D(6000), "gst": D(1080), "total": D(7080)}
    got = line_money(D(10), D(472), D(28), True, None)
    assert (round(got["before"], 2), got["total"]) == (D("3687.50"), D(4720))


def test_guard_gst_not_known_is_the_rate_as_recorded_and_no_rate_is_nothing() -> None:
    assert line_money(D(12), D(400), None, None, None) == {"before": D(4800), "gst": D(0), "total": D(4800)}
    assert line_money(D(12), None, D(18), False, None) is None


def _row(status: str = "waiting", **extra) -> dict:
    now = datetime.datetime(2026, 11, 10, 9, tzinfo=datetime.UTC)
    line = {"id": uuid.uuid4(), "material_id": uuid.uuid4(), "material": "TMT bar 12 mm", "unit": "kg",
            "unit_id": uuid.uuid4(), "main_category": None, "quantity": D(100), "rate": D(60), "gst_percent": D(18),
            "rate_includes_gst": False, "reason": "wrong_size", "receipt_id": None, "receipt_date": None,
            "grn_line_id": None, "usage_id": uuid.uuid4()}
    unpriced = {**line, "id": uuid.uuid4(), "rate": None, "quantity": D(2), "reason": "short", "material": "Binding wire"}
    return {"id": uuid.uuid4(), "number": 7, "vendor_id": uuid.uuid4(), "vendor_name": "KK", "vendor_phone": None,
            "vendor_gstin": None, "vendor_address": None, "project_id": uuid.uuid4(), "project_name": "Villa",
            "site_id": uuid.uuid4(), "site_name": "Block A", "goods_receipt_id": None, "grn_number": None,
            "order_id": None, "order_number": None, "status": status, "returned_on": datetime.date(2026, 11, 9),
            "notes": None, "photo_keys": [], "source": "web", "sent_on": None, "collected_by": None,
            "settled_how": None, "settled_receipt_id": None, "settled_expense_id": None, "settled_expense_number": None,
            "settled_payment_id": None, "settled_note": None, "settled_on": None, "cancel_reason": None,
            "status_at": now, "status_by_name": "Meera", "created_by_name": "Meera", "created_at": now,
            "lines": [line, unpriced], **extra}


def test_totals_count_an_unpriced_line_and_say_what_went_back() -> None:
    t = totals(_row())
    assert (t["total"], t["unpriced"]) == (D(7080), 1)
    out = describe(_row(), with_money=True)
    assert out["ref"] == ref(7) == "DN-0007" and out["total"] == "7080.00" and out["unpriced_lines"] == 1
    assert out["what"] == "100 kg TMT bar 12 mm (wrong size), 2 kg Binding wire (short)"


def test_site_roles_get_no_money_and_the_timeline_says_how_it_was_settled() -> None:
    hidden = describe(_row(), with_money=False)
    assert "total" not in hidden and "rate" not in hidden["lines"][0]
    done = describe(_row("settled", sent_on=datetime.date(2026, 11, 9), collected_by="driver", settled_how="credit",
                         settled_expense_number="EXP-0042", settled_on=datetime.date(2026, 11, 12)), with_money=True)
    assert [t["what"] for t in done["timeline"]] == [
        "Return recorded", "Sent back, collected by driver", "Settled by credit on EXP-0042"]
