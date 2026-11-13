"""WEB-83: the owner's board on Live (GET /dpr/live/board, ``domains/dpr/board.py``).

The board computes nothing: it calls each module's own route function and says a sentence from what came back.
So the tests hold three things: each sentence says only what the read returned (and nothing when there is nothing),
a read the person may not see is left out and never said as "nothing", and a switched-off module is not read."""

from __future__ import annotations

import contextlib
import datetime

import pytest
from fastapi import HTTPException

from mesiri.authorization.roles import may_view_expenses
from mesiri.domains.dpr import board, live_feed

TODAY = datetime.date(2026, 11, 12)

COSTS = {"total": "184200.00", "labour": {"amount": "62400.00"}, "materials": {"amount": "101800.00"},
         "expenses": {"amount": "20000.00"}, "machines": {"amount": "0.00"}}
DAYS = {"items": [
    {"site_id": "s1", "site_name": "Tower A", "work_items": 3, "progress_updates": 1, "workers": 14, "photos": 9,
     "materials": 2, "issues_today": 1, "open_issues": 2, "last_update_at": "2026-11-12T09:00:00"},
    {"site_id": "s2", "site_name": "Main block", "work_items": 0, "progress_updates": 0, "workers": 0, "photos": 0,
     "materials": 0, "issues_today": 0, "open_issues": 0, "last_update_at": None},
], "projects": [{"sent": True}, {"sent": False}]}
STOCK = [
    {"material_name": "Cement", "unit": "bag", "closing": "-6", "days_left": None},
    {"material_name": "Sand", "unit": "cft", "closing": "40", "days_left": 2},
    {"material_name": "Steel", "unit": "kg", "closing": "900", "days_left": 30},
]
BELOW = {"items": [{"material": "Cement", "site_name": "Main block", "closing": "12", "unit": "bag", "min_qty": "50"}],
         "total": 1, "not_covered": 1}


# --- the sentences -----------------------------------------------------------------------------------------------------

def test_costs_says_the_total_and_its_parts_biggest_first():
    assert board.say_costs(COSTS) == ("₹1.8 L spent in the last 7 days: materials ₹1.0 L, labour ₹62,400, "
                                      "expenses ₹20,000.")
    assert board.say_costs({"total": "0.00"}) is None


def test_budget_names_the_project_heading_over_else_the_one_that_spent_most():
    rows = [{"name": "Skyline", "percent_spent": "62.0", "forecast_difference": "5000.00"},
            {"name": "Lake View", "percent_spent": "40.0", "forecast_difference": "-120000.00"}]
    assert board.say_budget({"projects": rows}) == "Lake View is heading ₹1.2 L over its budget."
    assert board.say_budget({"projects": rows[:1]}) == "Skyline has spent 62% of its budget."
    # A project with no budget has no percent: nothing is said about it.
    assert board.say_budget({"projects": [{"name": "X", "percent_spent": None}]}) is None


def test_stock_beyond_the_books_and_days_left():
    assert board.say_beyond_stock(STOCK) == "6 bag of Cement used beyond the stock on the books."
    assert board.say_beyond_stock(STOCK[1:]) is None
    assert board.say_days_left(STOCK) == "Sand lasts 2 more days at this week's use."
    # Plenty left, or nothing left to last: not a thing that stops work tomorrow.
    assert board.say_days_left([STOCK[2]]) is None
    assert board.say_days_left([{"material_name": "Cement", "closing": "0", "days_left": 0}]) is None


def test_rates_schedule_and_below_minimum():
    assert board.say_rates({"summary": {"above_best": "500.00", "rising": 1}}) == (
        "₹500 paid above the best rate in the last 90 days; 1 item costs more than last time.")
    assert board.say_rates({"summary": {"above_best": "0.00", "rising": 0}}) is None
    late = [{"name": "Tower A", "scheduled": 12, "slip_days": 3, "progress": 68},
            {"name": "Villa", "scheduled": 4, "slip_days": 0, "progress": 10},
            {"name": "No dates", "scheduled": 0, "slip_days": 0, "progress": None}]
    assert board.say_schedule(late) == "Tower A: 68% done, 3 days behind the schedule."
    assert board.say_schedule(late[1:]) == "1 project on schedule."
    assert board.say_schedule(late[2:]) is None
    assert board.say_below(BELOW) == ("1 item below its minimum, 1 not ordered yet "
                                      "(Cement at Main block: 12 bag, minimum 50).")
    assert board.say_below({"items": []}) is None


