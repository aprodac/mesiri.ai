"""PRC-46: returns to a supplier on WhatsApp -- the Returns page's own routes as tools.

"12 steel bars bent, returning to KSL" holds a return (supplier in words, ``vendor_id`` and photos hidden, source
fixed to whatsapp), never a use or a delivery. Sibling: "KSL gave credit for DN-0003" holds a settle on the return
said by its number (PRC-32's rule, no new code). Guards: the tools exist on the real API with the fields the model
fills; the SOP keeps a return apart from a use and a delivery.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import Depends, FastAPI
from pydantic import BaseModel
from tests.agent_api.replaykit import _real_tools
from tests.agent_api.standin import ACTOR, SITE

from agent_api.agent import ApiAgent
from agent_api.client import ApiClient
from agent_api.tools import ALLOWED, CONFIRM_ARG, build_tools
from mesiri.domains.shared.auth import get_current_user
from mesiri_ai.fakes import FakeToolCallingProvider

TMT = str(uuid.uuid4())
DN = str(uuid.uuid4())


class Line(BaseModel):
    material_id: str
    quantity: float
    unit_id: str | None = None
    reason: str


class Return(BaseModel):
    supplier: str | None = None
    vendor_id: str | None = None
    site_id: str | None = None
    lines: list[Line]
    source: str = "web"


class Settle(BaseModel):
    how: str
    note: str | None = None


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/procurement/returns")
    async def returns(status: str | None = None, jwt: dict = Depends(get_current_user)):
        return {"items": [{"id": DN, "number": 3, "ref": "DN-0003"}, {"id": str(uuid.uuid4()), "number": 4,
                                                                       "ref": "DN-0004"}], "total": 2}

    @app.post("/procurement/returns", status_code=201)
    async def create(body: Return, jwt: dict = Depends(get_current_user)):
        return {"id": str(uuid.uuid4()), "ref": "DN-0005"}

    @app.post("/procurement/returns/{return_id}/settle")
    async def settle(return_id: uuid.UUID, body: Settle, jwt: dict = Depends(get_current_user)):
        return {"id": str(return_id)}

    return app


async def _held(tool: str, args: dict, said: str):
    app = _app()
    tools = build_tools(app.openapi(), tuple(a for a in ALLOWED if a.name in ("returns", tool)))
    client = ApiClient(ACTOR, app=app)
    try:
        turn = await ApiAgent(FakeToolCallingProvider([[(tool, {**args, CONFIRM_ARG: said})], "Ready."]), tools).run(
            client, said)
    finally:
        await client.close()
    assert turn.pending, turn.calls
    return turn.pending[0]


async def test_bent_bars_going_back_to_ksl_holds_a_return() -> None:
    held = await _held("return_to_supplier", {"supplier": "KSL", "site_id": SITE,
                                              "lines": [{"material_id": TMT, "quantity": 12, "reason": "damaged"}]},
                       "12 steel bars bent, returning to KSL")
    assert (held.method, held.path) == ("POST", "/procurement/returns")
    assert held.body["source"] == "whatsapp" and held.body["supplier"] == "KSL" and "vendor_id" not in held.body
    assert held.body["lines"][0]["reason"] == "damaged"


async def test_sibling_credit_for_a_debit_note_said_by_its_number() -> None:
    held = await _held("settle_return", {"return_id": "DN-0003", "how": "credit", "note": "less on the bill"},
                       "KSL gave credit for DN-0003 on the bill")
    assert held.path == f"/procurement/returns/{DN}/settle" and held.body["how"] == "credit"


def test_the_return_tools_are_on_the_real_api() -> None:
    tools = _real_tools()
    assert {"returns", "return_to_supplier", "settle_return"} <= set(tools)
    write = tools["return_to_supplier"]
    assert {"supplier", "site_id", "lines", "returned_on", "notes"} <= set(write.body_fields)
    assert not {"vendor_id", "photos", "source"} & set(write.body_fields)
    assert {"how", "receipt_id", "expense_id", "note"} <= set(tools["settle_return"].body_fields)


def test_guard_a_return_is_never_a_use_or_a_delivery() -> None:
    sop = (Path(__file__).resolve().parents[2] / "src" / "agent_api" / "SOP.md").read_text(encoding="utf-8")
    assert "`return_to_supplier` with the" in sop and "Never `record_usage` and never a delivery" in sop
