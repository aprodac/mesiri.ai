"""REST API for a project's start and schedule (ST-01, ST-04, ST-05).

  GET    /lifecycle/projects                       every project in scope: stage, dates, on time or late
  GET    /projects/{id}/start                      stage, dates and the project start checklist
  PATCH  /projects/{id}/start                      change the stage or the dates
  GET    /projects/{id}/schedule                   the Gantt: activities, links, state, knock-on, critical path
  POST   /projects/{id}/schedule/activities        add an activity or milestone that is not a BOQ section
  PATCH  /projects/{id}/schedule/activities/{aid}  dates, milestone, done, "starts after"; pushes what follows
  DELETE /projects/{id}/schedule/activities/{aid}  remove an activity with no BOQ lines and no site reports
  POST   /projects/{id}/schedule/sequence          place activities one after another from a day ("quick plan")
  POST   /projects/{id}/schedule/from-drawing      DR-05: add a drawing's draft activities, one after another
  POST   /projects/{id}/schedule/baselines         approve the programme as it stands (its dates are kept)
  GET    /projects/{id}/schedule/baselines         the approved programmes, newest first
  GET    /projects/{id}/schedule/export            the programme as an .xlsx, with the approved dates

Days are counted on the project's working calendar (``work_week``, ``holidays``; set with PATCH /start): a length is
working days, and Quick plan, "starts after" and the push skip the days off (QA Step 11, 23 Nov 2026).

Reading the schedule needs no money role: it carries names, dates and quantities, never rates. Anyone on the
project sees it (the site engineer asks "what is planned this week?"). Changing it is for the roles that edit the
BOQ (``may_view_expenses``), the same sections. Plan: docs/plans/project-start-plan.md.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import Response as FileResponse
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.authorization.context import AuthorizationContext
from mesiri.authorization.roles import may_view_expenses
from mesiri.domains.projects.router import get_auth_context
from mesiri.domains.schedule import logic, store
from mesiri.domains.shared.modules import require_module
from mesiri.http.activity import mark_saved_nothing, saves_nothing
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
    #: "FS": starts after the other ends (+ lag working days); "SS": starts with it (+ lag working days).
    kind: Literal["FS", "SS"] = "FS"


class StartUpdate(BaseModel):
    stage: str | None = None
    start_date: datetime.date | None = None
    planned_finish: datetime.date | None = None
    clear_dates: bool = False
    #: The days site works, Monday first ("1111110": Sunday off), and the holidays besides.
    work_week: str | None = Field(default=None, pattern=r"^[01]{7}$")
    holidays: list[datetime.date] | None = Field(default=None, max_length=120)

    @field_validator("work_week")
    @classmethod
    def _some_day(cls, v: str | None) -> str | None:
        if v is not None and "1" not in v:
            raise ValueError("site works on at least one day of the week")
        return v

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
    assigned_user_id: uuid.UUID | None = None
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
    #: Sent as null: the activity is for the whole project again / nobody in particular runs it.
    site_id: uuid.UUID | None = None
    assigned_user_id: uuid.UUID | None = None
    after: list[Predecessor] | None = None
    push: bool = True
    preview: bool = False

    _clean_name = field_validator("name")(_clean)


class SequenceItem(BaseModel):
    id: uuid.UUID
    days: int = Field(ge=0, le=1000, description="Working length in working days (the project's calendar); 0 makes "
                                                "it a milestone")


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
            "planned_finish": proj["planned_finish"], "work_week": proj.get("work_week") or "1111111",
            "holidays": sorted(proj.get("holidays") or [])}


def _cal(sched: dict) -> logic.Calendar:
    c = sched.get("calendar") or {}
    return logic.Calendar(c.get("work_week") or "1111111", c.get("holidays") or ())


def _for_role(sched: dict, auth: AuthorizationContext) -> dict:
    """Value shares are for the people who see money; the rest see the schedule without them."""
    if not _may_edit(auth):
        for a in sched["activities"]:
            a.pop("weight", None)
        sched.pop("people", None)  # only the people who change the schedule pick who runs an activity
    return sched


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
        "UPDATE projects SET stage = :stage, start_date = :s, planned_finish = :f, work_week = :w, "
        "holidays = CAST(:h AS date[]), updated_at = now() WHERE id = :p"),
        {"stage": body.stage or proj["stage"], "s": start, "f": finish, "p": project_id,
         "w": body.work_week or proj.get("work_week") or "1111111",
         "h": sorted(set(body.holidays)) if body.holidays is not None else sorted(proj.get("holidays") or [])})
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
    return _iso(_for_role(sched, auth))


async def _check_site(conn: AsyncConnection, project_id: uuid.UUID, site_id: uuid.UUID | None) -> None:
    from sqlalchemy import text

    if site_id is not None and not (await conn.execute(
            text("SELECT 1 FROM sites WHERE id = :s AND project_id = :p"), {"s": site_id, "p": project_id})).first():
        raise HTTPException(status_code=422, detail="site_id is not a site of this project")


async def _check_person(conn: AsyncConnection, auth: AuthorizationContext, user_id: uuid.UUID | None) -> None:
    from sqlalchemy import text

    if user_id is not None and not (await conn.execute(text(
            "SELECT 1 FROM users WHERE id = :u AND organization_id = :org AND status = 'active'"),
            {"u": user_id, "org": auth.organization_id})).first():
        raise HTTPException(status_code=422, detail="That person is not an active member of the company")


async def _check_predecessors(conn: AsyncConnection, auth: AuthorizationContext, project_id: uuid.UUID,
                              successor: uuid.UUID | None, after: list[Predecessor]) -> list[tuple[uuid.UUID, int, str]]:
    existing = await store.links(conn, auth.organization_id, project_id)
    others = [lk for lk in existing if lk["successor"] != successor]
    out = []
    for p in after:
        if await store.section(conn, auth.organization_id, project_id, p.id) is None:
            raise HTTPException(status_code=422, detail="A 'starts after' activity is not in this project's schedule")
        if successor is not None and logic.makes_cycle(others, p.id, successor):
            raise HTTPException(status_code=409, detail="That would make a circle: the other activity already comes "
                                                        "after this one")
        others.append({"predecessor": p.id, "successor": successor, "lag": p.lag, "kind": p.kind})
        out.append((p.id, p.lag, p.kind))
    return out


@router.post("/projects/{project_id}/schedule/activities", status_code=201)
async def create_activity(project_id: uuid.UUID, body: ActivityCreate,
                          auth: AuthorizationContext = Depends(get_auth_context),
                          conn: AsyncConnection = Depends(get_db_conn)):
    """An activity or milestone that is not a BOQ section ("Site mobilisation", "Handover"). Placed at the end."""
    await _project(conn, auth, project_id)
    _require_edit(auth)
    await _check_site(conn, project_id, body.site_id)
    await _check_person(conn, auth, body.assigned_user_id)
    from mesiri.infrastructure.postgres.repositories.boq import PostgresBoqRepository

    preds = await _check_predecessors(conn, auth, project_id, None, body.after)
    new_id = await PostgresBoqRepository(conn).create_section(
        auth.organization_id, project_id, body.name, body.site_id, None, auth.user_id)
    await store.update_section(conn, new_id, {"planned_start": body.start, "planned_end": body.end,
                                              "is_milestone": body.milestone,
                                              "assigned_user_id": body.assigned_user_id})
    await store.replace_predecessors(conn, auth.organization_id, new_id, preds)
    return await _respond(conn, auth, project_id, moved=[], focus=new_id)


async def _respond(conn: AsyncConnection, auth: AuthorizationContext, project_id: uuid.UUID, *,
                   moved: list[dict], focus: uuid.UUID | None, saved: bool = True, finish_before: Any = None) -> dict:
    sched = await store.load(conn, auth.organization_id, project_id, await _today(conn, auth))
    sched["project"] = _project_out(sched["project"])
    sched["can_edit"] = _may_edit(auth)
    sched = _for_role(sched, auth)
    after = sched["summary"]["planned_finish"]
    return _iso({"saved": saved, "focus": focus, "moved": moved,
                 "finish_moves": (after - finish_before).days if after and finish_before else 0,
                 "schedule": sched})


@router.patch("/projects/{project_id}/schedule/activities/{activity_id}")
async def update_activity(project_id: uuid.UUID, activity_id: uuid.UUID, body: ActivityUpdate, response: Response,
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
    await _check_person(conn, auth, body.assigned_user_id)

    savepoint = await conn.begin_nested()
    try:
        result = await _apply_update(conn, auth, project_id, activity_id, current, body)
    except BaseException:
        await savepoint.rollback()
        raise
    if body.preview:
        await savepoint.rollback()
        result["saved"] = False
        mark_saved_nothing(response)  # ADM-01: a preview is not a change
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
    if "site_id" in body.model_fields_set:
        changes["site_id"] = body.site_id
    if "assigned_user_id" in body.model_fields_set:
        changes["assigned_user_id"] = body.assigned_user_id
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
            new = {i: d for i, d in logic.push(acts, sched["links"], pinned, cal=_cal(sched)).items()
                   if i not in pinned}
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
    cal = store.calendar(await store.project(conn, auth.organization_id, project_id))
    day = cal.next_work(body.start)
    prev: uuid.UUID | None = None
    for item in body.items:
        milestone = item.days == 0
        end = day if milestone else cal.end_for(day, item.days)
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
        day = end if milestone else cal.next_work(end + logic.DAY)
    return await _respond(conn, auth, project_id, moved=[], focus=None)


class DraftActivity(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    days: int = Field(ge=0, le=365)

    _clean_name = field_validator("name")(_clean)


class FromDrawing(BaseModel):
    start: datetime.date
    activities: list[DraftActivity] = Field(min_length=1, max_length=120)
    site_id: uuid.UUID | None = None


@router.post("/projects/{project_id}/schedule/from-drawing")
async def schedule_from_drawing(project_id: uuid.UUID, body: FromDrawing,
                                auth: AuthorizationContext = Depends(get_auth_context),
                                conn: AsyncConnection = Depends(get_db_conn)):
    """DR-05: the draft from a drawing set (Planning > Drawing check), as edited by the person, added to the
    schedule one after another from ``start`` and linked in that order. Never overwrites: an activity whose name the
    schedule already has is left as it is and reported as skipped (D-DR2)."""
    from sqlalchemy import text

    from mesiri.infrastructure.postgres.repositories.boq import PostgresBoqRepository

    await _project(conn, auth, project_id)
    _require_edit(auth)
    await _check_site(conn, project_id, body.site_id)
    have = {n.lower() for n in (await conn.execute(text(
        "SELECT name FROM work_packages WHERE organization_id = :org AND project_id = :p"),
        {"org": auth.organization_id, "p": project_id})).scalars()}
    repo = PostgresBoqRepository(conn)
    cal = store.calendar(await store.project(conn, auth.organization_id, project_id))
    day, prev, added, skipped = cal.next_work(body.start), None, [], []
    for act in body.activities:
        if act.name.lower() in have:
            skipped.append(act.name)
            continue
        have.add(act.name.lower())
        new_id = await repo.create_section(auth.organization_id, project_id, act.name, body.site_id, None, auth.user_id)
        milestone = act.days == 0
        end = day if milestone else cal.end_for(day, act.days)
        await store.update_section(conn, new_id, {"planned_start": day, "planned_end": end, "is_milestone": milestone})
        if prev is not None:
            await store.replace_predecessors(conn, auth.organization_id, new_id, [(prev, 0)])
        prev, day = new_id, (end if milestone else cal.next_work(end + logic.DAY))
        added.append(act.name)
    out = await _respond(conn, auth, project_id, moved=[], focus=None)
    out.update(added=added, skipped=skipped)
    return out


# -- the approved programme and the export (QA Step 11, 23 Nov 2026) ------------------------------------------------

class BaselineIn(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    note: str | None = Field(default=None, max_length=500)

    _clean_name = field_validator("name", "note")(_clean)


@router.post("/projects/{project_id}/schedule/baselines", status_code=201)
async def approve_programme(project_id: uuid.UUID, body: BaselineIn,
                            auth: AuthorizationContext = Depends(get_auth_context),
                            conn: AsyncConnection = Depends(get_db_conn)):
    """The programme as it stands becomes the approved one: each dated activity's dates are kept, and from now on the
    schedule shows how far each has moved from them. A later approval (a revised programme) becomes the one compared
    with; earlier ones stay listed."""
    await _project(conn, auth, project_id)
    _require_edit(auth)
    sched = await store.load(conn, auth.organization_id, project_id, await _today(conn, auth))
    if not any(a["start"] and a["end"] for a in sched["activities"]):
        raise HTTPException(status_code=422, detail="Put dates on the activities first: there is nothing to approve")
    count = len(await store.baselines(conn, auth.organization_id, project_id))
    name = body.name or ("Approved programme" if count == 0 else f"Revised programme {count}")
    await store.lock_baseline(conn, auth.organization_id, project_id, sched["activities"], name, body.note,
                              auth.user_id)
    return await _respond(conn, auth, project_id, moved=[], focus=None)


@router.get("/projects/{project_id}/schedule/baselines")
async def list_programmes(project_id: uuid.UUID, auth: AuthorizationContext = Depends(get_auth_context),
                          conn: AsyncConnection = Depends(get_db_conn)):
    await _project(conn, auth, project_id)
    return _iso(await store.baselines(conn, auth.organization_id, project_id))


def _after_words(name: str, link: dict) -> str:
    """"Masonry", "Masonry (starts with) +5d": a link as the export says it."""
    kind = " (starts with)" if link.get("kind") == "SS" else ""
    lag = int(link.get("lag") or 0)
    return f"{name}{kind}{f' {lag:+d}d' if lag else ''}"


@router.get("/projects/{project_id}/schedule/export")
@saves_nothing
async def export_programme(project_id: uuid.UUID, auth: AuthorizationContext = Depends(get_auth_context),
                           conn: AsyncConnection = Depends(get_db_conn)):
    """The programme as an .xlsx to send the client or the architect: each activity with its site, what it follows,
    planned and approved dates, working days, progress and forecast. No money."""
    import io
    import re

    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    await _project(conn, auth, project_id)
    sched = await store.load(conn, auth.organization_id, project_id, await _today(conn, auth))
    proj = sched["project"]
    names = {a["id"]: a["name"] for a in sched["activities"]}
    states = {logic.LATE: "Late", logic.BEHIND: "Behind", logic.ON_TRACK: "On track", logic.NOT_STARTED: "Not started",
              logic.DONE: "Done", logic.UNSCHEDULED: "No dates"}
    book = Workbook()
    sheet = book.active
    sheet.title = "Programme"
    sheet.append([f"{proj['name']}: programme"])
    sheet["A1"].font = Font(bold=True, size=13)
    week = proj.get("work_week") or "1111111"
    off = [d for d, w in zip(("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"), week, strict=True) if w == "0"]
    sheet.append([f"As on {sched['today'].strftime('%d %b %Y')}. Working days: "
                  f"{'every day' if not off else 'all but ' + ', '.join(off)}"
                  f"{'; ' + str(len(proj.get('holidays') or [])) + ' holidays' if proj.get('holidays') else ''}."])
    base = sched["summary"].get("baseline")
    if base:
        sheet.append([f"Compared with: {base['name']} ({base['locked_at'].strftime('%d %b %Y')})."])
    sheet.append([])
    head = ["No.", "Activity", "Site", "Starts after", "Start", "Finish", "Working days", "Approved start",
            "Approved finish", "Moved (days)", "Done %", "State", "Forecast finish", "Who runs it"]
    sheet.append(head)
    for cell in sheet[sheet.max_row]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="EEEAE0")
    for n, a in enumerate(sched["activities"], 1):
        after = "; ".join(_after_words(names.get(p["id"], "?"), p) for p in a["after"])
        b = a.get("baseline") or {}
        sheet.append([n, a["name"] + (" (milestone)" if a["milestone"] else ""), a["site_name"] or "All", after,
                      a["start"], a["end"], a["duration"], b.get("start"), b.get("end"), a.get("baseline_slip_days"),
                      a["progress"], states.get(a["state"], a["state"]), a["forecast_end"], a["assigned_to"]])
    for row in sheet.iter_rows(min_row=1):
        for cell in row:
            if isinstance(cell.value, datetime.date):
                cell.number_format = "DD MMM YYYY"
    for col, width in zip("ABCDEFGHIJKLMN", (5, 34, 14, 30, 13, 13, 9, 13, 13, 9, 8, 12, 14, 18), strict=True):
        sheet.column_dimensions[col].width = width
    out = io.BytesIO()
    book.save(out)
    safe = re.sub(r"[^A-Za-z0-9 _-]+", "", proj["name"]).strip() or "project"
    return FileResponse(content=out.getvalue(),
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="{safe} programme.xlsx"'})
