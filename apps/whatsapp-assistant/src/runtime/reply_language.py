"""Conversational replies in the sender's own language (WA-11).

Every reply Mesiri wrote was fixed English text, while the understanding
step already knew the sender spoke Malayalam (or Hindi, Tamil...). A field
supervisor who sends a voice note in Malayalam and gets English back stops
using the product. And small talk ("how are you?") was answered with a
product description, which read as robotic.

Two pieces:

- ``UserLanguageStore`` remembers the language each sender last spoke
  (Redis, 30 days), so even replies that never touch the AI -- the instant
  answer to a bare "hi" -- come back in that language.
- ``ReplyComposer`` turns one of Mesiri's conversational replies (greetings,
  small talk, "what can you do?", "I didn't follow") into the sender's
  language with one AI call, and may open with a few words answering their
  small talk. It must not add facts, offers or capabilities; a reply that
  fails the call, the time limit or the sanity checks goes out in English,
  exactly as before.

Scope, deliberately: only conversational replies. Workflow prompts,
confirmations and receipts carry exact quantities, names and amounts and
stay English for now -- translating those is a separate, riskier step.

Layering: runtime/, because it does I/O (one LLM call, Redis), the same
reason runtime/capability_help.py lives here.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from typing import Any, Protocol

from mesiri_ai.ports.generation import JsonGenerationProvider
from workflows.worker_promotion import wording

logger = logging.getLogger(__name__)

#: How long a sender's language is remembered without hearing from them.
_LANGUAGE_TTL_SECONDS = 30 * 24 * 3600

#: The reply goes out in English if composing takes longer than this -- a
#: late reply in the right language is worse than a prompt one in English.
_COMPOSE_TIMEOUT_SECONDS = 6.0

#: Composed replies kept in memory: the fixed greeting/overview texts repeat
#: constantly, so most conversational replies cost no AI call at all.
_CACHE_SIZE = 512

_ENGLISH = frozenset({"english", "en", "eng", "en-in", "en-us", "en-gb"})


def normalize_language(value: object) -> str | None:
    """The language as a name the model understands, or None for English /
    unknown (no change needed). Accepts what the understanding step returns:
    a common English name ("Malayalam") or a code ("ml")."""
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned or cleaned.lower() in _ENGLISH or cleaned.lower() in {"unknown", "none", "null"}:
        return None
    return cleaned[:40]


def normalize_script(value: object) -> str:
    """"latin" when the sender wrote in English letters, else "native" -- the
    default for absent / unknown values, which is how every reply behaved
    before the script was tracked."""
    if isinstance(value, str) and value.strip().lower() == "latin":
        return "latin"
    return "native"


def infer_script(language: object, text: object) -> str | None:
    """A fallback for when the understanding step did not report the script:
    "latin" when ``text`` is non-English yet written (almost) entirely in
    Latin letters -- Manglish -- else None (unknown)."""
    if normalize_language(language) is None or not isinstance(text, str):
        return None
    letters = [ch for ch in text if ch.isalpha()]
    if len(letters) < 3:
        return None
    latin = sum(1 for ch in letters if ord(ch) <= 0x024F)
    return "latin" if latin / len(letters) >= 0.9 else None


class _RedisLike(Protocol):
    def namespaced(self, *parts: str) -> str: ...
    async def set_json(self, key: str, value: Any, *, ttl_seconds: int | None = None) -> None: ...
    async def get_json(self, key: str) -> Any | None: ...


class UserLanguageStore:
    """The language each sender last spoke. Never raises: a Redis problem
    costs a reply in English, never the reply itself."""

    def __init__(self, redis: _RedisLike) -> None:
        self._redis = redis

    def _key(self, user_id: str) -> str:
        return self._redis.namespaced("reply_language", user_id)

    async def remember(
        self,
        *,
        user_id: str,
        detected_language: object,
        detected_script: object = None,
        text: object = None,
    ) -> None:
        """Store what the understanding step detected. English is stored too
        (as None) so someone who switches back to English gets English. The
        script is what the model reported, else inferred from ``text``; a
        sender who typed Manglish keeps getting Manglish back."""
        if not user_id or not isinstance(detected_language, str) or not detected_language.strip():
            return
        script = normalize_script(detected_script or infer_script(detected_language, text))
        try:
            await self._redis.set_json(
                self._key(user_id),
                {"language": normalize_language(detected_language), "script": script},
                ttl_seconds=_LANGUAGE_TTL_SECONDS,
            )
        except Exception:  # noqa: BLE001
            logger.warning("reply_language.remember_failed user=%s", user_id)

    async def get(self, *, user_id: str) -> str | None:
        return (await self.get_profile(user_id=user_id))[0]

    async def get_script(self, *, user_id: str) -> str:
        return (await self.get_profile(user_id=user_id))[1]

    async def get_profile(self, *, user_id: str) -> tuple[str | None, str]:
        """(language, script) -- script is "native" unless the sender types
        their language in English letters."""
        try:
            stored = await self._redis.get_json(self._key(user_id))
        except Exception:  # noqa: BLE001
            logger.warning("reply_language.lookup_failed user=%s", user_id)
            return None, "native"
        if isinstance(stored, dict):
            return normalize_language(stored.get("language")), normalize_script(stored.get("script"))
        return None, "native"


_SYSTEM_PROMPT = """You write WhatsApp replies for Mesiri, an assistant that construction site supervisors in India use to report their day.

