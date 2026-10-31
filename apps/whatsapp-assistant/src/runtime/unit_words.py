"""One table of the words sites use for a unit (request 164).

"100 chaakku cement" asked "How many bags is 100 chaakku?" because the units
list only knew English spellings (the Malayalam script ചാക്ക് was the single
local word in it). Local words, Malayalam / Hindi script and the common
misspellings are listed HERE, once, and every resolver goes through
``canonical_unit``: the material resolver (``MaterialCatalogQuery.resolve_unit``),
a typed answer to a unit question (``draft_answer``) and labour.

Adding a word is one entry in ``_WORDS``. Pure; no I/O.
"""

from __future__ import annotations

import re

#: canonical unit code (as the units list names it) -> every way it is said.
_WORDS: dict[str, tuple[str, ...]] = {
    "bags": (
        "bag", "bags", "bagu", "bagg", "sack", "sacks", "chaak", "chaakku", "chakku", "chakk", "chaku",
        "chakkinte", "chaak", "chaaku", "chakkum", "bori", "boree", "boras", "ചാക്ക്", "ചാക്", "ചാക്കു",
        "ചാക്കിന്റെ", "बोरी", "बोरा", "बैग", "थैला",
    ),
    "load": ("load", "loads", "lod", "lode", "lood", "ലോഡ്", "ലോഡ", "लोड"),
    "ft": ("ft", "feet", "foot", "adi", "aadi", "അടി", "फ़ुट", "फुट"),
    "kg": ("kg", "kgs", "kilo", "kilos", "kilogram", "kilograms", "കിലോ", "കിലോഗ്രാം", "किलो"),
    "nos": ("no", "nos", "number", "numbers", "ennam", "enam", "എണ്ണം", "नग", "संख्या"),
    "tons": ("ton", "tons", "tonne", "tonnes", "tonn", "ടൺ", "टन"),
}


def fold(text: object) -> str:
    """"Chaakku." / " ചാക്ക് " -> comparable form: lower case, letters and digits only."""
    return re.sub(r"[^\w]+", "", str(text or "").casefold().replace("_", ""))


_INDEX: dict[str, str] = {fold(word): code for code, words in _WORDS.items() for word in words}


def canonical_unit(text: object) -> str | None:
    """The unit code a site word means ("chaakku" -> "bags"), or None when it
    is not a word in the table (then the units list decides, as before)."""
    return _INDEX.get(fold(text))


def words_for(code: object) -> frozenset[str]:
    """Every folded spelling of a unit code or any of its words ("bag" -> all of bags)."""
    canon = canonical_unit(code) or fold(code)
    return frozenset(w for w, c in _INDEX.items() if c == canon) | {fold(code)}
