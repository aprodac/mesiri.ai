"""PRC-09: orders to suppliers on WhatsApp, through the dashboard's own routes (/procurement/orders).

"Order 200 cement from Malabar at 410" (the office) is a write held for Save, one material per order, the supplier in
their words; "order Arun's cement from KK" orders the site's request (request_id). "What is still to come" only reads.
Guards: the dashboard's lines and vendor picker are never the model's; Mesiri never claims it sent the order.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi import Depends, FastAPI
from pydantic import BaseModel
from tests.agent_api.replaykit import _real_tools
from tests.agent_api.standin import ACTOR, BAG, CEMENT, PROJECT, SITE

from agent_api.agent import ApiAgent
from agent_api.client import ApiClient
from agent_api.record_links import RECORD_PAGES
from agent_api.tools import ALLOWED, CONFIRM_ARG, MATERIAL_SAID, build_tools
from mesiri.domains.shared.auth import get_current_user
from mesiri_ai.fakes import FakeToolCallingProvider

NAMES = ("purchase_orders", "place_order", "change_order", "cancel_order", "close_order")


class Place(BaseModel):
    project_id: uuid.UUID | None = None
    site_id: uuid.UUID | None = None
    supplier: str | None = None
    material_id: uuid.UUID | None = None
    quantity: Decimal | None = None
    unit_id: uuid.UUID | None = None
    rate: Decimal | None = None
    request_id: uuid.UUID | None = None
    expected_date: str | None = None
    their_ref: str | None = None
    confirm_duplicate: bool = False
    lines: list[dict] = []
    vendor_id: uuid.UUID | None = None


def _app(read: list, saved: list) -> FastAPI:
    app = FastAPI()

    @app.get("/materials")
    async def materials(search: str | None = None, jwt: dict = Depends(get_current_user)):
        return {"items": [{"id": CEMENT, "name": "Cement", "default_unit_id": BAG, "aliases": []}], "total": 1}

    @app.get("/procurement/orders")
    async def listing(status: str = "open", jwt: dict = Depends(get_current_user)):
        read.append(status)
        return {"items": [{"ref": "PO-0003", "vendor_name": "Malabar Hardware", "created_by_name": "Meera",
                           "status": "part", "urgency": "late", "lines": [{"material": "Cement", "quantity": "160",
                                                                           "received": "100", "pending": "60"}]}]}

    @app.post("/procurement/orders", status_code=201)
    async def place(body: Place, jwt: dict = Depends(get_current_user)):
        saved.append(body)
        return {"id": str(uuid.uuid4()), "ref": "PO-0004"}

    return app


async def _turn(script: list, text: str):  # noqa: ANN202
    read: list = []
    saved: list = []
    app = _app(read, saved)
    tools = build_tools(app.openapi(), tuple(a for a in ALLOWED if a.name in ("purchase_orders", "place_order",
                                                                              "search_materials")))
    client = ApiClient(ACTOR, app=app)
    try:
        return await ApiAgent(FakeToolCallingProvider(script), tools).run(client, text), read, saved
    finally:
        await client.close()


def test_the_order_tools_are_the_dashboards_routes() -> None:
    tools = _real_tools()
    assert {n: (tools[n].method, tools[n].path) for n in NAMES} == {
        "purchase_orders": ("GET", "/procurement/orders"),
        "place_order": ("POST", "/procurement/orders"),
        "change_order": ("PATCH", "/procurement/orders/{order_id}"),
        "cancel_order": ("POST", "/procurement/orders/{order_id}/cancel"),
        "close_order": ("POST", "/procurement/orders/{order_id}/close"),
    }
    place = tools["place_order"]
    assert {"material_id", "quantity", "unit_id", "rate", "supplier", "request_id", "their_ref",
            "confirm_duplicate"} <= set(place.body_fields)
    assert not {"lines", "vendor_id"} & set(place.body_fields)
    assert MATERIAL_SAID in place.spec.parameters["properties"]  # the material word is checked, as every line
    assert all(RECORD_PAGES[n] == "purchase_orders" for n in NAMES[1:])


async def test_order_200_cement_from_malabar_is_held_for_save() -> None:
    line = ("place_order", {"project_id": PROJECT, "site_id": SITE, "supplier": "Malabar Hardware",
                            "material_id": CEMENT, "unit_id": BAG, "quantity": 200, "rate": 410,
                            MATERIAL_SAID: "cement", CONFIRM_ARG: "Order 200 bags cement from Malabar Hardware, ₹410"})
    turn, _, saved = await _turn([[line], "Ready: order 200 bags cement from Malabar at ₹410."],
                                 "200 bag cement Malabar-il order cheythu, 410 rate")
    assert saved == []
    assert [(p.tool, p.method, p.path) for p in turn.pending] == [("place_order", "POST", "/procurement/orders")]
    body = turn.pending[0].body
    assert (body["supplier"], body["quantity"], body["rate"]) == ("Malabar Hardware", 200, 410)


async def test_ordering_a_request_names_only_the_request_and_supplier() -> None:
    request_id = str(uuid.uuid4())
    line = ("place_order", {"request_id": request_id, "supplier": "KK Traders",
                            CONFIRM_ARG: "Order REQ-0007 from KK Traders"})
    turn, _, _ = await _turn([[line], "Ready: REQ-0007 from KK Traders."], "Arun-nte cement KK-il order cheyyu")
    assert turn.pending[0].body == {"request_id": request_id, "supplier": "KK Traders"}


async def test_guard_what_is_still_to_come_only_reads() -> None:
    turn, read, saved = await _turn([[("purchase_orders", {})], "PO-0003 Malabar: 60 bags cement still to come, late."],
                                    "what is still to come?")
    assert read == ["open"] and turn.pending == [] and saved == []


def test_the_sop_keeps_orders_and_deliveries_apart_and_never_claims_sending() -> None:
    from pathlib import Path

    import agent_api

    sop = (Path(agent_api.__file__).parent / "SOP.md").read_text()
    assert "is `place_order`" in sop and "never say it was sent" in sop
    assert "Material that CAME is still `record_receipt`, never an order" in sop
    assert "\"What is still to come\"" in sop and "`purchase_orders`" in sop
