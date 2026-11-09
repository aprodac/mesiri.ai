"""PRC-44: quotations on WhatsApp -- the dashboard's own RFQ routes as tools.

"Malabar quoted 395 for RFQ-0001" holds a quote on that RFQ: the code finds RFQ-0001 by its number from the RFQ list
(PRC-32's rule, no new code), the supplier goes in words (``vendor_id`` hidden) and the source is fixed to whatsapp.
Sibling: "order the cheapest" holds an award on the RFQ said by its number. Guards: the tools exist on the real API
with the fields the model must fill; the SOP says a quoted rate is never a delivery.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import Depends, FastAPI
from pydantic import BaseModel
from tests.agent_api.replaykit import _real_tools
from tests.agent_api.standin import ACTOR, CEMENT

from agent_api.agent import ApiAgent
from agent_api.client import ApiClient
from agent_api.tools import ALLOWED, CONFIRM_ARG, build_tools
from mesiri.domains.shared.auth import get_current_user
from mesiri_ai.fakes import FakeToolCallingProvider

RFQ = str(uuid.uuid4())


class Line(BaseModel):
    material_id: str
    rate: float


class Quote(BaseModel):
    supplier: str | None = None
    vendor_id: str | None = None
    lines: list[Line]
    source: str = "web"


class Award(BaseModel):
    mode: str = "picks"


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/procurement/rfqs")
    async def rfqs(status: str | None = None, jwt: dict = Depends(get_current_user)):
        return {"items": [{"id": RFQ, "number": 1, "ref": "RFQ-0001"},
                          {"id": str(uuid.uuid4()), "number": 2, "ref": "RFQ-0002"}], "total": 2}

    @app.post("/procurement/rfqs/{rfq_id}/quotes", status_code=201)
    async def quote(rfq_id: uuid.UUID, body: Quote, jwt: dict = Depends(get_current_user)):
        return {"id": str(rfq_id)}

    @app.post("/procurement/rfqs/{rfq_id}/award", status_code=201)
    async def award(rfq_id: uuid.UUID, body: Award, jwt: dict = Depends(get_current_user)):
        return {"id": str(rfq_id)}

    return app


async def _held(tool: str, args: dict, said: str):
    app = _app()
    tools = build_tools(app.openapi(), tuple(a for a in ALLOWED if a.name in ("rfqs", tool)))
    client = ApiClient(ACTOR, app=app)
    try:
        turn = await ApiAgent(FakeToolCallingProvider([[(tool, {**args, CONFIRM_ARG: said})], "Ready."]), tools).run(
            client, said)
    finally:
        await client.close()
    assert turn.pending, turn.calls
    return turn.pending[0]


async def test_a_quote_said_against_an_rfq_number_goes_on_that_rfq() -> None:
    held = await _held("record_quote", {"rfq_id": "RFQ-0001", "supplier": "Malabar",
                                        "lines": [{"material_id": CEMENT, "rate": 395}]},
                       "Malabar quoted 395 for RFQ-0001 cement")
    assert held.path == f"/procurement/rfqs/{RFQ}/quotes"
    assert held.body["source"] == "whatsapp" and held.body["supplier"] == "Malabar" and "vendor_id" not in held.body


async def test_sibling_order_the_cheapest_on_an_rfq_by_number() -> None:
    held = await _held("award_quotes", {"rfq_id": "rfq 1", "mode": "lowest_per_line"}, "RFQ 1 cheapest order cheyyu")
    assert held.path == f"/procurement/rfqs/{RFQ}/award" and held.body["mode"] == "lowest_per_line"


def test_the_quotation_tools_are_on_the_real_api() -> None:
    tools = _real_tools()
    assert {"rfqs", "rfq", "ask_for_quotes", "record_quote", "decline_quote", "award_quotes"} <= set(tools)
    assert "vendor_id" not in tools["record_quote"].body_fields and "source" not in tools["record_quote"].body_fields
    assert {"lines", "request_id", "suppliers", "due_date"} <= set(tools["ask_for_quotes"].body_fields)
    assert "vendor_ids" not in tools["ask_for_quotes"].body_fields
    assert {"mode", "picks", "reason", "confirm_duplicate"} <= set(tools["award_quotes"].body_fields)


def test_guard_the_sop_never_takes_a_quoted_rate_for_a_delivery() -> None:
    sop = (Path(__file__).resolve().parents[2] / "src" / "agent_api" / "SOP.md").read_text(encoding="utf-8")
    assert "is `record_quote` on that RFQ" in sop and "never a delivery" in sop
