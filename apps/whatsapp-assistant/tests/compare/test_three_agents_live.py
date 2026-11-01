"""WA-123: the same messages through classic, v2 and the API agent, on the REAL model, side by side.

Run by the "Compare agents" workflow (Actions -> Compare agents -> Run). Not a gate: it prints,
for every message and every engine, the reply as written, what would be saved (classic / v2: the
draft card's lines; API agent: the entries waiting for Save), which tools ran and how long it took.
The table goes to the job summary and ``$MESIRI_COMPARE_OUT`` (JSON).

Same data for all three: the test company of the replay world (Project Alpha, Site A1; cement,
M sand, sand, steel, bricks, metal). Classic and v2 run in that world; the API agent runs on a
Postgres seeded with the same names (it reads them through the real API). Nothing is saved:
every engine stops at "ready to save".

Needs GEMINI_API_KEY and Postgres at head; marked ``live`` and ``integration``.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import replace
from typing import Any

import pytest

pytestmark = [pytest.mark.live, pytest.mark.integration]

#: Real-sounding site messages: mixed parts, Manglish / Hinglish, questions, records.
MESSAGES: tuple[tuple[str, str], ...] = (
    ("mixed", "Good morning. 50 bags cement and 50 steel rods came today. Did anyone report labour today? "
              "What's the weather like on site?"),
    ("manglish", "inn 50 bag cement vannu, 20 bag use cheythu"),
    ("labour", "aaj 6 mason aur 4 helper aaye"),
    ("weather", "rain from 2 pm, 3 hours work stopped"),
    ("work", "plastering 180 sqm done on first floor east side"),
    ("stock", "cement stock ethra und?"),
    ("expense", "tea and snacks for workers 450 rupees"),
    ("issue", "cement theernnu, work stopped till new load comes"),
)


def _provider() -> Any:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        pytest.skip("GEMINI_API_KEY not set")
    from pydantic import SecretStr

    from mesiri.bootstrap.settings import GeminiSettings
    from mesiri_ai.adapters.gemini.adapter import GeminiProvider

    return GeminiProvider(GeminiSettings(api_key=SecretStr(key), model=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")))


# -- classic and v2: the replay world -------------------------------------------------------


async def _world() -> Any:
    from tests.agent_v2.evalkit import _Books
    from tests.replay.test_agent_replay import _Catalog, _make_world

    from context import seed
    from runtime.agent.draft_store import MemoryDraftStore

    world = await _make_world(site_keys=(seed.SITE_A1,))
    world.draft_v2 = True
    world.drafts = MemoryDraftStore()
    world.catalog = _Catalog()
    world.inventory = _Books()
    world.actor = replace(world.actor, role="PROJECT_MANAGER")
    return world


async def _run_in_world(engine: str, text: str, provider: Any) -> dict[str, Any]:
    from tests.agent_v2.evalkit import Recording
    from tests.replay.test_draft_per_message_p1 import open_items

    from agent_v2 import runner as v2_runner
    from agent_v2.runner import V2Runner
    from runtime.agent import draft as draft_card
    from runtime.agent.runner import AgentRunner

    v2_runner._LAST_REPLY.clear()  # each message is a fresh conversation for every engine
    world = await _world()
    recording = Recording(provider)
    runner = AgentRunner(recording) if engine == "classic" else V2Runner(recording, AgentRunner(provider))
    card_line = draft_card.context_line(await world.drafts.open_for(world.actor.organization_id, world.actor.user_id))
    started = time.perf_counter()
    try:
        result = await runner.run(ctx=world.context(card_line=card_line), user_text=text, gateway=world.gateway(text),
                                  scope=world.scope(), correlation_id=f"cor_cmp_{engine}")
        reply = result.reply.text if result.reply else ""
        buttons = [b.title for b in (result.reply.buttons or result.reply.list_rows or ())] if result.reply else []
        error = type(result.error).__name__ if result.error else ""
    except Exception as exc:  # noqa: BLE001 -- shown in the table, never stops the comparison
        reply, buttons, error = "", [], f"{type(exc).__name__}: {exc}"[:200]
    seconds = time.perf_counter() - started
    items = await open_items(world)
    return {
        "reply": reply, "buttons": buttons, "error": error, "seconds": round(seconds, 1),
        "would_save": [i.summary or i.label or i.kind for i in items],
        "tools": [name for name, _ in recording.calls],
    }


# -- the API agent: Postgres with the same company ------------------------------------------


async def _seed(db: Any) -> dict[str, str]:
    import sqlalchemy as sa

    ids = {k: uuid.uuid4() for k in ("org", "user", "project", "site")}
    async with db.transaction() as conn:
        run = conn.execute
        await run(sa.text(
            "INSERT INTO organizations (id, name, deployment_type, db_route, status, created_at, updated_at) "
            "VALUES (:org, 'Acme Builders', 'local', 'default', 'active', now(), now())"), ids)
        await run(sa.text(
            "INSERT INTO users (id, organization_id, email, hashed_password, full_name, role, created_at, updated_at) "
            "VALUES (:user, :org, :email, 'x', 'Ravi', 'ADMIN', now(), now())"), {**ids, "email": f"{ids['user']}@t.in"})
        await run(sa.text(
            "INSERT INTO organization_settings (id, organization_id, key, value) VALUES "
            "(:id, :org, 'enabled_modules', CAST(:value AS jsonb))"),
            {"id": uuid.uuid4(), "org": ids["org"], "value": json.dumps(["dpr", "labour", "materials", "finance"])})
        await run(sa.text(
            "INSERT INTO projects (id, organization_id, name, created_at, updated_at) "
            "VALUES (:project, :org, 'Project Alpha', now(), now())"), ids)
        await run(sa.text(
            "INSERT INTO sites (id, project_id, organization_id, name) VALUES (:site, :project, :org, 'Site A1')"), ids)
        for name, unit in (("cement", "bags"), ("M sand", "cum"), ("sand", "cum"), ("steel", "kg"),
                           ("bricks", "pieces"), ("metal", "cum")):
            await run(sa.text(
                "INSERT INTO materials_catalog (id, organization_id, name, default_unit_id, is_active, created_by) "
                "VALUES (:id, :org, :name, (SELECT id FROM units_of_measure WHERE code = :unit), true, :user)"),
                {"id": uuid.uuid4(), "org": ids["org"], "user": ids["user"], "name": name, "unit": unit})
    return {k: str(v) for k, v in ids.items()}


async def _run_api(text: str, provider: Any, app: Any, company: dict[str, str]) -> dict[str, Any]:
    """Through v3's WhatsApp layer (facts up front, ready list, buttons), as a message would go."""
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from agent_api import whatsapp as wa
    from mesiri.infrastructure.redis.client import FakeRedis
    from mesiri_contracts.assistant.enums import InputModality
    from mesiri_contracts.assistant.normalized_message import NormalizedMessage, SenderInfo

    traced: dict[str, Any] = {}

    class _Trace:
        async def log_stage(self, **kw: Any) -> None:
            traced.update(kw["stage_payload"])

    class _Log:
        async def log_reply(self, **_: Any) -> None: ...
        async def mark_completed(self, **_: Any) -> None: ...

    sent: list[Any] = []

    async def send(spec: Any, wa_id: str) -> None:
        sent.append(spec)

    ctx = SimpleNamespace(
        user_id=company["user"], organization_id=company["org"], role="ADMIN", full_name="Ravi",
        timezone="Asia/Kolkata", projects=[SimpleNamespace(id=company["project"], name="Project Alpha")],
        sites=[SimpleNamespace(id=company["site"], name="Site A1", project_id=company["project"])],
    )
    service = wa.ApiWhatsApp(provider=provider, database=None, redis=FakeRedis(), send=send, transcribe=None,
                             message_logger=_Log(), trace_logger=_Trace(), app=app)
    message = NormalizedMessage(message_id=f"wamid.cmp.{uuid.uuid4().hex[:6]}", sender=SenderInfo(wa_id="919800000000"),
                                timestamp=datetime.now(UTC), modality=InputModality.TEXT, text=text)
    started = time.perf_counter()
    try:
        await service.handle(message, ctx)
        reply = sent[-1].text if sent else ""
        buttons = [b.title for b in (sent[-1].buttons or ())] if sent else []
        error = str(traced.get("error") or "")
    except Exception as exc:  # noqa: BLE001
        reply, buttons, error = "", [], f"{type(exc).__name__}: {exc}"[:200]
    return {
        "reply": reply, "buttons": buttons, "error": error, "seconds": round(time.perf_counter() - started, 1),
        "would_save": list(traced.get("pending") or []), "tools": [c["tool"] for c in traced.get("calls") or []],
    }


