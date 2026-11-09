"""PostgreSQL reads and writes for tasks (TSK-01): ``tasks`` and their history ``task_events`` (0533).

Every function takes the request's connection and never commits.
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

_SELECT = """
SELECT t.*, p.name AS project_name, s.name AS site_name,
       au.full_name AS assignee_name, v.name AS assignee_vendor_name,
       ln.name AS place_name, wp.name AS activity_name, cu.full_name AS created_by_name,
       si.issue_type, si.narrative AS issue_narrative, si.status AS issue_status,
       pi.work_type AS line_work, lu.code AS line_unit
  FROM tasks t
  JOIN projects p ON p.id = t.project_id
  LEFT JOIN sites s ON s.id = t.site_id
  LEFT JOIN users au ON au.id = t.assignee_user_id
  LEFT JOIN vendors v ON v.id = t.assignee_vendor_id
  LEFT JOIN location_nodes ln ON ln.id = t.place_id
  LEFT JOIN work_packages wp ON wp.id = t.work_package_id
  LEFT JOIN users cu ON cu.id = t.created_by
  LEFT JOIN site_issues si ON si.id = t.site_issue_id
  LEFT JOIN work_package_planned_items pi ON pi.id = t.planned_item_id
  LEFT JOIN units_of_measure lu ON lu.id = pi.unit_id
"""

#: Fields a task row may be given or changed through ``insert`` / ``update``.
FIELDS = ("site_id", "title", "notes", "priority", "due_date", "assignee_user_id", "assignee_vendor_id",
          "assignee_team", "place_id", "work_package_id", "planned_item_id", "expected_quantity", "site_issue_id")


async def project(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID) -> dict | None:
    row = (await conn.execute(text("SELECT id, name FROM projects WHERE id = :p AND organization_id = :org"),
                              {"p": project_id, "org": org})).mappings().first()
    return dict(row) if row else None


async def sites(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID) -> list[dict]:
    rows = await conn.execute(text("SELECT id, name FROM sites WHERE organization_id = :org AND project_id = :p "
                                   "ORDER BY name"), {"org": org, "p": project_id})
    return [dict(r) for r in rows.mappings().all()]


async def people(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID) -> list[dict]:
    """Active people who work on the project (org-wide admins and owners always do): who a task can be for."""
    rows = await conn.execute(text(
        "SELECT DISTINCT u.id, u.full_name AS name, u.role FROM users u "
        "LEFT JOIN project_members m ON m.user_id = u.id AND m.project_id = :p "
        "WHERE u.organization_id = :org AND u.status = 'active' AND COALESCE(u.full_name, '') <> '' "
        "AND (m.id IS NOT NULL OR upper(u.role) IN ('ADMIN', 'OWNER', 'SUPER_ADMIN')) ORDER BY 2"),
        {"org": org, "p": project_id})
    return [dict(r) for r in rows.mappings().all()]


async def subcontractors(conn: AsyncConnection, org: uuid.UUID) -> list[dict]:
    rows = await conn.execute(text("SELECT id, name FROM vendors WHERE organization_id = :org AND kind = 'subcontractor' "
                                   "AND COALESCE(status, 'active') = 'active' ORDER BY name"), {"org": org})
    return [dict(r) for r in rows.mappings().all()]


async def boq_lines(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID) -> list[dict]:
    """The project's current BOQ lines for a picker: what the work is, its unit and section. No rates (anyone who
    gives tasks may pick a line; rates are for the money roles)."""
    from mesiri.infrastructure.postgres.repositories.boq import PostgresBoqRepository

    sections = {s["id"]: s["name"] for s in await PostgresBoqRepository(conn).list_sections(org, project_id)}
    return [{"id": ln["id"], "work": ln["work_type"], "unit": ln["unit"], "planned_quantity": ln["planned_quantity"],
             "work_package_id": ln["work_package_id"], "section": sections.get(ln["work_package_id"])}
            for ln in await PostgresBoqRepository(conn).list_lines(org, project_id)]


async def places(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID) -> list[dict]:
    """The project's places as people say them ("First Floor / Room-2"), for a picker."""
    from mesiri.domains.places import store as places_store

    return [{"id": p["id"], "label": p["label"], "site_id": p["site_id"]}
            for p in await places_store.places(conn, org, project_id)]


def num(value: Decimal | None) -> str | None:
    """A quantity as the BOQ shows it: "6", "12.5" (no trailing zeros, never "6E+1")."""
    return None if value is None else f"{value.normalize():f}"


