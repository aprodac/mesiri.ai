"""PRC-04: a delivery's supplier is the company's vendor, as an expense's is (WA-201's one rule).

"KMS-il ninnu cement vannu" from "kms agency" next to the listed "KMS Agencies" holds the delivery with the listed
name, so the API links it to that vendor instead of making a second one. The model never sees ``vendor_id`` (it is
the dashboard's picker). Guards: a new shop stays as said; with the vendor list unreadable the name goes as said.
"""

from __future__ import annotations

import uuid

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel
from tests.agent_api.replaykit import _real_tools
from tests.agent_api.standin import ACTOR, BAG, CEMENT, PROJECT, SITE

from agent_api.agent import ApiAgent
from agent_api.client import ApiClient
from agent_api.tools import ALLOWED, CONFIRM_ARG, build_tools
from mesiri.domains.shared.auth import get_current_user
from mesiri_ai.fakes import FakeToolCallingProvider

VENDORS = [{"id": str(uuid.uuid4()), "name": "KMS Agencies", "status": "active"}]


class Delivery(BaseModel):
    project_id: uuid.UUID
    site_id: uuid.UUID | None = None
    material_id: uuid.UUID
    unit_id: uuid.UUID
    quantity: float
    occurred_date: str
    supplier: str | None = None
    vendor_id: uuid.UUID | None = None


def _app(vendors: list[dict] | None) -> FastAPI:
    app = FastAPI()

    @app.get("/finance/vendors")
    async def list_vendors(jwt: dict = Depends(get_current_user)):
        if vendors is None:
            raise HTTPException(status_code=403, detail="finance module is off")
        return vendors

    @app.get("/materials")
    async def materials(search: str | None = None, jwt: dict = Depends(get_current_user)):
        return {"items": [{"id": CEMENT, "name": "Cement", "default_unit_id": BAG, "aliases": []}], "total": 1}

    @app.post("/materials/inflows", status_code=201)
    async def inflow(body: Delivery, jwt: dict = Depends(get_current_user)):
        return {"id": str(uuid.uuid4())}

    return app


async def _held(supplier: str, vendors: list[dict] | None = VENDORS) -> dict:
    app = _app(vendors)
    tools = build_tools(app.openapi(), tuple(a for a in ALLOWED if a.name in ("record_receipt", "list_vendors")))
    line = ("record_receipt", {"project_id": PROJECT, "site_id": SITE, "material_id": CEMENT, "unit_id": BAG,
                               "quantity": 480, "occurred_date": "2026-11-06", "supplier": supplier,
                               CONFIRM_ARG: f"480 bags cement from {supplier}"})
    client = ApiClient(ACTOR, app=app)
    try:
        turn = await ApiAgent(FakeToolCallingProvider([[line], "Ready."]), tools).run(
            client, f"{supplier}-il ninnu 480 bag cement vannu")
    finally:
        await client.close()
    assert turn.pending, turn.calls
    return turn.pending[0].body


def test_the_model_never_sees_vendor_id_on_the_real_api() -> None:
    tool = _real_tools()["record_receipt"]
    assert "supplier" in tool.body_fields and "vendor_id" not in tool.body_fields


async def test_a_listed_vendor_said_another_way_is_that_vendor() -> None:
    for said in ("kms agency", "KMS AGENCIES", "kms  agencies."):
        assert (await _held(said))["supplier"] == "KMS Agencies", said


async def test_guard_a_new_shop_stays_as_they_said_it() -> None:
    assert (await _held("Sree Traders"))["supplier"] == "Sree Traders"


async def test_guard_the_list_unreadable_leaves_the_name_to_the_api() -> None:
    assert (await _held("kms agency", vendors=None))["supplier"] == "kms agency"


def test_plural_ies_matches_its_singular() -> None:
    from agent_api.materials import name_key

    assert name_key("KMS Agencies") == name_key("kms agency") == "kms agency"
    assert name_key("Malabar Supplies") == name_key("malabar supply")
    assert name_key("Ravi Traders.") == "ravi trader"  # WA-201 unchanged
