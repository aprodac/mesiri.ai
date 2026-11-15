"""What works, version 2 (SA-39 phase 4): Patterns -- the connections between failures, so the next fix is obvious.

1. **Same cause, many places**: every problem of the window (``intents_summary.problem_groups``), with every
   capability it hit, against the window before (new / growing / shrinking), and the ones that are gone.
2. **Where each flow leaks**: per capability, asked -> a tool was called -> ready or answered -> finished, and the
   widest drop.
3. **What makes it worse**: the finished share split by how it was sent, the script of the words, the sender's
   role and the company. A split is shown only when at least two of its groups have ``SPLIT_FLOOR`` requests:
   a share of six requests misleads.
4. **What people do after a failure**: tried again, said it was wrong, asked something else, or stopped. The
   repeat and the "that's wrong" signals are ``admin/friction.py``'s (the nightly reviewer's), not new rules.

Every cause carries what makes a fix fast: the correlation ids of its requests (the start of every fix is
``scripts/replay_to_test.py <correlation id>``, docs/engineering/FIX_APPROACH.md) and, when Mesiri passed a
request to the team, the team request's reference (``release_notes.request_ref``: the same "#a83f12" the request
log and the group show, made from the correlation id, never matched by text).

Pure functions; no I/O.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from admin.friction import signals_for
from admin.intents import FEEDBACK, GOOD_ENDINGS, OPEN, capability_name
from admin.intents_summary import _funnel, is_problem, problem_groups
from admin.message_map import _label

#: A split group needs this many requests before its share is shown.
SPLIT_FLOOR = 10
#: At most this many correlation ids are handed out per cause.
MAX_IDS = 25
REPLAY = "python3 scripts/replay_to_test.py {}"

#: Unicode blocks people write in, for the "script" split (read from the letters, no word lists).
_SCRIPTS = (
    ("malayalam", "Malayalam script", 0x0D00, 0x0D7F),
    ("devanagari", "Devanagari (Hindi)", 0x0900, 0x097F),
    ("tamil", "Tamil script", 0x0B80, 0x0BFF),
    ("kannada", "Kannada script", 0x0C80, 0x0CFF),
    ("telugu", "Telugu script", 0x0C00, 0x0C7F),
)
_HOW = {"text": "Typed", "voice": "Voice note", "audio": "Voice note", "image": "Photo", "interactive": "Button tap"}

AFTER = {
    "repeated": "Sent it again",
    "said_wrong": "Said it was wrong",
    "moved_on": "Asked something else",
    "stopped": "Stopped",
}


def script_of(text: str) -> tuple[str, str]:
    """The script most of the letters are in: ``("latin", "Latin letters (English, Manglish)")`` and so on."""
    counts: Counter[str] = Counter()
    for ch in text or "":
        code = ord(ch)
        if ch.isascii() and ch.isalpha():
            counts["latin"] += 1
            continue
        for key, _name, lo, hi in _SCRIPTS:
            if lo <= code <= hi:
                counts[key] += 1
                break
    if not counts:
        return "none", "No words (voice note heard as nothing, a tap, a photo)"
    key = counts.most_common(1)[0][0]
    if key == "latin":
        return key, "Latin letters (English, Manglish)"
    return key, next(label for k, label, _lo, _hi in _SCRIPTS if k == key)


def team_ref(correlation_id: str) -> str:
    from runtime.release_notes import request_ref

    return request_ref(correlation_id)


def _trend(now: int, before: int) -> str:
    if before == 0:
        return "new"
    if now >= before * 1.5 and now - before >= 3:
        return "growing"
    if now <= before / 1.5 and before - now >= 3:
        return "shrinking"
    return "steady"


def causes(intents: list[dict[str, Any]], earlier: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Every problem with its trend and fix actions; and the problems of the window before that are gone."""
    before = {g["key"]: g["count"] for g in problem_groups(earlier)}
    out = []
    for g in problem_groups(intents, top_capabilities=50):
        rows = g.pop("_rows")
        ids = [r["correlation_ids"][0] for r in rows if r.get("correlation_ids")][:MAX_IDS]
        passed = [cid for r in rows if FEEDBACK in r.get("tools", []) or r["ending"] == "complained"
                  for cid in r.get("correlation_ids", [])[:1]]
        out.append({**g, "before": before.get(g["key"], 0), "trend": _trend(g["count"], before.get(g["key"], 0)),
                    "correlation_ids": ids, "replay": REPLAY.format(ids[0]) if ids else "",
                    "team_refs": sorted({ref for cid in passed if (ref := team_ref(cid))})[:10]})
    current = {g["key"] for g in out}
    gone = [{"key": g["key"], "line": g["line"], "before": g["count"]}
            for g in problem_groups(earlier) if g["key"] not in current]
    return out, gone


