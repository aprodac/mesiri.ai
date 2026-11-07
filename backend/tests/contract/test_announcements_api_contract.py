"""SA-37: announcements API on a real Postgres (run with `pytest -m integration`).

Who an announcement reaches (active people with a WhatsApp number in active and trial companies; who messaged in
the last 24 hours), sending (one notification row per person, the payload the WhatsApp sender reads), sending
again (only people not queued that day), pictures, the audit entry, and that only a platform admin can do any of it.
"""

from __future__ import annotations

import base64
import json
import uuid

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from mesiri.bootstrap.settings import Settings
from mesiri.domains.identity.auth_service import create_access_token
from mesiri.http.app import create_app
from mesiri.infrastructure.postgres.dependency import get_db_conn

pytestmark = pytest.mark.integration

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 64).decode()


CREATED: list[uuid.UUID] = []  # this file's companies, removed after each test (nothing else is touched)


async def _wipe(engine: AsyncEngine) -> None:
    if not CREATED:
        return
    async with engine.begin() as conn:
        orgs = {"orgs": list(CREATED)}
        await conn.execute(sa.text("DELETE FROM notifications WHERE organization_id = ANY(:orgs)"), orgs)
        await conn.execute(sa.text("DELETE FROM inbound_messages WHERE sender_wa_id LIKE '91984700000%'"))
        await conn.execute(sa.text("DELETE FROM users WHERE organization_id = ANY(:orgs)"), orgs)
        await conn.execute(sa.text("DELETE FROM organizations WHERE id = ANY(:orgs)"), orgs)
    CREATED.clear()


@pytest.fixture
async def engine():
    engine = create_async_engine(Settings().postgres.dsn(), echo=False)
    yield engine
    await _wipe(engine)
    await engine.dispose()


@pytest.fixture
async def client(engine, monkeypatch):
    monkeypatch.setattr("mesiri.domains.shared.modules._database_for", lambda request: None)
    app = create_app()

    async def conn():
        async with engine.begin() as c:
            yield c

    app.dependency_overrides[get_db_conn] = conn
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def _exec(engine, sql: str, **params):
    async with engine.begin() as c:
        await c.execute(sa.text(sql), params)


async def _company(engine, name: str, status: str = "trial") -> uuid.UUID:
    org = uuid.uuid4()
    await _exec(engine, "INSERT INTO organizations (id, name, deployment_type, db_route, status, created_at, "
                "updated_at) VALUES (:id, :n, 'local', 'default', :s, now(), now())", id=org, n=name, s=status)
    CREATED.append(org)
    return org


async def _person(engine, org, role: str, number: str | None, status: str = "active") -> uuid.UUID:
    uid = uuid.uuid4()
    await _exec(engine, "INSERT INTO users (id, organization_id, email, hashed_password, full_name, role, status, "
                "access_policy, whatsapp_number, created_at, updated_at) VALUES (:id, :o, :e, 'h', 'P', :r, :s, "
                "CAST(:p AS jsonb), :w, now(), now())", id=uid, o=org, e=f"{uuid.uuid4().hex[:8]}@x.com", r=role,
                s=status, p=json.dumps({"mode": "all_projects", "projects": []}), w=number)
    return uid


@pytest.fixture
async def world(engine):
    acme = await _company(engine, "Acme Builders", "active")
    kb = await _company(engine, "Kerala Builders", "trial")
    gone = await _company(engine, "Closed Co", "suspended")
    people = {
        "acme_owner": await _person(engine, acme, "OWNER", "+91 98470 00001"),
        "acme_engineer": await _person(engine, acme, "SITE_ENGINEER", "919847000002"),
        "kb_admin": await _person(engine, kb, "ADMIN", "919847000003"),
        "kb_no_number": await _person(engine, kb, "SITE_ENGINEER", None),
        "kb_inactive": await _person(engine, kb, "SITE_ENGINEER", "919847000004", status="inactive"),
        "gone": await _person(engine, gone, "ADMIN", "919847000005"),
    }
    # The Acme owner messaged Mesiri an hour ago: inside the 24-hour window.
    await _exec(engine, "INSERT INTO inbound_messages (id, correlation_id, sender_wa_id, message_type, raw_payload, "
                "dedup_key, received_at, processing_status) VALUES (:id, :c, '919847000001', 'text', "
                "CAST('{}' AS jsonb), :d, now() - interval '1 hour', 'processed')",
                id=uuid.uuid4(), c=str(uuid.uuid4()), d=str(uuid.uuid4()))
    admin = {"Authorization": "Bearer " + create_access_token(
        data={"sub": str(uuid.uuid4()), "org": "", "role": "ADMIN", "name": "Ilan"})}
    company_admin = {"Authorization": "Bearer " + create_access_token(
        data={"sub": str(people["kb_admin"]), "org": str(kb), "role": "ADMIN"})}
    return {"acme": acme, "kb": kb, "gone": gone, "people": people, "admin": admin, "company_admin": company_admin,
            "mine": {"organization_ids": [str(acme), str(kb), str(gone)]}}


