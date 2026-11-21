"""FB-01: payment stages against a real Postgres.

The contractor's example: Footing and Lintel done, Roof slab not; the client paid ₹3,20,000 of the ₹7,00,000 the two
stages ask for -> an alert of ₹3,80,000 short since Lintel. A lump-sum contract bills the reached stages (one line
each, the contract's GST on top), never the BOQ, and a stage on a bill can't be billed again or deleted. A measured
contract's stages are the payment schedule only: its bills still come from the BOQ. Rolled back after the test."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from mesiri.application.organizations.create_company import NewCompany, create_company
from mesiri.authorization.context import AuthorizationContext, ProjectAccessScope, SiteAccessScope
from mesiri.domains.billing import router as billing
from mesiri.domains.progress import boq_router

from .test_live_questions_postgres import NOW, conn  # noqa: F401 -- the shared fixture

pytestmark = pytest.mark.integration


async def _company(conn, phone):  # noqa: F811
    made = await create_company(
        conn, NewCompany(name="Stage Builders", owner_name="Ravi Kumar", owner_phone=phone,
                         project_name="Green Villa", site_names=("Main block",), auto_dpr=False), now=NOW)
    org, project = made.organization_id, made.project_id
    owner = AuthorizationContext(user_id=made.owner_user_id, organization_id=org, role="ADMIN", status="active",
                                 access_policy={},  # type: ignore[arg-type]
                                 project_scope=ProjectAccessScope(mode="all_projects", project_ids=set()),
                                 site_scopes={project: SiteAccessScope(mode="all_sites", site_ids=set())})
    account = uuid.uuid4()
    await conn.execute(text(
        "INSERT INTO money_accounts (id, organization_id, account_type, name, opening_balance, opening_balance_date, "
        "created_by) VALUES (:id, :o, 'bank', 'Current account', 0, :d, :u)"),
        {"id": account, "o": org, "d": dt.date(2026, 8, 1), "u": made.owner_user_id})
    sections = {}
    for name in ("Footing", "Lintel", "Roof slab"):
        sections[name] = (await boq_router.create_section(project, boq_router.SectionCreate(name=name), auth=owner,
                                                          conn=conn))["id"]
    return org, project, owner, account, sections


async def _done(conn, section, day):  # noqa: F811
    await conn.execute(text("UPDATE work_packages SET status = 'COMPLETED', actual_end = :d WHERE id = :id"),
                       {"id": section, "d": day})


async def _contract(project, owner, conn, kind):  # noqa: F811
    await billing.put_contract(project, billing.ContractIn(
        new_client=billing.ClientIn(name="Mr Thomas"), contract_value=Decimal(1200000), gst_pct=Decimal(18),
        contract_type=kind), auth=owner, conn=conn)


async def _stages(project, owner, conn, sections):  # noqa: F811
    out = {}
    for name, amount in (("Footing", 300000), ("Lintel", 400000), ("Roof slab", 500000)):
        out[name] = await billing.create_payment_stage(project, billing.StageIn(
            name=name, amount=Decimal(amount), work_package_id=sections[name]), auth=owner, conn=conn)
    return out


async def test_milestone_done_and_money_short_raises_the_follow_up(conn) -> None:  # noqa: F811
    org, project, owner, account, sections = await _company(conn, "+919876500301")
    await _contract(project, owner, conn, "measured")
    await _stages(project, owner, conn, sections)

    nothing = await billing.payment_alerts(auth=owner, conn=conn)
    assert nothing["projects"] == []  # no stage reached: nothing is owed yet

    await _done(conn, sections["Footing"], dt.date(2026, 9, 1))
    await _done(conn, sections["Lintel"], dt.date(2026, 10, 5))
    await billing.record_client_receipt(billing.ReceiptIn(
        project_id=project, kind="on_account", amount=Decimal(320000), account_id=account,
        received_on=dt.date(2026, 9, 3)), auth=owner, conn=conn)

    alerts = await billing.payment_alerts(auth=owner, conn=conn)
    assert alerts["short"] == "380000.00"
    [one] = alerts["projects"]
    assert one["due"] == "700000.00" and one["received"] == "320000.00"
    assert one["behind_since"]["name"] == "Lintel" and one["behind_since"]["reached_on"] == "2026-10-05"
    assert one["latest_reached"]["name"] == "Lintel"

    state = await billing.list_payment_stages(project, auth=owner, conn=conn)
    by_name = {s["name"]: s for s in state["stages"]}
    assert by_name["Footing"]["reached"] and by_name["Footing"]["paid"]
    assert by_name["Lintel"]["reached"] and not by_name["Lintel"]["paid"]
    assert not by_name["Roof slab"]["reached"]
    assert state["total"] == "1200000.00"

    # Measured contract: the stages never become bill lines; with no measured work there is nothing to bill.
    with pytest.raises(HTTPException) as e:
        await billing.create_ra_bill(project, billing.BillCreate(), auth=owner, conn=conn)
    assert "No measured work" in e.value.detail

    # Paid up -> the alert goes.
    await billing.record_client_receipt(billing.ReceiptIn(
        project_id=project, kind="on_account", amount=Decimal(380000), account_id=account), auth=owner, conn=conn)
    assert (await billing.payment_alerts(auth=owner, conn=conn))["projects"] == []


async def test_lump_sum_bills_the_reached_stages_once(conn) -> None:  # noqa: F811
    org, project, owner, account, sections = await _company(conn, "+919876500302")
    await _contract(project, owner, conn, "lump_sum")
    stages = await _stages(project, owner, conn, sections)
    await _done(conn, sections["Footing"], dt.date(2026, 9, 1))

    to_bill = await billing.work_to_bill(auth=owner, conn=conn)
    assert to_bill["amount"] == "300000.00"
    assert to_bill["projects"][0]["stages"] is True  # Home says "1 payment stage reached", not BOQ lines

    bill = await billing.create_ra_bill(project, billing.BillCreate(), auth=owner, conn=conn)
    [line] = bill["lines"]
    assert line["work"] == "Footing" and line["unit"] == "LS" and line["payment_stage_id"] == stages["Footing"]["id"]
    assert line["planned_item_id"] is None
    assert bill["gross"] == "300000.00" and bill["gst"] == "54000.00" and bill["net"] == "354000.00"
    assert bill["warnings"] == []
    await billing.submit_ra_bill(uuid.UUID(bill["id"]), auth=owner, conn=conn)

    # Billed once: nothing more to bill until the next stage, and a billed stage can't be removed or re-priced.
    assert (await billing.work_to_bill(auth=owner, conn=conn))["amount"] == "0.00"
    with pytest.raises(HTTPException) as e:  # a refused request rolls back (its empty draft goes with it)
        async with conn.begin_nested():
            await billing.create_ra_bill(project, billing.BillCreate(), auth=owner, conn=conn)
    assert "No payment stage to bill" in e.value.detail
    stage_id = uuid.UUID(stages["Footing"]["id"])
    with pytest.raises(HTTPException) as e:
        await billing.delete_payment_stage(stage_id, auth=owner, conn=conn)
    assert e.value.status_code == 409
    with pytest.raises(HTTPException):
        await billing.update_payment_stage(stage_id, billing.StageIn(amount=Decimal(1)), auth=owner, conn=conn)

    # The next milestone: only Lintel goes on the next bill.
    await _done(conn, sections["Lintel"], dt.date(2026, 10, 5))
    second = await billing.create_ra_bill(project, billing.BillCreate(), auth=owner, conn=conn)
    assert [ln["work"] for ln in second["lines"]] == ["Lintel"]


async def test_stage_tied_to_nothing_is_reached_by_hand(conn) -> None:  # noqa: F811
    org, project, owner, account, sections = await _company(conn, "+919876500303")
    await _contract(project, owner, conn, "measured")
    handover = await billing.create_payment_stage(project, billing.StageIn(name="Handover", amount=Decimal(50000)),
                                                  auth=owner, conn=conn)
    sid = uuid.UUID(handover["id"])
    assert (await billing.payment_alerts(auth=owner, conn=conn))["projects"] == []
    await billing.update_payment_stage(sid, billing.StageIn(reached_on=dt.date(2026, 11, 20)), auth=owner, conn=conn)
    [one] = (await billing.payment_alerts(auth=owner, conn=conn))["projects"]
    assert one["short"] == "50000.00"

    # Tied to an activity: reached only by that activity, never by hand as well.
    await billing.update_payment_stage(sid, billing.StageIn(work_package_id=sections["Roof slab"]), auth=owner,
                                       conn=conn)
    assert (await billing.payment_alerts(auth=owner, conn=conn))["projects"] == []
    with pytest.raises(HTTPException) as e:
        await billing.update_payment_stage(sid, billing.StageIn(reached_on=dt.date(2026, 11, 20)), auth=owner,
                                           conn=conn)
    assert "schedule" in e.value.detail

    # Another project's activity is refused.
    with pytest.raises(HTTPException):
        await billing.create_payment_stage(project, billing.StageIn(name="X", amount=Decimal(1),
                                                                    work_package_id=uuid.uuid4()), auth=owner, conn=conn)
