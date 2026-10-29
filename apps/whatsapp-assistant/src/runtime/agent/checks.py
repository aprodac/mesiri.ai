"""The check layer (request 143, phase 3, D): an odd figure is asked about before it
is saved, never saved silently.

Repros (live, 29 Oct): "Site B 500 mason vannu" made a card and saved with no
question; "Green Villa ground floor tiling 40% aayi" after 88% was saved had no
"it went down, sure?".

``doubt`` is pure: the new line's kind, its tool arguments and prepared fields, and
the site's history from Day Facts (``SiteHistory``) in; the doubt (what is odd, with
its figures) or None out. ``draft_flow.add`` runs it on every line that is ready;
a doubt makes the line wait on a question with [Yes, it's right] [Change]. The
rules are few and plain, so a sender is never asked about a normal day:

- labour: the day's workers far above what the site usually has (more than three
  times its usual day and 30 more), or above 150 at a site with no history yet;
- work: a percent above 100, or below the newest saved percent of the same work
  and place ("went down from 88%");
- material used: more than the site holds in stock (when its stock is known).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import draft as dr

#: The two answers of a check question (button titles; a tap is read by its number).
RIGHT = "Yes, it's right"
CHANGE = "Change"
OPTIONS = [RIGHT, CHANGE]

#: Above this many workers, a site with no history yet is asked.
NEW_SITE_WORKERS = 150


@dataclass(frozen=True, slots=True)
class Doubt:
    """What is odd about a line: a ``wording`` key and the figures it names."""

    key: str
    values: dict[str, Any] = field(default_factory=dict)


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _shown(value: float) -> str:
    return f"{value:g}"


def _workers(fields: dict[str, Any]) -> int:
    total = 0
    for line in fields.get("lines") or []:
        if isinstance(line, dict):
            count = _number(line.get("headcount"))
            total += int(count) if count and count > 0 else 1
    return total


def doubt(kind: str, args: dict[str, Any], fields: dict[str, Any], history: Any) -> Doubt | None:
    """What is odd about a new line, or None (the normal case)."""
    if kind == dr.KIND_LABOUR:
        workers = _workers(fields)
        usual = getattr(history, "usual_workers", None)
        if usual:
            if workers > max(3 * usual, usual + 30):
                return Doubt("check.labour_many", {"workers": workers, "usual": usual})
        elif workers > NEW_SITE_WORKERS:
            return Doubt("check.labour_new", {"workers": workers})
        return None
    if kind == dr.KIND_WORK:
        percent = _number(args.get("progress_percent"))
        if percent is None:
            return None
        if percent > 100:
            return Doubt("check.percent_over", {"percent": _shown(percent)})
        from runtime import day_facts as df

        key = df.work_key(args.get("work_type"), df.place_of(args.get("location")) or args.get("location"))
        before = (getattr(history, "percents", None) or {}).get(key)
        if before is not None and percent < before[0]:
            return Doubt(
                "check.percent_down",
                {"percent": _shown(percent), "before": _shown(before[0]), "work": str(args.get("work_type") or "")},
            )
        return None
    if kind == dr.KIND_MATERIAL_OUT:
        used, stock = _number(fields.get("quantity")), _number(fields.get("available_stock"))
        if used is not None and stock is not None and stock > 0 and used > stock:
            return Doubt(
                "check.more_than_stock",
                {"used": _shown(used), "stock": _shown(stock), "unit": str(fields.get("unit") or args.get("unit") or "")},
            )
    return None


def asking(item: Any) -> bool:
    """The line waits on a check question (its answers are ``OPTIONS``)."""
    return getattr(item, "state", "") == dr.NEEDS_ANSWER and list(getattr(item, "options", None) or []) == OPTIONS


def with_figure(item: Any, figure: float) -> dict[str, Any] | None:
    """The line's tool arguments with the one figure the check asked about set to
    ``figure`` (a typed "50" for "500 workers?"); None when the line has more than
    one figure to set."""
    args = dict(item.args)
    plain: Any = int(figure) if float(figure).is_integer() else figure
    if item.kind == dr.KIND_LABOUR:
        workers = [dict(w) for w in args.get("workers") or [] if isinstance(w, dict)]
        if len(workers) != 1:
            return None
        workers[0]["headcount"] = plain
        return {**args, "workers": workers}
    if item.kind == dr.KIND_WORK and args.get("progress_percent") is not None:
        return {**args, "progress_percent": plain}
    if item.kind == dr.KIND_MATERIAL_OUT:
        return {**args, "quantity": plain}
    return None


#: A typed "yes, it's right" to a check question.
_RIGHT_WORDS = frozenset(
    "yes y yeah yep ok okay correct right sheri shari sari athe aanu ha haan haa sahi theek ശരി അതെ हाँ सही".split()
)


def says_right(text: str) -> bool:
    words = [w.strip(".,!?") for w in (text or "").lower().split()]
    return bool(words) and all(w in _RIGHT_WORDS or w in ("it's", "its", "it", "is") for w in words)
