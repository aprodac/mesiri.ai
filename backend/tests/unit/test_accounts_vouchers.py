"""ACC-12: a manual voucher's rules -- balanced, one side per line, no negatives, paise, Contra only cash and bank;
a reversal mirrors exactly."""

from __future__ import annotations

from decimal import Decimal

import pytest

from mesiri.domains.accounts.vouchers import VoucherError, mirror, validate

BANK, CASH, CHARGES = "b", "c", "x"


def _ln(ledger, dr="0", cr="0", **extra):
    return {"ledger_id": ledger, "debit": dr, "credit": cr, **extra}


def test_a_balanced_journal_is_cleaned_to_decimals():
    out = validate("journal", [_ln(CHARGES, "250.50"), _ln(BANK, cr="250.50")], {BANK, CASH})
    assert [(x["debit"], x["credit"]) for x in out] == [(Decimal("250.50"), 0), (0, Decimal("250.50"))]


@pytest.mark.parametrize(("lines", "words"), [
    ([_ln(CHARGES, "100"), _ln(BANK, cr="90")], "differ by 10"),
    ([_ln(CHARGES, "100", "100"), _ln(BANK, cr="100")], "one of them"),
    ([_ln(CHARGES, "0"), _ln(BANK, cr="0")], "one of them"),
    ([_ln(CHARGES, "-100"), _ln(BANK, cr="-100")], "no negative"),
    ([_ln(CHARGES, "10.005"), _ln(BANK, cr="10.005")], "two decimals"),
    ([_ln(CHARGES, "100")], "at least two"),
    ([_ln(None, "100"), _ln(BANK, cr="100")], "pick a ledger"),
    ([_ln(CHARGES, "1", cost_centre="snacks"), _ln(BANK, cr="1")], "cost centre"),
])
def test_what_is_refused_and_why(lines, words):
    with pytest.raises(VoucherError, match=words):
        validate("journal", lines, {BANK, CASH})


def test_a_contra_moves_money_between_cash_and_bank_only():
    assert validate("contra", [_ln(BANK, "5000"), _ln(CASH, cr="5000")], {BANK, CASH})
    with pytest.raises(VoucherError, match="cash and bank only"):
        validate("contra", [_ln(CHARGES, "5000"), _ln(CASH, cr="5000")], {BANK, CASH})
    with pytest.raises(VoucherError, match="Journal or a Contra|journal or a contra"):
        validate("payment", [_ln(BANK, "1"), _ln(CASH, cr="1")], {BANK, CASH})


def test_a_reversal_mirrors_every_line_exactly():
    lines = validate("journal", [_ln(CHARGES, "120", project_id="p1", site_id="s1", cost_centre="overhead"),
                                 _ln(BANK, cr="120")], {BANK})
    back = mirror(lines)
    assert [(x["ledger_id"], x["debit"], x["credit"], x["project_id"], x["site_id"], x["cost_centre"]) for x in back] == [
        (CHARGES, 0, Decimal("120"), "p1", "s1", "overhead"), (BANK, Decimal("120"), 0, None, None, None)]
    assert mirror(back) == lines
