"""PRC-22: "need 200 bags cement by tomorrow" on WhatsApp is a material request (Materials > Requests), not a receipt.

The tools are the dashboard's own routes (/procurement/requests). Asking is a write held for the person's Save, sent
as from WhatsApp, one material per request (the flat form, so the material and unit checks of every material line
apply). Guards: a question about requests only reads; the dashboard's ``lines`` and ``source`` are never the model's.
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
from agent_api.tools import ALLOWED, CONFIRM_ARG, MATERIAL_SAID, build_tools
from mesiri.domains.shared.auth import get_current_user
from mesiri_ai.fakes import FakeToolCallingProvider

NAMES = ("material_requests", "ask_for_material", "decide_material_request", "cancel_material_request")


class Ask(BaseModel):
    project_id: uuid.UUID
    site_id: uuid.UUID
    material_id: uuid.UUID | None = None
    quantity: Decimal | None = None
    unit_id: uuid.UUID | None = None
    needed_by: str | None = None
    purpose: str | None = None
    source: str = "dashboard"
    confirm_duplicate: bool = False
    lines: list[dict] = []


def _app(asked: list, saved: list) -> FastAPI:
    app = FastAPI()

    @app.get("/materials")
    async def materials(search: str | None = None, jwt: dict = Depends(get_current_user)):
        return {"items": [{"id": CEMENT, "name": "Cement", "default_unit_id": BAG, "aliases": []}], "total": 1}

    @app.get("/procurement/requests")
    async def listing(status: str = "waiting", mine: bool = False, jwt: dict = Depends(get_current_user)):
        asked.append({"status": status, "mine": mine})
        return {"items": [{"ref": "REQ-0007", "status": "waiting", "lines": [{"material": "Cement", "quantity": "200",
                                                                              "unit": "bags", "to_buy": "160"}]}],
                "counts": {"waiting": 1}}

    @app.post("/procurement/requests", status_code=201)
    async def ask(body: Ask, jwt: dict = Depends(get_current_user)):
        saved.append(body)
        return {"id": str(uuid.uuid4()), "ref": "REQ-0008"}

    return app


async def _turn(script: list, text: str):  # noqa: ANN202
    asked: list = []
    saved: list = []
    app = _app(asked, saved)
    tools = build_tools(app.openapi(), tuple(a for a in ALLOWED if a.name in (*NAMES[:2], "search_materials")))
    client = ApiClient(ACTOR, app=app)
    try:
        return await ApiAgent(FakeToolCallingProvider(script), tools).run(client, text), asked, saved
    finally:
        await client.close()


def test_the_request_tools_are_the_dashboards_routes() -> None:
    tools = _real_tools()
    assert {n: (tools[n].method, tools[n].path) for n in NAMES} == {
        "material_requests": ("GET", "/procurement/requests"),
        "ask_for_material": ("POST", "/procurement/requests"),
        "decide_material_request": ("POST", "/procurement/requests/{request_id}/decide"),
        "cancel_material_request": ("POST", "/procurement/requests/{request_id}/cancel"),
    }
    ask = tools["ask_for_material"]
    assert ask.is_write and not tools["material_requests"].is_write
    # One material per request, as flat fields: the model never builds the dashboard's lines, nor says the source.
    assert {"material_id", "quantity", "unit_id", "needed_by", "confirm_duplicate"} <= set(ask.body_fields)
    assert "lines" not in ask.body_fields and "source" not in ask.body_fields
    assert dict(ask.fixed) == {"source": "whatsapp"}
    assert MATERIAL_SAID in ask.spec.parameters["properties"]  # [210]: their word for it is checked


async def test_needing_cement_prepares_a_request_held_for_save() -> None:
    line = ("ask_for_material", {"project_id": PROJECT, "site_id": SITE, "material_id": CEMENT, "unit_id": BAG,
                                 "quantity": 200, "needed_by": "2026-11-08", "purpose": "slab",
                                 MATERIAL_SAID: "cement", CONFIRM_ARG: "Need 200 bags cement by tomorrow"})
    turn, _, saved = await _turn([[line], "Ready: 200 bags cement, needed tomorrow."], "200 bag cement venam nale, slab")
    assert saved == []  # nothing goes to the office until they tap Save
    assert [(p.tool, p.method, p.path) for p in turn.pending] == [("ask_for_material", "POST", "/procurement/requests")]
    body = turn.pending[0].body
    assert (body["material_id"], body["quantity"], body["needed_by"]) == (CEMENT, 200, "2026-11-08")


async def test_guard_asking_what_was_requested_only_reads() -> None:
    turn, asked, saved = await _turn([[("material_requests", {"mine": True})], "REQ-0007: 200 bags cement, waiting."],
                                     "what did I ask for?")
    assert asked == [{"status": "waiting", "mine": True}]
    assert turn.pending == [] and saved == []


def test_the_sop_says_a_need_is_a_request_not_a_receipt() -> None:
    from pathlib import Path

    import agent_api

    sop = (Path(agent_api.__file__).parent / "SOP.md").read_text()
    assert "Material a site NEEDS" in sop and "`ask_for_material`, one per material, never a receipt" in sop


def test_a_bare_my_requests_lists_both_kinds() -> None:
    """PRC-32 / [283] (7 Nov 22:14): "show my requests" listed only what was asked of Mesiri's team, never the material
    requests just made. Bare, it is both lists; with material words it is material_requests; complaints stay
    my_requests (guard for [230])."""
    from pathlib import Path

    import agent_api

    sop = (Path(agent_api.__file__).parent / "SOP.md").read_text()
    assert 'a bare "my requests" / "ente requests" is BOTH lists, material ones first' in sop
    assert '"ente complaints kaanikku" / "is it fixed", call\n   `my_requests`' in sop
