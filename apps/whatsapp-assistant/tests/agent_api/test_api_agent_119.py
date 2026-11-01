"""WA-119: the API agent.

1. The tools come from the real app's OpenAPI, and from the worker's own API app:
   every allowed route exists, the schemas are provider-safe, the write tools carry
   the API's required fields, internal fields are hidden or fixed.
2. A turn through a scripted model: reads hit the API as the sender, writes are
   held (nothing is POSTed) until confirmed, each sent once with an Idempotency-Key.
3. Waiting entries: kept across turns, saved only through ``save_ready_entries``
   (the person said so), dropped through ``drop_ready_entries``.
4. Guards: an unknown tool, a write missing a field, a call without the sender's
   token, and the API's company binding leaking into the caller.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest
from pydantic import BaseModel
from tests.agent_api.standin import (
    ACTOR,
    BAG,
    CEMENT,
    MESSAGE,
    ORG,
    PROJECT,
    TMT,
    USER,
    receipt_call,
    stand_in_api,
    stand_in_tools,
    two_receipts_model,
)

from agent_api.agent import DROP_READY, SAVE_READY, ApiAgent, confirm
from agent_api.app import build_api_app
from agent_api.client import ApiClient, token_for
from agent_api.tools import ALLOWED, CONFIRM_ARG, Allowed, ToolBuildError, build_tools
from mesiri_ai.fakes import FakeToolCallingProvider

# -- 1. tools from the real API ---------------------------------------------------------


@pytest.fixture(scope="module")
def real_openapi() -> dict:
    logging.disable(logging.CRITICAL)
    try:
        from runtime.dependencies import Settings
        from runtime.lifecycle import create_app

        return create_app(Settings(verify_token="x", app_secret="x", access_token="x")).openapi()
    finally:
        logging.disable(logging.NOTSET)


@pytest.fixture(scope="module")
def worker_openapi() -> dict:
    return build_api_app(None).openapi()


def test_every_allowed_route_is_in_the_real_api_and_in_the_workers_api_app(real_openapi, worker_openapi) -> None:
    names = {a.name for a in ALLOWED}
    assert set(build_tools(real_openapi)) == names
    assert set(build_tools(worker_openapi)) == names


def test_the_workers_api_app_serves_the_same_routes_as_the_real_app(real_openapi, worker_openapi) -> None:
    for item in ALLOWED:
        real = real_openapi["paths"][item.path][item.method.lower()]
        mine = worker_openapi["paths"][item.path][item.method.lower()]
        assert real.get("operationId") == mine.get("operationId"), item.name


def test_schemas_are_provider_safe(real_openapi) -> None:
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


def test_write_tools_carry_the_apis_required_fields(real_openapi) -> None:
    tools = build_tools(real_openapi)
    receipt = tools["record_receipt"]
    assert receipt.is_write and receipt.method == "POST"
    for name in ("project_id", "material_id", "unit_id", "quantity", "occurred_date", CONFIRM_ARG):
        assert name in receipt.required
    assert "supplier" in receipt.spec.parameters["properties"]
    assert {"from_site_id", "to_site_id"} <= set(tools["record_transfer"].required)
    assert {"project_id", "site_id", "issue_type", "severity"} <= set(tools["report_issue"].required)
    assert "narrative" in tools["report_issue"].spec.parameters["properties"]
    assert tools["set_site_conditions"].method == "PATCH" and tools["set_site_conditions"].is_write
    sites = tools["list_sites"]
    assert not sites.is_write and sites.path_params == ("project_id",)
    assert CONFIRM_ARG not in sites.spec.parameters["properties"]


def test_expense_bookkeeping_fields_are_hidden_and_source_is_fixed(real_openapi) -> None:
    expense = build_tools(real_openapi)["record_expense"]
    props = expense.spec.parameters["properties"]
    assert not {"source", "source_message_id", "correlation_id"} & set(props)
    assert dict(expense.fixed) == {"source": "whatsapp"}


def test_a_route_missing_from_the_api_fails_the_build(real_openapi) -> None:
    with pytest.raises(ToolBuildError):
        build_tools(real_openapi, (Allowed("gone", "GET", "/materials/no-such-route", "x"),))


class _ClashingBody(BaseModel):
    confirm_line: str


def test_a_body_field_named_like_the_confirm_line_fails_the_build() -> None:
    from fastapi import FastAPI

    app = FastAPI()

    @app.post("/x")
    async def x(body: _ClashingBody):
        return {}

    with pytest.raises(ToolBuildError):
        build_tools(app.openapi(), (Allowed("x", "POST", "/x", "x"),))


# -- 2. a turn against the stand-in API ---------------------------------------------------


async def test_reads_run_as_the_sender_and_writes_wait_for_confirmation() -> None:
    seen: list = []
    app = stand_in_api(seen)
    model = two_receipts_model()
    agent = ApiAgent(model, stand_in_tools(app))
    client = ApiClient(ACTOR, app=app)
    try:
        turn = await agent.run(client, MESSAGE, sender_name="Ravi")
        assert seen and all(jwt["sub"] == USER and jwt["org"] == ORG and jwt["role"] == "SITE_SUPERVISOR"
                            for _, _, jwt, _ in seen)
        assert [m for m, *_ in seen].count("POST") == 0
        assert [p.summary for p in turn.pending] == ["50 bags cement, Green Villa", "50 TMT bars, Green Villa"]
        assert turn.reply.startswith("Ready") and turn.saved == []
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


# -- 3. waiting entries -------------------------------------------------------------------


async def _two_waiting(app) -> list:  # noqa: ANN001
    client = ApiClient(ACTOR, app=app)
    try:
        return (await ApiAgent(two_receipts_model(), stand_in_tools(app)).run(client, MESSAGE)).pending
    finally:
        await client.close()


async def test_waiting_entries_are_listed_and_saved_when_the_person_says_so() -> None:
    seen: list = []
    app = stand_in_api(seen)
    ready = await _two_waiting(app)
    model = FakeToolCallingProvider([[(SAVE_READY, {})], "Saved both."])
    client = ApiClient(ACTOR, app=app)
    try:
        turn = await ApiAgent(model, stand_in_tools(app)).run(client, "ok save it", ready=ready)
    finally:
        await client.close()
    assert "Ready, waiting for the person's confirmation" in model.last_system_prompt
    assert "1. 50 bags cement, Green Villa" in model.last_system_prompt
    assert [r.ok for r in turn.saved] == [True, True] and turn.pending == []
    assert [m for m, *_ in seen].count("POST") == 2


async def test_a_correction_drops_the_old_entry_and_prepares_the_new_one() -> None:
    seen: list = []
    app = stand_in_api(seen)
    ready = await _two_waiting(app)
    model = FakeToolCallingProvider([
        [(DROP_READY, {"numbers": [1]}), receipt_call(CEMENT, BAG, "40 bags cement, Green Villa")],
        "Changed to 40 bags.",
    ])
    client = ApiClient(ACTOR, app=app)
    try:
        turn = await ApiAgent(model, stand_in_tools(app)).run(client, "alla, 40 bag cement", ready=ready)
    finally:
        await client.close()
    assert [e.summary for e in turn.pending] == ["50 TMT bars, Green Villa", "40 bags cement, Green Villa"]
    assert turn.saved == [] and [m for m, *_ in seen].count("POST") == 0


async def test_without_waiting_entries_the_save_tools_are_not_offered() -> None:
    model = FakeToolCallingProvider([[(SAVE_READY, {})], "Nothing to save."])
    app = stand_in_api([])
    client = ApiClient(ACTOR, app=app)
    try:
        turn = await ApiAgent(model, stand_in_tools(app)).run(client, "save it")
    finally:
        await client.close()
    assert "unknown tool" in turn.calls[0]["result"]["error"]


async def test_a_refused_entry_says_the_apis_reason_and_stays_out_of_saved() -> None:
    seen: list = []
    app = stand_in_api(seen, refuse_tmt=True)
    ready = await _two_waiting(app)
    model = FakeToolCallingProvider([[(SAVE_READY, {})], "Cement saved; TMT could not be saved."])
    client = ApiClient(ACTOR, app=app)
    try:
        turn = await ApiAgent(model, stand_in_tools(app)).run(client, "save", ready=ready)
    finally:
        await client.close()
    results = turn.calls[0]["result"]["results"]
    assert results[0]["saved"] is True
    assert results[1]["saved"] is False and "Not authorized" in results[1]["refused"]


# -- 4. guards ----------------------------------------------------------------------------


async def test_unknown_tool_and_missing_field_are_refused_without_a_call() -> None:
    seen: list = []
    app = stand_in_api(seen)
    model = FakeToolCallingProvider([
        [("delete_material", {"material_id": CEMENT}),
         ("record_receipt", {"project_id": PROJECT, "quantity": 5, CONFIRM_ARG: "5 cement"})],
        "Which material and unit?",
    ])
    client = ApiClient(ACTOR, app=app)
    try:
        turn = await ApiAgent(model, stand_in_tools(app)).run(client, "5 cement")
    finally:
        await client.close()
    assert turn.pending == [] and seen == []
    errors = [c["result"]["error"] for c in turn.calls]
    assert "unknown tool" in errors[0]
    assert errors[1].startswith("missing:") and "material_id" in errors[1]


async def test_the_api_refuses_a_call_without_the_senders_token() -> None:
    import httpx

    app = stand_in_api([])
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as raw:
        assert (await raw.get("/projects")).status_code == 401
        bad = {"Authorization": "Bearer not-a-token"}
        assert (await raw.get("/projects", headers=bad)).status_code == 401


async def test_the_apis_company_binding_never_leaks_into_the_caller() -> None:
    from fastapi import FastAPI

    from mesiri.infrastructure.postgres.tenant import bind_tenant, current_tenant, tenant_scope

    app = FastAPI()

    @app.get("/bind")
    async def bind():
        bind_tenant(ORG)  # what get_auth_context does for every request
        return {"bound": str(current_tenant())}

    client = ApiClient(ACTOR, app=app)
    try:
        with tenant_scope(None):
            response = await client.call("GET", "/bind")
            assert response.body == {"bound": ORG}
            assert current_tenant() is None
    finally:
        await client.close()


def test_the_token_is_short_lived_and_names_the_sender() -> None:
    import datetime as dt

    import jwt as pyjwt

    from mesiri.domains.identity.auth_service import ALGORITHM, SECRET_KEY

    claims = pyjwt.decode(token_for(ACTOR), SECRET_KEY, algorithms=[ALGORITHM])
    assert (claims["sub"], claims["org"], claims["role"]) == (USER, ORG, "SITE_SUPERVISOR")
    left = dt.datetime.fromtimestamp(claims["exp"], dt.UTC) - dt.datetime.now(dt.UTC)
    assert dt.timedelta(minutes=4) < left <= dt.timedelta(minutes=5)


async def test_a_login_token_is_used_as_given() -> None:
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


def test_unused_ids_are_distinct() -> None:
    assert len({CEMENT, TMT, BAG, PROJECT}) == 4
