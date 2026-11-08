"""PostgreSQL reads and writes for a project's places (LP-01..05): the ``location_nodes`` tree (0410, 0526).

A place is a floor (a root) or a room in it; deeper trees work the same. ``path`` is the ids from the root to the
place, kept on every insert and move. Every function takes the request's connection and never commits.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.domains.places import names
from mesiri.domains.places.progress import Work


class PlaceError(ValueError):
    """A change refused, with the words to show."""


async def project_exists(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID) -> bool:
    return (await conn.execute(text("SELECT 1 FROM projects WHERE id = :p AND organization_id = :org"),
                               {"p": project_id, "org": org})).first() is not None


async def places(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID, *,
                 archived: bool = False) -> list[dict[str, Any]]:
    """The project's places, tree order: each floor, then its rooms (by sort_order, then when added)."""
    rows = (await conn.execute(text(
        "SELECT id, parent_id, name, level_label, path, sort_order, archived_at, site_id FROM location_nodes "
        "WHERE organization_id = :org AND project_id = :p" + ("" if archived else " AND archived_at IS NULL") +
        " ORDER BY sort_order, created_at, name"), {"org": org, "p": project_id})).mappings().all()
    kids: dict[uuid.UUID | None, list[dict]] = {}
    ids = {r["id"] for r in rows}
    for r in rows:
        parent = r["parent_id"] if r["parent_id"] in ids else None
        kids.setdefault(parent, []).append(dict(r))
    out: list[dict[str, Any]] = []

    def walk(parent: uuid.UUID | None, depth: int, prefix: str) -> None:
        for r in kids.get(parent, []):
            r["depth"] = depth
            r["label"] = f"{prefix} / {r['name']}" if prefix else r["name"]
            out.append(r)
            walk(r["id"], depth + 1, r["label"])

    walk(None, 0, "")
    return out


def as_names(rows: list[dict[str, Any]]) -> list[names.Place]:
    return [names.Place(id=r["id"], name=r["name"], parent_id=r["parent_id"], level_label=r["level_label"])
            for r in rows]


async def _one(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID, place_id: uuid.UUID) -> dict | None:
    row = (await conn.execute(text(
        "SELECT id, parent_id, name, level_label, path, sort_order, archived_at FROM location_nodes "
        "WHERE id = :id AND organization_id = :org AND project_id = :p"),
        {"id": place_id, "org": org, "p": project_id})).mappings().first()
    return dict(row) if row else None


async def _name_taken(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID, parent_id: uuid.UUID | None,
                      name: str, but: uuid.UUID | None = None) -> bool:
    return (await conn.execute(text(
        "SELECT 1 FROM location_nodes WHERE organization_id = :org AND project_id = :p AND archived_at IS NULL "
        "AND parent_id IS NOT DISTINCT FROM :parent AND lower(name) = lower(:name) "
        "AND (CAST(:but AS uuid) IS NULL OR id <> CAST(:but AS uuid))"),
        {"org": org, "p": project_id, "parent": parent_id, "name": name, "but": but})).first() is not None


async def add(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID, *, name: str, level_label: str | None,
              parent_id: uuid.UUID | None, user_id: uuid.UUID | None, sort_order: int | None = None) -> dict:
    parent = None
    if parent_id is not None:
        parent = await _one(conn, org, project_id, parent_id)
        if parent is None or parent["archived_at"] is not None:
            raise PlaceError("That floor is not in this project")
    if await _name_taken(conn, org, project_id, parent_id, name):
        where = f" on {parent['name']}" if parent else ""
        raise PlaceError(f"There is already a place called {name}{where}")
    if sort_order is None:
        sort_order = (await conn.execute(text(
            "SELECT COALESCE(max(sort_order), -1) + 1 FROM location_nodes WHERE organization_id = :org "
            "AND project_id = :p AND parent_id IS NOT DISTINCT FROM :parent"),
            {"org": org, "p": project_id, "parent": parent_id})).scalar()
    new_id = uuid.uuid4()
    path = f"{parent['path']}/{new_id}" if parent else str(new_id)
    level = level_label or ("Room" if parent else "Floor")
    await conn.execute(text(
        "INSERT INTO location_nodes (id, organization_id, project_id, parent_id, level_label, name, path, sort_order, "
        "created_by) VALUES (:id, :org, :p, :parent, :level, :name, :path, :sort, :by)"),
        {"id": new_id, "org": org, "p": project_id, "parent": parent_id, "level": level, "name": name,
         "path": path, "sort": sort_order, "by": user_id})
    return {"id": new_id, "parent_id": parent_id, "name": name, "level_label": level, "sort_order": sort_order}


