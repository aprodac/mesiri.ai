"""Plain-words text (request [37] items 4 and 7)."""

from __future__ import annotations

import logging

import pytest

from channel.friendly_errors import friendly_rejection
from workflows.readable import field_lines, money, workflow_name


def test_money_is_rupees_by_default_and_groups_digits():
    assert money(1500) == "₹1,500"
    assert money(1500.5, "rupees") == "₹1,500.50"
    assert money(20, "usd") == "20 USD"


def test_field_lines_use_labels_and_hide_plumbing():
    lines = field_lines(
        {
            "amount": 1500,
            "currency": "rupees",
            "vendor": "JCB",
            "paid_from_own_pocket": True,
            "account_id": "abc",
            "_slot_answer_text": "x",
            "media_object_key": "k",
            "category": None,
        }
    )
    assert lines == [
        "   • Amount: ₹1,500",
        "   • For: JCB",
        "   • Paid: own pocket",
    ]


def test_unknown_fields_still_get_a_readable_label():
    assert field_lines({"gate_number": 4}) == ["   • Gate number: 4"]


def test_workflow_names_are_human():
    assert workflow_name("site.update") == "Work done"
    assert workflow_name("material.receipt") == "Material received"
    assert workflow_name("expense.submit") == "Expense"
    assert workflow_name("some.new_flow") == "Some new flow"


def test_the_19_oct_rejection_becomes_a_question_not_a_developer_message(caplog):
    with caplog.at_level(logging.WARNING, logger="mesiri.friendly_errors"):
        text = friendly_rejection(
            ["activity must have a narrative or at least one quantity"], where="test"
        )
    assert text.startswith("What work was done?")
    assert "narrative" not in text and "quantity" not in text
    assert "activity must have a narrative" in caplog.text  # raw reason stays in the log


def test_several_reasons_become_a_short_list():
    text = friendly_rejection(["unit is required", "quantity must be positive"])
    assert text.count("•") == 2


def test_an_unknown_reason_is_never_shown_raw():
    text = friendly_rejection(["constraint fk_site_project violated"])
    assert "constraint" not in text and "fk_" not in text


@pytest.mark.parametrize("reason", ["project is not resolved", "site is not resolved"])
def test_unresolved_scope_asks_which_one(reason):
    assert friendly_rejection([reason]).startswith("Which")