def test_what_is_owed_each_way():
    assert board.say_wages({"due": "62400.00", "due_rows": 14, "drafts": 1, "advances_outstanding": "0"}) == (
        "Wages due ₹62,400 to 14 people; 1 wage sheet waiting to be approved.")
    assert board.say_wages({"due": "0", "due_rows": 0, "drafts": 0, "advances_outstanding": "0"}) is None
    assert board.say_suppliers({"totals": {"payable": "320000", "overdue": "40000", "unbilled": "0"}}) == (
        "Suppliers are owed ₹3.2 L, ₹40,000 of it overdue.")
    assert board.say_suppliers({"totals": {"payable": "0", "overdue": "0", "unbilled": "0"}}) is None
    assert board.say_clients({"outstanding": "320000"}) == "Clients owe you ₹3.2 L."
    assert board.say_clients({"outstanding": "0"}) is None


def test_the_day_from_the_site_days():
    assert board.say_work_today(DAYS) == "4 work updates from 1 site today, 14 workers on site."
    assert board.say_issues(DAYS) == "2 issues open on 1 site."
    assert board.say_reports(DAYS) == "Today's reports: 8 lines, 9 photos, from 1 of 2 sites. 1 report sent."
    quiet = {"items": [DAYS["items"][1]], "projects": []}
    assert board.say_work_today(quiet) is None
    assert board.say_issues(quiet) is None
    assert board.say_waiting({"total": 3, "items": []}) == "3 things waiting for your yes."
    assert board.say_waiting({"total": 0, "items": []}) is None


# --- the board: who sees what ------------------------------------------------------------------------------------------

class _Conn:
    def begin_nested(self):
        @contextlib.asynccontextmanager
        async def savepoint():
            yield
        return savepoint()


class _Auth:
    def __init__(self, role: str):
        self.role = role


#: The reads that carry the company's money: each module's route refuses them to roles that do not see spending.
MONEY_READS = ("costs", "budget", "rates", "wages", "suppliers", "clients", "to_bill")
DATA = {"costs": COSTS, "budget": {"projects": [{"name": "Skyline", "percent_spent": "62.0"}]},
        "rates": {"summary": {"above_best": "500.00", "rising": 0}}, "stock": STOCK, "below": BELOW, "days": DAYS,
        "schedule": [{"name": "Tower A", "scheduled": 12, "slip_days": 3, "progress": 68}],
        "wages": {"due": "62400.00", "due_rows": 14, "drafts": 0, "advances_outstanding": "0"},
        "suppliers": {"totals": {"payable": "320000", "overdue": "0", "unbilled": "0"}},
        "clients": {"outstanding": "320000"}, "waiting": {"total": 2, "items": []},
        "to_bill": {"amount": "48000.00", "projects": [{"project": "Green Villa", "lines": 1, "amount": "48000.00"}]}}


@pytest.fixture
def reads(monkeypatch):
    """Every read stands in for its route: money reads answer 403 to a role that does not see spending."""
    calls: list[str] = []

    def make(name):
        async def read(ctx):
            calls.append(name)
            if name in MONEY_READS and not may_view_expenses(ctx.auth.role):
                raise HTTPException(status_code=403, detail="shown to the roles that see spending")
            return DATA[name]
        return read

    monkeypatch.setattr(board, "READS", {name: make(name) for name in board.READS})
    return calls


async def _board(role: str, off: tuple[str, ...] = ()):
    out = await board.build(_Conn(), _Auth(role), request=None, today=TODAY, enabled=lambda m: m not in off)
    return {q["key"]: q for q in out["questions"]}


