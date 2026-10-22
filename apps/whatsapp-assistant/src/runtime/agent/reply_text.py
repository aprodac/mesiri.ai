"""Checks on the words of the agent's reply (request 88).

Pure text functions: where a sentence ends (an abbreviation like "e.g." does
not end one), how to shorten a reply that is over the hard cap, and the script
and language checks the runner makes before a reply goes out. Nothing here
reads a worker's message; it only looks at what the model wrote.
"""

from __future__ import annotations

import re

#: Words whose full stop is part of the word, lowercase, with the dot. A
#: sentence never ends after one of these.
ABBREVIATIONS = frozenset(
    {
        "e.g.", "i.e.", "etc.", "vs.", "viz.", "approx.", "est.", "incl.", "no.", "nos.", "qty.",
        "pcs.", "rs.", "mr.", "mrs.", "ms.", "dr.", "st.", "sq.", "ft.", "cu.", "mt.", "dept.",
    }
)
#: "e.g." / "i.e." / "a.m." / "p.m.": letters each followed by a dot.
_INITIALISM = re.compile(r"(?:[^\W\d_]\.){2,}$")
_ENDERS = "!?।"


def _word_before(text: str, dot: int) -> str:
    start = dot
    while start > 0 and not text[start - 1].isspace():
        start -= 1
    return text[start : dot + 1].lower().lstrip("(\"'")


def _ends_sentence(text: str, first: int, last: int) -> bool:
    """Whether the run of dots ``text[first:last + 1]`` ends a sentence."""
    after = text[last + 1] if last + 1 < len(text) else None
    if after is not None and not after.isspace():
        return False  # "12.5", "Rs.4500", the dot inside "e.g"
    if first != last:
        return True  # "..." before a space or the end
    word = _word_before(text, first)
    return word not in ABBREVIATIONS and not _INITIALISM.search(word)


def sentences(text: str) -> list[str]:
    """``text`` cut into sentences (a line break also ends one); the pieces
    join back to ``text`` exactly. A full stop inside a number, after an
    abbreviation ("e.g.", "Rs.", "etc.") or in a dotted initialism does not
    end a sentence."""
    out: list[str] = []
    start = 0
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        end = -1
        if ch == "\n":
            end = i
        elif ch in _ENDERS:
            end = i
            while end + 1 < n and text[end + 1] in _ENDERS + ".":
                end += 1
        elif ch == ".":
            last = i
            while last + 1 < n and text[last + 1] == ".":
                last += 1
            if _ends_sentence(text, i, last):
                end = last
            i = last
        if end >= 0:
            out.append(text[start : end + 1])
            start = i = end + 1
            continue
        i += 1
    if start < n:
        out.append(text[start:])
    return out


def trim_at_sentence(text: str, limit: int) -> str:
    """``text`` as it is when it fits ``limit``; otherwise its leading
    sentences that fit, so it ends at a real sentence end. One sentence longer
    than the limit is cut at a word with an ellipsis, the only cut mid-sentence."""
    text = text.rstrip()
    if len(text) <= limit:
        return text
    kept = ""
    for sentence in sentences(text):
        if len(kept) + len(sentence) > limit:
            break
        kept += sentence
    kept = kept.rstrip()
    if kept:
        return kept
    cut = text[: max(limit - 1, 0)]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:-") + "…"


# -- Save prompts ------------------------------------------------------------

#: A sentence that asks the sender to tap Save, in the languages the sites write in.
_SAVE_WORD = re.compile(r"\bsave\b|സേവ്|सेव", re.IGNORECASE)
_TAP_WORD = re.compile(
    r"\b(?:tap|press|click|cheyyu|cheyyuka|cheyyoo|cheyyane|amarthu|amarthuka)\b|അമർത്ത|ടാപ്|दबा|टैप|क्लिक",
    re.IGNORECASE,
)


def asks_to_tap_save(sentence: str) -> bool:
    return bool(_SAVE_WORD.search(sentence) and _TAP_WORD.search(sentence))


def without_save_prompt(text: str) -> str:
    """``text`` without the sentences asking to tap Save. Only a reply with a
    Save card under it may ask that (22 Oct: a stock question ended with
    "Save tap cheyyu" and nothing to tap)."""
    kept = [s for s in sentences(text) if not asks_to_tap_save(s)]
    return re.sub(r"\n{3,}", "\n\n", "".join(kept)).strip()


# -- scripts and language ------------------------------------------------------

_NATIVE = re.compile(r"[ऀ-ൿ]")  # Devanagari .. Malayalam
_LATIN = re.compile(r"[A-Za-z]")
_TOKEN = re.compile(r"[^\W\d_]+(?:[-'’][^\W\d_]+)*", re.UNICODE)


def has_native_script(text: str) -> bool:
    return bool(_NATIVE.search(text or ""))


def mixed_script_words(text: str) -> list[str]:
    """Words written in two scripts at once ("innaleത്തെ": Latin letters
    running into Malayalam), which no one can read as one word."""
    found = []
    for match in re.finditer(r"[^\s]+", text or ""):
        word = match.group(0)
        if _LATIN.search(word) and _NATIVE.search(word):
            found.append(word)
    return found


def without_native_script(text: str) -> str:
    """``text`` without the sentences that carry native-script letters; the
    last resort for a reply that must be in English letters only."""
    kept = [s for s in sentences(text) if not _NATIVE.search(s)]
    return re.sub(r"\n{3,}", "\n\n", "".join(kept)).strip()


#: Words of the Manglish list that an English sentence uses too ("Reply UNDO").
_ENGLISH_HOMOGRAPHS = frozenset({"undo"})


def manglish_word_count(text: str, words: frozenset[str]) -> int:
    """How many distinct Manglish words ``text`` holds (``words`` is the
    prompt module's list); homographs of English words do not count."""
    found = set(re.findall(r"[a-z]+", (text or "").lower()))
    return len((found & words) - _ENGLISH_HOMOGRAPHS)


def is_clearly_manglish(text: str, words: frozenset[str]) -> bool:
    """A reply that is Manglish beyond doubt: two or more of its words are."""
    return manglish_word_count(text, words) >= 2
