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


def _markup(html: str) -> str:
    """The page after its stylesheet (the embedded fonts are base64 noise)."""
    return html.split("</style>", 1)[1]


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


# =============================== Stock card ====================================

from types import SimpleNamespace  # noqa: E402

from channel.cards import build_stock_card, days_left, stock_html  # noqa: E402
from channel.replies import ReplySpec  # noqa: E402
from runtime.agent.query_entry import QueryEntry  # noqa: E402
from runtime.inventory_query import MaterialInventoryQueryService  # noqa: E402
from runtime.reply_dispatch import send_reply_spec  # noqa: E402


def _lvl(name, stock, received, unit="bags"):
    return {"material_name": name, "unit": unit, "received": received, "used": received - stock,
            "current_stock": stock}


def test_days_left_is_stock_over_the_daily_use_of_the_week():
    assert days_left(42, 70) == pytest.approx(4.2)  # 70 in 7 days = 10 a day
    assert days_left(10, 7) == pytest.approx(10)


def test_days_left_is_left_out_with_no_use_and_with_no_stock():
    assert days_left(42, 0) is None
    assert days_left(0, 70) is None
    assert days_left(-5, 70) is None


def test_stock_rows_note_days_or_received_and_scale_the_bar_to_received():
    card = build_stock_card(
        [_lvl("cement", 50, 200), _lvl("sand", 80, 100, "cft")],
        {("cement", "bags"): 70.0},
        where="Block A",
    )
    cement = next(r for r in card.rows if r.name == "Cement")
    sand = next(r for r in card.rows if r.name == "Sand")
    assert (cement.bar_pct, cement.note) == (25, "≈5 days at this week's use")
    assert (sand.bar_pct, sand.note) == (80, "received 100")  # no use: no days figure
    assert not card.low


def test_red_when_stock_is_zero_or_below_and_the_footer_says_low():
    card = build_stock_card([_lvl("steel", -100, 3000, "kg"), _lvl("sand", 600, 900, "cft")], {}, where="A")
    steel = card.rows[0]  # trouble first
    assert steel.name == "Steel" and steel.red and steel.low
    assert card.low
    html = stock_html(card)
    assert "Steel is out." in html and "#C8102E" in html
    zero = build_stock_card([_lvl("sand", 0, 900, "cft"), _lvl("tile", 5, 9, "nos")], {}, where="A")
    assert zero.rows[0].red and zero.rows[0].note == "out of stock"
    # Request 93: no stock draws an empty bar and a red "0", never a full red bar.
    assert zero.rows[0].bar_pct == 0 and zero.rows[0].stock == "0" and steel.bar_pct == 0


def test_footer_names_the_low_materials_two_at_most_then_a_count():
    use = {("cement", "bags"): 70.0, ("sand", "bags"): 70.0}
    one = build_stock_card([_lvl("steel", 0, 9, "kg"), _lvl("tile", 50, 90)], {}, where="A")
    assert one.footer == "Steel is out."
    two = build_stock_card([_lvl("steel", 0, 9, "kg"), _lvl("cement", 20, 200)], use, where="A")
    assert two.footer == "Steel is out. Cement ≈2 days left."
    three = build_stock_card(
        [_lvl("steel", 0, 9, "kg"), _lvl("cement", 20, 200), _lvl("sand", 25, 200)], use, where="A"
    )
    assert three.footer == "Steel is out. Cement ≈2 days left. +1 more"
    ok = build_stock_card([_lvl("cement", 30, 200), _lvl("sand", 80, 100)], use, where="A")
    assert ok.footer == "Stock now"


def test_card_and_text_reply_round_the_same_way():
    from channel.cards.stock import _fmt as card_fmt
    from workflows.material_inventory_query.nodes import _fmt as text_fmt

    for value in (1.4285, 12, 12.0, 2.5, 1234.5678, 0.001):
        assert card_fmt(value) == text_fmt(value)
    assert card_fmt(1.4285) == "1.43" and card_fmt(12.0) == "12"


