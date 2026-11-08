"""What a drawing says, read from its text (DR-02). Pure: works on ``pdf_text.pages`` word lists.

- **Levels**: "+400 LVL", "±0 LVL", "-265 LVL", "FFL +450", "+12.70 M" on sections and elevations, in the sheet's
  units (most Kerala practices draw in centimetres).
- **Rooms**: a label ("ROOM-1", "TOILET", "M. TOILET", "LIFT") with the size printed under it ("1740 x 590",
  "120X150") and, when given, the area printed with it ("1217 Sq.ft"); with the page and position.
- **Fixtures**: how many toilets, urinals, wash basins, lifts and stairs each plan shows, counted from their labels.

Every fact keeps its page and position, so a person can find it on the sheet and confirm it; nothing is guessed: a
size with no label above it is a size, not a room.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from mesiri.domains.drawings.reader import lines

Word = Mapping[str, Any]

_LEVEL = re.compile(r"^(?:FFL|SFL|LVL|EL\.?|LEVEL)?\s*([+\-±])?\s*(\d+(?:\.\d+)?)\s*(?:LVL|FFL|M)?$", re.I)
_SIZE_ONE = re.compile(r"^(\d+(?:\.\d+)?)\s*[xX×]\s*(\d+(?:\.\d+)?)$")
_NUMBER = re.compile(r"^\d+(?:\.\d+)?$")
_AREA_UNIT = re.compile(r"^(SQ\.?\s*FT|SQFT|SFT|SQ\.?\s*M|SQM|M2|M²)\.?$", re.I)
#: Fixture labels counted on plans (one label is one fixture or room).
FIXTURES = {"toilet": ("TOILET", "WC", "W.C", "W.C."), "urinal": ("URINAL",), "wash": ("WASH", "WASH BASIN"),
            "lift": ("LIFT", "ELEVATOR"), "stair": ("STAIR", "STAIRCASE", "FIRE STAIR")}
_WORD_GAP = 8.0


def levels(words: Iterable[Word]) -> list[dict[str, Any]]:
    """Every level mark on a sheet: ``{"value", "text", "x", "top"}``; the same value once per sheet (its first
    mark). A level is a signed number next to LVL / FFL / EL, or a number with a + / ± sign followed by LVL."""
    out: dict[float, dict[str, Any]] = {}
    for row in lines(words):
        texts = [w["text"] for w in row]
        for i, w in enumerate(row):
            t = w["text"].upper()
            # "+400" "LVL"  /  "±0" "LVL"  /  "FFL" "+450"
            if t in ("LVL", "LEVEL") and i > 0:
                cand, at = texts[i - 1], row[i - 1]
            elif t in ("FFL", "SFL") and i + 1 < len(row):
                cand, at = texts[i + 1], row[i + 1]
            elif t.endswith("LVL") and len(t) > 3:
                cand, at = t[:-3], w
            else:
                continue
            m = _LEVEL.match(cand.strip())
            if not m:
                continue
            sign, number = m.group(1), float(m.group(2))
            value = -number if sign == "-" else number
            if value not in out:
                out[value] = {"value": value, "text": f"{cand.strip()} {t if t != cand else ''}".strip(),
                              "x": round(at["x0"], 1), "top": round(at["top"], 1)}
    return sorted(out.values(), key=lambda lv: -lv["value"])


def _sizes(rows: list[list[Word]]) -> list[dict[str, Any]]:
    """Every "A x B" on the sheet, as one word ("120X150") or three ("1740" "x" "590"), with its box."""
    out = []
    for row in rows:
        i = 0
        while i < len(row):
            w = row[i]
            m = _SIZE_ONE.match(w["text"])
            if m:
                out.append({"a": float(m.group(1)), "b": float(m.group(2)), "x0": w["x0"], "x1": w["x1"],
                            "top": w["top"], "bottom": w["bottom"], "text": w["text"]})
                i += 1
                continue
            # Three words "1740" "x" "590"; never single digits (letters of overlapping text, "0 x 1").
            if (i + 2 < len(row) and _NUMBER.match(w["text"]) and row[i + 1]["text"].lower() in ("x", "×")
                    and _NUMBER.match(row[i + 2]["text"]) and row[i + 2]["x0"] - w["x1"] < 3 * _WORD_GAP
                    and len(w["text"]) > 1 and len(row[i + 2]["text"]) > 1):
                last = row[i + 2]
                out.append({"a": float(w["text"]), "b": float(last["text"]), "x0": w["x0"], "x1": last["x1"],
                            "top": w["top"], "bottom": last["bottom"],
                            "text": f"{w['text']} x {last['text']}"})
                i += 3
                continue
            i += 1
    return out


def _centre(box: Mapping[str, Any]) -> float:
    return (box["x0"] + box["x1"]) / 2


def _label_above(rows: list[list[Word]], size: Mapping[str, Any], height: float) -> tuple[str, Word] | None:
    """The room name printed just above a size: up to two short lines of letters centred over it."""
    found: list[list[Word]] = []
    reach = 1.6 * height
    for row in reversed(rows):
        if row[0]["top"] >= size["top"] - 1:
            continue
        if size["top"] - max(w["bottom"] for w in row) > reach + len(found) * 1.2 * height:
            break
        # Over the size: overlapping its width (a neighbour's label, a room's width away, is not this one's).
        # A lone letter is a piece of overlapping text, except an initial such as "M." (men's) or "F." (women's).
        near = [w for w in row if w["x1"] > size["x0"] - 3 and w["x0"] < size["x1"] + 3
                and abs(_centre(w) - _centre(size)) < (size["x1"] - size["x0"]) / 2 + 4
                and re.search(r"[A-Za-z]", w["text"]) and not _SIZE_ONE.match(w["text"])
                and (len(w["text"].strip(".")) > 1 or (len(w["text"]) == 2 and w["text"].endswith(".")))]
        if near:
            found.append(sorted(near, key=lambda w: w["x0"]))
            if len(found) == 2:
                break
    if not found:
        return None
    words = [w for row in reversed(found) for w in row]
    return " ".join(w["text"] for w in words).strip(), words[-1]


def _area_below(rows: list[list[Word]], size: Mapping[str, Any], height: float) -> dict[str, Any] | None:
    """A stated area just under a size: "1217 Sq.ft"."""
    for row in rows:
        gap = row[0]["top"] - size["bottom"]
        if gap < -1:
            continue
        if gap > 1.6 * height:
            break
        for i, w in enumerate(row):
            if abs(_centre(w) - _centre(size)) > 40 or not _NUMBER.match(w["text"]):
                continue
            unit = row[i + 1]["text"] if i + 1 < len(row) else ""
            if _AREA_UNIT.match(unit.replace(" ", "")):
                return {"value": float(w["text"]), "unit": "sqft" if "F" in unit.upper() else "sqm",
                        "text": f"{w['text']} {unit}"}
    return None


def rooms(words: Iterable[Word]) -> list[dict[str, Any]]:
    """Rooms on a plan: ``{"label", "a", "b", "size_text", "area": {...} | None, "x", "top"}``, top to bottom."""
    rows = lines(words)
    out = []
    for size in _sizes(rows):
        height = max(size["bottom"] - size["top"], 4.0)
        label = _label_above(rows, size, height)
        if label is None:
            continue
        name = re.sub(r"\s+", " ", label[0]).upper()
        if re.fullmatch(r"[\d\s.+\-±]+(LVL)?", name):
            continue
        out.append({"label": name, "a": size["a"], "b": size["b"], "size_text": size["text"],
                    "area": _area_below(rows, size, height), "x": round(size["x0"], 1), "top": round(size["top"], 1)})
    return sorted(out, key=lambda r: (r["top"], r["x"]))


def fixtures(words: Iterable[Word]) -> dict[str, int]:
    """How many of each fixture the sheet labels (a two-word label such as "FIRE STAIR" counts once)."""
    counts = {k: 0 for k in FIXTURES}
    rotated = [[w] for w in words if not w.get("upright", True)]
    for row in lines(words) + rotated:
        texts = [w["text"].upper().strip(".,:") for w in row]
        i = 0
        while i < len(texts):
            two = f"{texts[i]} {texts[i + 1]}" if i + 1 < len(texts) else ""
            hit = None
            for kind, names in FIXTURES.items():
                if two in names:
                    hit, step = kind, 2
                    break
                if texts[i] in names:
                    hit, step = kind, 1
            if hit:
                counts[hit] += 1
                i += step
            else:
                i += 1
    return counts


def area_of(a: float, b: float, units: str | None) -> dict[str, float]:
    """A room's floor area from its size in the drawing's units (cm when not said): m² and sq ft."""
    factor = {"mm": 1e-6, "m": 1.0}.get(units or "cm", 1e-4)
    sqm = a * b * factor
    return {"sqm": round(sqm, 2), "sqft": round(sqm * 10.7639, 1)}
