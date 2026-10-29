"""What the model is shown of the conversation so far (request 132, P2.5).

With ``draft_v2`` on, the model does not read its own past replies: it copied
what they carried (a card header, "[options: ...]", the "closed" note) into its
new ones. It is shown instead

- the STATE, as one block (``draft.context_line`` / ``saved_context_line``: the
  open card's lines and the questions waiting on it, the last saved card), and
- each earlier turn as what the sender said plus a short gist of the answer: its
  first plain sentence, with no card, no options and no note.
"""

from __future__ import annotations

from dataclasses import replace

from .prompt import Turn
from .reply_clean import clean_model_text

#: The longest gist of an earlier reply.
GIST_MAX = 120
_CARD_LINE = ("📝", "✅", "❓", "•", "📍", "❌")


def gist(reply: str) -> str:
    """The first plain sentence of ``reply`` (no card, options or notes), cut
    short; empty when the reply was only a card."""
    from .reply_text import sentences

    for line in clean_model_text(reply).split("\n"):
        line = line.strip()
        if not line or line.startswith(_CARD_LINE):
            continue
        first = next((s.strip() for s in sentences(line) if s.strip()), "")
        if first.endswith("?"):
            return ""  # a question is open only in the state block, never from the past
        if first:
            return first if len(first) <= GIST_MAX else first[: GIST_MAX - 1].rsplit(" ", 1)[0] + "…"
    return ""


def for_model(turns: tuple[Turn, ...]) -> tuple[Turn, ...]:
    """``turns`` as the model sees them in draft mode: the sender's words and the
    gist of each reply."""
    return tuple(replace(turn, assistant_reply=gist(turn.assistant_reply)) for turn in turns)
