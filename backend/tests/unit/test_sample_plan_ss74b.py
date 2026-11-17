"""SS-74b: the planned simulation (application/learn/sample_plan.py, guided-demo-plan.md section 18.2).

The plan is data the player (SS-74c) plays day by day as each role's sandbox user. These tests hold it true without a
database: it is the same every time, every entry is a real route for the right role, nothing happens on a Sunday,
stock never goes below zero, everything asked for is ordered, delivered, billed and paid, wages are approved and paid
every week, Green Villa is handed over, and the readable copy in docs is up to date. Playing it against a real
database is SS-74c's test.
"""

from __future__ import annotations

import importlib
from collections import defaultdict

import pytest

from mesiri.application.learn import sample_plan as sp
from mesiri.application.organizations import sample_story as story
from mesiri.domains.progress.validation import ISSUE_SEVERITIES, ISSUE_TYPES


@pytest.fixture(scope="module")
def plan() -> sp.Plan:
    return sp.build()


def test_the_plan_is_the_same_every_time(plan):
    again = sp.build()
    assert [(e.id, e.kind, e.what, e.data, e.needs) for e in again.entries] == \
        [(e.id, e.kind, e.what, e.data, e.needs) for e in plan.entries]


def test_it_starts_from_what_the_seed_leaves(plan):
    # The seeded story's point: Main block is nearly out of cement on day 0 (below its minimum of 100 bags).
    assert plan.opening[("main", "cement")] < 10
    # Every site has stock; the seed's open orders still have some to come.
    assert {site for site, _m in plan.opening} == {key for key, _p, _n in sp.SITES}
    assert plan.seeded_on_order and all(q > 0 for q in plan.seeded_on_order.values())


def test_ids_are_unique_and_needs_point_back_in_time(plan):
    ids = [e.id for e in plan.entries]
    assert len(ids) == len(set(ids))
    seen: set[str] = set()
    for e in plan.entries:
        for need in e.needs:
            assert need in seen, f"{e.id} needs {need}, which is not an earlier entry"
        seen.add(e.id)


def test_each_entry_is_made_by_its_role_and_names_its_place(plan):
    for e in plan.entries:
        assert e.kind in sp.KINDS
        assert e.role in sp.WHO
        assert e.project in (sp.GREEN_VILLA, sp.LAKE_VIEW, None)
        if e.site:
            assert e.project == sp.SITE_PROJECT[e.site]
        assert e.what and e.what[0].isupper(), e.id


def test_nobody_works_on_sunday_and_every_scripted_day_is_a_working_day(plan):
    assert not [e.id for e in plan.entries if sp.is_sunday(e.day)]
    scripted = [d for d, *_ in sp.ISSUES] + [c for *_, c, _n in sp.ISSUES] + [d for d, *_ in sp.ADVANCES]
    scripted += list(sp.RAIN) + list(sp.RA_BILL_DAYS)
    assert not [d for d in scripted if sp.is_sunday(d)]
    assert sp.weekday(0) == 5  # day 0 is a Saturday: the seeded weeks end on a pay day


def test_stock_never_goes_below_zero(plan):
    stock = defaultdict(float, plan.opening)
    for e in plan.entries:
        if e.kind == "delivery":
            stock[(e.site, e.data["material"])] += e.data["quantity"]
        elif e.kind == "use":
            stock[(e.site, e.data["material"])] -= e.data["quantity"]
            assert stock[(e.site, e.data["material"])] >= -1e-6, f"{e.id}: {e.data['material']} below zero"


def test_asked_for_is_ordered_delivered_billed_and_paid(plan):
    by_id = plan.by_id()
    requests = [e for e in plan.entries if e.kind == "request"]
    orders = [e for e in plan.entries if e.kind == "order"]
    deliveries = [e for e in plan.entries if e.kind == "delivery"]
    bills = [e for e in plan.entries if e.kind == "supplier_bill"]
    paid = {b for e in plan.entries if e.kind == "supplier_payment" for b in e.data["bills"]}
    last = plan.last_day
    lead = max(sp.LEAD_DAYS.values()) + 2
    # Every request is ordered (the last days' may still be waiting), with the same material and quantity.
    ordered = {e.needs[0] for e in orders}
    for r in requests:
        if r.day < last - 2:
            assert r.id in ordered, f"{r.id} never ordered"
    for o in orders:
        req = by_id[o.needs[0]]
        assert (req.data["material"], req.data["quantity"]) == (o.data["material"], o.data["quantity"])
    # Every order arrives in full; deliveries match their order.
    delivered = defaultdict(float)
    for d in deliveries:
        if d.needs:
            delivered[d.needs[0]] += d.data["quantity"]
            assert by_id[d.needs[0]].data["material"] == d.data["material"]
    for o in orders:
        if o.day < last - lead:
            assert delivered[o.id] == o.data["quantity"], f"{o.id} not delivered in full"
    # The seed's own orders: what comes against them is no more than what was still to come.
    from_seed = defaultdict(float)
    for d in deliveries:
        if not d.needs:
            from_seed[(d.site, d.data["material"])] += d.data["quantity"]
    for key, qty in from_seed.items():
        assert qty <= plan.seeded_on_order.get(key, 0) + 1e-6
    # Every delivery is billed, for what came at the agreed rate; every bill a week old is paid.
    billed = {b.needs[0]: b for b in bills}
    for d in deliveries:
        if d.day < last - sp.BILL_AFTER - 1:
            assert d.id in billed, f"{d.id} never billed"
            assert billed[d.id].data["amount"] == round(d.data["quantity"] * d.data["rate"], 2)
    for b in bills:
        if b.day <= last - sp.CREDIT_DAYS - 7:
            assert b.id in paid, f"{b.id} never paid"
    for e in plan.entries:
        if e.kind == "supplier_payment":
            assert e.data["amount"] == round(sum(by_id[b].data["amount"] for b in e.data["bills"]), 2)
            assert {by_id[b].data["vendor"] for b in e.data["bills"]} == {e.data["vendor"]}


