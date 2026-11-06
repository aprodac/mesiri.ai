"""Joining a company with its code (SS-05): the reads and writes.

The rules (code format, requests, who decided) are in
domains/organizations/team_join.py; this module keeps them in
`organization_settings` (`join_code`, `join_requests`) and reads the people
to ask. Nothing here adds anyone to a company: an approved request goes on
through the same steps as sharing a contact (SS-13), on the WhatsApp side.

Every function takes the caller's connection and never commits.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.domains.organizations import lifecycle
from mesiri.domains.organizations import settings as settings_spec
from mesiri.domains.organizations import team_join as rules
from mesiri.infrastructure.postgres.repositories.organization_settings import (
    PostgresOrganizationSettingsRepository,
)
from mesiri.infrastructure.postgres.tenant import unscoped

#: Tries to find a code no other company holds before giving up.
_CODE_TRIES = 20


@dataclass(frozen=True, slots=True)
class Company:
    organization_id: uuid.UUID
    name: str


@dataclass(frozen=True, slots=True)
class Approver:
    user_id: uuid.UUID
    name: str
    whatsapp_number: str


async def _code_taken(conn: AsyncConnection, code: str) -> bool:
    async with unscoped(conn):
        return (
            await conn.execute(
                sa.text(
                    "SELECT 1 FROM organization_settings "
                    "WHERE key = :key AND upper(value ->> 'code') = :code LIMIT 1"
                ),
                {"key": settings_spec.JOIN_CODE, "code": code},
            )
        ).first() is not None


async def join_code(
    conn: AsyncConnection,
    organization_id: uuid.UUID,
    *,
    rotate: bool = False,
    now: dt.datetime,
    updated_by: uuid.UUID | None = None,
) -> str:
    """The company's code, made on first use. `rotate` replaces it: the old
    code stops working at once."""
    repo = PostgresOrganizationSettingsRepository(conn)
    stored = await repo.get(organization_id, settings_spec.JOIN_CODE)
    current = rules.normalize_code(stored.get("code")) if isinstance(stored, dict) else None
    if current and not rotate:
        return current
    name = (
        await conn.execute(
            sa.text("SELECT name FROM organizations WHERE id = :id"), {"id": organization_id}
        )
    ).scalar_one()
    for _ in range(_CODE_TRIES):
        code = rules.new_code(name)
        if code != current and not await _code_taken(conn, code):
            break
    else:  # pragma: no cover -- 10,000 codes per prefix
        raise RuntimeError("no free join code")
    await repo.set(
        organization_id,
        settings_spec.JOIN_CODE,
        {"code": code, "created_at": now.isoformat()},
        updated_by=updated_by,
    )
    return code


async def company_for_code(conn: AsyncConnection, code: str) -> Company | None:
    """The company a code belongs to, if it is using Mesiri right now (an
    ended trial or a suspended company takes no one new)."""
    async with unscoped(conn):
        row = (
            await conn.execute(
                sa.text(
                    "SELECT o.id, o.name FROM organization_settings st "
                    "JOIN organizations o ON o.id = st.organization_id "
                    "WHERE st.key = :key AND upper(st.value ->> 'code') = :code "
                    f"AND {lifecycle.operational_sql('o')} LIMIT 1"
                ),
                {"key": settings_spec.JOIN_CODE, "code": code},
            )
        ).mappings().first()
    return Company(organization_id=row["id"], name=row["name"]) if row else None


async def _requests_for_update(conn: AsyncConnection, organization_id: uuid.UUID) -> object:
    """The stored requests, with the row locked so two messages at once
    can't both add or both decide."""
    async with unscoped(conn):
        row = (
            await conn.execute(
                sa.text(
                    "SELECT value FROM organization_settings "
                    "WHERE organization_id = :org AND key = :key FOR UPDATE"
                ),
                {"org": organization_id, "key": settings_spec.JOIN_REQUESTS},
            )
        ).first()
    return row.value if row else []


async def _save_requests(
    conn: AsyncConnection, organization_id: uuid.UUID, requests: list[dict]
) -> None:
    async with unscoped(conn):
        await PostgresOrganizationSettingsRepository(conn).set(
            organization_id, settings_spec.JOIN_REQUESTS, requests, updated_by=None
        )


async def request_to_join(
    conn: AsyncConnection,
    organization_id: uuid.UUID,
    *,
    phone: str,
    name: str,
    now: dt.datetime,
) -> tuple[dict, bool]:
    """Record that `phone` asked to join; (the request, whether it is new).
    Raises rules.TooManyRequests when the company has too many open."""
    stored = await _requests_for_update(conn, organization_id)
    requests, request, is_new = rules.add_request(stored, phone=phone, name=name, now=now)
    if is_new:
        await _save_requests(conn, organization_id, requests)
    return request, is_new


