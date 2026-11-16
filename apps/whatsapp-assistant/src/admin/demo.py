"""SA-30: reset a demo company in one tap (asked 2 Nov 2026: "a demo company you can reset in one tap").

For showing Mesiri to contractors in the field: the demo company is deleted and created again, with the same
people (same names, numbers, roles, the owner's password) and fresh sample data of the last two weeks (``sample_story.seed``, SS-65; SA-36: two
projects, four sites, a worker register, vendors, deliveries and use, attendance, work, expenses, weather, a transfer
and issues), so every demo starts from the same clean, believable state.

Safe by construction:
- only a company whose ``demo_company`` setting is true (set by the Mesiri team only) can be reset;
- platform admins only (the route), and the reset is in the audit log;
- the delete and the re-create are one transaction: a failure leaves the old demo as it was;
- the company goes through the one create-company step every company uses, and the sample records through the
  same API the dashboard and v3 use, as the demo's owner, so they pass the real checks. A sample record that fails
  is counted, never fatal: the demo is usable without it.

The demo comes back on v3 (``assistant_mode = api``) with its other settings kept, except the ones that hold
progress (join code, setup checklist, requests), which start fresh like a new company's.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

import sqlalchemy as sa

from mesiri.application.audit.record import record_admin_action
from mesiri.application.organizations.create_company import NewCompany, create_company
from mesiri.application.organizations.delete_company import delete_company

# SS-65: the story (what the sample records are) is shared with the learning sandbox; the reset is this file's.
from mesiri.application.organizations.sample_story import DEMO_PROJECT, DEMO_SITES, seed
from mesiri.domains.audit import actions as audit
from mesiri.domains.organizations import settings as org_settings

_log = logging.getLogger(__name__)

#: Settings that hold a company's progress, not its preferences: a fresh demo starts without them.
_FRESH_KEYS = frozenset({
    org_settings.JOIN_CODE, org_settings.JOIN_REQUESTS, org_settings.SETUP_PROGRESS, org_settings.GETTING_STARTED,
    org_settings.CONTINUE_REQUESTS, org_settings.BRANDING_REQUESTS,
})


class DemoResetError(Exception):
    def __init__(self, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.status = status


@dataclass
class DemoResetResult:
    organization_id: uuid.UUID
    name: str
    people: int
    seeded: dict[str, int] = field(default_factory=dict)
    failed: list[str] = field(default_factory=list)


async def _is_demo(conn: Any, org_id: uuid.UUID) -> bool:
    value = (await conn.execute(sa.text(
        "SELECT value FROM organization_settings WHERE organization_id = :o AND key = :k"),
        {"o": org_id, "k": org_settings.DEMO_COMPANY})).scalar()
    if isinstance(value, str):
        value = json.loads(value)
    return value is True


async def rebuild(conn: Any, org_id: uuid.UUID, *, actor: Any) -> tuple[uuid.UUID, dict[str, Any]]:
    """Inside the caller's transaction: delete the demo company and create it again with the same people and
    settings. Returns the new company id and what the sample-data step needs (owner, project, sites, people)."""
    org = (await conn.execute(sa.text("SELECT id, name, timezone FROM organizations WHERE id = :o"), {"o": org_id})).mappings().first()
    if org is None:
        raise DemoResetError("Organization not found", 404)
    if not await _is_demo(conn, org_id):
        raise DemoResetError("Only a company marked as a demo (demo_company = true) can be reset.")
    people = [dict(r) for r in (await conn.execute(sa.text(
        "SELECT id, full_name, email, whatsapp_number, role, status, hashed_password, access_policy FROM users "
        "WHERE organization_id = :o ORDER BY (role = 'ADMIN') DESC, created_at"), {"o": org_id})).mappings()]
    owner = next((p for p in people if p["role"] == "ADMIN"), None)
    if owner is None:
        raise DemoResetError("The demo company has no ADMIN to keep as its owner.")
    kept = [dict(r) for r in (await conn.execute(sa.text(
        "SELECT key, value FROM organization_settings WHERE organization_id = :o"), {"o": org_id})).mappings()
        if r["key"] not in _FRESH_KEYS]

    await delete_company(conn, org_id)  # the one delete step (records, then company, then people)

    created = await create_company(conn, NewCompany(
        name=org["name"], owner_name=owner["full_name"], owner_email=owner["email"], owner_phone=owner["whatsapp_number"],
        project_name=DEMO_PROJECT, site_names=DEMO_SITES, auto_dpr=True, signup_source="superadmin",
        timezone=org["timezone"] or "Asia/Kolkata",
    ), actor=actor)
    new_id = created.organization_id
    # The owner keeps their dashboard password.
    await conn.execute(sa.text("UPDATE users SET hashed_password = :h WHERE id = :u"),
                       {"h": owner["hashed_password"], "u": created.owner_user_id})
    others = []
    for p in people:
        if p["id"] == owner["id"]:
            continue
        uid = uuid.uuid4()
        await conn.execute(sa.text(
            "INSERT INTO users (id, organization_id, email, hashed_password, full_name, role, status, whatsapp_number, "
            "access_policy, created_at, updated_at) VALUES (:id, :o, :e, :h, :n, :r, :s, :w, CAST(:a AS json), now(), now())"),
            {"id": uid, "o": new_id, "e": p["email"], "h": p["hashed_password"], "n": p["full_name"], "r": p["role"],
             "s": p["status"] or "active", "w": p["whatsapp_number"],
             "a": None if p.get("access_policy") is None else json.dumps(p["access_policy"])})
        others.append({"id": uid, "role": p["role"]})
    settings = {r["key"]: r["value"] for r in kept}
    settings[org_settings.DEMO_COMPANY] = True
    settings[org_settings.ASSISTANT_MODE] = org_settings.ASSISTANT_MODE_API  # demos show v3
    settings[org_settings.ENABLED_MODULES] = list(org_settings.MODULES)  # and every module
    for key, value in settings.items():
        await conn.execute(sa.text(
            "INSERT INTO organization_settings (id, organization_id, key, value) VALUES (gen_random_uuid(), :o, :k, CAST(:v AS jsonb)) "
            "ON CONFLICT (organization_id, key) DO UPDATE SET value = EXCLUDED.value"),
            {"o": new_id, "k": key, "v": value if isinstance(value, str) and _is_json(value) else json.dumps(value)})
    await record_admin_action(conn, actor=actor, action=audit.COMPANY_DEMO_RESET, organization_id=new_id,
                              target_type="organization", target_id=new_id,
                              summary=f"Demo reset: {org['name']} created again with {len(people)} people",
                              details={"previous_organization_id": str(org_id), "people": len(people)})
    return new_id, {"name": org["name"], "owner_id": created.owner_user_id, "owner_name": owner["full_name"],
                    "project_id": created.project_id, "site_ids": [s.site_id for s in created.sites], "others": others,
                    "people": len(people)}


def _is_json(value: str) -> bool:
    try:
        json.loads(value)
    except ValueError:
        return False
    return True


async def reset_demo(engine: Any, database: Any, org_id: uuid.UUID, *, actor: Any, today: dt.date | None = None) -> DemoResetResult:
    """Delete and re-create the demo (one transaction), then add the sample records as its owner."""
    async with engine.begin() as conn:
        new_id, info = await rebuild(conn, org_id, actor=actor)
    from agent_api.app import build_api_app
    from agent_api.client import Actor, ApiClient

    app = build_api_app(database)
    # WEB-85: the estimate (BOQ) is the dashboard's, not one of the assistant's tools; the demo's own client reaches
    # it to give the second project an estimate. The assistant's app and its tools are unchanged.
    from mesiri.domains.progress.boq_router import router as boq_router

    app.include_router(boq_router)
    client = ApiClient(Actor(user_id=str(info["owner_id"]), organization_id=str(new_id), role="ADMIN", name=info["owner_name"]),
                       app=app)
    try:
        seeded, failed = await seed(client, info, today=today or dt.datetime.now(dt.UTC).date())
    finally:
        await client.close()
    if failed:
        _log.warning("demo_reset.sample_failed org=%s failed=%s", new_id, failed)
    return DemoResetResult(organization_id=new_id, name=info["name"], people=info["people"], seeded=seeded, failed=failed)
