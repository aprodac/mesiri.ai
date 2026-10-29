"""WA-87: the dashboard's site WhatsApp group endpoints against a real database.

Admins of the site's own company only; making a group goes through
runtime/group_chat.py (Meta faked here).

Run with a live database:
    pytest apps/whatsapp-assistant/tests/integration/test_whatsapp_group_router_postgres.py -m integration
"""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

import httpx
import jwt
import pytest
from fastapi import FastAPI
from sqlalchemy import text

from mesiri.application.organizations.create_company import NewCompany, create_company
from mesiri.bootstrap.settings import Settings
from mesiri.domains.identity.auth_service import ALGORITHM, SECRET_KEY
from mesiri.infrastructure.postgres.database import PostgresDatabase
from runtime.group_chat import GroupChat
from runtime.whatsapp_group_query import WhatsAppGroupQueryService
from whatsapp_groups.router import router

pytestmark = pytest.mark.integration


class _Meta:
    def __init__(self) -> None:
        self.created: list[str] = []

    async def create_group(self, subject, *, description=None):
        self.created.append(subject)
        return {"request_id": f"req-{uuid.uuid4().hex[:6]}"}


async def _company(db, name: str):
    async with db.transaction() as conn:
        return await create_company(
            conn,
            NewCompany(
                name=f"{name} {uuid.uuid4().hex[:6]}",
                owner_name="Owner",
                owner_phone=f"9194{uuid.uuid4().int % 10**8:08d}",
                project_name="Green Villa",
                site_names=("Block A",),
            ),
            now=dt.datetime(2026, 10, 28, 6, tzinfo=dt.UTC),
        )


def _token(org, user, role="ADMIN") -> dict[str, str]:
    token = jwt.encode({"sub": str(user), "org": str(org), "role": role}, SECRET_KEY, algorithm=ALGORITHM)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def world(monkeypatch):
    import projects.router as projects_router

    # The router's engine is made once per process; each test has its own loop.
    monkeypatch.setattr(projects_router, "_engine", None)
    db = PostgresDatabase(Settings().postgres)
    await db.connect()
    mine, theirs = await _company(db, "Router E2E"), await _company(db, "Other Co")
    meta = _Meta()
    chat = GroupChat(
        groups=WhatsAppGroupQueryService(db), client=meta, sender=None, actor_reader=None,
        outbox=None, enabled=True,
    )
    app = FastAPI()
    app.include_router(router)
    app.state.container = SimpleNamespace(group_chat=chat)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    try:
        yield client, chat, meta, mine, theirs
    finally:
        await client.aclose()
        async with db.transaction() as conn:
            for company in (mine, theirs):
                await conn.execute(text("DELETE FROM organizations WHERE id = :id"), {"id": company.organization_id})
        await db.disconnect()


def _url(company) -> str:
    return f"/projects/{company.project_id}/sites/{company.sites[0].site_id}/whatsapp-group"


async def test_an_admin_makes_the_site_group_once(world) -> None:
    client, _chat, meta, mine, _theirs = world
    headers = _token(mine.organization_id, mine.owner_user_id)

    before = await client.get(_url(mine), headers=headers)
    assert before.status_code == 200 and before.json()["status"] == "none" and before.json()["enabled"]

    made = await client.post(_url(mine), headers=headers)
    assert made.status_code == 200
    assert made.json()["status"] == "creating" and made.json()["name"] == "Block A · Mesiri"
    assert made.json()["message"].startswith("Making the WhatsApp group for Block A")

    again = await client.post(_url(mine), headers=headers)
    assert "already" in again.json()["message"]
    assert meta.created == ["Block A · Mesiri"]


async def test_only_admins_of_the_sites_own_company(world) -> None:
    client, _chat, meta, mine, theirs = world
    engineer = _token(mine.organization_id, mine.owner_user_id, role="SITE_ENGINEER")
    assert (await client.post(_url(mine), headers=engineer)).status_code == 403
    # Another company's admin cannot see or make this site's group.
    other_admin = _token(theirs.organization_id, theirs.owner_user_id)
    assert (await client.get(_url(mine), headers=other_admin)).status_code == 404
    assert (await client.post(_url(mine), headers=other_admin)).status_code == 404
    assert (await client.get(_url(mine))).status_code == 401
    assert meta.created == []


async def test_switched_off(world) -> None:
    client, chat, _meta, mine, _theirs = world
    chat.enabled = False
    headers = _token(mine.organization_id, mine.owner_user_id)
    assert (await client.get(_url(mine), headers=headers)).json() == {
        "enabled": False, "status": "none", "inviteLink": None, "name": None, "message": None,
    }
    assert (await client.post(_url(mine), headers=headers)).status_code == 503
