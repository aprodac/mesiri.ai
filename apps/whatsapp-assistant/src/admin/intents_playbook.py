"""What works, version 2 (SA-39 phase 3): the Playbook -- how each capability should work, shown by a real conversation.

For every capability, every journey it was really used in (one thing then Save, several things in one message,
Mesiri asks and the person answers, changed before saving, ...) gets its **best case**: the cleanest real
request of the window, picked by a score, never written by hand (decision D2, 15 Nov 2026). It shows the real
reply wording and card text, costs nothing to keep current and cannot drift from the product. A journey with no
clean request says so ("no clean run of this in the window"), which is itself a finding.

Beside each one: how many real requests of that journey end the same way.

Pure functions over the intents ``admin/intents.py`` builds; no I/O.
"""

from __future__ import annotations

from typing import Any

from admin.intents import (
    ASKED_ANSWERED,
    CANCELLED,
    CANCELLED_JOURNEY,
    CORRECTED_AFTER_SAVE,
    FEEDBACK,
    GOOD_ENDINGS,
    JOURNEYS,
    MEMORY,
    OPEN,
    capability_name,
)
from admin.message_map import _label

#: The ending a request of a journey should have to be a best case (everything else: finished).
_GOOD_FOR: dict[str, frozenset[str]] = {CANCELLED_JOURNEY: frozenset({CANCELLED})}
#: Journeys where a question from Mesiri is part of the way, not a cost.
_QUESTION_ALLOWED = frozenset({ASKED_ANSWERED, MEMORY})


def _good(journey: str) -> frozenset[str]:
    return _GOOD_FOR.get(journey, GOOD_ENDINGS)


def clean(intent: dict[str, Any], journey: str) -> bool:
    """Whether a request can be the best case of a journey: it ended the way the journey should, nobody
    corrected it later, and Mesiri asked no question the journey does not need."""
    return (intent["ending"] in _good(journey)
            and (not intent.get("corrected_later") or journey == CORRECTED_AFTER_SAVE)
            and (not intent.get("had_question") or journey in _QUESTION_ALLOWED))


def score(intent: dict[str, Any]) -> tuple[float, ...]:
    """Lower is better: first, a card that was saved or cancelled by one of the request's own messages (on a
    shared card another request may hold the tap, and the preview would stop before it); then fewest refusals
    the model had to recover from, fewest messages, fastest slowest reply, the newest."""
    closes_elsewhere = bool(intent.get("reached_card")) and not intent.get("own_close")
    return (int(closes_elsewhere), intent.get("refusals", 0), len(intent["messages"]),
            intent.get("slowest_reply_s") or 0.0, -intent["started_at"].timestamp())


#: At most this many clean runs per journey are offered to step through (and to pin).
MAX_CANDIDATES = 10


def candidates(intents: list[dict[str, Any]], journey: str) -> list[dict[str, Any]]:
    """The clean requests of a journey, best first."""
    return sorted((i for i in intents if journey in i["journeys"] and clean(i, journey)), key=score)


def best_case(intents: list[dict[str, Any]], journey: str) -> dict[str, Any] | None:
    """The best clean request of a journey, or None when there is none."""
    found = candidates(intents, journey)
    return found[0] if found else None


def playbook(intents: list[dict[str, Any]],
             pins: dict[tuple[str, str], dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Modules -> capabilities -> journeys, each with its best case (an intent id) or none, and how many real
    requests of that journey end the same way. Only capabilities that are a tool a person asks for: talk with no
    tool, failures and the team feedback tool have no "how it should work".

    ``pins`` (decision D3): an admin's chosen example per (capability, journey), by the first message of the
    request. A pinned request in the window is the best case whatever its score; a pin whose request is not in
    the window is reported (``pinned.in_window`` false) and the scored pick shows."""
    pins = pins or {}
    done = [i for i in intents if i["ending"] != OPEN and not i["capability"].startswith("_")
            and i["capability"] != FEEDBACK]
    by_section: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for i in done:
        by_section.setdefault(i["section"], {}).setdefault(i["capability"], []).append(i)

    modules = []
    for section, caps in by_section.items():
        capabilities = []
        for tool, rows in sorted(caps.items(), key=lambda kv: -len(kv[1])):
            journeys = []
            for journey, label in JOURNEYS.items():
                used = [i for i in rows if journey in i["journeys"]]
                if not used:
                    continue
                clean_runs = candidates(used, journey)
                best = clean_runs[0] if clean_runs else None
                pin = pins.get((tool, journey))
                pinned = None
                if pin:
                    chosen = next((i for i in used if i["messages"] and i["messages"][0] == pin["message_id"]), None)
                    pinned = {**pin, "in_window": chosen is not None}
                    if chosen is not None:
                        best = chosen
                journeys.append({
                    "key": journey, "label": label, "count": len(used),
                    "same_end": sum(1 for i in used if i["ending"] in _good(journey)),
                    "best": best["id"] if best else None,
                    "best_messages": len(best["messages"]) if best else 0,
                    "best_reply_s": best.get("slowest_reply_s") if best else None,
                    "pinned": pinned,
                    "candidates": [i["id"] for i in clean_runs[:MAX_CANDIDATES]],
                })
            capabilities.append({"key": tool, "name": capability_name(tool), "tool": tool, "count": len(rows),
                                 "journeys": journeys,
                                 "missing": sum(1 for j in journeys if j["best"] is None)})
        modules.append({"key": section, "label": _label(section), "count": sum(c["count"] for c in capabilities),
                        "capabilities": capabilities,
                        "missing": sum(c["missing"] for c in capabilities)})
    modules.sort(key=lambda m: -m["count"])
    return modules
