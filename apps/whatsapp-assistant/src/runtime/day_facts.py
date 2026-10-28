"""Day Facts (request 137): what is saved for one site on one day, and the one
rule every part of the assistant uses to ask about it.

Before this, each part read saved work its own way: the correction lookup wanted a
quantity, the card matched lines by position, and the readers counted a progress
update only through its parent activity. A percentage ("tiling 80%") has no
quantity, so a correction found nothing, and a continuation hung off a parent
the readers hid. This module is the shared definition. It adds no table: facts
come from the saved card (each item carries its fact id) and the day readers
(``runtime/agent/project_day``); the database rule is ``fact_review``'s.

- ``counted``: a fact is saved when its latest review is not a draft. One
  definition, delegated to ``fact_review.counts`` so the readers and this module
  cannot drift apart.
- ``WorkFact``: a saved work item with its fact id, site, work key (the work and
  the place) and its value (a percent or a quantity).
- ``resolve_percent``: a newer percent for the same work is a NEW line; only an
  explicit correction ("alla, 75%") edits the saved one, found by fact id.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from mesiri.application.dpr import fact_review

PERCENT = "percent"
QUANTITY = "quantity"

#: What the resolver decides for one percent the sender sent.
NEW_LINE = "new_line"
CHANGE = "change"
NOTHING = "nothing"


def counted(state: str | None) -> bool:
    """Whether a fact in this review state is part of the record. Saved facts
    (confirmed, or never reviewed) count; a draft does not until it is saved."""
    return fact_review.counts(state)


#: SQL for "this activity can be continued": its latest review is neither a draft
#: (not saved yet) nor rejected (cancelled). ``column`` is the activity id column,
#: from code, never input.
def open_work_sql(column: str) -> str:
    return (
        "COALESCE((SELECT fr_o.state FROM fact_reviews fr_o "
        f"WHERE fr_o.fact_type = '{fact_review.ACTIVITY}' AND fr_o.fact_id = {column} "
        f"ORDER BY fr_o.created_at DESC LIMIT 1), '{fact_review.CONFIRMED}') = '{fact_review.CONFIRMED}'"
    )


def _said(value: Any) -> str:
    return " ".join(str(value or "").split()).casefold()


def work_key(work_type: Any, location: Any) -> str:
    """The work and the place, as one comparable key ("tiling|ground floor")."""
    return f"{_said(work_type)}|{_said(location)}"


@dataclass(frozen=True, slots=True)
class WorkFact:
    """One saved work item of a day."""

    fact_id: str
    fact_type: str
    site_id: str | None
    key: str
    field: str
    value: float | None
    saved: bool = True
    work_type: str = ""
    location: str = ""


def work_fact_of(item: Any, site_id: str | None = None) -> WorkFact | None:
    """A saved card item as a work fact; None for anything but a work item."""
    args = getattr(item, "args", None) or {}
    if getattr(item, "tool", "") != "save_work_done" or not _said(args.get("work_type")):
        return None
    percent = args.get("progress_percent")
    quantities = args.get("quantities") or []
    if percent is not None:
        field, value = PERCENT, _number(percent)
    elif quantities and isinstance(quantities[0], dict):
        field, value = QUANTITY, _number(quantities[0].get("quantity"))
    else:
        field, value = QUANTITY, None
    return WorkFact(
        fact_id=str(getattr(item, "fact_id", "") or ""),
        fact_type=str(getattr(item, "fact_type", "") or ""),
        site_id=str(site_id) if site_id else (str(args.get("site")) if args.get("site") else None),
        key=work_key(args.get("work_type"), args.get("location")),
        field=field,
        value=value,
        work_type=str(args.get("work_type") or ""),
        location=str(args.get("location") or ""),
    )


def work_facts(items: Any, site_id: str | None = None) -> list[WorkFact]:
    return [f for f in (work_fact_of(i, site_id) for i in items or []) if f is not None and f.fact_id]


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


_PERCENT_UNITS = frozenset({"%", "percent", "percentage", "pct", "per cent"})
_PERCENT_WORDS = r"(?:%|percent|percentage|per\s*cent|shatham|ശതമാനം|प्रतिशत)"

#: Words that say the last figure was wrong, not that the work moved on.
_CORRECTION_CUE = re.compile(
    r"\b(alla|allaa|illa|thettu|thettiyath|thett|galat|nahi|nahin|wrong|mistake|correction|correct\s+it|"
    r"not\s+\d|no\s*,|sorry|actually|instead|change\s+(?:it|that|to)|make\s+(?:it|that))\b|അല്ല|തെറ്റ്|गलत",
    re.IGNORECASE,
)


def is_correction(text: str) -> bool:
    return bool(_CORRECTION_CUE.search(text or ""))


def is_percent(value: Any, unit: Any, text: str) -> bool:
    """Whether a figure the sender gave is a percentage: said with a percent unit,
    or written next to a percent sign in their words."""
    if _said(unit) in _PERCENT_UNITS:
        return True
    number = _number(value)
    if number is None:
        return False
    shown = f"{number:g}"
    return bool(re.search(rf"(?<![\d.]){re.escape(shown)}\s*{_PERCENT_WORDS}", text or "", re.IGNORECASE))


@dataclass(frozen=True, slots=True)
class Resolution:
    action: str
    fact: WorkFact | None = None
    reason: str = ""


def resolve_percent(facts: list[WorkFact], value: Any, text: str, *, site_id: str | None = None) -> Resolution:
    """What a percent the sender sent means against what is saved.

    A correction ("alla, 75%") edits the saved percent line: the newest saved
    percent line of the day (only one line when several works are saved is not a
    guess: with several the sender must name the work, so nothing is edited).
    Any other percent ("tiling 80% aayi") is progress: a new line, never a
    correction of the earlier percent."""
    percents = [f for f in facts if f.field == PERCENT and (site_id is None or f.site_id in (None, site_id))]
    if _number(value) is None:
        return Resolution(NOTHING, reason="no figure")
    if not percents or not is_correction(text):
        return Resolution(NEW_LINE)
    keys = {f.key for f in percents}
    if len(keys) > 1:
        return Resolution(NOTHING, reason="more than one work is saved; the work must be named")
    return Resolution(CHANGE, percents[-1])
