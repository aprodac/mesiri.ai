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
from channel.replies import ListRow

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
    # Words of 3+ letters, and the day number of a date ("24 Oct" picks one of
    # two issues that read the same).
    return {w for w in re.findall(r"[^\W\d_]{3,}|\d{1,2}", (text or "").casefold()) if w not in _STOP}


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


TAP_PREFIX = "agc:"
#: The tap of a row: the issues it closes, by the first characters of their ids.
GROUP = "grp"
ELSE = "else"
ELSE_TEXT = "Tell me which issue it is, in a few words, or say 'all' to close every one listed."


def ref_of(issue: dict[str, Any]) -> str:
    return str(issue["id"]).replace("-", "")[:8]


def group_same(issues: list[dict[str, Any]], zone: str) -> list[list[dict[str, Any]]]:
    """The same report made twice (the same words on the same day) is one choice:
    closing it closes both, so a list never shows two rows that read alike."""
    groups: dict[tuple[str, dt.date], list[dict[str, Any]]] = {}
    for issue in issues:
        groups.setdefault((issue_label(issue).casefold(), _day(issue, zone)), []).append(issue)
    return list(groups.values())


def tap_id(refs: list[str]) -> str:
    return f"{TAP_PREFIX}{GROUP}:{','.join(refs)}"


def parse_tap(value: str) -> list[str] | None:
    """The issue refs a tap names; [] for "something else"; None when it is no issue tap."""
    if not value.startswith(TAP_PREFIX):
        return None
    kind, _, rest = value[len(TAP_PREFIX) :].partition(":")
    if kind == ELSE:
        return []
    if kind != GROUP:
        return None
    refs = [r for r in rest.split(",") if re.fullmatch(r"[0-9a-f]{8}", r)]
    return refs or None


def pick_rows(issues: list[dict[str, Any]], zone: str) -> tuple[ListRow, ...]:
    """The list of open issues to choose from, one row per distinct report. The title
    is the issue in a few words (cut between words), the description the whole line
    with its day; a row that closes several says how many. Each row's id names its issues."""
    from .site_match import short_title

    groups = group_same(issues, zone)[:MAX_LISTED]
    titles = [short_title(issue_label(g[0]), 24) for g in groups]
    rows = []
    for n, group in enumerate(groups):
        title = titles[n]
        if titles.count(title) > 1:
            title = f"{short_title(issue_label(group[0]), 15)} · {short_day(_day(group[0], zone))}"
        line = issue_line(group[0], zone)
        rows.append(
            ListRow(
                tap_id([ref_of(i) for i in group]),
                title,
                f"{line} · {len(group)} same reports" if len(group) > 1 else line,
            )
        )
    shown = [i for g in groups for i in g]
    if 1 < len(groups) and len(shown) <= MAX_CLOSE:
        rows.append(ListRow(tap_id([ref_of(i) for i in shown]), f"All {len(shown)} of these", ""))
    rows.append(ListRow(f"{TAP_PREFIX}{ELSE}", SOMETHING_ELSE, ""))
    return tuple(rows[:10])


def closing_action(
    issues: list[dict[str, Any]], fields: dict[str, Any], scoped: Any, choose: Any
) -> list[PendingAction] | Say:
    zone = str(company_zone(scoped.ctx.timezone))
    if not issues:
        return Say("info", "There are no open issues to close.")
    wants_all = bool(fields.get("all_issues"))
    picked: list[dict[str, Any]] | None = None
    offered = issues
    refs = {r for r in _phrases(fields.get("issue_refs"))}
    if refs:
        # A tap on a row: the issues it names, exactly (request 142).
        picked = [i for i in issues if ref_of(i) in refs] or None
    elif wants_all and len(issues) <= MAX_CLOSE:
        picked = issues
    elif _phrases(fields.get("about")):
        matched = best_matches(issues, _phrases(fields.get("about")), zone)
        if len(matched) == 1 or (fields.get("all_matching") and matched and len(matched) <= MAX_CLOSE):
            picked = matched
        elif matched:
            offered = matched
    if picked is None:
        shown = offered[:MAX_LISTED]
        say = choose("Which issue is fixed?", [*row_titles(shown, zone), SOMETHING_ELSE], "issue")
        if fields.get("pick_ids"):
            say.rows = pick_rows(offered, zone)
        return say
    out = []
    for group in group_same(picked, zone):
        issue = group[0]
        payload = {
            "organization_id": scoped.organization_id,
            "project_id": str(scoped.project_id) if scoped.project_id else None,
            "site_id": str(issue.get("site_id") or scoped.site_id or "") or None,
            "issues": [
                {"id": str(i["id"]), "title": issue_line(i, zone), "site_id": str(i.get("site_id") or "") or None}
                for i in group
            ],
        }
        many = f" ×{len(group)}" if len(group) > 1 else ""
        out.append(new_action(CLOSE_ISSUES, payload, f"To close: {issue_line(issue, zone)}{many}"))
    return out
