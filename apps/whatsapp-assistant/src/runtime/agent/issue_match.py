"""Request 104, C: which open issue does "Crane is repaired" mean?

The old close-out took *the latest reported* open issue, so "Crane is repaired"
offered to close "Cement running low". Here the issue is found by the words the
sender used; when more than one could be meant, or no words point to one, the
open issues are listed as buttons (newest first), never guessed.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

from channel.receipt.data import company_zone

from .actions import CLOSE_ISSUES, PendingAction, new_action
from .entry_base import Say

#: A list holds 10 rows: nine issues and "Something else".
MAX_LISTED = 9
SOMETHING_ELSE = "Something else"
#: "Both are fixed" / "all of them" closes up to this many in one card (a card holds 7).
MAX_CLOSE = 7

_STOP = frozenset(
    "the a an is are was were has have had been it its this that these those and or of to in on at "
    "for with from now not no yes fixed fix repaired repair done sorted resolved resolve closed close "
    "working work issue problem both all them one two please pani aayi theernnu sheri".split()
)
_TYPE_WORDS = {
    "WEATHER": "weather rain",
    "MATERIAL_SHORTAGE": "material shortage",
    "LABOUR_SHORTAGE": "labour shortage workers",
    "DRAWING_PENDING": "drawing pending",
    "EQUIPMENT_BREAKDOWN": "equipment breakdown machine",
    "INSPECTION_WAITING": "inspection waiting",
    "ACCESS": "access",
    "SAFETY": "safety accident injury",
    "QUALITY": "quality leak seepage crack",
    "OTHER": "",
}


def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[^\W_]{3,}", (text or "").casefold()) if w not in _STOP}


def _day(issue: dict[str, Any], zone: str) -> dt.date:
    when = issue.get("occurred_at")
    if isinstance(when, dt.datetime):
        from zoneinfo import ZoneInfo

        return (when.astimezone(ZoneInfo(zone)) if when.tzinfo else when).date()
    return dt.date.today()


def short_day(day: dt.date) -> str:
    return f"{day.day} {day.strftime('%b')}"


def issue_label(issue: dict[str, Any]) -> str:
    """The issue in a few words: the first clause of its note, else its type."""
    narrative = " ".join(str(issue.get("narrative") or "").split())
    clause = re.split(r"[.;,\n]| - ", narrative, maxsplit=1)[0].strip()
    label = clause or str(issue.get("issue_type") or "Issue").replace("_", " ").capitalize()
    return label[:1].upper() + label[1:][:44]


def issue_line(issue: dict[str, Any], zone: str) -> str:
    """"Crane breakdown (since 23 Oct)" -- "(today)" when it began today."""
    day = _day(issue, zone)
    today = dt.datetime.now(dt.UTC).astimezone(__import__("zoneinfo").ZoneInfo(zone)).date()
    return f"{issue_label(issue)} ({'today' if day == today else 'since ' + short_day(day)})"


def row_titles(issues: list[dict[str, Any]], zone: str) -> list[str]:
    """The list rows (24 characters each): the issue in a few words; when two
    read the same, the day is added so they can be told apart."""
    labels = [issue_label(i) for i in issues]
    cut = [label[:24] for label in labels]
    return [
        f"{label[:15].rstrip()} · {short_day(_day(issue, zone))}" if cut.count(cut[n]) > 1 else cut[n]
        for n, (label, issue) in enumerate(zip(labels, issues, strict=True))
    ]


def _match_text(issue: dict[str, Any], zone: str) -> tuple[set[str], set[str]]:
    """(the words of the issue's own note, the words of its type and day): a
    word in the note counts double."""
    day = _day(issue, zone)
    note = _tokens(str(issue.get("narrative") or ""))
    extra = _tokens(f"{_TYPE_WORDS.get(str(issue.get('issue_type')), '')} {short_day(day)}")
    return note, extra


def best_matches(issues: list[dict[str, Any]], about: list[str], zone: str) -> list[dict[str, Any]]:
    """The issues whose words fit what the sender said best; every one that
    ties for the best fit, none when no word fits."""
    wanted: set[str] = set()
    for phrase in about:
        wanted |= _tokens(phrase)
    if not wanted:
        return []
    scored = []
    for issue in issues:
        note, extra = _match_text(issue, zone)
        scored.append((2 * len(wanted & note) + len(wanted & (extra - note)), issue))
    top = max((score for score, _ in scored), default=0)
    return [issue for score, issue in scored if score == top] if top else []


def _phrases(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    return [str(v) for v in value or [] if str(v).strip()] if isinstance(value, list) else []


def closing_action(
    issues: list[dict[str, Any]], fields: dict[str, Any], scoped: Any, choose: Any
) -> list[PendingAction] | Say:
    zone = str(company_zone(scoped.ctx.timezone))
    if not issues:
        return Say("info", "There are no open issues to close.")
    wants_all = bool(fields.get("all_issues"))
    picked: list[dict[str, Any]] | None = None
    offered = issues
    if wants_all and len(issues) <= MAX_CLOSE:
        picked = issues
    elif _phrases(fields.get("about")):
        matched = best_matches(issues, _phrases(fields.get("about")), zone)
        if len(matched) == 1:
            picked = matched
        elif matched:
            offered = matched
    if picked is None:
        shown = offered[:MAX_LISTED]
        labels = row_titles(shown, zone)
        return choose(
            "Which issue is fixed?",
            [*labels, SOMETHING_ELSE],
            "issue",
            note=" Pass what they tapped as `about`.",
        )
    out = []
    for issue in picked:
        payload = {
            "organization_id": scoped.organization_id,
            "project_id": str(scoped.project_id) if scoped.project_id else None,
            "site_id": str(issue.get("site_id") or scoped.site_id or "") or None,
            "issues": [{"id": str(issue["id"]), "title": issue_line(issue, zone), "site_id": str(issue.get("site_id") or "") or None}],
        }
        out.append(new_action(CLOSE_ISSUES, payload, f"To close: {issue_line(issue, zone)}"))
    return out
