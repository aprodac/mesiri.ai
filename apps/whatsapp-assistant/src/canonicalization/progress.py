"""A stated percentage is progress, never "finished" (request 57, B4).

"Plastering 2nd floor 40% aayi" means 40% done. A model that read "aayi"
("has happened") as "done" saved the update as completed and wrote the note
as "plastering finished on 2nd floor", and the percentage was nowhere. This is
the deterministic safety net behind the extraction prompt, shared by the
classic path (canonicalization/builder.py) and the agent's save_work_done tool:

- the percentage is read from the extracted ``progress_percent`` or, failing
  that, from the sender's own words;
- below 100% the update is never "completed";
- the saved note is rebuilt from the saved data ("Plastering, 2nd floor: 40%")
  so what the activity says is what was reported, whatever language the model
  wrote its note in.

Pure; no I/O.
"""

from __future__ import annotations

import re
from typing import Any

_PERCENT = re.compile(
    r"(?<![\d.])(\d{1,3}(?:\.\d+)?)\s*(?:%|percent|per cent|pct|shatam\w*|satam\w*|ശതമാനം|प्रतिशत|फ़ीसदी|फीसदी|சதவீதம்)",
    re.IGNORECASE,
)


def _coerce(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        pct = float(str(value).strip().rstrip("%"))
    except ValueError:
        return None
    return pct if 0 <= pct <= 100 else None


def find_percent(*texts: str | None) -> float | None:
    """The first percentage in ``texts``, or None."""
    for text in texts:
        for match in _PERCENT.finditer(text or ""):
            pct = _coerce(match.group(1))
            if pct is not None:
                return pct
    return None


def percent_text(pct: float) -> str:
    return f"{int(pct)}%" if float(pct).is_integer() else f"{pct:g}%"


def progress_note(work_type: Any, location: Any, pct: float) -> str:
    work = str(work_type or "").replace("_", " ").strip()
    place = str(location or "").strip()
    head = ", ".join(p for p in (work[:1].upper() + work[1:] if work else "", place) if p)
    return f"{head}: {percent_text(pct)}" if head else f"Work progress: {percent_text(pct)}"


def apply_progress(fields: dict[str, Any], source_text: str | None = None) -> dict[str, Any]:
    """``fields`` of a site update with the percentage settled. Unchanged when
    no percentage was stated."""
    pct = _coerce(fields.get("progress_percent"))
    if pct is None:
        pct = find_percent(source_text, str(fields.get("narrative") or ""))
    if pct is None:
        return fields
    out = dict(fields)
    out["progress_percent"] = int(pct) if float(pct).is_integer() else pct
    if pct < 100 and str(out.get("update_kind") or "").strip().lower() == "completed":
        out["update_kind"] = "progress"
    narrative = str(out.get("narrative") or "").strip()
    if pct < 100 and out.get("work_type"):
        out["narrative"] = progress_note(out.get("work_type"), out.get("location"), pct)
    elif percent_text(pct) not in narrative:
        out["narrative"] = f"{narrative} ({percent_text(pct)})".strip()
    return out


_ORDINAL_WORDS = {"ground": "ground", "first": "1st", "second": "2nd", "third": "3rd", "fourth": "4th", "fifth": "5th"}
_FLOOR = re.compile(
    r"\b(?P<n>ground|first|second|third|fourth|fifth|\d{1,2}(?:st|nd|rd|th)?)[\s-]*(?:floor|flr)\b"
    r"|\b(?P<place>basement|terrace|roof|stilt)\b",
    re.IGNORECASE,
)
_COMPLETED = re.compile(
    r"\b(?:finish(?:ed)?|complet(?:e|ed)|theernnu|theernu|theernath|kazhinju|kazhinhu|poorthiyayi|"
    r"poorthi\s*aayi|ho\s*gaya|khatam|pura\s*ho\s*gaya)\b|തീർന്നു|കഴിഞ്ഞു|പൂർത്തിയായി|खत्म|पूरा",
    re.IGNORECASE,
)


def _suffix(n: int) -> str:
    return "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


def _floor_name(match: re.Match[str]) -> str:
    if match.group("place"):
        return match.group("place").lower()
    raw = match.group("n").lower()
    if raw in _ORDINAL_WORDS:
        raw = _ORDINAL_WORDS[raw]
    if raw == "ground":
        return "ground floor"
    digits = re.match(r"\d+", raw)
    number = int(digits.group(0)) if digits else 0
    return f"{number}{_suffix(number)} floor"


def find_place(text: str) -> str | None:
    """The floor or place named in ``text`` ("ground floor", "2nd floor", "terrace")."""
    match = _FLOOR.search(text or "")
    return _floor_name(match) if match else None


def settle_place_and_status(fields: dict[str, Any]) -> dict[str, Any]:
    """The floor and the finished/in-progress status of a work-done entry, kept
    whatever the model left out (request 83: "3rd floor slab concreting
    finished" was saved as bare "Slab concreting").

    - A floor said inside the work name or the sender's words and not in
      ``location`` moves to ``location`` ("3rd floor slab concreting" ->
      location "3rd floor", work "slab concreting").
    - ``update_kind`` is "completed" when the words say it is finished, or
      the percentage is 100; "progress" when a percentage below 100 is given.
      A kind the model already set stays, except that a percentage below 100
      is never "completed" (``apply_progress``).
    - A finished entry's narrative says so, as a percentage entry's does.

    Pure; no I/O. Call after ``apply_progress`` (it has settled the percentage).
    """
    out = dict(fields)
    work = str(out.get("work_type") or "").strip()
    narrative = str(out.get("narrative") or "").strip()
    if not str(out.get("location") or "").strip():
        for source in (work, narrative):
            match = _FLOOR.search(source)
            if match:
                out["location"] = _floor_name(match)
                break
    place = str(out.get("location") or "").strip()
    if work and place:
        cleaned = " ".join(_FLOOR.sub(" ", work).split())
        if cleaned and cleaned != work:
            out["work_type"] = cleaned
            work = cleaned

    pct = _coerce(out.get("progress_percent"))
    kind = str(out.get("update_kind") or "").strip().lower()
    if pct is not None and pct >= 100:
        kind = "completed"
    elif pct is not None:
        kind = "progress"
    elif not kind and _COMPLETED.search(f"{narrative} {work}"):
        kind = "completed"
    if kind:
        out["update_kind"] = kind
    if kind == "completed" and pct is None and work:
        head = ", ".join(p for p in (work[:1].upper() + work[1:], place) if p)
        out["narrative"] = f"{head} (completed)"
    return out
