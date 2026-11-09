"""Hand over a person's open work (ADM-03, decided in session by Ilan 9 Nov 2026): when someone leaves or changes job,
the owner or an admin moves what is still theirs to another person in one step.

What moves (D-A3):
- **open tasks** (open, doing, blocked) assigned to them, each through the tasks module's own reassign
  (``tasks.router.update_task``), so its rules apply and its history says who moved it, from whom, to whom;
- **schedule activities** (``work_packages.assigned_user_id``).

Only where the new person reaches the project (their real access, ``AuthorizationService``); the rest is listed as
left behind, with the project, so nothing moves to someone who could not open it. Deactivating the person stays the
Team page's own action. ``preview`` says what would move and saves nothing.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.authorization.context import AuthorizationContext


async def _person(conn: AsyncConnection, org: uuid.UUID, user_id: uuid.UUID) -> dict[str, Any]:
    row = (await conn.execute(text(
        "SELECT id, full_name, role, status FROM users WHERE id = :u AND organization_id = :org"),
        {"u": user_id, "org": org})).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Person not found")
    return dict(row)


async def _reaches(conn: AsyncConnection, org: uuid.UUID, person: dict[str, Any]) -> Any:
    """The project access of the person taking over: None for all projects, else the set they reach."""
    from mesiri.authorization.service import AuthorizationService

    try:
        ctx = await AuthorizationService(conn).resolve_from_jwt(person["id"], org, person["role"])
    except HTTPException as exc:
        raise HTTPException(status_code=422, detail=f"{person['full_name']} cannot take over: their account is not "
                                                    "active.") from exc
    return None if ctx.project_scope.grants_all_org_projects else set(ctx.project_scope.project_ids)


async def plan(conn: AsyncConnection, org: uuid.UUID, from_id: uuid.UUID, to_id: uuid.UUID) -> dict[str, Any]:
    """What would move from one person to the other, and what stays because the new person cannot reach it."""
    if from_id == to_id:
        raise HTTPException(status_code=422, detail="Pick someone else to take over")
    giver = await _person(conn, org, from_id)
    taker = await _person(conn, org, to_id)
    reach = await _reaches(conn, org, taker)

    tasks = [dict(r) for r in (await conn.execute(text(
        "SELECT t.id, t.number, t.title, t.status, t.due_date, t.project_id, p.name AS project_name "
        "FROM tasks t JOIN projects p ON p.id = t.project_id WHERE t.organization_id = :org "
        "AND t.assignee_user_id = :u AND t.status IN ('open', 'doing', 'blocked') ORDER BY t.due_date NULLS LAST, t.number"),
        {"org": org, "u": from_id})).mappings()]
    activities = [dict(r) for r in (await conn.execute(text(
        "SELECT w.id, w.name, w.project_id, p.name AS project_name FROM work_packages w "
        "JOIN projects p ON p.id = w.project_id WHERE w.organization_id = :org AND w.assigned_user_id = :u "
        "AND COALESCE(w.status::text, '') <> 'COMPLETED' ORDER BY p.name, w.sort_order"),
        {"org": org, "u": from_id})).mappings()]

    def split(rows: list[dict]) -> tuple[list[dict], list[dict]]:
        ok = [r for r in rows if reach is None or r["project_id"] in reach]
        return ok, [r for r in rows if r not in ok]

    t_move, t_stay = split(tasks)
    a_move, a_stay = split(activities)
    from mesiri.domains.tasks import logic

    def task_out(r: dict) -> dict:
        return {"id": str(r["id"]), "ref": logic.ref(r["number"]), "title": r["title"], "status": r["status"],
                "due_date": r["due_date"].isoformat() if r["due_date"] else None, "project_name": r["project_name"]}

    def act_out(r: dict) -> dict:
        return {"id": str(r["id"]), "name": r["name"], "project_name": r["project_name"]}

    return {
        "from": {"id": str(giver["id"]), "name": giver["full_name"]},
        "to": {"id": str(taker["id"]), "name": taker["full_name"]},
        "tasks": [task_out(r) for r in t_move], "activities": [act_out(r) for r in a_move],
        "left": {"tasks": [task_out(r) for r in t_stay], "activities": [act_out(r) for r in a_stay]},
        "_ids": {"tasks": [r["id"] for r in t_move], "activities": [r["id"] for r in a_move]},
    }


async def hand_over(conn: AsyncConnection, auth: AuthorizationContext, from_id: uuid.UUID, to_id: uuid.UUID) -> dict:
    """Move it. Each task through the tasks module's own reassign (its checks, its history); activities in one go."""
    from mesiri.domains.schedule import store as schedule_store
    from mesiri.domains.tasks.router import TaskPatch, update_task

    result = await plan(conn, auth.organization_id, from_id, to_id)
    ids = result.pop("_ids")
    for task_id in ids["tasks"]:
        await update_task(task_id, TaskPatch(assignee_user_id=to_id), auth=auth, conn=conn)
    for activity_id in ids["activities"]:
        await schedule_store.update_section(conn, activity_id, {"assigned_user_id": to_id})
    result["moved"] = {"tasks": len(ids["tasks"]), "activities": len(ids["activities"])}
    return result