async def progress(conn: AsyncConnection, org: uuid.UUID, tasks: list[dict]) -> dict[uuid.UUID, dict]:
    """For each task on a BOQ line: the work site recorded on that line since the task started (or was given), at its
    site when it has one, counted by the BOQ's own rule (``boq_router.counted_work``: the line's unit only, work on
    an older revision of the line still counts), so a task never disagrees with the BOQ page. Never typed (D-T4).

    Not by place: counted work carries no place yet, so a task at "First Floor / R2" counts the line's work on its
    whole site. The start day is the UTC day of ``started_at`` / ``created_at``."""
    from mesiri.domains.progress.boq_router import counted_work
    from mesiri.infrastructure.postgres.repositories.boq import PostgresBoqRepository

    out: dict[uuid.UUID, dict] = {}
    on_lines = [t for t in tasks if t.get("planned_item_id")]
    repo = PostgresBoqRepository(conn)
    for project_id in {t["project_id"] for t in on_lines}:
        lines = await repo.list_lines(org, project_id)
        current = await repo.current_revision_of(org, project_id)
        work = await counted_work(repo, org, project_id, lines)
        for t in (t for t in on_lines if t["project_id"] == project_id):
            line = current.get(t["planned_item_id"], t["planned_item_id"])
            since = (t.get("started_at") or t["created_at"]).date()
            mine = [w for w in work if w["line_id"] == line and w["work_date"] >= since
                    and (t.get("site_id") is None or w["site_id"] == t["site_id"])]
            done = sum((w["quantity"] for w in mine if w["quantity"] is not None), Decimal(0))
            expected = t.get("expected_quantity")
            out[t["id"]] = {"done": num(done), "expected": num(expected), "unit": t.get("line_unit"),
                            "other_unit": sum(1 for w in mine if w["quantity"] is None),
                            "pct": min(100, int(done * 100 / expected)) if expected else None}
    return out


async def section_of_line(conn: AsyncConnection, line_id: uuid.UUID) -> uuid.UUID | None:
    return (await conn.execute(text("SELECT work_package_id FROM work_package_planned_items WHERE id = :id"),
                               {"id": line_id})).scalar_one_or_none()


async def link_errors(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID, v: dict[str, Any]) -> list[str]:
    """What named in ``v`` is not of this project (or company): each one a sentence to show."""
    checks = (
        ("site_id", "SELECT 1 FROM sites WHERE id = :id AND project_id = :p AND organization_id = :org",
         "That site is not in this project"),
        ("place_id", "SELECT 1 FROM location_nodes WHERE id = :id AND project_id = :p AND organization_id = :org",
         "That place is not in this project"),
        ("work_package_id", "SELECT 1 FROM work_packages WHERE id = :id AND project_id = :p AND organization_id = :org",
         "That schedule activity is not in this project"),
        ("planned_item_id", "SELECT 1 FROM work_package_planned_items i JOIN work_packages w ON w.id = i.work_package_id "
                            "WHERE i.id = :id AND w.project_id = :p AND w.organization_id = :org",
         "That BOQ line is not in this project"),
        ("site_issue_id", "SELECT 1 FROM site_issues WHERE id = :id AND project_id = :p AND organization_id = :org",
         "That issue is not in this project"),
        ("assignee_vendor_id", "SELECT 1 FROM vendors WHERE id = :id AND organization_id = :org",
         "That subcontractor is not in this company"),
        ("assignee_user_id", "SELECT 1 FROM users WHERE id = :id AND organization_id = :org AND status = 'active'",
         "That person is not in this company"),
    )
    errors = []
    for key, sql, words in checks:
        if v.get(key) is not None and (await conn.execute(text(sql), {"id": v[key], "p": project_id, "org": org})).first() is None:
            errors.append(words)
    return errors


async def is_vendor(conn: AsyncConnection, org: uuid.UUID, vendor_id: uuid.UUID) -> bool:
    return (await conn.execute(text("SELECT 1 FROM vendors WHERE id = :id AND organization_id = :org"),
                               {"id": vendor_id, "org": org})).first() is not None


async def next_number(conn: AsyncConnection, project_id: uuid.UUID) -> int:
    """The next T-number of the project. The project row is locked first, so two tasks made at the same moment
    never get the same number (the unique index is the backstop)."""
    await conn.execute(text("SELECT 1 FROM projects WHERE id = :p FOR UPDATE"), {"p": project_id})
    return (await conn.execute(text("SELECT COALESCE(MAX(number), 0) + 1 FROM tasks WHERE project_id = :p"),
                               {"p": project_id})).scalar_one()