def leaks(intents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per capability a person asks for: its funnel and the widest drop, the largest loss first."""
    by_cap: dict[str, list[dict[str, Any]]] = {}
    for r in intents:
        if not r["capability"].startswith("_") and r["capability"] != FEEDBACK:
            by_cap.setdefault(r["capability"], []).append(r)
    out = []
    for tool, rows in by_cap.items():
        funnel = _funnel(rows)
        lost = [r for r in rows if r["ending"] not in GOOD_ENDINGS]
        if not lost:
            continue
        out.append({"key": tool, "name": capability_name(tool), "section": _label(rows[0]["section"]),
                    "steps": funnel["steps"], "widest_drop": funnel["widest_drop"], "lost": len(lost),
                    "intents": [r["id"] for r in sorted(lost, key=lambda r: r["started_at"], reverse=True)][:25]})
    return sorted(out, key=lambda x: -x["lost"])


def _split(rows: list[dict[str, Any]], key, label: str, dim: str) -> dict[str, Any] | None:
    groups: dict[str, list[dict[str, Any]]] = {}
    names: dict[str, str] = {}
    for r in rows:
        k, name = key(r)
        groups.setdefault(k, []).append(r)
        names[k] = name
    shown = [(k, g) for k, g in groups.items() if len(g) >= SPLIT_FLOOR]
    if len(shown) < 2:
        return None
    return {
        "key": dim, "label": label,
        "groups": sorted(({"key": k, "name": names[k], "count": len(g),
                           "finished": sum(1 for r in g if r["ending"] in GOOD_ENDINGS)} for k, g in shown),
                         key=lambda x: -x["count"]),
        "hidden": sum(len(g) for k, g in groups.items() if len(g) < SPLIT_FLOOR),
    }


def splits(intents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The finished share by how it was sent, the script, the sender's role, the company; only the splits with
    at least two groups over the floor."""
    rows = [r for r in intents if not r["capability"].startswith("_")]
    out = [
        _split(rows, lambda r: (r["how"], _HOW.get(r["how"], r["how"].capitalize())), "How it was sent", "how"),
        _split(rows, lambda r: script_of(r.get("text") or ""), "What it was written in", "script"),
        _split(rows, lambda r: (r.get("sender_role") or "unknown",
                                (r.get("sender_role") or "Unknown role").replace("_", " ").capitalize()),
               "Who sent it", "role"),
        _split(rows, lambda r: (r.get("company") or "unknown", r.get("company") or "Unknown company"),
               "Company", "company"),
    ]
    return [s for s in out if s]


def _friction_message(row: dict[str, Any], *, text: str | None = None) -> dict[str, Any]:
    """A message row in the shape ``admin/friction.py`` reads."""
    return {"text": row.get("body_text") if text is None else text, "reply": row.get("assistant_reply"),
            "type": row.get("message_type"), "status": row.get("processing_status"),
            "at": row["received_at"].isoformat()}


def after_failure(intents: list[dict[str, Any]], messages_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """What the person did right after a request that did not work, in the same conversation."""
    by_kind: dict[str, list[str]] = {k: [] for k in AFTER}
    for n, r in enumerate(intents):
        if r["ending"] == OPEN or not is_problem(r):
            continue
        following = intents[n + 1] if n + 1 < len(intents) else None
        if following is None or following["conversation"] != r["conversation"]:
            by_kind["stopped"].append(r["id"])
            continue
        last = messages_by_id.get(r["messages"][-1])
        nxt = messages_by_id.get(following["messages"][0])
        if not last or not nxt:
            continue
        # friction compares the next message with the one before it: give it the request's own first words.
        first = messages_by_id.get(r["messages"][0]) or last
        signals = {s["signal"] for s in signals_for({"messages": [
            _friction_message(last, text=first.get("body_text")), _friction_message(nxt)]})}
        if signals & {"negative", "weak_negative"} or following["ending"] == "complained":
            kind = "said_wrong"
        elif "repeat" in signals or following["capability"] == r["capability"]:
            kind = "repeated"
        else:
            kind = "moved_on"
        by_kind[kind].append(r["id"])
    return {"total": sum(len(v) for v in by_kind.values()),
            "kinds": [{"key": k, "label": AFTER[k], "count": len(v), "intents": v[-25:][::-1]}
                      for k, v in by_kind.items()]}


def patterns(intents: list[dict[str, Any]], earlier: list[dict[str, Any]],
             messages_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    done = [r for r in intents if r["ending"] != OPEN]
    found, gone = causes(done, [r for r in earlier if r["ending"] != OPEN])
    return {"causes": found, "gone": gone, "leaks": leaks(done), "splits": splits(done),
            "after_failure": after_failure(intents, messages_by_id), "split_floor": SPLIT_FLOOR}
