"""Real conversations as replay input (request 185).

A *conversation* is one sender's messages in one company with no gap longer than
``GAP_MINUTES`` between them. Each turn keeps what the sender sent (text, a voice note's
transcript, a button's title) and what production answered, so the same checks can judge
production (the baseline) and a replayed engine.

The corpus holds real customer words: it is written outside the repository (the default is
``~/.mesiri/replay``) and never committed. Phone numbers are cut to the last 4 digits.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

GAP_MINUTES = 45
DEFAULT_DIR = Path.home() / ".mesiri" / "replay"

#: Kinds of turn. A voice note without a transcript (the speech call failed) cannot be replayed.
TEXT, VOICE, TAP, IMAGE, OTHER = "text", "voice", "tap", "image", "other"
_KIND = {"text": TEXT, "voice": VOICE, "interactive": TAP, "image": IMAGE}


@dataclass(slots=True)
class Turn:
    correlation_id: str
    at: str
    kind: str
    text: str
    reply: str = ""
    status: str = ""
    error_code: str = ""
    tools: list[str] = field(default_factory=list)

    @property
    def replayable(self) -> bool:
        return self.kind in (TEXT, VOICE, TAP) and bool(self.text.strip())


@dataclass(slots=True)
class Conversation:
    company: str
    sender: str
    turns: list[Turn] = field(default_factory=list)

    @property
    def key(self) -> str:
        first = self.turns[0].at[:16] if self.turns else ""
        return f"{self.company}/{self.sender}/{first}"


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _text_of(row: dict[str, Any]) -> str:
    """The sender's words: the body (a voice note's transcript is stored there), else a
    normalized text; a media payload with no words is empty."""
    body = row.get("body") or ""
    if body.lstrip().startswith("{"):
        try:
            body = json.loads(body).get("text") or ""
        except (ValueError, AttributeError):
            body = ""
    return str(body).strip()


def group(rows: Iterable[dict[str, Any]], *, gap_minutes: int = GAP_MINUTES) -> list[Conversation]:
    """Rows (oldest first or not) -> conversations, each sender's turns in time order."""
    by_sender: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        by_sender.setdefault((row.get("org") or "-", row.get("s") or "-"), []).append(row)
    conversations: list[Conversation] = []
    for (company, sender), items in by_sender.items():
        items.sort(key=lambda r: r["received_at"])
        current: Conversation | None = None
        last: datetime | None = None
        for row in items:
            at = _parse_time(row["received_at"])
            if current is None or last is None or (at - last).total_seconds() > gap_minutes * 60:
                current = Conversation(company=company, sender=sender)
                conversations.append(current)
            last = at
            current.turns.append(
                Turn(
                    correlation_id=row.get("correlation_id") or "",
                    at=row["received_at"],
                    kind=_KIND.get(row.get("t") or "", OTHER),
                    text=_text_of(row),
                    reply=row.get("reply") or "",
                    status=row.get("st") or "",
                    error_code=row.get("e") or "",
                    tools=list(row.get("tools") or []),
                )
            )
    conversations.sort(key=lambda c: c.turns[0].at)
    return conversations


def save(conversations: list[Conversation], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for conv in conversations:
            fh.write(json.dumps(asdict(conv), ensure_ascii=False) + "\n")
    return path


def load(path: Path) -> list[Conversation]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        out.append(
            Conversation(company=raw["company"], sender=raw["sender"], turns=[Turn(**t) for t in raw["turns"]])
        )
    return out
