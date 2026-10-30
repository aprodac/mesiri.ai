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

from .prompt import preferred_language, reply_language

LANGUAGES = ("english", "manglish", "malayalam", "hindi", "hinglish")


#: Words that say nothing about a language: an acknowledgement ("ok thanks", "👍")
#: is answered in the sender's usual language, not in English for its English words.
_ACK = frozenset(
    "ok okay okey k kk fine thanks thank thanku thankyou thx tnx ty you done good great nice cool yes no "
    "hmm hm noted right alright super".split()
)


def usual_from(language: str | None, script: str | None) -> str | None:
    """The sender's remembered language (``UserLanguageStore`` profile: a name like
    "Malayalam" and "latin" / "native") as one of ``LANGUAGES``; None when English or
    not known."""
    name = str(language or "").strip().lower()
    latin = str(script or "").strip().lower() == "latin"
    if name in ("malayalam", "ml"):
        return "manglish" if latin else "malayalam"
    if name in ("hindi", "hi"):
        return "hinglish" if latin else "hindi"
    return None


def _no_words_of_its_own(text: str) -> bool:
    words = re.findall(r"[^\W\d_]+", (text or "").lower())
    return not words or all(w in _ACK for w in words)


def decide(text: str, usual: str | None = None) -> str | None:
    """THE reply language of a turn, decided once: the message's own when it tells
    (its script, Manglish or Hinglish words, plain English), else the sender's
    usual one. None when neither tells (then nothing is forced). Live 29 Oct: the
    language the sender set (``set_reply_language``) wins over both."""
    if preferred_language.get() in LANGUAGES:
        return str(preferred_language.get())
    if _no_words_of_its_own(text) and usual in LANGUAGES:
        return str(usual)
    found = reply_language(text or "")
    if found in LANGUAGES:
        return found
    if found is None and usual in LANGUAGES:
        return str(usual)
    return None


