# ruff: noqa: F811 -- pytest fixtures imported from other contract tests are used as test arguments
"""GM-01: "Waiting for you" on a real Postgres (run with `pytest -m integration`).

One list over each module's own statuses: a material request waiting, a subcontract bill flagged by its check, work a
subcontractor reported. Each person sees only what their module's rule lets them decide; deciding through the
module's own route takes the row off. Flagged first; the count matches the rows.
"""

from __future__ import annotations

import uuid

import pytest

from contract.test_rates_api_contract import _exec, _user, client, world  # noqa: F401
from contract.test_subcontracts_contract import _measure, _wo
from contract.test_supplier_ledger_contract import test_engine  # noqa: F401

pytestmark = pytest.mark.integration


async def _inbox(client, h, **params) -> dict:
    r = await client.get("/approvals/inbox", headers=h, params=params)
    assert r.status_code == 200, r.text
    return r.json()


async def _setup(client, w, test_engine) -> dict:
    h = w["admin"]["h"]
    req = await client.post("/procurement/requests", headers=w["arun"]["h"], json={
        "project_id": str(w["villa"]), "site_id": str(w["block_a"]),
        "lines": [{"material_id": w["cement"], "quantity": "250", "unit_id": w["units"]["bags"]}]})
    assert req.status_code == 201, req.text
    wo = await _wo(client, w, issue=True)
    await _measure(client, w, wo, 1, "200")
    bill = (await client.post(f"/subcontracts/work-orders/{wo['id']}/bills", headers=h, json={
        "lines": [{"line_id": wo["lines"][1]["id"], "quantity": "500"}]})).json()["bill"]
    assert bill["check_status"] == "flagged"
    mid = uuid.uuid4()
    await _exec(test_engine, "INSERT INTO work_order_measurements (id, organization_id, work_order_id, line_id, "
                "measured_on, quantity, status, source, recorded_by_name) VALUES (:id, :org, :wo, :line, CURRENT_DATE, "
                "950, 'proposed', 'whatsapp', 'Ravi Concrete Team')", id=mid, org=w["org"], wo=wo["id"],
                line=wo["lines"][1]["id"])
    return {"req": req.json(), "wo": wo, "bill": bill, "mid": str(mid)}


async def test_one_list_flagged_first_each_with_its_deciding_fact(client, world, test_engine):
    w = world
    s = await _setup(client, w, test_engine)
    out = await _inbox(client, w["admin"]["h"])
    kinds = [r["kind"] for r in out["items"]]
    assert kinds[0] == "subcontract_bill" and set(kinds) == {"subcontract_bill", "material_request", "measurement"}
    bill = out["items"][0]
    assert bill["flagged"] and bill["tone"] == "bad" and bill["amount"] == s["bill"]["gross"]
    assert bill["fact"].startswith("Billed 300 sqm more than measured on Shuttering")
    req = next(r for r in out["items"] if r["kind"] == "material_request")
    assert req["title"] == "Cement OPC 53 × 250 bags" and req["asked_by"] == "Arun"
    assert req["fact"].endswith("250 bags to buy") and req["actions"] == ["ordered", "sent", "rejected"]
    meas = next(r for r in out["items"] if r["kind"] == "measurement")
    assert meas["tone"] == "bad" and "1150 sqm of 1000 sqm agreed" in meas["fact"]   # 200 confirmed + 950 asked
    assert out["counts"]["total"] == 3 and out["counts"]["flagged"] == 1
    count = (await client.get("/approvals/inbox/count", headers=w["admin"]["h"])).json()["counts"]
    assert count == out["counts"]

    only = await _inbox(client, w["admin"]["h"], kind="material_request")
    assert [r["kind"] for r in only["items"]] == ["material_request"]
    assert (await client.get("/approvals/inbox", headers=w["admin"]["h"], params={"kind": "nonsense"})).status_code == 422


async def test_each_person_sees_only_what_their_module_lets_them_decide(client, world, test_engine):
    w = world
    await _setup(client, w, test_engine)
    # Arun, site engineer at the villa: confirms the subcontractor's measurement there; never bills or requests.
    arun = await _inbox(client, w["arun"]["h"])
    assert [r["kind"] for r in arun["items"]] == ["measurement"] and arun["items"][0]["amount"] is None
    # Ravi, site engineer on the other project: nothing.
    assert (await _inbox(client, w["ravi"]["h"]))["items"] == []
    # A project manager on the other project only: nothing from the villa.
    pm = await _user(test_engine, w["org"], "project_manager", "Joby", projects=[w["flats"]])
    assert (await _inbox(client, pm["h"]))["items"] == []
    # The same PM narrowed to a project they are not on: nothing, not an error.
    assert (await _inbox(client, pm["h"], project_id=str(w["villa"])))["items"] == []


async def test_deciding_through_the_module_takes_the_row_off(client, world, test_engine):
    w = world
    s = await _setup(client, w, test_engine)
    h = w["admin"]["h"]
    ok = await client.post(f"/subcontracts/bills/{s['bill']['id']}/approve", headers=h, json={"reason": "Checked on site"})
    assert ok.status_code == 200
    no = await client.post(f"/procurement/requests/{s['req']['id']}/decide", headers=h,
                           json={"action": "rejected", "note": "Stock at the yard"})
    assert no.status_code == 200, no.text
    yes = await client.post(f"/subcontracts/measurements/{s['mid']}/confirm", headers=h, json={})
    assert yes.status_code == 200, yes.text
    out = await _inbox(client, h)
    assert out["items"] == [] and out["counts"]["total"] == 0
