"""Clients and contract terms (NXT-01): who the company builds for, and the terms of each project's contract.

Tables from migration 0522 (``clients``, ``project_contracts``). The terms are what the RA bills (NXT-02) use: the
contract value, retention %, the mobilisation advance and how much of each bill recovers it, GST % and TDS %.

Every function takes the request's connection and never commits.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

CLIENT_FIELDS = ("name", "contact_person", "phone", "email", "gstin", "address", "notes")
TERM_FIELDS = ("contract_no", "contract_value", "signed_on", "retention_pct", "mobilisation_advance",
               "advance_recovery_pct", "gst_pct", "tds_pct", "defect_liability_months", "payment_terms", "notes")


async def list_clients(conn: AsyncConnection, org: uuid.UUID) -> list[dict[str, Any]]:
    """The company's clients, each with its projects and their contract value."""
    clients = [dict(r) for r in (await conn.execute(text(
        "SELECT id, name, contact_person, phone, email, gstin, address, notes FROM clients "
        "WHERE organization_id = :org ORDER BY lower(name)"), {"org": org})).mappings()]
    projects = (await conn.execute(text(
        "SELECT c.client_id, p.id, p.name, c.contract_value FROM project_contracts c "
        "JOIN projects p ON p.id = c.project_id WHERE c.organization_id = :org AND c.client_id IS NOT NULL "
        "ORDER BY lower(p.name)"), {"org": org})).mappings().all()
    by_client: dict[Any, list[dict]] = {}
    for p in projects:
        by_client.setdefault(p["client_id"], []).append(
            {"id": p["id"], "name": p["name"], "contract_value": p["contract_value"]})
    for c in clients:
        c["projects"] = by_client.get(c["id"], [])
    return clients


async def get_client(conn: AsyncConnection, org: uuid.UUID, client_id: uuid.UUID) -> dict[str, Any] | None:
    row = (await conn.execute(text(
        "SELECT id, name, contact_person, phone, email, gstin, address, notes FROM clients "
        "WHERE organization_id = :org AND id = :id"), {"org": org, "id": client_id})).mappings().first()
    return dict(row) if row else None


async def client_named(conn: AsyncConnection, org: uuid.UUID, name: str, exclude: uuid.UUID | None = None) -> Any:
    return (await conn.execute(text(
        "SELECT id FROM clients WHERE organization_id = :org AND lower(name) = lower(:n) "
        "AND (CAST(:x AS uuid) IS NULL OR id <> CAST(:x AS uuid))"),
        {"org": org, "n": name, "x": exclude})).scalar()


async def create_client(conn: AsyncConnection, org: uuid.UUID, values: dict[str, Any], user_id: uuid.UUID) -> Any:
    cols = [k for k in CLIENT_FIELDS if k in values]
    return (await conn.execute(text(
        f"INSERT INTO clients (organization_id, created_by, {', '.join(cols)}) "  # noqa: S608 (fixed column names)
        f"VALUES (:org, :by, {', '.join(':' + c for c in cols)}) RETURNING id"),
        {"org": org, "by": user_id, **{c: values[c] for c in cols}})).scalar_one()


async def update_client(conn: AsyncConnection, org: uuid.UUID, client_id: uuid.UUID, values: dict[str, Any]) -> None:
    cols = [k for k in CLIENT_FIELDS if k in values]
    if not cols:
        return
    await conn.execute(text(
        f"UPDATE clients SET {', '.join(f'{c} = :{c}' for c in cols)}, updated_at = now() "  # noqa: S608
        "WHERE organization_id = :org AND id = :id"), {"org": org, "id": client_id, **{c: values[c] for c in cols}})


async def get_contract(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID) -> dict[str, Any] | None:
    row = (await conn.execute(text(
        f"SELECT c.client_id, cl.name AS client_name, {', '.join('c.' + f for f in TERM_FIELDS)}, c.updated_at "  # noqa: S608
        "FROM project_contracts c LEFT JOIN clients cl ON cl.id = c.client_id "
        "WHERE c.organization_id = :org AND c.project_id = :p"), {"org": org, "p": project_id})).mappings().first()
    return dict(row) if row else None


async def put_contract(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID, client_id: Any,
                       terms: dict[str, Any], user_id: uuid.UUID) -> None:
    """Create or replace the project's contract terms (every term field is written: one not sent becomes empty)."""
    values = {f: terms.get(f) for f in TERM_FIELDS}
    await conn.execute(text(
        f"INSERT INTO project_contracts (project_id, organization_id, client_id, updated_by, {', '.join(TERM_FIELDS)}) "  # noqa: S608
        f"VALUES (:p, :org, :client, :by, {', '.join(':' + f for f in TERM_FIELDS)}) "
        "ON CONFLICT (project_id) DO UPDATE SET client_id = EXCLUDED.client_id, updated_by = EXCLUDED.updated_by, "
        f"updated_at = now(), {', '.join(f'{f} = EXCLUDED.{f}' for f in TERM_FIELDS)}"),
        {"p": project_id, "org": org, "client": client_id, "by": user_id, **values})


async def name_project_client(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID, name: str,
                              old_name: str | None) -> None:
    """``projects.client`` (the free-text name shown across the app) follows the contract's client, unless someone
    typed a different name there."""
    await conn.execute(text(
        "UPDATE projects SET client = :n, updated_at = now() WHERE organization_id = :org AND id = :p "
        "AND (client IS NULL OR btrim(client) = '' OR lower(client) = lower(CAST(:old AS text)))"),
        {"n": name, "org": org, "p": project_id, "old": old_name})
