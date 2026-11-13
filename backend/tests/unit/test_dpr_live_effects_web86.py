"""WEB-86: the remaining ripples: work done, an issue, a bill or expense, a machine's day.

Same shape as WEB-82's: pure builders from facts. The guards that matter here:
- work reaches the client's bill only through a person's tap (plan decision 5): work on a line says what it earned;
  work not on a line says the line suggested and what it *would* earn, never "earned";
- a bill is the company's spending: no card at all for a role that does not see it, and the route answers 404;
- a "before" only when this entry is the newest of its kind at the site.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException

from mesiri.application.dpr import fact_review
from mesiri.authorization.context import (
    AccessPolicy,
    AuthorizationContext,
    ProjectAccessScope,
    SiteAccessScope,
)
from mesiri.domains.dpr import effects, live_feed
from mesiri.domains.dpr import router as dpr_router

ORG, P1, S1 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


def _keys(cards):
    return [c["key"] for c in cards]


def _one(cards, key):
    return next(c for c in cards if c["key"] == key)


def _work(**kw):
    return {"what": "Plastering", "site_name": "Main block", "project_name": "Green Villa", "boq_page": f"/projects/{P1}/boq",
            "report_time": "9:00 pm", "photos": 0, "today": {"updates": 3, "latest": True}, **kw}


# --- work done -----------------------------------------------------------------------------------------------------

def test_work_alone_is_the_days_work_and_the_report():
    cards = effects.work_cards(_work(), sees_money=True)
    assert _keys(cards) == ["work_today", "report"]
    today = _one(cards, "work_today")
    assert (today["before"], today["after"]) == ("2", "3") and today["sentence"] == "3 work updates from Main block today."


def test_guard_no_before_when_a_later_work_update_is_already_in():
    assert _one(effects.work_cards(_work(today={"updates": 3, "latest": False}), True), "work_today")["before"] is None


def test_the_floor_the_schedule_and_the_photo_each_only_when_there():
    cards = effects.work_cards(_work(
        place={"label": "Second floor", "done": ["Brickwork"], "left": ["Plastering", "Tiling"]},
        schedule={"progress": 68, "slip_days": 3}, photos=2), sees_money=False)
    assert _keys(cards) == ["work_today", "place", "schedule", "photos", "report"]
    assert _one(cards, "place")["sentence"] == "Second floor: 1 kind of work done, 2 left. Left: Plastering, Tiling."
    behind = _one(cards, "schedule")
    assert behind["sentence"] == "Green Villa is 68% done and 3 days behind the schedule." and behind["tag"] == "caught"
    on_time = _one(effects.work_cards(_work(schedule={"progress": 20, "slip_days": 0}), False), "schedule")
    assert on_time["sentence"].endswith("on schedule.") and on_time["tag"] == "time"
    assert _one(cards, "photos")["sentence"] == "2 photos are kept with this line of the report."
    # A project with no dated schedule says nothing about it.
    assert "schedule" not in _keys(effects.work_cards(_work(schedule={"progress": None, "slip_days": 0}), False))


def test_work_counted_on_its_line_says_what_it_earned():
    q = {"quantity": Decimal(120), "unit": "sqm", "line": {"name": "Plastering, 2nd floor", "rate": Decimal(400)}, "suggested": None}
    line = _one(effects.work_cards(_work(quantities=[q]), True), "line")
    assert line["sentence"] == ("120 sqm is counted on “Plastering, 2nd floor”: ₹48,000 earned at ₹400 per sqm, "
                                "to bill the client.")
    assert line["after"] == "48000" and line["rupees"] and line["opens"] == f"/projects/{P1}/boq"


def test_guard_work_not_on_a_line_is_offered_never_said_as_earned():
    q = {"quantity": Decimal(120), "unit": "sqm", "line": None, "suggested": {"name": "Plastering, 2nd floor", "rate": Decimal(400)}}
    cards = effects.work_cards(_work(quantities=[q]), True)
    assert "line" not in _keys(cards)
    offer = _one(cards, "line_offer")
    assert offer["sentence"] == ("120 sqm is not on an estimate line yet. Suggested: “Plastering, 2nd floor”. "
                                 "Once counted: ₹48,000 to bill the client.")
    assert offer["after"] is None and "earned" not in offer["sentence"]
    assert offer["action"] is None  # no ids known: nothing to tap
    # No line fits: nothing is suggested, and nothing is said.
    none = effects.work_cards(_work(quantities=[{"quantity": Decimal(5), "unit": "nos", "line": None, "suggested": None}]), True)
    assert "line" not in _keys(none) and "line_offer" not in _keys(none)


def test_guard_the_estimate_line_is_money_and_not_for_a_site_role():
    q = {"quantity": Decimal(120), "unit": "sqm", "line": {"name": "Plastering", "rate": Decimal(400)}, "suggested": None}
    cards = effects.work_cards(_work(quantities=[q]), sees_money=False)
    assert _keys(cards) == ["work_today", "report"] and "₹" not in " ".join(c["sentence"] for c in cards)


# --- an issue ------------------------------------------------------------------------------------------------------

def _issue(**kw):
    return {"what": "Water leaking in the basement", "site_name": "Main block", "is_open": True, "latest": True,
            "open": 3, "oldest_days": 4, "report_time": None, "photos": 1, **kw}


def test_an_issue_is_counted_open_with_how_long_the_oldest_waited():
    cards = effects.issue_cards(_issue(), sees_money=False)
    assert _keys(cards) == ["issue_open", "photos", "report"]
    card = _one(cards, "issue_open")
    assert card["sentence"] == "3 issues open at Main block. The oldest has waited 4 days."
    assert (card["before"], card["after"], card["tag"]) == ("2", "3", "caught")


def test_an_issues_task_shows_only_when_one_was_raised():
    task = {"title": "Fix the basement leak", "due": datetime.date(2026, 11, 14), "assignee": "Suresh"}
    card = _one(effects.issue_cards(_issue(task=task), False), "issue_task")
    assert card["sentence"] == "A task is raised for Suresh, due 14 Nov: “Fix the basement leak”."
    assert "issue_task" not in _keys(effects.issue_cards(_issue(), False))


def test_guard_no_before_for_an_issue_already_closed_or_not_the_newest():
    for change in ({"is_open": False}, {"latest": False}):
        assert _one(effects.issue_cards(_issue(**change), False), "issue_open")["before"] is None


# --- a bill or an expense ------------------------------------------------------------------------------------------

def _bill(**kw):
    return {"what": "₹19,500 · ABC Traders", "amount": Decimal(19500), "tax": Decimal(2975), "vendor": "ABC Traders",
            "category": "Cement", "from_photo": True, "where": "Main block",
            "week": {"total": Decimal(184200), "materials": Decimal(101800), "labour": Decimal(62400)},
            "supplier": {"name": "ABC Traders", "balance": Decimal(58500), "unbilled_here": False}, **kw}


def test_a_bill_photo_read_checked_and_owed():
    deliveries = [{"material": "Cement", "flags": ["rate ₹400 on the bill, ₹390 on site"]},
                  {"material": "Sand", "flags": []}]
    cards = effects.expense_cards(_bill(deliveries=deliveries), sees_money=True)
    assert _keys(cards) == ["bill_read", "bill_match", "supplier", "week_cost"]
    assert _one(cards, "bill_read")["sentence"] == "Read from the photo: ₹19,500 to ABC Traders (GST ₹2,975, Cement)."
    match = _one(cards, "bill_match")
    assert match["tag"] == "caught" and match["sentence"] == (
        "Checked against 2 deliveries. Cement: rate ₹400 on the bill, ₹390 on site.")
    assert _one(cards, "supplier")["sentence"] == "You now owe ABC Traders ₹58,500."


def test_a_bill_that_matches_says_so_and_an_expense_typed_is_not_read_from_a_photo():
    same = _one(effects.expense_cards(_bill(deliveries=[{"material": "Cement", "flags": []}]), True), "bill_match")
    assert same["tag"] == "proof" and same["sentence"] == "It matches the 1 delivery it bills: same quantity, same rate."
    typed = effects.expense_cards(_bill(from_photo=False, tax=None, category="Uncategorized", supplier=None), True)
    assert _keys(typed) == ["expense_read", "week_cost"]
    read = _one(typed, "expense_read")
    assert read["sentence"] == "Recorded: ₹19,500 to ABC Traders." and "photo" not in read["say"]


def test_guard_a_supplier_owed_nothing_is_not_said_as_owed():
    paid = effects.expense_cards(_bill(supplier={"name": "Tea stall", "balance": Decimal(0), "unbilled_here": False}), True)
    assert "supplier" not in _keys(paid)


def test_guard_a_bill_has_no_card_for_a_role_that_does_not_see_spending():
    assert effects.expense_cards(_bill(), sees_money=False) == []
    assert effects.cards(effects.EXPENSE, _bill(), False)["count"] == 0


# --- a machine's day -----------------------------------------------------------------------------------------------

def _machine(**kw):
    return {"what": "JCB", "machine": "JCB", "site_name": "Main block", "worked": Decimal(6), "idle": Decimal(0),
            "breakdown": Decimal(0), "breakdown_reason": None, "fuel": Decimal(30), **kw}


def test_a_machines_day_its_breakdown_and_its_hire():
    cards = effects.machine_cards(_machine(breakdown=Decimal(2), breakdown_reason="hydraulic hose",
                                           hire={"expected": Decimal(7200), "days": 1, "vendor": "Kochi Earthmovers"}), True)
    assert _keys(cards) == ["machine_day", "machine_down", "machine_hire"]
    assert _one(cards, "machine_day")["sentence"] == "JCB at Main block: 6 h worked, 30 L diesel."
    assert _one(cards, "machine_down")["sentence"] == "2 h lost to breakdown: hydraulic hose."
    assert _one(cards, "machine_hire")["sentence"] == (
        "JCB's hire comes to ₹7,200 so far this month, over 1 day on site (Kochi Earthmovers).")


def test_guard_an_owned_machine_has_no_hire_and_a_site_role_sees_no_rupee():
    assert _keys(effects.machine_cards(_machine(), True)) == ["machine_day"]
    hired = _machine(hire={"expected": Decimal(7200), "days": 1, "vendor": None})
    plain = effects.machine_cards(hired, sees_money=False)
    assert _keys(plain) == ["machine_day"] and "₹" not in plain[0]["sentence"]


# --- the table, the feed and the route ------------------------------------------------------------------------------

def test_every_kind_has_its_rule_its_read_and_a_line_to_say():
    assert set(effects.RULES) == set(effects.READS)
    assert set(live_feed.RECORD_KINDS.values()) == set(effects.RULES)
    assert set(effects.RECORD_TABLES) == set(effects.RULES) - fact_review.FACT_TYPES
    assert effects.MONEY_KINDS <= set(effects.RULES)
    facts = {fact_review.ACTIVITY: _work(place={"label": "F", "done": [], "left": []}, schedule={"progress": 1, "slip_days": 0},
                                         photos=1, quantities=[{"quantity": 1, "unit": "sqm", "line": {"name": "L", "rate": 1},
                                                                "suggested": None}]),
             fact_review.SITE_ISSUE: _issue(task={"title": "T", "due": None, "assignee": None}),
             effects.EXPENSE: _bill(deliveries=[{"material": "C", "flags": []}]),
             effects.MACHINE_LOG: _machine(breakdown=1, hire={"expected": 1, "days": 1, "vendor": None})}
    for kind, f in facts.items():
        for card in effects.cards(kind, f, True)["cards"]:
            assert card["say"] and 1 <= card["question"] <= 6 and card["opens"].startswith("/"), card


def _row(turns):
    return {"id": "m1", "type": "text", "text": "x", "turns": turns}


@pytest.mark.parametrize(("tool", "kind", "record"), [
    ("record_work", "work", "activity"), ("report_issue", "issue", "site_issue"),
    ("record_expense", "expense", "expense"), ("log_machines", "machine", "machine_log"),
])
def test_the_feed_carries_the_saved_record_of_each_new_kind(tool, kind, record):
    rid = str(uuid.uuid4())
    out = live_feed.classify(_row([{"tools": [tool], "saved": [{"tool": tool, "status": 201, "id": rid, "summary": "s"}]}]))
    assert out["kind"] == kind and out["records"] == [{"kind": record, "id": rid}]
    assert out["label"] == live_feed.KIND_LABELS[kind]


def test_two_machines_on_one_message_are_two_records_and_a_refused_save_is_none():
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    saved = {"tools": ["log_machines"], "saved": [{"tool": "log_machines", "status": 201, "ids": [a, b]}]}
    assert live_feed.classify(_row([saved]))["records"] == [{"kind": "machine_log", "id": a}, {"kind": "machine_log", "id": b}]
    refused = {"tools": ["log_machines"], "saved": [{"tool": "log_machines", "status": 409, "ids": [a]}]}
    assert live_feed.classify(_row([refused]))["records"] == []


def _ctx(role, projects):
    scope = ProjectAccessScope(mode="custom_projects", project_ids=set(projects))
    return AuthorizationContext(user_id=uuid.uuid4(), organization_id=ORG, role=role, status="active",
                                access_policy=AccessPolicy(mode=scope.mode, projects=[]), project_scope=scope,
                                site_scopes={p: SiteAccessScope(mode="all_sites", site_ids=set()) for p in projects})


@pytest.fixture
def route(monkeypatch):
    seen: dict = {"located": {"project_id": P1, "site_id": S1}}

    async def locate(conn, org, kind, record_id):
        return seen["located"]

    def make(kind, facts):
        async def read(conn, org, record_id, today, sees_money, **kw):
            seen.update(read=kind, sees_money=sees_money, auth=kw.get("auth"))
            return facts
        return read

    async def today(conn, org):
        return datetime.date(2026, 11, 12)

    monkeypatch.setattr(effects, "locate", locate)
    monkeypatch.setitem(effects.READS, effects.EXPENSE, make(effects.EXPENSE, _bill()))
    monkeypatch.setitem(effects.READS, effects.MACHINE_LOG,
                        make(effects.MACHINE_LOG, _machine(hire={"expected": Decimal(7200), "days": 1, "vendor": None})))
    monkeypatch.setattr("mesiri.application.dpr.project_day.company_today", today)
    return seen


async def test_the_route_gives_a_bill_to_the_roles_that_see_spending_with_who_is_asking(route):
    owner = _ctx("ADMIN", [P1])
    out = await dpr_router.get_effects(effects.EXPENSE, uuid.uuid4(), auth_context=owner, conn=None)
    assert _keys(out["cards"]) == ["bill_read", "supplier", "week_cost"]
    assert route["auth"] is owner  # the bill's deliveries are read by the supplier page's own rule, as this person


async def test_guard_a_bill_is_not_there_for_a_site_engineer_and_nothing_is_read(route):
    with pytest.raises(HTTPException) as hidden:
        await dpr_router.get_effects(effects.EXPENSE, uuid.uuid4(), auth_context=_ctx("SITE_ENGINEER", [P1]), conn=None)
    assert hidden.value.status_code == 404 and "read" not in route


async def test_a_machine_log_goes_to_a_site_engineer_without_its_hire(route):
    out = await dpr_router.get_effects(effects.MACHINE_LOG, uuid.uuid4(), auth_context=_ctx("SITE_ENGINEER", [P1]), conn=None)
    assert _keys(out["cards"]) == ["machine_day"] and route["sees_money"] is False


async def test_guard_another_projects_record_and_an_unknown_one_are_not_found(route):
    with pytest.raises(HTTPException) as other:
        await dpr_router.get_effects(effects.MACHINE_LOG, uuid.uuid4(), auth_context=_ctx("ADMIN", [uuid.uuid4()]), conn=None)
    assert other.value.status_code == 404 and "read" not in route
    route["located"] = None
    with pytest.raises(HTTPException) as missing:
        await dpr_router.get_effects(effects.EXPENSE, uuid.uuid4(), auth_context=_ctx("ADMIN", [P1]), conn=None)
    assert missing.value.status_code == 404 and "read" not in route


# --- WEB-88: the person's tap is offered on the card --------------------------------------------------------------

def test_the_estimate_line_offered_carries_the_tap_that_counts_it():
    qid, lid = uuid.uuid4(), uuid.uuid4()
    q = {"id": qid, "quantity": Decimal(120), "unit": "sqm", "line": None,
         "suggested": {"id": lid, "name": "Plastering, 2nd floor", "rate": Decimal(400)}}
    offer = _one(effects.work_cards(_work(project_id=P1, quantities=[q]), True), "line_offer")
    assert offer["action"] == {"kind": "count_work", "label": "Count it on this line", "project_id": str(P1),
                               "quantity_id": str(qid), "line_id": str(lid)}


def test_guard_only_an_offer_has_a_tap_and_never_for_a_site_role():
    qid, lid = uuid.uuid4(), uuid.uuid4()
    counted = {"id": qid, "quantity": Decimal(120), "unit": "sqm", "line": {"id": lid, "name": "Plastering", "rate": Decimal(400)},
               "suggested": None}
    cards = effects.work_cards(_work(project_id=P1, quantities=[counted], photos=1,
                                     place={"label": "F", "done": [], "left": []}), True)
    assert [c["key"] for c in cards if c["action"]] == []  # work already counted, and every other card: no tap
    offered = {**counted, "line": None, "suggested": {"id": lid, "name": "Plastering", "rate": Decimal(400)}}
    plain = effects.work_cards(_work(project_id=P1, quantities=[offered]), sees_money=False)
    assert all(c["action"] is None for c in plain) and "line_offer" not in _keys(plain)


# --- WEB-93: a bill for more than its deliveries come to is not said to match --------------------------------------

def test_guard_a_bill_over_the_value_of_its_deliveries_is_caught_even_with_no_line_difference():
    deliveries = [{"material": "Solid Blocks", "flags": [], "amount": "63000.00"}]
    match = _one(effects.expense_cards(_bill(amount=Decimal(65400), deliveries=deliveries), True), "bill_match")
    assert match["tag"] == "caught" and match["sentence"] == (
        "The bill is ₹2,400 more than the 1 delivery it is for (₹63,000 delivered).")
    assert (match["before"], match["after"]) == ("63000", "65400")
    # The same bill for exactly what was delivered still matches; a delivery with no rate cannot be compared.
    same = _one(effects.expense_cards(_bill(amount=Decimal(63000), deliveries=deliveries), True), "bill_match")
    assert same["tag"] == "proof"
    unpriced = _one(effects.expense_cards(_bill(amount=Decimal(65400), deliveries=[{"material": "Sand", "flags": [], "amount": None}]), True), "bill_match")
    assert unpriced["tag"] == "proof" and "more than" not in unpriced["sentence"]
