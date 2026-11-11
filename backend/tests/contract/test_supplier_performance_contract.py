"""PRC-50: supplier performance on a real Postgres (run with `pytest -m integration`).

Three orders from one supplier: on time and complete; late, part rejected and closed short; on time. The score reads
them (closed short against complete %, rejected against quality), the list carries it, a supplier with too few
deliveries has none; the manual rating is given once per finished order, only by who may close orders; another
company sees nothing. Fixtures are the quotations contract's (same company, suppliers and items).
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

import pytest

from contract import test_rfqs_api_contract as rfq
from contract.company_day import company_today
from contract.test_rfqs_api_contract import _exec, _user, _vendor_id

# The quotations contract's fixtures (its company, suppliers and items), shared rather than copied.
test_engine, client, world = rfq.test_engine, rfq.client, rfq.world

pytestmark = pytest.mark.integration


async def _order(client, w, expected: datetime.date, qty="100", rate="400", supplier="Malabar Hardware") -> dict:
    resp = await client.post("/procurement/orders", headers=w["admin"]["h"], json={
        "project_id": str(w["villa"]), "site_id": str(w["block_a"]), "supplier": supplier, "confirm_duplicate": True,
        "expected_date": str(expected),
        "lines": [{"material_id": w["cement"], "quantity": qty, "unit_id": w["units"]["bags"], "rate": rate}]})
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _receive(client, w, order, accepted: str, rejected="0", reason=None) -> dict:
    line = {"line_id": order["lines"][0]["id"], "quantity": accepted, "rejected": rejected,
            **({"rejected_reason": reason} if reason else {})}
    resp = await client.post(f"/procurement/orders/{order['id']}/receive", headers=w["admin"]["h"],
                             json={"lines": [line], "occurred_date": str(company_today())})
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _history(client, w) -> list[dict]:
    today = company_today()
    first = await _order(client, w, today)
    await _receive(client, w, first, "100")
    late = await _order(client, w, today - datetime.timedelta(days=1))
    await _receive(client, w, late, "50", rejected="10", reason="torn bags")
    closed = await client.post(f"/procurement/orders/{late['id']}/close", json={"reason": "Shop out of stock"},
                               headers=w["admin"]["h"])
    assert closed.status_code == 200, closed.text
    third = await _order(client, w, today)
    await _receive(client, w, third, "100")
    return [first, late, third]


async def test_the_score_reads_orders_deliveries_and_rejections(client, world):
    w = world
    await _history(client, w)
    kk = await _vendor_id(client, w, "KK Traders")
    resp = await client.post("/materials/inflows", headers=w["admin"]["h"], json={
        "project_id": str(w["villa"]), "site_id": str(w["block_a"]), "material_id": w["cement"],
        "unit_id": w["units"]["bags"], "quantity": "50", "movement_reason": "RECEIVED",
        "occurred_date": str(company_today()), "unit_cost": "420", "vendor_id": kk})
    assert resp.status_code == 201, resp.text
    malabar = await _vendor_id(client, w, "Malabar Hardware")

    got = await client.get(f"/procurement/rates/suppliers/{malabar}/performance", headers=w["admin"]["h"])
    assert got.status_code == 200, got.text
    p = got.json()
    m = p["measures"]
    assert (p["deliveries"], p["enough"]) == (3, True)
    assert (m["on_time"]["pct"], m["on_time"]["of"]) == ("66.7", 3)  # the late one counts against
    assert (m["complete"]["pct"], m["complete"]["of"]) == ("83.3", 3)  # closed short at 50% counts against
    assert m["rejected"]["pct"] == "5.6"  # 10 of 60 on one GRN line of three
    assert Decimal(m["price"]["index"]) < 1 and m["price"]["items"] == 1  # 400 against the 403.33 average
    assert p["score"] is not None and Decimal("0") < Decimal(p["score"]) < Decimal("5")
    assert p["weights"] == {"on_time": 35, "complete": 20, "quality": 25, "price": 20}
    assert {x["kind"] for x in p["problems"]} == {"late", "rejected", "short"}
    assert len(p["trend"]) == 6 and p["trend"][-1]["score"] is not None

    listed = {i["vendor_id"]: i for i in (await client.get("/procurement/rates/suppliers/performance",
                                                            headers=w["admin"]["h"])).json()["items"]}
    assert listed[malabar]["score"] == p["score"] and listed[malabar]["problems"] == []
    assert listed[kk]["enough"] is False and listed[kk]["score"] is None  # no GRN: not enough orders yet


async def test_manual_rating_once_per_finished_order_by_who_may_close_orders(client, world):
    w = world
    first, late, _ = await _history(client, w)
    opened = await _order(client, w, company_today())
    shown = (await client.get(f"/procurement/orders/{first['id']}", headers=w["admin"]["h"])).json()
    assert shown["may_rate"] is True and shown["rating"] is None
    assert (await client.post(f"/procurement/orders/{first['id']}/rating", json={"stars": 4},
                              headers=w["arun"]["h"])).status_code == 403
    assert (await client.post(f"/procurement/orders/{opened['id']}/rating", json={"stars": 4},
                              headers=w["admin"]["h"])).status_code == 409  # not finished
    ok = await client.post(f"/procurement/orders/{first['id']}/rating", json={"stars": 4, "note": "Good bags"},
                           headers=w["admin"]["h"])
    assert ok.status_code == 201, ok.text
    assert ok.json()["rating"]["stars"] == 4 and ok.json()["may_rate"] is False
    assert (await client.post(f"/procurement/orders/{first['id']}/rating", json={"stars": 5},
                              headers=w["admin"]["h"])).status_code == 409  # once
    skipped = await client.post(f"/procurement/orders/{late['id']}/rating", json={}, headers=w["admin"]["h"])
    assert skipped.status_code == 201 and skipped.json()["may_rate"] is False  # a skip is not asked again
    assert (await client.post(f"/procurement/orders/{first['id']}/rating", json={"stars": 9},
                              headers=w["admin"]["h"])).status_code == 422

    malabar = await _vendor_id(client, w, "Malabar Hardware")
    p = (await client.get(f"/procurement/rates/suppliers/{malabar}/performance", headers=w["admin"]["h"])).json()
    assert p["rating"] == {"stars": "4.0", "count": 1, "last_note": "Good bags"}  # the skip is not a rating


async def test_site_roles_and_other_companies_see_no_performance(client, world, test_engine):
    w = world
    await _history(client, w)
    malabar = await _vendor_id(client, w, "Malabar Hardware")
    assert (await client.get(f"/procurement/rates/suppliers/{malabar}/performance", headers=w["arun"]["h"])).status_code == 403
    other = uuid.uuid4()
    await _exec(test_engine, "INSERT INTO organizations (id, name, deployment_type, db_route, status, created_at, "
                "updated_at) VALUES (:id, 'Other', 'local', 'default', 'active', now(), now())", id=other)
    stranger = await _user(test_engine, other, "admin", "Stranger")
    assert (await client.get(f"/procurement/rates/suppliers/{malabar}/performance", headers=stranger["h"])).status_code == 404
    assert (await client.get("/procurement/rates/suppliers/performance", headers=stranger["h"])).json()["items"] == []
