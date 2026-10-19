"""Backend rejection reasons, said the way a site engineer can act on them.

A domain validator's reason ("activity must have a narrative or at least one
quantity") is written for developers. When a confirmed record is rejected, the
sender gets a short question or line instead; the raw reasons go to the log
only. Unknown reasons fall back to a generic line -- never the raw text.
"""

from __future__ import annotations

import logging
import re

_log = logging.getLogger("mesiri.friendly_errors")

_GENERIC = "I couldn't save that — something in it wasn't clear. Please send it again."

#: (pattern on the lower-cased reason, friendly line). First match wins.
_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"narrative|note update needs"),
        "What work was done? Tell me in a few words, e.g. “plastering on 2nd floor east side”.",
    ),
    (re.compile(r"unit is required"), "Which unit is that in — bags, kg, sqm, nos?"),
    (re.compile(r"quantity must be positive"), "How much was it? Please send the quantity again."),
    (re.compile(r"material_name is required"), "Which material was it?"),
    (re.compile(r"headcount|at least 1 person|at least one line"), "How many workers were there?"),
    (re.compile(r"worker_name"), "What is the worker's name?"),
    (re.compile(r"daily_wage"), "That wage doesn't look right — please send it again."),
    (re.compile(r"already exists"), "That already exists, so I didn't add it again."),
    (re.compile(r"project is not resolved"), "Which project is this for?"),
    (re.compile(r"site is not resolved"), "Which site is this for?"),
)


#: Rules whose line is a question for the sender, not a statement about a
#: failure. A reply made only of these must not open with "Couldn't record
#: this" -- it is asking, not apologising.
_QUESTION_RULES = frozenset(text for _, text in _RULES if text.rstrip().endswith("?") or "?" in text)


def is_question_rejection(reasons: list[str] | tuple[str, ...]) -> bool:
    """True when every reason maps to a friendly line that asks something."""
    lines = [
        next((text for pattern, text in _RULES if pattern.search(reason.lower())), None)
        for reason in reasons
    ]
    return bool(lines) and all(line in _QUESTION_RULES for line in lines)


def friendly_rejection(reasons: list[str] | tuple[str, ...], *, where: str = "") -> str:
    """One friendly line for a rejected record. ``where`` only labels the log."""
    _log.warning("record.rejected where=%s reasons=%s", where, "; ".join(reasons))
    lines: list[str] = []
    for reason in reasons:
        low = reason.lower()
        line = next((text for pattern, text in _RULES if pattern.search(low)), None)
        if line is not None and line not in lines:
            lines.append(line)
    if not lines:
        return _GENERIC
    return lines[0] if len(lines) == 1 else "\n".join(f"• {line}" for line in lines)
