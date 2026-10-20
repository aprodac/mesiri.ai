"""Did the worker actually ask something?

The AI splitter sometimes labels part of a plain site update ("Plastering 2nd
floor 40% aayi") as a LABOUR_QUERY_ASKED / INVENTORY_QUERY_ASKED segment, which
then answers a question nobody asked as a second message (request [63]). A
query segment is kept only when the message carries a question signal.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from mesiri_contracts.assistant.canonical_event import CanonicalEventType
from mesiri_contracts.assistant.v2.canonical_event import CanonicalEventV2

_QUERY_TYPES = frozenset(
    {
        CanonicalEventType.LABOUR_QUERY_ASKED,
        CanonicalEventType.INVENTORY_QUERY_ASKED,
    }
)


@lru_cache(maxsize=1)
def _signal_pattern() -> re.Pattern[str]:
    words = json.loads((Path(__file__).with_name("question_signal.json")).read_text("utf-8"))["words"]
    return re.compile(r"\b(?:" + "|".join(re.escape(w) for w in words) + r")\b", re.IGNORECASE)


def has_question_signal(text: str | None) -> bool:
    text = text or ""
    return "?" in text or _signal_pattern().search(text) is not None


def drop_unasked_queries(events: list[CanonicalEventV2], text: str | None) -> list[CanonicalEventV2]:
    """Drop labour / stock query segments after the first when ``text`` holds no
    question signal. The first event is never touched."""
    if len(events) < 2 or has_question_signal(text):
        return events
    return [events[0], *(e for e in events[1:] if e.event_type not in _QUERY_TYPES)]