async def test_an_owner_gets_all_six_answers_in_the_plans_order(reads):
    out = await board.build(_Conn(), _Auth("OWNER"), request=None, today=TODAY, enabled=lambda m: True)
    assert [q["key"] for q in out["questions"]] == ["money", "leaks", "work", "owed", "stops", "proof"]
    by = {q["key"]: q for q in out["questions"]}
    assert all(q["lines"] and not q["hidden"] and not q["off"] and q["quiet"] is None for q in by.values())
    assert by["owed"]["lines"][0] == {"text": "Wages due ₹62,400 to 14 people.", "opens": "/labour/wages", "read": "wages"}
    # One read is made once, however many parts use it (the site days answer three questions).
    assert sorted(reads) == sorted(set(reads))


@pytest.mark.parametrize("read", MONEY_READS)
async def test_a_site_engineer_gets_no_money_sentence(reads, read):
    by = await _board("SITE_ENGINEER")
    assert not [line for q in by.values() for line in q["lines"] if line["read"] == read]


async def test_what_is_hidden_is_never_said_as_nothing(reads):
    by = await _board("SITE_ENGINEER")
    # Money and what is owed: every part is hidden. No "nothing spent", no "nothing owed".
    for key in ("money", "owed"):
        assert by[key]["lines"] == [] and by[key]["hidden"] is True and by[key]["quiet"] is None
    # The rest of the chain stays: stock, the schedule, issues, the report.
    assert [line["read"] for line in by["leaks"]["lines"]] == ["stock"]
    assert by["leaks"]["hidden"] is True
    assert by["stops"]["lines"] and by["work"]["lines"] and by["proof"]["lines"]
    assert by["proof"]["hidden"] is False


async def test_a_switched_off_module_is_named_and_not_read(reads):
    by = await _board("OWNER", off=("cost", "labour"))
    assert "budget" not in reads and "wages" not in reads
    assert by["money"]["off"] == ["cost"] and [line["read"] for line in by["money"]["lines"]] == ["costs"]
    assert by["owed"]["off"] == ["labour"]
    assert by["proof"]["off"] == []


async def test_quiet_only_when_everything_was_read_and_nothing_is_to_say(reads, monkeypatch):
    monkeypatch.setitem(DATA, "stock", [])
    monkeypatch.setitem(DATA, "rates", {"summary": {"above_best": "0.00", "rising": 0}})
    assert (await _board("OWNER"))["leaks"]["quiet"] == "Nothing to check right now."
    assert (await _board("SITE_ENGINEER"))["leaks"]["quiet"] is None  # rates were not seen


async def test_a_read_that_breaks_leaves_the_rest_of_the_board(reads, monkeypatch):
    async def broken(ctx):
        raise RuntimeError("boom")

    monkeypatch.setitem(board.READS, "stock", broken)
    by = await _board("OWNER")
    assert [line["read"] for line in by["leaks"]["lines"]] == ["rates"]
    assert by["stops"]["lines"] and by["stops"]["quiet"] is None
    assert by["proof"]["lines"]


def test_every_part_names_a_read_and_a_module_that_exist():
    from mesiri.domains.organizations import settings as org_settings

    for q in board.QUESTIONS:
        for part in q.parts:
            assert part.read in board.READS and part.module in org_settings.MODULES and part.opens.startswith("/")
    assert set(board.KIND_QUESTIONS) <= set(live_feed.KIND_LABELS)
    assert {k for keys in board.KIND_QUESTIONS.values() for k in keys} <= {q.key for q in board.QUESTIONS}


#: Each read and the route function it calls. The call must fit the route's own signature with nothing left to a
#: FastAPI default (a ``Query(...)`` default is not a value when the function is called directly).
ROUTES = {
    "costs": "mesiri.domains.finance.router.project_costs",
    "budget": "mesiri.domains.costing.router.portfolio",
    "rates": "mesiri.domains.procurement.rates_router.list_rates",
    "stock": "mesiri.domains.materials.router.stock_summary",
    "below": "mesiri.domains.materials.stock_levels_router.below",
    "days": "mesiri.domains.dpr.router.list_site_days",
    "schedule": "mesiri.domains.schedule.router.projects_lifecycle",
    "wages": "mesiri.domains.workforce.pay_router.pay_summary",
    "suppliers": "mesiri.domains.vendors.router.payables",
    "clients": "mesiri.domains.billing.router.receivables",
    "to_bill": "mesiri.domains.billing.router.work_to_bill",
    "waiting": "mesiri.domains.approvals.router.waiting",
}


