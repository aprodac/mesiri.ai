"""WEB-53: the company Live's feed (GET /dpr/live/feed): what each message
was (one table, ``live_feed.classify``), how far it got, and who sees it:
the site rule for a site's messages, the project rule for a project's, the
whole company for neither, and spending only for the roles that see it
(SEC-01)."""

from __future__ import annotations

import datetime
import uuid

import pytest
from fastapi import HTTPException

from mesiri.authorization.context import (
    AccessPolicy,
    AuthorizationContext,
    ProjectAccessScope,
    SiteAccessScope,
)
from mesiri.domains.dpr import live_feed
from mesiri.domains.dpr import router as dpr_router

ORG = uuid.uuid4()
P1, P2 = uuid.uuid4(), uuid.uuid4()
S1, S2 = uuid.uuid4(), uuid.uuid4()
SINCE = datetime.datetime(2026, 11, 5, tzinfo=datetime.UTC)
UNTIL = SINCE + datetime.timedelta(days=1)


def _turn(tools=(), **kw):
    return {"tools": list(tools), **kw}


def _row(id_, turns=(), type_="text", project=P1, site=S1, **kw):
    return {
        "id": id_, "type": type_, "text": f"msg {id_}", "translated_text": None, "reply": "ok",
        "media_object_key": None, "received_at": SINCE.isoformat(), "project_id": project, "site_id": site,
        "site_name": "Tower A", "project_name": "Skyline", "sender_name": "Ravi", "source": "whatsapp", "first_message": False,
        "turns": list(turns), **kw,
    }


# --- classify: every kind of message -------------------------------------------------------------

@pytest.mark.parametrize(
    ("tools", "kind"),
    [
        (["search_materials", "record_receipt"], "delivery"),
        (["record_usage"], "usage"),
        (["record_transfer"], "transfer"),
        (["list_workers", "record_attendance"], "attendance"),
        (["record_work"], "work"),
        (["work_item", "correct_work"], "correction"),
        (["report_issue"], "issue"),
        (["list_issues", "resolve_issue"], "issue_closed"),
        (["undo_receipt"], "undo"),
        (["add_site"], "setup"),
        (["add_material_alias"], "catalogue"),
        (["set_reply_language"], "language"),
        (["send_dpr"], "report"),
        (["record_expense"], "expense"),
        (["stock_levels"], "question"),
        (["explain_mesiri"], "intro"),
    ],
)
def test_each_tool_says_what_the_message_was(tools, kind):
    what = live_feed.classify(_row("m", [_turn(tools)]))
    assert what["kind"] == kind
    assert what["label"] == live_feed.KIND_LABELS[kind]


def test_a_prepared_entry_is_a_draft_until_saved():
    draft = live_feed.classify(_row("m", [_turn(["record_receipt"], pending=["Cement 50 bags in"])]))
    assert (draft["state"], draft["summaries"]) == ("draft", ["Cement 50 bags in"])

    saved = live_feed.classify(_row("m", [_turn(["record_receipt"], saved=[{"summary": "Cement 50 bags in", "status": 201}])]))
    assert (saved["state"], saved["summaries"]) == ("saved", ["Cement 50 bags in"])


def test_a_save_tap_says_what_it_saved_and_a_refused_save_fails():
    tap = live_feed.classify(_row("m", [_turn(save_results=[{"summary": "8 masons", "tool": "record_attendance", "status": 201}])]))
    assert (tap["kind"], tap["state"], tap["saved_kind"]) == ("saved", "saved", "attendance")

    refused = live_feed.classify(_row("m", [_turn(save_results=[{"summary": "8 masons", "tool": "record_attendance", "status": 422}])]))
    assert refused["state"] == "failed"


def test_asked_back_photo_cancel_and_chat():
    assert live_feed.classify(_row("m", [_turn(["search_materials"], asked="Which size of TMT?")]))["state"] == "asked"
    assert live_feed.classify(_row("m", type_="image"))["kind"] == "photo"
    assert live_feed.classify(_row("m", [_turn(cancelled=["x"])]))["kind"] == "cancelled"
    hi = live_feed.classify(_row("m"))
    assert (hi["kind"], hi["state"]) == ("chat", "heard")


def test_spending_is_marked_money():
    assert live_feed.classify(_row("m", [_turn(["record_expense"])]))["money"] is True
    assert live_feed.classify(_row("m", [_turn(["list_expenses"])]))["money"] is True
    assert live_feed.classify(_row("m", [_turn(save_results=[{"tool": "record_expense", "status": 201}])]))["money"] is True
    # The guard: a material receipt is not spending.
    assert live_feed.classify(_row("m", [_turn(["record_receipt"])]))["money"] is False


def test_what_mesiri_did_in_plain_words_once_each():
    what = live_feed.classify(_row("m", [_turn(["search_materials", "stock_check", "stock_check", "record_usage", "unknown_tool"])]))
    assert what["did"] == ["Found the material", "Checked the stock", "Prepared the usage"]


def test_a_transfer_names_its_two_sites():
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    what = live_feed.classify(_row("m", [_turn(["record_transfer"], writes=[{"tool": "record_transfer", "args": {"from_site_id": a, "to_site_id": b}}])]))
    assert (what["kind"], what["transfer"]) == ("transfer", {"from_site_id": a, "to_site_id": b})
    # The guard: a half-known transfer draws no arc.
    half = live_feed.classify(_row("m", [_turn(["record_transfer"], writes=[{"tool": "record_transfer", "args": {"from_site_id": a, "to_site_id": None}}])]))
    assert half["transfer"] is None


