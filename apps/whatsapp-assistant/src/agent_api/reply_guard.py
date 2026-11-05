"""WA-193: two basics held by code, not only by SOP.md (docs/architecture/assistant-v3.md, "The basics").

Basic 3: a reply never says something was saved when nothing was. Basic 9: a reply never shows an id or an API error.
Both look only at the model's words; what the code itself draws (the ready list, the "Saved" line) is true already.
"""

from __future__ import annotations

import re

from runtime.agent.reply_text import sentences

#: "saved", "save cheythu", "daal diya", "സേവ് ചെയ്തു", "सेव कर दिया": the SOP's words for a thing already kept.
#: WA-195: "noted" / "stored" / "made a note" / "kurichu vechu" / "note kar liya" say the same thing ("I have noted
#: the information about his increased rate", with no tool called and nothing kept). "Updated" is not here: it is
#: how the model says it changed a line on the ready list, which is true.
_SAVED = re.compile(
    r"\b(?:saved|recorded|logged|added|entered|noted|stored)\b"
    r"|\b(?:made|taken|took|kept)\s+(?:a\s+)?(?:note|record)\b"
    r"|\b(?:save|record|note|add|entry)\s*(?:cheythu|cheythittund\w*|chethu|aakki\w*|aayi)\b"
    r"|\brekhappeduthi\w*|\bcherthu\b|\bdaal\s*(?:diya|diye|di)\b"
    r"|\b(?:kurichu|ezhuthi)\s*(?:vechu|vachu|vechittund\w*|vachittund\w*)\b"
    r"|\b(?:save|record|add|darj|note)\s*(?:kar\s*)?(?:diya|liya|kiya|ho\s*gaya)\b"
    r"|സേവ്\s*(?:ചെയ്തു|ചെയ്തിട്ടുണ്ട്|ആയി)|രേഖപ്പെടുത്തി|ചേർത്തു|കുറിച്ചു\s*വെച്ചു|കുറിച്ചുവച്ചു|എഴുതി\s*വെച്ചു"
    r"|(?:सेव|दर्ज|रिकॉर्ड|नोट)\s*(?:कर\s*)?(?:दिया|लिया|किया|हो\s*गया)",
    re.IGNORECASE,
)
#: The same words that say the opposite: not yet, once they tap, or about an earlier day ("saved an hour ago").
_NOT_A_CLAIM = re.compile(
    r"\b(?:not|nothing|never|no|yet|will|would|should|can|once|when|after|until|till|if|to\s+be|to\s+get|gets?"
    r"|ago|yesterday|earlier|already|illa|cheythittilla|nahi|nahin)\b|n't\b|ില്ല|नहीं|\?",
    re.IGNORECASE,
)
_CLAUSE = re.compile(r"[^,;]*(?:[,;]\s*|$)")


def claims_saved(text: str | None) -> bool:
    """The reply says, as a fact of this turn, that something is saved."""
    return any(_claims(part) for part in sentences(text or "") if part)


def _claims(sentence: str) -> bool:
    return bool(_SAVED.search(sentence)) and not _NOT_A_CLAIM.search(sentence)


#: WA-199 (basic 10, never a dead end): the reply says Mesiri cannot do it. First person or Mesiri ("I can't",
#: "Mesiri cannot", "I'm unable to"), the Manglish / Malayalam "it can't be done" ("pattilla", "kazhiyilla",
#: "sadhikkilla"), and the Hindi "nahi kar sakta". Not a question ("can't find it?").
_CANNOT = re.compile(
    r"\b(?:i|we|mesiri)\s+(?:can\s*not|can't|can’t|am\s+unable|'m\s+unable|am\s+not\s+able|'m\s+not\s+able"
    r"|do\s+not\s+have\s+(?:a\s+)?(?:way|tool|option)|don't\s+have\s+(?:a\s+)?(?:way|tool|option))\b"
    r"|\bi[’']m\s+(?:unable|not\s+able)\b"
    r"|\bnot\s+(?:possible|supported)\s+(?:here|in\s+whatsapp|through\s+whatsapp|for\s+me|yet)\b"
    r"|\b(?:patt(?:illa|ula|unnilla)|kazhiyilla|kazhiyunnilla|sadhikkilla|saadhikkilla)\b"
    r"|\bnahi[n]?\s+kar\s+(?:sakta|sakti|sakte|paunga|paungi)\b"
    r"|പറ്റില്ല|പറ്റുന്നില്ല|കഴിയില്ല|സാധിക്കില്ല|नहीं\s+कर\s+(?:सकता|सकती|सकते|पाऊंगा|पाऊंगी)",
    re.IGNORECASE,
)