@pytest.mark.parametrize("name", sorted(ROUTES))
async def test_each_read_calls_its_modules_route_with_every_argument(name, monkeypatch):
    import importlib
    import inspect

    module_path, func = ROUTES[name].rsplit(".", 1)
    module = importlib.import_module(module_path)
    signature = inspect.signature(getattr(module, func))
    seen: dict = {}

    async def route(**kwargs):
        signature.bind(**kwargs)  # an unknown argument fails here
        seen.update(kwargs)
        return "the route's answer"

    monkeypatch.setattr(module, func, route)
    ctx = board.Ctx(conn="conn", auth="auth", request="request", today=TODAY)
    assert await board.READS[name](ctx) == "the route's answer"
    assert set(seen) == set(signature.parameters)
    assert "conn" in seen.values() and "auth" in seen.values()


def test_every_read_has_its_route():
    assert set(ROUTES) == set(board.READS)


def test_the_ripples_question_numbers_are_the_boards_order():
    """A ripple card names its question by number (effects.py); Live lands it on the board's question at that place."""
    from mesiri.domains.dpr import effects

    numbers = (effects.MONEY_GOING, effects.LEAKING, effects.WORK_MOVING, effects.OWE, effects.STOPS_WORK, effects.PROOF)
    assert numbers == (1, 2, 3, 4, 5, 6)
    assert [q.key for q in board.QUESTIONS] == ["money", "leaks", "work", "owed", "stops", "proof"]


# --- WEB-89: the board's missing words ---------------------------------------------------------------------------------

def test_days_left_names_the_site_when_the_site_days_are_seen():
    rows = [{"material_name": "Sand", "unit": "cft", "closing": "40", "days_left": 2, "site_id": "s2"}]
    assert board.say_days_left(rows, DAYS) == "Sand at Main block lasts 2 more days at this week's use."
    # Not seen, or a site that is not in them: the sentence stays true without the name.
    assert board.say_days_left(rows, None) == "Sand lasts 2 more days at this week's use."
    assert board.say_days_left(rows, {"items": []}) == "Sand lasts 2 more days at this week's use."


def test_the_report_says_when_the_next_one_goes_out_by_itself():
    nine, six = datetime.time(21, 0), datetime.time(18, 30)
    projects = [{"sent": False, "auto_generate_dpr": True, "dpr_send_deadline": nine},
                {"sent": False, "auto_generate_dpr": True, "dpr_send_deadline": six},
                {"sent": True, "auto_generate_dpr": True, "dpr_send_deadline": datetime.time(17, 0)},   # gone already
                {"sent": False, "auto_generate_dpr": False, "dpr_send_deadline": datetime.time(16, 0)}]  # sent by hand
    said = board.say_reports({"items": DAYS["items"], "projects": projects})
    assert said == "Today's reports: 8 lines, 9 photos, from 1 of 2 sites. 1 report sent. The next goes out at 6:30 pm."
    assert "goes out" not in board.say_reports({"items": DAYS["items"], "projects": projects[2:]})


async def test_the_board_gives_the_site_name_to_the_stock_sentence(reads, monkeypatch):
    monkeypatch.setitem(DATA, "stock", [{"material_name": "Sand", "unit": "cft", "closing": "40", "days_left": 2, "site_id": "s1"}])
    by = await _board("OWNER")
    assert "Sand at Tower A lasts 2 more days at this week's use." in [line["text"] for line in by["stops"]["lines"]]


def test_what_can_be_billed_to_the_client_now():
    one = {"amount": "48000.00", "projects": [{"project": "Green Villa", "lines": 1, "amount": "48000.00"}]}
    assert board.say_to_bill(one) == "₹48,000 of measured work on Green Villa can be billed to the client now."
    two = {"amount": "320000", "projects": [{"project": "A"}, {"project": "B"}]}
    assert board.say_to_bill(two) == "₹3.2 L of measured work across 2 projects can be billed to the client now."
    assert board.say_to_bill({"amount": "0.00", "projects": []}) is None
