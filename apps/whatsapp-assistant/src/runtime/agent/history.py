"""What the model is shown of the conversation so far (request 132, P2.5).

With ``draft_v2`` on, the model does not read its own past replies: it copied
what they carried (a card header, "[options: ...]", the "closed" note) into its
new ones. It is shown instead

- the STATE, as one block (``draft.context_line`` / ``saved_context_line``: the
  open card's lines and the questions waiting on it, the last saved card), and
- each earlier turn as what the sender said plus a short gist of the answer: its
  plain sentences (not only the first: live 29 Oct), with no card, no options,
  no note and no question.
"""

from __future__ import annotations

from dataclasses import replace

from .prompt import Turn
from .reply_clean import clean_model_text

#: The longest gist of an earlier reply. Live 29 Oct: the gist was the reply's
#: first sentence only, so of "No work saved today. Materials: 10 bags cement in.
#: 2 issues: ..." the model saw "No work saved today." and then told the sender
#: it had never said anything about cement or rain.
GIST_MAX = 400
_CARD_LINE = ("📝", "🟠", "✅", "❓", "•", "📍", "❌")


def gist(reply: str) -> str:
    """The plain sentences of ``reply`` (no card, options, notes or questions),
    cut short; empty when the reply was only a card or a question."""
    from .reply_text import sentences

    kept: list[str] = []
    for line in clean_model_text(reply).split("\n"):
        line = line.strip()
        if not line or line.startswith(_CARD_LINE):
            continue
        for sentence in (s.strip() for s in sentences(line)):
            if not sentence or sentence.endswith("?"):
                continue  # a question is open only in the state block, never from the past
            kept.append(sentence)
    text = " ".join(kept)
    return text if len(text) <= GIST_MAX else text[: GIST_MAX - 1].rsplit(" ", 1)[0] + "…"


def for_model(turns: tuple[Turn, ...]) -> tuple[Turn, ...]:
    """``turns`` as the model sees them in draft mode: the sender's words and the
    gist of each reply."""
    return tuple(replace(turn, assistant_reply=gist(turn.assistant_reply)) for turn in turns)
