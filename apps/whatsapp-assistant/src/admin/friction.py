"""Friction signals -- signs a conversation went badly, read from behaviour (WA-15).

Workers never rate the assistant, so this module looks for what they *do*
when something goes wrong: repeat themselves, say "wrong", undo, give up
halfway. Pure functions over the conversation shape that
admin/review_export.py builds; no I/O, no AI. The nightly reviewer uses the
score to decide which conversations to read first, and
admin/review_router.py's /friction trend uses the same signals day by day, so
WA-16 can tell whether a fix made things better or worse.

Every signal is a heuristic. A "no" can be a legitimate answer, and a
repeated message can be a second delivery of the same cement. The
weights are deliberately small and the reviewer still judges each
conversation; tune the weights here when the reports disagree with people.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from channel.replies import render_unsupported_reply

# A repeat counts only if it comes this quickly after the earlier message.
REPEAT_WINDOW_SECONDS = 180
REPEAT_SIMILARITY = 0.6

# "Slow" thresholds (ms) by message type; the rubric's "too slow" line.
SLOW_MS = {"text": 15_000, "interactive": 15_000, "button": 15_000}
SLOW_MS_MEDIA = 30_000

# Phases in which a workflow is still waiting on the user. A conversation
# that ends in one of these was left unfinished.
OPEN_PHASES = frozenset({"active", "awaiting_confirmation", "collecting_fields", "paused"})

# Workflows a user only reaches when something earlier was wrong.
CORRECTION_WORKFLOWS = frozenset({"site.activity_correction", "finance.reverse"})

# Strong: the user says the assistant got it wrong. English, Hinglish,
# Malayalam/Tamil/Hindi transliterations seen on sites. Weak: a bare
# no/cancel, which is often just an answer to a yes/no question.
_STRONG_NEGATIVE = re.compile(
    r"\b(wrong|galat|incorrect|not (this|that|correct|right)|mistake|thett?u|tappu|"
    r"sari ?alla|sahi nahi|kuch aur|undo|why (did|is)|didn'?t (ask|say)|not what)\b",
    re.IGNORECASE,
)
_WEAK_NEGATIVE = re.compile(
    r"^\s*(no+|nahi|nahin|illa|venda|cancel|stop)\s*[.!]*\s*$", re.IGNORECASE
)

WEIGHTS = {
    "failed": 3,
    "repeat": 2,
    "negative": 2,
    "correction": 2,
    "abandoned": 2,
    "unsupported": 2,
    "weak_negative": 1,
    "slow": 1,
}

_WORD = re.compile(r"\w+", re.UNICODE)


def _words(text: str | None) -> set[str]:
    return {w.lower() for w in _WORD.findall(text or "")}


def _similar(a: str | None, b: str | None) -> bool:
    wa, wb = _words(a), _words(b)
    if not wa or not wb:
        return False
    return len(wa & wb) / len(wa | wb) >= REPEAT_SIMILARITY


def _ts(iso: str) -> datetime:
    return datetime.fromisoformat(iso)


def signals_for(conversation: dict[str, Any]) -> list[dict[str, Any]]:
    """All friction signals in one conversation, in message order.

    Each is ``{"signal": name, "at": message index, "detail": short text}``.
    """
    messages = conversation["messages"]
    unsupported = render_unsupported_reply()
    found: list[dict[str, Any]] = []

    def add(signal: str, i: int, detail: str) -> None:
        found.append({"signal": signal, "at": i, "detail": detail})

    for i, m in enumerate(messages):
        text = m.get("text")
        if m.get("status") == "failed" or any(s.get("ok") is False for s in m.get("stages", [])):
            add("failed", i, m.get("error_code") or "a stage failed")
        if (m.get("reply") or "").strip() == unsupported.strip():
            add("unsupported", i, "got the 'can't do that yet' reply")
        if m.get("workflow_key") in CORRECTION_WORKFLOWS and m.get("workflow_key") != (
            messages[i - 1].get("workflow_key") if i else None
        ):
            add("correction", i, m["workflow_key"])

        limit = SLOW_MS.get(m.get("type") or "", SLOW_MS_MEDIA)
        if m.get("wall_ms") is not None and m["wall_ms"] > limit:
            add("slow", i, f"{m['wall_ms'] / 1000:.0f}s")

        if i == 0:
            continue
        prev = messages[i - 1]
        if _STRONG_NEGATIVE.search(text or ""):
            add("negative", i, (text or "")[:60])
        elif prev.get("reply") and _WEAK_NEGATIVE.match(text or ""):
            add("weak_negative", i, (text or "")[:20])
        if (
            m.get("type") == "text"
            and prev.get("type") == "text"
            and (_ts(m["at"]) - _ts(prev["at"])).total_seconds() <= REPEAT_WINDOW_SECONDS
            and _similar(text, prev.get("text"))
        ):
            add("repeat", i, "sent nearly the same thing again")

    if messages and (messages[-1].get("workflow_phase") or "") in OPEN_PHASES:
        add("abandoned", len(messages) - 1, f"left {messages[-1].get('workflow_key')} unfinished")
    return found


def score(signals: list[dict[str, Any]]) -> int:
    return sum(WEIGHTS.get(s["signal"], 1) for s in signals)


def annotate(conversations: list[dict[str, Any]]) -> dict[str, Any]:
    """Adds ``friction`` to each conversation in place; returns the totals."""
    for conv in conversations:
        sig = signals_for(conv)
        conv["friction"] = {"score": score(sig), "signals": sig}
    return summarize(conversations)


def summarize(conversations: list[dict[str, Any]]) -> dict[str, Any]:
    """Totals over conversations that ``annotate`` has already scored."""
    counts: dict[str, int] = {}
    with_friction = 0
    by_workflow: dict[str, dict[str, int]] = {}
    for conv in conversations:
        sig = conv["friction"]["signals"]
        if sig:
            with_friction += 1
        for s in sig:
            counts[s["signal"]] = counts.get(s["signal"], 0) + 1
        keys = {m.get("workflow_key") for m in conv["messages"] if m.get("workflow_key")} or {
            "(none)"
        }
        for key in keys:
            row = by_workflow.setdefault(key, {"conversations": 0, "with_friction": 0})
            row["conversations"] += 1
            row["with_friction"] += 1 if sig else 0
    total = len(conversations)
    return {
        "conversations": total,
        "with_friction": with_friction,
        "friction_rate": round(with_friction / total, 3) if total else None,
        "avg_user_messages": round(sum(len(c["messages"]) for c in conversations) / total, 2)
        if total
        else None,
        "signals": dict(sorted(counts.items(), key=lambda kv: -kv[1])),
        "by_workflow": dict(sorted(by_workflow.items(), key=lambda kv: -kv[1]["with_friction"])),
    }
