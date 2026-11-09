"""The company activity log, read (ADM-02): who changed what, when. Owner and admins (``may_read_activity_log``).

  GET /activity    newest first: who, web or WhatsApp, the action, the record (kind, id, ref or name), when.
                   Filters: person, days (the company's calendar), source, record kind, words; ``before`` pages back.

Rows are written by the one recorder (``mesiri.http.activity``, ADM-01). Read only: nothing here changes a row.
"""

from __future__ import annotations

import base64
import datetime
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.application.dpr.project_day import local_date_sql
from mesiri.authorization.context import AuthorizationContext
from mesiri.authorization.roles import may_read_activity_log
from mesiri.domains.projects.router import get_auth_context
from mesiri.infrastructure.postgres.dependency import get_db_conn

router = APIRouter(tags=["activity"])

_COLUMNS = ("id", "at", "actor_user_id", "actor_name", "actor_role", "source", "method", "route", "action",
            "record_kind", "record_id", "record_label", "path_ids", "status_code")


def _cursor(at: datetime.datetime, row_id: Any) -> str:
    return base64.urlsafe_b64encode(f"{at.isoformat()}|{row_id}".encode()).decode()


def _uncursor(value: str) -> tuple[datetime.datetime, uuid.UUID]:
    try:
        at, row_id = base64.urlsafe_b64decode(value.encode()).decode().split("|")
        return datetime.datetime.fromisoformat(at), uuid.UUID(row_id)
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=422, detail="before is not a cursor this list gave") from exc


def _out(row: dict[str, Any]) -> dict[str, Any]:
    out = {k: row[k] for k in _COLUMNS}
    out["id"] = str(out["id"])
    out["at"] = row["at"].isoformat()
    out["actor_user_id"] = str(row["actor_user_id"]) if row["actor_user_id"] else None
    return out


@router.get("/activity")
async def activity(
    user_id: uuid.UUID | None = Query(default=None, description="Only this person's changes"),
    date_from: datetime.date | None = Query(default=None, description="From this day (the company's calendar)"),
    date_to: datetime.date | None = Query(default=None, description="To this day, inclusive"),
    source: Literal["web", "whatsapp"] | None = None,
    kind: str | None = Query(default=None, max_length=60, description="Record kind: task, ra_bill, request, ..."),
    q: str | None = Query(default=None, max_length=100, description="Words in the action or the record's ref / name"),
    before: str | None = Query(default=None, description="The `next` value of the previous page"),
    limit: int = Query(default=100, ge=1, le=200),
    auth: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
) -> dict[str, Any]:
    """Who changed what, when: every save, edit, delete and approval, on the web and on WhatsApp, newest first."""
    if not may_read_activity_log(auth.role):
        raise HTTPException(status_code=403, detail="The activity log is for the owner and admins.")
    where, params = ["a.organization_id = :org"], {"org": auth.organization_id, "n": limit + 1}
    day = local_date_sql("a.at", ":org")
    if user_id:
        where.append("a.actor_user_id = :u")
        params["u"] = user_id
    if date_from:
        where.append(f"{day} >= :df")
        params["df"] = date_from
    if date_to:
        where.append(f"{day} <= :dt")
        params["dt"] = date_to
    if source:
        where.append("a.source = :src")
        params["src"] = source
    if kind:
        where.append("a.record_kind = :kind")
        params["kind"] = kind
    if q and q.strip():
        where.append("(a.action ILIKE :q OR a.record_label ILIKE :q OR a.actor_name ILIKE :q)")
        params["q"] = f"%{q.strip()}%"
    if before:
        at, row_id = _uncursor(before)
        where.append("(a.at, a.id) < (:bat, :bid)")
        params.update(bat=at, bid=row_id)
    rows = [dict(r) for r in (await conn.execute(text(
        f"SELECT a.id, a.at, a.actor_user_id, COALESCE(u.full_name, a.actor_name) AS actor_name, a.actor_role, "  # noqa: S608
        f"a.source, a.method, a.route, a.action, a.record_kind, a.record_id, a.record_label, a.path_ids, a.status_code "
        f"FROM activity_log a LEFT JOIN users u ON u.id = a.actor_user_id WHERE {' AND '.join(where)} "
        f"ORDER BY a.at DESC, a.id DESC LIMIT :n"), params)).mappings()]
    more = len(rows) > limit
    rows = rows[:limit]
    people = [{"id": str(r["id"]), "name": r["full_name"]} for r in (await conn.execute(text(
        "SELECT DISTINCT u.id, u.full_name FROM activity_log a JOIN users u ON u.id = a.actor_user_id "
        "WHERE a.organization_id = :org ORDER BY u.full_name"), {"org": auth.organization_id})).mappings()]
    return {"items": [_out(r) for r in rows], "people": people,
            "next": _cursor(rows[-1]["at"], rows[-1]["id"]) if more and rows else None}
