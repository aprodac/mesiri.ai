"""Request 91: the Swiss cards -- Today (evening confirm), Stock, Welcome.

HTML for typical, empty and long-name data; the send paths and their text
fallback; the receipt's send_image unchanged."""

from __future__ import annotations

import datetime

import pytest

pytest.importorskip("jinja2")

from channel.cards import (  # noqa: E402
    build_today_card,
    render_payload_card,
    today_html,
    today_payload,
)
from channel.cards.base import clip  # noqa: E402
from channel.whatsapp.outbound import WhatsAppSender  # noqa: E402
from channel.whatsapp.templates import SITE_DAY_REVIEW, choose_template  # noqa: E402
from runtime import site_day_review as sdr  # noqa: E402
from runtime.send_pending_notifications import _send_one  # noqa: E402

DAY = datetime.date(2026, 10, 23)
PNG = b"\x89PNG-card"

TYPICAL = {
    "labour": {
        "headcount": 24,
        "trades": [
            {"trade": "mason", "headcount": 10},
            {"trade": "helper", "headcount": 9},
            {"trade": "bar_bender", "headcount": 5},
        ],
    },
    "materials": [
        {"material_name": "cement", "unit": "bags", "used": "18", "closing": "42"},
        {"material_name": "sand", "unit": "cft", "used": "2", "closing": "80"},
    ],
    "activities": [
        {"work_type": "plastering", "narrative": "2nd floor east"},
        {"work_type": "slab shuttering", "narrative": ""},
        {"work_type": "third", "narrative": ""},
    ],
    "activity_count": 3,
    "open_issue_count": 1,
    "issues": [
        {"status": "CLOSED", "narrative": "old"},
        {"status": "OPEN", "narrative": "Water pump not working"},
    ],
}


def _card(payload, **kw):
    return build_today_card(
        payload, site_name=kw.pop("site_name", "Block A"), report_date=DAY,
        footer=kw.pop("footer", "Draft · goes out at 9:00 pm"),
    )


# -- Today: the data ------------------------------------------------------------


def test_today_card_reads_the_day_payload():
    card = _card(TYPICAL)
    assert card.workers_total == 24
    assert card.trades == (("Mason", 10), ("Helper", 9), ("Bar bender", 5))
    # the material that moved most, with its stock left and what was used
    assert (card.material_name, card.material_stock, card.material_used) == ("Cement", "42", "18")
    assert card.progress == ("Plastering", "Slab shuttering")  # at most two lines
    assert (card.issue_count, card.first_issue) == (1, "Water pump not working")
    assert card.date_label == "23 Oct"


def test_today_card_for_an_empty_day():
    card = _card({})
    assert card.workers_total == 0 and card.trades == ()
    assert card.material_name is None and card.progress == () and card.issue_count == 0
    html = today_html(card)
    assert "no count yet" in html and "nothing logged yet" in html and "none open" in html


def test_a_material_without_closing_stock_shows_what_was_used():
    card = _card({"materials": [{"material_name": "cement", "unit": "bags", "used": "18"}]})
    assert card.material_stock == "–"
    assert "18 bags used today" in today_html(card)


def test_more_than_three_trades_fold_into_other():
    trades = [{"trade": t, "headcount": n} for t, n in (("a", 5), ("b", 4), ("c", 3), ("d", 2), ("e", 1))]
    assert _card({"labour": {"headcount": 15, "trades": trades}}).trades[-1] == ("other", 3)


# -- Today: the markup ----------------------------------------------------------


def test_today_html_has_the_swiss_frame_and_is_escaped():
    card = _card(
        {**TYPICAL, "issues": [{"status": "OPEN", "narrative": "<script>x</script> leak"}]},
        site_name="Block <b>A</b>",
    )
    html = today_html(card)
    assert "Mesiri &middot; Today" in html and 'class="card"' in html
    assert "DRAFT" not in html and "Draft · goes out at 9:00 pm" in html  # case via CSS only
    assert "<script>x</script>" not in html and "&lt;script&gt;" in html
    assert "<b>A</b>" not in html


def test_long_names_are_clipped():
    long = "Very long site name " * 6
    card = _card({**TYPICAL, "activities": [{"work_type": long}]}, site_name=long)
    html = today_html(card)
    assert "…" in html and long not in html
    assert len(card.progress[0]) <= 46
    assert clip("x" * 100, 10) == "xxxxxxxxx…"


def test_the_card_round_trips_through_a_notification_payload():
    card = _card(TYPICAL)
    from channel.cards import TodayCard

    assert TodayCard.from_dict(today_payload(card)["data"]) == card


# -- Today: sending -------------------------------------------------------------


class _Renderer:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = 0

    async def render_png(self, html):
        self.calls += 1
        if self.fail:
            raise RuntimeError("chromium down")
        return PNG


class _Sender:
    def __init__(self, *, image_ok=True):
        self.sent = []
        self.image_ok = image_ok

    async def send_button(self, wa_id, *, body, buttons, header_image=None):
        self.sent.append(("button", body, [b.id for b in buttons], header_image))
        return header_image is None or self.image_ok

    async def send_text(self, wa_id, text):
        self.sent.append(("text", text))
        return True

    async def send_image(self, wa_id, image, *, caption=None, filename="receipt.png"):
        self.sent.append(("image", caption, filename))
        return self.image_ok

    async def send_document(self, *a, **k):
        self.sent.append(("document",))
        return True


