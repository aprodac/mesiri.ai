"""Hard UX checks on a conversation (request 185).

One check per failure family seen live 27-31 Oct (docs/reviews/2026-10-31-v2-cross-check.md).
They are deterministic: no model, no key. They judge a reply in the context of the turns before
it, so the same function scores production's replies (the baseline) and a replayed engine's.

A check finds a *symptom* in the words. It is a measuring tool for the test, never a rule the
assistant runs on (the assistant's rules live in the skills).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from .corpus import TAP

#: How the assistant's words are split into what the sender reads as prose (not the card lines).
_CARD_LINE = ("📝", "🟠", "✅", "❓", "•", "📍", "❌", "📦", "⚠️", "👍")


@dataclass(frozen=True, slots=True)
class Finding:
    check: str
    turn: int
    detail: str = ""


def prose(reply: str) -> str:
    """The reply without its card / list lines."""
    kept = [ln.strip() for ln in (reply or "").splitlines() if ln.strip() and not ln.strip().startswith(_CARD_LINE)]
    return " ".join(kept)


def _questions(reply: str) -> list[str]:
    text = prose(reply)
    return [q.strip().casefold() for q in re.findall(r"[^.?!\n]*\?", text) if len(q.strip()) > 8]


def _norm(text: str) -> str:
    return re.sub(r"\W+", " ", (text or "").casefold()).strip()


# ── the checks ─────────────────────────────────────────────────────────────
# Each: (turn index, replies so far, sender texts so far, kinds so far) -> detail or None.

_DEAD_END = re.compile(
    r"send it again in one line|that wasn'?t saved or changed|veendum ayakk|വീണ്ടും അയക്കുക"
    r"|save/maattan pattiyilla|സേവ് ചെയ്യാനോ മാറ്റാനോ കഴിഞ്ഞില്ല",
    re.IGNORECASE,
)
_CANT_SEE = re.compile(
    r"can only see what you type|don'?t see any earlier|pazhaya message|kaanaan kazhiyunnilla"
    r"|can'?t see (?:that|the|your) (?:old|earlier|previous)|മെസ്സേജ് കാണാൻ കഴിയുന്നില്ല",
    re.IGNORECASE,
)
_OUTAGE = re.compile(r"process this in a few minutes|couldn'?t process that message", re.IGNORECASE)
_LIMIT = re.compile(r"free-trial limit|trial (?:has )?ended", re.IGNORECASE)
_DUMP = re.compile(r"current inventory", re.IGNORECASE)
_ASKED_FOR_STOCK = re.compile(
    r"inventory|stock|സ്റ്റോക്ക്|baakki|ബാക്കി|\bleft\b|remaining|ഇൻവെന്ററി",
    re.IGNORECASE,
)
_CARD_WORD = re.compile(r"\bcard\b|കാർഡ്", re.IGNORECASE)
_NEGATIVE = re.compile(r"[−-]\s?\d+(?:\.\d+)?\s*(?:bags?|nos|pieces|kg|ton|cum)\b", re.IGNORECASE)


def dead_end(i: int, replies: Sequence[str], texts: Sequence[str], kinds: Sequence[str]) -> str | None:
    """'Send it again in one line' after the sender already said it."""
    m = _DEAD_END.search(replies[i])
    return m.group(0) if m else None


def repeated_question(i: int, replies: Sequence[str], texts: Sequence[str], kinds: Sequence[str]) -> str | None:
    """The same question again right after the sender answered it."""
    if i == 0:
        return None
    before = {_norm(q) for q in _questions(replies[i - 1])}
    for q in _questions(replies[i]):
        if _norm(q) in before:
            return q[:80]
    return None


def repeated_reply(i: int, replies: Sequence[str], texts: Sequence[str], kinds: Sequence[str]) -> str | None:
    """Word for word the previous reply to a DIFFERENT message (a complaint answered with the same
    text). The same message sent twice may get the same answer."""
    if i == 0 or not replies[i].strip() or kinds[i] == TAP:
        return None
    if _norm(texts[i]) == _norm(texts[i - 1]) or _LIMIT.search(replies[i]) or _OUTAGE.search(replies[i]):
        return None  # a system notice (trial limit, outage) is counted by its own check
    return "same as previous reply" if _norm(replies[i]) == _norm(replies[i - 1]) else None


def cant_see(i: int, replies: Sequence[str], texts: Sequence[str], kinds: Sequence[str]) -> str | None:
    """Says it cannot see a message the sender swiped and replied to, or its own earlier words."""
    m = _CANT_SEE.search(replies[i])
    return m.group(0) if m else None


def unasked_dump(i: int, replies: Sequence[str], texts: Sequence[str], kinds: Sequence[str]) -> str | None:
    """The whole inventory when the message did not ask about stock."""
    if not _DUMP.search(replies[i]):
        return None
    if i > 0 and _DUMP.search(replies[i - 1]) and _norm(texts[i]) != _norm(texts[i - 1]):
        return "inventory sent again after another message"
    if not _ASKED_FOR_STOCK.search(texts[i] or ""):
        return "inventory sent unasked"
    return None


def card_jargon(i: int, replies: Sequence[str], texts: Sequence[str], kinds: Sequence[str]) -> str | None:
    """Talks about 'the card' in its own words (the sender sees a message, not a card)."""
    m = _CARD_WORD.search(prose(replies[i]))
    return m.group(0) if m else None


def negative_stock(i: int, replies: Sequence[str], texts: Sequence[str], kinds: Sequence[str]) -> str | None:
    m = _NEGATIVE.search(replies[i])
    return m.group(0) if m else None


def outage(i: int, replies: Sequence[str], texts: Sequence[str], kinds: Sequence[str]) -> str | None:
    m = _OUTAGE.search(replies[i])
    return m.group(0) if m else None


def trial_limit(i: int, replies: Sequence[str], texts: Sequence[str], kinds: Sequence[str]) -> str | None:
    m = _LIMIT.search(replies[i])
    return m.group(0) if m else None


def no_reply(i: int, replies: Sequence[str], texts: Sequence[str], kinds: Sequence[str]) -> str | None:
    return "empty reply" if not (replies[i] or "").strip() else None


Check = Callable[[int, Sequence[str], Sequence[str], Sequence[str]], "str | None"]

#: Name -> check. ``severe`` checks are the ones the gate allows none of.
CHECKS: dict[str, Check] = {
    "dead_end": dead_end,
    "repeated_question": repeated_question,
    "repeated_reply": repeated_reply,
    "cant_see": cant_see,
    "unasked_dump": unasked_dump,
    "card_jargon": card_jargon,
    "negative_stock": negative_stock,
    "outage": outage,
    "trial_limit": trial_limit,
    "no_reply": no_reply,
}
SEVERE = frozenset({"dead_end", "repeated_question", "repeated_reply", "cant_see", "unasked_dump", "no_reply"})


def check_conversation(
    texts: Sequence[str], replies: Sequence[str], kinds: Sequence[str] | None = None
) -> list[Finding]:
    """Every finding of every check, turn by turn."""
    kinds = list(kinds or ["text"] * len(texts))
    found = []
    for i in range(len(replies)):
        for name, check in CHECKS.items():
            detail = check(i, replies, texts, kinds)
            if detail:
                found.append(Finding(name, i, str(detail)))
    return found
