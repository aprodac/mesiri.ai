"""A bank account's details (WEB-66): the bank, the branch's IFSC and the account number's last 4 digits. Pure.

The full account number is never kept: the last 4 are what tell two accounts apart on a statement, and nothing in
Mesiri pays out of an account, so the rest would only be a liability.
"""

from __future__ import annotations

import re

_IFSC = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
BANK_NAME_MAX = 80


class BankDetailError(ValueError):
    """A detail that cannot be saved, with a message fit to show the person."""


def clean_bank_name(value: str | None) -> str | None:
    text = " ".join((value or "").split())
    if len(text) > BANK_NAME_MAX:
        raise BankDetailError(f"The bank name is longer than {BANK_NAME_MAX} characters.")
    return text or None


def clean_ifsc(value: str | None) -> str | None:
    text = "".join((value or "").split()).upper()
    if not text:
        return None
    if not _IFSC.match(text):
        raise BankDetailError("An IFSC is 11 characters: 4 letters, a 0, then 6 letters or digits (e.g. SBIN0001234).")
    return text


def last4(value: str | None) -> str | None:
    """The last 4 digits of what was typed: the whole number or only its end ("•••• 1234", "XX1234")."""
    digits = re.sub(r"\D", "", value or "")
    if not digits:
        return None
    if len(digits) < 4:
        raise BankDetailError("Give at least the last 4 digits of the account number.")
    return digits[-4:]
