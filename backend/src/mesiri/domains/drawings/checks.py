"""Mistakes in a drawing set, found before the drawings reach site (DR-03). Pure.

Each check is something to ask the architect, with where it is (page, position) and why it matters. Nothing here
changes a drawing or tells the architect: the person who uploaded the set decides (D-DR1).

- **area_label**: a room's stated area does not match its size (more than ``AREA_TOLERANCE`` apart). When another
  room on the same sheet has the same label and its size does give that area, the label was likely copied.
- **level**: two sheets give a level a few centimetres apart where each has one and not the other (+1167.5 on the
  sections, +1170 on the elevations): one of them is probably wrong.
- **typical_floor**: a room that appears once on each of two plans (ROOM-1 on the ground and first floor) has a
  different size on each.
- **missing**: sheets without a scale, a date or a title; a set with no drawing numbers or no revisions at all.
- **no_text**: a scanned page: nothing on it can be read, so nothing on it was checked.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from typing import Any

from mesiri.domains.drawings.facts import area_of

#: Stated vs worked-out area: more than this share apart is flagged (drawings round to whole sq ft).
AREA_TOLERANCE = 0.03
#: Levels closer than this (in the drawing's units) on two sheets are "probably the same level".
LEVEL_NEAR = 10.0


def _fmt(n: float) -> str:
    return f"{n:,.0f}" if abs(n) >= 100 else f"{n:,.1f}".rstrip("0").rstrip(".")


def area_labels(sheet: Mapping[str, Any]) -> list[dict[str, Any]]:
    out = []
    units = sheet.get("units") or "cm"
    rooms = sheet.get("rooms") or []
    for room in rooms:
        stated = room.get("area")
        if not stated:
            continue
        got = area_of(room["a"], room["b"], units)
        actual = got["sqft"] if stated["unit"] == "sqft" else got["sqm"]
        if actual <= 0 or abs(stated["value"] - actual) / actual <= AREA_TOLERANCE:
            continue
        unit = "sq ft" if stated["unit"] == "sqft" else "m²"
        source = next((r for r in rooms if r is not room and r.get("area") and r["area"]["value"] == stated["value"]
                       and abs(area_of(r["a"], r["b"], units)["sqft" if stated["unit"] == "sqft" else "sqm"]
                               - stated["value"]) / stated["value"] <= AREA_TOLERANCE), None)
        message = (f"{room['label']} is drawn {room['size_text']} {units} ({_fmt(got['sqm'])} m², {_fmt(got['sqft'])} "
                   f"sq ft) but labelled {_fmt(stated['value'])} {unit}.")
        if source:
            message += f" {_fmt(stated['value'])} {unit} is {source['label']}'s area: the label looks copied."
        out.append({"kind": "area_label", "severity": "high", "page": sheet["page"], "sheet": sheet.get("title"),
                    "x": room["x"], "top": room["top"], "message": message,
                    "why": "Rent, sale and flooring quantities are worked out from the area printed on the plan."})
    return out


def levels(sheets: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out = []
    seen: set[tuple[float, float]] = set()
    for a in sheets:
        va = {lv["value"] for lv in a.get("levels") or []}
        for b in sheets:
            if b["page"] <= a["page"]:
                continue
            vb = {lv["value"] for lv in b.get("levels") or []}
            for x in va - vb:
                for y in vb - va:
                    if 0 < abs(x - y) <= LEVEL_NEAR and (x, y) not in seen:
                        seen.add((x, y))
                        out.append({"kind": "level", "severity": "medium", "page": a["page"], "sheet": a.get("title"),
                                    "message": f"Page {a['page']} ({a.get('title') or 'no title'}) has a level "
                                               f"{x:+g} and page {b['page']} ({b.get('title') or 'no title'}) has "
                                               f"{y:+g}: the same level drawn two ways?",
                                    "why": "Site builds to whichever sheet is open; a slab or sill at the wrong "
                                           "height is broken out."})
    return out


def typical_floors(sheets: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """A room label that appears once on each plan, with different sizes between plans."""
    per_label: dict[str, list[tuple[Mapping[str, Any], Mapping[str, Any]]]] = defaultdict(list)
    for s in sheets:
        if s.get("kind") != "plan":
            continue
        counts: dict[str, int] = defaultdict(int)
        for r in s.get("rooms") or []:
            counts[r["label"]] += 1
        for r in s.get("rooms") or []:
            if counts[r["label"]] == 1:
                per_label[r["label"]].append((s, r))
    out = []
    for label, found in per_label.items():
        sizes = {(r["a"], r["b"]) for _, r in found}
        if len(found) > 1 and len(sizes) > 1:
            where = "; ".join(f"{s.get('level') or s.get('title')}: {r['size_text']}" for s, r in found)
            out.append({"kind": "typical_floor", "severity": "low", "page": found[0][0]["page"],
                        "sheet": found[0][0].get("title"), "message": f"{label} has a different size on each plan "
                                                                      f"({where}). Intended?",
                        "why": "Floors drawn as typical are usually built the same; a changed size changes walls, "
                               "doors and finishes."})
    return out


def missing(sheets: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out = []
    readable = [s for s in sheets if s.get("has_text")]
    for field, what in (("title", "title"), ("scale", "scale"), ("date", "date")):
        pages = [s["page"] for s in readable if not s.get(field)]
        if pages:
            out.append({"kind": "missing", "severity": "low", "page": pages[0], "sheet": None,
                        "message": f"No {what} found on page{'s' if len(pages) > 1 else ''} "
                                   f"{', '.join(map(str, pages))}.", "why": "A sheet without it can't be checked or "
                                                                            "filed against the right revision."})
    for field, what in (("number", "drawing number"), ("revision", "revision")):
        if readable and not any(s.get(field) for s in readable):
            out.append({"kind": "missing", "severity": "low", "page": None, "sheet": None,
                        "message": f"No sheet has a {what}.",
                        "why": "Without it, nobody can tell which version of a sheet is the latest on site."})
    for s in sheets:
        if not s.get("has_text"):
            out.append({"kind": "no_text", "severity": "info", "page": s["page"], "sheet": None,
                        "message": f"Page {s['page']} has no text (a scan or a picture): it was not read or checked.",
                        "why": "Ask the architect for the CAD PDF instead of a scan."})
    return out


def run(sheets: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """All checks, most serious first."""
    order = {"high": 0, "medium": 1, "low": 2, "info": 3}
    found = [c for s in sheets for c in area_labels(s)] + levels(sheets) + typical_floors(sheets) + missing(sheets)
    return sorted(found, key=lambda c: (order[c["severity"]], c["page"] or 0))
