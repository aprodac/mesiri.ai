"""What works, version 2 (SA-39): the summary the page shows, from the intents ``admin/intents.py`` builds.

Modules -> capabilities with their endings, journeys, how people sent them, real phrasings, top failure reasons
and the funnel; "Fix these first", the largest problems across every module. Pure functions, no I/O.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from admin.intents import (
    ABANDONED,
    COMPLAINED,
    ENDINGS,
    FAILED,
    GOOD_ENDINGS,
    OPEN,
    UNSURE,
    UNSURE_REASONS,
    capability_name,
    plain_reason,
)
from admin.message_map import _label

#: At most this many intents listed under one capability or problem (failures first).
MAX_INTENT_EXAMPLES = 25
#: How many problems "Fix these first" lists.
FIX_FIRST = 5


def _bar(rows: list[dict[str, Any]]) -> dict[str, int]:
    endings = Counter(r["ending"] for r in rows)
    return {key: endings.get(key, 0) for key in ENDINGS}


def _funnel(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """intents -> a tool was called -> ready on the card or answered -> finished, and the widest drop."""
    steps = [
        ("asked", "Asked", len(rows)),
        ("called", "A tool was called", sum(1 for r in rows if r["called_tool"])),
        ("prepared", "Ready on the card or answered",
         sum(1 for r in rows if r["reached_card"] or r["ending"] in GOOD_ENDINGS)),
        ("finished", "Saved, sent or answered", sum(1 for r in rows if r["ending"] in GOOD_ENDINGS)),
    ]
    drops = [(steps[i][2] - steps[i + 1][2], steps[i + 1][1]) for i in range(len(steps) - 1)]
    widest = max(drops, key=lambda d: d[0], default=(0, ""))  # the first one on a tie
    return {"steps": [{"key": k, "label": label, "count": n} for k, label, n in steps],
            "widest_drop": {"at": widest[1], "lost": widest[0]} if widest[0] > 0 else None}


def summarise(intents: list[dict[str, Any]], messages_by_id: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Modules -> capabilities, each with its ending bar, journeys, how it was sent, top failure reasons,
    a few real phrasings and the funnel. Intents still going are left out of every count."""
    done = [r for r in intents if r["ending"] != OPEN]
    messages_by_id = messages_by_id or {}
    by_section: dict[str, list[dict[str, Any]]] = {}
    for r in done:
        by_section.setdefault(r["section"], []).append(r)

    sections = []
    for section, rows in by_section.items():
        by_capability: dict[str, list[dict[str, Any]]] = {}
        for r in rows:
            by_capability.setdefault(r["capability"], []).append(r)
        capabilities = []
        for tool, crows in sorted(by_capability.items(), key=lambda kv: -len(kv[1])):
            reasons = Counter(r["reason"] for r in crows if r["ending"] not in GOOD_ENDINGS and r["reason"])
            phrasings: list[str] = []
            for r in sorted(crows, key=lambda r: r["started_at"], reverse=True):
                text = (messages_by_id.get(r["messages"][0]) or {}).get("body_text") or ""
                text = " ".join(str(text).split())[:160]
                if text and text not in phrasings:
                    phrasings.append(text)
                if len(phrasings) == 3:
                    break
            capabilities.append({
                "key": tool, "name": capability_name(tool), "tool": None if tool.startswith("_") else tool,
                "count": len(crows), "finished": sum(1 for r in crows if r["ending"] in GOOD_ENDINGS),
                "endings": _bar(crows), "how": dict(Counter(r["how"] for r in crows).most_common()),
                "journeys": dict(Counter(j for r in crows for j in r["journeys"]).most_common()),
                "top_reasons": [{"reason": why, "count": n} for why, n in reasons.most_common(2)],
                "phrasings": phrasings, "funnel": _funnel(crows),
                "intents": [r["id"] for r in sorted(crows, key=lambda r: (r["ending"] in GOOD_ENDINGS,
                                                                           -r["started_at"].timestamp()))][:MAX_INTENT_EXAMPLES],
            })
        sections.append({"key": section, "label": _label(section), "count": len(rows),
                         "finished": sum(1 for r in rows if r["ending"] in GOOD_ENDINGS),
                         "endings": _bar(rows), "capabilities": capabilities})
    sections.sort(key=lambda s: -s["count"])
    return {"totals": {"intents": len(done), "still_going": len(intents) - len(done), **_bar(done)},
            "funnel": _funnel(done), "fix_first": fix_first(done), "sections": sections}


#: Endings that are a problem to fix, and how a line about them starts.
_PROBLEM = {FAILED: "failed: ", COMPLAINED: "", ABANDONED: "", UNSURE: ""}
#: "Not sure" reasons that are not a problem: nothing to fix there.
_NOT_A_PROBLEM = frozenset({UNSURE_REASONS["no_record"], UNSURE_REASONS["greeting"], UNSURE_REASONS["idea"]})

def is_problem(intent: dict[str, Any]) -> bool:
    """An ending worth fixing: failed, a complaint or 'not yet', left without Save, or a reply with nothing done
    (not a sign-up, a greeting or an idea)."""
    return intent["ending"] in _PROBLEM and not (intent["ending"] == UNSURE and intent["reason"] in _NOT_A_PROBLEM)


def problem_groups(intents: list[dict[str, Any]], *, top_capabilities: int = 3) -> list[dict[str, Any]]:
    """Every problem of the window, largest first: the same ending and reason is one problem wherever it happened,
    with the capabilities it hit and its intents (newest first) to open."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for r in intents:
        if is_problem(r):
            groups.setdefault((r["ending"], r["reason"]), []).append(r)
    out = []
    for (ending, reason), rows in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        caps = Counter(r["capability"] for r in rows)
        words = plain_reason(reason)
        newest = sorted(rows, key=lambda r: r["started_at"], reverse=True)
        out.append({
            "key": f"{ending}|{reason}", "ending": ending, "reason": reason, "count": len(rows),
            "line": f"{len(rows)} {'request' if len(rows) == 1 else 'requests'}"
                    + (f" {_PROBLEM[ending]}{words}" if ending == FAILED else f": {words}"),
            "capabilities": [{"key": k, "name": capability_name(k), "count": n}
                             for k, n in caps.most_common(top_capabilities)],
            "intents": [r["id"] for r in newest][:MAX_INTENT_EXAMPLES],
            "_rows": newest,
        })
    return out


def fix_first(intents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The largest problems of the window across every module (the first ``FIX_FIRST`` of ``problem_groups``)."""
    return [{k: v for k, v in g.items() if k != "_rows"} for g in problem_groups(intents)[:FIX_FIRST]]


def previous_window(since: datetime, until: datetime) -> tuple[datetime, datetime]:
    """The window of the same length just before ``since`` (for "change against the previous window")."""
    length: timedelta = until - since
    return since - length, since
