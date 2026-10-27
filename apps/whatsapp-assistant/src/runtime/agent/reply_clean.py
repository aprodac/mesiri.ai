"""What the model's own words may never carry (request 132, P2.5).

The card, its questions and its buttons are the code's (``draft.card_text`` /
``card_rows``); the model returns tool calls and at most one short sentence. On
27 Oct it wrote "📝 To save · … for Unknown purpose" itself, with no card behind
it (so no buttons), and echoed a note the history carried into its own words
("(closed: not to be asked again unless the sender brings it up)").

``clean_model_text`` removes, from words the MODEL wrote:

- the card's headers and their bullets ("📝 To save", "📝 To close", "✅ Saved");
- "Reply YES / NO" instructions and ``[options: ...]`` lists (the buttons are the
  code's);
- parenthesised system notes: the closed-question note the history used to carry
  and anything that reads like a note to the model.

``leaks`` names what is still there, for the guard test: a reply must never
contain text of the prompt or of an annotation constant.
"""

from __future__ import annotations

import re

from .stale_questions import CLOSED

_HEADER = re.compile(r"^\s*(?:✅\s*Saved|📝\s*(?:To close|To save|Send to engineer))", re.IGNORECASE)
_BULLET = re.compile(r"^\s*[•\-\*▫️]\s")
_REPLY_YES = re.compile(r"\breply\s+(?:yes|no)\b", re.IGNORECASE)
_OPTIONS = re.compile(r"\[\s*options\s*:[^\]]*\]?", re.IGNORECASE)
#: "(closed: ...)" and notes written to the model, in brackets.
_NOTE = re.compile(
    r"\(\s*(?:closed\b|system\b|note to\b|internal\b)[^)]*\)"
    r"|\([^)]*(?:not to be asked again|unless the sender|nothing is written|not tapped yet)[^)]*\)",
    re.IGNORECASE,
)

#: Fragments that only the code's prompts and annotations contain.
_FRAGMENTS = (CLOSED.strip(" ()"), "not to be asked again", "[options:", "[context]", "User message:")


def clean_annotations(text: str) -> str:
    """``text`` without ``[options: ...]`` and parenthesised system notes: safe
    for every reply, whatever the mode."""
    text = _OPTIONS.sub("", text or "")
    text = _NOTE.sub("", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def clean_model_text(text: str) -> str:
    """The model's words for a draft-mode reply: annotations out, and no card of
    its own -- header lines with the bullets under them, and "Reply YES / NO"."""
    kept: list[str] = []
    dropping = False
    for line in clean_annotations(text).split("\n"):
        if _HEADER.match(line):
            dropping = True
            continue
        if dropping and _BULLET.match(line):
            continue
        dropping = False
        if _REPLY_YES.search(line):
            continue
        kept.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()


def leaks(text: str) -> list[str]:
    """What of the prompt, an annotation or a model-written card is in ``text``."""
    found = [f for f in _FRAGMENTS if f and f.casefold() in (text or "").casefold()]
    if _NOTE.search(text or ""):
        found.append("system note")
    return found
