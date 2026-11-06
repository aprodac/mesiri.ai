"""WEB-66: a bank account's details: the bank, the IFSC, and only the last 4 digits of the number."""

import pytest

from mesiri.domains.finance.bank_details import BankDetailError, clean_bank_name, clean_ifsc, last4


def test_the_bank_name_is_tidied_and_empty_clears_it():
    assert clean_bank_name("  State  Bank of India ") == "State Bank of India"
    assert clean_bank_name("") is None and clean_bank_name(None) is None


@pytest.mark.parametrize("typed", ["sbin0001234", " SBIN 000 1234 ", "SBIN0001234"])
def test_an_ifsc_is_read_however_it_is_typed(typed):
    assert clean_ifsc(typed) == "SBIN0001234"


@pytest.mark.parametrize("bad", ["SBIN1001234", "SBI0001234", "SBIN00012345"])
def test_a_wrong_ifsc_is_refused(bad):
    with pytest.raises(BankDetailError):
        clean_ifsc(bad)


@pytest.mark.parametrize(("typed", "kept"), [("50100123456789", "6789"), ("•••• 4321", "4321"), ("XX-1234", "1234")])
def test_only_the_last_4_digits_are_kept(typed, kept):
    assert last4(typed) == kept


def test_fewer_than_4_digits_is_refused_and_empty_clears():
    with pytest.raises(BankDetailError):
        last4("12")
    assert last4("") is None
