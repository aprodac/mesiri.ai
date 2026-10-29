"""WA [103]: "cancel that" while a question is waiting drops the question.

Found live (24 Oct): a typed "cancel that" after "Which project is Site B part
of?" answered "Nothing to undo from your last card", as if it were an undo.
The sender is answering the question, not undoing a card, so it is settled here
without the model: the question is left, nothing is saved or undone.
"""

from __future__ import annotations

import re
from typing import Any

LEFT_IT = "Okay, left it."

#: Typed words that mean "drop this" (English, Manglish, Malayalam).
_DROP = frozenset(
    {
        "cancel",
        "cancel that",
        "cancel it",
        "cancel this",
        "never mind",
        "nevermind",
        "leave it",
        "forget it",
        "venda",
        "vendaa",
        "venda venda",
        "vendaa vendaa",
        "venda ath",
        "cancel cheyyu",
        "വേണ്ട",
        "വേണ്ടാ",
    }
)
#: A reply that already holds a record or a card, not a question. The words, not the
#: header's exact form ("🟠 *To save* · Tower A:" never held "To save:").
_NOT_A_QUESTION = ("To save", "To close", "Send to engineer", "✅ Saved", "✅ *Saved*", "Saved:")


def is_drop_word(text: str | None) -> bool:
    """Whether the whole message is one of the drop words."""
    words = " ".join(re.sub(r"[.,!?;:'\"()\-]", " ", (text or "").casefold()).split())
    return words in _DROP


def question_is_open(pack: Any | None) -> bool:
    """Whether the last thing said to the sender was a question (a trailing
    "?" or buttons), not a saved record or a card waiting on its Save tap."""
    turns = getattr(pack, "recent_turns", None) or ()
    if not turns:
        return False
    last = str(getattr(turns[-1], "assistant_reply", "") or "").strip()
    if not last or any(mark in last for mark in _NOT_A_QUESTION):
        return False
    before_options = last.split("\n[options:", 1)[0].rstrip()
    return "\n[options:" in last or before_options.endswith("?")
