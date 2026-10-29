"""The code's own sentences, in the sender's language (request 143).

Every fixed line the assistant sends without the model (a report sent, a module
switched off, a question the code asks) is written here once per language and
picked by ``say``. A line missing for a language falls back to English, so a new
key never breaks a reply; a test checks every key has every language.

The language is the message's own when it says (``language_of``); a message that
cannot tell ("ok", "20", a tap) takes the sender's ``usual`` language, the one
their recent messages were in, so a Manglish sender's "ok thanks" is answered in
Manglish, not English.
"""

from __future__ import annotations

import re

from .prompt import is_hinglish, is_manglish, reply_language

LANGUAGES = ("english", "manglish", "malayalam", "hindi", "hinglish")


def language_of(text: str, usual: str | None = None) -> str:
    """The language of the reply to ``text``: one of ``LANGUAGES``."""
    if re.search(r"[ഀ-ൿ]", text or ""):
        return "malayalam"
    if re.search(r"[ऀ-ॿ]", text or ""):
        return "hindi"
    if is_manglish(text or ""):
        return "manglish"
    if is_hinglish(text or ""):
        return "hinglish"
    if reply_language(text or "") is None and usual in LANGUAGES:
        return str(usual)
    return "english"


def usual_language(texts: list[str]) -> str | None:
    """The language the sender's recent messages were in (newest first wins), for a
    message that cannot tell on its own."""
    for text in texts:
        if reply_language(text or "") is not None:
            return language_of(text)
    return None


#: A day in each language: "of" (the report OF the day) and "on" (saved ON it).
_DAY = {
    "english": {"of_today": "today", "of": "{d}", "on_today": "today", "on": "for {d}"},
    "manglish": {"of_today": "Innathe", "of": "{d}-inte", "on_today": "Innu", "on": "{d}-nu"},
    "malayalam": {"of_today": "ഇന്നത്തെ", "of": "{d}-ലെ", "on_today": "ഇന്ന്", "on": "{d}-ന്"},
    "hindi": {"of_today": "आज की", "of": "{d} की", "on_today": "आज", "on": "{d} को"},
    "hinglish": {"of_today": "Aaj ki", "of": "{d} ki", "on_today": "Aaj", "on": "{d} ko"},
}


def day_words(day: object, today: object, language: str) -> dict[str, str]:
    """``of_day`` and ``on_day`` for ``say``: "today" or "28 Oct", in the language."""
    forms = _DAY.get(language, _DAY["english"])
    if day == today:
        return {"of_day": forms["of_today"], "on_day": forms["on_today"]}
    shown = f"{day:%d %b}".lstrip("0")  # type: ignore[str-format]
    if getattr(day, "year", None) != getattr(today, "year", None):
        shown = f"{day:%d %b %Y}".lstrip("0")  # type: ignore[str-format]
    return {"of_day": forms["of"].format(d=shown), "on_day": forms["on"].format(d=shown)}


