"""PostgreSQL reads and writes for the project documents register (DOC-01, DR-07). Every function takes the
request's connection and never commits; the file itself is put in object storage by the router."""

from __future__ import annotations

import datetime
import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.domains.documents.naming import RESTRICTED_FOLDERS

_COLS = ("id", "project_id", "site_id", "folder", "discipline", "number", "title", "revision", "revision_date",
         "status", "supersedes_id", "valid_until", "restricted", "object_key", "file_name", "content_type",
         "size_bytes", "pages", "source", "work_package_id", "work_order_id", "vendor_id", "goods_receipt_id", "notes",
         "uploaded_by", "created_at", "updated_at")
#: Every column of a document as read with the uploader's name (``d`` the document, ``u`` the user). PRC-52: a
#: delivery certificate names its GRN.
COLUMNS = (", ".join(f"d.{c}" for c in _COLS) + ", (d.facts IS NOT NULL) AS has_facts"
           ", (SELECT g.number FROM goods_receipts g WHERE g.id = d.goods_receipt_id) AS goods_receipt_number")


def _visible(see_restricted: bool) -> str:
    if see_restricted:
        return ""
    folders = ", ".join(f"'{f}'" for f in sorted(RESTRICTED_FOLDERS))
    return f" AND NOT d.restricted AND d.folder NOT IN ({folders})"


def is_restricted(doc: dict[str, Any]) -> bool:
    return bool(doc.get("restricted")) or doc.get("folder") in RESTRICTED_FOLDERS


async def project_name(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID) -> str | None:
    return (await conn.execute(text("SELECT name FROM projects WHERE id = :p AND organization_id = :org"),
                               {"p": project_id, "org": org})).scalar()


async def listing(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID, *, see_restricted: bool,
                  folder: str | None = None, status: str = "current", q: str | None = None,
                  work_package_id: uuid.UUID | None = None) -> list[dict[str, Any]]:
    where = ["d.organization_id = :org", "d.project_id = :p"]
    params: dict[str, Any] = {"org": org, "p": project_id}
    if status != "all":
        where.append("d.status = :status")
        params["status"] = status
    if folder:
        where.append("d.folder = :folder")
        params["folder"] = folder
    if work_package_id:
        where.append("d.work_package_id = :wp")
        params["wp"] = work_package_id
    if q:
        where.append("(d.title ILIKE :q OR d.number ILIKE :q OR d.file_name ILIKE :q)")
        params["q"] = f"%{q.strip()}%"
    rows = (await conn.execute(text(
        f"SELECT {COLUMNS}, u.full_name AS uploaded_by_name FROM project_documents d "
        f"LEFT JOIN users u ON u.id = d.uploaded_by WHERE {' AND '.join(where)}{_visible(see_restricted)} "
        "ORDER BY d.folder, d.number NULLS LAST, d.title, d.created_at DESC"), params)).mappings().all()
    return [dict(r) for r in rows]


async def counts(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID, *,
                 see_restricted: bool) -> dict[str, int]:
    rows = (await conn.execute(text(
        "SELECT d.folder, count(*) FROM project_documents d WHERE d.organization_id = :org AND d.project_id = :p "
        f"AND d.status = 'current'{_visible(see_restricted)} GROUP BY d.folder"),
        {"org": org, "p": project_id})).all()
    return {r[0]: int(r[1]) for r in rows}


async def expiring(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID, *, see_restricted: bool,
                   within_days: int = 30) -> list[dict[str, Any]]:
    rows = (await conn.execute(text(
        f"SELECT d.id, d.title, d.folder, d.valid_until FROM project_documents d WHERE d.organization_id = :org "
        f"AND d.project_id = :p AND d.status = 'current' AND d.valid_until IS NOT NULL "
        f"AND d.valid_until <= CURRENT_DATE + CAST(:days AS integer){_visible(see_restricted)} ORDER BY d.valid_until"),
        {"org": org, "p": project_id, "days": within_days})).mappings().all()
    return [dict(r) for r in rows]


async def one(conn: AsyncConnection, org: uuid.UUID, doc_id: uuid.UUID) -> dict[str, Any] | None:
    row = (await conn.execute(text(
        f"SELECT {COLUMNS}, u.full_name AS uploaded_by_name FROM project_documents d "
        "LEFT JOIN users u ON u.id = d.uploaded_by WHERE d.id = :id AND d.organization_id = :org"),
        {"id": doc_id, "org": org})).mappings().first()
    return dict(row) if row else None


