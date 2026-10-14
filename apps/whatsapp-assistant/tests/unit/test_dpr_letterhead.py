"""DPR letterhead (BE-19): what the template prints, and how it is loaded."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from channel.dpr_document.data import build_document_data
from channel.dpr_document.letterhead import Letterhead, _data_uri

jinja2 = pytest.importorskip("jinja2")
from channel.dpr_document.template import render_html  # noqa: E402

_PNG_URI = "data:image/png;base64,iVBORw0KGgo="
_DATA = build_document_data(
    code="DPR-1",
    payload={"project_name": "Skyline", "site_name": "Block A", "report_date": "2026-10-13"},
)
_FULL = Letterhead(
    company_name="Acme Builders",
    address="12 MG Road, Pune",
    contact="+91 20 1234 · office@acme.test",
    gstin="27AAPFU0939F1ZV",
    brand_color="#C2410C",
    signatory_name="R. Rao",
    signatory_designation="Project Director",
    logo_data_uri=_PNG_URI,
    client_name="Skyline Developers",
    client_logo_data_uri=_PNG_URI,
)


def test_full_letterhead_is_printed():
    html = render_html(_DATA, _FULL)

    for text in (
        "Acme Builders",
        "12 MG Road, Pune",
        "GSTIN: 27AAPFU0939F1ZV",
        "Client: Skyline Developers",
        "R. Rao",
        "Project Director",
    ):
        assert text in html
    assert html.count(_PNG_URI) == 2  # company and client logos
    assert "#C2410C" in html  # brand colour replaces the default accent
    assert "Generated with Mesiri" in html


def test_without_letterhead_the_plain_header_stays():
    html = render_html(_DATA)

    assert 'class="letterhead"' not in html
    assert 'class="signatory"' not in html
    assert "#0A8F4C" in html  # default accent
    assert "Daily Progress Report" in html


def test_empty_parts_are_left_out():
    html = render_html(_DATA, Letterhead(company_name="Acme Builders"))

    assert 'class="letterhead"' in html
    assert "GSTIN" not in html
    assert "Client:" not in html
    assert "<img" not in html
    assert 'class="signatory"' not in html


def test_letterhead_text_is_escaped():
    html = render_html(
        _DATA,
        Letterhead(
            company_name="<script>alert(1)</script>",
            address='"><img src=x onerror=alert(1)>',
            signatory_name="<b>R</b>",
            client_name="A & B",
        ),
    )

    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "onerror=alert(1)>" not in html
    assert "<b>R</b>" not in html
    assert "A &amp; B" in html


class _Storage:
    def __init__(self, objects):
        self.objects = objects

    async def get_object(self, key):
        if key not in self.objects:
            raise KeyError(key)
        data, content_type = self.objects[key]
        return SimpleNamespace(data=data, content_type=content_type)


@pytest.mark.anyio
async def test_logo_data_uri_rules():
    org = uuid.uuid4()
    mine = f"org/{org}/branding/logo-a.png"
    storage = _Storage(
        {
            mine: (b"\x89PNG", "image/png"),
            f"org/{org}/branding/svg.svg": (b"<svg/>", "image/svg+xml"),
            f"org/{uuid.uuid4()}/branding/theirs.png": (b"\x89PNG", "image/png"),
        }
    )

    assert (await _data_uri(storage, org, mine)).startswith("data:image/png;base64,")
    assert await _data_uri(storage, org, f"org/{org}/branding/svg.svg") is None
    assert await _data_uri(storage, org, next(k for k in storage.objects if "theirs" in k)) is None
    assert await _data_uri(storage, org, f"org/{org}/branding/missing.png") is None
    assert await _data_uri(storage, org, None) is None


@pytest.mark.anyio
async def test_load_failure_gives_no_letterhead_instead_of_an_error():
    from channel.dpr_document.letterhead import load_letterhead

    class Broken:
        async def execute(self, *_a, **_k):
            raise RuntimeError("database down")

    assert await load_letterhead(Broken(), _Storage({}), uuid.uuid4()) is None
