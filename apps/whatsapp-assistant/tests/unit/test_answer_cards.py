"""channel/cards/: answer card HTML (pure), CardRenderer's degrade-to-None
contract, and one real Chromium render when a browser is available."""

from __future__ import annotations

import pytest

from channel.cards import (
    MAX_ROWS,
    CardRenderer,
    RosterCard,
    RosterGroup,
    RosterPerson,
    TableCard,
    render_roster_card_html,
    render_table_card_html,
)
from channel.cards.snapshot import HtmlSnapshotter
from channel.receipt import ReceiptRenderer


def _stock_card(rows: int = 3) -> TableCard:
    return TableCard(
        title="Site stock · Green Valley Block A",
        subtitle="14 Oct, 3:14 pm",
        columns=("Material", "In stock", "Used this wk"),
        rows=tuple((f"Material {i}", f"{i} bags", f"{i * 2} bags") for i in range(rows)),
        numeric_columns=frozenset({1, 2}),
        flagged_rows=frozenset({0}),
        flag_note="less than 3 days at this week's rate",
    )


def test_table_card_escapes_user_text():
    """Material and site names are user data; markup in them must render as
    text and never reach Chromium as a tag (the BE-36 hole)."""
    card = TableCard(
        title='<script>alert(1)</script>',
        columns=("Material",),
        rows=(('<img src="http://169.254.169.254/x">',),),
    )

    html = render_table_card_html(card)

    assert "<script>alert" not in html
    assert '<img src="http://169.254.169.254' not in html
    assert "&lt;img src=&#34;http://169.254.169.254/x&#34;&gt;" in html


def test_roster_card_escapes_user_text():
    card = RosterCard(
        title="Reported today",
        groups=(RosterGroup("Reported", (RosterPerson("<b>Ravi</b>", "<i>A</i>"),), "ok"),),
    )

    html = render_roster_card_html(card)

    assert "<b>Ravi</b>" not in html and "&lt;b&gt;Ravi&lt;/b&gt;" in html


def test_table_card_caps_rows_and_says_how_many_more():
    html = render_table_card_html(_stock_card(rows=MAX_ROWS + 5))

    assert f"Material {MAX_ROWS - 1}<" in html
    assert f"Material {MAX_ROWS}<" not in html
    assert "+ 5 more" in html


def test_table_card_marks_flagged_rows_and_explains_the_marker():
    html = render_table_card_html(_stock_card())

    assert html.count('class="flag"') == 1
    assert "less than 3 days at this week&#39;s rate" in html


def test_table_card_right_aligns_numeric_columns():
    html = render_table_card_html(_stock_card(rows=1))

    assert '<td class="num">0 bags</td>' in html


def test_roster_card_keeps_a_row_for_every_group_even_when_the_first_is_long():
    """A long "reported" list must not push the "not yet" people -- the
    ones who matter -- off the card."""
    reported = tuple(RosterPerson(f"Engineer {i}") for i in range(30))
    card = RosterCard(
        title="Reporting today",
        groups=(
            RosterGroup("Reported", reported, "ok"),
            RosterGroup("Not yet", (RosterPerson("Suresh P."),), "wait"),
        ),
    )

    html = render_roster_card_html(card)

    assert "Suresh P." in html
    assert f"+ {30 - (MAX_ROWS - 1)} more" in html


class _FakeSnapshotter:
    def __init__(self, result=b"png", error: Exception | None = None):
        self.result = result
        self.error = error
        self.calls: list[tuple[str, dict]] = []

    async def render_png(self, html, **kwargs):
        self.calls.append((html, kwargs))
        if self.error:
            raise self.error
        return self.result


async def test_card_renderer_renders_on_the_shared_snapshotter_and_logs_as_card():
    snap = _FakeSnapshotter()

    png = await CardRenderer(snap).render(_stock_card())

    assert png == b"png"
    html, kwargs = snap.calls[0]
    assert "Site stock" in html
    assert kwargs == {"log_as": "card"}


async def test_card_renderer_returns_none_when_rendering_fails():
    png = await CardRenderer(_FakeSnapshotter(error=RuntimeError("chromium died"))).render(
        RosterCard(title="t", groups=())
    )

    assert png is None


def test_receipt_renderer_is_the_shared_snapshotter_with_its_old_log_prefix():
    renderer = ReceiptRenderer()

    assert isinstance(renderer, HtmlSnapshotter)
    assert renderer._log_prefix == "receipt"


async def test_real_render_produces_a_png():
    """One real Chromium render. Skipped where no browser is installed (the
    core suite runs without one), same as every other playwright path."""
    pytest.importorskip("playwright")
    snapshotter = HtmlSnapshotter()
    try:
        try:
            png = await CardRenderer(snapshotter).render(_stock_card(rows=8))
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"no usable Chromium: {exc}")
        if png is None:
            pytest.skip("no usable Chromium")
        assert png[:8] == b"\x89PNG\r\n\x1a\n"
    finally:
        await snapshotter.close()