async def setup(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID, *, floors: list[str],
                rooms: list[str], user_id: uuid.UUID | None) -> dict[str, int]:
    """Floors x rooms in one go (the same rooms on every floor). Places already there are kept, never doubled."""
    existing = await places(conn, org, project_id)
    roots = {r["name"].lower(): r for r in existing if r["parent_id"] is None}
    made_floors = made_rooms = 0
    for floor_name in floors:
        floor = roots.get(floor_name.lower())
        if floor is None:
            floor = await add(conn, org, project_id, name=floor_name, level_label="Floor", parent_id=None,
                              user_id=user_id)
            roots[floor_name.lower()] = floor
            made_floors += 1
        have = {r["name"].lower() for r in existing if r["parent_id"] == floor["id"]}
        for room in rooms:
            if room.lower() in have:
                continue
            await add(conn, org, project_id, name=room, level_label="Room", parent_id=floor["id"], user_id=user_id)
            have.add(room.lower())
            made_rooms += 1
    return {"floors": made_floors, "rooms": made_rooms}


async def change(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID, place_id: uuid.UUID, *,
                 name: str | None, sort_order: int | None, parent_id: uuid.UUID | None, move: bool,
                 level_label: str | None) -> dict:
    place = await _one(conn, org, project_id, place_id)
    if place is None or place["archived_at"] is not None:
        raise PlaceError("Place not found")
    new_parent = parent_id if move else place["parent_id"]
    new_name = name or place["name"]
    parent = None
    if move and new_parent is not None:
        parent = await _one(conn, org, project_id, new_parent)
        if parent is None or parent["archived_at"] is not None:
            raise PlaceError("That floor is not in this project")
        if str(place_id) in parent["path"].split("/"):
            raise PlaceError("A place cannot go inside itself or one of its rooms")
    if (name or move) and await _name_taken(conn, org, project_id, new_parent, new_name, but=place_id):
        raise PlaceError(f"There is already a place called {new_name} there")
    await conn.execute(text(
        "UPDATE location_nodes SET name = :name, sort_order = COALESCE(:sort, sort_order), "
        "level_label = COALESCE(:level, level_label), parent_id = :parent, updated_at = now() WHERE id = :id"),
        {"name": new_name, "sort": sort_order, "level": level_label, "parent": new_parent, "id": place_id})
    if move and new_parent != place["parent_id"]:
        new_path = f"{parent['path']}/{place_id}" if parent else str(place_id)
        # The place and everything under it: swap the old prefix for the new one.
        await conn.execute(text(
            "UPDATE location_nodes SET path = :new || substr(path, length(:old) + 1), updated_at = now() "
            "WHERE organization_id = :org AND project_id = :p AND (path = :old OR path LIKE :old || '/%')"),
            {"new": new_path, "old": place["path"], "org": org, "p": project_id})
    return {"id": place_id, "name": new_name, "parent_id": new_parent}


async def remove(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID, place_id: uuid.UUID) -> str:
    """Delete a place and its rooms when no work, issue or schedule item points at them; archive them otherwise."""
    place = await _one(conn, org, project_id, place_id)
    if place is None or place["archived_at"] is not None:
        raise PlaceError("Place not found")
    params = {"org": org, "p": project_id, "path": place["path"]}
    subtree = ("SELECT id FROM location_nodes WHERE organization_id = :org AND project_id = :p "
               "AND (path = :path OR path LIKE :path || '/%')")
    used = (await conn.execute(text(
        f"SELECT EXISTS (SELECT 1 FROM activities WHERE location_id IN ({subtree})) "
        f"OR EXISTS (SELECT 1 FROM site_issues WHERE location_id IN ({subtree})) "
        f"OR EXISTS (SELECT 1 FROM work_packages WHERE location_id IN ({subtree}))"), params)).scalar()
    if used:
        await conn.execute(text(f"UPDATE location_nodes SET archived_at = now(), updated_at = now() "
                                f"WHERE id IN ({subtree})"), params)
        return "archived"
    await conn.execute(text(f"DELETE FROM location_nodes WHERE id IN ({subtree})"), params)
    return "deleted"


