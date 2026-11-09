"""REST API for tasks (TSK-01): who does what, by when. The `tasks` module (on by default; off per company).

  GET    /tasks                    list: mine, a project's, a site's, a person's; overdue / today / this week
  GET    /tasks/summary            counts for the sidebar and Today: mine open, mine overdue, overdue in my projects
  GET    /tasks/options            a project's sites, people and subcontractors, for the pickers
  POST   /tasks                    give a task (site, person and place by id or in words)
  GET    /tasks/{id}               one task with its history (photos as links)
  PATCH  /tasks/{id}               change the details, reassign
  POST   /tasks/{id}/status        start, block (with a reason), done, reopen, cancel
  POST   /tasks/{id}/comments      a comment, a photo, or both

A task is seen by everyone on its project, except that a person limited to some sites sees only those sites'
tasks, plus the ones they gave or were given (the BE-42 rule). Who may change what is ``logic.may_*`` (D-T2).
A WhatsApp photo (``media_object_key``) must be one this company's WhatsApp received. Plan:
docs/plans/tasks-plan.md.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.authorization.context import AuthorizationContext
from mesiri.domains.projects.router import get_auth_context
from mesiri.domains.shared.media import photo_is_ours, signed_media_url
from mesiri.domains.shared.modules import require_module
from mesiri.domains.tasks import logic, store
from mesiri.infrastructure.objectstorage.dependency import get_object_storage
from mesiri.infrastructure.postgres.dependency import get_db_conn
from mesiri_contracts.common.storage import ObjectStoragePort

router = APIRouter(prefix="/tasks", tags=["tasks"], dependencies=[Depends(require_module("tasks"))])

Source = Literal["web", "whatsapp"]
Priority = Literal["normal", "high", "urgent"]


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = " ".join(value.split())
    return value or None


class TaskIn(BaseModel):
    project_id: uuid.UUID
    title: str = Field(min_length=1, max_length=200, description="What to do, in a line: 'Tie steel for grid B'")
    notes: str | None = Field(default=None, max_length=2000)
    site_id: uuid.UUID | None = None
    site: str | None = Field(default=None, max_length=120, description="The site in words, when there is no site_id")
    due_date: datetime.date | None = None
    priority: Priority = "normal"
    assignee_user_id: uuid.UUID | None = None
    assignee: str | None = Field(default=None, max_length=120,
                                 description="The person it is for, by name ('Arun'), when there is no assignee_user_id")
    assignee_vendor_id: uuid.UUID | None = Field(default=None, description="A subcontractor it is for, instead of a person")
    assignee_team: str | None = Field(default=None, max_length=120, description="A team in words ('bar bending team')")
    place_id: uuid.UUID | None = None
    place: str | None = Field(default=None, max_length=120, description="Where on site in words ('first floor R2')")
    work_package_id: uuid.UUID | None = Field(default=None, description="The schedule activity (BOQ section)")
    planned_item_id: uuid.UUID | None = Field(default=None, description="The BOQ line the work counts against")
    expected_quantity: Decimal | None = Field(default=None, gt=0, description="How much of the BOQ line is expected")
    site_issue_id: uuid.UUID | None = Field(default=None, description="The site issue this task fixes")
    media_object_key: str | None = None
    source: Source = "web"

    _strip = field_validator("title", "notes", "site", "assignee", "assignee_team", "place")(_clean)


class TaskPatch(BaseModel):
    """Only the fields sent change; a field sent as null is cleared (not the title)."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    notes: str | None = Field(default=None, max_length=2000)
    site_id: uuid.UUID | None = None
    due_date: datetime.date | None = None
    priority: Priority | None = None
    assignee_user_id: uuid.UUID | None = None
    assignee_vendor_id: uuid.UUID | None = None
    assignee_team: str | None = Field(default=None, max_length=120)
    place_id: uuid.UUID | None = None
    work_package_id: uuid.UUID | None = None
    planned_item_id: uuid.UUID | None = None
    expected_quantity: Decimal | None = Field(default=None, gt=0)
    site_issue_id: uuid.UUID | None = None
    source: Source = "web"

    _strip = field_validator("title", "notes", "assignee_team")(_clean)


class StatusIn(BaseModel):
    status: Literal["open", "doing", "blocked", "done", "cancelled"]
    note: str | None = Field(default=None, max_length=1000, description="Why (required when blocked), or a remark")
    media_object_key: str | None = None
    source: Source = "web"

    _strip = field_validator("note")(_clean)