LINES: dict[str, dict[str, str]] = {
    # -- the DPR request (request 143, phase 2) --------------------------------
    "report.confirmed": {
        "english": "Here is the DPR for {of_day}{at}.",
        "manglish": "{of_day} DPR{at} ithaa.",
        "malayalam": "{of_day} DPR{at} ഇതാ.",
        "hindi": "{of_day} DPR{at} यह है.",
        "hinglish": "{of_day} DPR{at} yeh hai.",
    },
    "report.draft": {
        "english": "Here is the draft report for {of_day}{at}, from what is saved so far. Not confirmed yet.",
        "manglish": "{of_day} draft report{at} ithaa, ithuvare save cheythathil ninnu. Confirm aayittilla.",
        "malayalam": "{of_day} ഡ്രാഫ്റ്റ് റിപ്പോർട്ട്{at} ഇതാ, ഇതുവരെ സേവ് ചെയ്തതിൽ നിന്ന്. സ്ഥിരീകരിച്ചിട്ടില്ല.",
        "hindi": "{of_day} ड्राफ्ट रिपोर्ट{at} यह है, अब तक सेव की गई जानकारी से. अभी कन्फर्म नहीं है.",
        "hinglish": "{of_day} draft report{at} yeh hai, ab tak save kiye gaye se. Abhi confirm nahi hai.",
    },
    "report.many": {
        "english": "Here are the reports for {of_day}, one per site: {sites}.",
        "manglish": "{of_day} report ithaa, oro site-num onnu: {sites}.",
        "malayalam": "{of_day} റിപ്പോർട്ടുകൾ ഇതാ, ഓരോ സൈറ്റിനും ഒന്ന്: {sites}.",
        "hindi": "{of_day} रिपोर्ट यह हैं, हर साइट की एक: {sites}.",
        "hinglish": "{of_day} reports yeh hain, har site ki ek: {sites}.",
    },
    "report.nothing": {
        "english": "Nothing is saved {on_day}{at} yet, so there is no report.",
        "manglish": "{on_day}{at} onnum save cheythittilla, athukondu report illa.",
        "malayalam": "{on_day}{at} ഒന്നും സേവ് ചെയ്തിട്ടില്ല, അതുകൊണ്ട് റിപ്പോർട്ട് ഇല്ല.",
        "hindi": "{on_day}{at} अभी कुछ सेव नहीं है, इसलिए रिपोर्ट नहीं है.",
        "hinglish": "{on_day}{at} abhi kuch save nahi hai, isliye report nahi hai.",
    },
    "report.bad_date": {
        "english": 'Which day\'s report do you want? Say "yesterday" or a date like 12 Oct.',
        "manglish": 'Ethu divasathe report venam? "innale" allenkil 12 Oct pole oru date parayu.',
        "malayalam": 'ഏത് ദിവസത്തെ റിപ്പോർട്ട് വേണം? "ഇന്നലെ" അല്ലെങ്കിൽ 12 Oct പോലെ ഒരു തീയതി പറയൂ.',
        "hindi": 'किस दिन की रिपोर्ट चाहिए? "कल" या 12 Oct जैसी तारीख बताइए.',
        "hinglish": 'Kis din ki report chahiye? "kal" ya 12 Oct jaisi date batayein.',
    },
    "report.failed": {
        "english": "Couldn't make the report just now, please ask again in a few minutes.",
        "manglish": "Report ippo undaakkan pattiyilla, kurachu kazhinju veendum chodikku.",
        "malayalam": "റിപ്പോർട്ട് ഇപ്പോൾ ഉണ്ടാക്കാൻ കഴിഞ്ഞില്ല, കുറച്ച് കഴിഞ്ഞ് വീണ്ടും ചോദിക്കൂ.",
        "hindi": "रिपोर्ट अभी नहीं बन सकी, कुछ मिनट बाद फिर पूछें.",
        "hinglish": "Report abhi nahi ban saki, kuch minute baad phir poochein.",
    },
    "report.not_sent": {
        "english": "Sorry, the PDF didn't go through. Please ask again in a minute.",
        "manglish": "Sorry, PDF poyilla. Oru minute kazhinju veendum chodikku.",
        "malayalam": "ക്ഷമിക്കണം, PDF പോയില്ല. ഒരു മിനിറ്റ് കഴിഞ്ഞ് വീണ്ടും ചോദിക്കൂ.",
        "hindi": "माफ़ कीजिए, PDF नहीं गई. एक मिनट बाद फिर पूछें.",
        "hinglish": "Sorry, PDF nahi gayi. Ek minute baad phir poochein.",
    },
    "report.with_card": {
        "english": "The report so far is attached; the items above join it once you tap Save.",
        "manglish": "Ithuvareyulla report koode und; mukalile items Save tap cheythaal athil cherum.",
        "malayalam": "ഇതുവരെയുള്ള റിപ്പോർട്ട് കൂടെയുണ്ട്; മുകളിലെ ഇനങ്ങൾ Save അമർത്തിയാൽ അതിൽ ചേരും.",
        "hindi": "अब तक की रिपोर्ट साथ है; ऊपर की चीज़ें Save दबाने पर उसमें जुड़ेंगी.",
        "hinglish": "Ab tak ki report saath hai; upar ke items Save dabane par usmein judenge.",
    },
}


def say(key: str, language: str, **values: str) -> str:
    """The line ``key`` in ``language`` (English when it has none), filled in."""
    lines = LINES[key]
    return lines.get(language, lines["english"]).format(**values)
