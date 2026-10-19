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
