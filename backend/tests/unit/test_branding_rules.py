"""Branding and logo rules (BE-20, BE-33)."""

from __future__ import annotations

import base64
import uuid

import pytest

from mesiri.domains.organizations import branding
from mesiri.domains.organizations import settings as org_settings

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 32


def test_text_fields_are_cleaned():
    clean = branding.validate_text_fields(
        {
            "letterhead_name": "  Acme Builders Pvt Ltd ",
            "brand_color": "#1f6feb",
            "gstin": "27aapfu0939f1zv",
            "signatory_name": "",
            "signatory_designation": None,
        }
    )
    assert clean == {
        "letterhead_name": "Acme Builders Pvt Ltd",
        "brand_color": "#1F6FEB",
        "gstin": "27AAPFU0939F1ZV",
        "signatory_name": None,
        "signatory_designation": None,
    }


@pytest.mark.parametrize(
    "update",
    [
        {"brand_color": "blue"},
        {"gstin": "27AAPFU0939F1Z"},
        {"gstin": "XXAAPFU0939F1ZV"},
        {"logo_object_key": "org/other/branding/logo.png"},
        {"letterhead_name": 5},
        {"letterhead_name": "x" * 201},
        ["not", "a", "dict"],
    ],
)
def test_invalid_text_fields_are_refused(update):
    with pytest.raises(ValueError):
        branding.validate_text_fields(update)


@pytest.mark.parametrize(
    ("data", "declared", "ext"),
    [
        (PNG, "image/png", "png"),
        (JPEG, "image/jpeg", "jpg"),
        (JPEG, "image/jpg", "jpg"),
        (WEBP, "image/webp", "webp"),
    ],
)
def test_accepted_logos(data, declared, ext):
    assert branding.logo_extension(data, declared) == ext


@pytest.mark.parametrize(
    ("data", "declared"),
    [
        (b"", "image/png"),
        (JPEG, "image/png"),  # declared type must match the bytes
        (PNG, "image/svg+xml"),
        (b"<svg onload=alert(1)>", "image/svg+xml"),
        (PNG + b"\x00" * branding.LOGO_MAX_BYTES, "image/png"),
    ],
)
def test_refused_logos(data, declared):
    with pytest.raises(ValueError):
        branding.logo_extension(data, declared)


def test_decode_upload():
    data, ext, content_type = branding.decode_upload(base64.b64encode(JPEG).decode(), "image/jpeg")
    assert (data, ext, content_type) == (JPEG, "jpg", "image/jpeg")
    with pytest.raises(ValueError, match="base64"):
        branding.decode_upload("not base64!!", "image/png")


def test_keys_are_fresh_and_scoped_to_the_company():
    org, project = uuid.uuid4(), uuid.uuid4()
    first, second = branding.company_logo_key(org, "png"), branding.company_logo_key(org, "png")
    client = branding.client_logo_key(org, project, "jpg")

    assert first != second
    assert all(branding.owns_key(org, k) for k in (first, second, client))
    assert f"/projects/{project}/" in client
    assert not branding.owns_key(uuid.uuid4(), first)
    assert not branding.owns_key(org, None)


def test_stored_values_fall_back_per_field():
    assert branding.branding_values(None) == branding.DEFAULT_BRANDING
    values = branding.branding_values({"gstin": "27AAPFU0939F1ZV", "brand_color": 7, "junk": "x"})
    assert values["gstin"] == "27AAPFU0939F1ZV"
    assert values["brand_color"] is None
    assert "junk" not in values


def test_generic_settings_api_cannot_write_branding():
    assert org_settings.is_known_key(org_settings.BRANDING)
    with pytest.raises(ValueError, match="own page"):
        org_settings.validate(org_settings.BRANDING, {"logo_object_key": "org/x/secret.png"})