def language_of(text: str, usual: str | None = None) -> str:
    """The language of a code-made line for ``text``: one of ``LANGUAGES``."""
    return decide(text, usual) or "english"


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
    # -- the check layer (request 143, phase 3) --------------------------------
    "check.labour_many": {
        "english": "{workers} workers? This site usually has about {usual}.",
        "manglish": "{workers} per aano? Ee site-il saadharana {usual} okke aanu.",
        "malayalam": "{workers} പേരോ? ഈ സൈറ്റിൽ സാധാരണ {usual} ഓളം ആണ്.",
        "hindi": "{workers} मज़दूर? इस साइट पर आमतौर पर लगभग {usual} होते हैं.",
        "hinglish": "{workers} workers? Is site par aam taur par {usual} ke aas paas hote hain.",
    },
    "check.labour_new": {
        "english": "{workers} workers in one day, is that right?",
        "manglish": "Oru divasam {workers} per, shariyaano?",
        "malayalam": "ഒരു ദിവസം {workers} പേർ, ശരിയാണോ?",
        "hindi": "एक दिन में {workers} मज़दूर, सही है?",
        "hinglish": "Ek din mein {workers} workers, sahi hai?",
    },
    "check.percent_over": {
        "english": "{percent}% is above 100%. Is that right?",
        "manglish": "{percent}% 100%-il kooduthal aanu. Shariyaano?",
        "malayalam": "{percent}% 100%-ൽ കൂടുതലാണ്. ശരിയാണോ?",
        "hindi": "{percent}% तो 100% से ज़्यादा है. सही है?",
        "hinglish": "{percent}% to 100% se zyada hai. Sahi hai?",
    },
    "check.percent_down": {
        "english": "{work} went down: {before}% was saved, now {percent}%. Is that right?",
        "manglish": "{work} kuranju: munpu {before}% save cheythirunnu, ippo {percent}%. Shariyaano?",
        "malayalam": "{work} കുറഞ്ഞു: മുമ്പ് {before}% സേവ് ചെയ്തിരുന്നു, ഇപ്പോൾ {percent}%. ശരിയാണോ?",
        "hindi": "{work} कम हो गया: पहले {before}% सेव था, अब {percent}%. सही है?",
        "hinglish": "{work} kam ho gaya: pehle {before}% save tha, ab {percent}%. Sahi hai?",
    },
    "check.more_than_stock": {
        "english": "{used} {unit} used, but the site has {stock} {unit} in stock. Is that right?",
        "manglish": "{used} {unit} use cheythu, pakshe site-il {stock} {unit} maathrame stock ullu. Shariyaano?",
        "malayalam": "{used} {unit} ഉപയോഗിച്ചു, പക്ഷേ സൈറ്റിൽ {stock} {unit} മാത്രമേ സ്റ്റോക്കുള്ളൂ. ശരിയാണോ?",
        "hindi": "{used} {unit} इस्तेमाल हुआ, पर साइट पर {stock} {unit} ही स्टॉक है. सही है?",
        "hinglish": "{used} {unit} use hua, par site par {stock} {unit} hi stock hai. Sahi hai?",
    },
    "check.future_date": {
        "english": "📅 It says {day}, which is after today. Save it as today, {today}?",
        "manglish": "📅 {day} ennaanu, athu innathe kazhinjulla date aanu. Innathe ({today}) aayi save cheyyatte?",
        "malayalam": "📅 {day} എന്നാണ്, അത് ഇന്നത്തേതിന് ശേഷമുള്ള തീയതിയാണ്. ഇന്നത്തെ ({today}) തീയതിയിൽ സേവ് ചെയ്യട്ടെ?",
        "hindi": "📅 इसमें {day} लिखा है, जो आज के बाद की तारीख है. आज ({today}) की तारीख में सेव करें?",
        "hinglish": "📅 Ismein {day} likha hai, jo aaj ke baad ki date hai. Aaj ({today}) ki date mein save karein?",
    },
    "check.already_saved": {
        "english": "already saved at {time}. Save again?",
        "manglish": "{time}-nu save aayi. Veendum save cheyyano?",
        "malayalam": "{time}-ന് സേവ് ആയി. വീണ്ടും സേവ് ചെയ്യണോ?",
        "hindi": "{time} पर सेव हो चुका. फिर से सेव करें?",
        "hinglish": "{time} par save ho chuka. Phir se save karein?",
    },
    "check.removed_repeat": {
        "english": "Okay, not saved twice: {line} stays saved once.",
        "manglish": "Sheri, randu thavana save cheyyilla: {line} oru thavana save aayittund.",
        "malayalam": "ശരി, രണ്ടു തവണ സേവ് ചെയ്യില്ല: {line} ഒരു തവണ സേവ് ആയിട്ടുണ്ട്.",
        "hindi": "ठीक है, दो बार सेव नहीं होगा: {line} एक बार सेव है.",
        "hinglish": "Theek hai, do baar save nahi hoga: {line} ek baar save hai.",
    },
    "cancel.rest": {
        "english": "❌ Cancelled the rest. Already saved: {saved}.",
        "manglish": "❌ Baakki cancel cheythu. Save aayath: {saved}.",
        "malayalam": "❌ ബാക്കി ക്യാൻസൽ ചെയ്തു. സേവ് ആയത്: {saved}.",
        "hindi": "❌ बाकी कैंसल किया. पहले से सेव है: {saved}.",
        "hinglish": "❌ Baaki cancel kiya. Pehle se save hai: {saved}.",
    },
    "check.change": {
        "english": "Okay, {line} is off the card. Send the right figure.",
        "manglish": "Sheri, {line} card-il ninnu maatti. Shariyaaya figure ayakku.",
        "malayalam": "ശരി, {line} കാർഡിൽ നിന്ന് മാറ്റി. ശരിയായ കണക്ക് അയക്കൂ.",
        "hindi": "ठीक है, {line} कार्ड से हटा दिया. सही आँकड़ा भेजें.",
        "hinglish": "Theek hai, {line} card se hata diya. Sahi figure bhejein.",
    },
    # -- a module the company has switched off (WA-07; request 143: in their language) --
    "module.off.admin": {
        "english": "{name} {verb} switched on for your company yet, so I didn't record this. Ask your admin to turn {pronoun} on.",
        "manglish": "{name} ningalude company-kku ippo on cheythittilla, athukondu ithu record cheythilla. Ningalude admin-inodu on aakkan parayu.",
        "malayalam": "{name} നിങ്ങളുടെ കമ്പനിക്ക് ഇതുവരെ ഓൺ ചെയ്തിട്ടില്ല, അതുകൊണ്ട് ഇത് രേഖപ്പെടുത്തിയില്ല. ഓൺ ആക്കാൻ നിങ്ങളുടെ അഡ്മിനോട് പറയൂ.",
        "hindi": "{name} आपकी कंपनी के लिए अभी चालू नहीं है, इसलिए यह दर्ज नहीं हुआ. अपने एडमिन से चालू करने को कहें.",
        "hinglish": "{name} aapki company ke liye abhi on nahi hai, isliye yeh record nahi hua. Apne admin se on karne ko kahein.",
    },
    "module.off.team": {
        "english": "{name} {verb} switched on for your company yet, so I didn't record this. Ask the Mesiri team to turn {pronoun} on.",
        "manglish": "{name} ningalude company-kku ippo on cheythittilla, athukondu ithu record cheythilla. Mesiri team-inodu on aakkan parayu.",
        "malayalam": "{name} നിങ്ങളുടെ കമ്പനിക്ക് ഇതുവരെ ഓൺ ചെയ്തിട്ടില്ല, അതുകൊണ്ട് ഇത് രേഖപ്പെടുത്തിയില്ല. ഓൺ ആക്കാൻ മെസിരി ടീമിനോട് പറയൂ.",
        "hindi": "{name} आपकी कंपनी के लिए अभी चालू नहीं है, इसलिए यह दर्ज नहीं हुआ. Mesiri टीम से चालू करने को कहें.",
        "hinglish": "{name} aapki company ke liye abhi on nahi hai, isliye yeh record nahi hua. Mesiri team se on karne ko kahein.",
    },
    # -- the "Received or used?" question (request 143: in their language, with Cancel) --
    "material.direction": {
        "english": "Did {what} come in, or was it used?",
        "manglish": "{what} vannatho, use cheythatho?",
        "malayalam": "{what} വന്നതോ, ഉപയോഗിച്ചതോ?",
        "hindi": "{what} आया या इस्तेमाल हुआ?",
        "hinglish": "{what} aaya ya use hua?",
    },
    "photo.purpose": {
        "english": "📷 What is this photo for?",
        "manglish": "📷 Ee photo enthinaanu?",
        "malayalam": "📷 ഈ ഫോട്ടോ എന്തിനാണ്?",
        "hindi": "📷 यह फोटो किसलिए है?",
        "hinglish": "📷 Yeh photo kis liye hai?",
    },
    "photo.waiting": {
        "english": "📷 {count} {noun} you sent are still waiting. What {is_are} for?",
        "manglish": "📷 Ningal ayacha {count} photo ippozhum kaathirikkunnu. Enthinaanu?",
        "malayalam": "📷 നിങ്ങൾ അയച്ച {count} ഫോട്ടോ ഇപ്പോഴും കാത്തിരിക്കുന്നു. എന്തിനാണ്?",
        "hindi": "📷 आपकी भेजी {count} फोटो अभी इंतज़ार में हैं. किसलिए हैं?",
        "hinglish": "📷 Aapki bheji {count} photo abhi wait kar rahi hain. Kis liye hain?",
    },
    "material.direction_cancelled": {
        "english": "Okay, nothing saved.",
        "manglish": "Sheri, onnum save cheythilla.",
        "malayalam": "ശരി, ഒന്നും സേവ് ചെയ്തില്ല.",
        "hindi": "ठीक है, कुछ सेव नहीं हुआ.",
        "hinglish": "Theek hai, kuch save nahi hua.",
    },
}


def say(key: str, language: str, **values: str) -> str:
    """The line ``key`` in ``language`` (English when it has none), filled in."""
    lines = LINES[key]
    return lines.get(language, lines["english"]).format(**values)
