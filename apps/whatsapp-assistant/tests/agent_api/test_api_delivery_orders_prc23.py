"""PRC-23: a delivery saved on WhatsApp and the purchase orders at its site.

The API decides (``record_inflow``): a delivery fills the one open order it plainly belongs to, and otherwise offers
the open ones. The saved line says which (code-drawn, in their language). "It's PO-0002" puts a saved delivery on
that order through the dashboard's own route (``delivery_order``), held for Save. Guards: a plain delivery reads as
before; the order line and the extra-confirmation stay the API's, never the model's.
"""

from __future__ import annotations

import uuid

from fastapi import Depends, FastAPI
from pydantic import BaseModel
from tests.agent_api.replaykit import _real_tools
from tests.agent_api.standin import ACTOR

from agent_api.agent import ApiAgent, PendingWrite, WriteResult
from agent_api.client import ApiClient
from agent_api.tools import ALLOWED, CONFIRM_ARG, build_tools
from agent_api.whatsapp import _saved_text, order_note
from mesiri.domains.shared.auth import get_current_user
from mesiri_ai.fakes import FakeToolCallingProvider

RECEIPT = str(uuid.uuid4())


def _receipt(summary: str = "50 bags Cement came at Block A") -> PendingWrite:
    return PendingWrite(tool="record_receipt", method="POST", path="/materials/inflows", params={},
                        body={"material_id": str(uuid.uuid4())}, summary=summary, idempotency_key="k")


ON_ORDER = {"id": RECEIPT, "status": "success", "order": {
    "ref": "PO-0003", "vendor_name": "Malabar Hardware", "received": "150", "quantity": "160", "unit": "bags"}}
OFFERED = {"id": RECEIPT, "status": "success", "open_orders": [
    {"ref": "PO-0003", "vendor_name": "Malabar Hardware", "pending": "100", "unit": "bags", "line_id": "x"},
    {"ref": "PO-0004", "vendor_name": "KK Traders", "pending": "50", "unit": "bags", "line_id": "y"}]}


def test_the_delivery_order_tool_is_the_dashboards_route() -> None:
    tools = _real_tools()
    put = tools["delivery_order"]
    assert (put.method, put.path, put.is_write) == ("POST", "/procurement/orders/deliveries/{receipt_id}/order", True)
    assert {"order", "line_id", "confirm_extra"} <= set(put.body_fields)
    receipt = tools["record_receipt"]
    # The code matches the order; the model only says "not from any order".
    assert "no_order" in receipt.body_fields
    assert not {"purchase_order_line_id", "confirm_extra", "vendor_id"} & set(receipt.body_fields)


def test_the_saved_delivery_says_the_order_it_filled() -> None:
    text = _saved_text([WriteResult(_receipt(), 201, ON_ORDER)], None)
    assert "✅ 50 bags Cement came at Block A\n📦 On PO-0003 (Malabar Hardware): 150 of 160 bags came" in text
    assert "PO-0003 (Malabar Hardware): 160-il 150 bags vannu" in _saved_text(
        [WriteResult(_receipt(), 201, ON_ORDER)], "manglish")


def test_open_orders_are_offered_never_filled_silently() -> None:
    text = _saved_text([WriteResult(_receipt(), 201, OFFERED)], None)
    assert ("📦 Not put on an order: PO-0003 (Malabar Hardware, 100 bags), PO-0004 (KK Traders, 50 bags) still to "
            "come here.") in text
    assert "ഓർഡറിൽ ചേർത്തില്ല" in order_note(WriteResult(_receipt(), 201, OFFERED), "malayalam")


def test_guard_a_plain_delivery_reads_as_before() -> None:
    plain = WriteResult(_receipt(), 201, {"id": RECEIPT, "status": "success"})
    assert order_note(plain, None) == ""
    assert _saved_text([plain], None) == "Saved.\n✅ 50 bags Cement came at Block A"
    refused = WriteResult(_receipt(), 409, {"detail": "x", "order": ON_ORDER["order"]})
    assert order_note(refused, None) == ""  # only a saved delivery speaks of its order


