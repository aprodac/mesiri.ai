"""PRC-32 (7 Nov 22:26, WhatsApp check): "REQ-0001 cement athu 250 aakku" held change_material_request with request_id
"REQ-0001" (the number people see). The card said Save; the Save failed (422, "Input should be a valid UUID").

Root cause: a write's path id went into the URL unchecked; only the API at Save could refuse it, after the person was
told to tap Save. Class: every write whose path takes a record's id (requests, orders, issues, receipts, expenses, work,
materials, sites ...). Fix: when a line is prepared, a path param the API declares as a UUID must be one; otherwise the
model is told to look the record up and prepare it again, in the same turn.

Guards: a real id goes through unchanged; a read is not stopped (its error comes back at once anyway).
"""

from __future__ import annotations

import uuid

from fastapi import Depends, FastAPI
from pydantic import BaseModel
from tests.agent_api.standin import ACTOR

from agent_api.agent import ApiAgent
from agent_api.client import ApiClient
from agent_api.tools import ALLOWED, CONFIRM_ARG, build_tools
from mesiri.domains.shared.auth import get_current_user
from mesiri_ai.fakes import FakeToolCallingProvider

REQ = str(uuid.uuid4())
ORDER = str(uuid.uuid4())
NAMES = ("material_requests", "change_material_request", "change_order", "work_item")


class Change(BaseModel):
    quantity: float | None = None
    needed_by: str | None = None


class OrderChange(BaseModel):
    expected_date: str | None = None


def _app(seen: list) -> FastAPI:
    app = FastAPI()

    @app.get("/procurement/requests")
    async def listing(status: str = "waiting", mine: bool = False, jwt: dict = Depends(get_current_user)):
        seen.append("list")
        return {"items": [{"id": REQ, "ref": "REQ-0001", "status": "waiting"}], "counts": {"waiting": 1}}

    @app.patch("/procurement/requests/{request_id}")
    async def change(request_id: uuid.UUID, body: Change, jwt: dict = Depends(get_current_user)):
        return {"id": str(request_id)}

    @app.patch("/procurement/orders/{order_id}")
    async def change_order(order_id: uuid.UUID, body: OrderChange, jwt: dict = Depends(get_current_user)):
        return {"id": str(order_id)}

    @app.get("/progress/activities/{activity_id}")
    async def work(activity_id: str, jwt: dict = Depends(get_current_user)):
        seen.append(f"work:{activity_id}")
        return {"id": activity_id}

    return app


async def _turn(script: list, text: str):  # noqa: ANN202
    seen: list = []
    app = _app(seen)
    tools = build_tools(app.openapi(), tuple(a for a in ALLOWED if a.name in NAMES))
    client = ApiClient(ACTOR, app=app)
    try:
        return await ApiAgent(FakeToolCallingProvider(script), tools).run(client, text), seen
    finally:
        await client.close()


def test_the_tools_know_which_path_ids_are_uuids() -> None:
    tools = build_tools(_app([]).openapi(), tuple(a for a in ALLOWED if a.name in NAMES))
    assert tools["change_material_request"].uuid_path == ("request_id",)
    assert tools["change_order"].uuid_path == ("order_id",)
    assert tools["work_item"].uuid_path == ()  # declared a plain string: never checked


async def test_a_request_named_by_its_number_is_looked_up_before_the_card() -> None:
    by_ref = ("change_material_request", {"request_id": "REQ-0001", "quantity": 250, CONFIRM_ARG: "REQ-0001: 250 bags"})
    by_id = ("change_material_request", {"request_id": REQ, "quantity": 250, CONFIRM_ARG: "REQ-0001: 250 bags"})
    turn, seen = await _turn([[by_ref], [("material_requests", {"mine": True})], [by_id], "Ready: REQ-0001 250 bags."],
                             "REQ-0001 cement athu 250 aakku")
    refused = turn.calls[0]
    assert "error" in refused["result"] and "REQ-0001" in refused["result"]["error"]
    assert seen == ["list"]  # the model looked it up in the same turn
    assert [p.path for p in turn.pending] == [f"/procurement/requests/{REQ}"]  # the card holds the real id only


async def test_sibling_an_order_by_its_po_number_is_refused_when_prepared() -> None:
    by_ref = ("change_order", {"order_id": "PO-0003", "expected_date": "2026-11-13", CONFIRM_ARG: "PO-0003 Friday"})
    turn, _ = await _turn([[by_ref], "Ok."], "PO-0003 Friday-lekku maattu")
    assert "error" in turn.calls[0]["result"] and turn.pending == []


async def test_guard_a_real_id_goes_through_and_a_read_is_not_stopped() -> None:
    line = ("change_order", {"order_id": ORDER, "expected_date": "2026-11-13", CONFIRM_ARG: "PO-0003 Friday"})
    turn, seen = await _turn([[line, ("work_item", {"activity_id": "W-12"})], "Ready."], "PO-0003 Friday-lekku maattu")
    assert [p.path for p in turn.pending] == [f"/procurement/orders/{ORDER}"]
    assert "work:W-12" in seen
