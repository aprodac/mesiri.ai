# ruff: noqa: F811 -- pytest fixtures imported from other contract tests are used as test arguments
"""GM-01 sources in the NXT-08 inbox, on a real Postgres (run with `pytest -m integration`).

Work a subcontractor reported (proposed) waits for the site to confirm it: urgent when it takes the line past the
agreed quantity; the site engineer at that site sees it too. A unit size nobody knew waits for those who may set one,
never for a site engineer. Confirming the work takes it off.
"""

from __future__ import annotations

import uuid

import pytest

from contract.test_rates_api_contract import _exec, client, world  # noqa: F401
from contract.test_subcontracts_contract import _measure, _wo
from contract.test_supplier_ledger_contract import test_engine  # noqa: F401

pytestmark = pytest.mark.integration


async def _waiting(client, h) -> dict:
    r = await client.get("/approvals/waiting", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


async def test_work_to_confirm_and_unit_sizes(client, world, test_engine):
    w = world
    wo = await _wo(client, w, issue=True)
    await _measure(client, w, wo, 1, "200")
    mid = uuid.uuid4()
    await _exec(test_engine, "INSERT INTO work_order_measurements (id, organization_id, work_order_id, line_id, "
                "measured_on, quantity, status, source, recorded_by_name) VALUES (:id, :org, :wo, :line, CURRENT_DATE, "
                "950, 'proposed', 'whatsapp', 'Ravi Concrete Team')", id=mid, org=w["org"], wo=wo["id"],
                line=wo["lines"][1]["id"])
    size = await client.post("/materials/size-requests", headers=w["arun"]["h"], json={
        "material_id": w["cement"], "from_unit_id": w["units"]["kg"], "one_unit_equals": "0.02"})
    assert size.status_code == 201, size.text

    admin = await _waiting(client, w["admin"]["h"])
    work = next(i for i in admin["items"] if i["kind"] == "measurement")
    assert work["urgent"] and work["title"] == "Ravi Concrete Team: 950 sqm Shuttering"
    assert "Takes the line to 1150 of 1000 sqm agreed" in work["detail"] and work["work_order_id"] == wo["id"]
    sizes = [i for i in admin["items"] if i["kind"] == "size_request"]
    assert len(sizes) == 1 and sizes[0]["title"] == "How much is 1 kg of Cement OPC 53?"
    assert admin["counts"]["measurement"] == 1 and admin["counts"]["size_request"] == 1

    arun = await _waiting(client, w["arun"]["h"])  # site engineer at the villa
    assert [i["kind"] for i in arun["items"] if i["kind"] in ("measurement", "size_request")] == ["measurement"]
    ravi = await _waiting(client, w["ravi"]["h"])  # site engineer on the other project
    assert [i for i in ravi["items"] if i["kind"] == "measurement"] == []

    ok = await client.post(f"/subcontracts/measurements/{mid}/confirm", headers=w["admin"]["h"], json={})
    assert ok.status_code == 200, ok.text
    assert (await _waiting(client, w["admin"]["h"]))["counts"]["measurement"] == 0
