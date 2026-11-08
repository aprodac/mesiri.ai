"""A drawing sheet's title block and what the sheet is (DR-01). Pure: works on ``pdf_text.pages`` word lists.

From each page: the sheet's title ("GROUND FLOOR PLAN", "SECTION-AA", "FRONT ELEVATION"), what kind of sheet it is
(plan, elevation, section, schedule, detail, site plan), the floor it shows when it is a plan, the discipline, and
the title-block fields offices print on every sheet: project, client, architect, drawing number, revision, scale,
date, drawn / checked by, the units note ("all dimensions are in cm").

Title blocks differ by office, so nothing depends on one layout: a field is found by its label ("PROJECT:", "DWG.TITLE",
"Drg. Title:", "SCALE:") and the words to its right or just below, or by its own shape (a scale is "1:100", a date
"18.05.2026"). A field that is not found is None, never guessed; the checks (DR-03) say what is missing.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

Word = Mapping[str, Any]

#: Words that start a title-block field; the value is to the right of the label or just below it.
LABELS = {
    "project": ("PROJECT", "PROJECT NAME", "NAME OF WORK", "WORK"),
    "client": ("CLIENT", "OWNER"),
    "title": ("DWG.TITLE", "DWG TITLE", "DRG. TITLE", "DRG.TITLE", "DRAWING TITLE", "TITLE", "SHEET TITLE"),
    "number": ("DWG.NO", "DWG NO", "DRG.NO", "DRG NO", "DRAWING NO", "SHEET NO", "DWG.NO.", "DRG. NO"),
    "revision": ("REV", "REV.", "REVISION"),
    "drawn": ("DRAWN", "DRAWN BY"),
    "checked": ("CHECKED", "CHECKED BY"),
}
ALL_LABELS = {lab for labs in LABELS.values() for lab in labs} | {"ARCHITECTS", "ARCHITECT", "SCALE", "DATE",
                                                                    "REMARKS", "NOTE", "APPROVED", "OFFICE SEAL"}

#: How far below a label its value may sit (points).
BELOW = 14

_SCALE = re.compile(r"\b1\s*:\s*(\d{1,4})\b")
_DATE = re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})\b")
_UNITS = re.compile(r"DIMENSIONS\s+(?:ARE\s+)?IN\s+(CM|MM|CENTIMETERS?|MILLIMETERS?|METERS?|M)\b", re.I)
_LEVEL_WORDS = ("BASEMENT", "CELLAR", "STILT", "GROUND", "FIRST", "SECOND", "THIRD", "FOURTH", "FIFTH", "SIXTH",
                "TERRACE", "ROOF", "MEZZANINE", "TYPICAL", "FOUNDATION", "FOOTING", "PLINTH", "LOWER GROUND",
                "UPPER GROUND", "1ST", "2ND", "3RD", "4TH", "5TH")
_TITLE = re.compile(
    r"\b(?:(?:LOWER |UPPER )?(?:BASEMENT|CELLAR|STILT|GROUND|FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH|TERRACE|ROOF|"
    r"MEZZANINE|TYPICAL|FOUNDATION|FOOTING|PLINTH|1ST|2ND|3RD|4TH|5TH|\d+(?:ST|ND|RD|TH))\s+(?:FLOOR\s+)?"
    r"(?:PLAN|LAYOUT)|SITE\s+PLAN|KEY\s+PLAN|LOCATION\s+PLAN|SECTION[\s-]*[A-Z](?:\s?[A-Z])?|"
    r"(?:(?:FRONT|BACK|REAR|LEFT|RIGHT|SIDE|NORTH|SOUTH|EAST|WEST)\s+)+ELEVATION|"
    r"(?:COLUMN|FOOTING|BEAM|SLAB|DOOR|WINDOW)\s+(?:SCHEDULE|DETAILS?|LAYOUT))\b", re.I)


def lines(words: Iterable[Word], tol: float = 2.5) -> list[list[Word]]:
    """Upright words grouped into text lines (same baseline within ``tol`` points), each line left to right.
    Words drawn turned 90° are left out: they run across lines (they still count as fixtures, ``facts.fixtures``)."""
    rows: list[list[Word]] = []
    for w in sorted((w for w in words if w.get("upright", True)), key=lambda w: (round(w["top"]), w["x0"])):
        for row in rows:
            if abs(row[0]["top"] - w["top"]) <= tol:
                row.append(w)
                break
        else:
            rows.append([w])
    for row in rows:
        row.sort(key=lambda w: w["x0"])
    rows.sort(key=lambda r: (r[0]["top"], r[0]["x0"]))
    return rows


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace(":", " ").strip()).upper().strip(" .")


def _is_label(text: str) -> bool:
    t = _norm(text)
    return t in ALL_LABELS or t.rstrip(".") in ALL_LABELS


def _label_at(row: list[Word], i: int, names: tuple[str, ...]) -> int:
    """How many words from ``row[i]`` make one of ``names`` (0 when none): "DWG.TITLE:" is one, "Drg. Title:" two."""
    for n in (3, 2, 1):
        if i + n <= len(row):
            text = _norm(" ".join(w["text"] for w in row[i:i + n]))
            if text in names or text.rstrip(".") in names:
                return n
    return 0


def _noise(w: Word) -> bool:
    """A stray letter from rotated or overlapping text ("s"), or a lone punctuation mark."""
    t = w["text"].strip()
    return not t or (len(t) == 1 and not t.isdigit() and not t.isupper())


def _value_after(rows: list[list[Word]], names: tuple[str, ...]) -> tuple[str, Word] | None:
    """The value of the first label in ``names``: the words right of it on its line (up to the next label or a
    wide gap), else the words in its column on the next line (within ``BELOW`` points, up to the next label's
    column). Notes such as "all dimensions are in cm" are never a value."""
    for r, row in enumerate(rows):
        for i in range(len(row)):
            n = _label_at(row, i, names)
            if not n:
                continue
            label = row[i:i + n]
            right: list[Word] = []
            for w in row[i + n:]:
                gap = w["x0"] - (right[-1]["x1"] if right else label[-1]["x1"])
                if _is_label(w["text"]) or gap > (40 if right else 90):
                    break
                if not _noise(w):
                    right.append(w)
            if right:
                return " ".join(w["text"] for w in right).strip(), label[0]
            x0 = label[0]["x0"]
            nxt = next((w["x0"] for w in row[i + n:] if _is_label(w["text"])), x0 + 220)
            for below in rows[r + 1:]:
                if below[0]["top"] - label[0]["top"] > BELOW:
                    break
                near = [w for w in below if x0 - 15 <= w["x0"] < nxt and not _is_label(w["text"]) and not _noise(w)]
                text = " ".join(w["text"] for w in near).strip()
                if near and not _UNITS.search(" ".join(w["text"] for w in below)):
                    return text, label[0]
    return None


def _titles(rows: list[list[Word]]) -> list[tuple[str, float, Word]]:
    """Every sheet-title phrase on the page with its text size."""
    out = []
    for row in rows:
        text = " ".join(w["text"] for w in row)
        for m in _TITLE.finditer(text):
            # the word where the match starts, for its size and position
            start = len(text[:m.start()].split())
            w = row[min(start, len(row) - 1)]
            out.append((re.sub(r"\s+", " ", m.group(0)).upper(), w.get("size") or 0, w))
    return out


def kind_of(title: str | None) -> str | None:
    if not title:
        return None
    t = title.upper()
    for word, kind in (("ELEVATION", "elevation"), ("SECTION", "section"), ("SCHEDULE", "schedule"),
                       ("DETAIL", "detail"), ("SITE PLAN", "site_plan"), ("KEY PLAN", "site_plan"),
                       ("LOCATION PLAN", "site_plan"), ("PLAN", "plan"), ("LAYOUT", "plan")):
        if word in t:
            return kind
    return None


def level_of(title: str | None) -> str | None:
    """The floor a plan shows ("Ground floor", "Basement"), from its title."""
    if not title or kind_of(title) != "plan":
        return None
    t = title.upper()
    for word in sorted(_LEVEL_WORDS, key=len, reverse=True):
        if re.search(rf"\b{word}\b", t):
            name = {"1ST": "First", "2ND": "Second", "3RD": "Third", "4TH": "Fourth", "5TH": "Fifth"}.get(
                word, word.title())
            plain = word in ("ROOF", "TERRACE", "FOUNDATION", "FOOTING", "PLINTH", "BASEMENT", "CELLAR", "STILT")
            return name if plain else f"{name} floor"
    return None


def discipline_of(title: str | None, text: str) -> str:
    t = f"{title or ''} {text}".upper()
    if re.search(r"\b(STRUCTURAL|REINFORCEMENT|FOOTING SCHEDULE|COLUMN SCHEDULE|BAR BENDING)\b", t):
        return "structural"
    if re.search(r"\b(ELECTRICAL|PLUMBING|DRAINAGE|HVAC|FIRE FIGHTING|SANITARY LAYOUT)\b", t):
        return "mep"
    return "architectural"


def sheet(page: Mapping[str, Any]) -> dict[str, Any]:
    """What one page is: title, kind, level, discipline and the title-block fields; ``has_text`` False for a
    scanned page (nothing can be read from it)."""
    words = page["words"]
    rows = lines(words)
    text = " ".join(" ".join(w["text"] for w in row) for row in rows)
    found = {k: _value_after(rows, names) for k, names in LABELS.items()}
    titles = _titles(rows)
    title = None
    labelled = found.get("title")
    if labelled:
        m = _TITLE.search(labelled[0].upper())
        title = re.sub(r"\s+", " ", m.group(0)).upper() if m else None
    if title is None and titles:
        # Near the title label when there is one; else the biggest title text on the sheet.
        if labelled:
            lw = labelled[1]
            titles.sort(key=lambda t: abs(t[2]["top"] - lw["top"]) + abs(t[2]["x0"] - lw["x0"]))
        else:
            titles.sort(key=lambda t: -t[1])
        title = titles[0][0]
    scale = _SCALE.search(text)
    date = _DATE.search(text)
    units = _UNITS.search(text)
    # The practice's name as printed in capitals: "KALEIDO ARCHITECTS" (never a note such as "consult the architect").
    architect = None
    for row in rows:
        m = re.search(r"\b((?:[A-Z][A-Z&.]+\s+){1,3}ARCHITECTS?)\b", " ".join(w["text"] for w in row))
        if m:
            architect = m.group(1).strip().title()
            break

    def val(key: str) -> str | None:
        v = found.get(key)
        return v[0] if v else None

    units_word = units.group(1).upper() if units else None
    return {
        "page": page["number"],
        "has_text": bool(words),
        "title": title,
        "kind": kind_of(title),
        "level": level_of(title),
        "discipline": discipline_of(title, text) if words else None,
        "project": val("project"),
        "client": val("client"),
        "architect": architect,
        "number": val("number"),
        "revision": val("revision"),
        "drawn_by": val("drawn"),
        "checked_by": val("checked"),
        "scale": f"1:{scale.group(1)}" if scale else None,
        "date": f"{int(date.group(1)):02d}.{int(date.group(2)):02d}.{date.group(3)}" if date else None,
        "units": {"CM": "cm", "CENTIMETER": "cm", "CENTIMETERS": "cm", "MM": "mm", "MILLIMETER": "mm",
                  "MILLIMETERS": "mm", "M": "m", "METER": "m", "METERS": "m"}.get(units_word or "", None),
    }
