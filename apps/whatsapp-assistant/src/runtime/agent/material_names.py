"""The English catalogue name for a material said in any language (request 165).

A material is always SAVED in English, in Latin letters ("Laterite stone", never
"ചെങ്കല്ല്"). The word the person used is kept beside it as an alias, so it still
finds the material next time. Where the English name comes from, in order, with no
extra model call on the reply path:

1. the local-word table below (``LOCAL_WORDS``), one entry per word;
2. ``name_en`` the model passed in the tool call (it is already reading the message);
3. otherwise a transliteration of the Malayalam letters, and the card asks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from mesiri.domains.materials.names import alias_key, is_latin_name

__all__ = ["EnglishName", "english_name", "local_word", "to_latin", "transliterate"]

#: Local word (Malayalam script or Manglish) -> the English catalogue name. A new
#: word is one line here. ചെങ്കല്ല് (laterite) and കല്ല് (stone) are different materials.
LOCAL_WORDS: dict[str, str] = {
    # cement and sand
    "സിമന്റ്": "Cement", "സിമൻറ്": "Cement", "siment": "Cement", "simentu": "Cement",
    "എംസാന്റ്": "M sand", "എം സാൻഡ്": "M sand", "emsand": "M sand", "m sand": "M sand", "msand": "M sand",
    "പിസാന്റ്": "P sand", "psand": "P sand", "p sand": "P sand",
    "മണൽ": "River sand", "manal": "River sand", "mannu": "River sand",
    # stone and brick
    "ചെങ്കല്ല്": "Laterite stone", "ചെങ്കല്ലു": "Laterite stone", "chenkallu": "Laterite stone",
    "chenkal": "Laterite stone", "chenkallu stone": "Laterite stone",
    "കല്ല്": "Stone", "kallu": "Stone", "kal": "Stone",
    "കരിങ്കല്ല്": "Granite stone", "karinkallu": "Granite stone", "karinkal": "Granite stone",
    "ഇഷ്ടിക": "Bricks", "ishtika": "Bricks", "ishtikka": "Bricks", "ishtik": "Bricks",
    "മെറ്റൽ": "Aggregate (metal)", "mettal": "Aggregate (metal)",
    # steel
    "കമ്പി": "TMT steel bars", "kambi": "TMT steel bars",
}
_LOCAL = {alias_key(word): english for word, english in LOCAL_WORDS.items()}


def local_word(said: str) -> str | None:
    """The English name of a known local word, else None."""
    return _LOCAL.get(alias_key(said))


# ISO-15919-like, plain letters only (no diacritics): good enough to read back
# and to ask "Name it 'Chenkallu'?".
_VOWELS = {
    "അ": "a", "ആ": "aa", "ഇ": "i", "ഈ": "ee", "ഉ": "u", "ഊ": "oo", "ഋ": "ru", "എ": "e", "ഏ": "ee",
    "ഐ": "ai", "ഒ": "o", "ഓ": "o", "ഔ": "au",
}
_SIGNS = {
    "ാ": "aa", "ി": "i", "ീ": "ee", "ു": "u", "ൂ": "oo", "ൃ": "ru", "െ": "e", "േ": "ee", "ൈ": "ai",
    "ൊ": "o", "ോ": "o", "ൗ": "au",
}
_CONSONANTS = {
    "ക": "k", "ഖ": "kh", "ഗ": "g", "ഘ": "gh", "ങ": "ng", "ച": "ch", "ഛ": "chh", "ജ": "j", "ഝ": "jh",
    "ഞ": "nj", "ട": "t", "ഠ": "th", "ഡ": "d", "ഢ": "dh", "ണ": "n", "ത": "th", "ഥ": "th", "ദ": "d",
    "ധ": "dh", "ന": "n", "പ": "p", "ഫ": "f", "ബ": "b", "ഭ": "bh", "മ": "m", "യ": "y", "ര": "r",
    "ല": "l", "വ": "v", "ശ": "sh", "ഷ": "sh", "സ": "s", "ഹ": "h", "ള": "l", "ഴ": "zh", "റ": "r",
}
_VIRAMA = "്"
_ANUSVARA = {"ം": "m", "ഃ": "h"}
_CHILLU = {"ൻ": "n", "ർ": "r", "ൽ": "l", "ൾ": "l", "ൺ": "n"}


def transliterate(text: str) -> str:
    """Malayalam letters -> Latin letters; anything else is kept as it is."""
    out: list[str] = []
    chars = list(text)
    for i, char in enumerate(chars):
        nxt = chars[i + 1] if i + 1 < len(chars) else ""
        if char in _CONSONANTS:
            out.append(_CONSONANTS[char])
            if nxt not in _SIGNS and nxt != _VIRAMA:
                out.append("a")  # the inherent vowel: ക = ka
        elif char == _VIRAMA:
            if not re.match(r"[\u0d00-\u0d7f]", nxt):
                out.append("u")  # a word ending in a bare consonant: കല്ല് = kallu
        elif char in _VOWELS:
            out.append(_VOWELS[char])
        elif char in _SIGNS:
            out.append(_SIGNS[char])
        elif char in _ANUSVARA:
            out.append(_ANUSVARA[char])
        elif char in _CHILLU:
            out.append(_CHILLU[char])
        elif char in ("\u200c", "\u200d"):
            continue
        else:
            out.append(char)
    return "".join(out).replace("nr", "nt")


_DEVA_VOWELS = {"अ": "a", "आ": "a", "इ": "i", "ई": "i", "उ": "u", "ऊ": "u", "ऋ": "ri", "ए": "e", "ऐ": "ai",
                "ओ": "o", "औ": "au", "ऑ": "o"}
_DEVA_SIGNS = {"ा": "a", "ि": "i", "ी": "i", "ु": "u", "ू": "u", "ृ": "ri", "े": "e", "ै": "ai", "ो": "o",
               "ौ": "au", "ॉ": "o", "ॅ": "e"}
_DEVA_CONSONANTS = {
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "ng", "च": "ch", "छ": "chh", "ज": "j", "झ": "jh", "ञ": "n",
    "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n", "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n",
    "प": "p", "फ": "f", "ब": "b", "भ": "bh", "म": "m", "य": "y", "र": "r", "ल": "l", "व": "v", "श": "sh",
    "ष": "sh", "स": "s", "ह": "h",
}
_DEVA_VIRAMA = "\u094d"
_DEVA_NASAL = {"ं": "n", "ँ": "n", "ः": "h"}
_DEVA_DIGITS = {c: str(i) for i, c in enumerate("०१२३४५६७८९")}
_SCRIPT = re.compile(r"[\u0900-\u097f\u0d00-\u0d7f]")
_DEVA = re.compile(r"[\u0900-\u097f]")


def _devanagari(text: str) -> str:
    """Devanagari -> Latin, Hindi style: the inherent "a" is dropped at the end of a word (बता = bata)."""
    out: list[str] = []
    chars = list(text)
    for i, char in enumerate(chars):
        nxt = chars[i + 1] if i + 1 < len(chars) else ""
        if char in _DEVA_CONSONANTS:
            out.append(_DEVA_CONSONANTS[char])
            if nxt not in _DEVA_SIGNS and nxt != _DEVA_VIRAMA and nxt != "\u093c" and _DEVA.match(nxt or " "):
                out.append("a")
        elif char in _DEVA_VOWELS:
            out.append(_DEVA_VOWELS[char])
        elif char in _DEVA_SIGNS:
            out.append(_DEVA_SIGNS[char])
        elif char in _DEVA_NASAL:
            out.append(_DEVA_NASAL[char])
        elif char in _DEVA_DIGITS:
            out.append(_DEVA_DIGITS[char])
        elif char == "\u0964":
            out.append(".")
        elif char in (_DEVA_VIRAMA, "\u093c", "\u200c", "\u200d"):
            continue
        else:
            out.append(char)
    return "".join(out)


def to_latin(text: str) -> str:
    """Every Malayalam or Devanagari word in ``text`` in Latin letters; everything else (Latin words, names,
    numbers, emoji, punctuation) is kept exactly as it is. Text with no such letter is returned unchanged."""
    if not text or not _SCRIPT.search(text):
        return text
    return _devanagari(transliterate(text))


def _tidy(name: str) -> str:
    """One space, first letter capital, the rest as given ("Laterite stone", "M sand")."""
    words = " ".join(name.split())
    return words[:1].upper() + words[1:]


@dataclass(frozen=True, slots=True)
class EnglishName:
    #: What is stored: Latin letters only.
    name: str
    #: The person's word, when it differs (kept as an alias).
    said: str
    #: False when the English was a guess (a transliteration): the card asks.
    sure: bool


def english_name(said: str, name_en: object = None) -> EnglishName:
    """The English catalogue name for ``said``; see the module docstring for the order."""
    said = " ".join(str(said or "").split())
    known = local_word(said)
    if known:
        return EnglishName(known, said, True)
    offered = " ".join(str(name_en or "").split())
    if offered and is_latin_name(offered):
        return EnglishName(_tidy(offered), said, True)
    if said and is_latin_name(said):
        return EnglishName(_tidy(said), said, True)
    guess = _tidy(transliterate(said))
    if not is_latin_name(guess) or not guess:
        guess = "Material"
    return EnglishName(guess, said, False)
