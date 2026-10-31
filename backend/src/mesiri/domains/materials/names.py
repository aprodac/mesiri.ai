"""Material names: always English, in Latin letters (request 165, Ilan 31 Oct).

A catalogue name is what records, DPRs, PDFs and the dashboard show. It is never
Malayalam script ("ചെങ്കല്ല്"): the word a person said is kept beside the material
as an alias (``material_aliases``), so it still finds the material next time.

One rule for every path that creates or renames a material: the REST API, the
repository, the WhatsApp add.
"""

from __future__ import annotations

import unicodedata

__all__ = ["MaterialNameError", "alias_key", "is_latin_name", "require_latin_name"]

# Malayalam chillu letters, as base letter + virama: "സിമൻറ്" and "സിമന്റ്" are one word.
_CHILLU = str.maketrans({"ൻ": "ന്", "ർ": "ര്", "ൽ": "ല്", "ൾ": "ള്", "ൺ": "ണ്"})
_JOINERS = dict.fromkeys(map(ord, "‌‍"))


class MaterialNameError(ValueError):
    """A material name that is not English in Latin letters."""


def is_latin_name(name: str) -> bool:
    """True when every letter of ``name`` is a Latin letter (digits, spaces and
    signs such as "12mm", "M-sand", "20 mm" are fine)."""
    for char in name:
        if char.isalpha() and not unicodedata.name(char, "").startswith("LATIN"):
            return False
    return True


def require_latin_name(name: str) -> str:
    """The stripped name, or ``MaterialNameError`` when it has non-Latin letters."""
    clean = (name or "").strip()
    if not is_latin_name(clean):
        raise MaterialNameError(
            "Material names are saved in English, in Latin letters "
            "(for example 'Laterite stone', not 'ചെങ്കല്ല്'). "
            "The local word can be added as an alias."
        )
    return clean


def alias_key(text: str) -> str:
    """The form a word is matched by: case-folded, one space, chillu and
    joiner variants of Malayalam spelling made equal."""
    folded = unicodedata.normalize("NFC", text or "").translate(_JOINERS).translate(_CHILLU)
    return " ".join(folded.casefold().split())
