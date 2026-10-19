"""Unit tests for channel.receipt.data -- pure, no playwright/browser needed."""

from __future__ import annotations

import pytest
from tests.unit.receipt_samples import (
    ACTIVITY,
    ACTIVITY_QTY,
    CORRECTION,
    EXPENSE,
    FIVE_TRADES,
    ISSUE,
    MATERIAL_IN,
    MATERIAL_USED,
    SEVEN_TRADES,
    UNDO,
    labour,
    multi,
    part_rows,
    receipt,
)

from channel.receipt.data import (
    KIND_STYLE,
    MAX_ROWS,
    ReceiptKind,
    combine_receipts,
)
from mesiri_contracts.assistant.draft_action import DraftActionType
from trade_label import trade_label


def _rows(data) -> dict[str, str]:
    return {r.tag: r.text for r in data.rows}


def test_each_type_has_its_own_colour_and_shape():
    """The shape carries the meaning too (colour-blind safe), so no two
    record types may share a shape -- except material in/out, which differ
    by direction (▲ in, ▼ used) and share the amber colour."""
    shapes = [s.shape for k, s in KIND_STYLE.items() if k is not ReceiptKind.RECORD]
    assert len(shapes) == len(set(shapes))
    assert KIND_STYLE[ReceiptKind.WORK].colour == "#0A8F4C"
    assert KIND_STYLE[ReceiptKind.LABOUR].colour == "#2563EB"
    assert KIND_STYLE[ReceiptKind.MATERIAL_IN].colour == KIND_STYLE[ReceiptKind.MATERIAL_USED].colour == "#D97706"
    assert KIND_STYLE[ReceiptKind.ISSUE].colour == "#DC2626"
    assert KIND_STYLE[ReceiptKind.EXPENSE].colour == "#7C3AED"


def test_material_in_and_used_differ_by_direction():
    got, used = receipt(*MATERIAL_IN), receipt(*MATERIAL_USED)
    assert (got.kind, used.kind) == (ReceiptKind.MATERIAL_IN, ReceiptKind.MATERIAL_USED)
    assert (got.hero_number, got.hero_unit) == ("50", "bags")
    assert _rows(got) == {"Material": "Cement", "Supplier": "UltraTech"}
    assert _rows(used) == {"Material": "Cement", "Used for": "Slab casting"}
    assert got.record_id.startswith("MR-191026-") and used.record_id.startswith("MU-191026-")


def test_header_and_footer_follow_the_record():
    data = receipt(*MATERIAL_IN)
    assert data.status == "SAVED · DRAFT"
    assert data.footer_note == "Confirm with tonight's report"
    assert data.site_line == "Block A · Riverside Tower"
    assert data.meta_line == "19 Oct 2026 · 4:27 PM · Mohammed"
    assert receipt(*MATERIAL_IN, late_entry=True).status == "LATE ENTRY"


def test_missing_reporter_and_supplier_degrade_to_nothing_not_a_crash():
    """A receipt with a KeyError is worse than one with a missing line."""
    data = receipt(
        DraftActionType.RECORD_MATERIAL_RECEIPT,
        {"material_name": "sand", "quantity": 5, "unit": "tons"},
        reporter=None,
    )
    assert data.meta_line == "19 Oct 2026 · 4:27 PM"
    assert _rows(data) == {"Material": "Sand"}  # no Supplier row rather than a dash


def test_expense_hero_is_the_amount():
    data = receipt(*EXPENSE)
    assert data.kind is ReceiptKind.EXPENSE
    assert data.hero_number == "₹4500"
    assert _rows(data) == {"Category": "Transport", "Description": "Tipper hire for debris"}


def test_issue_without_a_number_leads_with_its_title_and_shows_open():
    data = receipt(*ISSUE)
    assert data.kind is ReceiptKind.ISSUE
    assert data.hero_number == ""
    assert data.hero_title == "Material Shortage"
    assert data.hero_status == "Open"
    assert _rows(data)["Severity"] == "High"


def test_activity_with_and_without_a_quantity():
    plain = receipt(*ACTIVITY)
    assert plain.hero_number == "" and plain.hero_title == "Plastering"
    sized = receipt(*ACTIVITY_QTY)
    assert (sized.hero_number, sized.hero_unit) == ("120", "sqm")
    assert sized.kind is ReceiptKind.WORK


def test_correction_keeps_old_and_new():
    data = receipt(*CORRECTION)
    assert data.correction.old_value == "120 sqm"
    assert data.correction.new_value == "150 sqm"
    assert data.hero_number == "150"


def test_undo_is_grey_and_says_undone():
    data = receipt(*UNDO)
    assert data.kind is ReceiptKind.UNDONE
    assert data.status == "UNDONE"
    assert data.hero_title == "Undone"
    assert data.footer_note == "Not in tonight's report"