class Put(BaseModel):
    line_id: uuid.UUID | None = None
    order: str | None = None
    confirm_extra: bool = False


async def test_its_po_0004_prepares_putting_the_delivery_on_that_order() -> None:
    app = FastAPI()
    saved: list = []

    @app.post("/procurement/orders/deliveries/{receipt_id}/order")
    async def put(receipt_id: uuid.UUID, body: Put, jwt: dict = Depends(get_current_user)):
        saved.append(body)
        return {"id": str(receipt_id)}

    tools = build_tools(app.openapi(), tuple(a for a in ALLOWED if a.name == "delivery_order"))
    client = ApiClient(ACTOR, app=app)
    line = ("delivery_order", {"receipt_id": RECEIPT, "order": "PO-0004",
                               CONFIRM_ARG: "Count the 50 bags cement against PO-0004 (KK Traders)"})
    try:
        turn = await ApiAgent(FakeToolCallingProvider([[line], "Ready: count it against PO-0004."]), tools).run(
            client, "athu KK-nte order aanu, PO-0004")
    finally:
        await client.close()
    assert saved == []  # held for Save, like every write
    assert [(p.tool, p.path) for p in turn.pending] == [
        ("delivery_order", f"/procurement/orders/deliveries/{RECEIPT}/order")]
    assert turn.pending[0].body["order"] == "PO-0004"


def test_the_sop_says_how_a_delivery_meets_its_order() -> None:
    from pathlib import Path

    import agent_api

    sop = (Path(agent_api.__file__).parent / "SOP.md").read_text()
    assert "prepare `delivery_order` with that order number" in sop and "`no_order` on the receipt" in sop


# --- PRC-31: a waiting request is changed, never asked again ----------------------------------------------------------


def test_changing_a_request_is_the_dashboards_route() -> None:
    tools = _real_tools()
    change = tools["change_material_request"]
    assert (change.method, change.path, change.is_write) == ("PATCH", "/procurement/requests/{request_id}", True)
    assert {"quantity", "unit_id", "needed_by", "purpose"} <= set(change.body_fields)
    assert "lines" not in change.body_fields  # the flat one-item form, as asking


class Change(BaseModel):
    quantity: str | None = None
    unit_id: uuid.UUID | None = None
    needed_by: str | None = None


async def test_make_it_900_prepares_a_change_held_for_save() -> None:
    app = FastAPI()
    saved: list = []
    request_id = str(uuid.uuid4())

    @app.patch("/procurement/requests/{request_id}")
    async def change(request_id: uuid.UUID, body: Change, jwt: dict = Depends(get_current_user)):
        saved.append(body)
        return {"id": str(request_id)}

    tools = build_tools(app.openapi(), tuple(a for a in ALLOWED if a.name == "change_material_request"))
    client = ApiClient(ACTOR, app=app)
    line = ("change_material_request", {"request_id": request_id, "needed_by": "2026-11-13",
                                        CONFIRM_ARG: "REQ-0002: needed by Fri 13 Nov"})
    try:
        turn = await ApiAgent(FakeToolCallingProvider([[line], "Ready: REQ-0002 needed Friday."]), tools).run(
            client, "TMT venda innu, Friday mathi")
    finally:
        await client.close()
    assert saved == []
    assert [(p.tool, p.method) for p in turn.pending] == [("change_material_request", "PATCH")]
    assert turn.pending[0].body == {"needed_by": "2026-11-13"}


def test_the_sop_says_a_change_is_not_a_new_request() -> None:
    from pathlib import Path

    import agent_api

    sop = (Path(agent_api.__file__).parent / "SOP.md").read_text()
    assert "is `change_material_request`, never a new request" in sop