async def decide_request(
    conn: AsyncConnection,
    organization_id: uuid.UUID,
    *,
    request_id: str,
    approve: bool,
    by: str,
    now: dt.datetime,
) -> tuple[dict | None, bool]:
    """Approve or reject an open request; (the request, whether this call
    decided it). Already decided or expired: unchanged, False."""
    stored = await _requests_for_update(conn, organization_id)
    requests, request, decided = rules.decide(
        stored, request_id=request_id, approve=approve, by=by, now=now
    )
    if decided:
        await _save_requests(conn, organization_id, requests)
    return request, decided


async def note_step(
    conn: AsyncConnection,
    organization_id: uuid.UUID,
    *,
    request_id: str,
    role: str | None = None,
    project: str | None = None,
    joined_at: dt.datetime | None = None,
) -> None:
    """Record an approved request's next step (rules.note_step)."""
    stored = await _requests_for_update(conn, organization_id)
    requests, changed = rules.note_step(
        stored, request_id=request_id, role=role, project=project, joined_at=joined_at
    )
    if changed:
        await _save_requests(conn, organization_id, requests)


async def joining_now(
    conn: AsyncConnection, organization_id: uuid.UUID, *, now: dt.datetime, hours: int = 24
) -> list[dict]:
    """Who asked to join, or was added by number, in the last `hours`, oldest
    first, for the company's Live screen: {"key", "name", "phone_tail",
    "source" ("code" | "added"), "step" ("asked" | "approved" | "role" |
    "joined" | "rejected"), "role", "project", "at"}. A request whose
    number is now in the company counts as joined, whatever was noted."""
    stored = await PostgresOrganizationSettingsRepository(conn).get(
        organization_id, settings_spec.JOIN_REQUESTS
    )
    since = now - dt.timedelta(hours=hours)
    users = (
        await conn.execute(
            sa.text(
                "SELECT u.id, u.full_name, u.whatsapp_number, u.created_at, "
                "regexp_replace(coalesce(u.whatsapp_number, ''), '\\D', '', 'g') AS digits, "
                "(SELECT pm.role::text FROM project_members pm WHERE pm.user_id = u.id "
                " ORDER BY pm.created_at DESC NULLS LAST LIMIT 1) AS member_role, "
                "(SELECT p.name FROM project_members pm JOIN projects p ON p.id = pm.project_id "
                " WHERE pm.user_id = u.id ORDER BY pm.created_at DESC NULLS LAST LIMIT 1) AS project "
                "FROM users u JOIN organizations o ON o.id = u.organization_id "
                "WHERE u.organization_id = :org AND u.whatsapp_number IS NOT NULL "
                "AND u.created_at >= :since "
                # The owner made with the company at sign-up didn't join it.
                "AND u.created_at > o.created_at + interval '5 minutes' "
                "ORDER BY u.created_at"
            ),
            {"org": organization_id, "since": since},
        )
    ).mappings().all()
    by_digits = {r["digits"]: r for r in users if r["digits"]}
    people: list[dict] = []
    seen: set[str] = set()
    for request in rules.recent(stored, now=now, hours=hours):
        phone = str(request.get("phone") or "")
        seen.add(phone)
        user = by_digits.get(phone)
        status = request.get("status")
        if user is not None or status == rules.JOINED:
            step = "joined"
        elif status == rules.REJECTED:
            step = "rejected"
        elif status == rules.APPROVED:
            step = "role" if request.get("role") else "approved"
        else:
            step = "asked"
        people.append(
            {
                "key": f"r-{request.get('id')}",
                "name": request.get("name") or "",
                "phone_tail": phone[-4:],
                "source": "code",
                "step": step,
                "role": (user and user["member_role"]) or request.get("role"),
                "project": (user and user["project"]) or request.get("project"),
                "at": request.get("requested_at"),
            }
        )
    for user in users:
        if user["digits"] in seen or not user["project"]:
            continue
        people.append(
            {
                "key": f"u-{user['id']}",
                "name": user["full_name"] or "",
                "phone_tail": user["digits"][-4:],
                "source": "added",
                "step": "joined",
                "role": user["member_role"],
                "project": user["project"],
                "at": user["created_at"].isoformat() if user["created_at"] else None,
            }
        )
    people.sort(key=lambda p: str(p["at"] or ""))
    return people


async def approvers(conn: AsyncConnection, organization_id: uuid.UUID) -> list[Approver]:
    """The company's active admins with a WhatsApp number: who is asked."""
    rows = (
        await conn.execute(
            sa.text(
                "SELECT id, full_name, whatsapp_number FROM users "
                "WHERE organization_id = :org AND upper(role::text) = 'ADMIN' "
                "AND lower(status::text) = 'active' AND whatsapp_number IS NOT NULL "
                "ORDER BY created_at"
            ),
            {"org": organization_id},
        )
    ).mappings().all()
    return [
        Approver(user_id=r["id"], name=r["full_name"] or "", whatsapp_number=r["whatsapp_number"])
        for r in rows
    ]