@pytest.mark.parametrize("trades", [FIVE_TRADES, SEVEN_TRADES, [("mason", 4)]])
def test_labour_has_one_row_per_trade_with_counts(trades):
    data = labour(trades)
    assert data.kind is ReceiptKind.LABOUR
    assert [(t.name, t.count) for t in data.trades] == [
        (trade_label(name), n) for name, n in trades
    ]
    assert data.hero_number == str(sum(n for _, n in trades))
    assert data.more == 0


def test_labour_merges_a_repeated_trade_and_keeps_report_order():
    data = labour([("mason", 2), ("helper", 5), ("mason", 3)])
    assert [(t.name, t.count) for t in data.trades] == [("Mason", 5), ("Helper", 5)]


def test_labour_with_more_than_ten_trades_shows_nine_and_counts_the_rest():
    data = labour([(f"trade{i}", 1) for i in range(13)])
    assert len(data.trades) == MAX_ROWS - 1
    assert data.more == 13 - (MAX_ROWS - 1)
    assert data.hero_number == "13"  # the total still counts everyone


def test_labour_shows_named_versus_counted_people():
    """P10's distinction belongs on the record the user keeps."""
    data = receipt(
        DraftActionType.RECORD_LABOUR_ATTENDANCE,
        {
            "lines": [
                {"worker_name": "Ravi", "trade": "mason", "headcount": 1},
                {"worker_name": None, "trade": "helper", "headcount": 12},
            ]
        },
    )
    assert data.hero_number == "13"
    assert _rows(data)["People"] == "1 named, 12 by headcount"


def test_labour_survives_an_empty_attendance():
    data = labour([])
    assert data.hero_number == "0" and data.trades == []


def test_labour_singular_worker_reads_naturally():
    assert labour([("mason", 1)]).hero_unit == "worker"


# -- several parts, one card ----------------------------------------------------


@pytest.mark.parametrize(("parts", "shown", "more"), [(3, 3, 0), (6, 6, 0), (10, 10, 0), (12, 9, 3)])
def test_multi_part_card_rows_and_plus_n_more(parts, shown, more):
    data = multi(parts)
    assert data.hero_number == str(parts)
    assert len(data.rows) == shown
    assert data.more == more
    assert data.status == f"{parts} SAVED · DRAFT"


def test_multi_part_rows_carry_each_records_kind_and_value():
    data = multi(6)
    assert [r.kind for r in data.rows] == [
        ReceiptKind.LABOUR,
        ReceiptKind.MATERIAL_IN,
        ReceiptKind.MATERIAL_USED,
        ReceiptKind.WORK,
        ReceiptKind.ISSUE,
        ReceiptKind.EXPENSE,
    ]
    assert data.rows[0].value == "27 workers"
    assert data.rows[1].value == "50 bags"
    assert data.rows[4].value == "Open"
    assert data.rows[5].value == "₹4500"
    assert data.record_id.endswith("+5")


def test_one_part_is_just_that_receipt():
    only = part_rows(1)[0]
    assert combine_receipts([only]) is only


def test_combining_nothing_is_an_error():
    with pytest.raises(ValueError):
        combine_receipts([])


# -- finance / admin types: never mislabelled as material -------------------------


def _finance(action_type: DraftActionType, fields: dict):
    return receipt(action_type, fields, project="", site="")


def test_transfer_receipt_is_money_not_material():
    data = _finance(
        DraftActionType.TRANSFER_MONEY,
        {"amount": "5000", "from_account_name": "Company Bank", "to_account_name": "Site Cash"},
    )
    assert data.category == "Transfer"
    assert data.kind is ReceiptKind.EXPENSE
    assert data.hero_number == "₹5000"
    assert data.record_id.startswith("TR-")
    assert _rows(data) == {"From": "Company Bank", "To": "Site Cash"}


def test_petty_cash_issue_and_return():
    issue = _finance(
        DraftActionType.TRANSFER_MONEY,
        {"amount": "1000", "direction": "issue", "recipient_account_name": "Alan", "other_account_name": "Site Cash"},
    )
    assert issue.category == "Petty cash" and issue.record_id.startswith("PC-")
    assert _rows(issue) == {"Issued to": "Alan", "From": "Site Cash"}
    back = _finance(
        DraftActionType.TRANSFER_MONEY,
        {"amount": "300", "direction": "return", "recipient_account_name": "Alan", "other_account_name": "Site Cash"},
    )
    assert _rows(back) == {"Returned by": "Alan", "Into": "Site Cash"}


def test_reversals_are_grey_undone_cards():
    expense = _finance(
        DraftActionType.REVERSE_TRANSACTION,
        {"target_kind": "expense", "reversal_amount": "700.00", "reversal_description": "diesel refill"},
    )
    assert expense.kind is ReceiptKind.UNDONE and expense.status == "UNDONE"
    assert expense.hero_number == "₹700.00" and expense.record_id.startswith("RV-")
    assert _rows(expense)["Description"] == "diesel refill"
    attendance = _finance(
        DraftActionType.REVERSE_TRANSACTION,
        {"target_kind": "attendance", "reversal_amount": "1200", "reversal_attendance_headcount": 9},
    )
    assert attendance.hero_title == "Withdrawn"
    assert _rows(attendance)["Cost removed"] == "₹1200"


