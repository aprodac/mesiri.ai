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
from typing import Any, Protocol

from mesiri_ai.ports.generation import JsonGenerationProvider

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

    async def remember(self, *, user_id: str, detected_language: object) -> None:
        """Store what the understanding step detected. English is stored too
        (as None) so someone who switches back to English gets English."""
        if not user_id or not isinstance(detected_language, str) or not detected_language.strip():
            return
        try:
            await self._redis.set_json(
                self._key(user_id),
                {"language": normalize_language(detected_language)},
                ttl_seconds=_LANGUAGE_TTL_SECONDS,
            )
        except Exception:  # noqa: BLE001
            logger.warning("reply_language.remember_failed user=%s", user_id)

    async def get(self, *, user_id: str) -> str | None:
        try:
            stored = await self._redis.get_json(self._key(user_id))
        except Exception:  # noqa: BLE001
            logger.warning("reply_language.lookup_failed user=%s", user_id)
            return None
        if isinstance(stored, dict):
            return normalize_language(stored.get("language"))
        return None


_SYSTEM_PROMPT = """You write WhatsApp replies for Mesiri, an assistant that construction site supervisors in India use to report their day.

You are given Mesiri's REPLY (in English), the LANGUAGE to write it in, and possibly the user's MESSAGE that it answers.

Rules:
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
    ) -> str:
        """The reply in ``language``. With no language (English / unknown)
        and no small talk to answer, the reply is returned untouched without
        an AI call."""
        language = normalize_language(language)
        message = (user_message or "").strip()[:500] or None
        if not reply.strip() or (language is None and message is None):
            return reply

        cache_key = self._cache_key(reply, language, message)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            raw = await asyncio.wait_for(
                self._json.generate_json(
                    system_prompt=_SYSTEM_PROMPT,
                    user_prompt=json.dumps(
                        {"LANGUAGE": language or "English", "MESSAGE": message, "REPLY": reply},
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
    def _cache_key(reply: str, language: str | None, message: str | None) -> str:
        # Small talk is answered per message, so a message makes the key
        # unique; the fixed replies without one are what the cache is for.
        material = json.dumps([reply, (language or "").lower(), message], ensure_ascii=False)
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
        "✅ Recorded. Thank you.": "✅ രേഖപ്പെടുത്തി. നന്ദി.",
        "Saved as a draft. You'll confirm it with tonight's report. Reply UNDO if it's wrong.": (
            "ഡ്രാഫ്റ്റായി സേവ് ചെയ്തു. ഇന്ന് രാത്രിയിലെ റിപ്പോർട്ടിനൊപ്പം സ്ഥിരീകരിക്കാം. "
            "തെറ്റാണെങ്കിൽ UNDO എന്ന് മറുപടി നൽകൂ."
        ),
        "❌ Discarded. Nothing was recorded.": "❌ ഒഴിവാക്കി. ഒന്നും രേഖപ്പെടുത്തിയിട്ടില്ല.",
        "Cancelled. Nothing was recorded.": "റദ്ദാക്കി. ഒന്നും രേഖപ്പെടുത്തിയിട്ടില്ല.",
        "That request was already handled.": "ഇത് നേരത്തെ തന്നെ കൈകാര്യം ചെയ്തു.",
        "⚠️ Something went wrong — we'll retry automatically.": (
            "⚠️ എന്തോ പിശക് സംഭവിച്ചു — ഞങ്ങൾ വീണ്ടും ശ്രമിക്കും."
        ),
        "Not saved yet.": "ഇതുവരെ സേവ് ചെയ്തിട്ടില്ല.",
        "I'll ask about this one after the rest.": "ഇതിനെക്കുറിച്ച് ബാക്കി കഴിഞ്ഞ് ചോദിക്കാം.",
        "Which site is this for?": "ഏത് സൈറ്റിനാണ് ഇത്?",
        "Which project is this for?": "ഏത് പ്രോജക്റ്റിനാണ് ഇത്?",
    },
    "hindi": {
        "✅ Recorded. Thank you.": "✅ दर्ज हो गया। धन्यवाद।",
        "Saved as a draft. You'll confirm it with tonight's report. Reply UNDO if it's wrong.": (
            "ड्राफ्ट के रूप में सेव किया। आज रात की रिपोर्ट के साथ इसे कन्फर्म करें। "
            "गलत हो तो UNDO लिखें।"
        ),
        "❌ Discarded. Nothing was recorded.": "❌ रद्द किया। कुछ भी दर्ज नहीं हुआ।",
        "Cancelled. Nothing was recorded.": "रद्द किया। कुछ भी दर्ज नहीं हुआ।",
        "⚠️ Something went wrong — we'll retry automatically.": (
            "⚠️ कुछ गड़बड़ हुई — हम अपने आप दोबारा कोशिश करेंगे।"
        ),
        "Not saved yet.": "अभी सेव नहीं हुआ।",
        "I'll ask about this one after the rest.": "इसके बारे में बाकी के बाद पूछूँगा।",
        "Which site is this for?": "यह किस साइट के लिए है?",
        "Which project is this for?": "यह किस प्रोजेक्ट के लिए है?",
    },
}
_FIXED_ALIASES = {"ml": "malayalam", "hi": "hindi"}


def localize_fixed_reply(text: str, language: str | None) -> str:
    """``text`` with its fixed confirmation sentences in the sender's language.

    Only known sentences are swapped (longest first), so a receipt keeps its
    exact quantities, names and amounts; text with none of them, or a
    language without wording yet, comes back unchanged."""
    normalized = normalize_language(language)
    if not normalized or not text:
        return text
    key = normalized.lower()
    table = _FIXED_REPLIES.get(_FIXED_ALIASES.get(key, key))
    if not table:
        return text
    for english in sorted(table, key=len, reverse=True):
        text = text.replace(english, table[english])
    return text