You are given Mesiri's REPLY (in English), the LANGUAGE to write it in, the SCRIPT to write it in, and possibly the user's MESSAGE that it answers.

Rules:
0. SCRIPT "latin" means the user types LANGUAGE in English letters (for example Malayalam as "njan site il ethi"): write the reply in LANGUAGE using ONLY English/Roman letters, the same casual way they type -- never the language's own script. SCRIPT "native" means use LANGUAGE's own script.
1. Write the reply in LANGUAGE, the way people on a construction site in India actually speak and text it -- simple, warm, everyday words, not formal or literary. Common English work words (site, mason, helper, slab, cement, report) may stay in English if that is how people say them.
2. If the user's MESSAGE is a greeting or small talk ("hi", "how are you?", "what's up"), you may begin with at most one short, natural answer to it ("I'm good, thanks!") before the reply. Otherwise do not add an opening.
3. Do NOT add anything else: no new facts, offers, features, promises, questions or advice that are not in the REPLY. Keep its meaning, order and line breaks.
4. Keep exactly as they are: numbers, amounts, dates, names of people, projects and sites, the word "Mesiri", emoji, and anything inside “quotes” that the user is meant to send -- translate those example messages naturally so the user can copy them in their own language.
5. Keep it about as short as the REPLY.

If LANGUAGE is English, rule 2 still applies and the rest stays as written.