def test_low_footer_when_under_three_days_left_but_not_red():
    card = build_stock_card([_lvl("cement", 20, 200), _lvl("sand", 80, 100)], {("cement", "bags"): 70.0}, where="A")
    cement = next(r for r in card.rows if r.name == "Cement")
    assert not cement.red and cement.low and card.low  # 20 / 10 a day = 2 days
    assert "≈2 days" in cement.note
    ok = build_stock_card([_lvl("cement", 30, 200), _lvl("sand", 80, 100)], {("cement", "bags"): 70.0}, where="A")
    assert not ok.low and "LOW" not in _markup(stock_html(ok))  # exactly 3 days is not low


def test_stock_card_with_long_names_and_many_rows():
    levels = [_lvl(f"material number {i} " + "x" * 40, 10 + i, 100) for i in range(11)]
    card = build_stock_card(levels, {}, where="w" * 80)
    assert len(card.rows) == 8 and card.more == 3
    html = stock_html(card)
    assert "+3 more" in html and "…" in html and "x" * 40 not in html


def test_stock_html_escapes_names():
    html = stock_html(build_stock_card([_lvl("<img src=x>", 5, 10), _lvl("sand", 5, 10)], {}, where="A"))
    assert "<img" not in _markup(html) and "&lt;Img" in html


# -- the image goes out with the reply as its caption ---------------------------


class _Out:
    def __init__(self, image_ok=True):
        self.calls = []
        self.image_ok = image_ok

    async def text(self, wa_id, body):
        self.calls.append(("text", body))
        return "w"

    async def image(self, wa_id, image, *, caption=None, filename="receipt.png"):
        self.calls.append(("image", caption, filename))
        return self.image_ok


async def _dispatch(spec, out):
    await send_reply_spec(spec, "91", send_text=out.text, send_image=out.image)


async def test_a_stock_reply_is_one_captioned_image():
    out = _Out()
    await _dispatch(ReplySpec(text="📦 stock", header_image=PNG, caption_image=True), out)
    assert out.calls == [("image", "📦 stock", "stock.png")]


async def test_a_failed_stock_image_sends_the_text():
    out = _Out(image_ok=False)
    await _dispatch(ReplySpec(text="📦 stock", header_image=PNG, caption_image=True), out)
    assert out.calls == [("image", "📦 stock", "stock.png"), ("text", "📦 stock")]


async def test_the_receipt_still_goes_text_then_image():
    out = _Out()
    await _dispatch(ReplySpec(text="✅ Saved", header_image=PNG), out)
    assert out.calls == [("text", "✅ Saved"), ("image", None, "receipt.png")]


# -- the stock tool draws the card -------------------------------------------------


class _Inventory:
    def __init__(self, usage=None, fail=False):
        self.usage, self.fail, self.asked = usage or {}, fail, 0

    async def usage_last_days(self, **kw):
        self.asked += 1
        if self.fail:
            raise RuntimeError("db")
        return self.usage


def _entry(renderer, inventory):
    actor = SimpleNamespace(sites=[SimpleNamespace(id="s1", name="Block A")], org_name="Acme")
    return QueryEntry(
        context_resolver=None, org_settings_query=None, actor=actor,
        inventory_query=inventory, card_renderer=renderer,
    )


def _ready(levels, **fields):
    event = SimpleNamespace(
        organization_id="o", project_id="p", site_id="s1",
        fields={"inventory_levels": levels, **fields},
    )
    return SimpleNamespace(event=event)


TWO = [_lvl("cement", 42, 200), _lvl("sand", 600, 900, "cft")]


async def test_an_all_materials_question_draws_the_card():
    entry, renderer = _entry(_Renderer(), _Inventory({("cement", "bags"): 70.0})), None
    renderer = entry.card_renderer
    await entry._stock_card(_ready(TWO))
    assert entry.stock_card == PNG and renderer.calls == 1


async def test_one_material_or_one_row_stays_text():
    for ready in (_ready(TWO, material_name="cement"), _ready(TWO[:1])):
        entry = _entry(_Renderer(), _Inventory())
        await entry._stock_card(ready)
        assert entry.stock_card is None and entry.card_renderer.calls == 0


