# ruff: noqa: F811  (pytest fixtures imported from the billing suite are parameters here)
"""Contract tests for the end of a project: END-01 snag list, END-02 payments received and receivables, END-03 the
handover checklist.

Requires a live Postgres reachable via Settings().postgres.dsn() -- run with `pytest -m integration`. Fixtures and
helpers are the billing suite's (same org / project / BOQ setup).
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa

from .test_billing_contract import (  # noqa: F401 (fixtures)
    _boq,
    _h,
    _measured,
    _user,
    clean_db,
    client,
    ctx,
    test_engine,
)

pytestmark = pytest.mark.integration


async def _site(engine, ctx) -> str:
    async with engine.begin() as conn:
        return str((await conn.execute(sa.text("SELECT id FROM sites WHERE project_id = :p"),
                                       {"p": ctx["project"]})).scalar_one())


# -- END-01 snags ------------------------------------------------------------------------------------------------------

async def test_a_snag_from_raised_to_closed_and_who_may_do_what(client, ctx, test_engine):
    p, admin = ctx["project"], _h(ctx["admin"])
    engineer = _h(await _user(test_engine, ctx["org"], "site_engineer"))
    site = await _site(test_engine, ctx)
    r = await client.post(f"/projects/{p}/snags", json={
        "description": "  Tile chipped   near the door ", "place": "Bedroom 2", "site_id": site, "trade": "tiler",
        "due_on": "2026-11-20"}, headers=engineer)
    assert r.status_code == 201, r.text
    one = r.json()
    assert (one["ref"], one["status"], one["description"], one["site_name"], one["phase"]) == (
        "SN-001", "open", "Tile chipped near the door", "Main building", "before_handover")
    two = (await client.post(f"/projects/{p}/snags", json={"description": "Switch board loose", "found_by": "client"},
                             headers=admin)).json()
    assert two["ref"] == "SN-002" and two["found_by"] == "client"

    # The site engineer says it is fixed; only a manager closes or sends it back.
    r = await client.post(f"/snags/{one['id']}/fixed", json={"note": "Replaced 2 tiles"}, headers=engineer)
    assert r.json()["status"] == "fixed" and r.json()["fixed_note"] == "Replaced 2 tiles"
    assert (await client.post(f"/snags/{one['id']}/close", headers=engineer)).status_code == 403
    r = await client.post(f"/snags/{one['id']}/reopen", json={"reason": "Grout colour differs"}, headers=admin)
    assert r.json()["status"] == "open" and r.json()["reopened_note"] == "Grout colour differs"
    await client.post(f"/snags/{one['id']}/fixed", headers=engineer)
    assert (await client.post(f"/snags/{one['id']}/close", headers=admin)).json()["status"] == "closed"
    assert (await client.patch(f"/snags/{one['id']}", json={"place": "x"}, headers=admin)).status_code == 409
    assert (await client.delete(f"/snags/{one['id']}", headers=admin)).status_code == 409

    listed = (await client.get(f"/snags?project_id={p}&status=pending", headers=engineer)).json()
    assert [s["ref"] for s in listed["snags"]] == ["SN-002"]
    assert listed["counts"] == {"open": 1, "fixed": 0, "closed": 1} and listed["can_manage"] is False
    assert (await client.delete(f"/snags/{two['id']}", headers=admin)).status_code == 204


async def test_snag_validation_scope_and_the_defect_period(client, ctx, test_engine):
    p, admin = ctx["project"], _h(ctx["admin"])
    for body in ({}, {"description": " "}, {"description": "x", "found_by": "them"},
                 {"description": "x", "site_id": str(uuid.uuid4())}, {"description": "x", "vendor_id": str(uuid.uuid4())}):
        assert (await client.post(f"/projects/{p}/snags", json=body, headers=admin)).status_code == 422, body
    assert (await client.get("/snags?status=done", headers=admin)).status_code == 422
    other = _h(await _user(test_engine, ctx["org"], "site_engineer", '{"mode": "selected_projects", "projects": []}'))
    assert (await client.post(f"/projects/{p}/snags", json={"description": "x"}, headers=other)).status_code == 403

    # Handed over: the stage moves to the defect period and new snags are defects.
    r = await client.patch(f"/projects/{p}/handover", json={"handed_over_on": "2026-11-01"}, headers=admin)
    assert r.status_code == 200, r.text
    assert r.json()["project"]["stage"] == "defects" and r.json()["handed_over_on"] == "2026-11-01"
    snag = (await client.post(f"/projects/{p}/snags", json={"description": "Leak under the sink"}, headers=admin)).json()
    assert snag["phase"] == "defects"
    assert (await client.patch(f"/projects/{p}/handover", json={"handed_over_on": "2099-01-01"},
                               headers=admin)).status_code == 422
    r = await client.patch(f"/projects/{p}/handover", json={"clear": True}, headers=admin)
    assert r.json()["project"]["stage"] == "handover" and r.json()["handed_over_on"] is None


# -- END-02 payments and receivables -----------------------------------------------------------------------------------

async def _submitted_bill(client, ctx, engine) -> dict:
    h = _h(ctx["admin"])
    m20, plaster = await _boq(client, ctx)
    await _measured(client, ctx, engine, m20["id"], "120", "cum")
    await _measured(client, ctx, engine, plaster["id"], "800", "sqm")
    bill = (await client.post(f"/projects/{ctx['project']}/ra-bills", json={"bill_date": "2026-11-01"}, headers=h)).json()
    return (await client.post(f"/billing/ra-bills/{bill['id']}/submit", headers=h)).json()


async def test_payments_against_a_bill_retention_and_advance(client, ctx, test_engine):
    p, h = ctx["project"], _h(ctx["admin"])
    bill = await _submitted_bill(client, ctx, test_engine)  # net 11,27,160; retention 55,800; advance 8,50,000
    url = f"/projects/{p}/client-payments"

    # "client paid 6 lakh for RA-01": the bill named the way people say it.
    r = await client.post(url, json={"amount": "600000", "bill_ref": "RA-01", "mode": "bank", "reference": "UTR123"},
                          headers=h)
    assert r.status_code == 201, r.text
    pay, money = r.json()["payment"], r.json()["receivable"]
    assert (pay["bill_ref"], pay["kind"], pay["amount"], pay["client_name"]) == ("RA-01", "bill", "600000.00", None)
    assert money["outstanding"] == "527160.00" and money["bills"][0]["received"] == "600000.00"
    # One bill still owed: a payment that names no bill goes on it.
    r = await client.post(url, json={"amount": "27160"}, headers=h)
    assert r.json()["payment"]["bill_ref"] == "RA-01" and r.json()["receivable"]["outstanding"] == "500000.00"

    for body, words in (({"amount": "500001", "bill_ref": "RA-01"}, "more than"),
                        ({"amount": "1", "bill_ref": "RA-09"}, "No bill RA-09"),
                        ({"amount": "55801", "kind": "retention"}, "retention"),
                        ({"amount": "850001", "kind": "advance"}, "advance"),
                        ({"amount": "1", "kind": "other", "bill_id": bill["id"]}, "names a bill"),
                        ({"amount": "1", "kind": "bill", "received_on": "2099-01-01"}, "not come yet")):
        r = await client.post(url, json=body, headers=h)
        assert r.status_code == 422 and words in r.text, (body, r.text)
    assert (await client.post(url, json={"amount": "0"}, headers=h)).status_code == 422

    await client.post(url, json={"amount": "850000", "kind": "advance", "received_on": "2026-10-01"}, headers=h)
    await client.post(url, json={"amount": "20000", "kind": "retention"}, headers=h)
    rec = (await client.get(f"/billing/receivables?project_id={p}", headers=h)).json()
    one = rec["projects"][0]
    assert (one["outstanding"], one["retention_held"], one["retention_left"], one["advance_left"]) == (
        "500000.00", "55800.00", "35800.00", "0.00")
    assert rec["outstanding"] == "500000.00"
    # The company-wide list finds the project without being told which.
    assert [x["project"]["id"] for x in (await client.get("/billing/receivables", headers=h)).json()["projects"]] == [
        str(p)]

    pays = (await client.get(f"/billing/payments?project_id={p}", headers=h)).json()
    assert [x["kind"] for x in pays][-1] == "advance" and len(pays) == 4
    # A bill with payments can't be withdrawn; removing the payments first lets it.
    assert (await client.post(f"/billing/ra-bills/{bill['id']}/cancel", headers=h)).status_code == 409
    for x in pays:
        assert (await client.delete(f"/billing/payments/{x['id']}", headers=h)).status_code == 204
    assert (await client.post(f"/billing/ra-bills/{bill['id']}/cancel", headers=h)).json()["status"] == "cancelled"


async def test_certified_amount_is_what_is_due_and_who_sees_money(client, ctx, test_engine):
    p, h = ctx["project"], _h(ctx["admin"])
    bill = await _submitted_bill(client, ctx, test_engine)
    await client.post(f"/billing/ra-bills/{bill['id']}/certify", json={"certified_amount": "1100000"}, headers=h)
    rec = (await client.get(f"/billing/receivables?project_id={p}", headers=h)).json()
    assert rec["projects"][0]["bills"][0]["due"] == "1100000.00"
    for role, code in (("finance", 200), ("project_manager", 403), ("site_engineer", 403)):
        token = _h(await _user(test_engine, ctx["org"], role))
        assert (await client.get("/billing/receivables", headers=token)).status_code == code, role
        assert (await client.post(f"/projects/{p}/client-payments", json={"amount": "1"},
                                  headers=token)).status_code in (code if code != 200 else 201, 422), role


# -- END-03 handover checklist -----------------------------------------------------------------------------------------

async def test_handover_checklist_shows_money_only_to_money_roles(client, ctx, test_engine):
    p, h = ctx["project"], _h(ctx["admin"])
    await _submitted_bill(client, ctx, test_engine)
    await client.post(f"/projects/{p}/snags", json={"description": "Paint patch in the hall"}, headers=h)
    r = (await client.get(f"/projects/{p}/handover", headers=h)).json()
    steps = {s["key"]: s for s in r["steps"]}
    assert list(steps) == ["work", "snags", "subcontracts", "final_bill", "paid", "handover"]
    assert steps["final_bill"]["done"] is True  # everything measured is on RA-01
    assert steps["paid"]["done"] is False and "₹11,27,160 still owed" in steps["paid"]["detail"]
    assert steps["snags"]["detail"].startswith("1 open") and r["next"] == "work"
    pm = _h(await _user(test_engine, ctx["org"], "project_manager"))
    r = (await client.get(f"/projects/{p}/handover", headers=pm)).json()
    assert [s["key"] for s in r["steps"]] == ["work", "snags", "subcontracts", "handover"] and r["money"] is None
    assert r["can_edit"] is True and r["can_see_money"] is False

    # More work measured after the bill: the final bill step asks for it.
    m20_line = (await client.get(f"/billing/ra-bills?project_id={p}", headers=h)).json()
    assert m20_line
    async with test_engine.begin() as conn:
        line = (await conn.execute(sa.text(
            "SELECT planned_item_id FROM ra_bill_lines l JOIN ra_bills b ON b.id = l.ra_bill_id WHERE b.project_id = :p "
            "ORDER BY l.sort_order LIMIT 1"), {"p": p})).scalar_one()
    await _measured(client, ctx, test_engine, str(line), "5", "cum")
    steps = {s["key"]: s for s in (await client.get(f"/projects/{p}/handover", headers=h)).json()["steps"]}
    assert steps["final_bill"]["done"] is False and steps["final_bill"]["detail"].startswith("1 BOQ lines")
