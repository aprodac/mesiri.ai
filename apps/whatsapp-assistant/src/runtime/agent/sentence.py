"""The sentence above the card must speak of every item on the card (22 Oct:
"6 mason, 2 electrician ... " came back as a sentence about the masons only).

The model writes the sentence from the tool calls it made. This checks it
against those same calls -- their structured arguments, never the worker's
text: every saved item has key numbers and nouns (a trade and its headcount, a
material and its quantity, a work type, a floor), and the sentence must carry
at least one of them per item. A sentence in another script cannot be matched
on English nouns, so there only the numbers count.

When it falls short the model gets one more try with the reason; if that falls
short too, a short line built from the same arguments goes out instead.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from mesiri_ai.models import ToolCallRecord

from .prompt import is_manglish
from .tools import (
    SAVE_EXPENSE,
    SAVE_LABOUR,
    SAVE_MATERIAL_RECEIPT,
    SAVE_MATERIAL_USAGE,
    SAVE_WORK_DONE,
)

#: The save tools that put an item on the card, and are spoken of.
SPOKEN_TOOLS = frozenset(
    {SAVE_LABOUR, SAVE_WORK_DONE, SAVE_MATERIAL_RECEIPT, SAVE_MATERIAL_USAGE, SAVE_EXPENSE}
)

_STEM = 5
_NUMBER = re.compile(r"\d+(?:\.\d+)?")


@dataclass(frozen=True, slots=True)
class Item:
    """One thing the sentence must mention: any one of ``numbers`` or ``words``
    is enough. ``label`` is how it is named to the model and in the fallback."""

    label: str
    numbers: frozenset[str]
    words: frozenset[str]


def _num(value: Any) -> str:
    try:
        number = float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return ""
    return str(int(number)) if number == int(number) else f"{number:g}"


def _words(*values: Any) -> frozenset[str]:
    """Stems of the words in ``values``: "plastering" and "plaster" meet."""
    out: set[str] = set()
    for value in values:
        for word in re.findall(r"[^\W\d_]+", str(value or "").casefold()):
            if len(word) >= 4:
                out.add(word[:_STEM])
    return frozenset(out)


def _nums(*values: Any) -> frozenset[str]:
    return frozenset(n for n in (_num(v) for v in values) if n)


def items_of(calls: Iterable[ToolCallRecord]) -> list[Item]:
    """What the card shows, from the arguments of the save calls that saved."""
    items: list[Item] = []
    for call in calls:
        if call.name not in SPOKEN_TOOLS or call.outcome.content.get("status") != "saved":
            continue
        args = call.arguments or {}
        if call.name == SAVE_LABOUR:
            for line in args.get("workers") or []:
                if not isinstance(line, dict):
                    continue
                trade = str(line.get("trade") or "").strip()
                name = str(line.get("name") or "").strip()
                count = _num(line.get("headcount")) if line.get("headcount") else ""
                label = " ".join(p for p in (count, trade or name) if p) or "workers"
                items.append(Item(label, _nums(count), _words(trade, name)))
        elif call.name == SAVE_WORK_DONE:
            quantities = [q for q in args.get("quantities") or [] if isinstance(q, dict)]
            work = str(args.get("work_type") or (quantities[0].get("work_type") if quantities else "") or "")
            place = str(args.get("location") or "")
            label = ", ".join(p for p in (work, place) if p) or "work done"
            items.append(
                Item(
                    label,
                    _nums(args.get("progress_percent"), *(q.get("quantity") for q in quantities)),
                    _words(work, place),
                )
            )
        elif call.name == SAVE_EXPENSE:
            what = str(args.get("description") or args.get("category") or "expense")
            amount = _num(args.get("amount"))
            items.append(Item(f"{what} {amount}".strip(), _nums(amount), _words(what, args.get("category"))))
        else:
            material = str(args.get("material") or "material")
            qty = " ".join(p for p in (_num(args.get("quantity")), str(args.get("unit") or "")) if p)
            verb = "received" if call.name == SAVE_MATERIAL_RECEIPT else "used"
            items.append(Item(f"{material} {verb} {qty}".strip(), _nums(args.get("quantity")), _words(material)))
    return items


def missing_items(text: str, items: list[Item]) -> list[Item]:
    """The items the sentence does not speak of."""
    lowered = (text or "").casefold()
    present = set(_NUMBER.findall(lowered))
    native = bool(re.search(r"[ऀ-෿]", lowered))
    missing = []
    for item in items:
        if item.numbers & present:
            continue
        if not native and any(stem in lowered for stem in item.words):
            continue
        if native and not item.numbers:
            continue  # a native-script sentence cannot be matched on English nouns
        missing.append(item)
    return missing


def retry_request(missing: list[Item]) -> str:
    return (
        "Your message leaves out: "
        + "; ".join(item.label for item in missing)
        + ". Say your message again so it speaks of every item you saved, short, in the same "
        "language and letters, with the same numbers and nothing else added. Only the message."
    )


_ML = re.compile(r"[ഀ-ൿ]")
_HI = re.compile(r"[ऀ-ॿ]")

#: (lead, ask) -- the same shapes as the persona's own lines; no claim that
#: anything is saved: the Save tap keeps it.
_LINES = {
    "en": ("Got it: {items}.", "Please check it and tap Save."),
    "manglish": ("Sheri: {items}.", "Onnu nokki Save tap cheyyu."),
    "ml": ("ശരി: {items}.", "ഒന്ന് നോക്കി Save അമർത്തുക."),
    "hi": ("ठीक है: {items}.", "देखकर Save दबाएँ."),
}


def fallback_line(items: list[Item], user_text: str) -> str:
    """A short line naming every item, in the sender's language, from the
    save arguments alone."""
    if _ML.search(user_text or ""):
        lang = "ml"
    elif _HI.search(user_text or ""):
        lang = "hi"
    elif is_manglish(user_text or ""):
        lang = "manglish"
    else:
        lang = "en"
    lead, ask = _LINES[lang]
    return f"{lead.format(items=', '.join(item.label for item in items))} {ask}"
