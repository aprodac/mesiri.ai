"""WA-277 step B: every route the assistant may call answers, with no model.

[285] (live, 11 Nov 2026, New India): "one week's report" was answered "could not check it right now" both times it was
ever asked in production. The route was on ``ALLOWED`` and every scripted test passed, but the API app the WORKER
builds (``agent_api.app.build_api_app``) gave its routers no object storage, so the route raised and answered 500;
about a dozen routes shared it. No test called a route through that app unless a feature's own test happened to.

This calls EVERY tool on ``ALLOWED`` once, as an admin of a seeded company, through the worker's own API app on
Postgres: path ids from the company (or an id that does not exist), the required query and body fields filled from
the tool's own schema. The route may refuse the made-up values (404, 409, 422, 403): that is an answer. What fails
the build is a crash: a 5xx, or a route that raises. A new route added to ``ALLOWED`` is covered the day it is added.

Needs Postgres at head (``alembic upgrade head``); marked ``integration``.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

import pytest
import sqlalchemy as sa
from tests.integration.test_api_agent_119_postgres import (  # noqa: F401
    _actor,
    _company,
    _fresh_projects_engine,
    database,
)

from agent_api.app import build_api_app
from agent_api.client import ApiClient, new_idempotency_key
from agent_api.tools import ALLOWED, CONFIRM_ARG, MATERIAL_SAID, ApiTool, build_tools
from mesiri.infrastructure.postgres.database import PostgresDatabase

pytestmark = pytest.mark.integration

#: Routes that answer 503 on purpose when a service they stand on is not set up (a test database has no request log):
#: a worded answer the assistant passes on, not a crash. Only these, and only 503.
NOT_CONNECTED = {"my_requests"}
#: Every module switched on, so a route is reached and not turned away at the module gate.
MODULES = ("dpr", "materials", "finance", "labour", "tasks", "equipment", "cost", "accounts", "automations")


def sample(name: str, schema: dict[str, Any], known: dict[str, str]) -> Any:
    """A value of the right shape for one field, from its schema: the company's own ids where the name says which
    record it is, else an id that does not exist."""
    for option in schema.get("anyOf") or schema.get("oneOf") or []:
        if option.get("type") != "null":
            return sample(name, option, known)
    if schema.get("enum"):
        return schema["enum"][0]
    kind, form = schema.get("type"), schema.get("format")
    if kind == "string" and form == "uuid" or name.endswith("_id") and kind in ("string", None):
        return known.get(name) or str(uuid.uuid4())
    if kind == "string" and form == "date":
        return dt.date.today().isoformat()
    if kind == "string" and form == "date-time":
        return dt.datetime.now(dt.UTC).isoformat()
    if kind == "integer":
        return 1
    if kind == "number":
        return 1.0
    if kind == "boolean":
        return False
    if kind == "array":
        return []
    if kind == "object":
        return {}
    return "Test"


def request_for(tool: ApiTool, known: dict[str, str]) -> tuple[str, dict[str, Any], dict[str, Any] | None]:
    properties = tool.spec.parameters.get("properties") or {}
    needed = {n for n in tool.required if n not in (CONFIRM_ARG, MATERIAL_SAID)} | set(tool.path_params)
    values = {n: sample(n, properties.get(n) or {}, known) for n in needed}
    path = tool.path
    for p in tool.path_params:
        path = path.replace("{" + p + "}", str(values[p]))
    params = {q: values[q] for q in tool.query_params if q in values}
    body = {f: values[f] for f in tool.body_fields if f in values}
    body.update(dict(tool.fixed))
    return path, params, (body if tool.is_write else None)


async def test_every_allowed_route_answers_through_the_workers_api_app(database: PostgresDatabase) -> None:  # noqa: F811
    company = await _company(database, f"Route check {uuid.uuid4().hex[:6]}", MODULES)
    async with database.transaction() as conn:
        unit = (await conn.execute(sa.text("SELECT id::text FROM units_of_measure WHERE code = 'bags'"))).scalar()
    known = {"project_id": company["project"], "site_id": company["site"], "material_id": company["cement"],
             "unit_id": unit, "default_unit_id": unit, "from_unit_id": unit, "size_unit_id": unit}
    app = build_api_app(database)
    tools = build_tools(app.openapi())
    assert set(tools) == {a.name for a in ALLOWED}
    crashed: list[str] = []
    client = ApiClient(_actor(company), app=app)
    try:
        for name, tool in tools.items():
            path, params, body = request_for(tool, known)
            try:
                response = await client.call(tool.method, path, params=params or None, json=body,
                                             idempotency_key=new_idempotency_key() if tool.is_write else None)
            except Exception as exc:  # noqa: BLE001 -- a route that raises is the failure this test exists for
                crashed.append(f"{name} ({tool.method} {tool.path}): raised {type(exc).__name__}: {exc}"[:300])
                continue
            if response.status == 503 and name in NOT_CONNECTED:
                continue
            if response.status >= 500:
                crashed.append(f"{name} ({tool.method} {tool.path}): {response.status} {str(response.body)[:200]}")
    finally:
        await client.close()
    assert not crashed, f"{len(crashed)} of {len(tools)} routes crashed:\n" + "\n".join(crashed)


async def test_the_check_catches_the_crash_of_11_nov(database: PostgresDatabase, monkeypatch) -> None:  # noqa: ANN001, F811
    """The guard of the guard: with the API app as it was on 11 Nov (no object storage for its routers), the
    period report and its siblings are reported as crashed."""
    from agent_api import app as api_app

    class NoStorage:
        def __init__(self, database: Any, object_storage: Any = None) -> None:
            self.material_db = database

    monkeypatch.setattr(api_app, "_Container", NoStorage)
    company = await _company(database, f"Route check {uuid.uuid4().hex[:6]}", MODULES)
    app = build_api_app(database)
    tool = build_tools(app.openapi())["period_report"]
    path, params, body = request_for(tool, {"project_id": company["project"], "site_id": company["site"]})
    client = ApiClient(_actor(company), app=app)
    try:
        response = await client.call(tool.method, path, params=params or None, json=body)
    finally:
        await client.close()
    assert response.status >= 500


def test_sample_values_follow_the_schema() -> None:
    known = {"project_id": "p-1"}
    assert sample("project_id", {"type": "string", "format": "uuid"}, known) == "p-1"
    assert uuid.UUID(sample("issue_id", {"type": "string", "format": "uuid"}, known))
    assert sample("status", {"enum": ["open", "closed"]}, known) == "open"
    assert sample("quantity", {"anyOf": [{"type": "number"}, {"type": "null"}]}, known) == 1.0
    assert sample("on", {"type": "string", "format": "date"}, known) == dt.date.today().isoformat()
    assert sample("lines", {"type": "array"}, known) == []