async def test_a_render_failure_leaves_the_text():
    entry = _entry(_Renderer(fail=True), _Inventory())
    await entry._stock_card(_ready(TWO))
    assert entry.stock_card is None


async def test_a_failed_usage_read_still_draws_without_days():
    entry = _entry(_Renderer(), _Inventory(fail=True))
    await entry._stock_card(_ready(TWO))
    assert entry.stock_card == PNG


async def test_no_renderer_no_card():
    entry = _entry(None, _Inventory())
    await entry._stock_card(_ready(TWO))
    assert entry.stock_card is None


class _Conn:
    def __init__(self, rows):
        self.rows, self.sql, self.params = rows, None, None

    async def execute(self, sql, params):
        self.sql, self.params = str(sql), params
        return SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: self.rows))


class _Db:
    def __init__(self, conn):
        self.conn = conn

    def transaction(self):
        conn = self.conn

        class _Tx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *a):
                return False

        return _Tx()


async def test_usage_last_days_reads_seven_days_per_material_and_unit():
    import uuid

    conn = _Conn([{"name": "cement", "unit": "bags", "used": 70}, {"name": "cement", "unit": "kg", "used": 5}])
    now = datetime.datetime(2026, 10, 23, tzinfo=datetime.UTC)
    org, site = str(uuid.uuid4()), str(uuid.uuid4())
    usage = await MaterialInventoryQueryService(_Db(conn)).usage_last_days(
        organization_id=org, project_id=None, site_id=site, now=now
    )
    assert usage == {("cement", "bags"): 70.0, ("cement", "kg"): 5.0}
    assert conn.params["since"] == now - datetime.timedelta(days=7)
    assert "m.site_id = :site" in conn.sql and "m.project_id" not in conn.sql
    assert "INSERT" not in conn.sql.upper() and "UPDATE" not in conn.sql.upper()  # read-only


# =============================== Welcome card ==================================

import uuid  # noqa: E402

from backend.ports import ActorIdentity, ProjectSummary  # noqa: E402
from channel.cards import build_welcome_card, welcome_html  # noqa: E402
from channel.cards.welcome import EXAMPLES, FOOTER  # noqa: E402
from mesiri.infrastructure.redis.client import FakeRedis  # noqa: E402
from mesiri_contracts.assistant.draft_action import DraftActionType  # noqa: E402
from runtime import contact_share_journey as cs  # noqa: E402


def test_the_welcome_card_greets_by_first_name_and_role():
    card = build_welcome_card(first="Ravi", role_code="SITE_ENGINEER", added_by="Suresh", company="Acme Builders")
    html = welcome_html(card)
    body = _markup(html)
    assert "Hi Ravi." in body and "You're the site engineer." in body
    assert "Added by Suresh" in body and "Acme Builders" in body
    assert FOOTER.replace("'", "&#39;") in body and "Mesiri &middot; Welcome" in body


def test_welcome_uses_the_roles_own_examples():
    engineer = build_welcome_card(first="R", role_code="SITE_ENGINEER", added_by="S", company="A")
    supervisor = build_welcome_card(first="R", role_code="SUPERVISOR", added_by="S", company="A")
    assert engineer.examples == EXAMPLES["SITE_ENGINEER"] and len(engineer.examples) == 3
    assert supervisor.examples == EXAMPLES["SUPERVISOR"] != engineer.examples
    # the engineer's three: workers, progress, a stock question (Malayalam-English mix)
    assert "workers" in engineer.examples[0] and "Cement" in engineer.examples[2]
    for line in engineer.examples:
        assert line in welcome_html(engineer)


def test_an_unknown_role_gets_the_engineer_examples_and_a_readable_name():
    card = build_welcome_card(first="R", role_code="STORE_KEEPER", added_by="", company="")
    assert card.role == "store keeper" and card.examples == EXAMPLES["SITE_ENGINEER"]
    assert card.added_by == "your admin"