# -- the run --------------------------------------------------------------------------------


async def test_compare_classic_v2_and_the_api_agent() -> None:
    import asyncio

    from agent_api.app import build_api_app
    from mesiri.bootstrap.settings import Settings
    from mesiri.infrastructure.postgres.database import PostgresDatabase

    provider = _provider()
    pace = float(os.environ.get("MESIRI_LIVE_PACE_SECONDS", "0"))
    db = PostgresDatabase(Settings().postgres)
    await db.connect()
    try:
        company = await _seed(db)
        app = build_api_app(db)
        rows = []
        for label, text in MESSAGES:
            row: dict[str, Any] = {"label": label, "message": text}
            for engine in ("classic", "v2", "api"):
                if pace:
                    await asyncio.sleep(pace)
                row[engine] = (await _run_api(text, provider, app, company) if engine == "api"
                               else await _run_in_world(engine, text, provider))
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False))
    finally:
        await db.disconnect()
    _report(rows)


def _report(rows: list[dict[str, Any]]) -> None:
    out = os.environ.get("MESIRI_COMPARE_OUT")
    if out:
        with open(out, "w", encoding="utf-8") as fh:
            json.dump({"model": os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"), "rows": rows}, fh,
                      ensure_ascii=False, indent=1)
    lines = [f"# Classic vs v2 vs API agent ({os.environ.get('GEMINI_MODEL', 'gemini-2.5-flash')})", ""]
    for row in rows:
        lines += [f"## {row['label']}: “{row['message']}”", "", "| | Reply | Would save | Tools | Time |",
                  "|---|---|---|---|---|"]
        for engine, name in (("classic", "Classic"), ("v2", "v2"), ("api", "API agent")):
            r = row[engine]
            reply = (r["reply"] or f"*(no words{': ' + r['error'] if r['error'] else ''})*").replace("\n", "<br>")
            saves = "<br>".join(r["would_save"]) or "—"
            lines.append(f"| **{name}** | {reply.replace('|', '/')} | {saves.replace('|', '/')} | "
                         f"{', '.join(r['tools']) or '—'} | {r['seconds']} s |")
        lines.append("")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    print("\n".join(lines))
