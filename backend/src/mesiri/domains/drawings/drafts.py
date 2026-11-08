"""Drafts from a read drawing set (DR-05 schedule, DR-06 BOQ quantities). Pure.

Both are drafts a person edits and confirms; nothing here is saved, and saving never overwrites what the project
already has (D-DR2).

**Schedule (DR-05).** The floors the plans show (basement, ground, first ...) become a building sequence a Kerala
contractor recognises: the foundation once, then each floor's columns and slab going up, then masonry, plaster and
flooring floor by floor, then finishes and handover. Durations are typical working days for a small commercial or
residential building (``DAYS``), meant to be changed.

**BOQ quantities (DR-06).** From each plan's rooms (sizes in the drawing's units): floor area (flooring, ceiling
plaster), room perimeters × clear height (wall plaster and paint, both sides of a partition counted once per room
face, doors and windows not deducted), skirting (perimeter), and the fixtures counted from labels. The clear height
comes from the levels: the floor-to-floor height between the two lowest floors at or above ground, less a 15 cm slab;
3.0 m when the levels don't say. Every line says how it was worked out.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from mesiri.domains.drawings.facts import area_of

#: Typical working days per activity; the person changes them in the preview.
DAYS = {
    "Site clearing and setting out": 3, "Excavation": 7, "Footings and columns up to plinth": 12, "Plinth beam": 7,
    "Basement retaining wall": 12, "columns": 6, "slab and beams": 12, "masonry": 10, "plastering": 10,
    "flooring": 8, "Electrical and plumbing": 15, "Painting": 15, "Doors, windows and fittings": 10,
    "Handover": 0,
}
_UP = {"basement": 0, "cellar": 0, "stilt": 1, "lower ground": 1, "ground": 2, "upper ground": 3, "first": 4,
       "second": 5, "third": 6, "fourth": 7, "fifth": 8, "sixth": 9, "terrace": 20, "roof": 21}
#: Rooms that get no flooring, plaster or paint in the draft.
_NOT_ROOMS = ("LIFT", "STAIR", "DUCT", "SHAFT", "RAMP")
SLAB_CM = 15.0
#: A floor with sized rooms under this share of the biggest floor's gets a warning.
COVERAGE = 0.4
DEFAULT_CLEAR_M = 3.0


def _order(floor: str) -> int:
    f = floor.lower().replace(" floor", "")
    return _UP.get(f, 10)


def floors(read: Mapping[str, Any]) -> list[str]:
    """The plans' floors, bottom to top, each once."""
    seen: list[str] = []
    for f in read.get("floors") or []:
        if f not in seen and f.lower() not in ("terrace", "roof", "foundation", "footing", "plinth"):
            seen.append(f)
    return sorted(seen, key=_order)


