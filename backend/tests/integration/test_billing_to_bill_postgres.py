"""WEB-91: "can be billed to the client now" (GET /billing/to-bill) against a real Postgres.

The read and a new RA bill's draft are one working (``bills.unbilled_lines``), so they must agree: work counted on a
priced BOQ line shows as billable; the draft takes exactly that; and once it is on a bill it is no longer "to bill".
Work not on a line, and a line with no client rate, are never billable. Rolled back after the test."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from mesiri.application.organizations.create_company import NewCompany, create_company
from mesiri.authorization.context import AuthorizationContext, ProjectAccessScope, SiteAccessScope
from mesiri.domains.billing import bills
from mesiri.domains.billing import router as billing
from mesiri.domains.dpr import board
from mesiri.domains.progress import boq_router

from .test_live_questions_postgres import NOW, conn  # noqa: F401 -- the shared fixture

pytestmark = pytest.mark.integration
TODAY = NOW.date()


async def _work(conn, org, project, site, section, quantity_id, amount, unit="sqm"):  # noqa: F811
    activity = uuid.uuid4()
    await conn.execute(text(
        "INSERT INTO activities (id, organization_id, project_id, site_id, activity_date, work_type, work_package_id) "
        "VALUES (:id, :org, :p, :s, :d, 'Plastering', :sec)"),
        {"id": activity, "org": org, "p": project, "s": site, "d": TODAY, "sec": section})
    await conn.execute(text(
        "INSERT INTO activity_quantities (id, activity_id, unit_id, quantity, work_type) "
        "SELECT :id, :a, u.id, :q, 'Plastering' FROM units_of_measure u WHERE u.code = :unit LIMIT 1"),
        {"id": quantity_id, "a": activity, "q": amount, "unit": unit})


async def test_work_counted_on_a_priced_line_is_billable_until_it_is_on_a_bill(conn) -> None:  # noqa: F811
    made = await create_company(
        conn, NewCompany(name="To Bill Builders", owner_name="Ravi Kumar", owner_phone="+919876500091",
                         project_name="Green Villa", site_names=("Main block",), auto_dpr=False), now=NOW)
    org, project, site = made.organization_id, made.project_id, made.sites[0].site_id

    def auth(role):
        return AuthorizationContext(user_id=made.owner_user_id, organization_id=org, role=role, status="active",
                                    access_policy={},  # type: ignore[arg-type]
                                    project_scope=ProjectAccessScope(mode="all_projects", project_ids=set()),
                                    site_scopes={project: SiteAccessScope(mode="all_sites", site_ids=set())})

    owner = auth("ADMIN")
    section = await boq_router.create_section(project, boq_router.SectionCreate(name="Finishes"), auth=owner, conn=conn)
    priced = await boq_router.create_line(project, section["id"], boq_router.LineCreate(
        work="Plastering", unit="sqm", planned_quantity=Decimal(900), client_rate=Decimal(400)), auth=owner, conn=conn)
    unpriced = await boq_router.create_line(project, section["id"], boq_router.LineCreate(
        work="Painting", unit="sqm", planned_quantity=Decimal(900)), auth=owner, conn=conn)
    on_line, off_line, no_rate = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await _work(conn, org, project, site, section["id"], on_line, 120)
    await _work(conn, org, project, site, section["id"], off_line, 500)   # not put on a line by anyone
    await _work(conn, org, project, site, section["id"], no_rate, 50)

    # Nothing is on a line yet: nothing can be billed, and the board says nothing about it.
    assert (await billing.work_to_bill(project_id=None, auth=owner, conn=conn))["amount"] == "0.00"

    for quantity, line in ((on_line, priced), (no_rate, unpriced)):
        await boq_router.put_work_on_line(project, quantity, boq_router.WorkLine(line_id=uuid.UUID(str(line["id"]))),
                                          auth=owner, conn=conn)
    got = await billing.work_to_bill(project_id=None, auth=owner, conn=conn)
    assert got["amount"] == "48000.00"  # 120 sqm at 400; the 500 off a line and the unpriced 50 are not in it
    assert [(p["project"], p["lines"], p["amount"]) for p in got["projects"]] == [("Green Villa", 1, "48000.00")]
    assert board.say_to_bill(got) == "₹48,000 of measured work on Green Villa can be billed to the client now."

    # Guard: a project manager and a site engineer are refused, as on the bills themselves.
    for role in ("PROJECT_MANAGER", "SITE_ENGINEER"):
        with pytest.raises(HTTPException) as refused:
            await billing.work_to_bill(project_id=None, auth=auth(role), conn=conn)
        assert refused.value.status_code == 403

    # The draft is made from the same working: the same one line, the same quantity.
    bill_id, added = await bills.create_draft(conn, org, project, TODAY, None, made.owner_user_id)
    assert added == 1
    line = (await conn.execute(text(
        "SELECT quantity, client_rate, measured_to_date, previous_quantity FROM ra_bill_lines WHERE ra_bill_id = :b"),
        {"b": bill_id})).one()
    assert (Decimal(line.quantity), Decimal(line.client_rate), Decimal(line.measured_to_date),
            Decimal(line.previous_quantity)) == (Decimal(120), Decimal(400), Decimal(120), Decimal(0))
    # It is on a bill now: no longer "to bill". A cancelled bill gives it back.
    assert (await billing.work_to_bill(project_id=None, auth=owner, conn=conn))["amount"] == "0.00"
    await conn.execute(text("UPDATE ra_bills SET status = 'cancelled' WHERE id = :b"), {"b": bill_id})
    assert (await billing.work_to_bill(project_id=None, auth=owner, conn=conn))["amount"] == "48000.00"