class CommentIn(BaseModel):
    text: str | None = Field(default=None, max_length=2000)
    media_object_key: str | None = None
    source: Source = "web"

    _strip = field_validator("text")(_clean)


# -- access ------------------------------------------------------------------------------------------------------------

def _project_in_scope(auth: AuthorizationContext, project_id: uuid.UUID) -> bool:
    return auth.project_scope.grants_all_org_projects or project_id in auth.project_scope.project_ids


def _site_in_scope(auth: AuthorizationContext, project_id: uuid.UUID, site_id: uuid.UUID | None) -> bool:
    scope = auth.site_scope_for_project(project_id)
    return scope.grants_all_sites or (site_id is not None and site_id in scope.site_ids)


def _visible(auth: AuthorizationContext, task: dict[str, Any]) -> bool:
    if not _project_in_scope(auth, task["project_id"]):
        return False
    me = str(auth.user_id)
    return (_site_in_scope(auth, task["project_id"], task["site_id"])
            or str(task.get("assignee_user_id")) == me or str(task.get("created_by")) == me)


async def _task(conn: AsyncConnection, auth: AuthorizationContext, task_id: uuid.UUID) -> dict[str, Any]:
    task = await store.one(conn, auth.organization_id, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if not _visible(auth, task):
        raise HTTPException(status_code=403, detail="Not authorized for this task")
    return task


async def _today(conn: AsyncConnection, auth: AuthorizationContext) -> datetime.date:
    from mesiri.application.dpr.project_day import company_today

    return await company_today(conn, auth.organization_id)


async def _check_photo(conn: AsyncConnection, auth: AuthorizationContext, key: str | None) -> None:
    if key and not await photo_is_ours(conn, auth.organization_id, key):
        raise HTTPException(status_code=404, detail="Photo not found")


def _choose(message: str, options: list[str]) -> HTTPException:
    """Refused because words fit several things or none: the choices, so the caller can ask which."""
    return HTTPException(status_code=422, detail={"message": message, "options": options[:20]})


# -- shape -------------------------------------------------------------------------------------------------------------

def _out(task: dict[str, Any], today: datetime.date, progress: dict | None = None) -> dict[str, Any]:
    keep = ("id", "project_id", "project_name", "site_id", "site_name", "number", "title", "notes", "status",
            "priority", "due_date", "assignee_user_id", "assignee_name", "assignee_vendor_id",
            "assignee_vendor_name", "assignee_team", "place_id", "place_name", "work_package_id", "activity_name",
            "planned_item_id", "expected_quantity", "site_issue_id", "blocked_reason", "started_at", "done_at",
            "done_by", "source", "created_by", "created_by_name", "created_at", "updated_at")
    out = {k: task.get(k) for k in keep}
    out["ref"] = logic.ref(task["number"])
    out["expected_quantity"] = store.num(task["expected_quantity"]) if task.get("expected_quantity") is not None else None
    out["assigned_to"] = task.get("assignee_name") or task.get("assignee_vendor_name") or task.get("assignee_team")
    out["overdue"] = logic.is_overdue(task["status"], task.get("due_date"), today)
    out["days_late"] = logic.days_late(task["status"], task.get("due_date"), today)
    out["issue"] = ({"id": task["site_issue_id"], "type": task.get("issue_type"), "narrative": task.get("issue_narrative"),
                     "status": task.get("issue_status")} if task.get("site_issue_id") else None)
    out["line"] = ({"id": task["planned_item_id"], "work": task.get("line_work"), "unit": task.get("line_unit")}
                   if task.get("planned_item_id") else None)
    out["progress"] = progress
    return out


async def _shaped(conn: AsyncConnection, auth: AuthorizationContext, task_id: uuid.UUID) -> dict[str, Any]:
    """A task as every write answers it: the row, its links and its progress (the same shape as the list)."""
    task = await store.one(conn, auth.organization_id, task_id)
    done = await store.progress(conn, auth.organization_id, [task])
    return _out(task, await _today(conn, auth), done.get(task_id))


# -- routes ------------------------------------------------------------------------------------------------------------

@router.get("")
async def list_tasks(
    project_id: uuid.UUID | None = None,
    site_id: uuid.UUID | None = None,
    assignee: str | None = Query(default=None, description="'me', a person's id or a subcontractor's id"),
    status: str | None = Query(default=None, description="open, doing, blocked, done, cancelled, or 'live' (the "
                                                         "first three, the default) or 'all'; several with commas"),
    due: Literal["overdue", "today", "week"] | None = None,
    q: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=200, ge=1, le=500),
    auth: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Tasks, late first, then by due day. Default: the ones still waiting on someone (open, doing, blocked)."""
    if project_id is not None and not _project_in_scope(auth, project_id):
        raise HTTPException(status_code=403, detail="Not authorized for this project")
    statuses = _statuses(status)
    user_id = vendor_id = None
    if assignee == "me":
        user_id = auth.user_id
    elif assignee:
        try:
            who = uuid.UUID(assignee)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="assignee is 'me' or an id") from exc
        user_id, vendor_id = (None, who) if await store.is_vendor(conn, auth.organization_id, who) else (who, None)
    scope = None if auth.project_scope.grants_all_org_projects else set(auth.project_scope.project_ids)
    rows = await store.listing(conn, auth.organization_id, project_ids=scope, project_id=project_id, site_id=site_id,
                               statuses=statuses, assignee_user_id=user_id, assignee_vendor_id=vendor_id, q=_clean(q),
                               limit=limit)
    today = await _today(conn, auth)
    rows = [r for r in rows if _visible(auth, r) and _due_fits(r, due, today)]
    rows.sort(key=lambda r: logic.sort_key(r, today))
    done = await store.progress(conn, auth.organization_id, rows)
    return {"items": [_out(r, today, done.get(r["id"])) for r in rows], "today": today}


def _statuses(words: str | None) -> tuple[str, ...]:
    if not words or words == "live":
        return tuple(logic.LIVE)
    if words == "all":
        return logic.STATUSES
    picked = tuple(s.strip() for s in words.split(",") if s.strip())
    unknown = [s for s in picked if s not in logic.STATUSES]
    if unknown or not picked:
        raise HTTPException(status_code=422, detail=f"Unknown status: {', '.join(unknown) or words}")
    return picked


def _due_fits(task: dict[str, Any], due: str | None, today: datetime.date) -> bool:
    day = task.get("due_date")
    if due is None:
        return True
    if due == "overdue":
        return logic.is_overdue(task["status"], day, today)
    if due == "today":
        return day is not None and day <= today and task["status"] in logic.LIVE
    return day is not None and day <= today + datetime.timedelta(days=6 - today.weekday())


@router.get("/summary")
async def summary(auth: AuthorizationContext = Depends(get_auth_context),
                  conn: AsyncConnection = Depends(get_db_conn)):
    """How many: mine still open, mine late, and late in the projects I see."""
    scope = None if auth.project_scope.grants_all_org_projects else set(auth.project_scope.project_ids)
    rows = await store.listing(conn, auth.organization_id, project_ids=scope, project_id=None, site_id=None,
                               statuses=tuple(logic.LIVE), assignee_user_id=None, assignee_vendor_id=None, q=None,
                               limit=5000)
    today = await _today(conn, auth)
    rows = [r for r in rows if _visible(auth, r)]
    mine = [r for r in rows if str(r.get("assignee_user_id")) == str(auth.user_id)]
    late = [r for r in rows if logic.is_overdue(r["status"], r.get("due_date"), today)]
    return {"mine_open": len(mine), "mine_overdue": sum(1 for r in mine if r in late), "overdue": len(late)}


@router.get("/options")
async def options(project_id: uuid.UUID, auth: AuthorizationContext = Depends(get_auth_context),
                  conn: AsyncConnection = Depends(get_db_conn)):
    """What a task on this project can name: its sites (those this person sees), the people it can be for (the
    same list ``POST /tasks`` matches names against), the company's subcontractors, the project's places and its
    BOQ lines (no rates)."""
    org = auth.organization_id
    if not _project_in_scope(auth, project_id) or await store.project(conn, org, project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    sites = [s for s in await store.sites(conn, org, project_id) if _site_in_scope(auth, project_id, s["id"])]
    return {"sites": sites, "people": await store.people(conn, org, project_id),
            "subcontractors": await store.subcontractors(conn, org), "places": await store.places(conn, org, project_id),
            "lines": await store.boq_lines(conn, org, project_id), "may_create": logic.may_create(auth.role)}


@router.post("", status_code=201)
async def create_task(body: TaskIn, auth: AuthorizationContext = Depends(get_auth_context),
                      conn: AsyncConnection = Depends(get_db_conn)):
    """Give a task. The site, the person and the place can be said in words; words that fit several or none are
    refused (422) with the choices, so the caller can ask which. Refused for finance and supervisors (D-T2)."""
    org = auth.organization_id
    if not logic.may_create(auth.role):
        raise HTTPException(status_code=403, detail="Only an owner, admin, project manager or site engineer gives tasks")
    if not _project_in_scope(auth, body.project_id) or await store.project(conn, org, body.project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    v = body.model_dump(exclude={"project_id", "site", "assignee", "place", "media_object_key", "source"})
    if body.site_id is None and body.site:
        found = logic.pick(body.site, await store.sites(conn, org, body.project_id), lambda s: s["name"])
        if found.item is None:
            raise _choose(f"Which site is {body.site!r}?", found.options)
        v["site_id"] = found.item["id"]
    if v["assignee_user_id"] is None and body.assignee:
        found = logic.pick(body.assignee, await store.people(conn, org, body.project_id), lambda p: p["name"])
        if found.item is None:
            raise _choose(f"Who is {body.assignee!r}?", found.options)
        v["assignee_user_id"] = found.item["id"]
    if v["assignee_user_id"] is not None and v["assignee_vendor_id"] is not None:
        raise HTTPException(status_code=422, detail="A task is for a person or a subcontractor, not both")
    if body.place_id is None and body.place:
        v["place_id"] = await _place(conn, org, body.project_id, body.place)
    if v["expected_quantity"] is not None and v["planned_item_id"] is None:
        raise HTTPException(status_code=422, detail="An expected quantity needs the BOQ line it counts against")
    if v["planned_item_id"] is not None and v["work_package_id"] is None:
        v["work_package_id"] = await store.section_of_line(conn, v["planned_item_id"])
    if v["site_id"] is not None and not _site_in_scope(auth, body.project_id, v["site_id"]):
        raise HTTPException(status_code=403, detail="Not authorized for this site")
    errors = await store.link_errors(conn, org, body.project_id, v)
    if errors:
        raise HTTPException(status_code=422, detail="; ".join(errors))
    await _check_photo(conn, auth, body.media_object_key)

    number = await store.next_number(conn, body.project_id)
    task_id = await store.insert(conn, org, body.project_id, number, v, source=body.source, user_id=auth.user_id)
    await store.add_event(conn, org, task_id, "created", user_id=auth.user_id, source=body.source,
                          to_status=logic.OPEN, media_object_key=body.media_object_key)
    return await _shaped(conn, auth, task_id)


async def _place(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID, words: str) -> uuid.UUID:
    from mesiri.domains.places import names
    from mesiri.domains.places import store as places_store

    pool = places_store.as_names(await places_store.places(conn, org, project_id))
    match = names.resolve(words, pool)
    if match.place is None:
        by_id = {p.id: p for p in pool}
        raise _choose(f"Which place is {words!r}?", [names.label(p, by_id) for p in (match.options or pool)])
    return match.place.id


@router.get("/{task_id}")
async def get_task(task_id: uuid.UUID, auth: AuthorizationContext = Depends(get_auth_context),
                   conn: AsyncConnection = Depends(get_db_conn),
                   object_storage: ObjectStoragePort = Depends(get_object_storage)):
    """One task, its history (oldest first; photos as short-lived links) and what this person may do with it."""
    task = await _task(conn, auth, task_id)
    history = await store.events(conn, auth.organization_id, task_id)
    for e in history:
        e["photo_url"] = await signed_media_url(object_storage, e.pop("media_object_key"))
    out = _out(task, await _today(conn, auth), (await store.progress(conn, auth.organization_id, [task])).get(task_id))
    out["history"] = history
    out["may"] = {"edit": logic.may_edit(auth.role, auth.user_id, task),
                  "cancel": logic.may_move(auth.role, auth.user_id, task, logic.CANCELLED),
                  "move": logic.may_move(auth.role, auth.user_id, task, logic.DONE),
                  "comment": logic.may_comment(auth.role, auth.user_id, task)}
    return out


@router.patch("/{task_id}")
async def update_task(task_id: uuid.UUID, body: TaskPatch, auth: AuthorizationContext = Depends(get_auth_context),
                      conn: AsyncConnection = Depends(get_db_conn)):
    """Change the details or reassign: the person who gave it, or a manager. Recorded in the history (old, new)."""
    org = auth.organization_id
    task = await _task(conn, auth, task_id)
    if not logic.may_edit(auth.role, auth.user_id, task):
        raise HTTPException(status_code=403, detail="Only the person who gave the task or a manager changes it")
    sent = {k: getattr(body, k) for k in body.model_fields_set if k != "source"}
    if "title" in sent and sent["title"] is None:
        raise HTTPException(status_code=422, detail="A task needs a title")
    after = {**{k: task.get(k) for k in store.FIELDS}, **sent}
    if after["assignee_user_id"] is not None and after["assignee_vendor_id"] is not None:
        if "assignee_user_id" in sent and "assignee_vendor_id" not in sent:
            sent["assignee_vendor_id"] = after["assignee_vendor_id"] = None
        elif "assignee_vendor_id" in sent and "assignee_user_id" not in sent:
            sent["assignee_user_id"] = after["assignee_user_id"] = None
        else:
            raise HTTPException(status_code=422, detail="A task is for a person or a subcontractor, not both")
    if after["expected_quantity"] is not None and after["planned_item_id"] is None:
        raise HTTPException(status_code=422, detail="An expected quantity needs the BOQ line it counts against")
    if "site_id" in sent and sent["site_id"] is not None and not _site_in_scope(auth, task["project_id"], sent["site_id"]):
        raise HTTPException(status_code=403, detail="Not authorized for this site")
    errors = await store.link_errors(conn, org, task["project_id"], sent)
    if errors:
        raise HTTPException(status_code=422, detail="; ".join(errors))
    changes = {k: v for k, v in sent.items() if task.get(k) != v}
    if changes:
        await store.update(conn, task_id, changes)
        await store.add_event(conn, org, task_id, "changed", user_id=auth.user_id, source=body.source,
                              changes={k: [task.get(k), v] for k, v in changes.items()})
    return await _shaped(conn, auth, task_id)


@router.post("/{task_id}/status")
async def move_task(task_id: uuid.UUID, body: StatusIn, auth: AuthorizationContext = Depends(get_auth_context),
                    conn: AsyncConnection = Depends(get_db_conn)):
    """Start, block (say why), finish, reopen or cancel. Finishing never records work done (D-T4)."""
    org = auth.organization_id
    task = await _task(conn, auth, task_id)
    if not logic.may_move(auth.role, auth.user_id, task, body.status):
        raise HTTPException(status_code=403, detail="Only the person it is for, the person who gave it or a manager "
                                                    "moves it" if body.status != logic.CANCELLED else
                            "Only the person who gave the task or a manager cancels it")
    error = logic.move_error(task["status"], body.status, body.note)
    if error:
        raise HTTPException(status_code=409, detail=error)
    await _check_photo(conn, auth, body.media_object_key)
    changes: dict[str, Any] = {"status": body.status,
                               "blocked_reason": body.note if body.status == logic.BLOCKED else None}
    if body.status == logic.DOING and task["started_at"] is None:
        changes["started_at"] = datetime.datetime.now(datetime.UTC)
    if body.status == logic.DONE:
        changes["done_at"] = datetime.datetime.now(datetime.UTC)
        changes["done_by"] = auth.user_id
    elif body.status == logic.OPEN:
        changes["done_at"] = changes["done_by"] = None
    await store.update(conn, task_id, changes)
    await store.add_event(conn, org, task_id, "status", user_id=auth.user_id, source=body.source,
                          from_status=task["status"], to_status=body.status, words=body.note,
                          media_object_key=body.media_object_key)
    return await _shaped(conn, auth, task_id)


@router.post("/{task_id}/comments", status_code=201)
async def comment(task_id: uuid.UUID, body: CommentIn, auth: AuthorizationContext = Depends(get_auth_context),
                  conn: AsyncConnection = Depends(get_db_conn)):
    """A comment, a photo, or both, on the task's history."""
    task = await _task(conn, auth, task_id)
    if not body.text and not body.media_object_key:
        raise HTTPException(status_code=422, detail="Say something or send a photo")
    if not logic.may_comment(auth.role, auth.user_id, task):
        raise HTTPException(status_code=403, detail="Not authorized to comment on this task")
    await _check_photo(conn, auth, body.media_object_key)
    await store.add_event(conn, auth.organization_id, task_id, "comment", user_id=auth.user_id, source=body.source,
                          words=body.text, media_object_key=body.media_object_key)
    return {"ok": True, "ref": logic.ref(task["number"])}