def test_wages_are_approved_and_paid_every_week(plan):
    by_id = plan.by_id()
    saturdays = [d for d in range(1, plan.last_day + 1) if sp.weekday(d) == 5]
    for project in (sp.GREEN_VILLA, sp.LAKE_VIEW):
        weeks = {(e.data["week_from_day"], e.data["week_to_day"]) for e in plan.entries
                 if e.kind == "wage_approve" and e.project == project}
        assert (-6, 0) in weeks  # the seeded weeks' last pay week
        for sat in saturdays:
            assert (sat - 6, sat) in weeks, f"{project}: week to day {sat} never approved"
    for pay in (e for e in plan.entries if e.kind == "wage_pay"):
        approve = by_id[pay.needs[0]]
        assert approve.kind == "wage_approve" and approve.data == pay.data and approve.project == pay.project


def test_green_villa_is_finished_and_handed_over(plan):
    handover = [e for e in plan.entries if e.kind == "stage"]
    assert len(handover) == 1 and handover[0].data == {"stage": "handover"} and handover[0].day == plan.last_day
    assert 50 <= plan.last_day <= 70  # about 60 days (plan section 18.2)
    for site in ("main", "annex"):
        done = {e.data["work"] for e in plan.entries if e.kind == "work" and e.site == site}
        assert {s.work for s in sp.STAGES[site]} <= done, f"{site} did not finish every stage"


def test_the_subcontract_runs_from_work_order_to_payment(plan):
    by_id = plan.by_id()
    wo = [e for e in plan.entries if e.kind == "work_order"]
    assert len(wo) == 1
    tiled = sum(e.data["quantity"] for e in plan.entries if e.kind == "work" and e.data.get("by"))
    measured = [e for e in plan.entries if e.kind == "measurement"]
    assert measured and all(m.needs == (wo[0].id,) for m in measured)
    assert abs(sum(m.data["quantity"] for m in measured) - tiled) < 1e-6
    assert sum(m.data["quantity"] for m in measured) <= wo[0].data["quantity"] + 1e-6
    bills = [e for e in plan.entries if e.kind == "sub_bill"]
    assert {by_id[b.needs[0]].id for b in bills} == {m.id for m in measured}
    paid = {e.needs[0] for e in plan.entries if e.kind == "sub_payment"}
    assert paid == {b.id for b in bills}


def test_issues_use_real_types_and_are_closed(plan):
    issues = [e for e in plan.entries if e.kind == "issue"]
    assert len(issues) == len(sp.ISSUES)
    for e in issues:
        assert e.data["issue_type"] in ISSUE_TYPES and e.data["severity"] in ISSUE_SEVERITIES
    closed = {e.needs[0] for e in plan.entries if e.kind == "issue_resolve"}
    assert closed == {e.id for e in issues}


def test_names_are_the_stories(plan):
    vendors = {v for v, _a in story.DEMO_VENDORS} | {v for v, _a, _n in story.DEMO_SUBCONTRACTORS}
    workers = {n for n, *_ in story.DEMO_WORKERS}
    for e in plan.entries:
        if e.kind in ("order", "delivery", "supplier_bill", "supplier_payment", "work_order", "sub_bill"):
            assert e.data["vendor"] in vendors, e.id
        if e.kind == "advance":
            assert e.data["worker"] in workers
        if e.kind in ("use", "request", "delivery", "order"):
            assert e.data["material"] in story.DEMO_SUPPLY
        if e.kind == "attendance":
            assert {w["name"] for w in e.data["workers"]} <= workers
    # BOQ counting only on lines Lake View's estimate has (the seed makes one per site and work).
    lines = {(sp.SITES[at][0], work) for at in (2, 3) for work, *_ in story.DEMO_WORK[at]}
    for e in plan.entries:
        if e.kind == "boq_count":
            assert (e.site, e.data["work"]) in lines


def test_every_kind_has_a_real_route():
    # Each router is mounted as it is (runtime/lifecycle.py), so its routes' paths (prefix included) are the app's.
    routes = [route for module in sp.ROUTER_MODULES for route in importlib.import_module(module).router.routes]
    have = {(method, route.path) for route in routes for method in getattr(route, "methods", ()) or ()}
    missing = [(kind, m, p) for kind, k in sp.KINDS.items() for m, p in k.routes if (m, p) not in have]
    assert not missing, missing


def test_the_readable_plan_in_docs_is_up_to_date(plan):
    assert sp.DOC.read_text(encoding="utf-8") == sp.render(plan), (
        "docs/plans/sample-plan.md is out of date: run `python -m mesiri.application.learn.sample_plan` from backend/")
