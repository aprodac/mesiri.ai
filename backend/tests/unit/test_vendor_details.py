"""PRC-04: a vendor's GSTIN and phone are tidied and checked when typed."""

from __future__ import annotations

import pytest

from mesiri.domains.vendors.details import (
    VendorDetailError,
    clean_address,
    clean_gstin,
    clean_phone,
)


def test_gstin_is_upper_case_without_spaces() -> None:
    assert clean_gstin(" 32abcde1234f1z5 ") == "32ABCDE1234F1Z5"
    assert clean_gstin("32 ABCDE 1234 F1Z5") == "32ABCDE1234F1Z5"
    assert clean_gstin("") is None and clean_gstin(None) is None


@pytest.mark.parametrize("bad", ["32ABC", "32ABCDE1234F1Y5", "ABCDE1234F1Z532", "32ABCDE1234F0Z5"])
def test_a_wrong_gstin_is_refused(bad: str) -> None:
    with pytest.raises(VendorDetailError):
        clean_gstin(bad)


def test_phone_keeps_digits_and_a_leading_plus() -> None:
    assert clean_phone("+91 98470-12345") == "+919847012345"
    assert clean_phone("0484 2345678") == "04842345678"
    assert clean_phone("  ") is None
    with pytest.raises(VendorDetailError):
        clean_phone("12-3")


def test_address_spaces() -> None:
    assert clean_address("  Edappally,   Kochi ") == "Edappally, Kochi"
    assert clean_address("") is None
