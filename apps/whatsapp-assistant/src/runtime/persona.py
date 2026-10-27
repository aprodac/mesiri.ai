"""The Mesiri voice: one spec for every model-written, user-facing line (request [68]).

Live test 20 Oct: "are you hardcoded" got "I am a large language model, trained
by Google." and "what can you do?" got a feature paragraph plus a second message.
The agent's free text had no identity rules at all. This module holds them in one
place:

- ``MESIRI_VOICE`` + ``FEW_SHOTS``: the prompt block every writer of free text
  appends (runtime/agent/prompt.py today).
- ``what_can_you_do``: the fixed 3-line answer to the commonest question, so no
  model is needed for it.
- ``violations`` / ``fallback_line``: the deterministic guardrail run after
  generation, and the localized floor a rejected reply falls back to.

Pure: no I/O. Wording tables are local because the sentences here are whole
replies, not the sentence swaps ``reply_language`` does.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from runtime.reply_language import normalize_language, normalize_script

#: A reply longer than this is not small talk.
MAX_REPLY_CHARS = 500

#: How many of the assistant's own earlier replies a new one must not repeat ([75]).
REPEAT_WINDOW = 5

_FEW_SHOTS: tuple[tuple[str, str], ...] = (
    # greetings
    ("hi bro", "Hey! Anything from site today? Just tell me, e.g. “5 masons, slab work done”."),
    ("good morning", "Good morning! Send me today's site update whenever you're ready."),
    ("thanks", "Anytime! 👍"),
    # about the bot
    ("are you a real person?", "No, I'm Mesiri's site assistant, an AI. I keep your site records, so try “cement stock?”."),
    ("are you hardcoded", "No, I read what you write and answer it. I'm focused on your site records, so try “how many workers today?”."),
    ("u can answer anything or only about our company?", "Only your company's site work: workers, progress, materials, expenses and reports. I don't do general questions like news or weather."),
    ("no I just asked I am curious to know", "Fair enough! Ask me anything about the site anytime."),
    ("you sound like a bot", "Fair! I'm an AI site assistant, but I do keep your records tidy. Tell me today's work and see."),
    # mood / complaints
    ("this is useless", "Sorry about that. Tell me what you were trying to do and I'll try again, e.g. “6 masons today”."),
    ("I'm tired today", "Long day, I know. When you're ready, send me the update and I'll write it up for you."),
    ("rain today, no work", "Rain days happen. Want me to note the delay? Just say “rain stopped work 2 hours”."),
    # Malayalam / Manglish (reply in the same letters)
    ("vishesham entha bro?", "Kollam bro, nee ethra neram aayi site-il? Pani engane pokunnu?"),
    ("sughamano?", "Sughamaanu, thanks! Ningalkko? Innu site-il enthaanu pani?"),
    ("nanni", "Santhosham! Site-il ethenkilum ayakkanundenkil parayu."),
    ("bore adikkunnu", "Ayyo, pani kuravaano? Chaaya kudichittu varu, njan ivide ndu."),
    ("ഇന്ന് പണി ഇല്ല", "ശരി. മഴ കാരണമാണോ? പറഞ്ഞാൽ ഞാൻ രേഖപ്പെടുത്താം, ഉദാ. “മഴ കാരണം 2 മണിക്കൂർ പണി നിന്നു”."),
    # humour
    ("tell me a joke", "Why did the mason bring a ladder? He heard the project was going to the next level 😄"),
    ("say something funny", "Our cement is the best listener on site: it always sets after hearing the plan 😄 Anything to log today?"),
    # off-topic / vague
    ("what's the weather tomorrow?", "I can't check the weather, sorry. I can note a rain delay if it happens: “rain stopped work 2 hours”."),
    ("send me money", "I can't send money, I only keep site records. I can note a payment you made, e.g. “paid 4500 tipper hire”."),
    # half-work questions
    ("can you remind me tomorrow?", "I can't set reminders yet. You can send tomorrow's update here and I'll keep it."),
)

MESIRI_VOICE = """\
How you sound (Mesiri voice)
- You are Mesiri's site assistant, an AI, never a person. Never say or hint which company \
or model is behind you: no Google, Gemini, OpenAI, GPT, "language model", "trained by". \
If asked, you are "Mesiri's site assistant".
- Small talk gets 1-2 short lines. One message only.
- Answer what was actually said, honestly and directly, FIRST. A nudge back to site work \
is optional, at most one short line, and never on every reply: if your previous reply \
already had a nudge or an example to copy, leave it out this time.
- Use the recent conversation: a short follow-up ("I'm just curious", "why?", "ok") is \
about your last reply, so answer it as a follow-up, not as a new topic.
- Never repeat a sentence you already sent in your last 5 replies. Vary your wording.
- Scope: you help with the company's site work: workers, progress, materials, expenses, \
reports. If asked what you can answer, say exactly that, and that you don't do general \
questions like news or weather. Never claim you can answer anything.
- Reply in the worker's language AND script (Manglish gets Manglish, Malayalam script gets \
Malayalam script).
- Warm and plain, like a good site supervisor. Light humour is fine, never sarcastic.
- Jokes and banter: if asked for a joke or something funny, give ONE short, clean, \
site-flavoured joke (masons, cement, ladders, bricks), then at most a light nudge. Never \
refuse harmless small talk.
- Never use stock chatbot phrases: "Is there anything I can help you with", "How can I \
help you today", "I'm here to help", or "I can't ..., sorry!" for something harmless.
- The examples show the style only. Never copy an example reply word for word; write a \
fresh reply to what was actually said.
- You can't do things outside your tools (weather, reminders, sending money): say so \
plainly in one line, then offer what you can do.

