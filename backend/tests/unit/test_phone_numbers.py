"""BE-04: the shared "one WhatsApp number = one person" helper (no database)."""

from __future__ import annotations

from mesiri.application.identity.phone_numbers import (
    whatsapp_digits,
    whatsapp_number_taken,
)


def test_digits_ignore_spacing_and_punctuation() -> None:
    assert whatsapp_digits("+91 98765-43210") == "919876543210"
    assert whatsapp_digits(None) == ""
    assert whatsapp_digits("n/a") == ""


async def test_a_number_with_no_digits_is_never_taken_and_skips_the_database() -> None:
    class _NoDb:
        async def execute(self, *_a, **_k):
            raise AssertionError("must not query")

    assert not await whatsapp_number_taken(_NoDb(), "  ")  # type: ignore[arg-type]
    assert not await whatsapp_number_taken(_NoDb(), None)  # type: ignore[arg-type]

