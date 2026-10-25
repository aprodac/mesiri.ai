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


def without_undo_prompt(text: str) -> str:
    """``text`` without the sentences about UNDO. Nothing is kept before the
    Save tap, so there is nothing to undo (request 114)."""
    kept = [s for s in sentences(text) if not re.search(r"\bundo\b", s, re.IGNORECASE)]
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


def without_manglish(text: str, words: frozenset[str]) -> str:
    """``text`` without the sentences that hold a Manglish word; the last
    resort for a reply that must be plain English (request 89)."""
    kept = [s for s in sentences(text) if not manglish_word_count(s, words)]
    return re.sub(r"\n{3,}", "\n\n", "".join(kept)).strip()


# -- sentences that belong to nothing ---------------------------------------------

#: Filler seen on 22 Oct: "Nale nokkam.", "Verenthenkilum ariyamo?", "Ethra steel
#: venam ennu paranjal record cheyyam.", and the chatbot closers.
_FILLER = re.compile(
    r"\bnale\s+nokk\w*|\bvere\s*enthenkilum\b|\bverenthenkilum\b|\bpara[nj]+al\b.*\brecord\b"
    r"|\banything else\b|\blet me know if\b|\bis there anything\b|\bhow can i help\b|\bhappy to help\b"
    r"|\bshall i (?:save|record|note)\b|\bsave cheyyamo\b",
    re.IGNORECASE,
)
#: A human touch is allowed without a source: it answers the feeling, not a fact.
_TOUCH = re.compile(
    r"\b(?:ayyo|sorry|oh no|unlucky|alas|pity|nice|great|good|well done|got it|right|sheri|sari|ok|okay)\b"
    r"|അയ്യോ|ക്ഷമിക്കണം|നന്നായി|ശരി|अफ़सोस|ठीक",
    re.IGNORECASE,
)
_CONTENT = re.compile(r"[^\W\d_]{4,}")


def _stems(text: str) -> set[str]:
    return {w[:4] for w in _CONTENT.findall((text or "").casefold())}


def without_stray_sentences(text: str, grounds: list[str]) -> str:
    """``text`` without the sentences tied to nothing (request 89): a sentence
    stays when it shares a word with ``grounds`` (the sender's message, the
    tool results and what the tools were given), carries a figure, asks to tap
    Save, is a short human touch ("Ayyo", "Sorry to hear that"), or has no
    word of substance. Known filler goes whatever it shares. Never empties a
    reply: with nothing left, ``text`` stands."""
    known = _stems(" ".join(grounds))
    kept = []
    for sentence in sentences(text):
        body = sentence.strip()
        if not body:
            kept.append(sentence)
            continue
        if _FILLER.search(body):
            continue
        stems = _stems(body)
        tied = (
            not stems
            or stems & known
            or re.search(r"\d", body)
            or asks_to_tap_save(body)
            or _TOUCH.search(body)
        )
        if tied:
            kept.append(sentence)
    result = re.sub(r"\n{3,}", "\n\n", "".join(kept)).strip()
    return result or text


# -- promises to ask the engineer ------------------------------------------------

_ENGINEER_WORD = re.compile(r"engin|\bengg?\b|എഞ്ചിനീ|എൻജിനീ|ഇഞ്ചിനീ|इंजीनियर|इंजिनियर", re.IGNORECASE)
_PASS_ON_WORD = re.compile(
    r"\b(?:ask|asked|asking|pass|passed|passing|forward\w*|send|sent|tell|told|inform\w*|check with"
    r"|chodikk\w*|chodich\w*|chodhikk\w*|ariyikk\w*|ariyich\w*|parayam|paranj\w*)\b"
    r"|ചോദിക്ക|ചോദിച്ച|അറിയിക്ക|അറിയിച്ച|പറയാം|പറഞ്ഞ|पूछ|बता|भेज",
    re.IGNORECASE,
)


def promises_engineer(sentence: str) -> bool:
    """A sentence saying the question goes (or went) to their engineer ("I'll
    ask your engineer", "engineer-inodu chodikkam"). An offer that asks ("Shall
    I ask your engineer?") is no promise."""
    return bool(
        "?" not in sentence and _ENGINEER_WORD.search(sentence) and _PASS_ON_WORD.search(sentence)
    )


def without_engineer_promise(text: str) -> str:
    """``text`` without the sentences saying a question was passed to their
    engineer, for a reply where nothing was (WA-52: 23 Oct "I'll ask your
    engineer" went out for a stock question the records answered)."""
    kept = [s for s in sentences(text) if not promises_engineer(s)]
    return re.sub(r"\n{3,}", "\n\n", "".join(kept)).strip()


_DPR_READY = re.compile(
    r"^(?:The DPR for (?P<day>.+?)|Today's DPR)(?P<code> \([^)]*\))? attached\.(?P<note> Not confirmed yet\.)?$"
)


def dpr_caption(answer: str, language: str | None) -> str | None:
    """Request 94: the "report attached" line of the DPR lookup in the language
    of the message ("22 Oct 2026-inte DPR ithaa."), decided in code so the
    caption never depends on the model rewriting it. None when ``answer`` is
    another kind of line or the language has no wording here."""
    found = _DPR_READY.match((answer or "").strip())
    if found is None or language not in ("manglish", "malayalam"):
        return None
    day, code, note = found.group("day"), found.group("code") or "", bool(found.group("note"))
    if language == "manglish":
        head = f"{day}-inte DPR" if day else "Innathe DPR"
        return f"{head}{code} ithaa." + (" Confirm cheythittilla." if note else "")
    head = f"{day}-ലെ DPR" if day else "ഇന്നത്തെ DPR"
    return f"{head}{code} ഇതാ." + (" ഇതുവരെ സ്ഥിരീകരിച്ചിട്ടില്ല." if note else "")