def claims_cannot(text: str | None) -> bool:
    """WA-199: the reply says, as a statement, that Mesiri cannot do what was asked."""
    return any(_CANNOT.search(part) and not part.rstrip().endswith("?") for part in sentences(text or "") if part)


def without_saved_claims(text: str) -> str:
    """``text`` without the claim: "50 bag cement vannu, save cheythu." keeps "50 bag cement vannu."."""
    kept = [_cut(part) if _claims(part) else part for part in sentences(text or "") if part]
    return re.sub(r"\n{3,}", "\n\n", "".join(kept)).strip()


def _cut(sentence: str) -> str:
    before: list[str] = []
    for clause in (c for c in _CLAUSE.findall(sentence) if c):
        if _SAVED.search(clause):
            break
        before.append(clause)
    body = "".join(before).rstrip().rstrip(",;").rstrip()
    if not body:
        return ""
    end = re.search(r"[.!?।]+\s*$|\n$", sentence)
    return body + (end.group(0) if end else "")


#: [265]: a sentence that is only an apology for a slip ("My bad!", "Sorry, I missed that date.", "Apologies for the
#: oversight."): what a corrective retry from the code drew out of the model, about a mistake the person never saw.
_BARE_APOLOGY = re.compile(
    r"^\s*(?:(?:my\s+bad|oops|sorry|apologies|my\s+apologies|my\s+mistake)[\s!.,]*)+$"
    r"|^\s*(?:my\s+bad|oops|(?:so\s+)?sorry|apologies|i\s+apologi[sz]e|my\s+apologies|my\s+mistake)\b[^0-9\n:]{0,40}"
    r"\b(?:missed|forgot|overlooked|oversight|mistake|confusion|got\s+(?:that|it)\s+wrong)\b[^0-9\n:]{0,25}[.!]?\s*$",
    re.IGNORECASE,
)


def without_apology(text: str) -> str:
    """[265]: ``text`` without sentences that are only an apology; a sentence with an action or a figure stays."""
    kept = [part for part in sentences(text or "") if part and not _BARE_APOLOGY.match(part.strip())]
    return re.sub(r"\n{3,}", "\n\n", "".join(kept)).strip()


_URL = re.compile(r"(https?://\S+)")
_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
#: An id with what introduces it: "(id: 3fa8…)", "`3fa8…`". Links keep theirs: the dashboard needs it.
_ID = re.compile(rf"[(\[]?\s*(?:\b\w*\s?id\b\s*[:=]?\s*)?[`'\"]?\b{_UUID}\b[`'\"]?(?:\s*[)\]])?", re.IGNORECASE)
_TRACE_ID = re.compile(r"\bcor_[0-9a-f]{8,}\b", re.IGNORECASE)
#: agent_api.materials.NEW: the code's mark for a material being added.
_NEW_MARK = re.compile(r"\bnew:(?=\S)")
#: What only an API error or the code contains. "422" alone is not here: it can be a real number on a site.
_API_ERROR = re.compile(
    r"\b[a-z]+_id\b|\bHTTP\s*\d{3}\b|\b(?:400|401|403|404|409|422|424|500|502|503)\s+(?:error|bad|not found|forbidden"
    r"|conflict|unprocessable|internal)|\bTraceback\b|\bvalidation error\b|\bUnprocessable\b|\bInternal Server Error\b"
    r"|\bField required\b|\bis not a valid\b|[\"']detail[\"']\s*:",
    re.IGNORECASE,
)


