"""WEB-82: what one saved entry changed (GET /dpr/effects/{kind}/{id}), Live's ripple.

The cards are built by pure functions from facts (``effects.RULES``): the entry, its siblings, and the guards:
a card appears only when it is true for the entry, a "before" only when it is known, and money only for the roles
that see the company's spending (SEC-01). The route applies the site rule of the sources panel.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException

from mesiri.application.dpr.fact_review import FactReviewError
from mesiri.authorization.context import (
    AccessPolicy,
    AuthorizationContext,
    ProjectAccessScope,
    SiteAccessScope,
)
from mesiri.domains.dpr import effects, live_feed
from mesiri.domains.dpr import router as dpr_router

ORG, P1, S1 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


def _receipt(**kw):
    return {
        "what": "Cement · 50 bags", "material": "Cement", "unit": "bags", "quantity": Decimal(50), "site_name": "Main block",
        "stock": {"closing": Decimal(126), "days_left": 9, "on_order": 0, "min_qty": None, "running_low": False,
                  "last_rate": Decimal(390), "to_order": None, "latest": True},
        "report_time": "9:00 pm", **kw,
    }


def _keys(cards):
    return [c["key"] for c in cards]


def _one(cards, key):
    return next(c for c in cards if c["key"] == key)


# --- material came --------------------------------------------------------------------------------

def test_a_delivery_alone_moves_the_stock_and_is_on_the_report():
    cards = effects.receipt_cards(_receipt(), sees_money=True)
    assert _keys(cards) == ["stock", "report"]
    stock = _one(cards, "stock")
    assert (stock["before"], stock["after"], stock["unit"]) == ("76", "126", "bags")
    assert stock["sentence"] == "Main block now holds 126 bags of Cement. At the last week's use that lasts 9 days."
    assert _one(cards, "report")["sentence"] == "It is already in today's report for Main block, which goes out at 9:00 pm."
    assert all(c["say"] for c in cards)


def test_guard_no_before_when_a_later_entry_already_moved_the_stock():
    f = _receipt()
    f["stock"]["latest"] = False
    stock = _one(effects.receipt_cards(f, sees_money=True), "stock")
    assert stock["before"] is None and stock["after"] == "126"


def test_the_order_says_what_is_still_to_come_and_when_it_is_complete():
    f = _receipt(order={"ref": "PO-0012", "ordered": Decimal(100), "received": Decimal(50), "pending": Decimal(50)})
    order = _one(effects.receipt_cards(f, sees_money=False), "order")
    assert order["title"] == "Order PO-0012" and (order["before"], order["after"]) == ("0", "50")
    assert order["sentence"] == "50 of 100 bags delivered. 50 bags still to come."
    f["order"].update(received=Decimal(100), pending=Decimal(0))
    assert "The order is complete." in _one(effects.receipt_cards(f, sees_money=False), "order")["sentence"]


def test_a_rate_over_the_order_is_caught_with_what_it_cost():
    f = _receipt(rate={"rate": Decimal(390), "entered": Decimal(390), "ordered_rate": Decimal(380),
                       "differs_from_order": True, "previous": None}, amount=Decimal(19500))
    rate = _one(effects.receipt_cards(f, sees_money=True), "rate")
    assert rate["tag"] == "caught" and rate["question"] == effects.LEAKING
    assert rate["sentence"] == "₹390 per bag. The order said ₹380: ₹10 more per bag, ₹500 on this delivery."
    assert (rate["before"], rate["after"], rate["rupees"]) == ("380", "390", True)


def test_a_rate_against_last_time_dearer_cheaper_the_same_and_the_first():
    last = {"rate": Decimal(380), "vendor": "ABC Traders", "date": datetime.date(2026, 11, 3)}

    def card(now, previous=last):
        f = _receipt(rate={"rate": Decimal(now), "entered": Decimal(now), "ordered_rate": None,
                           "differs_from_order": False, "previous": previous})
        return _one(effects.receipt_cards(f, sees_money=True), "rate")

    dearer = card(390)
    assert dearer["tag"] == "caught" and "Last time (ABC Traders, 3 Nov) it was ₹380: ₹500 more on this delivery." in dearer["sentence"]
    cheaper = card(360)
    assert cheaper["tag"] == "money" and "₹1,000 saved on this delivery." in cheaper["sentence"]
    # Guard: within 2% is the same rate, never "caught".
    same = card(385)
    assert same["tag"] == "money" and same["sentence"].endswith("The same rate as last time.")
    first = card(390, previous=None)
    assert first["before"] is None and "The first rate recorded for Cement." in first["sentence"]


def test_the_supplier_and_the_weeks_cost():
    f = _receipt(amount=Decimal(19500), supplier={"name": "ABC Traders", "balance": Decimal(124500), "unbilled_here": True},
                 week={"total": "213000.00", "materials": "150000.00", "labour": "63000.00"})
    cards = effects.receipt_cards(f, sees_money=True)
    assert _keys(cards) == ["stock", "supplier", "week_cost", "report"]
    supplier = _one(cards, "supplier")
    assert (supplier["before"], supplier["after"]) == ("105000", "124500")
    assert supplier["sentence"] == "You now owe ABC Traders ₹1,24,500. ₹19,500 of it is this delivery, not billed yet."
    assert _one(cards, "week_cost")["sentence"] == (
        "Main block has cost ₹2,13,000 in the last 7 days: materials ₹1,50,000, labour ₹63,000.")
    # Guard: a delivery already on a bill is not counted twice in the before.
    f["supplier"]["unbilled_here"] = False
    billed = _one(effects.receipt_cards(f, sees_money=True), "supplier")
    assert billed["before"] is None and billed["sentence"] == "You now owe ABC Traders ₹1,24,500."


def test_guard_money_cards_are_only_for_the_roles_that_see_spending():
    f = _receipt(rate={"rate": Decimal(390), "entered": Decimal(390), "ordered_rate": None, "differs_from_order": False,
                       "previous": None}, amount=Decimal(19500),
                 supplier={"name": "ABC", "balance": Decimal(1), "unbilled_here": True},
                 week={"total": "1.00", "materials": "1.00", "labour": "0.00"},
                 order={"ref": "PO-0001", "ordered": Decimal(50), "received": Decimal(50), "pending": Decimal(0)})
    cards = effects.receipt_cards(f, sees_money=False)
    assert _keys(cards) == ["stock", "order", "report"]
    assert not any(c["rupees"] for c in cards) and "₹" not in " ".join(c["sentence"] for c in cards)


# --- material used --------------------------------------------------------------------------------

def _usage(**stock):
    return {
        "what": "Cement · 30 bags used", "material": "Cement", "unit": "bags", "quantity": Decimal(30), "site_name": "Main block",
        "stock": {"closing": Decimal(46), "days_left": 6, "on_order": 0, "min_qty": None, "running_low": False,
                  "last_rate": Decimal(390), "to_order": None, "latest": True, **stock},
        "report_time": None,
    }


def test_a_use_takes_stock_down_and_says_what_went_into_the_work():
    cards = effects.usage_cards(_usage(), sees_money=True)
    assert _keys(cards) == ["stock", "use_cost", "report"]
    assert (_one(cards, "stock")["before"], _one(cards, "stock")["after"]) == ("76", "46")
    assert "about ₹11,700 of Cement into the work" in _one(cards, "use_cost")["sentence"]
    assert _one(cards, "report")["sentence"] == "It is already in today's report for Main block."
    assert _keys(effects.usage_cards(_usage(), sees_money=False)) == ["stock", "report"]


def test_below_the_minimum_says_how_much_to_order_unless_it_is_already_coming():
    low = _one(effects.usage_cards(_usage(closing=Decimal(18), min_qty=Decimal(40), to_order=Decimal(62)), True), "low")
    assert low["tag"] == "caught" and low["sentence"] == "Cement is below the minimum of 40 bags. Order 62 bags."
    coming = _one(effects.usage_cards(_usage(closing=Decimal(18), min_qty=Decimal(40), to_order=Decimal(62),
                                             on_order=Decimal(100)), True), "low")
    assert coming["sentence"] == "Cement is below the minimum of 40 bags. 100 bags is on order."


def test_running_out_by_days_without_a_minimum_and_guard_nothing_when_fine():
    low = _one(effects.usage_cards(_usage(closing=Decimal(8), days_left=2, running_low=True), True), "low")
    assert low["sentence"] == "At this rate Cement runs out in 2 days."
    assert "low" not in _keys(effects.usage_cards(_usage(), True))


# --- attendance -----------------------------------------------------------------------------------

def _attendance(**wages):
    return {
        "what": "10 on site", "site_name": "Tower A", "headcount": Decimal(10),
        "trades": [("mason", Decimal(6)), ("helper", Decimal(4))], "report_time": "9:00 pm",
        "wages": {"today": Decimal(8400), "unpriced_man_days": Decimal(0), "week": Decimal(46200),
                  "week_from": datetime.date(2026, 11, 8), "week_to": datetime.date(2026, 11, 14), "counted": True,
                  "advances": Decimal(12000), **wages},
    }


def test_attendance_gives_who_is_there_the_wages_the_week_and_advances():
    cards = effects.attendance_cards(_attendance(), sees_money=True)
    assert _keys(cards) == ["on_site", "wages", "week_wages", "advances", "report"]
    assert _one(cards, "on_site")["sentence"] == "10 people at Tower A today: 6 mason, 4 helper."
    assert _one(cards, "wages")["sentence"] == "₹8,400 in wages today."
    week = _one(cards, "week_wages")
    assert (week["before"], week["after"]) == ("37800", "46200")
    assert week["sentence"] == "₹46,200 in wages so far this pay week (8 Nov to 14 Nov)."
    assert _one(cards, "advances")["sentence"] == "₹12,000 in advances is still to come off wages on this project."


def test_attendance_guards_no_wage_set_a_replaced_report_no_advances_and_no_money_role():
    gap = effects.attendance_cards(_attendance(today=Decimal(0), unpriced_man_days=Decimal(10), week=Decimal(0), advances=0), True)
    assert _keys(gap) == ["on_site", "wages", "report"]
    assert _one(gap, "wages")["sentence"] == "₹0 in wages today. 10 man-days have no wage set yet."
    # A report a later one replaced is not in the week's total: no before worked out from it.
    replaced = _one(effects.attendance_cards(_attendance(counted=False), True), "week_wages")
    assert replaced["before"] is None
    assert _keys(effects.attendance_cards(_attendance(), sees_money=False)) == ["on_site", "report"]


# --- the answer, and the numbers on it ------------------------------------------------------------

def test_the_answer_counts_its_cards_and_an_entry_taken_back_has_none():
    out = effects.cards("material_receipt", _receipt(), True)
    assert out["title"] == "Material came" and out["what"] == "Cement · 50 bags" and out["count"] == len(out["cards"]) == 2
    gone = effects.cards("material_usage", None, True)
    assert gone == {"kind": "material_usage", "title": "Material used", "what": None, "cards": [], "count": 0}


@pytest.mark.parametrize(("value", "words"), [(500, "₹500"), (19500, "₹19,500"), (124500, "₹1,24,500"),
                                               ("1245000.49", "₹12,45,000"), (0, "₹0"), (-2500, "-₹2,500")])
def test_rupees_are_grouped_the_indian_way(value, words):
    assert effects.rupees(value) == words


@pytest.mark.parametrize(("unit", "single"), [("bags", "bag"), ("loads", "load"), ("nos", "nos"), ("kg", "kg"),
                                                ("cft", "cft"), (None, "unit"), ("glass", "glass")])
def test_per_one_of_a_unit(unit, single):
    assert effects.one(unit) == single


@pytest.mark.parametrize(("stored", "said"), [
    ("21:00", "9:00 pm"), ("21:00:00", "9:00 pm"), ("09:05", "9:05 am"), ("00:30", "12:30 am"), ("12:00", "12:00 pm"),
    (datetime.time(18, 30), "6:30 pm"), (None, None), ("", None), ("soon", None), ("25:00", None),
])
def test_the_report_time_is_read_as_the_project_keeps_it(stored, said):
    # The project keeps the time as text ("21:00"): formatting it as a time object broke every ripple on a project
    # whose report goes out by itself (found 12 Nov on the demo's first project).
    assert effects.clock(stored) == said


def test_every_card_has_a_line_to_say_and_every_kind_a_read():
    assert set(effects.READS) == set(effects.RULES)
    # WEB-87: a question's ripple is keyed by the message itself, not by a saved record.
    assert set(live_feed.RECORD_KINDS.values()) | {effects.ANSWER} == set(effects.RULES)


# --- the feed names the records -------------------------------------------------------------------

def _row(turns):
    return {"id": "m", "type": "text", "turns": turns}


def test_the_feed_names_the_records_a_message_saved():
    rid = str(uuid.uuid4())
    turn = {"tools": ["record_receipt"], "saved": [{"summary": "Cement 50 bags in", "tool": "record_receipt", "status": 201, "id": rid}]}
    assert live_feed.classify(_row([turn]))["records"] == [{"kind": "material_receipt", "id": rid}]
    tap = {"tools": [], "save_results": [{"summary": "8 masons", "tool": "record_attendance", "status": 201, "id": rid}]}
    assert live_feed.classify(_row([tap]))["records"] == [{"kind": "labour_report", "id": rid}]


def test_guard_no_record_for_a_refused_save_an_old_trace_or_a_kind_without_a_ripple():
    rid = str(uuid.uuid4())
    refused = {"tools": ["record_usage"], "saved": [{"tool": "record_usage", "status": 422, "id": rid}]}
    old = {"tools": ["record_usage"], "saved": [{"summary": "Cement 30 bags used", "status": 201}]}
    # A transfer has no ripple (WEB-86 gave work done, issues, bills and machine logs theirs).
    other = {"tools": ["record_transfer"], "saved": [{"tool": "record_transfer", "status": 201, "id": rid}]}
    draft = {"tools": ["record_receipt"], "pending": ["Cement 50 bags in"]}
    for turn in (refused, old, other, draft):
        assert live_feed.classify(_row([turn]))["records"] == []


# --- the route: who may ask ------------------------------------------------------------------------

class _Repo:
    located: dict | None = {"project_id": P1, "site_id": S1, "fact_date": datetime.date(2026, 11, 12)}

    def __init__(self, conn):
        pass

    async def locate(self, org, kind, record_id):
        if _Repo.located is None:
            raise FactReviewError("that item was not found")
        return _Repo.located


def _ctx(role, projects):
    scope = ProjectAccessScope(mode="custom_projects", project_ids=set(projects))
    return AuthorizationContext(user_id=uuid.uuid4(), organization_id=ORG, role=role, status="active",
                                access_policy=AccessPolicy(mode=scope.mode, projects=[]), project_scope=scope,
                                site_scopes={p: SiteAccessScope(mode="all_sites", site_ids=set()) for p in projects})


@pytest.fixture
def _route(monkeypatch):
    seen: dict = {}

    async def read(conn, org, record_id, today, sees_money, **_):
        seen.update(org=org, sees_money=sees_money)
        return _receipt(amount=Decimal(19500), supplier={"name": "ABC", "balance": Decimal(19500), "unbilled_here": True})

    async def today(conn, org):
        return datetime.date(2026, 11, 12)

    monkeypatch.setattr(dpr_router, "PostgresFactReviewRepository", _Repo)
    monkeypatch.setitem(effects.READS, "material_receipt", read)
    monkeypatch.setattr("mesiri.application.dpr.project_day.company_today", today)
    _Repo.located = {"project_id": P1, "site_id": S1, "fact_date": datetime.date(2026, 11, 12)}
    return seen


async def test_the_route_gives_money_cards_to_the_owner_and_not_to_a_site_engineer(_route):
    rid = uuid.uuid4()
    owner = await dpr_router.get_effects("material_receipt", rid, auth_context=_ctx("ADMIN", [P1]), conn=None)
    assert _keys(owner["cards"]) == ["stock", "supplier", "report"] and _route["sees_money"] is True
    engineer = await dpr_router.get_effects("material_receipt", rid, auth_context=_ctx("SITE_ENGINEER", [P1]), conn=None)
    assert _keys(engineer["cards"]) == ["stock", "report"] and _route["sees_money"] is False


async def test_guard_the_route_refuses_another_project_an_unknown_record_and_an_unknown_kind(_route):
    rid = uuid.uuid4()
    with pytest.raises(HTTPException) as denied:
        await dpr_router.get_effects("material_receipt", rid, auth_context=_ctx("ADMIN", [uuid.uuid4()]), conn=None)
    assert denied.value.status_code == 404 and "org" not in _route  # nothing was read
    _Repo.located = None
    with pytest.raises(HTTPException) as missing:
        await dpr_router.get_effects("material_receipt", rid, auth_context=_ctx("ADMIN", [P1]), conn=None)
    assert missing.value.status_code == 404
    _Repo.located = {"project_id": P1, "site_id": S1, "fact_date": datetime.date(2026, 11, 12)}
    other_site = AuthorizationContext(
        user_id=uuid.uuid4(), organization_id=ORG, role="SITE_ENGINEER", status="active",
        access_policy=AccessPolicy(mode="custom_projects", projects=[]),
        project_scope=ProjectAccessScope(mode="custom_projects", project_ids={P1}),
        site_scopes={P1: SiteAccessScope(mode="custom_sites", site_ids={uuid.uuid4()})})
    with pytest.raises(HTTPException) as site:
        await dpr_router.get_effects("material_receipt", rid, auth_context=other_site, conn=None)
    assert site.value.status_code == 404 and "org" not in _route
    with pytest.raises(HTTPException) as unknown:
        await dpr_router.get_effects("material_transfer", rid, auth_context=_ctx("ADMIN", [P1]), conn=None)
    assert unknown.value.status_code == 404
