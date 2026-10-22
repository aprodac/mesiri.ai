"""The onboarding cards (SS-17): view models, markup, and real renders."""

from __future__ import annotations

import contextlib
import struct

import pytest

from channel.onboarding_cards import (
    STEP_KEYS,
    ProgressFacts,
    build_progress_card,
    build_ready_card,
    build_welcome_card,
    detect_lang,
    language_to_lang,
    render_card_png,
    render_html,
)

pytest.importorskip("jinja2")

ALL = ProgressFacts(first_update=True, materials=True, logo=True, site_engineer=True, report_time=True)


def test_welcome_card_text_en():
    card = build_welcome_card("en")
    assert card.header == "MESIRI · WELCOME"
    assert card.headline == "Tell me what happened. I keep the records."
    assert [k for k, _ in card.rows] == ["Tell", "Ask", "Get"]
    assert "6 mason, 10 helper vannu" in card.rows[0][1]
    assert "cement stock ethra?" in card.rows[1][1]
    assert card.footer == "Type or send a voice note · Malayalam or English"


def test_ready_card_splits_site_and_place():
    card = build_ready_card(company="Suresh Builders", site_name="Green Villa, Kakkanad")
    assert card.headline == "Green Villa is live."
    assert card.subline == "Suresh Builders · Kakkanad"
    assert card.rows[2][0] == "Daily report at 9 pm" and card.rows[2][1] == "On"
    assert all(done for *_, done in card.rows)
    assert card.action_label == "TRY IT NOW"
    assert card.action_text == "Send: 6 mason, 10 helper vannu"


def test_ready_card_without_a_place_shows_the_company_alone():
    assert build_ready_card(company="Acme", site_name="Tower 1").subline == "Acme"


def test_progress_none_done_but_the_company():
    card = build_progress_card(site_name="Green Villa, Kakkanad", facts=ProgressFacts())
    assert (card.done, card.total) == (1, 6)
    assert card.subline == "Green Villa · about 5 min left"
    assert card.next_step == "first_update"
    assert card.action_label == "NEXT"
    assert card.action_text == "Send: 6 mason, 10 helper vannu"


def test_progress_partial_next_is_the_first_pending_step():
    facts = ProgressFacts(first_update=True, materials=True, site_engineer=True)
    card = build_progress_card(site_name="Green Villa", facts=facts)
    assert card.done == 4
    assert card.next_step == "logo"  # not site_engineer (done) and not report_time (later)
    assert "company logo" in card.action_text
    assert [done for _, done in card.steps] == [True, True, True, False, True, False]


def test_progress_next_follows_the_order_of_the_steps():
    for index, key in enumerate(STEP_KEYS[1:], start=1):
        facts = ProgressFacts(**{k: True for k in STEP_KEYS[:index]})
        assert build_progress_card(site_name="S", facts=facts).next_step == key


def test_progress_all_done():
    card = build_progress_card(site_name="Green Villa", facts=ALL)
    assert (card.done, card.total) == (6, 6)
    assert card.next_step is None
    assert card.action_label == "ALL SET"
    assert card.subline == "Green Villa · all set"


def test_malayalam_cards_are_translated_and_keep_the_examples():
    welcome = build_welcome_card("ml")
    assert welcome.headline != build_welcome_card("en").headline
    assert "6 mason, 10 helper vannu" in welcome.rows[0][1]
    progress = build_progress_card(site_name="Green Villa", facts=ProgressFacts(), lang="ml")
    assert progress.steps[0][0] == "കമ്പനിയും സൈറ്റും"
    assert "6 mason, 10 helper vannu" in progress.action_text


def test_language_choice():
    assert detect_lang("Hi", "സുരേഷ് ബിൽഡേഴ്സ്") == "ml"
    assert detect_lang("Suresh Builders", None, "Green Villa") == "en"
    assert language_to_lang("Malayalam") == "ml" and language_to_lang("ml") == "ml"
    assert language_to_lang("Hindi") == "en" and language_to_lang(None) == "en"


def test_markup_is_the_swiss_design_and_escapes_owner_text():
    html = render_html(
        build_ready_card(company="<b>Acme</b> & Co", site_name="<script>x</script>, Kochi")
    )
    assert "<script>x" not in html and "&lt;script&gt;" in html and "&lt;b&gt;Acme" in html
    assert "width: 540px" in html and "height: 675px" in html  # 4:5; 2x = 1080 x 1350
    assert "#1a7f4b" in html  # the one colour
    assert "border-radius: 50%" in html
    assert "box-shadow" not in html
    assert "http://" not in html and "https://" not in html and "@import" not in html
    assert html.count("data:font/woff2;base64,") == 3


def test_green_only_marks_done_rows():
    done = render_html(build_progress_card(site_name="S", facts=ALL))
    none = render_html(build_progress_card(site_name="S", facts=ProgressFacts()))
    assert done.count('class="dot done"') == 6
    assert none.count('class="dot done"') == 1 and none.count('class="dot"') == 5


@pytest.mark.parametrize("lang", ["en", "ml"])
def test_html_snapshot_per_language(lang):
    html = render_html(build_welcome_card(lang))
    assert f'<div class="card {lang}">' in html
    assert build_welcome_card(lang).headline in html


async def test_render_failure_returns_none():
    class Boom:
        async def render_png(self, html):
            raise RuntimeError("no chromium")

    assert await render_card_png(Boom(), build_welcome_card()) is None
    assert await render_card_png(None, build_welcome_card()) is None


@pytest.mark.parametrize("lang", ["en", "ml"])
async def test_real_render_is_1080_by_1350(lang):
    pytest.importorskip("playwright")
    from channel.receipt import ReceiptRenderer

    renderer = ReceiptRenderer()
    try:
        try:
            png = await render_card_png(
                renderer, build_progress_card(site_name="Green Villa", facts=ProgressFacts(), lang=lang)
            )
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"Chromium unavailable: {exc}")
        if png is None:
            pytest.skip("Chromium unavailable")
        assert png[:8] == b"\x89PNG\r\n\x1a\n"
        assert struct.unpack(">II", png[16:24]) == (1080, 1350)
    finally:
        with contextlib.suppress(Exception):
            await renderer.close()
