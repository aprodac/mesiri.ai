"""WA-119 on a real database: the API agent writes through the same API app the
worker builds (``agent_api.app.build_api_app``: the dashboard's own routers), with
the real auth and company checks.

The model is scripted, but every id it sends is read from the API's own answers
(nothing is seeded into the script), so the test proves the read -> write chain
the real model has to follow. Also: a WhatsApp message -> Save tap -> rows; an
issue, an expense and a site's weather through the real routers; a user of
another company can neither see the project nor record into it.

Needs Postgres at head (``alembic upgrade head``); marked ``integration``.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from types import SimpleNamespace

import pytest
import sqlalchemy as sa

from agent_api import whatsapp as wa
from agent_api.agent import ApiAgent, PendingWrite, confirm
from agent_api.app import build_api_app
from agent_api.client import Actor, ApiClient, new_idempotency_key
from agent_api.tools import CONFIRM_ARG, build_tools
from channel.replies import ReplySpec
from mesiri.bootstrap.settings import Settings
from mesiri.infrastructure.postgres.database import PostgresDatabase
from mesiri.infrastructure.redis.client import FakeRedis
from mesiri_ai.fakes import FakeToolCallingProvider
from mesiri_contracts.assistant.enums import InputModality
from mesiri_contracts.assistant.normalized_message import NormalizedMessage, SenderInfo

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
async def _fresh_projects_engine():
    """The dashboard's projects router keeps one engine per process (one event loop in the
    worker); pytest gives each test its own loop, so each test gets its own engine."""
    import projects.router as projects_router

    projects_router._engine = None
    yield
    if projects_router._engine is not None:
        await projects_router._engine.dispose()
    projects_router._engine = None


@pytest.fixture
async def database():
    db = PostgresDatabase(Settings().postgres)
    await db.connect()
    yield db
    await db.disconnect()


async def _company(db: PostgresDatabase, name: str, modules: tuple[str, ...] = ("dpr", "materials", "finance")) -> dict:
    ids = {k: uuid.uuid4() for k in ("org", "user", "project", "site", "cement", "tmt")}
    async with db.transaction() as conn:
        run = conn.execute
        await run(sa.text(
            "INSERT INTO organizations (id, name, deployment_type, db_route, status, created_at, updated_at) "
            "VALUES (:org, :name, 'local', 'default', 'active', now(), now())"), {**ids, "name": name})
        await run(sa.text(
            "INSERT INTO users (id, organization_id, email, hashed_password, full_name, role, created_at, updated_at) "
            "VALUES (:user, :org, :email, 'x', 'Ravi', 'ADMIN', now(), now())"), {**ids, "email": f"{ids['user']}@t.in"})
        await run(sa.text(
            "INSERT INTO organization_settings (id, organization_id, key, value) "
            "VALUES (:id, :org, 'enabled_modules', CAST(:value AS jsonb))"),
            {"id": uuid.uuid4(), "org": ids["org"], "value": json.dumps(list(modules))})
        await run(sa.text(
            "INSERT INTO projects (id, organization_id, name, created_at, updated_at) "
            "VALUES (:project, :org, 'Green Villa', now(), now())"), ids)
        await run(sa.text(
            "INSERT INTO sites (id, project_id, organization_id, name) VALUES (:site, :project, :org, 'Main block')"), ids)
        for key, material, unit in (("cement", "Cement", "bags"), ("tmt", "TMT bar", "pieces")):
            await run(sa.text(
                "INSERT INTO materials_catalog (id, organization_id, name, default_unit_id, is_active, created_by) "
                "VALUES (:id, :org, :name, (SELECT id FROM units_of_measure WHERE code = :unit), true, :user)"),
                {"id": ids[key], "org": ids["org"], "user": ids["user"], "name": material, "unit": unit})
    return {k: str(v) for k, v in ids.items()}


def _actor(company: dict) -> Actor:
    return Actor(company["user"], company["org"], "ADMIN", "Ravi")


def _result(records: list, tool: str) -> object:
    """The JSON the API answered to the last call of ``tool`` in this run."""
    last = [r for r in records if r.name == tool][-1]
    return json.loads(last.outcome.content["result"])


def _model() -> FakeToolCallingProvider:
    def receipts(records: list) -> list:
        project = _result(records, "list_projects")[0]["id"]
        site = _result(records, "list_sites")[0]["id"]
        found = {r.arguments["search"]: json.loads(r.outcome.content["result"])["items"][0]
                 for r in records if r.name == "search_materials"}
        return [("record_receipt", {
            "project_id": project, "site_id": site, "material_id": item["id"],
            "unit_id": item["default_unit_id"], "quantity": 50, "occurred_date": "2026-11-01",
            "supplier": "Sri Traders", CONFIRM_ARG: f"50 {name}, Main block",
        }) for name, item in found.items()]

    return FakeToolCallingProvider([
        [("list_projects", {}), ("search_materials", {"search": "Cement"}), ("search_materials", {"search": "TMT"})],
        lambda records: [("list_sites", {"project_id": _result(records, "list_projects")[0]["id"]})],
        receipts,
        "Ready: 50 bags cement and 50 TMT bars at Main block.",
    ])


async def _receipts(database: PostgresDatabase, org: str) -> list:
    async with database.transaction() as conn:
        return (await conn.execute(sa.text(
            "SELECT material_id::text, quantity, site_id::text FROM material_receipts WHERE organization_id = :o"),
            {"o": org})).all()


async def test_a_receipt_message_is_recorded_through_the_real_api(database: PostgresDatabase) -> None:
    acme = await _company(database, "Acme Builders")
    app = build_api_app(database)
    client = ApiClient(_actor(acme), app=app)
    try:
        turn = await ApiAgent(_model(), build_tools(app.openapi())).run(client, "50 bag cement, 50 TMT vannu")
        statuses = [c["result"].get("status") for c in turn.calls if c["tool"] != "record_receipt"]
        assert statuses and all(s == 200 for s in statuses), turn.calls
        assert len(turn.pending) == 2
        assert await _receipts(database, acme["org"]) == []  # held, not written

        results = await confirm(client, turn.pending)
        assert [r.status for r in results] == [201, 201], [r.body for r in results]
        again = await confirm(client, turn.pending)  # a repeated confirmation records nothing new
        assert all(r.ok for r in again)
    finally:
        await client.close()
    rows = await _receipts(database, acme["org"])
    assert sorted(r[0] for r in rows) == sorted([acme["cement"], acme["tmt"]])
    assert all(float(r[1]) == 50 and r[2] == acme["site"] for r in rows)


async def test_whatsapp_message_then_save_tap_writes_the_rows(database: PostgresDatabase) -> None:
    acme = await _company(database, "Acme Builders")
    sent: list[ReplySpec] = []

    async def send(spec: ReplySpec, wa_id: str) -> None:
        sent.append(spec)

    service = wa.ApiWhatsApp(provider=_model(), database=database, redis=FakeRedis(), send=send,
                             transcribe=None, message_logger=SimpleNamespace(
                                 log_reply=_noop, mark_completed=_noop))
    ctx = SimpleNamespace(user_id=acme["user"], organization_id=acme["org"], role="ADMIN", full_name="Ravi",
                          timezone="Asia/Kolkata")

    def message(text: str, tap: str | None = None) -> NormalizedMessage:
        return NormalizedMessage(
            message_id=f"wamid.{uuid.uuid4().hex[:6]}", sender=SenderInfo(wa_id="919800000000"),
            timestamp=dt.datetime.now(dt.UTC), text=text,
            modality=InputModality.INTERACTIVE if tap else InputModality.TEXT,
            metadata={"interactive_reply_id": tap} if tap else {},
        )

    assert await service.handle(message("50 bag cement, 50 TMT vannu, Sri Traders"), ctx)
    assert "*Ready to save:*" in sent[-1].text and await _receipts(database, acme["org"]) == []
    await service.handle(message("Save", tap=sent[-1].buttons[0].id), ctx)
    assert sent[-1].text.startswith("Saved."), sent[-1].text
    assert len(await _receipts(database, acme["org"])) == 2


async def _noop(**_: object) -> None:
    return None


async def test_issue_expense_and_weather_through_the_real_routers(database: PostgresDatabase) -> None:
    acme = await _company(database, "Acme Builders")
    app = build_api_app(database)
    today = dt.date.today().isoformat()

    def entry(tool: str, method: str, path: str, body: dict, params: dict | None = None) -> PendingWrite:
        return PendingWrite(tool=tool, method=method, path=path, params=params or {}, body=body,
                            summary=tool, idempotency_key=new_idempotency_key())

    entries = [
        entry("report_issue", "POST", "/progress/issues", {
            "project_id": acme["project"], "site_id": acme["site"], "issue_type": "MATERIAL_SHORTAGE",
            "severity": "MEDIUM", "narrative": "Cement ran out at 3 pm"}),
        entry("record_expense", "POST", "/expenses", {
            "project_id": acme["project"], "site_id": acme["site"], "amount": 1500, "occurred_date": today,
            "description": "Tea and snacks", "source": "whatsapp"}),
        entry("set_site_conditions", "PATCH", f"/dpr/site-days/{acme['site']}/conditions",
              {"weather": "rainy", "hours_lost": 2}, {"date": today}),
    ]
    client = ApiClient(_actor(acme), app=app)
    try:
        results = await confirm(client, entries)
        issues = await client.call("GET", "/progress/issues", params={"site_id": acme["site"]})
        day = await client.call("GET", f"/dpr/site-days/{acme['site']}", params={"date": today})
    finally:
        await client.close()
    assert [r.ok for r in results] == [True, True, True], [(r.pending.tool, r.status, r.body) for r in results]
    assert [i["narrative"] for i in issues.body["items"]] == ["Cement ran out at 3 pm"]
    assert "rainy" in json.dumps(day.body)


async def test_another_companys_user_cannot_see_or_record_into_it(database: PostgresDatabase) -> None:
    acme = await _company(database, "Acme Builders")
    other = await _company(database, "Other Co")
    app = build_api_app(database)
    client = ApiClient(_actor(other), app=app)
    try:
        projects = await client.call("GET", "/projects")
        assert acme["project"] not in {p["id"] for p in projects.body}
        sites = await client.call("GET", f"/projects/{acme['project']}/sites")
        assert not sites.ok or sites.body == []
        materials = await client.call("GET", "/materials", params={"search": "Cement"})
        assert acme["cement"] not in {m["id"] for m in materials.body["items"]}
        write = await client.call("POST", "/materials/inflows", json={
            "project_id": acme["project"], "site_id": acme["site"], "material_id": acme["cement"],
            "unit_id": str(uuid.uuid4()), "quantity": 5, "occurred_date": "2026-11-01"})
        assert write.status in (400, 403, 404, 422), write.body
        issue = await client.call("POST", "/progress/issues", json={
            "project_id": acme["project"], "site_id": acme["site"], "issue_type": "OTHER", "severity": "LOW"})
        assert issue.status in (400, 403, 404), issue.body
    finally:
        await client.close()
    assert await _receipts(database, acme["org"]) == []


async def test_a_module_the_company_does_not_have_is_refused_by_the_api(database: PostgresDatabase) -> None:
    """The API's own module switch applies to the agent as to the dashboard."""
    acme = await _company(database, "No Finance Co", modules=("dpr", "materials"))
    client = ApiClient(_actor(acme), app=build_api_app(database))
    try:
        result = (await confirm(client, [PendingWrite(
            tool="record_expense", method="POST", path="/expenses", params={}, summary="tea",
            body={"project_id": acme["project"], "amount": 100, "occurred_date": dt.date.today().isoformat(),
                  "source": "whatsapp"}, idempotency_key=new_idempotency_key())]))[0]
    finally:
        await client.close()
    assert result.status == 403 and result.body["detail"]["code"] == "MODULE_DISABLED"
