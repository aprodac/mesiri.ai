"""A bill (receipt) file added to an expense from the dashboard. Pure.

Until 5 Nov 2026 a bill could only reach an expense from WhatsApp (the photo the
expense was recorded from). The dashboard now adds one to an expense already
saved: a photo of the bill (the page shrinks it first) or a PDF.

Same transport as the company logo (``organizations/branding.py``): base64 in
JSON, and production's nginx keeps its default 1 MB body, so a file stays at
700 KB or under. The declared type must match the bytes.
"""

from __future__ import annotations

import base64
import binascii
import uuid

BILL_MAX_BYTES = 700 * 1024

_SIGNATURES: tuple[tuple[str, bytes, str], ...] = (
    ("image/jpeg", b"\xff\xd8\xff", "jpg"),
    ("image/png", b"\x89PNG\r\n\x1a\n", "png"),
    ("application/pdf", b"%PDF-", "pdf"),
)


def decode_bill(data_base64: str, content_type: str, what: str = "bill") -> tuple[bytes, str, str]:
    """Bytes, extension and canonical content type of a bill upload.

    ValueError, with a message fit to show the person, when it is not a usable bill. ``what`` names the file in
    those messages: the same rule takes a photo on a task (TSK-12).
    """
    try:
        data = base64.b64decode(data_base64 or "", validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("The file could not be read. Try again.") from exc
    if not data:
        raise ValueError("The file is empty.")
    if len(data) > BILL_MAX_BYTES:
        raise ValueError(f"The file is too big: a {what} must be 700 KB or smaller.")
    declared = (content_type or "").split(";")[0].strip().lower()
    if declared == "image/jpg":
        declared = "image/jpeg"
    if declared == "image/webp":
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            return data, "webp", "image/webp"
        raise ValueError("The file is not a WebP image.")
    for mime, signature, ext in _SIGNATURES:
        if declared == mime:
            if data.startswith(signature):
                return data, ext, mime
            raise ValueError("The file is not what it says it is.")
    raise ValueError(f"A {what} must be a photo (JPEG, PNG or WebP) or a PDF.")


def bill_key(organization_id: uuid.UUID, expense_id: uuid.UUID, extension: str) -> str:
    """Where the file is stored: under the company's own prefix, a fresh name each time."""
    return f"org/{organization_id}/expenses/{expense_id}/bill-{uuid.uuid4().hex}.{extension}"