@pytest.mark.parametrize(
    ("action_type", "fields", "category", "title", "prefix"),
    [
        (DraftActionType.MANAGE_MONEY_ACCOUNT, {"action": "create", "name": "Petrol Card"}, "Account", "Created", "AC-"),
        (DraftActionType.MANAGE_MONEY_ACCOUNT, {"action": "rename", "target_name": "A", "new_name": "B"}, "Account", "Renamed", "AC-"),
        (DraftActionType.MANAGE_MONEY_ACCOUNT, {"action": "deactivate", "target_name": "A"}, "Account", "Deactivated", "AC-"),
        (DraftActionType.CREATE_PROJECT, {"name": "Skyline Towers", "location": "Kochi"}, "Project", "Created", "PJ-"),
        (DraftActionType.CREATE_SITE, {"name": "Block A", "location": "North Yard"}, "Site", "Created", "ST-"),
        (DraftActionType.ADD_PROJECT_MEMBER, {"member_name": "Asha", "role": "site_engineer"}, "Project member", "Added", "PM-"),
        (DraftActionType.CREATE_USER, {"full_name": "Asha", "role": "supervisor"}, "New user", "Created", "US-"),
    ],
)
def test_setup_records_are_plain_saved_cards(action_type, fields, category, title, prefix):
    data = _finance(action_type, fields)
    assert (data.category, data.hero_title) == (category, title)
    assert data.record_id.startswith(prefix)
    assert data.status == "SAVED" and data.footer_note == ""
    assert "Material" not in data.category


def test_progress_update_and_close_issue():
    progress = receipt(
        DraftActionType.ADD_PROGRESS_UPDATE,
        {"update_kind": "COMPLETED", "narrative": "Finished the pour", "activity_summary": "Slab casting"},
    )
    assert progress.category == "Progress update" and progress.hero_title == "Completed"
    assert _rows(progress) == {"Activity": "Slab casting", "Details": "Finished the pour"}
    closed = receipt(
        DraftActionType.CLOSE_SITE_ISSUE,
        {"action": "resolve", "site_issue_type": "MATERIAL_SHORTAGE", "resolution_notes": "Cement delivered"},
    )
    assert closed.kind is ReceiptKind.ISSUE and closed.hero_status == "Resolved"
    assert closed.record_id.startswith("SC-")


def _stamped(moment, timezone=None):
    from tests.unit.receipt_samples import ORG, PRJ, SITE, USR, Named

    from channel.receipt.data import build_receipt_data
    from mesiri_contracts.assistant.v2.draft_action import DraftActionV2

    draft = DraftActionV2(
        draft_id="d", correlation_id="c", workflow_instance_id="w",
        action_type=DraftActionType.RECORD_LABOUR_ATTENDANCE,
        organization_id=ORG, user_id=USR, project_id=PRJ, site_id=SITE,
        fields={"lines": [{"worker_name": None, "trade": "mason", "headcount": 2}]},
    )
    return build_receipt_data(
        draft, record_row_id="abcd1234", reporter_name=None,
        projects=[Named(PRJ, "P")], sites=[Named(SITE, "S")],
        confirmed_at=moment, timezone=timezone,
    )


def test_receipt_time_is_the_companys_clock_not_utc():
    from datetime import UTC, datetime

    data = _stamped(datetime(2026, 10, 19, 12, 35, tzinfo=UTC))
    assert data.meta_line.startswith("19 Oct 2026 · 6:05 PM")


def test_receipt_date_and_record_id_roll_over_at_indian_midnight():
    from datetime import UTC, datetime

    data = _stamped(datetime(2026, 10, 19, 19, 0, tzinfo=UTC))  # 00:30 IST on the 20th
    assert data.meta_line.startswith("20 Oct 2026 · 12:30 AM")
    assert "-201026-" in data.record_id


def test_receipt_uses_the_given_zone_and_falls_back_to_india():
    from datetime import UTC, datetime

    moment = datetime(2026, 10, 19, 12, 35, tzinfo=UTC)
    assert _stamped(moment, "Asia/Dubai").meta_line.startswith("19 Oct 2026 · 4:35 PM")
    assert _stamped(moment, "Not/AZone").meta_line.startswith("19 Oct 2026 · 6:05 PM")


def test_trade_label_is_readable_and_receipt_rows_use_it():
    assert trade_label("steel_bender") == "Steel bender"
    assert trade_label("Mason") == "Mason"
    assert trade_label(None) == ""
    assert [t.name for t in labour([("steel_bender", 5)]).trades] == ["Steel bender"]
