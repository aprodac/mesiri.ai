"""Progress by place (LP-03): each place x each kind of work -> done, in progress or not started. Pure.

The kinds of work are the ones the site has reported anywhere on the project (plastering, brickwork, flooring ...),
grouped without case or extra spaces, in the order they were first reported. A cell is

- **done** when work of that kind at the place itself was marked finished, or when the place has rooms and every one
  of them is done;
- **in_progress** when any work of that kind was recorded at the place or any room in it;
- **not_started** otherwise.

"What's left" at a place is every kind of work reported under its own floor (or the Foundation) not done there.
"""

from __future__ import annotations

import datetime
import uuid
from collections import defaultdict
from dataclasses import dataclass

DONE, IN_PROGRESS, NOT_STARTED = "done", "in_progress", "not_started"


@dataclass(frozen=True)
class Work:
    """One work entry with a place."""

    location_id: uuid.UUID
    work_type: str | None
    finished: bool
    day: datetime.date
    photos: int = 0


def work_key(work_type: str | None) -> str:
    return " ".join((work_type or "").lower().split()) or "other work"


def roll_up(places: list[dict], works: list[Work]) -> dict:
    """``places``: dicts with id, parent_id (ordered as shown). Returns kinds and, per place id, cells and totals."""
    children: dict[uuid.UUID | None, list[uuid.UUID]] = {}
    for p in places:
        children.setdefault(p["parent_id"], []).append(p["id"])

    kinds: list[str] = []
    shown: dict[str, dict[str, int]] = {}
    own: dict[tuple[uuid.UUID, str], dict] = {}
    for w in sorted(works, key=lambda w: w.day):
        key = work_key(w.work_type)
        if key not in shown:
            kinds.append(key)
            shown[key] = {}
        label = (w.work_type or "Other work").strip() or "Other work"
        shown[key][label] = shown[key].get(label, 0) + 1
        cell = own.setdefault((w.location_id, key), {"finished": False, "last": w.day, "entries": 0})
        cell["finished"] = cell["finished"] or w.finished
        cell["last"] = max(cell["last"], w.day)
        cell["entries"] += 1

    names = {k: max(v, key=lambda label: v[label]) for k, v in shown.items()}
    photos: dict[uuid.UUID, int] = {}
    for w in works:
        photos[w.location_id] = photos.get(w.location_id, 0) + w.photos

    # "Left" at a place counts only the kinds of work reported under its own top place (a floor's rooms are
    # compared with that floor's work, the Foundation's footings with foundation work): never "footing concrete" in
    # a bedroom.
    parent_of = {p["id"]: p["parent_id"] for p in places}

    def top(pid: uuid.UUID) -> uuid.UUID:
        while parent_of.get(pid) is not None:
            pid = parent_of[pid]
        return pid

    kinds_at: dict[uuid.UUID, set[str]] = defaultdict(set)
    for w in works:
        if w.location_id in parent_of:
            kinds_at[top(w.location_id)].add(work_key(w.work_type))

    out: dict[uuid.UUID, dict] = {}

    def visit(pid: uuid.UUID) -> dict:
        if pid in out:
            return out[pid]
        kids = [visit(c) for c in children.get(pid, [])]
        cells: dict[str, dict] = {}
        for key in kinds:
            mine = own.get((pid, key))
            kid_cells = [k["cells"][key] for k in kids]
            last = max([c["last"] for c in kid_cells if c["last"]] + ([mine["last"]] if mine else []), default=None)
            if (mine and mine["finished"]) or (kids and all(c["state"] == DONE for c in kid_cells)):
                state = DONE
            elif mine or any(c["state"] != NOT_STARTED for c in kid_cells):
                state = IN_PROGRESS
            else:
                state = NOT_STARTED
            cells[key] = {"state": state, "last": last}
        result = {
            "cells": cells,
            "photos": photos.get(pid, 0) + sum(k["photos"] for k in kids),
            "last_update": max([c["last"] for c in cells.values() if c["last"]], default=None),
            "left": [names[k] for k in kinds if cells[k]["state"] != DONE and k in kinds_at[top(pid)]],
            "done": [names[k] for k in kinds if cells[k]["state"] == DONE],
        }
        out[pid] = result
        return result

    for p in places:
        visit(p["id"])
    return {"kinds": [{"key": k, "name": names[k]} for k in kinds], "places": out}
