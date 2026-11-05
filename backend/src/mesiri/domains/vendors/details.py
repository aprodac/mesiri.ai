"""A vendor's contact details (PRC-04): phone, GSTIN, address.

GSTIN is India's 15-character GST number: state code (2 digits), PAN (5 letters, 4 digits, 1 letter), entity
number (1-9 or A-Z), "Z", and a check character. It is kept upper-case without spaces, and refused when it does
not have that shape (a typo caught when it is typed, not months later on a bill). The check character itself is
not verified: a valid-looking number is accepted.
"""

from __future__ import annotations

import re

_GSTIN = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")


class VendorDetailError(ValueError):
    """A detail that can't be saved; the message is for the person."""


def clean_gstin(value: str | None) -> str | None:
    """Upper-case, no spaces; None for empty. Raises ``VendorDetailError`` for a wrong shape."""
    text = re.sub(r"\s+", "", value or "").upper()
    if not text:
        return None
    if not _GSTIN.match(text):
        raise VendorDetailError(f"'{value}' is not a GSTIN: it has 15 characters, like 32ABCDE1234F1Z5.")
    return text


def clean_phone(value: str | None) -> str | None:
    """Digits and a leading +, spaces and dashes dropped; None for empty. Refused when under 6 digits."""
    text = (value or "").strip()
    if not text:
        return None
    plus = text.startswith("+")
    digits = re.sub(r"\D", "", text)
    if len(digits) < 6:
        raise VendorDetailError(f"'{value}' is not a phone number.")
    return ("+" if plus else "") + digits


def clean_address(value: str | None) -> str | None:
    text = " ".join((value or "").split())
    return text or None
