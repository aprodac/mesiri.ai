"""REST API for a project's start and schedule (ST-01, ST-04, ST-05).

  GET    /lifecycle/projects                       every project in scope: stage, dates, on time or late
  GET    /projects/{id}/start                      stage, dates and the project start checklist
  PATCH  /projects/{id}/start                      change the stage or the dates
  GET    /projects/{id}/schedule                   the Gantt: activities, links, state, knock-on, critical path
  POST   /projects/{id}/schedule/activities        add an activity or milestone that is not a BOQ section
  PATCH  /projects/{id}/schedule/activities/{aid}  dates, milestone, done, "starts after"; pushes what follows
  DELETE /projects/{id}/schedule/activities/{aid}  remove an activity with no BOQ lines and no site reports
  POST   /projects/{id}/schedule/sequence          place activities one after another from a day ("quick plan")

Reading the schedule needs no money role: it carries names, dates and quantities, never rates. Anyone on the
project sees it (the site engineer asks "what is planned this week?"). Changing it is for the roles that edit the
BOQ (``may_view_expenses``), the same sections. Plan: docs/plans/project-start-plan.md.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.authorization.context import AuthorizationContext
from mesiri.authorization.roles import may_view_expenses
from mesiri.domains.projects.router import get_auth_context
from mesiri.domains.schedule import logic, store
from mesiri.domains.shared.modules import require_module
from mesiri.infrastructure.postgres.dependency import get_db_conn

router = APIRouter(tags=["schedule"], dependencies=[Depends(require_module("dpr"))])

STAGE_WORDS = {
    "tender": "Tender", "won": "Won", "running": "Running", "handover": "Handover", "defects": "Defect period",
    "closed": "Closed",
}


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = " ".join(value.split())
    return value or None


class Predecessor(BaseModel):
    id: uuid.UUID
    lag: int = Field(default=0, ge=-365, le=365)


class StartUpdate(BaseModel):
    stage: str | None = None
    start_date: datetime.date | None = None
    planned_finish: datetime.date | None = None
    clear_dates: bool = False

    @field_validator("stage")
    @classmethod
    def _stage(cls, v: str | None) -> str | None:
        if v is not None and v not in store.STAGES:
            raise ValueError(f"stage must be one of {', '.join(store.STAGES)}")
        return v


class ActivityCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    start: datetime.date
    end: datetime.date | None = None
    milestone: bool = False
    site_id: uuid.UUID | None = None
    after: list[Predecessor] = Field(default_factory=list)

    _clean_name = field_validator("name")(_clean)

    @model_validator(mode="after")
    def _dates(self) -> ActivityCreate:
        if self.milestone or self.end is None:
            self.end = self.start if self.milestone else self.end
        if self.end is None:
            raise ValueError("an activity needs an end day (or make it a milestone)")
        if self.end < self.start:
            raise ValueError("the end is before the start")
        return self


class ActivityUpdate(BaseModel):
    """Only the fields sent change. ``push`` (default on): activities after this one that would now start too early
    move with it. ``preview``: say what would change, save nothing."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    start: datetime.date | None = None
    end: datetime.date | None = None
    clear_dates: bool = False
    milestone: bool | None = None
    done: bool | None = None
    site_id: uuid.UUID | None = None
    after: list[Predecessor] | None = None
    push: bool = True
    preview: bool = False

    _clean_name = field_validator("name")(_clean)


class SequenceItem(BaseModel):
    id: uuid.UUID
    days: int = Field(ge=0, le=1000, description="Working length in calendar days; 0 makes it a milestone")


class SequenceBody(BaseModel):
    start: datetime.date
    items: list[SequenceItem] = Field(min_length=1, max_length=500)
    link: bool = Field(default=True, description="Also link each to the one before (starts after)")


# -- access ------------------------------------------------------------------------------------------------------------

def _in_scope(auth: AuthorizationContext, project_id: uuid.UUID) -> None:
    if not auth.project_scope.grants_all_org_projects and project_id not in auth.project_scope.project_ids:
        raise HTTPException(status_code=403, detail="Not authorized for this project")


def _may_edit(auth: AuthorizationContext) -> bool:
    return may_view_expenses(auth.role)


def _require_edit(auth: AuthorizationContext) -> None:
    if not _may_edit(auth):
        raise HTTPException(status_code=403, detail="Only the owner, an admin, finance or a project manager can change "
                                                    "the schedule")