async def facts(conn: AsyncConnection, org: uuid.UUID, doc_id: uuid.UUID) -> dict[str, Any] | None:
    value = (await conn.execute(text("SELECT facts FROM project_documents WHERE id = :id AND organization_id = :org"),
                                {"id": doc_id, "org": org})).scalar()
    return value if isinstance(value, dict) else (json.loads(value) if value else None)


async def history(conn: AsyncConnection, org: uuid.UUID, doc: dict[str, Any]) -> list[dict[str, Any]]:
    """Every revision of this document's number (or the supersedes chain when it has none), newest first."""
    if doc.get("number"):
        rows = (await conn.execute(text(
            "SELECT id, revision, status, file_name, created_at FROM project_documents WHERE organization_id = :org "
            "AND project_id = :p AND lower(number) = lower(:n) ORDER BY created_at DESC"),
            {"org": org, "p": doc["project_id"], "n": doc["number"]})).mappings().all()
        return [dict(r) for r in rows]
    out, seen, current = [], set(), doc
    while current and current["id"] not in seen:
        seen.add(current["id"])
        out.append({k: current.get(k) for k in ("id", "revision", "status", "file_name", "created_at")})
        current = await one(conn, org, current["supersedes_id"]) if current.get("supersedes_id") else None
    return out


async def same_file(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID, sha256: str) -> dict | None:
    row = (await conn.execute(text(
        "SELECT id, title, revision, status FROM project_documents WHERE organization_id = :org AND project_id = :p "
        "AND sha256 = :sha AND status <> 'archived' LIMIT 1"),
        {"org": org, "p": project_id, "sha": sha256})).mappings().first()
    return dict(row) if row else None


async def current_by_number(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID,
                            number: str | None) -> dict | None:
    if not number:
        return None
    row = (await conn.execute(text(
        "SELECT id, revision, title, folder, discipline, restricted FROM project_documents WHERE organization_id = "
        ":org AND project_id = :p AND status = 'current' AND lower(number) = lower(:n)"),
        {"org": org, "p": project_id, "n": number})).mappings().first()
    return dict(row) if row else None


async def insert(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID, values: dict[str, Any]) -> uuid.UUID:
    doc_id = values.pop("id", None) or uuid.uuid4()
    if values.get("supersedes_id"):
        await conn.execute(text(
            "UPDATE project_documents SET status = 'superseded', updated_at = now() WHERE id = :old "
            "AND organization_id = :org"), {"old": values["supersedes_id"], "org": org})
    cols = ["id", "organization_id", "project_id", *values.keys()]
    params = {"id": doc_id, "organization_id": org, "project_id": project_id, **values}
    if params.get("facts") is not None:
        params["facts"] = json.dumps(params["facts"], default=str)
    placeholders = ", ".join("CAST(:facts AS jsonb)" if c == "facts" else f":{c}" for c in cols)
    await conn.execute(text(f"INSERT INTO project_documents ({', '.join(cols)}) VALUES ({placeholders})"), params)
    return doc_id


async def update(conn: AsyncConnection, org: uuid.UUID, doc_id: uuid.UUID, values: dict[str, Any]) -> None:
    if not values:
        return
    sets = ", ".join(f"{k} = :{k}" for k in values)
    await conn.execute(text(f"UPDATE project_documents SET {sets}, updated_at = now() WHERE id = :id "
                            "AND organization_id = :org"), {**values, "id": doc_id, "org": org})


async def archive(conn: AsyncConnection, org: uuid.UUID, doc_id: uuid.UUID) -> None:
    """Archived: kept and hidden. When it was the current revision, the one it replaced becomes current again."""
    doc = await one(conn, org, doc_id)
    if doc is None:
        return
    await update(conn, org, doc_id, {"status": "archived"})
    if doc["status"] == "current" and doc.get("supersedes_id"):
        await conn.execute(text(
            "UPDATE project_documents SET status = 'current', updated_at = now() WHERE id = :old "
            "AND organization_id = :org AND status = 'superseded'"), {"old": doc["supersedes_id"], "org": org})


async def current_drawing_facts(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID) -> list[dict]:
    """DR-08: the facts of every current drawing with facts, newest first."""
    rows = (await conn.execute(text(
        "SELECT id, number, title, revision, facts FROM project_documents WHERE organization_id = :org "
        "AND project_id = :p AND status = 'current' AND facts IS NOT NULL ORDER BY created_at DESC"),
        {"org": org, "p": project_id})).mappings().all()
    return [dict(r) for r in rows]


def today() -> datetime.date:
    return datetime.date.today()