def schedule(read: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Activities in building order: ``{"name", "days"}`` (0 days = a milestone)."""
    fl = floors(read) or ["Ground floor"]
    out = [{"name": "Site clearing and setting out", "days": DAYS["Site clearing and setting out"]},
           {"name": "Excavation", "days": DAYS["Excavation"]}]
    if any(f.lower() in ("basement", "cellar") for f in fl):
        out.append({"name": "Basement retaining wall", "days": DAYS["Basement retaining wall"]})
    out += [{"name": "Footings and columns up to plinth", "days": DAYS["Footings and columns up to plinth"]},
            {"name": "Plinth beam", "days": DAYS["Plinth beam"]}]
    for f in fl:
        out += [{"name": f"{f}: columns", "days": DAYS["columns"]},
                {"name": f"{f}: slab and beams", "days": DAYS["slab and beams"]}]
    for f in fl:
        out += [{"name": f"{f}: masonry", "days": DAYS["masonry"]}]
    for f in fl:
        out += [{"name": f"{f}: plastering", "days": DAYS["plastering"]},
                {"name": f"{f}: flooring", "days": DAYS["flooring"]}]
    out += [{"name": n, "days": DAYS[n]} for n in ("Electrical and plumbing", "Painting", "Doors, windows and fittings",
                                                  "Handover")]
    return out


def clear_height_m(read: Mapping[str, Any]) -> tuple[float, str]:
    """The clear height for wall finishes, and how it was found."""
    units = read.get("units") or "cm"
    to_m = {"mm": 0.001, "m": 1.0}.get(units, 0.01)
    values = sorted(lv["value"] for lv in read.get("levels") or [])
    # Floors: levels at or above ground, merged when within 60 cm (a slab top and its finish are one floor).
    groups: list[float] = []
    for v in (v for v in values if v * to_m >= -0.05):
        if groups and (v - groups[-1]) * to_m < 0.6:
            continue
        groups.append(v)
    if len(groups) >= 2:
        f2f = (groups[1] - groups[0]) * to_m
        if 2.4 <= f2f <= 6.0:
            clear = round(f2f - SLAB_CM / 100, 2)
            return clear, f"floor to floor {f2f:.2f} m from the levels, less a {SLAB_CM:.0f} cm slab"
    return DEFAULT_CLEAR_M, f"{DEFAULT_CLEAR_M:.1f} m assumed: the levels don't give a floor-to-floor height"


def boq(read: Mapping[str, Any]) -> dict[str, Any]:
    """Draft BOQ lines per floor: ``{"clear_height_m", "height_note", "sections": [{"name", "lines": [{"work",
    "unit", "quantity", "basis"}]}]}``. Quantities are rounded to 0.01 (m², m) or whole (nos)."""
    clear, note = clear_height_m(read)
    units = read.get("units") or "cm"
    to_m = {"mm": 0.001, "m": 1.0}.get(units, 0.01)
    sections = []
    for sheet in sorted((s for s in read.get("sheets") or [] if s.get("kind") == "plan"),
                        key=lambda s: _order(s.get("level") or "")):
        rooms = [r for r in sheet.get("rooms") or [] if not any(x in r["label"] for x in _NOT_ROOMS)]
        if not rooms and not any((sheet.get("fixtures") or {}).values()):
            continue
        floor_area = sum(area_of(r["a"], r["b"], units)["sqm"] for r in rooms)
        perimeter = sum(2 * (r["a"] + r["b"]) * to_m for r in rooms)
        n = len(rooms)
        lines = []
        if rooms:
            lines += [
                {"work": "Flooring (vitrified tiles)", "unit": "sqm", "quantity": round(floor_area, 2),
                 "basis": f"{n} rooms' floor area"},
                {"work": "Skirting", "unit": "rm", "quantity": round(perimeter, 2),
                 "basis": f"{n} rooms' perimeters, doors not deducted"},
                {"work": "Ceiling plaster 12 mm", "unit": "sqm", "quantity": round(floor_area, 2),
                 "basis": "same as the floor area"},
                {"work": "Wall plaster 12 mm (inside)", "unit": "sqm", "quantity": round(perimeter * clear, 2),
                 "basis": f"perimeters × {clear:.2f} m clear height, openings not deducted"},
                {"work": "Painting (walls and ceiling)", "unit": "sqm",
                 "quantity": round(perimeter * clear + floor_area, 2), "basis": "wall plaster + ceiling"},
            ]
        fx = sheet.get("fixtures") or {}
        for key, work in (("toilet", "WC with fittings"), ("urinal", "Urinal with fittings"),
                          ("wash", "Wash basin with fittings")):
            if fx.get(key):
                lines.append({"work": work, "unit": "nos", "quantity": fx[key],
                              "basis": f"{fx[key]} labelled on the plan"})
        sections.append({"name": sheet.get("level") or sheet.get("title") or f"Page {sheet['page']}",
                         "page": sheet["page"], "lines": lines, "area_sqm": round(floor_area, 2), "warning": None})
    # A floor whose sized rooms cover much less than the biggest floor: its halls or parking have no printed size,
    # so the quantities above leave them out. Said, never filled in by guess.
    biggest = max((s["area_sqm"] for s in sections), default=0)
    for s in sections:
        if biggest and s["area_sqm"] < COVERAGE * biggest:
            s["warning"] = (f"Only {s['area_sqm']:.0f} m² of rooms have a printed size on this floor (the largest floor "
                            f"has {biggest:.0f} m²). Areas without a size, such as halls or parking, are not included: "
                            "add them by hand.")
    found = (read.get("structure") or {}).get("foundation") or {}
    if found.get("footings"):
        # DR-09: the foundation from the structural set's schedules, before the floors.
        st = read["structure"]
        lines = [
            {"work": f"PCC {found['pcc_mix']} below footings", "unit": "cum", "quantity": found["pcc_cum"],
             "basis": f"{found['footings']} footings, 10 cm thick, beyond each footing as the notes say"},
            {"work": f"RCC {found['concrete_grade']} in footings", "unit": "cum", "quantity": found["concrete_cum"],
             "basis": "; ".join(f"{f['mark']} × {f['count']}" for f in st["footings"] if f.get("concrete_cum"))},
            {"work": f"Steel {st['notes'].get('steel') or 'Fe 500'} in footings", "unit": "kg",
             "quantity": found["steel_kg"],
             "basis": ", ".join(f"{d}: {kg:,.0f} kg" for d, kg in found["steel_by_dia"].items())
                      + " (net cut lengths)"},
        ]
        sections.insert(0, {"name": "Foundation", "page": st.get("plan_page"), "lines": lines, "area_sqm": 0,
                            "warning": None})
    return {"clear_height_m": clear, "height_note": note, "sections": sections}
