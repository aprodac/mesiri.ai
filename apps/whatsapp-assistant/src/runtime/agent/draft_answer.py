"""Typed answers to a question on the open draft card, read by code (WA-81).

The card asks "Which site?" or "How many kg is 20 rod?". The answer used to go
back to the model, which had to call the tool again with exactly the right
arguments; live on 27 Oct it did not ("oru rod 12 kg" asked which site, then the
steel line showed twice and the 12 kg was lost). An answer is short and has a
fixed shape, so code reads it; anything else (a new update, a question) returns
None and the model reads the message as usual.

Pure functions; no I/O.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from . import draft_site, site_match

#: An answer is a few words; a longer message is something else (a new update).
MAX_ANSWER_WORDS = 7

#: Words that make "N <unit>" the amount of ONE of the reported unit ("oru rod 12 kg",
#: "1 rod = 12 kg", "per rod 12 kg", "ek rod 12 kg", "ഒരു റോഡ് 12 കിലോ").
_ONE = r"(?:oru|ore|one|ek|each|per|ഒരു|एक)"
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
#: How a stock unit may be written ("kg", "kilo", "കിലോ").
_UNIT_WORDS = {
    "kg": ("kg", "kgs", "kilo", "kilos", "kilogram", "kilograms", "കിലോ", "किलो"),
    "bag": ("bag", "bags", "chakku", "ചാക്ക്"),
    "cum": ("cum", "cubic", "m3"),
    "nos": ("nos", "no", "numbers", "pcs", "pieces", "ennam", "എണ്ണം"),
    "ton": ("ton", "tons", "tonne", "tonnes"),
}


def _words(text: str) -> list[str]:
    return [w for w in re.split(r"[\s,=:/\-]+", (text or "").strip().casefold()) if w]


def site_answer(actor: Any, text: str, options: list[str]) -> str | None:
    """The option of the card's "which site?" that ``text`` names when it says only
    that ("Green Villa", "Green Villa, Kakkanad", "Site B-il"), else None. "Green
    Villa 2 helper vannu" names the site but is an update, not an answer."""
    if not text or len(_words(text)) > MAX_ANSWER_WORDS:
        return None
    site = draft_site.named_in(actor, text)
    if site is None or not draft_site.is_location_statement(actor, text, str(site.name)):
        return None
    want = set(site_match.words(str(site.name)))
    return next((o for o in options if want and want <= set(site_match.words(o))), str(site.name))


def _number(raw: str) -> Decimal | None:
    try:
        value = Decimal(raw.replace(",", "."))
    except InvalidOperation:
        return None
    return value if value > 0 else None


def amount_answer(text: str, args: dict[str, Any], stock_unit: str) -> Decimal | None:
    """The amount in ``stock_unit`` that ``text`` gives for the waiting line ``args``
    ("20 rod"): "oru rod 12 kg" / "1 rod = 12 kg" -> 240; "240 kg" / "240" -> 240.
    None when it is not such an answer (no number, too many words, another unit)."""
    words = _words(text)
    if not words or len(words) > MAX_ANSWER_WORDS or not stock_unit:
        return None
    asked_unit = str(args.get("unit") or "").strip().casefold()
    stock_words = set(_UNIT_WORDS.get(stock_unit.casefold(), ())) | {stock_unit.casefold()}
    unit_words = {asked_unit, asked_unit.rstrip("s"), f"{asked_unit.rstrip('s')}s"} - {""}
    known = stock_words | unit_words | {"=", "aanu", "anu", "und", "undu", "ku", "kku", "nu", "is", "hai", "approx"}
    numbers = [n for n in (_number(m) for m in _NUMBER.findall(text)) if n is not None]
    rest = [w for w in words if not _NUMBER.fullmatch(w) and w not in known and not re.fullmatch(_ONE, w)]
    if not numbers or rest:
        return None
    quantity = _number(str(args.get("quantity") or ""))
    lowered = " ".join(words)
    per_one = bool(re.search(rf"(?:^|\s){_ONE}(?:\s|$)", lowered)) or (
        len(numbers) == 2 and numbers[0] == 1 and any(w in unit_words for w in words)
    )
    if per_one:
        each = numbers[-1]
        return each * quantity if quantity is not None else None
    if len(numbers) != 1:
        return None
    return numbers[0]


def _plain(text: str) -> list[str]:
    """Words only: no emoji, signs or punctuation ("➕ Add new: TMT" -> add new tmt)."""
    # Malayalam vowel signs and the virama are combining marks, not \w: keep them in the word.
    return [w for w in re.split(r"[^\w\u0d00-\u0d7f]+", (text or "").casefold()) if w]


def option_answer(text: str, options: list[str]) -> str | None:
    """Request 159 (A): the one option of a card question that a short typed reply
    picks: its number ("2"), its words ("office cash" for "Office Cash"), or words
    only that option has ("own pocket" for "My own pocket"). None when the reply
    is longer than an answer, or fits no option or more than one (then the model
    reads it as usual)."""
    said = _plain(text)
    if not said or len(said) > MAX_ANSWER_WORDS or not options:
        return None
    if len(said) == 1 and said[0].isdigit():
        n = int(said[0])
        return options[n - 1] if 1 <= n <= len(options) else None
    exact = [o for o in options if _plain(o) == said]
    if len(exact) == 1:
        return exact[0]
    want = set(said)
    within = [o for o in options if want <= set(_plain(o))]
    return within[0] if len(within) == 1 else None
