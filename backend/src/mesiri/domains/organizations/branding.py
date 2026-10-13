"""Company branding and logos for the DPR letterhead (BE-20, BE-33).

Pure rules, no I/O. What a company's letterhead is made of:

- From ``organizations`` (already there, not copied): name, address, phone,
  email.
- From the ``branding`` organization setting: the name to print if it differs
  from the account name, brand colour, GSTIN, the signatory's name and
  designation, and the stored logo's object key.
- Per project (``projects.client_logo_object_key``): the client's logo, shown
  on that project's DPRs.

Logos are set only through their upload endpoints, never through the generic
settings API: an object key written by hand could point at another company's
file, which the letterhead would then serve.
"""

from __future__ import annotations

import base64
import binascii
import re
import uuid

# Uploads arrive base64-encoded in JSON (no multipart dependency), which grows
# them by a third, and production's nginx keeps its default 1 MB body limit
# (mercon.conf sets no client_max_body_size). 700 KB of image stays under it,
# and is far more than a letterhead logo needs.
LOGO_MAX_BYTES = 700 * 1024

# Raster formats only. SVG can carry script and is not accepted.
_SIGNATURES: tuple[tuple[str, bytes, str], ...] = (
    ("image/png", b"\x89PNG\r\n\x1a\n", "png"),
    ("image/jpeg", b"\xff\xd8\xff", "jpg"),
)
LOGO_CONTENT_TYPES: tuple[str, ...] = (*(t for t, _, _ in _SIGNATURES), "image/webp")

# Fields a company admin edits. The logo key is deliberately absent.
TEXT_FIELDS: tuple[str, ...] = (
    "letterhead_name",
    "brand_color",
    "gstin",
    "signatory_name",
    "signatory_designation",
)

DEFAULT_BRANDING: dict[str, object] = {
    **dict.fromkeys(TEXT_FIELDS),
    "logo_object_key": None,
}

_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
# 2-digit state code, 10-character PAN, entity number, "Z", check character.
_GSTIN = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
_MAX_TEXT = 200


def branding_values(stored: object) -> dict[str, object]:
    """The full branding dict for a stored value, defaults filled in.

    Unknown or malformed stored content falls back to the default per field
    rather than failing a letterhead.
    """
    values = dict(DEFAULT_BRANDING)
    if isinstance(stored, dict):
        for key in DEFAULT_BRANDING:
            if isinstance(stored.get(key), str) and stored[key]:
                values[key] = stored[key]
    return values


def validate_text_fields(update: object) -> dict[str, str | None]:
    """Canonical form of an admin's edit; ValueError on anything invalid.

    Only fields present in ``update`` are returned. An empty string or null
    clears a field.
    """
    if not isinstance(update, dict):
        raise ValueError("branding must be an object")
    unknown = set(update) - set(TEXT_FIELDS)
    if unknown:
        raise ValueError(f"unknown branding field: {sorted(unknown)[0]}")
    clean: dict[str, str | None] = {}
    for key, raw in update.items():
        if raw is None:
            clean[key] = None
            continue
        if not isinstance(raw, str):
            raise ValueError(f"{key} must be text")
        value = raw.strip()
        if not value:
            clean[key] = None
            continue
        if len(value) > _MAX_TEXT:
            raise ValueError(f"{key} is too long")
        if key == "brand_color":
            if not _COLOR.match(value):
                raise ValueError("brand_color must look like #1F6FEB")
            value = value.upper()
        elif key == "gstin":
            value = value.upper().replace(" ", "")
            if not _GSTIN.match(value):
                raise ValueError("gstin is not a valid 15-character GSTIN")
        clean[key] = value
    return clean


def logo_extension(data: bytes, content_type: str) -> str:
    """File extension for a logo upload; ValueError if it isn't an accepted image.

    The declared type must match what the bytes actually are.
    """
    if not data:
        raise ValueError("the logo file is empty")
    if len(data) > LOGO_MAX_BYTES:
        raise ValueError("the logo must be 700 KB or smaller")
    declared = (content_type or "").split(";")[0].strip().lower()
    if declared == "image/jpg":
        declared = "image/jpeg"
    if declared == "image/webp":
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            return "webp"
        raise ValueError("the file is not a WebP image")
    for mime, signature, ext in _SIGNATURES:
        if declared == mime:
            if data.startswith(signature):
                return ext
            raise ValueError(f"the file is not a {ext.upper()} image")
    raise ValueError("the logo must be a PNG, JPEG or WebP image")


def decode_upload(data_base64: str, content_type: str) -> tuple[bytes, str, str]:
    """Bytes, file extension and canonical content type of a base64 logo upload.

    ValueError (with a message fit to show the user) when it isn't a usable logo.
    """
    try:
        data = base64.b64decode(data_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("data_base64 is not valid base64") from exc
    extension = logo_extension(data, content_type)
    return data, extension, "image/jpeg" if extension == "jpg" else f"image/{extension}"


def company_logo_key(organization_id: uuid.UUID, extension: str) -> str:
    # A fresh name per upload, so a link handed out for the old logo never
    # shows the new one and the old file can be removed safely.
    return f"org/{organization_id}/branding/logo-{uuid.uuid4().hex}.{extension}"


def client_logo_key(organization_id: uuid.UUID, project_id: uuid.UUID, extension: str) -> str:
    return f"org/{organization_id}/projects/{project_id}/client-logo-{uuid.uuid4().hex}.{extension}"


def owns_key(organization_id: uuid.UUID, key: object) -> bool:
    """True when ``key`` is a file stored under this company's prefix."""
    return isinstance(key, str) and key.startswith(f"org/{organization_id}/")
