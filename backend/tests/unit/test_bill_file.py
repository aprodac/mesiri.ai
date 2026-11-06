"""WEB-60: a bill file added to an expense from the dashboard: a photo or a PDF, what it says it is, 700 KB or under."""

import base64
import uuid

import pytest

from mesiri.domains.expenses.bill_file import BILL_MAX_BYTES, bill_key, decode_bill


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


@pytest.mark.parametrize(
    ("data", "declared", "ext", "mime"),
    [
        (b"\xff\xd8\xff\xe0rest", "image/jpeg", "jpg", "image/jpeg"),
        (b"\xff\xd8\xff\xe0rest", "image/jpg", "jpg", "image/jpeg"),
        (b"\x89PNG\r\n\x1a\nrest", "image/png", "png", "image/png"),
        (b"RIFF\x00\x00\x00\x00WEBPrest", "image/webp", "webp", "image/webp"),
        (b"%PDF-1.7 rest", "application/pdf", "pdf", "application/pdf"),
    ],
)
def test_a_photo_or_pdf_is_accepted(data, declared, ext, mime):
    assert decode_bill(_b64(data), declared) == (data, ext, mime)


@pytest.mark.parametrize(
    ("payload", "declared"),
    [
        (_b64(b"<svg onload=x/>"), "image/svg+xml"),  # can carry script
        (_b64(b"%PDF-1.7"), "image/jpeg"),  # not what it says
        (_b64(b"\xff\xd8\xff" + b"0" * BILL_MAX_BYTES), "image/jpeg"),  # too big for the 1 MB body
        ("not base64!", "image/jpeg"),
        ("", "image/jpeg"),
    ],
)
def test_anything_else_is_refused_with_a_reason(payload, declared):
    with pytest.raises(ValueError) as caught:
        decode_bill(payload, declared)
    assert str(caught.value)


def test_the_file_is_stored_under_the_companys_prefix():
    org, expense = uuid.uuid4(), uuid.uuid4()
    key = bill_key(org, expense, "pdf")
    assert key.startswith(f"org/{org}/expenses/{expense}/bill-") and key.endswith(".pdf")
    assert key != bill_key(org, expense, "pdf")
