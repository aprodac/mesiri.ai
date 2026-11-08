"""Live plans (DR-10, DR-11): the project's drawings as live maps of the building.

Every footing on a structural set's footing plan, and every room on an architect's floor plan, is a place (LP), so
the work site reports on WhatsApp ("B3 footing concreted", "first floor kitchen plastering done") lands on it. A map
is the drawing's own page as a picture with a marker where each footing or room is, coloured by that work, per trade,
with the newest photos; plus a feed of the newest updates.

- ``render_plans``: at upload, a picture of each floor plan with rooms (the footing plan is DR-10's).
- ``track``: the drawing's footings ("Foundation / B3") and rooms ("Ground Floor / Kitchen") become places; places
  already there are kept, a room named the same way ("Room 1" / "ROOM-1") is the same room.
- ``maps``: every map of the project's current drawings, newest drawing per floor.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import re
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.domains.places import names, progress
from mesiri.domains.places import store as places
from mesiri.domains.shared.media import signed_media_url
from mesiri_contracts.common.storage import ObjectStoragePort

_log = logging.getLogger(__name__)

FOUNDATION = "Foundation"
#: Floor plans drawn as pictures per drawing (a big set has a plan per floor; more are rare and slow to draw).
MAX_PLANS = 8
#: An update this recent glows on the map.
FRESH = datetime.timedelta(hours=48)
#: A room is shown where its name is printed: the marker covers the name, just above the size printed under it
#: (rooms are read from the size's position).
LABEL_NUDGE = (16.0, -3.0)


def floor_sheets(facts: dict[str, Any] | None) -> list[dict[str, Any]]:
    """The floor plans of a drawing that show rooms (an architect's plans; never a structural sheet)."""
    return [s for s in (facts or {}).get("sheets") or []
            if s.get("kind") == "plan" and s.get("discipline") != "structural" and len(s.get("rooms") or []) >= 2
            and s.get("width")][:MAX_PLANS]


def room_name(label: str) -> str:
    """A room as people write it: "KITCHEN" -> "Kitchen", "M. TOILET" -> "M. Toilet", "ROOM-1" -> "Room-1"."""
    return " ".join(label.split()).title() if label.isupper() else " ".join(label.split())


def floor_name(level: str) -> str:
    return " ".join(w.capitalize() for w in level.split())


async def render_plans(data: bytes, facts: dict[str, Any], object_storage: ObjectStoragePort, key_base: str) -> None:
    """Pictures of the floor plans, kept with the drawing (``facts["plans"]``). A failure leaves the map
    without its picture, never the drawing unkept."""
    from mesiri.domains.drawings.pdf_text import render_png

    plans = []
    for sheet in floor_sheets(facts):
        entry = {"page": sheet["page"], "level": sheet.get("level") or sheet.get("title")}
        try:
            png, w, h = await asyncio.wait_for(asyncio.to_thread(render_png, data, sheet["page"]), 20)
            entry["image_key"] = f"{key_base}/plan-page-{sheet['page']}.png"
            await object_storage.put_object(entry["image_key"], png, content_type="image/png")
            entry["image_width"], entry["image_height"] = w, h
        except Exception:  # noqa: BLE001
            _log.info("documents.floor_plan_image_failed page=%s", sheet["page"], exc_info=True)
        plans.append(entry)
    if plans:
        facts["plans"] = plans


def _grid_walk(f: dict) -> tuple:
    """Footings grid line by grid line, as site walks it: A1, D1, E1, B2, A3 ..."""
    m = re.match(r"([A-Z]+)(\d+)$", f.get("grid") or "")
    return (int(m.group(2)), m.group(1)) if m else (9999, f.get("grid") or "")


def _floor_root(rows: list[dict], level: str) -> dict | None:
    want = names.floor_number(level)[0]
    for r in rows:
        if r["parent_id"] is None and (r["name"].lower() == level.lower()
                                       or (want is not None and names.floor_number(r["name"])[0] == want)):
            return r
    return None


def _rooms_by_name(rows: list[dict], root: dict | None) -> dict[str, dict]:
    return {names.compact(r["name"]): r for r in rows if root and r["parent_id"] == root["id"]}


def _sheet_rooms(sheet: dict[str, Any]) -> list[tuple[str, dict]]:
    """Each room on a sheet with its place name; the same name twice on a floor is "Toilet", "Toilet 2"."""
    seen: dict[str, int] = {}
    out = []
    for room in sheet.get("rooms") or []:
        name = room_name(room["label"])
        n = seen.get(names.compact(name), 0) + 1
        seen[names.compact(name)] = n
        out.append((name if n == 1 else f"{name} {n}", room))
    return out


async def track(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID, facts: dict[str, Any],
                user_id: uuid.UUID | None) -> dict[str, Any]:
    """The drawing's footings and rooms become places. Running it again adds nothing."""
    out: dict[str, Any] = {}
    plan = (facts.get("structure") or {}).get("plan")
    if plan and plan.get("footings"):
        rows = await places.places(conn, org, project_id)
        root = next((p for p in rows if p["parent_id"] is None and p["name"].lower() == FOUNDATION.lower()), None)
        if root is None:
            root = await places.add(conn, org, project_id, name=FOUNDATION, level_label="Stage", parent_id=None,
                                    user_id=user_id, sort_order=-1)
        have = {p["name"].lower() for p in rows if p["parent_id"] == root["id"]}
        made = 0
        for f in sorted(plan["footings"], key=_grid_walk):
            name = f.get("grid")
            if not name or name.lower() in have:
                continue
            await places.add(conn, org, project_id, name=name, level_label=f"Footing {f['mark']}",
                             parent_id=root["id"], user_id=user_id)
            have.add(name.lower())
            made += 1
        out.update({"made": made, "tracked": len(have),
                    "untracked": sum(1 for f in plan["footings"] if not f.get("grid"))})
    sheets = {s["page"]: s for s in floor_sheets(facts)}
    rooms_made = rooms_tracked = 0
    for entry in facts.get("plans") or []:
        sheet = sheets.get(entry["page"])
        level = entry.get("level")
        if not sheet or not level:
            continue
        rows = await places.places(conn, org, project_id)
        root = _floor_root(rows, level)
        if root is None:
            number = names.floor_number(level)[0]
            order = number if isinstance(number, int) else 50
            root = await places.add(conn, org, project_id, name=floor_name(level), level_label="Floor",
                                    parent_id=None, user_id=user_id, sort_order=order)
        have = _rooms_by_name(rows, root)
        for name, _room in _sheet_rooms(sheet):
            rooms_tracked += 1
            if names.compact(name) in have:
                continue
            made_room = await places.add(conn, org, project_id, name=name, level_label="Room", parent_id=root["id"],
                                         user_id=user_id)
            have[names.compact(name)] = made_room
            rooms_made += 1
    if facts.get("plans"):
        out["rooms"] = {"made": rooms_made, "tracked": rooms_tracked}
    return out


def _overall(cells: dict[str, dict], kinds: set[str], rule: str) -> str:
    states = [cells[k]["state"] for k in kinds if k in cells]
    if rule == "foundation":  # a footing is done when any stage there is marked finished (concreted)
        return "done" if "done" in states else "in_progress" if any(s != "not_started" for s in states) \
            else "not_started"
    if states and all(s == "done" for s in states):
        return "done"
    return "in_progress" if any(s != "not_started" for s in states) else "not_started"


async def maps(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID,
               object_storage: ObjectStoragePort) -> dict[str, Any]:
    docs = (await conn.execute(text(
        "SELECT id, number, title, revision, facts FROM project_documents WHERE organization_id = :org "
        "AND project_id = :p AND status = 'current' AND (facts -> 'structure' -> 'plan' -> 'footings' IS NOT NULL "
        "OR facts -> 'plans' IS NOT NULL) ORDER BY created_at DESC"), {"org": org, "p": project_id})).mappings().all()
    rows = await places.places(conn, org, project_id)
    works = await places.works(conn, org, project_id)
    rolled = progress.roll_up(rows, works)
    kind_names = {k["key"]: k["name"] for k in rolled["kinds"]}
    by_place: dict[uuid.UUID, list] = {}
    for w in works:
        by_place.setdefault(w.location_id, []).append(w)
    photos = await places.latest_photos(conn, org, project_id)
    feed_rows = await places.recent_work(conn, org, project_id, limit=40)
    now = datetime.datetime.now(datetime.UTC)
    fresh = {r["location_id"] for r in feed_rows if r["created_at"] and now - r["created_at"] < FRESH}

    async def thumbs(place_id: uuid.UUID | None) -> list[str]:
        urls = [await signed_media_url(object_storage, k) for k in photos.get(place_id, [])] if place_id else []
        return [u for u in urls if u]

    async def marker(place: dict | None, key: str, label: str, sub: str | None, x: float, y: float,
                     kinds: set[str], rule: str, extra: dict) -> dict[str, Any]:
        cells = rolled["places"][place["id"]]["cells"] if place else {}
        here = sorted(by_place.get(place["id"], []) if place else [], key=lambda w: w.day)
        last = here[-1] if here else None
        return {"key": key, "label": label, "sub": sub, "x": round(x, 4), "y": round(y, 4),
                "place_id": str(place["id"]) if place else None, "state": _overall(cells, kinds, rule),
                "cells": {k: cells[k]["state"] for k in kinds if k in cells},
                "last_work": last.work_type if last else None, "last_date": last.day.isoformat() if last else None,
                "updates": len(here), "photos": sum(w.photos for w in here), "thumbs": await thumbs(
                    place["id"] if place else None), "fresh": bool(place and place["id"] in fresh), **extra}

    def kinds_under(root: dict | None) -> set[str]:
        if not root:
            return set()
        cells = rolled["places"][root["id"]]["cells"]
        return {k for k, c in cells.items() if c["state"] != "not_started"}

    def kind_stats(markers: list[dict], kinds: set[str]) -> list[dict]:
        tracked = [m for m in markers if m["place_id"]]
        return [{"key": k, "name": kind_names.get(k, k), "done": sum(1 for m in tracked if m["cells"].get(k) == "done"),
                 "started": sum(1 for m in tracked if m["cells"].get(k) == "in_progress"), "total": len(tracked)}
                for k in sorted(kinds, key=lambda k: list(kind_names).index(k) if k in kind_names else 99)]

    def summary(markers: list[dict]) -> dict[str, int]:
        out = {"done": 0, "in_progress": 0, "not_started": 0}
        for m in markers:
            out[m["state"]] += 1
        return {**out, "count": len(markers), "photos": sum(m["photos"] for m in markers)}

    result: list[dict[str, Any]] = []
    seen_levels: set[str] = set()
    foundation_done = False
    for d in docs:
        facts = d["facts"] or {}
        doc = {"id": str(d["id"]), "number": d["number"], "title": d["title"], "revision": d["revision"]}
        plan = (facts.get("structure") or {}).get("plan")
        if plan and plan.get("footings") and not foundation_done:
            foundation_done = True
            root = next((p for p in rows if p["parent_id"] is None and p["name"].lower() == FOUNDATION.lower()), None)
            by_name = {p["name"].lower(): p for p in rows if root and p["parent_id"] == root["id"]}
            kinds = kinds_under(root)
            w, h = plan.get("width") or 1, plan.get("height") or 1
            markers, done_cum = [], [0.0, 0.0, 0.0, 0.0]
            for f in plan["footings"]:
                place = by_name.get((f.get("grid") or "").lower())
                m = await marker(place, str(place["id"]) if place else f"f-{f['x']}-{f['y']}", f.get("grid") or f["mark"],
                                 " · ".join(x for x in (f["mark"], f.get("column"), f.get("size")) if x),
                                 f["x"] / w, f["y"] / h, kinds, "foundation",
                                 {"concrete_cum": f.get("concrete_cum"), "steel_kg": f.get("steel_kg")})
                markers.append(m)
                done_cum[2] += f.get("concrete_cum") or 0
                done_cum[3] += f.get("steel_kg") or 0
                if m["state"] == "done":
                    done_cum[0] += f.get("concrete_cum") or 0
                    done_cum[1] += f.get("steel_kg") or 0
            result.append({
                "id": f"{d['id']}:{plan.get('page')}", "kind": "foundation", "name": FOUNDATION, "document": doc,
                "page": plan.get("page"), "order": -1,
                "image_url": await signed_media_url(object_storage, plan["image_key"]) if plan.get("image_key") else None,
                "image_width": plan.get("image_width"), "image_height": plan.get("image_height"),
                "tracked": root is not None, "markers": markers, "kinds": kind_stats(markers, kinds),
                "summary": {**summary(markers), "concrete_done_cum": round(done_cum[0], 2),
                            "concrete_cum": round(done_cum[2], 2), "steel_done_kg": round(done_cum[1], 1),
                            "steel_kg": round(done_cum[3], 1)}})
        sheets = {s["page"]: s for s in floor_sheets(facts)}
        for entry in facts.get("plans") or []:
            sheet = sheets.get(entry["page"])
            level = entry.get("level") or ""
            if not sheet or level.lower() in seen_levels:
                continue
            seen_levels.add(level.lower())
            root = _floor_root(rows, level)
            have = _rooms_by_name(rows, root)
            kinds = kinds_under(root)
            w, h = sheet.get("width") or 1, sheet.get("height") or 1
            markers = []
            for name, room in _sheet_rooms(sheet):
                place = have.get(names.compact(name))
                area = (room.get("computed") or {})
                sub = " · ".join(x for x in (room.get("size_text"), f"{area['sqm']:g} m²" if area.get("sqm") else None)
                                 if x)
                markers.append(await marker(place, str(place["id"]) if place else f"r-{room['x']}-{room['top']}",
                                            name, sub, (room["x"] + LABEL_NUDGE[0]) / w, (room["top"] + LABEL_NUDGE[1]) / h,
                                            kinds, "rooms", {"area_sqm": area.get("sqm"), "area_sqft": area.get("sqft")}))
            number = names.floor_number(level)[0]
            result.append({
                "id": f"{d['id']}:{entry['page']}", "kind": "floor", "name": floor_name(level) if level else
                f"Page {entry['page']}", "document": doc, "page": entry["page"],
                "order": number if isinstance(number, int) else 50,
                "image_url": await signed_media_url(object_storage, entry["image_key"]) if entry.get("image_key") else None,
                "image_width": entry.get("image_width"), "image_height": entry.get("image_height"),
                "tracked": bool(root) and any(m["place_id"] for m in markers), "markers": markers,
                "kinds": kind_stats(markers, kinds), "summary": summary(markers)})
    result.sort(key=lambda m: m["order"])
    labels = {p["id"]: p["label"] for p in rows}
    where = {m["place_id"]: mp["id"] for mp in result for m in mp["markers"] if m["place_id"]}
    feed = [{"id": str(r["id"]), "place": labels.get(r["location_id"]), "place_id": str(r["location_id"]),
             "map_id": where.get(str(r["location_id"])), "work": r["work_type"], "finished": bool(r["finished"]),
             "who": r["who"], "date": r["activity_date"].isoformat(), "at": r["created_at"].isoformat(),
             "via": "WhatsApp" if (r["source"] or "").startswith("whatsapp") else "Dashboard",
             "photo": await signed_media_url(object_storage, r["photo"]) if r["photo"] else None}
            for r in feed_rows[:15]]
    return {"maps": result, "feed": feed}
