"""REST API for places on site: floors and rooms (LP-01, LP-03, LP-04, LP-05).

  GET    /projects/{project_id}/places                 the floors and rooms (tree order), can_edit
  POST   /projects/{project_id}/places                 add a floor (no parent) or a room (parent_id)
  POST   /projects/{project_id}/places/setup           floors x rooms in one go; places already there are kept
  PATCH  /projects/{project_id}/places/{place_id}      rename, reorder, move (parent_id with move=true)
  DELETE /projects/{project_id}/places/{place_id}      delete (nothing recorded there) or archive (work kept)
  GET    /projects/{project_id}/places/progress        floor x work grid: done / in progress / not started, what's
                                                       left; ?place=<words> for one floor or room ("first floor")
  GET    /projects/{project_id}/places/{place_id}/work the work recorded there and in its rooms, with photos

Who: everyone on the project reads; the people who plan (owner, admin, finance, project manager, as the schedule)
set places up (D-LP1). Work is put at a place by the work entry itself (``POST /progress/activities`` ``place``).
Plan: docs/plans/location-progress-plan.md.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.authorization.context import AuthorizationContext
from mesiri.authorization.roles import may_view_expenses
from mesiri.domains.places import names, progress, store
from mesiri.domains.projects.router import get_auth_context
from mesiri.domains.shared.media import signed_media_url
from mesiri.domains.shared.modules import require_module
from mesiri.infrastructure.objectstorage.dependency import get_object_storage
from mesiri.infrastructure.postgres.dependency import get_db_conn
from mesiri_contracts.common.storage import ObjectStoragePort

router = APIRouter(prefix="/projects/{project_id}/places", tags=["places"],
                   dependencies=[Depends(require_module("dpr"))])

#: The quick setup's suggestion (renamable before saving).
DEFAULT_FLOORS = ("Ground Floor", "First Floor")
DEFAULT_ROOMS = ("Living", "Kitchen", "Bedroom 1", "Bedroom 2", "Toilet 1")


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = " ".join(value.split())
    return value or None


class PlaceIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    parent_id: uuid.UUID | None = None
    level_label: str | None = Field(default=None, max_length=40)

    _c = field_validator("name", "level_label")(_clean)


class PlaceChange(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    sort_order: int | None = Field(default=None, ge=0, le=10_000)
    level_label: str | None = Field(default=None, max_length=40)
    parent_id: uuid.UUID | None = None
    move: bool = Field(default=False, description="True to move the place under parent_id (null: make it a floor)")

    _c = field_validator("name", "level_label")(_clean)


class SetupIn(BaseModel):
    floors: list[str] = Field(min_length=1, max_length=60)
    rooms: list[str] = Field(default_factory=list, max_length=60)

    @field_validator("floors", "rooms")
    @classmethod
    def _names(cls, values: list[str]) -> list[str]:
        out: list[str] = []
        for v in values:
            v = _clean(v) or ""
            if len(v) > 80:
                raise ValueError("a place name is at most 80 characters")
            if v and v.lower() not in {o.lower() for o in out}:
                out.append(v)
        return out


def _in_scope(auth: AuthorizationContext, project_id: uuid.UUID) -> None:
    if not auth.project_scope.grants_all_org_projects and project_id not in auth.project_scope.project_ids:
        raise HTTPException(status_code=403, detail="Not authorized for this project")


def _may_edit(auth: AuthorizationContext) -> bool:
    return may_view_expenses(auth.role)


def _require_edit(auth: AuthorizationContext) -> None:
    if not _may_edit(auth):
        raise HTTPException(status_code=403, detail="Only the owner, an admin, finance or a project manager can set "
                                                    "up floors and rooms")


async def _project(conn: AsyncConnection, auth: AuthorizationContext, project_id: uuid.UUID) -> None:
    _in_scope(auth, project_id)
    if not await store.project_exists(conn, auth.organization_id, project_id):
        raise HTTPException(status_code=404, detail="Project not found")


def _place_out(r: dict) -> dict:
    return {"id": str(r["id"]), "parent_id": str(r["parent_id"]) if r.get("parent_id") else None,
            "name": r["name"], "level_label": r["level_label"], "label": r.get("label", r["name"]),
            "depth": r.get("depth", 0), "sort_order": r.get("sort_order", 0)}


@router.get("")
async def list_places(project_id: uuid.UUID, auth: AuthorizationContext = Depends(get_auth_context),
                      conn: AsyncConnection = Depends(get_db_conn)):
    await _project(conn, auth, project_id)
    rows = await store.places(conn, auth.organization_id, project_id)
    return {"places": [_place_out(r) for r in rows], "can_edit": _may_edit(auth),
            "suggested": {"floors": list(DEFAULT_FLOORS), "rooms": list(DEFAULT_ROOMS)}}


@router.post("", status_code=201)
async def add_place(project_id: uuid.UUID, body: PlaceIn, auth: AuthorizationContext = Depends(get_auth_context),
                    conn: AsyncConnection = Depends(get_db_conn)):
    await _project(conn, auth, project_id)
    _require_edit(auth)
    try:
        row = await store.add(conn, auth.organization_id, project_id, name=body.name, level_label=body.level_label,
                              parent_id=body.parent_id, user_id=auth.user_id)
    except store.PlaceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _place_out(row)


@router.post("/setup")
async def setup_places(project_id: uuid.UUID, body: SetupIn, auth: AuthorizationContext = Depends(get_auth_context),
                       conn: AsyncConnection = Depends(get_db_conn)):
    await _project(conn, auth, project_id)
    _require_edit(auth)
    if not body.floors:
        raise HTTPException(status_code=422, detail="Name at least one floor")
    try:
        made = await store.setup(conn, auth.organization_id, project_id, floors=body.floors, rooms=body.rooms,
                                 user_id=auth.user_id)
    except store.PlaceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    rows = await store.places(conn, auth.organization_id, project_id)
    return {"made": made, "places": [_place_out(r) for r in rows]}


@router.get("/progress")
async def places_progress(project_id: uuid.UUID,
                          place: str | None = Query(default=None, max_length=120,
                                                    description="A floor or room in words: 'first floor', 'FF R2'"),
                          auth: AuthorizationContext = Depends(get_auth_context),
                          conn: AsyncConnection = Depends(get_db_conn)):
    """The floor x work grid. Each place: per kind of work done / in_progress / not_started, ``left`` (not done),
    ``done``, photos, last update. With ``place``: that place and its rooms only, or ``options`` when the words fit
    several (ask which), or ``not_found`` with the floors there are."""
    await _project(conn, auth, project_id)
    org = auth.organization_id
    rows = await store.places(conn, org, project_id)
    rolled = progress.roll_up(rows, await store.works(conn, org, project_id))
    chosen = None
    if place:
        match = names.resolve(place, store.as_names(rows))
        if match.place is None:
            by_id = {r["id"]: r for r in rows}
            return {"place": None, "asked": place, "reason": match.reason,
                    "options": [by_id[o.id]["label"] for o in match.options if o.id in by_id]
                    or [r["label"] for r in rows if r["parent_id"] is None],
                    "kinds": rolled["kinds"], "places": []}
        chosen = match.place.id
    shown = rows
    if chosen is not None:
        root = next(r for r in rows if r["id"] == chosen)
        shown = [r for r in rows if r["path"] == root["path"] or r["path"].startswith(root["path"] + "/")]
    out = []
    for r in shown:
        cell = rolled["places"][r["id"]]
        out.append({**_place_out(r), "cells": {k: {"state": v["state"], "last": v["last"].isoformat()
                                                   if v["last"] else None} for k, v in cell["cells"].items()},
                    "left": cell["left"], "done": cell["done"], "photos": cell["photos"],
                    "last_update": cell["last_update"].isoformat() if cell["last_update"] else None})
    return {"place": out[0]["label"] if chosen is not None else None, "kinds": rolled["kinds"], "places": out,
            "set_up": bool(rows)}


@router.patch("/{place_id}")
async def change_place(project_id: uuid.UUID, place_id: uuid.UUID, body: PlaceChange,
                       auth: AuthorizationContext = Depends(get_auth_context),
                       conn: AsyncConnection = Depends(get_db_conn)):
    await _project(conn, auth, project_id)
    _require_edit(auth)
    try:
        row = await store.change(conn, auth.organization_id, project_id, place_id, name=body.name,
                                 sort_order=body.sort_order, parent_id=body.parent_id, move=body.move,
                                 level_label=body.level_label)
    except store.PlaceError as exc:
        raise HTTPException(status_code=404 if "not found" in str(exc) else 422, detail=str(exc)) from exc
    return {"id": str(row["id"]), "name": row["name"]}


@router.delete("/{place_id}")
async def remove_place(project_id: uuid.UUID, place_id: uuid.UUID,
                       auth: AuthorizationContext = Depends(get_auth_context),
                       conn: AsyncConnection = Depends(get_db_conn)):
    await _project(conn, auth, project_id)
    _require_edit(auth)
    try:
        outcome = await store.remove(conn, auth.organization_id, project_id, place_id)
    except store.PlaceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"id": str(place_id), "outcome": outcome}


@router.get("/{place_id}/work")
async def place_work(project_id: uuid.UUID, place_id: uuid.UUID,
                     auth: AuthorizationContext = Depends(get_auth_context),
                     conn: AsyncConnection = Depends(get_db_conn),
                     object_storage: ObjectStoragePort = Depends(get_object_storage)):
    """LP-05: the work at a place and its rooms, newest first, each with its photos (short-lived links)."""
    await _project(conn, auth, project_id)
    rows = await store.places(conn, auth.organization_id, project_id)
    place = next((r for r in rows if r["id"] == place_id), None)
    if place is None:
        raise HTTPException(status_code=404, detail="Place not found")
    labels = {r["path"]: r["label"] for r in rows}
    entries = []
    for w in await store.place_work(conn, auth.organization_id, project_id, place["path"]):
        photos = [u for u in [await signed_media_url(object_storage, k) for k in w["photo_keys"] or []] if u]
        entries.append({"id": str(w["id"]), "date": w["activity_date"].isoformat(), "work_type": w["work_type"],
                        "narrative": w["narrative"], "finished": bool(w["finished"]),
                        "place": labels.get(w["path"], w["place"]), "reported_by": w["reported_by"],
                        "photos": photos})
    return {"place": _place_out(place), "work": entries}