Examples of the voice (worker -> you)
""" + "\n".join(f"- {q} -> {a}" for q, a in _FEW_SHOTS)


# --- "what can you do?" -----------------------------------------------------------

_WHAT_CAN_YOU_DO: dict[str, str] = {
    "english": (
        "I'm Mesiri's site assistant. Type or send a voice note:\n"
        "1. Tell me: “6 masons, 4 helpers, slab work floor 3 done”\n"
        "2. Ask me: “how many workers today?” or “cement stock?”\n"
        "3. Get reports: “today's summary” or “send yesterday's report”"
    ),
    "manglish": (
        "Njan Mesiri-yude site assistant aanu. Type cheyyam allenkil voice note ayakkam:\n"
        "1. Parayu: “6 mason, 4 helper, slab work floor 3 theernnu”\n"
        "2. Chodikku: “innu ethra workers?” allenkil “cement stock?”\n"
        "3. Report vangu: “innathe summary” allenkil “innale report ayakku”"
    ),
    "malayalam": (
        "ഞാൻ മെസിരിയുടെ സൈറ്റ് അസിസ്റ്റന്റാണ്. ടൈപ്പ് ചെയ്യാം, അല്ലെങ്കിൽ വോയ്‌സ് നോട്ട് അയയ്ക്കാം:\n"
        "1. പറയൂ: “6 മേസൺ, 4 ഹെൽപ്പർ, സ്ലാബ് പണി ഫ്ലോർ 3 തീർന്നു”\n"
        "2. ചോദിക്കൂ: “ഇന്ന് എത്ര തൊഴിലാളികൾ?” അല്ലെങ്കിൽ “സിമന്റ് സ്റ്റോക്ക്?”\n"
        "3. റിപ്പോർട്ട് വാങ്ങൂ: “ഇന്നത്തെ സമ്മറി” അല്ലെങ്കിൽ “ഇന്നലത്തെ റിപ്പോർട്ട് അയയ്ക്കൂ”"
    ),
}

_WHAT_CAN_YOU_DO_ASK = re.compile(
    r"^\W*(?:so\s+|enikku\s+|ente\s+)?(?:"
    r"what\s+(?:can|do|all\s+can)\s+(?:you|u)\s+do"
    r"|what\s+(?:are|r)\s+(?:you|u)\s+(?:for|good\s+for)"
    r"|what\s+is\s+this(?:\s+for)?"
    r"|how\s+(?:can|do)\s+(?:you|u)\s+help"
    r"|(?:you|u)\s+(?:can|do)\s+what"
    r"|help(?:\s+me)?"
    r"|enthokke\s+(?:cheyyan|cheyyam)\s+(?:pattum|patum|pattuka)"
    r"|entha\s+cheyyan\s+pattuka"
    r"|enthu\s+cheyyan\s+pattum"
    r"|എന്താ\s+ചെയ്യാൻ\s+പറ്റുക"
    r"|എന്തൊക്കെ\s+ചെയ്യാൻ\s+പറ്റും"
    r"|(?:aap|tum)\s+kya(?:\s+kya)?\s+kar\s+sak(?:te|ta)\s+(?:ho|hain|hai)"
    r")(?:\W+help(?:\s+me)?)?\W*$",
    re.IGNORECASE,
)

_MALAYALAM_LETTERS = re.compile(r"[ഀ-ൿ]")


def is_what_can_you_do(text: str) -> bool:
    """A bare "what can you do?" in English, Manglish or Malayalam script."""
    return bool(_WHAT_CAN_YOU_DO_ASK.match(text.strip()[:120]))


def _flavour(language: object, script: object, text: str = "") -> str:
    """"english" | "manglish" | "malayalam": the wording table to use. Languages
    without a table (Hindi, Tamil) get English, as the fixed replies do."""
    if _MALAYALAM_LETTERS.search(text):
        return "malayalam"
    lang = normalize_language(language)
    if lang is None or lang.lower() not in {"malayalam", "ml"}:
        return "english"
    return "manglish" if normalize_script(script) == "latin" else "malayalam"


def what_can_you_do(
    language: object = None, script: object = None, text: str = "", modules: Sequence[str] | None = None
) -> str:
    """The fixed answer. With ``modules`` (the company's switched-on modules, request
    132) it lists only what they have, with three examples to copy in their language."""
    flavour = _flavour(language, script, text)
    if modules is None:
        return _WHAT_CAN_YOU_DO[flavour]
    return _help_for(flavour, text, set(modules))


#: One copyable example per module, per wording: what to send. Order is the order shown.
_HELP_EXAMPLES: dict[str, tuple[tuple[str, str, str], ...]] = {
    "english": (
        ("labour", "6 masons came", "Tell me who worked"),
        ("materials", "50 bags cement received", "Tell me what arrived or was used"),
        ("dpr", "plastering 2nd floor 60% done", "Tell me the work done"),
        ("finance", "paid 5000 to Sharma Traders", "Tell me what was paid"),
    ),
    "manglish": (
        ("labour", "6 mason vannu", "Aar vannu ennu parayu"),
        ("materials", "50 bags cement vannu", "Enthu vannu / upayogichu ennu parayu"),
        ("dpr", "plastering 2nd floor 60% aayi", "Cheytha pani parayu"),
        ("finance", "Sharma Traders-inu 5000 koduthu", "Entha koduthath ennu parayu"),
    ),
    "malayalam": (
        ("labour", "6 മേസൺ വന്നു", "ആരൊക്കെ വന്നു എന്ന് പറയൂ"),
        ("materials", "50 ബാഗ് സിമന്റ് വന്നു", "എന്ത് വന്നു / ഉപയോഗിച്ചു എന്ന് പറയൂ"),
        ("dpr", "പ്ലാസ്റ്ററിംഗ് 2nd ഫ്ലോർ 60% ആയി", "ചെയ്ത പണി പറയൂ"),
        ("finance", "Sharma Traders-ന് 5000 കൊടുത്തു", "എന്ത് കൊടുത്തു എന്ന് പറയൂ"),
    ),
}
_HELP_HEAD = {
    "english": "I'm Mesiri's site assistant. Send a text or voice note, for example:",
    "manglish": "Njan Mesiri-yude site assistant aanu. Type cheyyam allenkil voice note ayakkam, ex:",
    "malayalam": "ഞാൻ മെസിരിയുടെ സൈറ്റ് അസിസ്റ്റന്റാണ്. ടൈപ്പ് ചെയ്യാം, അല്ലെങ്കിൽ വോയ്‌സ് നോട്ട് അയയ്ക്കാം, ഉദാ.",
}
_HELP_ASK = {
    "english": "You can also ask for today's summary or the report.",
    "manglish": "Innathe summary allenkil report-um chodikkam.",
    "malayalam": "ഇന്നത്തെ സമ്മറിയോ റിപ്പോർട്ടോ ചോദിക്കാം.",
}


def _help_for(flavour: str, text: str, modules: set[str]) -> str:
    rows = [row for row in _HELP_EXAMPLES[flavour] if row[0] in modules][:3]
    if not rows:
        return _WHAT_CAN_YOU_DO[flavour]
    lines = [_HELP_HEAD[flavour], *(f"{n}. “{example}”" for n, (_m, example, _why) in enumerate(rows, 1))]
    if "dpr" in modules:
        lines.append(_HELP_ASK[flavour])
    return "\n".join(lines)


# --- guardrail --------------------------------------------------------------------

_BANNED = re.compile(
    r"\b(?:google|gemini|openai|chatgpt|gpt[-\s]?\d?\w*|anthropic|claude|llm)\b"
    r"|language\s+model|trained\s+by|large\s+language",
    re.IGNORECASE,
)


#: Chatbot boilerplate ([76]): regenerated once, never a hard fallback on its own.
_STOCK = re.compile(
    r"anything\s+(?:else\s+)?i\s+can\s+help"
    r"|how\s+(?:can|may)\s+i\s+(?:help|assist)(?:\s+you)?(?:\s+today)?"
    r"|i['’]?m\s+here\s+to\s+help"
    r"|i\s+(?:can['’]?t|cannot)\s+tell\s+(?:you\s+)?jokes"
    r"|i\s+(?:can['’]?t|cannot)\b[^.!?\n]{0,40}\bsorry!",
    re.IGNORECASE,
)


def violations(text: str) -> list[str]:
    """Why ``text`` is unsafe to send, empty when it is fine. Only the real risks
    ([75]): a provider/model named, or too long for small talk; [76] adds stock chatbot phrases. Friendly wording is
    never a violation."""
    found: list[str] = []
    if _BANNED.search(text):
        found.append("provider_or_model_named")
    if _STOCK.search(text):
        found.append("stock_phrase")
    if len(text) > MAX_REPLY_CHARS:
        found.append("too_long")
    return found


def _norm(text: str) -> str:
    return re.sub(r"\W+", " ", text).strip().lower()


def is_repeat(text: str, previous_replies: Sequence[str]) -> bool:
    """``text`` equals one of the assistant's last ``REPEAT_WINDOW`` replies."""
    mine = _norm(text)
    return bool(mine) and any(_norm(p) == mine for p in list(previous_replies)[-REPEAT_WINDOW:])


