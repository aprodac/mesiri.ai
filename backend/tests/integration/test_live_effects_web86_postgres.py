"""WEB-86: the remaining ripples read from real records, against a real Postgres.

Work done on a floor, then counted on an estimate line by a person; an issue; an expense to a supplier; a hired
machine's day. Each figure must be the one its own module holds, and the money must stay with the roles that see it.
The estimate, the place, the machine and its log are made through their own routes; rolled back after the test."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text

from mesiri.application.organizations.create_company import NewCompany, create_company
from mesiri.authorization.context import AuthorizationContext, ProjectAccessScope, SiteAccessScope
from mesiri.domains.dpr import effects

from .test_live_questions_postgres import NOW, conn  # noqa: F401 -- the shared fixture

pytestmark = pytest.mark.integration
TODAY = NOW.date()


def _keys(out):
    return [c["key"] for c in out["cards"]]


def _one(out, key):
    return next(c for c in out["cards"] if c["key"] == key)


async def _company(conn):  # noqa: F811
    made = await create_company(
        conn, NewCompany(name="Ripple Two Builders", owner_name="Ravi Kumar", owner_phone="+919876500086",
                         project_name="Green Villa", site_names=("Main block",), auto_dpr=False), now=NOW)
    auth = AuthorizationContext(user_id=made.owner_user_id, organization_id=made.organization_id, role="ADMIN",
                                status="active", access_policy={},  # type: ignore[arg-type]
                                project_scope=ProjectAccessScope(mode="all_projects", project_ids=set()),
                                site_scopes={made.project_id: SiteAccessScope(mode="all_sites", site_ids=set())})
    return made, auth


async def test_work_done_on_a_floor_then_counted_on_its_estimate_line(conn) -> None:  # noqa: F811
    from mesiri.domains.places import store as places
    from mesiri.domains.progress import boq_router

    made, auth = await _company(conn)
    org, project, site = made.organization_id, made.project_id, made.sites[0].site_id
    section = await boq_router.create_section(project, boq_router.SectionCreate(name="Finishes"), auth=auth, conn=conn)
    line = await boq_router.create_line(project, section["id"], boq_router.LineCreate(
        work="Plastering", unit="sqm", planned_quantity=Decimal(900), client_rate=Decimal(400)), auth=auth, conn=conn)
    floor = await places.add(conn, org, project, name="Second floor", level_label="floor", parent_id=None,
                             user_id=made.owner_user_id)
    activity, quantity = uuid.uuid4(), uuid.uuid4()
    await conn.execute(text(
        "INSERT INTO activities (id, organization_id, project_id, site_id, activity_date, work_type, narrative, location_id, "
        "work_package_id) VALUES (:id, :org, :p, :s, :d, 'Plastering', 'Plastering second floor', :loc, :sec)"),
        {"id": activity, "org": org, "p": project, "s": site, "d": TODAY, "loc": floor["id"], "sec": section["id"]})
    await conn.execute(text(
        "INSERT INTO activity_quantities (id, activity_id, unit_id, quantity, work_type) "
        "SELECT :id, :a, u.id, 120, 'Plastering' FROM units_of_measure u WHERE u.code = 'sqm' LIMIT 1"),
        {"id": quantity, "a": activity})

    # Not on a line yet: Mesiri offers the line, and says what it would come to. Nothing is said as earned.
    before = effects.cards("activity", await effects.read_activity(conn, org, activity, TODAY, True), True)
    assert _keys(before) == ["work_today", "place", "line_offer", "report"], _keys(before)
    assert _one(before, "work_today")["after"] == "1" and _one(before, "work_today")["before"] == "0"
    assert _one(before, "place")["title"] == "Second floor"
    assert _one(before, "line_offer")["sentence"] == (
        "120 sqm is not on an estimate line yet. Suggested: “Plastering”. Once counted: ₹48,000 to bill the client.")

    # WEB-88: the card carries the tap: this work, on the line suggested.
    tap = _one(before, "line_offer")["action"]
    assert tap == {"kind": "count_work", "label": "Count it on this line", "project_id": str(project),
                   "quantity_id": str(quantity), "line_id": str(line["id"])}

    # A person taps it (the estimate page's own route, with the card's ids): now it is earned.
    await boq_router.put_work_on_line(uuid.UUID(tap["project_id"]), uuid.UUID(tap["quantity_id"]),
                                      boq_router.WorkLine(line_id=uuid.UUID(tap["line_id"])), auth=auth, conn=conn)
    after = effects.cards("activity", await effects.read_activity(conn, org, activity, TODAY, True), True)
    assert "line_offer" not in _keys(after)
    assert _one(after, "line")["after"] == "48000" and _one(after, "line")["action"] is None
    assert _one(after, "line")["opens"] == f"/projects/{project}/boq"

    # Guard: a role that does not see spending gets the same chain with no rupee and no estimate line.
    plain = effects.cards("activity", await effects.read_activity(conn, org, activity, TODAY, False), False)
    assert _keys(plain) == ["work_today", "place", "report"]
    assert "₹" not in " ".join(c["sentence"] for c in plain["cards"])
    # Guard: work that was deleted, and a record that is not there, have no ripple.
    await conn.execute(text("UPDATE activities SET deleted_at = now() WHERE id = :id"), {"id": activity})
    assert await effects.read_activity(conn, org, activity, TODAY, True) is None
    assert await effects.read_activity(conn, org, uuid.uuid4(), TODAY, True) is None


async def test_an_issue_an_expense_and_a_machines_day(conn) -> None:  # noqa: F811
    from mesiri.domains.equipment import router as equipment

    made, auth = await _company(conn)
    org, project, site = made.organization_id, made.project_id, made.sites[0].site_id

    # --- an issue: the Today page's open count, and how long the oldest has waited -----------------------
    old, new = uuid.uuid4(), uuid.uuid4()
    for issue, at in ((old, NOW - dt.timedelta(days=4)), (new, NOW)):
        await conn.execute(text(
            "INSERT INTO site_issues (id, organization_id, project_id, site_id, issue_type, narrative, occurred_at, created_at) "
            "VALUES (:id, :org, :p, :s, 'MATERIAL_SHORTAGE', 'Cement may run short', :at, :at)"),
            {"id": issue, "org": org, "p": project, "s": site, "at": at})
    out = effects.cards("site_issue", await effects.read_issue(conn, org, new, TODAY, False), False)
    assert _keys(out) == ["issue_open", "report"]
    card = _one(out, "issue_open")
    assert (card["before"], card["after"]) == ("1", "2")
    assert card["sentence"] == "2 issues open at Main block. The oldest has waited 4 days."
    assert _one(effects.cards("site_issue", await effects.read_issue(conn, org, old, TODAY, False), False),
                "issue_open")["before"] is None  # not the newest: no before
    assert await effects.read_issue(conn, org, uuid.uuid4(), TODAY, False) is None

    # --- an expense to a supplier: read, owed by the supplier ledger, in the week's cost -----------------
    vendor, expense = uuid.uuid4(), uuid.uuid4()
    await conn.execute(text("INSERT INTO vendors (id, organization_id, name, created_by) VALUES (:id, :org, 'ABC Traders', :u)"),
                       {"id": vendor, "org": org, "u": made.owner_user_id})
    category = uuid.uuid4()
    await conn.execute(text("INSERT INTO expense_categories (id, organization_id, name, created_by) VALUES (:id, :org, 'Cement', :u)"),
                       {"id": category, "org": org, "u": made.owner_user_id})
    await conn.execute(text(
        "INSERT INTO expenses (id, organization_id, project_id, site_id, amount, tax_amount, occurred_date, created_by, "
        "category_id, workflow_status, vendor_id) VALUES (:id, :org, :p, :s, 19500, 2975, :d, :u, :c, 'confirmed', :v)"),
        {"id": expense, "org": org, "p": project, "s": site, "d": TODAY, "u": made.owner_user_id, "c": category, "v": vendor})
    bill = effects.cards("expense", await effects.read_expense(conn, org, expense, TODAY, True, auth=auth), True)
    assert _keys(bill)[0] == "expense_read" and "supplier" in _keys(bill) and "week_cost" in _keys(bill), _keys(bill)
    assert _one(bill, "expense_read")["after"] == "19500"
    assert _one(bill, "supplier")["sentence"] == "You now owe ABC Traders ₹19,500."
    # Guard: nothing at all for a role that does not see spending; a draft expense has no ripple.
    assert await effects.read_expense(conn, org, expense, TODAY, False, auth=auth) is None
    await conn.execute(text("UPDATE expenses SET workflow_status = 'pending_confirmation' WHERE id = :id"), {"id": expense})
    assert await effects.read_expense(conn, org, expense, TODAY, True, auth=auth) is None

    # --- a hired machine's day, saved through the equipment routes ------------------------------------------
    await equipment.create_machine(equipment.MachineCreate(
        name="JCB", type="Excavator", ownership="hired", hire_company="Kochi Earthmovers", rate=Decimal(1200),
        rate_unit="hour", min_hours_per_day=Decimal(4), site_id=site), auth_context=auth, conn=conn)
    saved = await equipment.save_logs(equipment.LogCreate(lines=[equipment.LogLine(
        machine="JCB", worked_hours=Decimal(6), breakdown_hours=Decimal(2), breakdown_reason="hydraulic hose",
        fuel_litres=Decimal(30))]), auth_context=auth, conn=conn)
    log = uuid.UUID(saved["items"][0]["id"])
    day = (await conn.execute(text("SELECT occurred_date FROM equipment_events WHERE id = :id"), {"id": log})).scalar()
    located = await effects.locate(conn, org, effects.MACHINE_LOG, log)
    assert located == {"project_id": project, "site_id": site}
    machine = effects.cards("machine_log", await effects.read_machine_log(conn, org, log, day, True), True)
    assert _keys(machine) == ["machine_day", "machine_down", "machine_hire"]
    assert _one(machine, "machine_day")["sentence"] == "JCB at Main block: 6 h worked, 30 L diesel."
    assert _one(machine, "machine_hire")["after"] == "7200"  # 6 h at ₹1,200, as the hire check counts it
    plain = effects.cards("machine_log", await effects.read_machine_log(conn, org, log, day, False), False)
    assert _keys(plain) == ["machine_day", "machine_down"]
    # Guard: another company's record is not located.
    assert await effects.locate(conn, uuid.uuid4(), effects.MACHINE_LOG, log) is None
