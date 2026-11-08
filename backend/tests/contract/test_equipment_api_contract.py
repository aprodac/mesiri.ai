# ruff: noqa: F811 -- pytest fixtures imported from the rates contract test are used as test arguments
"""NXT-11 / NXT-13 / NXT-14 / NXT-15: the equipment API on a real Postgres (run with `pytest -m integration`).

A hired JCB is added at a site (its hire company made a vendor of kind hire); the site engineer logs its day once
("6 hrs, 2 hrs breakdown, 30 L diesel"), which raises the breakdown issue once; a second message the same day adds
to the day instead of wiping it; a log at another site moves it there. Hire is charged per the hire's minimum hours,
never for breakdown; the hire bill is checked against the hours; costs per site count hire and diesel once. Rates and
costs are hidden from a site engineer, and a site engineer of another project cannot see or log the machine.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from contract.test_rates_api_contract import (  # noqa: F401 -- fixtures
    _TABLES,
    _day,
    client,
    world,
)
from mesiri.bootstrap.settings import Settings

pytestmark = pytest.mark.integration


async def _wipe(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        for table in ("equipment_hire_bills", "equipment_events", "equipment", "site_issues"):
            await conn.execute(sa.text(f"DELETE FROM {table}"))  # noqa: S608 -- fixed names
        await conn.execute(sa.text("UPDATE material_usage SET reverses_movement_id = NULL"))
        await conn.execute(sa.text("UPDATE material_receipts SET reverses_movement_id = NULL, invoice_id = NULL"))
        await conn.execute(sa.text("UPDATE material_invoices SET expense_id = NULL"))
        await conn.execute(sa.text("UPDATE expense_payments SET advance_id = NULL"))
        for table in _TABLES:
            if table == "users":
                await conn.execute(sa.text("DELETE FROM money_accounts"))
            await conn.execute(sa.text(f"DELETE FROM {table}"))  # noqa: S608 -- fixed names


@pytest.fixture
async def test_engine():
    engine = create_async_engine(Settings().postgres.dsn(), echo=False)
    await _wipe(engine)
    yield engine
    await _wipe(engine)
    await engine.dispose()


async def _jcb(client, w, **extra) -> dict:
    r = await client.post("/equipment", headers=w["admin"]["h"], json={
        "name": "JCB", "type": "Backhoe loader", "hire_company": "Kerala Earthmovers", "rate": "1100",
        "rate_unit": "hour", "min_hours_per_day": "8", "site_id": str(w["block_a"]), **extra})
    assert r.status_code == 201, r.text
    return r.json()


async def test_a_hired_machine_logged_once_charged_checked_and_costed(client, world, test_engine):
    w = world
    jcb = await _jcb(client, w)
    assert (jcb["ref"], jcb["ownership"], jcb["state"], jcb["site_name"]) == ("EQ-0001", "hired", "not_logged", "Block A")
    vendor = (await client.get(f"/finance/vendors/{jcb['vendor_id']}", headers=w["admin"]["h"])).json()
    assert vendor["kind"] == "hire" and vendor["linked"]["machines"] == 1

    # The site engineer logs the day in words: saved once, the breakdown raises one issue.
    r = await client.post("/equipment/logs", headers=w["arun"]["h"], json={"source": "whatsapp", "lines": [
        {"machine": "jcb", "worked_hours": "6", "breakdown_hours": "2", "breakdown_reason": "hydraulic leak",
         "fuel_litres": "30", "fuel_cost": "2700"}]})
    assert r.status_code == 201, r.text
    saved = r.json()
    assert len(saved["issues"]) == 1 and saved["replaced"] == []
    line = saved["items"][0]
    assert (line["worked_hours"], line["breakdown_hours"], line["fuel_litres"], line["fuel_cost"]) == ("6", "2", "30", None)
    issue = (await client.get("/progress/issues", headers=w["admin"]["h"])).json()
    issues = issue["items"] if isinstance(issue, dict) else issue
    assert [i["issue_type"] for i in issues] == ["EQUIPMENT_BREAKDOWN"]

    # The same day again, only diesel: added to the day, hours kept, no second issue.
    r = await client.post("/equipment/logs", headers=w["arun"]["h"], json={"lines": [
        {"machine": "JCB", "fuel_litres": "40"}]})
    assert r.status_code == 201, r.text
    again = r.json()
    assert again["issues"] == [] and again["replaced"][0]["was"]["fuel_litres"] == "30"
    assert (again["items"][0]["worked_hours"], again["items"][0]["fuel_litres"]) == ("6", "40")

    # The engineer sees hours but no money; the admin sees the hire: 8 hrs minimum x 1,100 (breakdown not charged).
    board = (await client.get("/equipment", headers=w["arun"]["h"])).json()
    one = board["items"][0]
    assert (one["state"], one["rate"], one["month"]["cost"], board["counts"]["working"]) == ("working", None, None, 1)
    board = (await client.get("/equipment", headers=w["admin"]["h"])).json()
    one = board["items"][0]
    assert (one["rate"], one["month"]["hire_cost"], one["month"]["fuel_cost"]) == ("1100.00", "8800.00", "2700.00")

    # Another project's engineer can neither see it nor log it.
    assert (await client.get("/equipment", headers=w["ravi"]["h"])).json()["items"] == []
    r = await client.post("/equipment/logs", headers=w["ravi"]["h"], json={"lines": [{"machine": "JCB", "worked_hours": "3"}]})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "unknown_machine"

    # Costs per site: hire + diesel, once.
    costs = (await client.get("/equipment/costs", headers=w["admin"]["h"])).json()
    assert (costs["hire"], costs["fuel"], costs["total"]) == ("8800.00", "2700.00", "11500.00")
    assert (await client.get("/equipment/costs", headers=w["arun"]["h"])).status_code == 403

    # The hire bill asks for 10 hours and 13,000: flagged against the 8 hours recorded.
    r = await client.post("/equipment/hire-bills", headers=w["admin"]["h"], json={
        "equipment_id": jcb["id"], "period_from": _day(0), "period_to": _day(0), "billed_hours": "10",
        "amount": "13000", "bill_ref": "KE/77"})
    assert r.status_code == 201, r.text
    check = r.json()["check"]
    assert (check["status"], check["recorded"]["charged_hours"], check["difference"]) == ("over", "8", "4200.00")
    hc = (await client.get("/equipment/hire-check", headers=w["admin"]["h"])).json()
    assert hc["items"][0]["state"] == "over" and hc["totals"]["over"] == 1
    r = await client.post("/equipment/hire-bills", headers=w["admin"]["h"], json={
        "equipment_id": jcb["id"], "period_from": _day(0), "period_to": _day(0), "amount": "1"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "overlapping_bill"

    # History keeps the machine and its hire company: delete refused, retire allowed.
    assert (await client.delete(f"/equipment/{jcb['id']}", headers=w["admin"]["h"])).status_code == 409
    assert (await client.delete(f"/finance/vendors/{jcb['vendor_id']}", headers=w["admin"]["h"])).status_code == 409
    detail = (await client.get(f"/equipment/{jcb['id']}", headers=w["admin"]["h"])).json()
    assert len(detail["logs"]) == 1 and detail["bills"][0]["check"]["status"] == "over"
    assert [e["event_type"] for e in detail["events"]] == ["arrived"]


async def test_names_sites_moves_and_the_day_rules(client, world, test_engine):
    w = world
    await _jcb(client, w)
    r = await client.post("/equipment", headers=w["admin"]["h"], json={"name": "jcb", "site_id": str(w["yard"])})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "name_taken"
    two = (await client.post("/equipment", headers=w["admin"]["h"], json={
        "name": "JCB 2", "type": "Backhoe loader", "site_id": str(w["yard"]), "service_every_hours": "10"})).json()
    assert two["ownership"] == "owned" and two["service"]["status"] == "ok"

    # "JCB" is the machine of that name; "backhoe" fits both: the one at the site said, else asked.
    r = await client.post("/equipment/logs", headers=w["admin"]["h"], json={"lines": [{"machine": "backhoe", "worked_hours": "5"}]})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "which_machine"
    r = await client.post("/equipment/logs", headers=w["admin"]["h"], json={"lines": [
        {"machine": "backhoe", "site_id": str(w["yard"]), "worked_hours": "9.5"}, {"machine": "EQ-0001", "idle_hours": "8"}]})
    assert r.status_code == 201, r.text
    by = {x["machine"]: x for x in r.json()["items"]}
    assert (by["JCB 2"]["worked_hours"], by["JCB"]["idle_hours"]) == ("9.5", "8")
    board = {x["name"]: x for x in (await client.get("/equipment", headers=w["admin"]["h"])).json()["items"]}
    assert (board["JCB"]["state"], board["JCB 2"]["service"]["status"]) == ("idle", "soon")

    # An older day's breakdown stays on its log: no new issue dated today, no site hours lost.
    r = await client.post("/equipment/logs", headers=w["admin"]["h"], json={"occurred_date": _day(5), "lines": [
        {"machine": "JCB", "worked_hours": "2", "breakdown_hours": "6", "breakdown_reason": "tyre"}]})
    assert r.status_code == 201 and r.json()["issues"] == []
    r = await client.post("/equipment/logs", headers=w["admin"]["h"], json={"occurred_date": _day(1), "lines": [
        {"machine": "JCB 2", "worked_hours": "2", "breakdown_hours": "3"}]})
    assert len(r.json()["issues"]) == 1
    issues = (await client.get("/progress/issues", headers=w["admin"]["h"])).json()
    issues = issues["items"] if isinstance(issues, dict) else issues
    assert [i["delay_duration_minutes"] for i in issues] == [None]

    # A day of more than 24 hours, a future date, a line saying nothing: refused, nothing saved.
    for line, date in (({"machine": "JCB", "worked_hours": "20", "idle_hours": "5"}, None),
                       ({"machine": "JCB", "worked_hours": "2"}, _day(-1)), ({"machine": "JCB"}, None)):
        r = await client.post("/equipment/logs", headers=w["admin"]["h"], json={"lines": [line], "occurred_date": date})
        assert r.status_code == 422, (line, r.text)

    # Logged at the yard today: the JCB is at the yard now (one move).
    r = await client.post("/equipment/logs", headers=w["admin"]["h"], json={"lines": [
        {"machine": "JCB", "site_id": str(w["yard"]), "worked_hours": "4"}]})
    assert r.status_code == 201 and r.json()["moved"][0]["from_site_name"] == "Block A"
    jcb = next(x for x in (await client.get("/equipment", headers=w["admin"]["h"])).json()["items"] if x["name"] == "JCB")
    assert jcb["site_name"] == "Yard" and jcb["today"]["site_name"] == "Yard"

    # The daily log page: one date, with the machines not logged yet.
    day = (await client.get("/equipment/logs", params={"date": _day(0)}, headers=w["admin"]["h"])).json()
    assert day["totals"]["machines"] == 2 and day["missing"] == []

    # Off hire: no more logs at no site; on hire again at a site.
    r = await client.post(f"/equipment/{jcb['id']}/off-hire", headers=w["admin"]["h"], json={})
    assert r.status_code == 200 and r.json()["state"] == "off_hire"
    r = await client.post("/equipment/logs", headers=w["admin"]["h"], json={"lines": [{"machine": "JCB", "worked_hours": "1"}]})
    assert r.status_code == 409
    r = await client.post(f"/equipment/{jcb['id']}/on-hire", headers=w["admin"]["h"], json={"site_id": str(w["block_a"])})
    assert r.status_code == 200 and r.json()["status"] == "active" and r.json()["site_name"] == "Block A"

    # Service resets the hours to the next one; a voided log leaves the day.
    r = await client.post(f"/equipment/{two['id']}/service", headers=w["admin"]["h"], json={})
    assert r.json()["service"]["since"] == "0"
    log_id = day["items"][0]["id"]
    assert (await client.delete(f"/equipment/logs/{log_id}", headers=w["admin"]["h"])).status_code == 200
    day = (await client.get("/equipment/logs", params={"date": _day(0)}, headers=w["admin"]["h"])).json()
    assert day["totals"]["logs"] == 1 and len(day["missing"]) == 1


async def test_returnable_items_are_materials_per_site(client, world, test_engine):
    w = world
    h = w["admin"]["h"]
    cat = await client.post("/materials/categories", headers=h, json={"name": "Shuttering"})
    assert cat.status_code in (200, 201), cat.text
    cat_id = cat.json()["id"]
    assert (await client.put(f"/equipment/returnables/categories/{cat_id}", headers=h, json={"returnable": True})).status_code == 200
    assert (await client.put(f"/equipment/returnables/categories/{cat_id}", headers=w["arun"]["h"],
                             json={"returnable": True})).status_code == 403
    plate = (await client.post("/materials", headers=h, json={"name": "Shuttering plate", "default_unit_id": w["units"]["nos"],
                                                              "category_id": cat_id})).json()["id"]
    r = await client.post("/materials/inflows", headers=h, json={
        "project_id": str(w["villa"]), "site_id": str(w["block_a"]), "material_id": plate, "unit_id": w["units"]["nos"],
        "quantity": "400", "movement_reason": "RECEIVED", "occurred_date": _day(0)})
    assert r.status_code == 201, r.text
    out = (await client.get("/equipment/returnables", headers=h)).json()
    assert [(x["name"], x["total"]) for x in out["items"]] == [("Shuttering plate", "400")]
    assert out["sites"][0]["site_name"] == "Block A"
    assert (await client.get("/equipment/returnables", headers=w["ravi"]["h"])).json()["items"] == []
