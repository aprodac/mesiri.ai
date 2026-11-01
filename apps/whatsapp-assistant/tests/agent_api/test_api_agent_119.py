"""WA-119: the API agent pilot.

1. The tools come from the real app's OpenAPI: every allowed route exists,
   the schemas are provider-safe, the write tools carry the API's required fields.
2. A turn through a scripted model: reads hit the API as the sender, writes are
   held (nothing is POSTed) until ``confirm``, which sends each once with an
   Idempotency-Key.
3. Guards: an unknown tool, a write missing a field, and a call without the
   sender's token are refused.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

import pytest
from fastapi import Depends, FastAPI, Header
from pydantic import BaseModel

from agent_api.agent import ApiAgent, confirm
from agent_api.client import Actor, ApiClient, token_for
from agent_api.tools import ALLOWED, SUMMARY_ARG, Allowed, ToolBuildError, build_tools
from mesiri.domains.shared.auth import get_current_user
from mesiri_ai.fakes import FakeToolCallingProvider

ORG = str(uuid.uuid4())
USER = str(uuid.uuid4())
PROJECT = str(uuid.uuid4())
SITE = str(uuid.uuid4())
CEMENT = str(uuid.uuid4())
TMT = str(uuid.uuid4())
BAG = str(uuid.uuid4())
NOS = str(uuid.uuid4())


# -- 1. tools from the real app ---------------------------------------------------------


@pytest.fixture(scope="module")
def real_openapi() -> dict:
    logging.disable(logging.CRITICAL)
    try:
        from runtime.dependencies import Settings
        from runtime.lifecycle import create_app

        return create_app(Settings(verify_token="x", app_secret="x", access_token="x")).openapi()
    finally:
        logging.disable(logging.NOTSET)


def test_every_allowed_route_is_in_the_real_api(real_openapi: dict) -> None:
    tools = build_tools(real_openapi)
    assert set(tools) == {a.name for a in ALLOWED}


def test_schemas_are_provider_safe(real_openapi: dict) -> None:
    def walk(node: Any) -> None:
        if isinstance(node, dict):
            assert not {"$ref", "anyOf", "oneOf", "title"} & set(node), node
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    for tool in build_tools(real_openapi).values():
        walk(tool.spec.parameters)


def test_write_tools_carry_the_apis_required_fields(real_openapi: dict) -> None:
    tools = build_tools(real_openapi)
    receipt = tools["record_receipt"]
    assert receipt.is_write and receipt.method == "POST"
    for name in ("project_id", "material_id", "unit_id", "quantity", "occurred_date", SUMMARY_ARG):
        assert name in receipt.required
    assert "supplier" in receipt.spec.parameters["properties"]
    transfer = tools["record_transfer"]
    assert {"from_site_id", "to_site_id"} <= set(transfer.required)
    sites = tools["list_sites"]
    assert not sites.is_write and sites.path_params == ("project_id",)
    assert SUMMARY_ARG not in sites.spec.parameters["properties"]


def test_a_route_missing_from_the_api_fails_the_build(real_openapi: dict) -> None:
    with pytest.raises(ToolBuildError):
        build_tools(real_openapi, (Allowed("gone", "GET", "/materials/no-such-route", "x"),))


# -- 2. a turn against a stand-in API (same auth dependency as the real one) ------------


class Inflow(BaseModel):
    project_id: uuid.UUID
    site_id: uuid.UUID | None = None
    material_id: uuid.UUID
    unit_id: uuid.UUID
    quantity: float
    occurred_date: str
    supplier: str | None = None


def stand_in_api(seen: list[tuple[str, str, dict, str | None]]) -> FastAPI:
    """The pilot's routes, answering like the real ones, behind the real ``get_current_user``."""
    app = FastAPI()

    def note(method: str, path: str, jwt: dict, key: str | None = None) -> None:
        seen.append((method, path, jwt, key))

    @app.get("/projects")
    async def projects(jwt: dict = Depends(get_current_user)):
        note("GET", "/projects", jwt)
        return [{"id": PROJECT, "name": "Green Villa"}]

    @app.get("/projects/{project_id}/sites")
    async def sites(project_id: str, jwt: dict = Depends(get_current_user)):
        note("GET", f"/projects/{project_id}/sites", jwt)
        return [{"id": SITE, "name": "Green Villa main"}]

    @app.get("/materials")
    async def materials(search: str | None = None, jwt: dict = Depends(get_current_user)):
        note("GET", f"/materials?search={search}", jwt)
        catalog = {"cement": (CEMENT, "Cement OPC 53"), "tmt": (TMT, "TMT bar 12mm")}
        hit = catalog.get((search or "").lower())
        return {"items": [{"id": hit[0], "name": hit[1]}] if hit else [], "total": 1 if hit else 0}

    @app.get("/materials/units-of-measure")
    async def units(jwt: dict = Depends(get_current_user)):
        note("GET", "/materials/units-of-measure", jwt)
        return [{"id": BAG, "code": "bag"}, {"id": NOS, "code": "nos"}]

    @app.post("/materials/inflows", status_code=201)
    async def inflow(body: Inflow, jwt: dict = Depends(get_current_user),
                     idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
        note("POST", "/materials/inflows", jwt, idempotency_key)
        return {"id": str(uuid.uuid4()), "status": "created", "quantity": body.quantity}

    return app


def stand_in_tools(app: FastAPI):  # noqa: ANN201
    pilot = tuple(a for a in ALLOWED if a.name in {
        "list_projects", "list_sites", "search_materials", "list_units", "record_receipt"})
    return build_tools(app.openapi(), pilot)


ACTOR = Actor(user_id=USER, organization_id=ORG, role="SITE_SUPERVISOR", name="Ravi")

MESSAGE = "50 bag cement and 50 TMT came today at Green Villa"


def scripted_model() -> FakeToolCallingProvider:
    def receipt(material: str, unit: str, summary: str) -> tuple[str, dict]:
        return ("record_receipt", {
            "project_id": PROJECT, "site_id": SITE, "material_id": material, "unit_id": unit,
            "quantity": 50, "occurred_date": "2026-11-01", SUMMARY_ARG: summary,
        })

    return FakeToolCallingProvider([
        [("list_projects", {}), ("search_materials", {"search": "cement"}),
         ("search_materials", {"search": "TMT"}), ("list_units", {})],
        [("list_sites", {"project_id": PROJECT})],
        [receipt(CEMENT, BAG, "50 bags cement, Green Villa"), receipt(TMT, NOS, "50 TMT bars, Green Villa")],
        "Ready: 50 bags cement and 50 TMT bars at Green Villa. Confirm to save.",
    ])


async def test_reads_run_as_the_sender_and_writes_wait_for_confirmation() -> None:
    seen: list = []
    app = stand_in_api(seen)
    model = scripted_model()
    agent = ApiAgent(model, stand_in_tools(app))
    client = ApiClient(ACTOR, app=app)
    try:
        turn = await agent.run(client, MESSAGE, sender_name="Ravi")
        # Every read went through the API with the sender's own token claims.
        assert seen and all(jwt["sub"] == USER and jwt["org"] == ORG and jwt["role"] == "SITE_SUPERVISOR"
                            for _, _, jwt, _ in seen)
        # Nothing was written: two entries are held, named in the person's words.
        assert [m for m, *_ in seen].count("POST") == 0
        assert [p.summary for p in turn.pending] == ["50 bags cement, Green Villa", "50 TMT bars, Green Villa"]
        assert turn.reply.startswith("Ready")
        # The model was told the entries are not saved.
        held = [c for c in turn.calls if c["tool"] == "record_receipt"]
        assert all("NOT saved" in c["result"]["status"] for c in held)
        assert "Today is" in model.last_system_prompt and "Ravi" in model.last_system_prompt

        results = await confirm(client, turn.pending)
        assert [r.ok for r in results] == [True, True]
        posts = [(path, key) for m, path, _, key in seen if m == "POST"]
        assert len(posts) == 2 and all(key and key.startswith("api-agent-") for _, key in posts)
        assert posts[0][1] != posts[1][1]
    finally:
        await client.close()


async def test_unknown_tool_and_missing_field_are_refused_without_a_call() -> None:
    seen: list = []
    app = stand_in_api(seen)
    model = FakeToolCallingProvider([
        [("delete_material", {"material_id": CEMENT}),
         ("record_receipt", {"project_id": PROJECT, "quantity": 5, SUMMARY_ARG: "5 cement"})],
        "Which material and unit?",
    ])
    client = ApiClient(ACTOR, app=app)
    try:
        turn = await ApiAgent(model, stand_in_tools(app)).run(client, "5 cement")
    finally:
        await client.close()
    assert turn.pending == [] and seen == []
    errors = [c["result"]["error"] for c in turn.calls]
    assert "unknown tool" in errors[0]  # the fake refuses a tool that was never offered
    assert errors[1].startswith("missing:") and "material_id" in errors[1]


async def test_the_api_refuses_a_call_without_the_senders_token() -> None:
    import httpx

    app = stand_in_api([])
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as raw:
        assert (await raw.get("/projects")).status_code == 401
        bad = {"Authorization": "Bearer not-a-token"}
        assert (await raw.get("/projects", headers=bad)).status_code == 401


def test_the_token_is_short_lived_and_names_the_sender() -> None:
    import datetime as dt

    import jwt as pyjwt

    from mesiri.domains.identity.auth_service import ALGORITHM, SECRET_KEY

    claims = pyjwt.decode(token_for(ACTOR), SECRET_KEY, algorithms=[ALGORITHM])
    assert (claims["sub"], claims["org"], claims["role"]) == (USER, ORG, "SITE_SUPERVISOR")
    left = dt.datetime.fromtimestamp(claims["exp"], dt.UTC) - dt.datetime.now(dt.UTC)
    assert dt.timedelta(minutes=4) < left <= dt.timedelta(minutes=5)


async def test_a_login_token_is_used_as_given() -> None:
    """The chat script's path: the person's own dashboard login token, no token made here."""
    seen: list = []
    app = stand_in_api(seen)
    client = ApiClient(app=app, token=token_for(ACTOR))
    try:
        assert (await client.call("GET", "/projects")).ok
    finally:
        await client.close()
    assert seen[0][2]["sub"] == USER
    with pytest.raises(ValueError):
        ApiClient(ACTOR, app=app, token="x")
    with pytest.raises(ValueError):
        ApiClient(app=app)