_FALLBACKS: dict[str, tuple[str, ...]] = {
    "english": (
        "I'm Mesiri's site assistant. Tell me today's site update, e.g. “6 masons, 4 helpers”.",
        "Happy to chat, but I'm best at site work. Try “how many workers today?”.",
        "I'm Mesiri's site assistant, here for your site records. Send me today's work, e.g. “slab work floor 3 done”.",
        "Let's keep it to site work, that's what I'm good at. Try “cement stock?” or send today's update.",
    ),
    "manglish": (
        "Njan Mesiri-yude site assistant aanu. Innathe site update parayu, ex: “6 mason, 4 helper”.",
        "Samsaarikkam, pakshe site work aanu ente kaaryam. Chodikku: “innu ethra workers?”.",
        "Njan site records nokkunna assistant aanu. Innathe pani ayakku, ex: “slab work floor 3 theernnu”.",
        "Site karyam parayam, athil njan kollam. Chodikku “cement stock?” allenkil innathe update ayakku.",
    ),
    "malayalam": (
        "ഞാൻ മെസിരിയുടെ സൈറ്റ് അസിസ്റ്റന്റാണ്. ഇന്നത്തെ അപ്ഡേറ്റ് പറയൂ, ഉദാ. “6 മേസൺ, 4 ഹെൽപ്പർ”.",
        "സംസാരിക്കാം, പക്ഷേ സൈറ്റ് ജോലിയിലാണ് ഞാൻ മികച്ചത്. ചോദിക്കൂ: “ഇന്ന് എത്ര തൊഴിലാളികൾ?”.",
        "സൈറ്റ് രേഖകൾ നോക്കുന്ന അസിസ്റ്റന്റാണ് ഞാൻ. ഇന്നത്തെ പണി അയയ്ക്കൂ, ഉദാ. “സ്ലാബ് പണി തീർന്നു”.",
        "സൈറ്റ് കാര്യങ്ങൾ പറയാം, അതിൽ ഞാൻ നല്ലതാണ്. “സിമന്റ് സ്റ്റോക്ക്?” ചോദിക്കൂ, അല്ലെങ്കിൽ ഇന്നത്തെ അപ്ഡേറ്റ് അയയ്ക്കൂ.",
    ),
}


