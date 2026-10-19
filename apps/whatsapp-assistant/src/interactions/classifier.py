"""Deterministic classification of a confirmation reply.

Logic lives here; the *vocabulary* lives in confirmation_phrases.json so adding
a language is a config edit, not a code change. Matching is case-folded and
whole-phrase (a phrase matches if the normalized message equals it or contains
it as a whitespace-delimited token/run). No LLM — richer NLU is future work.
"""

from __future__ import annotations

import json
import pathlib

from .intent import InteractionIntent

_PHRASES_PATH = pathlib.Path(__file__).with_name("confirmation_phrases.json")


def _load_phrase_sets() -> dict[str, list[str]]:
    data = json.loads(_PHRASES_PATH.read_text(encoding="utf-8"))
    return {
        "confirm": [p.casefold() for p in data.get("confirm", [])],
        "reject": [p.casefold() for p in data.get("reject", [])],
        "cancel": [p.casefold() for p in data.get("cancel", [])],
    }


# Loaded once at import — the JSON is static configuration.
_PHRASE_SETS = _load_phrase_sets()

_INTENT_BY_KEY = {
    "confirm": InteractionIntent.CONFIRM,
    "reject": InteractionIntent.REJECT,
    "cancel": InteractionIntent.CANCEL,
}


#: A reply to a YES/NO question is a few words ("yes please", "no cancel"). A
#: longer message is a new message even when it happens to contain "done" or
#: "ok" ("Shuttering done for 3rd floor slab...") -- request [43].
MAX_REPLY_WORDS = 4


def _matches(normalized: str, tokens: set[str], phrases: list[str]) -> bool:
    for phrase in phrases:
        if " " in phrase:
            if phrase in normalized:  # multi-word phrase: substring on normalized text
                return True
        elif phrase in tokens:  # single token: exact token match (avoids "no" in "now")
            return True
    return False


def classify_reply(text: str | None) -> InteractionIntent:
    """Classify a reply while a workflow awaits confirmation.

    Conflicting signals (e.g. matches both confirm and reject) → AMBIGUOUS.
    No match → UNRELATED (a fresh intent, not a reply to the pending workflow).
    """
    if not text or not text.strip():
        return InteractionIntent.UNRELATED

    normalized = text.strip().casefold()
    tokens = {t.strip(".,!?;:'\"") for t in normalized.split()}
    if len(normalized.split()) > MAX_REPLY_WORDS:
        return InteractionIntent.UNRELATED

    confirm = _matches(normalized, tokens, _PHRASE_SETS["confirm"])
    reject = _matches(normalized, tokens, _PHRASE_SETS["reject"])
    cancel = _matches(normalized, tokens, _PHRASE_SETS["cancel"])

    # Only confirm-vs-negative is genuinely ambiguous. reject and cancel are both
    # negative (a "no cancel" is a clear abort, not a contradiction).
    if confirm and (reject or cancel):
        return InteractionIntent.AMBIGUOUS
    if confirm:
        return InteractionIntent.CONFIRM
    if cancel:
        return InteractionIntent.CANCEL
    if reject:
        return InteractionIntent.REJECT
    return InteractionIntent.UNRELATED
