"""WA-201 (basic 5, "never create a duplicate"; Ilan, 5 Nov: "do it"). The API matches an expense's vendor by its
exact name (case aside) and makes a new vendor otherwise, so "ravi trader." next to the listed "Ravi Traders" became a
second vendor and the spend split between them. Now the assistant reads the vendor list (``list_vendors``, the
dashboard's own route) and an expense names a listed vendor as it is listed. The backend's matching is unchanged
(shared by the dashboard and the materials invoices).
"""

from __future__ import annotations

import uuid

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel
from tests.agent_api.standin import ACTOR, PROJECT, SITE

from agent_api.agent import ApiAgent
from agent_api.client import ApiClient
from agent_api.materials import known_vendor, name_key
from agent_api.tools import ALLOWED, CONFIRM_ARG, build_tools
from mesiri.domains.shared.auth import get_current_user
from mesiri_ai.fakes import FakeToolCallingProvider

VENDORS = [{"id": str(uuid.uuid4()), "name": "Ravi Traders", "status": "active"},
           {"id": str(uuid.uuid4()), "name": "Old Shop", "status": "inactive"}]


class Expense(BaseModel):
    project_id: uuid.UUID
    amount: float
    occurred_date: str
    site_id: uuid.UUID | None = None
    vendor_text: str | None = None
    category_text: str | None = None
    description: str | None = None
    source: str = "web"


def _app(vendors: list[dict] | None = VENDORS) -> FastAPI:
    app = FastAPI()

    @app.get("/finance/vendors")
    async def list_vendors(jwt: dict = Depends(get_current_user)):
        if vendors is None:
            raise HTTPException(status_code=403, detail="finance module is off")
        return vendors

    @app.post("/expenses", status_code=201)
    async def expense(body: Expense, jwt: dict = Depends(get_current_user)):
        return {"id": str(uuid.uuid4())}

    return app


def _expense(vendor: str) -> tuple[str, dict]:
    return ("record_expense", {"project_id": PROJECT, "site_id": SITE, "amount": 4500, "occurred_date": "2026-11-05",
                               "vendor_text": vendor, "category_text": "Hardware", CONFIRM_ARG: f"₹4500 {vendor}"})


async def _held(vendor: str, vendors: list[dict] | None = VENDORS) -> dict:
    app = _app(vendors)
    tools = build_tools(app.openapi(), tuple(a for a in ALLOWED if a.name in ("record_expense", "list_vendors")))
    client = ApiClient(ACTOR, app=app)
    try:
        turn = await ApiAgent(FakeToolCallingProvider([[_expense(vendor)], "Ready."]), tools).run(
            client, f"{vendor} 4500 hardware")
    finally:
        await client.close()
    return turn.pending[0].body


async def test_a_listed_vendor_said_another_way_is_that_vendor() -> None:
    for said in ("ravi trader.", "RAVI TRADERS", "Ravi  Traders", "ravi traders"):
        assert (await _held(said))["vendor_text"] == "Ravi Traders", said


async def test_guard_a_new_vendor_stays_as_they_said_it() -> None:
    assert (await _held("Kumar Hardware"))["vendor_text"] == "Kumar Hardware"


async def test_guard_an_inactive_vendor_is_not_brought_back() -> None:
    assert (await _held("old shop"))["vendor_text"] == "old shop"


async def test_guard_the_list_unreadable_leaves_the_name_to_the_api() -> None:
    assert (await _held("ravi trader", vendors=None))["vendor_text"] == "ravi trader"


def test_the_name_key() -> None:
    assert name_key("Ravi Traders.") == name_key("ravi  trader") == "ravi trader"
    assert name_key("Glass House") == name_key("glass house")
    assert name_key("Ravi Traders") != name_key("Ravi Steels")


async def test_known_vendor_reads_the_list() -> None:
    client = ApiClient(ACTOR, app=_app())
    try:
        assert await known_vendor(client, "ravi trader") == "Ravi Traders"
        assert await known_vendor(client, "") == ""
    finally:
        await client.close()
