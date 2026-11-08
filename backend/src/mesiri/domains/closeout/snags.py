"""The snag list (END-01): defects to put right before handover and in the defect period. Reads and writes.

A snag is numbered per project (SN-001 ...). open -> fixed (the site says it is done, with a note) -> closed (a
manager checked it). A fix that is not good goes back to open with the reason; a closed snag stays closed (a new
problem is a new snag). ``phase`` is taken from the project's stage when the snag is raised: in the defect period
the client's complaints are snags too, and the closeout page counts them apart.

Every function takes the request's connection and never commits.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

STATUSES = ("open", "fixed", "closed")
STATUS_WORDS = {"open": "Open", "fixed": "Fixed, to check", "closed": "Closed"}
EDITABLE = ("place", "description", "trade", "vendor_id", "site_id", "due_on", "found_by")

_SNAG = ("s.id, s.project_id, p.name AS project_name, s.site_id, si.name AS site_name, s.number, s.place, "
         "s.description, s.trade, s.vendor_id, v.name AS vendor_name, s.found_by, s.phase, s.status, s.due_on, "
         "s.fixed_note, s.fixed_at, s.closed_at, s.reopened_note, s.created_at, ru.full_name AS raised_by_name")


def ref(number: int) -> str:
    return f"SN-{number:03d}"


def _shape(row: Any) -> dict[str, Any]:
    s = dict(row)
    s["ref"] = ref(s["number"])
    s["status_label"] = STATUS_WORDS[s["status"]]
    return s


async def list_snags(conn: AsyncConnection, org: uuid.UUID, project_ids: set | None, *, status: str | None = None,
                     site_id: uuid.UUID | None = None) -> list[dict[str, Any]]:
    """Snags, open first then fixed then closed; in each, the oldest first (the order to work through them)."""
    sql = (f"SELECT {_SNAG} FROM project_snags s JOIN projects p ON p.id = s.project_id "  # noqa: S608
           "LEFT JOIN sites si ON si.id = s.site_id LEFT JOIN vendors v ON v.id = s.vendor_id "
           "LEFT JOIN users ru ON ru.id = s.raised_by WHERE s.organization_id = :org")
    params: dict[str, Any] = {"org": org}
    if project_ids is not None:
        sql += " AND s.project_id = ANY(:ps)"
        params["ps"] = list(project_ids)
    if status == "pending":  # open or fixed: everything not finished
        sql += " AND s.status <> 'closed'"
    elif status:
        sql += " AND s.status = :status"
        params["status"] = status
    if site_id is not None:
        sql += " AND s.site_id = :site"
        params["site"] = site_id
    sql += (" ORDER BY CASE s.status WHEN 'open' THEN 0 WHEN 'fixed' THEN 1 ELSE 2 END, lower(p.name), "
            "s.due_on NULLS LAST, s.number")
    return [_shape(r) for r in (await conn.execute(text(sql), params)).mappings()]


async def get(conn: AsyncConnection, org: uuid.UUID, snag_id: uuid.UUID) -> dict[str, Any] | None:
    row = (await conn.execute(text(
        f"SELECT {_SNAG} FROM project_snags s JOIN projects p ON p.id = s.project_id "  # noqa: S608
        "LEFT JOIN sites si ON si.id = s.site_id LEFT JOIN vendors v ON v.id = s.vendor_id "
        "LEFT JOIN users ru ON ru.id = s.raised_by WHERE s.organization_id = :org AND s.id = :id"),
        {"org": org, "id": snag_id})).mappings().first()
    return _shape(row) if row else None


async def counts(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID) -> dict[str, int]:
    """Per status, and per phase for the ones not closed."""
    rows = (await conn.execute(text(
        "SELECT status, phase, count(*) AS n FROM project_snags WHERE organization_id = :org AND project_id = :p "
        "GROUP BY status, phase"), {"org": org, "p": project_id})).mappings().all()
    out = {"open": 0, "fixed": 0, "closed": 0, "total": 0, "defects_pending": 0, "overdue": 0}
    for r in rows:
        out[r["status"]] += r["n"]
        out["total"] += r["n"]
        if r["phase"] == "defects" and r["status"] != "closed":
            out["defects_pending"] += r["n"]
    return out


async def overdue(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID, today: Any) -> int:
    return int((await conn.execute(text(
        "SELECT count(*) FROM project_snags WHERE organization_id = :org AND project_id = :p AND status = 'open' "
        "AND due_on < :today"), {"org": org, "p": project_id, "today": today})).scalar() or 0)


async def create(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID, stage: str, values: dict[str, Any],
                 user_id: uuid.UUID) -> Any:
    # One number per project: lock the project's row so two snags raised at once never get the same number.
    await conn.execute(text("SELECT 1 FROM projects WHERE id = :p FOR UPDATE"), {"p": project_id})
    number = (await conn.execute(text(
        "SELECT COALESCE(MAX(number), 0) + 1 FROM project_snags WHERE project_id = :p"), {"p": project_id})).scalar_one()
    phase = "defects" if stage in ("defects", "closed") else "before_handover"
    return (await conn.execute(text(
        "INSERT INTO project_snags (organization_id, project_id, site_id, number, place, description, trade, "
        "vendor_id, found_by, phase, due_on, raised_by) VALUES (:org, :p, :site, :n, :place, :d, :trade, :vendor, "
        ":found, :phase, :due, :by) RETURNING id"),
        {"org": org, "p": project_id, "site": values.get("site_id"), "n": number, "place": values.get("place"),
         "d": values["description"], "trade": values.get("trade"), "vendor": values.get("vendor_id"),
         "found": values.get("found_by") or "us", "phase": phase, "due": values.get("due_on"),
         "by": user_id})).scalar_one()


async def update(conn: AsyncConnection, snag_id: uuid.UUID, values: dict[str, Any]) -> None:
    cols = [c for c in EDITABLE if c in values]
    if cols:
        await conn.execute(text(
            f"UPDATE project_snags SET {', '.join(f'{c} = :{c}' for c in cols)}, updated_at = now() "  # noqa: S608
            "WHERE id = :id"), {"id": snag_id, **{c: values[c] for c in cols}})


async def mark_fixed(conn: AsyncConnection, snag_id: uuid.UUID, note: str | None, user_id: uuid.UUID) -> None:
    await conn.execute(text(
        "UPDATE project_snags SET status = 'fixed', fixed_note = :note, fixed_at = now(), fixed_by = :by, "
        "updated_at = now() WHERE id = :id"), {"id": snag_id, "note": note, "by": user_id})


async def close(conn: AsyncConnection, snag_id: uuid.UUID, user_id: uuid.UUID) -> None:
    await conn.execute(text(
        "UPDATE project_snags SET status = 'closed', closed_at = now(), closed_by = :by, updated_at = now() "
        "WHERE id = :id"), {"id": snag_id, "by": user_id})


async def reopen(conn: AsyncConnection, snag_id: uuid.UUID, reason: str) -> None:
    await conn.execute(text(
        "UPDATE project_snags SET status = 'open', reopened_note = :why, fixed_at = NULL, fixed_by = NULL, "
        "updated_at = now() WHERE id = :id"), {"id": snag_id, "why": reason})


async def delete(conn: AsyncConnection, snag_id: uuid.UUID) -> None:
    await conn.execute(text("DELETE FROM project_snags WHERE id = :id"), {"id": snag_id})