async def insert(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID, number: int, v: dict[str, Any], *,
                 source: str, user_id: uuid.UUID) -> uuid.UUID:
    cols = [k for k in FIELDS if v.get(k) is not None]
    names = ", ".join(["organization_id", "project_id", "number", "source", "created_by", *cols])
    values = ", ".join([":org", ":p", ":n", ":source", ":u", *[f":{k}" for k in cols]])
    return (await conn.execute(text(f"INSERT INTO tasks ({names}) VALUES ({values}) RETURNING id"),  # noqa: S608
                               {"org": org, "p": project_id, "n": number, "source": source, "u": user_id,
                                **{k: v[k] for k in cols}})).scalar_one()


async def update(conn: AsyncConnection, task_id: uuid.UUID, changes: dict[str, Any]) -> None:
    sets = ", ".join(f"{k} = :{k}" for k in changes)
    await conn.execute(text(f"UPDATE tasks SET {sets}, updated_at = now() WHERE id = :id"),  # noqa: S608
                       {"id": task_id, **changes})


async def add_event(conn: AsyncConnection, org: uuid.UUID, task_id: uuid.UUID, kind: str, *, user_id: uuid.UUID,
                    source: str, from_status: str | None = None, to_status: str | None = None,
                    words: str | None = None, media_object_key: str | None = None,
                    changes: dict[str, Any] | None = None) -> None:
    await conn.execute(text(
        "INSERT INTO task_events (organization_id, task_id, kind, from_status, to_status, text, media_object_key, "
        "changes, actor_user_id, source) VALUES (:org, :t, :kind, :fs, :ts, :words, :key, CAST(:changes AS jsonb), "
        ":u, :source)"),
        {"org": org, "t": task_id, "kind": kind, "fs": from_status, "ts": to_status, "words": words,
         "key": media_object_key, "changes": json.dumps(changes, default=str) if changes else None, "u": user_id,
         "source": source})


async def one(conn: AsyncConnection, org: uuid.UUID, task_id: uuid.UUID) -> dict | None:
    row = (await conn.execute(text(_SELECT + " WHERE t.id = :id AND t.organization_id = :org"),
                              {"id": task_id, "org": org})).mappings().first()
    return dict(row) if row else None


async def events(conn: AsyncConnection, org: uuid.UUID, task_id: uuid.UUID) -> list[dict]:
    rows = await conn.execute(text(
        "SELECT e.id, e.kind, e.from_status, e.to_status, e.text, e.media_object_key, e.changes, e.source, "
        "e.created_at, e.actor_user_id, u.full_name AS actor_name FROM task_events e "
        "LEFT JOIN users u ON u.id = e.actor_user_id WHERE e.task_id = :t AND e.organization_id = :org "
        "ORDER BY e.created_at, e.id"), {"t": task_id, "org": org})
    return [dict(r) for r in rows.mappings().all()]


async def listing(conn: AsyncConnection, org: uuid.UUID, *, project_ids: set[uuid.UUID] | None,
                  project_id: uuid.UUID | None, site_id: uuid.UUID | None, statuses: tuple[str, ...],
                  assignee_user_id: uuid.UUID | None, assignee_vendor_id: uuid.UUID | None,
                  q: str | None, limit: int) -> list[dict]:
    """Tasks of the company in these statuses (the caller filters by site scope and due day)."""
    where = ["t.organization_id = :org", "t.status = ANY(:statuses)"]
    params: dict[str, Any] = {"org": org, "statuses": list(statuses), "limit": limit}
    if project_ids is not None:
        where.append("t.project_id = ANY(:pids)")
        params["pids"] = list(project_ids)
    for key, value in (("project_id", project_id), ("site_id", site_id), ("assignee_user_id", assignee_user_id),
                       ("assignee_vendor_id", assignee_vendor_id)):
        if value is not None:
            where.append(f"t.{key} = :{key}")
            params[key] = value
    if q:
        where.append("(t.title ILIKE :q OR t.notes ILIKE :q OR t.assignee_team ILIKE :q)")
        params["q"] = f"%{q}%"
    rows = await conn.execute(text(_SELECT + " WHERE " + " AND ".join(where) +  # noqa: S608
                                   " ORDER BY t.due_date NULLS LAST, t.created_at DESC LIMIT :limit"), params)
    return [dict(r) for r in rows.mappings().all()]