def test_welcome_with_a_long_name_and_markup_is_clipped_and_escaped():
    card = build_welcome_card(first="<b>" + "R" * 60, role_code="SITE_ENGINEER", added_by="S" * 90, company="C" * 90)
    body = _markup(welcome_html(card))
    assert "<b>" not in body and "…" in body and "R" * 60 not in body


def _admin():
    return ActorIdentity(
        user_id=str(uuid.uuid4()), full_name="Suresh Nair", role="ADMIN",
        organization_id=str(uuid.uuid4()), org_name="Acme Builders", org_active=True,
        projects=[ProjectSummary(id=str(uuid.uuid4()), name="Green Villa")],
    )


async def _joined(monkeypatch, *, renderer, send_image):
    async def fake_plan(**kw):
        return ReplySpec(text="confirm")

    monkeypatch.setattr(cs, "start_member_create_plan", fake_plan)
    texts = []

    async def send_text(to, body):
        texts.append((to, body))

    share = cs.ContactShareJourney(
        redis=FakeRedis(), db=None, plan_store=None, workflow_runtime=None,
        send_text=send_text, send_image=send_image, card_renderer=renderer,
    )

    async def nobody(phone):
        return None

    share._find_user = nobody  # type: ignore[method-assign]
    actor = _admin()
    await share.start_join(actor, name="Ravi Kumar", phone="919876500001", business_number="15550001111")
    to_owner = await share.invite_after_member_added(
        action_type=DraftActionType.ADD_PROJECT_MEMBER, member_name="Ravi Kumar", actor=actor
    )
    return to_owner, texts


async def test_the_joiner_gets_the_welcome_card_with_the_joined_text_as_caption(monkeypatch):
    images = []

    async def send_image(to, png, *, caption=None, filename="receipt.png"):
        images.append((to, png, caption, filename))
        return True

    to_owner, texts = await _joined(monkeypatch, renderer=_Renderer(), send_image=send_image)
    assert texts == []  # the text is the caption, not a second message
    [(to, png, caption, filename)] = images
    assert (to, png, filename) == ("919876500001", PNG, "welcome.png")
    assert caption.startswith("✅ You're in, Ravi! *Acme Builders* added you to *Green Villa*")
    assert to_owner == ["✅ *Ravi Kumar* can now report on *Green Villa*. I've told them they're in."]


@pytest.mark.parametrize("why", ["render", "upload"])
async def test_the_joined_text_goes_alone_when_the_card_cannot(monkeypatch, why):
    async def send_image(to, png, *, caption=None, filename="receipt.png"):
        return why != "upload"

    to_owner, texts = await _joined(
        monkeypatch, renderer=_Renderer(fail=why == "render"), send_image=send_image
    )
    [(to, body)] = texts
    assert to == "919876500001" and body.startswith("✅ You're in, Ravi! *Acme Builders* added you")
    assert to_owner[0].startswith("✅ *Ravi Kumar* can now report")


async def test_without_a_renderer_the_joiner_text_is_unchanged(monkeypatch):
    to_owner, texts = await _joined(monkeypatch, renderer=None, send_image=None)
    assert len(texts) == 1 and texts[0][1].startswith("✅ You're in, Ravi!")


async def test_deliver_draws_the_card_but_a_pdf_lookup_still_sends_the_pdf():
    from runtime.agent import query_entry as qe

    entry = _entry(_Renderer(), _Inventory())
    ready = SimpleNamespace(
        event=SimpleNamespace(organization_id="o", project_id="p", site_id="s1",
                              fields={"inventory_levels": TWO}),
        decision=SimpleNamespace(workflow_key=qe.K.MATERIAL_INVENTORY_QUERY),
    )
    message = SimpleNamespace(correlation_id="c", sender=SimpleNamespace(wa_id="91"))
    assert await entry.deliver(ready, message) is None
    assert entry.stock_card == PNG
    pdf = _entry(_Renderer(), _Inventory())
    ready.event.fields["output_format"] = "pdf"
    assert await pdf.deliver(ready, message) is None
    assert pdf.stock_card is None  # a PDF was asked for: no card