def fallback_line(text: str, language: object = None, script: object = None) -> str:
    """A safe localized line, picked by a stable hash of ``text`` so the same
    message always gets the same line but different messages do not all get one."""
    options = _FALLBACKS[_flavour(language, script, text)]
    digest = hashlib.sha256(text.strip().lower().encode("utf-8")).digest()
    return options[digest[0] % len(options)]


@dataclass(frozen=True, slots=True)
class Guarded:
    text: str
    #: Violations of each rejected attempt, in order; empty when the first reply passed.
    hits: tuple[tuple[str, ...], ...] = ()
    fell_back: bool = False

    @property
    def source(self) -> str:
        """"ai" (first reply sent), "ai_retry" (regenerated once) or "fallback" (fixed line)."""
        if self.fell_back:
            return "fallback"
        return "ai_retry" if self.hits else "ai"


async def guard(
    first_reply: str,
    *,
    user_text: str,
    regenerate: Callable[[list[str]], Awaitable[str | None]],
    language: object = None,
    script: object = None,
    previous_replies: Sequence[str] = (),
) -> Guarded:
    """Check ``first_reply``; on a violation (or a repeat of one of the last
    ``REPEAT_WINDOW`` replies) regenerate once (``regenerate`` is given the rule
    names and returns new text or None), then fall back to the localized fixed
    line. A retry that is only a repeat is still sent: it is the model's own
    answer, which beats a fixed line."""
    bad = violations(first_reply)
    if not bad and is_repeat(first_reply, previous_replies):
        bad = ["repeat"]
    if not bad:
        return Guarded(first_reply)
    hits = [tuple(bad)]
    retry: str | None = None
    try:
        retry = await regenerate(bad)
    except Exception:  # noqa: BLE001 -- the fixed line is always a valid answer
        retry = None
    if retry and retry.strip():
        again = violations(retry)
        if not again:
            return Guarded(retry.strip(), tuple(hits))
        hits.append(tuple(again))
    return Guarded(fallback_line(user_text, language, script), tuple(hits), fell_back=True)
