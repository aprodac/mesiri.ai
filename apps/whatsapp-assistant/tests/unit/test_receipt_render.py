"""The receipt template and renderer: markup checks (no browser) and real
Chromium renders of every receipt type (skipped where Chromium isn't installed)."""

from __future__ import annotations

import contextlib
import struct

import pytest
from tests.unit.receipt_samples import (
    CORRECTION,
    FIVE_TRADES,
    ISSUE,
    MALAYALAM,
    MATERIAL_IN,
    SEVEN_TRADES,
    all_samples,
    labour,
    multi,
    receipt,
)

from channel.receipt.template import render_html

pytest.importorskip("jinja2")


def test_card_is_620_wide_square_and_embeds_its_fonts():
    html = render_html(receipt(*MATERIAL_IN))
    assert "width: 620px" in html
    assert "border-radius" not in html and "box-shadow" not in html
    # Nothing is fetched at render time: the page has no network (locked_page.py).
    assert "http://" not in html and "https://" not in html and "@import" not in html
    assert html.count("data:font/woff2;base64,") == 3
    for family in ("Inter", "Noto Sans Malayalam", "Noto Sans Devanagari"):
        assert f'font-family: "{family}"' in html


def test_marker_shape_follows_the_record_type():
    assert "<polygon points=\"7,0.8 13.4,12.6 0.6,12.6\"/>" in render_html(receipt(*MATERIAL_IN))  # ▲
    assert "<polygon points=\"7,0 14,7 7,14 0,7\"/>" in render_html(receipt(*ISSUE))  # ◆
    assert '<circle cx="7" cy="7" r="6.2"/>' in render_html(labour(FIVE_TRADES))  # ●


def test_labour_bars_are_proportional_to_the_count():
    html = render_html(labour([("mason", 12), ("helper", 6), ("painter", 3)]))
    assert "width: 100%" in html and "width: 50%" in html and "width: 25%" in html


def test_correction_strikes_the_old_value():
    html = render_html(receipt(*CORRECTION))
    assert '<span class="old">120 sqm</span>' in html
    assert '<span class="new">150 sqm</span>' in html


def test_more_line_only_when_rows_were_left_out():
    assert "more &mdash; all saved" not in render_html(multi(10))
    assert "+3 more &mdash; all saved" in render_html(multi(12))


def test_the_old_design_is_gone():
    html = render_html(receipt(*MATERIAL_IN))
    for old in ("saved-pill", "badge-circle", "Saved at", "ribbon-undone"):
        assert old not in html


# -- real renders ----------------------------------------------------------------


@contextlib.asynccontextmanager
async def _renderer():
    """A renderer in the test's own event loop (Playwright objects are bound
    to the loop that created them, so this can't be a fixture)."""
    from channel.receipt.render import ReceiptRenderer

    r = ReceiptRenderer()
    try:
        await r._ensure_browser()
    except Exception as exc:  # noqa: BLE001 -- no Chromium here
        pytest.skip(f"Chromium not available: {exc}")
    try:
        yield r
    finally:
        await r.close()


def _png_size(png: bytes) -> tuple[int, int]:
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", png[16:24])


@pytest.mark.parametrize("name", sorted(all_samples()))
async def test_every_sample_renders_to_a_card_sized_png(name):
    async with _renderer() as renderer:
        png = await renderer.render_png(render_html(all_samples()[name]))
    width, height = _png_size(png)
    assert width == 620 * 2  # the card, clipped to its own edge, at 2x
    assert 300 * 2 < height < 1400 * 2
    assert len(png) < 5 * 1024 * 1024  # WhatsApp's header-image limit


async def test_height_grows_with_rows():
    async with _renderer() as renderer:
        five = _png_size(await renderer.render_png(render_html(labour(FIVE_TRADES))))[1]
        seven = _png_size(await renderer.render_png(render_html(labour(SEVEN_TRADES))))[1]
    assert seven > five


async def test_text_never_overflows_the_card():
    """Long names and Malayalam wrap inside the card instead of widening it."""
    long_names = receipt(
        *ISSUE,
        project="Riverside Tower Phase Two Residential Complex",
        site="Block A North Wing Podium Level " * 3,
    )
    async with _renderer() as renderer:
        for data in (long_names, receipt(*MALAYALAM, site="ബ്ലോക്ക് എ"), multi(12)):
            page = await renderer._browser.new_page(viewport={"width": 680, "height": 800})
            try:
                await page.set_content(render_html(data))
                widths = await page.evaluate(
                    "() => [document.querySelector('.card').scrollWidth,"
                    " document.querySelector('.card').clientWidth, document.body.scrollWidth]"
                )
                assert widths[0] <= widths[1] and widths[2] <= 680
            finally:
                await page.close()