async def _project(conn: AsyncConnection, auth: AuthorizationContext, project_id: uuid.UUID) -> dict:
    _in_scope(auth, project_id)
    proj = await store.project(conn, auth.organization_id, project_id)
    if proj is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return proj


async def _today(conn: AsyncConnection, auth: AuthorizationContext) -> datetime.date:
    from mesiri.application.dpr.project_day import company_today

    return await company_today(conn, auth.organization_id)


def _iso(value: Any) -> Any:
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dict):
        return {k: _iso(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_iso(v) for v in value]
    return value


def _project_out(proj: dict) -> dict:
    return {"id": proj["id"], "name": proj["name"], "client": proj["client"], "stage": proj["stage"],
            "stage_label": STAGE_WORDS.get(proj["stage"], proj["stage"]), "start_date": proj["start_date"],
            "planned_finish": proj["planned_finish"]}


# -- lifecycle and project start -------------------------------------------------------------------------------------

@router.get("/lifecycle/projects")
async def projects_lifecycle(auth: AuthorizationContext = Depends(get_auth_context),
                             conn: AsyncConnection = Depends(get_db_conn)):
    """Every project in scope with its stage, dates and whether its schedule is on time: the Projects list chips."""
    from sqlalchemy import text

    rows = (await conn.execute(text(
        "SELECT id FROM projects WHERE organization_id = :org AND COALESCE(status, '') <> 'archived' ORDER BY name"),
        {"org": auth.organization_id})).scalars().all()
    today = await _today(conn, auth)
    out = []
    for pid in rows:
        if not auth.project_scope.grants_all_org_projects and pid not in auth.project_scope.project_ids:
            continue
        sched = await store.load(conn, auth.organization_id, pid, today)
        s = sched["summary"]
        out.append({**_project_out(sched["project"]), "scheduled": s["scheduled"], "activities": s["activities"],
                    "late": s["counts"].get(logic.LATE, 0), "behind": s["counts"].get(logic.BEHIND, 0),
                    "slip_days": s["slip_days"], "forecast_finish": s["forecast_finish"], "progress": s["progress"]})
    return _iso(out)


def _steps(proj: dict, c: dict) -> list[dict]:
    """The project start checklist, in the order a contractor does it, each with what is done and a next step."""
    dated = proj["start_date"] is not None and proj["planned_finish"] is not None
    steps = [
        {"key": "dates", "title": "Contract dates", "done": dated,
         "detail": "Start and finish set" if dated else "When work starts and when the client expects handover"},
        {"key": "contract", "title": "Client and contract", "done": c["contract"] > 0,
         "detail": ("The client and the contract terms are set" if c["contract"]
                    else "Who the client is, the contract value, retention and advance: the RA bills use them"),
         # Optional: only the owner, an admin or finance can set it (D-N3), so it never becomes a PM's "next" step.
         "optional": True},
        {"key": "boq", "title": "BOQ and budget", "done": c["lines"] > 0,
         "detail": (f"{c['lines']} lines in {c['sections']} sections, {c['priced_lines']} priced"
                    if c["lines"] else "Upload your estimate Excel: it becomes the BOQ, the budget and the schedule")},
        {"key": "schedule", "title": "Schedule", "done": c["sections"] > 0 and c["scheduled"] >= c["sections"],
         "detail": (f"{c['scheduled']} of {c['sections']} activities have dates, {c['links']} links"
                    if c["sections"] else "Dates for each part of the work, and what follows what")},
        {"key": "sites", "title": "Sites", "done": c["sites"] > 0,
         "detail": f"{c['sites']} site{'s' if c['sites'] != 1 else ''}" if c["sites"] else "Where the work happens"},
        {"key": "team", "title": "Site team on WhatsApp", "done": c["reporters"] > 0,
         "detail": (f"{c['reporters']} on the project with WhatsApp" if c["reporters"]
                    else "The engineers who send updates: their messages fill the schedule")},
        {"key": "suppliers", "title": "Suppliers and opening stock", "done": c["suppliers"] > 0,
         "detail": (f"{c['suppliers']} suppliers, {c['stock_moves']} stock entries" if c["suppliers"]
                    else "Suppliers with their phone and GSTIN, and what each site holds on day one"),
         "optional": True},
        {"key": "work_orders", "title": "Subcontract work orders", "done": c["work_orders"] > 0,
         "detail": (f"{c['work_orders']} work orders" if c["work_orders"]
                    else "Who does which BOQ work at what rate (optional)"), "optional": True},
    ]
    return steps


@router.get("/projects/{project_id}/start")
async def project_start(project_id: uuid.UUID, auth: AuthorizationContext = Depends(get_auth_context),
                        conn: AsyncConnection = Depends(get_db_conn)):
    proj = await _project(conn, auth, project_id)
    counts = await store.checklist(conn, auth.organization_id, project_id)
    steps = _steps(proj, counts)
    required = [s for s in steps if not s.get("optional")]
    nxt = next((s["key"] for s in required if not s["done"]), None) or next(
        (s["key"] for s in steps if not s["done"]), None)
    return _iso({"project": _project_out(proj), "steps": steps, "next": nxt,
                 "ready": all(s["done"] for s in required), "done": sum(1 for s in steps if s["done"]),
                 "total": len(steps), "counts": counts, "can_edit": _may_edit(auth),
                 "stages": [{"key": k, "label": v} for k, v in STAGE_WORDS.items()]})


@router.patch("/projects/{project_id}/start")
async def update_project_start(project_id: uuid.UUID, body: StartUpdate,
                               auth: AuthorizationContext = Depends(get_auth_context),
                               conn: AsyncConnection = Depends(get_db_conn)):
    from sqlalchemy import text

    proj = await _project(conn, auth, project_id)
    _require_edit(auth)
    start = None if body.clear_dates else (body.start_date or proj["start_date"])
    finish = None if body.clear_dates else (body.planned_finish or proj["planned_finish"])
    if start and finish and finish < start:
        raise HTTPException(status_code=422, detail="The finish is before the start")
    await conn.execute(text(
        "UPDATE projects SET stage = :stage, start_date = :s, planned_finish = :f, updated_at = now() WHERE id = :p"),
        {"stage": body.stage or proj["stage"], "s": start, "f": finish, "p": project_id})
    return await project_start(project_id, auth, conn)


# -- the schedule ----------------------------------------------------------------------------------------------------

@router.get("/projects/{project_id}/schedule")
async def get_schedule(project_id: uuid.UUID, auth: AuthorizationContext = Depends(get_auth_context),
                       conn: AsyncConnection = Depends(get_db_conn)):
    """The Gantt. Each activity (a BOQ section, or a step added here) with its planned days, progress measured from
    site reports, its state (done / on track / behind / late / not started), how many days the late work before it
    pushes it, and whether it is on the critical path. ``summary`` has the forecast finish."""
    await _project(conn, auth, project_id)
    sched = await store.load(conn, auth.organization_id, project_id, await _today(conn, auth))
    sched["project"] = _project_out(sched["project"])
    sched["can_edit"] = _may_edit(auth)
    return _iso(sched)


async def _check_site(conn: AsyncConnection, project_id: uuid.UUID, site_id: uuid.UUID | None) -> None:
    from sqlalchemy import text

    if site_id is not None and not (await conn.execute(
            text("SELECT 1 FROM sites WHERE id = :s AND project_id = :p"), {"s": site_id, "p": project_id})).first():
        raise HTTPException(status_code=422, detail="site_id is not a site of this project")


async def _check_predecessors(conn: AsyncConnection, auth: AuthorizationContext, project_id: uuid.UUID,
                              successor: uuid.UUID | None, after: list[Predecessor]) -> list[tuple[uuid.UUID, int]]:
    existing = await store.links(conn, auth.organization_id, project_id)
    others = [lk for lk in existing if lk["successor"] != successor]
    out = []
    for p in after:
        if await store.section(conn, auth.organization_id, project_id, p.id) is None:
            raise HTTPException(status_code=422, detail="A 'starts after' activity is not in this project's schedule")
        if successor is not None and logic.makes_cycle(others, p.id, successor):
            raise HTTPException(status_code=409, detail="That would make a circle: the other activity already comes "
                                                        "after this one")
        others.append({"predecessor": p.id, "successor": successor, "lag": p.lag})
        out.append((p.id, p.lag))
    return out


@router.post("/projects/{project_id}/schedule/activities", status_code=201)
async def create_activity(project_id: uuid.UUID, body: ActivityCreate,
                          auth: AuthorizationContext = Depends(get_auth_context),
                          conn: AsyncConnection = Depends(get_db_conn)):
    """An activity or milestone that is not a BOQ section ("Site mobilisation", "Handover"). Placed at the end."""
    await _project(conn, auth, project_id)
    _require_edit(auth)
    await _check_site(conn, project_id, body.site_id)
    from mesiri.infrastructure.postgres.repositories.boq import PostgresBoqRepository

    preds = await _check_predecessors(conn, auth, project_id, None, body.after)
    new_id = await PostgresBoqRepository(conn).create_section(
        auth.organization_id, project_id, body.name, body.site_id, None, auth.user_id)
    await store.update_section(conn, new_id, {"planned_start": body.start, "planned_end": body.end,
                                              "is_milestone": body.milestone})
    await store.replace_predecessors(conn, auth.organization_id, new_id, preds)
    return await _respond(conn, auth, project_id, moved=[], focus=new_id)


async def _respond(conn: AsyncConnection, auth: AuthorizationContext, project_id: uuid.UUID, *,
                   moved: list[dict], focus: uuid.UUID | None, saved: bool = True, finish_before: Any = None) -> dict:
    sched = await store.load(conn, auth.organization_id, project_id, await _today(conn, auth))
    sched["project"] = _project_out(sched["project"])
    sched["can_edit"] = _may_edit(auth)
    after = sched["summary"]["planned_finish"]
    return _iso({"saved": saved, "focus": focus, "moved": moved,
                 "finish_moves": (after - finish_before).days if after and finish_before else 0,
                 "schedule": sched})


@router.patch("/projects/{project_id}/schedule/activities/{activity_id}")
async def update_activity(project_id: uuid.UUID, activity_id: uuid.UUID, body: ActivityUpdate,
                          auth: AuthorizationContext = Depends(get_auth_context),
                          conn: AsyncConnection = Depends(get_db_conn)):
    """Change one activity. A new start or end moves the activities after it that would now start too early
    (``push``), keeping their length; ``moved`` lists them and ``finish_moves`` says how many days the project's
    last day moved. With ``preview`` nothing is saved: the same answer, rolled back."""
    await _project(conn, auth, project_id)
    _require_edit(auth)
    current = await store.section(conn, auth.organization_id, project_id, activity_id)
    if current is None:
        raise HTTPException(status_code=404, detail="Activity not found")
    await _check_site(conn, project_id, body.site_id)

    savepoint = await conn.begin_nested()
    try:
        result = await _apply_update(conn, auth, project_id, activity_id, current, body)
    except BaseException:
        await savepoint.rollback()
        raise
    if body.preview:
        await savepoint.rollback()
        result["saved"] = False
    else:
        await savepoint.commit()
    return result


async def _apply_update(conn: AsyncConnection, auth: AuthorizationContext, project_id: uuid.UUID,
                        activity_id: uuid.UUID, current: dict, body: ActivityUpdate) -> dict:
    org = auth.organization_id
    today = await _today(conn, auth)
    before = await store.load(conn, org, project_id, today)
    names = {a["id"]: a["name"] for a in before["activities"]}
    old_dates = {a["id"]: (a["start"], a["end"]) for a in before["activities"]}
    finish_before = before["summary"]["planned_finish"]

    changes: dict[str, Any] = {}
    if body.name is not None:
        changes["name"] = body.name
    if body.site_id is not None:
        changes["site_id"] = body.site_id
    milestone = current["is_milestone"] if body.milestone is None else body.milestone
    if body.milestone is not None:
        changes["is_milestone"] = body.milestone
    if body.done is not None:
        changes["status"] = "COMPLETED" if body.done else ("IN_PROGRESS" if current["actual_start"] else "NOT_STARTED")
        changes["actual_end"] = _finished_on(before, activity_id, current, today) if body.done else None
    if body.clear_dates:
        changes["planned_start"] = changes["planned_end"] = None
    start = body.start or current["planned_start"]
    end = body.end or current["planned_end"]
    if milestone:
        # A milestone is one day: the day given, else the day it already had.
        day = body.start or body.end or current["planned_start"]
        start = end = day
    dates_changed = not body.clear_dates and (body.start is not None or body.end is not None
                                              or (body.milestone is not None and start is not None))
    if dates_changed:
        if start is None or end is None:
            raise HTTPException(status_code=422, detail="Give both a start and an end the first time")
        if end < start:
            raise HTTPException(status_code=422, detail="The end is before the start")
        changes["planned_start"], changes["planned_end"] = start, end
    await store.update_section(conn, activity_id, changes)

    if body.after is not None:
        preds = await _check_predecessors(conn, auth, project_id, activity_id, body.after)
        await store.replace_predecessors(conn, org, activity_id, preds)

    moved: list[dict] = []
    if body.push and (dates_changed or body.after is not None):
        sched = await store.load(conn, org, project_id, today)
        acts = [{"id": a["id"], "name": a["name"], "start": a["start"], "end": a["end"], "milestone": a["milestone"],
                 "done": a["done"], "progress": None, "actual_start": None, "actual_end": None}
                for a in sched["activities"]]
        mine = next(a for a in acts if a["id"] == activity_id)
        if logic.scheduled(mine):
            # New dates the PM typed stay as typed; a new "starts after" alone may push this activity too.
            pinned = {activity_id: (mine["start"], mine["end"])} if dates_changed else {}
            new = {i: d for i, d in logic.push(acts, sched["links"], pinned).items() if i not in pinned}
            await store.set_dates(conn, new)
            for i, (s_day, e_day) in new.items():
                was = old_dates.get(i, (None, None))
                if was != (s_day, e_day):
                    moved.append({"id": i, "name": names.get(i, ""), "from_start": was[0], "from_end": was[1],
                                  "start": s_day, "end": e_day, "days": (s_day - was[0]).days if was[0] else None})
    return await _respond(conn, auth, project_id, moved=moved, focus=activity_id, finish_before=finish_before)


def _finished_on(sched: dict, activity_id: uuid.UUID, current: dict, today: datetime.date) -> datetime.date:
    """The day a "finished" activity ended: site's last report on it; else its planned end when that has passed (the
    PM marks it later, so today would make it look late); else today."""
    mine = next((a for a in sched["activities"] if a["id"] == activity_id), None)
    last = mine["last_update"] if mine else None
    if last:
        return min(last, today)
    if current["planned_end"] and current["planned_end"] < today:
        return current["planned_end"]
    return today


@router.delete("/projects/{project_id}/schedule/activities/{activity_id}", status_code=204)
async def delete_activity(project_id: uuid.UUID, activity_id: uuid.UUID,
                          auth: AuthorizationContext = Depends(get_auth_context),
                          conn: AsyncConnection = Depends(get_db_conn)):
    await _project(conn, auth, project_id)
    _require_edit(auth)
    if await store.section(conn, auth.organization_id, project_id, activity_id) is None:
        raise HTTPException(status_code=404, detail="Activity not found")
    why = await store.section_in_use(conn, activity_id)
    if why:
        raise HTTPException(status_code=409, detail=why)
    from sqlalchemy import text

    await conn.execute(text("DELETE FROM work_packages WHERE id = :id"), {"id": activity_id})
    return Response(status_code=204)


@router.post("/projects/{project_id}/schedule/sequence")
async def sequence(project_id: uuid.UUID, body: SequenceBody, auth: AuthorizationContext = Depends(get_auth_context),
                   conn: AsyncConnection = Depends(get_db_conn)):
    """Quick plan: put the given activities one after another from ``start``, each for its number of days (0 = a
    milestone), and link each to the one before. The fastest way from a BOQ to a first schedule."""
    await _project(conn, auth, project_id)
    _require_edit(auth)
    ids = [i.id for i in body.items]
    if len(set(ids)) != len(ids):
        raise HTTPException(status_code=422, detail="An activity is listed twice")
    for i in ids:
        if await store.section(conn, auth.organization_id, project_id, i) is None:
            raise HTTPException(status_code=422, detail="An activity is not in this project's schedule")
    day = body.start
    prev: uuid.UUID | None = None
    for item in body.items:
        milestone = item.days == 0
        end = day if milestone else day + logic.DAY * (item.days - 1)
        await store.update_section(conn, item.id, {"planned_start": day, "planned_end": end,
                                                   "is_milestone": milestone})
        if body.link and prev is not None:
            existing = await store.links(conn, auth.organization_id, project_id)
            keep = [(lk["predecessor"], lk["lag"]) for lk in existing
                    if lk["successor"] == item.id and lk["predecessor"] != prev
                    and not logic.makes_cycle([x for x in existing if x["successor"] != item.id],
                                              lk["predecessor"], item.id)]
            await store.replace_predecessors(conn, auth.organization_id, item.id, [(prev, 0), *keep])
        prev = item.id
        day = end if milestone else end + logic.DAY
    return await _respond(conn, auth, project_id, moved=[], focus=None)