async def works(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID) -> list[Work]:
    """Every work entry with a place on the project (not undone), with whether it was finished and its photos."""
    rows = (await conn.execute(text(
        "SELECT a.location_id, a.work_type, a.activity_date, "
        "(a.status = 'COMPLETED' OR EXISTS (SELECT 1 FROM progress_updates u WHERE u.activity_id = a.id "
        "  AND u.update_kind = 'COMPLETED' AND u.deleted_at IS NULL)) AS finished, "
        "(SELECT count(*) FROM progress_attachments pa WHERE pa.parent_type = 'ACTIVITY' AND pa.parent_id = a.id) "
        "+ (SELECT count(*) FROM progress_attachments pa JOIN progress_updates u ON pa.parent_type = "
        "  'PROGRESS_UPDATE' AND pa.parent_id = u.id WHERE u.activity_id = a.id AND u.deleted_at IS NULL) AS photos "
        "FROM activities a JOIN location_nodes n ON n.id = a.location_id "
        "WHERE a.organization_id = :org AND a.project_id = :p AND a.deleted_at IS NULL"),
        {"org": org, "p": project_id})).mappings().all()
    return [Work(location_id=r["location_id"], work_type=r["work_type"], finished=bool(r["finished"]),
                 day=r["activity_date"], photos=int(r["photos"] or 0)) for r in rows]


async def place_work(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID, path: str,
                     limit: int = 60) -> list[dict[str, Any]]:
    """The work recorded at a place and its rooms, newest first, each with its photo keys (LP-05)."""
    rows = (await conn.execute(text(
        "SELECT a.id, a.activity_date, a.work_type, a.narrative, n.name AS place, n.path, "
        "  (a.status = 'COMPLETED' OR EXISTS (SELECT 1 FROM progress_updates c WHERE c.activity_id = a.id "
        "   AND c.update_kind = 'COMPLETED' AND c.deleted_at IS NULL)) AS finished, "
        "  u.full_name AS reported_by, "
        "  ARRAY(SELECT pa.media_object_key FROM progress_attachments pa WHERE (pa.parent_type = 'ACTIVITY' "
        "    AND pa.parent_id = a.id) OR (pa.parent_type = 'PROGRESS_UPDATE' AND pa.parent_id IN "
        "    (SELECT pu.id FROM progress_updates pu WHERE pu.activity_id = a.id AND pu.deleted_at IS NULL)) "
        "    ORDER BY pa.created_at) AS photo_keys "
        "FROM activities a JOIN location_nodes n ON n.id = a.location_id "
        "LEFT JOIN users u ON u.id = a.reported_by_user_id "
        "WHERE a.organization_id = :org AND a.project_id = :p AND a.deleted_at IS NULL "
        "AND (n.path = :path OR n.path LIKE :path || '/%') "
        "ORDER BY a.activity_date DESC, a.created_at DESC LIMIT :limit"),
        {"org": org, "p": project_id, "path": path, "limit": limit})).mappings().all()
    return [dict(r) for r in rows]


async def set_activity_place(conn: AsyncConnection, org: uuid.UUID, activity_id: uuid.UUID,
                             place_id: uuid.UUID | None) -> bool:
    """Put a work entry already saved at a place (or take it off one: None)."""
    result = await conn.execute(text(
        "UPDATE activities a SET location_id = :place, updated_at = now() WHERE a.id = :id "
        "AND a.organization_id = :org AND a.deleted_at IS NULL AND (CAST(:place AS uuid) IS NULL OR EXISTS "
        "(SELECT 1 FROM location_nodes n WHERE n.id = :place AND n.project_id = a.project_id "
        " AND n.archived_at IS NULL))"),
        {"place": place_id, "id": activity_id, "org": org})
    return result.rowcount > 0