def test_a_bill_photo_says_what_mesiri_read_from_it():
    what = live_feed.classify(_row("m", [_turn(["record_expense"], writes=[{"tool": "record_expense", "args": {
        "amount": "4500", "vendor_text": "KP Fuels", "category_text": "Diesel", "occurred_date": "2026-11-05",
        "tax_amount": None, "project_id": "p"}}])], type_="image"))
    assert what["kind"] == "expense" and what["money"] is True
    assert what["expense"] == {"amount": "4500", "vendor": "KP Fuels", "category": "Diesel", "date": "2026-11-05", "tax": None, "what": None}
    # The guard: no amount, no bill moment.
    assert live_feed.classify(_row("m", [_turn(["record_expense"], writes=[{"tool": "record_expense", "args": {}}])]))["expense"] is None


def test_a_language_change_names_the_language():
    what = live_feed.classify(_row("m", [_turn(["set_reply_language"], writes=[{"tool": "set_reply_language", "args": {"reply_language": "malayalam"}}])]))
    assert (what["kind"], what["language"]) == ("language", "malayalam")


def test_what_can_mesiri_do_is_an_intro_answered():
    what = live_feed.classify(_row("m", [_turn(["explain_mesiri"])], type_="voice"))
    assert (what["kind"], what["state"], what["label"]) == ("intro", "answered", "About Mesiri")
    # The guard: an entry made in the same turn stays the entry.
    assert live_feed.classify(_row("m", [_turn(["explain_mesiri", "record_receipt"])]))["kind"] == "delivery"


def test_unknown_trace_shapes_never_break_it():
    what = live_feed.classify(_row("m", [None, {"tools": None, "saved": "x", "pending": [None, ""]}]))  # type: ignore[list-item]
    assert what["kind"] == "chat"


# --- the endpoint: who sees what -----------------------------------------------------------------

class _Feed:
    rows: list = []

    def __init__(self, conn):
        pass

    async def live_feed(self, **kw):
        return [dict(r) for r in _Feed.rows]


class _Storage:
    async def generate_presigned_url(self, key, expires_in_seconds):
        return f"https://media.example/{key}"


@pytest.fixture(autouse=True)
def _fakes(monkeypatch):
    monkeypatch.setattr(dpr_router, "PostgresFactReviewRepository", _Feed)
    _Feed.rows = [
        _row("s1", [_turn(["record_receipt"])]),
        _row("s2", [_turn(["record_work"])], site=S2),
        _row("p2", [_turn(["record_work"])], project=P2, site=None),
        _row("none", [_turn(["create_project"])], project=None, site=None),
        _row("money", [_turn(["record_expense"])]),
    ]


def _ctx(role, project_scope, site_scopes=None):
    return AuthorizationContext(
        user_id=uuid.uuid4(), organization_id=ORG, role=role, status="active",
        access_policy=AccessPolicy(mode=project_scope.mode, projects=[]),
        project_scope=project_scope, site_scopes=site_scopes or {},
    )


def _admin():
    every_site = SiteAccessScope(mode="all_sites", site_ids=set())
    return _ctx("ADMIN", ProjectAccessScope(mode="all_projects", project_ids=set()), {P1: every_site, P2: every_site})


async def _ids(ctx):
    res = await dpr_router.list_live_feed(SINCE, UNTIL, auth_context=ctx, conn=None, object_storage=_Storage())
    return [i["id"] for i in res["items"]]


async def test_an_admin_sees_the_whole_company():
    admin = _admin()
    assert await _ids(admin) == ["s1", "s2", "p2", "none", "money"]


async def test_a_site_engineer_sees_only_their_site_and_no_spending():
    only_s1 = _ctx(
        "SITE_ENGINEER", ProjectAccessScope(mode="custom_projects", project_ids={P1}),
        {P1: SiteAccessScope(mode="custom_sites", site_ids={S1})},
    )
    assert await _ids(only_s1) == ["s1"]


async def test_items_carry_no_trace_internals():
    admin = _admin()
    res = await dpr_router.list_live_feed(SINCE, UNTIL, auth_context=admin, conn=None, object_storage=_Storage())
    first = res["items"][0]
    assert "turns" not in first and "media_object_key" not in first and "money" not in first
    assert (first["kind"], first["site_id"]) == ("delivery", str(S1))


async def test_a_photo_comes_with_its_link():
    _Feed.rows = [_row("ph", type_="image", media_object_key="m/1.jpg")]
    admin = _admin()
    res = await dpr_router.list_live_feed(SINCE, UNTIL, auth_context=admin, conn=None, object_storage=_Storage())
    assert res["items"][0]["media_url"] == "https://media.example/m/1.jpg"


async def test_one_day_at_a_time():
    admin = _admin()
    with pytest.raises(HTTPException) as exc:
        await dpr_router.list_live_feed(SINCE, SINCE + datetime.timedelta(days=3), auth_context=admin, conn=None, object_storage=_Storage())
    assert exc.value.status_code == 422