async def _new(client, w, title="Material Requests") -> str:
    resp = await client.post("/admin/announcements", json={"title": title, "message": "*New:* ask for material"},
                             headers=w["admin"])
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def test_reach_counts_people_with_whatsapp_in_live_companies(client, world):
    w = world
    reach = (await client.post("/admin/announcements/audience", json=w["mine"], headers=w["admin"])).json()
    assert reach["people"] == 3 and reach["in_window"] == 1
    assert {c["name"]: (c["people"], c["in_window"]) for c in reach["companies"]} == {
        "Acme Builders": (2, 1), "Kerala Builders": (1, 0)}  # not the suspended company, nobody without a number
    everyone = (await client.post("/admin/announcements/audience", json={}, headers=w["admin"])).json()
    assert {"Acme Builders", "Kerala Builders"} <= {c["name"] for c in everyone["companies"]}
    assert "Closed Co" not in {c["name"] for c in everyone["companies"]}
    office = (await client.post("/admin/announcements/audience", json={**w["mine"], "roles": ["office"]},
                                headers=w["admin"])).json()
    assert office["people"] == 2  # the owner and the admin, not the engineer
    one = (await client.post("/admin/announcements/audience", json={"organization_ids": [str(w["kb"])]},
                             headers=w["admin"])).json()
    assert one["people"] == 1


async def test_sending_queues_one_message_per_person_once(client, world, engine):
    w = world
    aid = await _new(client, w)
    added = await client.post(f"/admin/announcements/{aid}/images", json={"content_type": "image/png", "data_base64": PNG},
                              headers=w["admin"])
    assert added.status_code == 201, added.text
    assert (await client.get(f"/admin/announcements/{aid}/images/0", headers=w["admin"])).content.startswith(b"\x89PNG")

    sent = (await client.post(f"/admin/announcements/{aid}/send", json=w["mine"], headers=w["admin"])).json()
    assert (sent["queued"], sent["already"], sent["people"]) == (3, 0, 3)
    async with engine.begin() as c:
        rows = (await c.execute(sa.text(
            "SELECT recipient_user_id, status, payload FROM notifications WHERE rule_key = 'announcement' "
            "AND subject_id LIKE :a"), {"a": f"{aid}:%"})).all()
    assert {r.recipient_user_id for r in rows} == {w["people"][k] for k in ("acme_owner", "acme_engineer", "kb_admin")}
    payload = rows[0].payload
    assert payload["message"] == "*New:* ask for material" and len(payload["images"]) == 1
    assert payload["hold_until_window"] is True and payload["hold_days"] == 7
    assert payload["template"] == {"name": "mesiri_product_update", "body_params": ["Material Requests"]}
    assert {r.status for r in rows} == {"pending"}

    again = (await client.post(f"/admin/announcements/{aid}/send", json=w["mine"], headers=w["admin"])).json()
    assert (again["queued"], again["already"]) == (0, 3)

    listed = (await client.get("/admin/announcements", headers=w["admin"])).json()["items"]
    mine = next(a for a in listed if a["id"] == aid)
    assert mine["deliveries"] == {"pending": 3} and [s["queued"] for s in mine["sends"]] == [3, 0]
    async with engine.begin() as c:
        audit = (await c.execute(sa.text(
            "SELECT action, actor_label FROM admin_audit_log WHERE target_id = :id"), {"id": aid})).all()
    assert [(a.action, a.actor_label) for a in audit] == [("announcement.sent", "Ilan")] * 2


async def test_pictures_are_checked(client, world):
    w = world
    aid = await _new(client, w)
    bad = await client.post(f"/admin/announcements/{aid}/images", json={"content_type": "application/pdf",
                                                                        "data_base64": PNG}, headers=w["admin"])
    assert bad.status_code == 422
    for _ in range(4):
        assert (await client.post(f"/admin/announcements/{aid}/images",
                                  json={"content_type": "image/png", "data_base64": PNG}, headers=w["admin"])).status_code == 201
    fifth = await client.post(f"/admin/announcements/{aid}/images", json={"content_type": "image/png", "data_base64": PNG},
                              headers=w["admin"])
    assert fifth.status_code == 422
    assert (await client.delete(f"/admin/announcements/{aid}/images/0", headers=w["admin"])).status_code == 204


async def test_guard_only_a_platform_admin(client, world):
    w = world
    assert (await client.get("/admin/announcements", headers=w["company_admin"])).status_code == 403
    assert (await client.post("/admin/announcements/audience", json={}, headers=w["company_admin"])).status_code == 403