def _row(card=None, *, buttons=True):
    payload = {"message": "📋 *Block A*: today's report is ready."}
    if buttons:
        payload["buttons"] = [{"id": "sdr:closed:1:20261023", "title": "Site closed today"}]
    if card:
        payload["card"] = card
    return {"rule_key": "site_day_review:1", "payload": payload}


async def _send(row, sender, renderer):
    return await _send_one(row, wa_id="91", sender=sender, object_storage=None, card_renderer=renderer)


async def test_the_card_rides_as_the_header_of_the_buttons_with_the_text_as_body():
    sender = _Sender()
    assert await _send(_row(today_payload(_card(TYPICAL))), sender, _Renderer())
    assert sender.sent == [
        ("button", "📋 *Block A*: today's report is ready.", ["sdr:closed:1:20261023"], PNG)
    ]


async def test_a_render_failure_sends_the_text_and_the_same_buttons():
    sender = _Sender()
    assert await _send(_row(today_payload(_card(TYPICAL))), sender, _Renderer(fail=True))
    assert sender.sent == [
        ("button", "📋 *Block A*: today's report is ready.", ["sdr:closed:1:20261023"], None)
    ]


async def test_a_failed_image_upload_falls_back_to_the_text():
    sender = _Sender(image_ok=False)
    assert await _send(_row(today_payload(_card(TYPICAL))), sender, _Renderer())
    assert [s[0] for s in sender.sent] == ["button", "button"]
    assert sender.sent[-1][3] is None


async def test_no_card_or_no_renderer_is_the_old_message():
    for row, renderer in ((_row(), _Renderer()), (_row(today_payload(_card(TYPICAL))), None)):
        sender = _Sender()
        assert await _send(row, sender, renderer)
        assert sender.sent == [
            ("button", "📋 *Block A*: today's report is ready.", ["sdr:closed:1:20261023"], None)
        ]


async def test_a_garbled_card_is_ignored():
    renderer = _Renderer()
    assert await render_payload_card({"kind": "today", "data": {"nope": 1}}, renderer) is None
    assert await render_payload_card({"kind": "other"}, renderer) is None
    assert renderer.calls == 0


async def test_the_project_report_goes_as_a_captioned_image_then_the_pdf():
    sender = _Sender()
    row = _row(today_payload(_card(TYPICAL)), buttons=False)
    row["payload"]["document_object_key"] = None
    assert await _send(row, sender, _Renderer())
    assert sender.sent == [("image", "📋 *Block A*: today's report is ready.", "today.png")]
    sender = _Sender()
    assert await _send(row, sender, _Renderer(fail=True))
    assert sender.sent == [("text", "📋 *Block A*: today's report is ready.")]


# -- Today: the review payloads -------------------------------------------------


def test_every_review_payload_carries_a_card_with_the_cutoff_in_its_footer():
    card = sdr.day_card(TYPICAL, site_name="Block A", report_date=DAY, deadline="21:00")
    assert card["data"]["footer"] == "Draft · goes out at 9:00 pm"
    confirmed = sdr.day_card(TYPICAL, site_name="Block A", report_date=DAY, deadline="21:00", status="APPROVED")
    assert confirmed["data"]["footer"] == "Confirmed"
    gap = sdr.gap_check_payload(
        site_id="s", site_name="Block A", project_name=None,
        missing={"blocking": ["labour"]}, deadline="21:00", report_date=DAY, card=card,
    )
    assert gap["card"] == card
    nothing = sdr.no_update_payload(
        site_id="s", site_name="Block A", project_name=None, deadline="21:00", report_date=DAY, card=card
    )
    assert nothing["card"] == card
    assert "card" not in sdr.no_update_payload(
        site_id="s", site_name="Block A", project_name=None, deadline="21:00", report_date=DAY
    )


def test_outside_the_window_the_approved_template_is_unchanged_by_the_card():
    card = sdr.day_card(TYPICAL, site_name="Block A", report_date=DAY, deadline="21:00")
    payload = sdr.gap_check_payload(
        site_id="s", site_name="Block A", project_name=None,
        missing={"blocking": ["labour"]}, deadline="21:00", report_date=DAY, card=card,
    )
    choice = choose_template(payload, frozenset({SITE_DAY_REVIEW.name}))
    assert choice.spec is SITE_DAY_REVIEW
    assert list(choice.body_params) == payload["template"]["body_params"]


# -- the receipt's send_image is unchanged ---------------------------------------


async def test_send_image_names_the_upload_receipt_png_unless_told_otherwise(monkeypatch):
    sender = WhatsAppSender(client=None, access_token="t", phone_number_id="1")
    uploads, posts = [], []

    async def upload(data, *, mime_type, filename):
        uploads.append(filename)
        return "media-1"

    async def send(to, body):
        posts.append(body)
        return "wamid"

    monkeypatch.setattr(sender, "_upload_media", upload)
    monkeypatch.setattr(sender, "_send", send)
    assert await sender.send_image("91", PNG, caption="c")
    assert await sender.send_image("91", PNG, caption="c", filename="today.png")
    assert uploads == ["receipt.png", "today.png"]
    assert posts[0] == {"type": "image", "image": {"id": "media-1", "caption": "c"}}
