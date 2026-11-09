"""Client links (CV-01): the secret links a company sends its clients. Table from migration 0534.

A token is 32 random bytes (URL-safe base64, 43 characters). Only its SHA-256 is stored, so a database read, a backup
or a log of the table never yields a working link; the token is returned once, when the link is made. A revoked link
stops working at once.

Every function takes the request's connection and never commits.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

# token_urlsafe(32) gives 43 characters of [A-Za-z0-9_-]. Anything else is refused before the database is asked.
_TOKEN = re.compile(r"^[A-Za-z0-9_-]{43}$")

_SELECT = (
    "SELECT l.id, l.project_id, p.name AS project_name, l.label, l.created_at, u.full_name AS created_by_name, "
    "l.revoked_at, l.last_opened_at, l.open_count FROM client_links l JOIN projects p ON p.id = l.project_id "
    "LEFT JOIN users u ON u.id = l.created_by WHERE l.organization_id = :org"
)


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def well_formed(token: str) -> bool:
    return bool(_TOKEN.match(token or ""))


async def create(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID, label: str | None,
                 user_id: uuid.UUID | None) -> tuple[uuid.UUID, str]:
    """A new link for the project: its id and the token (the only time the token exists outside the client's hand)."""
    token = new_token()
    link_id = (await conn.execute(text(
        "INSERT INTO client_links (organization_id, project_id, token_hash, label, created_by) "
        "VALUES (:org, :p, :h, :label, :by) RETURNING id"),
        {"org": org, "p": project_id, "h": token_hash(token), "label": label, "by": user_id})).scalar_one()
    return link_id, token


async def list_links(conn: AsyncConnection, org: uuid.UUID, project_ids: set | None) -> list[dict[str, Any]]:
    sql, params = _SELECT, {"org": org}
    if project_ids is not None:
        sql += " AND l.project_id = ANY(:ps)"
        params["ps"] = list(project_ids)
    rows = (await conn.execute(text(sql + " ORDER BY l.revoked_at IS NOT NULL, l.created_at DESC"), params)).mappings()
    return [dict(r) for r in rows]


async def get(conn: AsyncConnection, org: uuid.UUID, link_id: uuid.UUID) -> dict[str, Any] | None:
    row = (await conn.execute(text(_SELECT + " AND l.id = :id"), {"org": org, "id": link_id})).mappings().first()
    return dict(row) if row else None


async def revoke(conn: AsyncConnection, org: uuid.UUID, link_id: uuid.UUID, user_id: uuid.UUID | None) -> None:
    await conn.execute(text(
        "UPDATE client_links SET revoked_at = now(), revoked_by = :by "
        "WHERE organization_id = :org AND id = :id AND revoked_at IS NULL"),
        {"org": org, "id": link_id, "by": user_id})


async def open_link(conn: AsyncConnection, token: str) -> dict[str, Any] | None:
    """The live link for a token (organization_id, project_id), counting the visit; None for a malformed, unknown or
    revoked token, or a project that is gone. Runs before any company is known: the token is what names it."""
    if not well_formed(token):
        return None
    row = (await conn.execute(text(
        "UPDATE client_links SET last_opened_at = now(), open_count = open_count + 1 "
        "WHERE token_hash = :h AND revoked_at IS NULL RETURNING id, organization_id, project_id"),
        {"h": token_hash(token)})).mappings().first()
    return dict(row) if row else None