Output JSON only: {"text": "<the reply>"}
"""


class ReplyComposer:
    """Writes a conversational reply in the sender's language (see module
    docstring). ``compose`` never raises and never returns an empty reply."""

    def __init__(
        self,
        json_generation: JsonGenerationProvider,
        *,
        timeout_seconds: float = _COMPOSE_TIMEOUT_SECONDS,
    ) -> None:
        self._json = json_generation
        self._timeout = timeout_seconds
        self._cache: dict[str, str] = {}

    async def compose(
        self,
        reply: str,
        *,
        language: str | None,
        user_message: str | None = None,
        correlation_id: str = "",
        script: str | None = None,
    ) -> str:
        """The reply in ``language``. With no language (English / unknown)
        and no small talk to answer, the reply is returned untouched without
        an AI call."""
        language = normalize_language(language)
        script = normalize_script(script) if language else "native"
        message = (user_message or "").strip()[:500] or None
        if not reply.strip() or (language is None and message is None):
            return reply

        cache_key = self._cache_key(reply, language, message, script)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            raw = await asyncio.wait_for(
                self._json.generate_json(
                    system_prompt=_SYSTEM_PROMPT,
                    user_prompt=json.dumps(
                        {
                            "LANGUAGE": language or "English",
                            "SCRIPT": script,
                            "MESSAGE": message,
                            "REPLY": reply,
                        },
                        ensure_ascii=False,
                    ),
                    correlation_id=correlation_id or None,
                ),
                timeout=self._timeout,
            )
        except Exception:  # noqa: BLE001 -- English is always a valid answer
            logger.warning(
                "reply_language.compose_failed language=%s correlation_id=%s",
                language,
                correlation_id,
                exc_info=True,
            )
            return reply

        composed = self._parse(raw, reply)
        if composed is None:
            return reply
        if len(self._cache) >= _CACHE_SIZE:
            self._cache.pop(next(iter(self._cache)))
        self._cache[cache_key] = composed
        return composed

    @staticmethod
    def _cache_key(reply: str, language: str | None, message: str | None, script: str = "native") -> str:
        # Small talk is answered per message, so a message makes the key
        # unique; the fixed replies without one are what the cache is for.
        material = json.dumps([reply, (language or "").lower(), message, script], ensure_ascii=False)
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    @staticmethod
    def _parse(raw: str, original: str) -> str | None:
        """The composed text, or None when it should not be trusted: not
        JSON, empty, or wildly longer than the reply it renders (a sign the
        model added content it was told not to)."""
        try:
            payload = json.loads(raw)
            text = payload.get("text") if isinstance(payload, dict) else None
        except (json.JSONDecodeError, TypeError, AttributeError):
            logger.warning("reply_language.unparseable_completion")
            return None
        if not isinstance(text, str) or not text.strip():
            return None
        text = text.strip()
        if len(text) > 3 * len(original) + 200:
            logger.warning("reply_language.too_long original=%d composed=%d", len(original), len(text))
            return None
        return text


#: Fixed confirmations and receipts in the languages we have wording for
#: (request [38]). Plain text swaps -- no AI call, and numbers, names and
#: amounts around them are never touched. Keyed by the lower-cased language
#: name or code the understanding step reports.
_FIXED_REPLIES: dict[str, dict[str, str]] = {
    "malayalam": {
        "Here's what I can do:": "എനിക്ക് ചെയ്യാവുന്നത്:",
        "1. Just send me what happened on site, e.g.": "1. സൈറ്റിൽ എന്ത് നടന്നു എന്ന് അയയ്ക്കൂ, ഉദാ.",
        "2. Ask me, e.g.": "2. എന്നോട് ചോദിക്കൂ, ഉദാ.",
        "3. Get reports, e.g.": "3. റിപ്പോർട്ട് വാങ്ങൂ, ഉദാ.",
        "Type it or send a voice note. Or pick what you're reporting:": (
            "ടൈപ്പ് ചെയ്യാം, അല്ലെങ്കിൽ വോയ്‌സ് നോട്ട് അയയ്ക്കാം. അല്ലെങ്കിൽ എന്താണെന്ന് തിരഞ്ഞെടുക്കൂ:"
        ),
        "I'm Mesiri's site assistant. I'm best at site work. Try": (
            "ഞാൻ മെസിരിയുടെ സൈറ്റ് അസിസ്റ്റന്റാണ്. സൈറ്റ് ജോലിയിലാണ് ഞാൻ മികച്ചത്. ഇത് പരീക്ഷിക്കൂ:"
        ),
        "Fair point! I'm built for site work. Tell me what happened today, or ask me something like": (
            "ശരിയാണ്! ഞാൻ സൈറ്റ് ജോലിക്കായി ഉണ്ടാക്കിയതാണ്. ഇന്ന് എന്ത് നടന്നു എന്ന് പറയൂ, അല്ലെങ്കിൽ ഇങ്ങനെ ചോദിക്കൂ:"
        ),
        "I'll keep it simple: send me today's site update, or ask": (
            "ലളിതമായി പറയാം: ഇന്നത്തെ സൈറ്റ് അപ്ഡേറ്റ് അയയ്ക്കൂ, അല്ലെങ്കിൽ ചോദിക്കൂ:"
        ),
        "Sorry if that sounded stiff. I'm a site assistant: tell me what got done today, or ask": (
            "ക്ഷമിക്കണം. ഞാൻ ഒരു സൈറ്റ് അസിസ്റ്റന്റാണ്: ഇന്ന് എന്ത് ചെയ്തു എന്ന് പറയൂ, അല്ലെങ്കിൽ ചോദിക്കൂ:"
        ),
        "✅ Recorded. Thank you.": "✅ രേഖപ്പെടുത്തി. നന്ദി.",
        "Saved as a draft. You'll confirm it with tonight's report. Reply UNDO if it's wrong.": (
            "ഡ്രാഫ്റ്റായി സേവ് ചെയ്തു. ഇന്ന് രാത്രിയിലെ റിപ്പോർട്ടിനൊപ്പം സ്ഥിരീകരിക്കാം. "
            "തെറ്റാണെങ്കിൽ UNDO എന്ന് മറുപടി നൽകൂ."
        ),
        "❌ Discarded. Nothing was recorded.": "❌ ഒഴിവാക്കി. ഒന്നും രേഖപ്പെടുത്തിയിട്ടില്ല.",
        "Cancelled. Nothing was recorded.": "റദ്ദാക്കി. ഒന്നും രേഖപ്പെടുത്തിയിട്ടില്ല.",
        "That request was already handled.": "ഇത് നേരത്തെ തന്നെ കൈകാര്യം ചെയ്തു.",
        "⚠️ I couldn't save that just now, so nothing was recorded. Please send it again.": (
            "⚠️ ഇപ്പോൾ സേവ് ചെയ്യാൻ കഴിഞ്ഞില്ല, അതിനാൽ ഒന്നും രേഖപ്പെടുത്തിയിട്ടില്ല. ദയവായി വീണ്ടും അയയ്ക്കൂ."
        ),
        "Not saved yet.": "ഇതുവരെ സേവ് ചെയ്തിട്ടില്ല.",
        "I'll ask about this one after the rest.": "ഇതിനെക്കുറിച്ച് ബാക്കി കഴിഞ്ഞ് ചോദിക്കാം.",
        "Which site is this for?": "ഏത് സൈറ്റിനാണ് ഇത്?",
        "Which project is this for?": "ഏത് പ്രോജക്റ്റിനാണ് ഇത്?",
    },
    "hindi": {
        "Here's what I can do:": "मैं यह कर सकता हूँ:",
        "1. Just send me what happened on site, e.g.": "1. साइट पर क्या हुआ मुझे भेजें, जैसे",
        "2. Ask me, e.g.": "2. मुझसे पूछें, जैसे",
        "3. Get reports, e.g.": "3. रिपोर्ट पाएँ, जैसे",
        "Type it or send a voice note. Or pick what you're reporting:": (
            "लिखकर या वॉइस नोट भेजें। या चुनें कि क्या बता रहे हैं:"
        ),
        "I'm Mesiri's site assistant. I'm best at site work. Try": (
            "मैं Mesiri का साइट असिस्टेंट हूँ। साइट के काम में मैं सबसे अच्छा हूँ। आज़माएँ:"
        ),
        "Fair point! I'm built for site work. Tell me what happened today, or ask me something like": (
            "सही बात! मैं साइट के काम के लिए बना हूँ। आज क्या हुआ बताएँ, या ऐसे पूछें:"
        ),
        "I'll keep it simple: send me today's site update, or ask": (
            "सीधी बात: आज का साइट अपडेट भेजें, या पूछें:"
        ),
        "Sorry if that sounded stiff. I'm a site assistant: tell me what got done today, or ask": (
            "माफ़ कीजिए। मैं साइट असिस्टेंट हूँ: आज क्या काम हुआ बताएँ, या पूछें:"
        ),
        "✅ Recorded. Thank you.": "✅ दर्ज हो गया। धन्यवाद।",
        "Saved as a draft. You'll confirm it with tonight's report. Reply UNDO if it's wrong.": (
            "ड्राफ्ट के रूप में सेव किया। आज रात की रिपोर्ट के साथ इसे कन्फर्म करें। "
            "गलत हो तो UNDO लिखें।"
        ),
        "❌ Discarded. Nothing was recorded.": "❌ रद्द किया। कुछ भी दर्ज नहीं हुआ।",
        "Cancelled. Nothing was recorded.": "रद्द किया। कुछ भी दर्ज नहीं हुआ।",
        "⚠️ I couldn't save that just now, so nothing was recorded. Please send it again.": (
            "⚠️ अभी सेव नहीं हो सका, इसलिए कुछ भी दर्ज नहीं हुआ। कृपया फिर से भेजें।"
        ),
        "Not saved yet.": "अभी सेव नहीं हुआ।",
        "I'll ask about this one after the rest.": "इसके बारे में बाकी के बाद पूछूँगा।",
        "Which site is this for?": "यह किस साइट के लिए है?",
        "Which project is this for?": "यह किस प्रोजेक्ट के लिए है?",
    },
}
_FIXED_ALIASES = {"ml": "malayalam", "hi": "hindi"}


#: Label words of the "✅ Saved: ..." lines (interactions/saved_summary.py).
#: Only these words are swapped, and only on the lines that start with the
#: saved header or a bullet under it; numbers, names, trades and units stay.
_SAVED_WORDS: dict[str, dict[str, str]] = {
    "malayalam": {
        "✅ Saved:": "✅ സേവ് ചെയ്തു:",
        "Question for your engineer:": "എൻജിനീയർക്കുള്ള ചോദ്യം:",
        " workers": " തൊഴിലാളികൾ",
        " worker": " തൊഴിലാളി",
        "Expense ₹": "ചെലവ് ₹",
        "Issue (": "പ്രശ്നം (",
        " in:": " വന്നു:",
        " used:": " ഉപയോഗിച്ചു:",
    },
    "hindi": {
        "✅ Saved:": "✅ सेव हो गया:",
        "Question for your engineer:": "इंजीनियर के लिए सवाल:",
        " workers": " मज़दूर",
        " worker": " मज़दूर",
        "Expense ₹": "खर्च ₹",
        "Issue (": "समस्या (",
        " in:": " आया:",
        " used:": " इस्तेमाल हुआ:",
    },
}


def localize_saved_lines(text: str, language: str | None, script: str | None = None) -> str:
    """The label words of the saved lines in the sender's language; English
    letters and unknown languages keep the English text."""
    normalized = normalize_language(language)
    if not normalized or not text or normalize_script(script) == "latin":
        return text
    table = _SAVED_WORDS.get(_FIXED_ALIASES.get(normalized.lower(), normalized.lower()))
    if not table:
        return text
    out: list[str] = []
    in_block = False
    for line in text.split("\n"):
        stripped = line.lstrip()
        if stripped.startswith("✅ Saved:"):
            in_block = True
        elif in_block and not stripped.startswith("•"):
            in_block = False
        if in_block:
            for english in sorted(table, key=len, reverse=True):
                line = line.replace(english, table[english])
        out.append(line)
    return "\n".join(out)


def localize_fixed_reply(text: str, language: str | None, script: str | None = None) -> str:
    """``text`` with its fixed confirmation sentences in the sender's language.

    Only known sentences are swapped (longest first), so a receipt keeps its
    exact quantities, names and amounts; text with none of them, or a
    language without wording yet, comes back unchanged. A sender who types
    their language in English letters gets the English text -- the tables
    only hold native-script wording, which they would not read as easily."""
    normalized = normalize_language(language)
    if not normalized or not text or normalize_script(script) == "latin":
        return text
    key = normalized.lower()
    table = _FIXED_REPLIES.get(_FIXED_ALIASES.get(key, key))
    if not table:
        return text
    for english in sorted(table, key=len, reverse=True):
        text = text.replace(english, table[english])
    return text


# --- Worker-promotion questions (request [51]) ---------------------------------
#
# These carry names, so they cannot be swapped as fixed sentences: each English
# template (workflows/worker_promotion/wording.py) is turned into a pattern with
# its {placeholders} captured, and rebuilt from the translated template. The
# names, trades and dates inside are never touched. Buttons are translated by
# title; a tap comes back as its id, so no translated word is ever parsed.

_PROMOTION_TEMPLATES: dict[str, dict[str, str]] = {
    "malayalam": {
        wording.INTRO: "നിങ്ങളുടെ തൊഴിലാളി പട്ടിക വൃത്തിയായി നിലനിർത്താൻ ഒരു ചെറിയ പരിശോധന 👇",
        wording.OFFER_ONE: (
            "{names} ഒരു പുതിയ പേരാണ്. അടുത്ത തവണ തയ്യാറായിരിക്കാൻ ഇവരെ സ്ഥിരം "
            "തൊഴിലാളി പട്ടികയിൽ ചേർക്കട്ടേ?"
        ),
        wording.OFFER_MANY: (
            "{names} പുതിയ പേരുകളാണ്. അടുത്ത തവണ തയ്യാറായിരിക്കാൻ ഇവരെ സ്ഥിരം "
            "തൊഴിലാളി പട്ടികയിൽ ചേർക്കട്ടേ?"
        ),
        wording.CHOOSE: "ആരെയൊക്കെ ചേർക്കണം? പേരുകൾ മറുപടി നൽകൂ, ഉദാ. {example}.",
        wording.LOOKS_LIKE: (
            "{new} നിങ്ങളുടെ പട്ടികയിലുള്ള {old} എന്നയാളെപ്പോലെയാണ്{detail}. "
            "ഇത് അതേ ആൾ തന്നെയാണോ?"
        ),
        wording.LOOKS_LIKE_NEXT: (
            "ഒന്നുകൂടി 👇\n\n{new} നിങ്ങളുടെ പട്ടികയിലുള്ള {old} എന്നയാളെപ്പോലെയാണ്"
            "{detail}. ഇത് അതേ ആൾ തന്നെയാണോ?"
        ),
        wording.RETRY_OFFER: (
            "സാരമില്ല. ഒരെണ്ണം തൊട്ടാൽ മതി: {names} സ്ഥിരം തൊഴിലാളി പട്ടികയിൽ ചേർക്കട്ടേ? "
            "ഉറപ്പില്ലെങ്കിൽ ഇപ്പോൾ വേണ്ട എന്ന് തൊടൂ. 🙂"
        ),
        wording.RETRY_CHOOSE: (
            "സാരമില്ല. ചേർക്കേണ്ടവരുടെ പേരുകൾ മറുപടി നൽകൂ, ഉദാ. {example}. "
            "ഉറപ്പില്ലെങ്കിൽ ഇപ്പോൾ വേണ്ട എന്ന് തൊടൂ. 🙂"
        ),
        wording.RETRY_LOOKS_LIKE: (
            "സാരമില്ല. ഒരെണ്ണം തൊട്ടാൽ മതി: ഇന്ന് വന്ന {new} നിങ്ങളുടെ പട്ടികയിലെ {old} "
            "തന്നെയാണോ? ഉറപ്പില്ലെങ്കിൽ ഒഴിവാക്കുക എന്ന് തൊടൂ. 🙂"
        ),
        wording.MADE_PERMANENT: "✅ നിങ്ങളുടെ തൊഴിലാളി രജിസ്റ്ററിൽ സ്ഥിരമാക്കി: {names}",
        wording.NONE_ADDED: (
            "സാരമില്ല — അവർ താൽക്കാലിക തൊഴിലാളികളായി തുടരും. ഡാഷ്ബോർഡിലെ തൊഴിലാളി "
            "രജിസ്റ്ററിൽ നിന്ന് എപ്പോൾ വേണമെങ്കിലും സ്ഥിരമാക്കാം."
        ),
        wording.SAME_NOT_ADDED: "👍 {new} വീണ്ടും ചേർക്കുന്നില്ല — ഇതിനകം പട്ടികയിൽ {old} ആയി ഉണ്ട്.",
        wording.KEPT_SEPARATE: (
            "ഇപ്പോൾ {names} ഒരു വേറെ പേരായി നിലനിർത്തും. തൊഴിലാളി രജിസ്റ്ററിൽ "
            "എപ്പോൾ വേണമെങ്കിലും ശരിയാക്കാം."
        ),
    },
    "hindi": {
        wording.INTRO: "आपकी वर्कर लिस्ट साफ़ रहे, इसलिए एक छोटी जाँच 👇",
        wording.OFFER_ONE: (
            "{names} एक नया नाम है। क्या इन्हें स्थायी वर्कर लिस्ट में जोड़ दूँ, ताकि अगली बार तैयार रहें?"
        ),
        wording.OFFER_MANY: (
            "{names} नए नाम हैं। क्या इन्हें स्थायी वर्कर लिस्ट में जोड़ दूँ, ताकि अगली बार तैयार रहें?"
        ),
        wording.CHOOSE: "किन्हें जोड़ना है? नाम लिखकर भेजें, जैसे {example}।",
        wording.LOOKS_LIKE: (
            "{new} आपकी लिस्ट में पहले से मौजूद {old} जैसा लग रहा है{detail}। क्या यह वही व्यक्ति है?"
        ),
        wording.LOOKS_LIKE_NEXT: (
            "एक और 👇\n\n{new} आपकी लिस्ट में पहले से मौजूद {old} जैसा लग रहा है{detail}। "
            "क्या यह वही व्यक्ति है?"
        ),
        wording.RETRY_OFFER: (
            "कोई बात नहीं। बस एक बटन दबाएँ: {names} को स्थायी वर्कर लिस्ट में जोड़ दूँ? "
            "पक्का न हो तो अभी नहीं दबाएँ। 🙂"
        ),
        wording.RETRY_CHOOSE: (
            "कोई बात नहीं। जोड़ने वालों के नाम लिखें, जैसे {example}। पक्का न हो तो अभी नहीं दबाएँ। 🙂"
        ),
        wording.RETRY_LOOKS_LIKE: (
            "कोई बात नहीं। बस एक बटन दबाएँ: आज आया {new} क्या आपकी लिस्ट वाला {old} ही है? "
            "पक्का न हो तो छोड़ें दबाएँ। 🙂"
        ),
        wording.MADE_PERMANENT: "✅ वर्कर रजिस्टर में स्थायी किया: {names}",
        wording.NONE_ADDED: (
            "ठीक है — वे अस्थायी वर्कर बने रहेंगे। डैशबोर्ड के वर्कर रजिस्टर से कभी भी स्थायी कर सकते हैं।"
        ),
        wording.SAME_NOT_ADDED: "👍 {new} को दोबारा नहीं जोड़ रहा — लिस्ट में पहले से {old} नाम से है।",
        wording.KEPT_SEPARATE: (
            "अभी {names} को अलग नाम के रूप में रखता हूँ। वर्कर रजिस्टर में कभी भी ठीक कर सकते हैं।"
        ),
    },
}

_BUTTON_TITLES: dict[str, dict[str, str]] = {
    "malayalam": {
        wording.TITLE_ADD_ONE: "ചേർക്കുക",
        wording.TITLE_ADD_BOTH: "രണ്ടും ചേർക്കുക",
        wording.TITLE_ADD_ALL: "എല്ലാം ചേർക്കുക",
        wording.TITLE_CHOOSE: "തിരഞ്ഞെടുക്കുക",
        wording.TITLE_NOT_NOW: "ഇപ്പോൾ വേണ്ട",
        wording.TITLE_SAME: "അതേ ആൾ",
        wording.TITLE_NEW: "പുതിയ ആൾ",
        wording.TITLE_SKIP: "ഒഴിവാക്കുക",
    },
    "hindi": {
        wording.TITLE_ADD_ONE: "जोड़ें",
        wording.TITLE_ADD_BOTH: "दोनों जोड़ें",
        wording.TITLE_ADD_ALL: "सब जोड़ें",
        wording.TITLE_CHOOSE: "चुनें",
        wording.TITLE_NOT_NOW: "अभी नहीं",
        wording.TITLE_SAME: "वही व्यक्ति",
        wording.TITLE_NEW: "नया व्यक्ति",
        wording.TITLE_SKIP: "छोड़ें",
    },
}

_PLACEHOLDER = re.compile(r"\\\{(\w+)\\\}")


def _template_pattern(english: str) -> re.Pattern[str]:
    """A regex matching ``english`` with each {placeholder} captured by name."""
    pattern = _PLACEHOLDER.sub(lambda m: f"(?P<{m.group(1)}>[^\\n]*?)", re.escape(english))
    if english.rstrip().endswith("}"):
        pattern += r"(?=\n|$)"
    return re.compile(pattern)


_PROMOTION_PATTERNS: dict[str, list[tuple[re.Pattern[str], str]]] = {
    language: [(_template_pattern(en), tr) for en, tr in sorted(table.items(), key=lambda kv: -len(kv[0]))]
    for language, table in _PROMOTION_TEMPLATES.items()
}


def _language_key(language: str | None) -> str | None:
    normalized = normalize_language(language)
    if not normalized:
        return None
    key = normalized.lower()
    return _FIXED_ALIASES.get(key, key)


def localize_promotion_reply(text: str, language: str | None) -> str:
    """The worker-promotion questions in the sender's language; text that
    matches none of them, or a language without wording, comes back as it was."""
    key = _language_key(language)
    if not text or key not in _PROMOTION_PATTERNS:
        return text
    for pattern, translated in _PROMOTION_PATTERNS[key]:
        text = pattern.sub(lambda m, tr=translated: tr.format(**m.groupdict()), text)
    return text


def localize_reply_spec(spec, language: str | None, script: str | None = None):  # type: ignore[no-untyped-def]
    """``spec`` with its text, and its button / list titles, in the sender's
    language. English (or an unknown language, or a sender who types in
    English letters) returns it unchanged."""
    key = _language_key(language)
    if key is None or normalize_script(script) == "latin" or (key not in _FIXED_REPLIES and key not in _PROMOTION_PATTERNS):
        return spec
    from dataclasses import replace

    titles = _BUTTON_TITLES.get(key, {})

    def _row(row):  # type: ignore[no-untyped-def]
        title = titles.get(row.title)
        return replace(row, title=title[:20]) if title else row

    return replace(
        spec,
        text=localize_saved_lines(
            localize_promotion_reply(localize_fixed_reply(spec.text, language), language),
            language,
        ),
        buttons=tuple(_row(r) for r in spec.buttons) if spec.buttons else spec.buttons,
        list_rows=tuple(_row(r) for r in spec.list_rows) if spec.list_rows else spec.list_rows,
    )