def without_ids(text: str) -> str:
    """``text`` without ids and code marks; a link stays whole."""
    pieces = _URL.split(text or "")
    for i in range(0, len(pieces), 2):  # the odd pieces are the links
        piece = _NEW_MARK.sub("", _TRACE_ID.sub("", _ID.sub("", pieces[i])))
        piece = re.sub(r"[ \t]+([.,;:!?])", r"\1", piece)
        pieces[i] = re.sub(r"[ \t]{2,}", " ", piece)
    return "".join(pieces).strip()


def without_internals(text: str, tool_names: frozenset[str] | set[str] = frozenset()) -> str:
    """``text`` without ids, without any sentence that is an API error, and without tool names ([249]: "(record\\_receipt)"
    in a "what can Mesiri do" answer): the person cannot act on any of them."""
    kept = [part for part in sentences(text or "") if part and not _API_ERROR.search(_URL.sub("", part))]
    return without_tool_names(without_ids("".join(kept)), tool_names)


def without_tool_names(text: str, tool_names: frozenset[str] | set[str]) -> str:
    """[249]: a tool's snake_case name (also markdown-escaped, ``record\\_receipt``) is cut, with the brackets or
    backticks around it; a sentence that only had the name in brackets reads on."""
    if not text or not tool_names:
        return text
    names = sorted((n for n in tool_names if "_" in n), key=len, reverse=True)
    if not names:
        return text
    alternation = "|".join(re.escape(n).replace("_", r"\\?_") for n in names)
    text = re.sub(rf"\s*\((?:\s*`?(?:{alternation})`?\s*,?\s*)+\)", "", text)
    text = re.sub(rf"`?\b(?:{alternation})\b`?", "", text)
    return re.sub(r"[ \t]{2,}", " ", re.sub(r" +([,.;:])", r"\1", text))


#: [247] Words too common in tool descriptions to say what a question is about.
_PLAIN = frozenset("this that with from have what when where which done work site sites into your their them then also "
                   "other about mesiri tool tools reply please project projects answer answers questions".split())


def read_tools_for(topic: str, tools: dict[str, object]) -> list[str]:
    """[247] The read tools (GET) whose name or description shares a word with ``topic``: the model's own words for what it
    was asked (its tell_the_team ``about``, its reply), matched against the tools it has. No list of topic words here:
    a new route is found by its own description. Empty when nothing matches (then the guard stays out)."""
    stems = {w[:5] for w in re.findall(r"[a-z]{4,}", (topic or "").casefold()) if w not in _PLAIN}
    found: list[str] = []
    for name, tool in tools.items():
        if getattr(tool, "is_write", True):
            continue
        words = re.findall(r"[a-z]{4,}", f"{name.replace('_', ' ')} {tool.spec.description}".casefold())  # type: ignore[attr-defined]
        if stems & {w[:5] for w in words if w not in _PLAIN}:
            found.append(name)
    return found


_FIGURE = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)?(?![\w.]*\d)")


def _figures(text: str) -> set[str]:
    clean = _URL.sub(" ", text or "")
    return {f.replace(",", ".").lstrip("0") or "0" for f in _FIGURE.findall(clean)}


def unbacked_figures(reply: str | None, said: str, facts: str) -> list[str]:
    """[260] (5 Nov: "how many workers are on site now?" got "10 helpers", read from a card they had cancelled, and
    the next answer said no attendance today): the figures in a reply that are neither in what the person said nor
    in the records the turn started from. Used only when no tool was called: a figure with no source came from the
    conversation (lines that may have been cancelled or never saved) or was made up. Single digits are left out
    (counting words, list numbers)."""
    backed = _figures(said) | _figures(facts)
    return [f for f in sorted(_figures(reply or "")) if len(f) > 1 and f not in backed]
