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
        "english": "📅 Bill date {day}? Today is {today}.",
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
    # -- request 198: a Save the system failed under keeps the line and says what to tap --
    "save.failed_retry": {
        "english": "Nothing was saved. {line} is still here: something went wrong on our side. Tap Save to try again, or Cancel.",
        "manglish": "Onnum save aayilla. {line} ivide thanne und: nammude bhagath ninnu oru prashnam vannu. Veendum Save tap cheyyu, allenkil Cancel.",
        "malayalam": "ഒന്നും സേവ് ആയില്ല. {line} ഇവിടെ തന്നെയുണ്ട്: ഞങ്ങളുടെ ഭാഗത്ത് ഒരു പ്രശ്നം വന്നു. വീണ്ടും Save അമർത്തുക, അല്ലെങ്കിൽ Cancel.",
        "hindi": "कुछ सेव नहीं हुआ. {line} यहीं है: हमारी तरफ़ से कोई गड़बड़ हुई. फिर से Save दबाएं, या Cancel.",
        "hinglish": "Kuch save nahi hua. {line} yahin hai: hamari taraf se kuch gadbad hui. Phir se Save dabaiye, ya Cancel.",
    },
    "check.change_date": {
        "english": "Okay, {line} is off the list. Send it again with the right date.",
        "manglish": "Sheri, {line} list-il ninnu maatti. Shariyaaya date koode ayakku.",
        "malayalam": "ശരി, {line} ലിസ്റ്റിൽ നിന്ന് മാറ്റി. ശരിയായ തീയതിയോടെ വീണ്ടും അയക്കൂ.",
        "hindi": "ठीक है, {line} लिस्ट से हटा दिया. सही तारीख के साथ फिर भेजें.",
        "hinglish": "Theek hai, {line} list se hata diya. Sahi date ke saath phir bhejein.",
    },
    "check.removed_repeat": {
        "english": "Okay, not saved twice: {line} stays saved once.",
        "manglish": "Sheri, randu thavana save cheyyilla: {line} oru thavana save aayittund.",
        "malayalam": "ശരി, രണ്ടു തവണ സേവ് ചെയ്യില്ല: {line} ഒരു തവണ സേവ് ആയിട്ടുണ്ട്.",
        "hindi": "ठीक है, दो बार सेव नहीं होगा: {line} एक बार सेव है.",
        "hinglish": "Theek hai, do baar save nahi hoga: {line} ek baar save hai.",
    },
    # -- request 162: a removal correction and a tap on an old card, in their language --
    "remove.done": {
        "english": "👍 Okay, {line} is off the list.",
        "manglish": "👍 Sheri, {line} list-il ninnu maattiyittund.",
        "malayalam": "👍 ശരി, {line} ലിസ്റ്റിൽ നിന്ന് മാറ്റി.",
        "hindi": "👍 ठीक है, {line} लिस्ट से हटा दिया.",
        "hinglish": "👍 Theek hai, {line} list se hata diya.",
    },
    "remove.rebuilt": {
        "english": "👍 Okay, without {line}. Here is what's left, tap Save if it's right:",
        "manglish": "👍 Sheri, {line} illathe. Baakki ithaanu, sheriyaanenkil Save tap cheyyu:",
        "malayalam": "👍 ശരി, {line} ഒഴികെ. ബാക്കി ഇതാണ്, ശരിയാണെങ്കിൽ Save അമർത്തുക:",
        "hindi": "👍 ठीक है, {line} के बिना. बाकी यह है, सही हो तो Save दबाएँ:",
        "hinglish": "👍 Theek hai, {line} ke bina. Baaki yeh hai, sahi ho to Save dabayein:",
    },
    "remove.empty": {
        "english": "👍 Okay, {line} is off, and nothing is left on the list. Nothing was saved.",
        "manglish": "👍 Sheri, {line} maattiyittund, list-il onnum baakkiyilla. Onnum save aayittilla.",
        "malayalam": "👍 ശരി, {line} മാറ്റി, ലിസ്റ്റിൽ ഒന്നും ബാക്കിയില്ല. ഒന്നും സേവ് ആയിട്ടില്ല.",
        "hindi": "👍 ठीक है, {line} हटा दिया, लिस्ट पर कुछ नहीं बचा. कुछ सेव नहीं हुआ.",
        "hinglish": "👍 Theek hai, {line} hata diya, list par kuch nahi bacha. Kuch save nahi hua.",
    },
    "tap.old_card": {
        "english": "That one was already cancelled. Here's what I have now:",
        "manglish": "Athu munpe cancel cheythirunnu. Ippol ullath ithaanu:",
        "malayalam": "അത് നേരത്തെ ക്യാൻസൽ ചെയ്തിരുന്നു. ഇപ്പോൾ ഉള്ളത് ഇതാണ്:",
        "hindi": "वह पहले ही कैंसल हो चुका था. अभी यह है:",
        "hinglish": "Woh pehle hi cancel ho chuka tha. Abhi yeh hai:",
    },
    "tap.nothing_open": {
        "english": "That one was already cancelled, and nothing is open now. Nothing was saved. Send it again whenever you're ready.",
        "manglish": "Athu munpe cancel cheythirunnu, ippol onnum open alla. Onnum save aayittilla. Ready aakumbol veendum ayakku.",
        "malayalam": "അത് നേരത്തെ ക്യാൻസൽ ചെയ്തിരുന്നു, ഇപ്പോൾ ഒന്നും തുറന്നിട്ടില്ല. ഒന്നും സേവ് ആയിട്ടില്ല. തയ്യാറാകുമ്പോൾ വീണ്ടും അയക്കുക.",
        "hindi": "वह पहले ही कैंसल हो चुका था, अभी कुछ खुला नहीं है. कुछ सेव नहीं हुआ. तैयार हों तो फिर भेजें.",
        "hinglish": "Woh pehle hi cancel ho chuka tha, abhi kuch open nahi hai. Kuch save nahi hua. Ready ho to dobara bhejein.",
    },
    "cancel.rest": {
        "english": "❌ Cancelled the rest. Already saved: {saved}.",
        "manglish": "❌ Baakki cancel cheythu. Save aayath: {saved}.",
        "malayalam": "❌ ബാക്കി ക്യാൻസൽ ചെയ്തു. സേവ് ആയത്: {saved}.",
        "hindi": "❌ बाकी कैंसल किया. पहले से सेव है: {saved}.",
        "hinglish": "❌ Baaki cancel kiya. Pehle se save hai: {saved}.",
    },
    "check.change": {
        "english": "Okay, {line} is off the list. Send the right figure.",
        "manglish": "Sheri, {line} list-il ninnu maatti. Shariyaaya figure ayakku.",
        "malayalam": "ശരി, {line} ലിസ്റ്റിൽ നിന്ന് മാറ്റി. ശരിയായ കണക്ക് അയക്കൂ.",
        "hindi": "ठीक है, {line} लिस्ट से हटा दिया. सही आँकड़ा भेजें.",
        "hinglish": "Theek hai, {line} list se hata diya. Sahi figure bhejein.",
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
    "read.all_sites": {
        "english": "All your sites",
        "manglish": "Ningalude ellaa site-um",
        "malayalam": "നിങ്ങളുടെ എല്ലാ സൈറ്റുകളും",
        "hindi": "आपकी सभी साइट",
        "hinglish": "Aapki saari sites",
    },
    "material_request.not_built_card": {
        # Item 195: said under a card that HAS lines, so it never says "nothing was saved".
        "english": "Material requests aren't in Mesiri yet, so that part is not added below.",
        "manglish": "Material request ippo Mesiri-il illa, athukondu aa bhagam thazhe cherkkunnilla.",
        "malayalam": "മെറ്റീരിയൽ റിക്വസ്റ്റ് ഇപ്പോൾ Mesiri-യിൽ ഇല്ല, അതിനാൽ ആ ഭാഗം താഴെ ചേർക്കുന്നില്ല.",
        "hindi": "मटेरियल रिक्वेस्ट अभी Mesiri में नहीं है, इसलिए वह हिस्सा नीचे नहीं जोड़ा.",
        "hinglish": "Material request abhi Mesiri mein nahi hai, isliye woh hissa neeche nahi joda.",
    },
    "material_request.not_built": {
        "english": "Material requests aren't in Mesiri yet, so nothing was saved. To record what is on site, send what arrived or was used.",
        "manglish": "Material request ippo Mesiri-il illa, athukondu onnum save cheythilla. Site-il vanna / use cheytha material ayakku.",
        "malayalam": "മെറ്റീരിയൽ റിക്വസ്റ്റ് ഇപ്പോൾ Mesiri-യിൽ ഇല്ല, അതിനാൽ ഒന്നും സേവ് ചെയ്തില്ല.",
        "hindi": "मटेरियल रिक्वेस्ट अभी Mesiri में नहीं है, इसलिए कुछ सेव नहीं हुआ.",
        "hinglish": "Material request abhi Mesiri mein nahi hai, isliye kuch save nahi hua.",
    },
    "change.refused": {
        "english": "I couldn't change that line, so it stays as it is below. Tell me the new name or figure once more.",
        "manglish": "Aa line maattan pattiyilla, athu thazhe pazhayathu thanne. Puthiya peru/figure onnu koodi parayamo.",
        "malayalam": "ആ വരി മാറ്റാൻ കഴിഞ്ഞില്ല, താഴെ പഴയതുപോലെ തന്നെ. പുതിയ പേരോ കണക്കോ ഒന്നുകൂടി പറയാമോ.",
        "hindi": "वह लाइन बदली नहीं जा सकी, नीचे वह पहले जैसी ही है। नया नाम या आँकड़ा एक बार फिर बताइए।",
        "hinglish": "Woh line change nahi ho saki, neeche woh pehle jaisi hi hai. Naya naam ya figure ek baar phir batao.",
    },
    "v2.repeat_reply": {
        "english": "Sorry, that is what I just told you, so it is not what you need. Tell me again in a few words what you want and I will answer only that.",
        "manglish": "Sorry, ithu thanneyaanu njan ippo paranjathu, athu ningalkku venda ennu manasilaayi. Enthaanu venamennu chuttathil onnu koodi parayamo, njan athinu mathram marupadi tharam.",
        "malayalam": "ക്ഷമിക്കണം, ഞാൻ ഇപ്പോൾ പറഞ്ഞത് തന്നെയാണിത്, അത് നിങ്ങൾക്ക് വേണ്ടതല്ല. എന്താണ് വേണ്ടതെന്ന് ഒന്നുകൂടി ചുരുക്കി പറയാമോ, ഞാൻ അതിന് മാത്രം മറുപടി തരാം.",
        "hindi": "माफ़ कीजिए, यही मैंने अभी कहा था, यह आपको नहीं चाहिए। कृपया थोड़े शब्दों में फिर बताइए, मैं सिर्फ़ उसी का जवाब दूँगा।",
        "hinglish": "Sorry, yahi maine abhi bola tha, woh aapko nahi chahiye. Thode shabdon mein phir batao, main sirf usi ka jawab dunga.",
    },
    "voice.cant_hear": {
        "english": "I couldn't hear that clearly. Could you say it once more?",
        "manglish": "Shabdam vyakthamaayilla, onnu koodi parayamo?",
        "malayalam": "ശബ്ദം വ്യക്തമായില്ല, ഒന്നു കൂടി പറയാമോ?",
        "hindi": "आवाज़ साफ़ नहीं सुनाई दी, एक बार फिर बोलेंगे?",
        "hinglish": "Awaaz saaf nahi aayi, ek baar phir bolenge?",
    },
    "api.cancelled_why": {
        "english": "Cancelled. Nothing was saved. What was wrong? (one tap helps us fix it)",
        "manglish": "Cancel cheythu. Onnum save aayilla. Enthaanu thettiyathu? (oru tap mathi, njangal sheriyaakkaam)",
        "malayalam": "ക്യാൻസൽ ചെയ്തു. ഒന്നും സേവ് ആയില്ല. എന്താണ് തെറ്റിയത്? (ഒരു ടാപ്പ് മതി)",
        "hindi": "रद्द कर दिया। कुछ सेव नहीं हुआ। क्या गलत था? (एक टैप से हमें ठीक करने में मदद मिलेगी)",
        "hinglish": "Cancel kar diya. Kuch save nahi hua. Kya galat tha? (ek tap se humein theek karne mein madad milegi)",
    },
    "api.cancel_noted": {
        "english": "Thanks 👍 I've told the team. Send it again the right way and I'll get it ready.",
        "manglish": "Thanks 👍 Team-ne ariyichu. Sheriyaaya reethiyil onnu koodi ayakkoo, njan ready aakkaam.",
        "malayalam": "നന്ദി 👍 ടീമിനെ അറിയിച്ചു. ശരിയായി ഒന്നുകൂടി അയക്കൂ, ഞാൻ തയ്യാറാക്കാം.",
        "hindi": "धन्यवाद 👍 टीम को बता दिया। सही तरीके से फिर भेजिए, मैं तैयार कर दूँगा।",
        "hinglish": "Thanks 👍 Team ko bata diya. Sahi tarike se phir bhejiye, main ready kar dunga.",
    },
    "api.cancel_other": {
        "english": "Thanks. What was wrong? Send it as a message or a voice note.",
        "manglish": "Thanks. Enthaanu thettiyathu? Message aayo voice note aayo ayakkoo.",
        "malayalam": "നന്ദി. എന്താണ് തെറ്റിയത്? മെസ്സേജ് ആയോ വോയ്സ് നോട്ട് ആയോ അയക്കൂ.",
        "hindi": "धन्यवाद। क्या गलत था? मैसेज या वॉइस नोट भेजिए।",
        "hinglish": "Thanks. Kya galat tha? Message ya voice note bhejiye.",
    },
    "api.feedback_ask": {
        "english": "Sorry 🙏 I've passed it to the team. How should it be instead? Send it as a message or a voice note; you'll see how it will look before it changes.",
        "manglish": "Sorry 🙏 Team-nu koduthu. Ithu engane aayirikkanam? Message aayo voice note aayo ayakkoo; maattunnathinu munpu ethu pole aakum ennu kaanikkaam.",
        "malayalam": "ക്ഷമിക്കണം 🙏 ടീമിന് കൊടുത്തു. ഇത് എങ്ങനെ ആയിരിക്കണം? മെസ്സേജ് ആയോ വോയ്സ് നോട്ട് ആയോ അയക്കൂ; മാറ്റുന്നതിനു മുൻപ് എങ്ങനെ ആകുമെന്ന് കാണിക്കാം.",
        "hindi": "माफ़ कीजिए 🙏 मैंने टीम को बता दिया है। इसे कैसा होना चाहिए? मैसेज या वॉइस नोट भेजिए; बदलने से पहले आपको दिखा देंगे कि यह कैसा दिखेगा।",
        "hinglish": "Sorry 🙏 Maine team ko bata diya. Ise kaisa hona chahiye? Message ya voice note bhejiye; badalne se pehle aapko dikha denge ki ye kaisa dikhega.",
    },
    # -- [219]: a project they already have (said by the code; never an offer to make another) --
    "api.project_exists": {
        "english": "{name} already exists ✅",
        "manglish": "{name} ippo thanne undu ✅",
        "malayalam": "{name} ഇപ്പോൾ തന്നെ ഉണ്ട് ✅",
        "hindi": "{name} पहले से है ✅",
        "hinglish": "{name} pehle se hai ✅",
    },
    "api.project_twins": {
        "english": "({count} of them: please tidy them up on the dashboard)",
        "manglish": "({count} ennam undu: dashboard-il onnaakkoo)",
        "malayalam": "({count} എണ്ണം ഉണ്ട്: ഡാഷ്ബോർഡിൽ ഒന്നാക്കൂ)",
        "hindi": "({count} हैं: कृपया डैशबोर्ड पर ठीक कर लें)",
        "hinglish": "({count} hain: please dashboard par theek kar lein)",
    },
    "api.feedback_noted": {
        "english": "Thanks 🙏 I've passed it to the team. You'll see how it will look, and I'll tell you here when it's fixed.",
        "manglish": "Thanks 🙏 Team-nu koduthu. Ethu pole aakum ennu kaanikkaam, sheriyaakumbol ivide ariyikkaam.",
        "malayalam": "നന്ദി 🙏 ടീമിന് കൊടുത്തു. എങ്ങനെ ആകുമെന്ന് കാണിക്കാം, ശരിയാകുമ്പോൾ ഇവിടെ അറിയിക്കാം.",
        "hindi": "धन्यवाद 🙏 मैंने टीम को बता दिया है। आपको दिखा देंगे कि यह कैसा दिखेगा, और ठीक होने पर यहीं बताएँगे।",
        "hinglish": "Thanks 🙏 Maine team ko bata diya. Aapko dikha denge ki ye kaisa dikhega, aur theek hone par yahin batayenge.",
    },
    "api.feedback_got_why": {
        "english": "Thanks 👍 Added to your request. You'll see how it will look before it changes.",
        "manglish": "Thanks 👍 Ningalude request-il cherthu. Maattunnathinu munpu ethu pole aakum ennu kaanikkaam.",
        "malayalam": "നന്ദി 👍 നിങ്ങളുടെ അഭ്യർത്ഥനയിൽ ചേർത്തു. മാറ്റുന്നതിനു മുൻപ് എങ്ങനെ ആകുമെന്ന് കാണിക്കാം.",
        "hindi": "धन्यवाद 👍 आपकी रिक्वेस्ट में जोड़ दिया। बदलने से पहले आपको दिखा देंगे कि यह कैसा दिखेगा।",
        "hinglish": "Thanks 👍 Aapki request mein jod diya. Badalne se pehle aapko dikha denge ki ye kaisa dikhega.",
    },
    "api.thanks": {
        "english": "Thanks 👍",
        "manglish": "Thanks 👍",
        "malayalam": "നന്ദി 👍",
        "hindi": "धन्यवाद 👍",
        "hinglish": "Thanks 👍",
    },
    "preview.ask": {
        "english": "👀 *Preview* of the change you asked for. Is this how you want it? We're already building it.",
        "manglish": "👀 Ningal chodicha maattathinte *preview*. Ingane aano venda? Njangal ithu undaakki thudangi.",
        "malayalam": "👀 നിങ്ങൾ ചോദിച്ച മാറ്റത്തിന്റെ *പ്രിവ്യൂ*. ഇങ്ങനെയാണോ വേണ്ടത്? ഞങ്ങൾ ഇത് ഉണ്ടാക്കി തുടങ്ങി.",
        "hindi": "👀 आपने जो बदलाव माँगा, उसका *प्रीव्यू*। क्या आपको ऐसा ही चाहिए? हम इसे बना रहे हैं।",
        "hinglish": "👀 Aapne jo badlav maanga, uska *preview*. Kya aapko aisa hi chahiye? Hum ise bana rahe hain.",
    },
    "preview.confirm": {
        "english": "Confirm ✅", "manglish": "Sheri ✅", "malayalam": "ശരി ✅", "hindi": "ठीक है ✅", "hinglish": "Theek hai ✅",
    },
    "preview.change": {
        "english": "Change it ✏️", "manglish": "Maattanam ✏️", "malayalam": "മാറ്റണം ✏️", "hindi": "बदलना है ✏️", "hinglish": "Badalna hai ✏️",
    },
    "preview.confirmed": {
        "english": "Thanks 👍 We'll finish it like that and message you here when it's live.",
        "manglish": "Thanks 👍 Ingane thanne theerkkaam, live aakumbol ivide ariyikkaam.",
        "malayalam": "നന്ദി 👍 ഇങ്ങനെ തന്നെ തീർക്കാം, ലൈവ് ആകുമ്പോൾ ഇവിടെ അറിയിക്കാം.",
        "hindi": "धन्यवाद 👍 हम इसे ऐसे ही पूरा करेंगे और लाइव होने पर यहीं बताएँगे।",
        "hinglish": "Thanks 👍 Hum ise aise hi poora karenge aur live hone par yahin batayenge.",
    },
    "preview.what_change": {
        "english": "Sure. What should be different? Send it as a message or a voice note and I'll pass it to the team building it.",
        "manglish": "Sheri. Enthaanu maattendathu? Message aayo voice note aayo ayakkoo, njan team-nu kodukkaam.",
        "malayalam": "ശരി. എന്താണ് മാറ്റേണ്ടത്? മെസ്സേജ് ആയോ വോയ്സ് നോട്ട് ആയോ അയക്കൂ, ഞാൻ ടീമിന് കൊടുക്കാം.",
        "hindi": "ठीक है। क्या अलग होना चाहिए? मैसेज या वॉइस नोट भेजिए, मैं टीम को दे दूँगा।",
        "hinglish": "Theek hai. Kya alag hona chahiye? Message ya voice note bhejiye, main team ko de dunga.",
    },
    "release.works": {
        "english": "Thank you 👍 Glad it works.",
        "manglish": "Thanks 👍 Work aakunnundallo, santhosham.",
        "malayalam": "നന്ദി 👍 ശരിയായി പ്രവർത്തിക്കുന്നതിൽ സന്തോഷം.",
        "hindi": "धन्यवाद 👍 अच्छा लगा कि यह चल रहा है।",
        "hinglish": "Thanks 👍 Accha laga ki ye chal raha hai.",
    },
    "release.still_wrong": {
        "english": "Sorry 🙏 I've told the team it's still not right. What is still wrong? Send it as a message or a voice note.",
        "manglish": "Sorry 🙏 Ippozhum sheriyalla ennu team-ne ariyichu. Enthaanu ippozhum thettu? Message aayo voice note aayo ayakkoo.",
        "malayalam": "ക്ഷമിക്കണം 🙏 ഇപ്പോഴും ശരിയല്ലെന്ന് ടീമിനെ അറിയിച്ചു. എന്താണ് ഇപ്പോഴും തെറ്റ്? മെസ്സേജ് ആയോ വോയ്സ് നോട്ട് ആയോ അയക്കൂ.",
        "hindi": "माफ़ कीजिए 🙏 मैंने टीम को बता दिया है कि यह अभी भी ठीक नहीं है। क्या अभी भी गलत है? मैसेज या वॉइस नोट भेजिए।",
        "hinglish": "Sorry 🙏 Maine team ko bata diya ki ye abhi bhi theek nahi hai. Kya abhi bhi galat hai? Message ya voice note bhejiye.",
    },
    "outage.budget": {
        "english": "Got it 👍 Mesiri's AI is paused for a short while (the team has been told). Your message is kept and I'll do it as soon as it's back.",
        "manglish": "Sheri 👍 Mesiri-yude AI kurachu neram nirthi vechirikkunnu (team-ne ariyichu). Message sookshichittundu, thirichu vannal udane cheyyaam.",
        "malayalam": "ശരി 👍 Mesiri-യുടെ AI കുറച്ചു നേരം നിർത്തിയിരിക്കുന്നു (ടീമിനെ അറിയിച്ചു). സന്ദേശം സൂക്ഷിച്ചിട്ടുണ്ട്, തിരിച്ചു വന്നാൽ ഉടനെ ചെയ്യാം.",
        "hindi": "ठीक है 👍 Mesiri का AI थोड़ी देर के लिए रुका है (टीम को बता दिया है)। आपका संदेश रखा है, वापस आते ही कर दूँगा।",
        "hinglish": "Theek hai 👍 Mesiri ka AI thodi der ke liye ruka hai (team ko bata diya hai). Aapka message rakha hai, wapas aate hi kar dunga.",
    },
    "outage.queued": {
        "english": "Got it 👍 I'll process this in a few minutes.",
        "manglish": "Sheri 👍 njan ithu kurachu minutil cheyyaam.",
        "malayalam": "ശരി 👍 ഞാൻ ഇത് കുറച്ച് മിനിറ്റിനുള്ളിൽ ചെയ്യാം.",
        "hindi": "ठीक है 👍 मैं इसे कुछ मिनट में कर दूँगा.",
        "hinglish": "Theek hai 👍 main ise kuch minute mein kar dunga.",
    },
    "outage.gave_up": {
        "english": "Sorry, I couldn't process that message — nothing was saved. Please send it again in a little while.",
        "manglish": "Kshamikkanam, aa message process cheyyaan pattiyilla — onnum save cheythilla. Kurachu kazhinju onnu koodi ayakkamo.",
        "malayalam": "ക്ഷമിക്കണം, ആ സന്ദേശം പ്രോസസ് ചെയ്യാൻ കഴിഞ്ഞില്ല — ഒന്നും സേവ് ചെയ്തില്ല. കുറച്ചു കഴിഞ്ഞ് ഒന്നുകൂടി അയയ്ക്കാമോ.",
        "hindi": "माफ़ कीजिए, वह संदेश प्रोसेस नहीं हो सका — कुछ सेव नहीं हुआ. थोड़ी देर बाद फिर भेजिए.",
        "hinglish": "Sorry, woh message process nahi ho saka — kuch save nahi hua. Thodi der baad phir bhejo.",
    },
    "outage.resend": {
        "english": "I can't process messages right now — nothing was saved. Please send it again in a few minutes.",
        "manglish": "Ippo message process cheyyaan pattunnilla — onnum save cheythilla. Kurachu minuttu kazhinju onnu koodi ayakkamo.",
        "malayalam": "ഇപ്പോൾ സന്ദേശങ്ങൾ പ്രോസസ് ചെയ്യാൻ കഴിയുന്നില്ല — ഒന്നും സേവ് ചെയ്തില്ല. കുറച്ച് മിനിറ്റ് കഴിഞ്ഞ് ഒന്നുകൂടി അയയ്ക്കാമോ.",
        "hindi": "अभी संदेश प्रोसेस नहीं हो पा रहे — कुछ सेव नहीं हुआ. कुछ मिनट बाद फिर भेजिए.",
        "hinglish": "Abhi messages process nahi ho pa rahe — kuch save nahi hua. Kuch minute baad phir bhejo.",
    },
    "outage.not_now": {
        "english": "I couldn't work on that just now. Please send it again in a minute.",
        "manglish": "Ippo athu cheyyaan pattiyilla. Oru minute kazhinju onnu koodi ayakkamo.",
        "malayalam": "ഇപ്പോൾ അത് ചെയ്യാൻ കഴിഞ്ഞില്ല. ഒരു മിനിറ്റ് കഴിഞ്ഞ് ഒന്നുകൂടി അയയ്ക്കാമോ.",
        "hindi": "अभी इस पर काम नहीं हो सका. एक मिनट बाद फिर भेजिए.",
        "hinglish": "Abhi ispe kaam nahi ho saka. Ek minute baad phir bhejo.",
    },
    "photo.cant_read": {
        "english": "I couldn't read that photo. Please send it again, or type what it is.",
        "manglish": "Aa photo vaayikkaan pattiyilla. Onnu koodi ayakkamo, allenkil enthaanennu type cheyyamo.",
        "malayalam": "ആ ഫോട്ടോ വായിക്കാൻ കഴിഞ്ഞില്ല. ഒന്നുകൂടി അയയ്ക്കാമോ, അല്ലെങ്കിൽ എന്താണെന്ന് ടൈപ്പ് ചെയ്യാമോ.",
        "hindi": "वह फोटो पढ़ी नहीं जा सकी. फिर भेजिए, या लिखकर बताइए कि वह क्या है.",
        "hinglish": "Woh photo padhi nahi ja saki. Phir bhejo, ya type karke batao woh kya hai.",
    },
    "card.still_open": {
        "english": "Still to save:",
        "manglish": "Ippozhum save aakaanullathu:",
        "malayalam": "ഇനിയും സേവ് ചെയ്യാനുള്ളത്:",
        "hindi": "अभी सेव होना बाकी है:",
        "hinglish": "Abhi save hona baaki hai:",
    },
    "card.answer_failed": {
        "english": "I couldn't apply that answer.",
        "manglish": "Aa utharam edukkan pattiyilla.",
        "malayalam": "ആ ഉത്തരം എടുക്കാൻ കഴിഞ്ഞില്ല.",
        "hindi": "वह जवाब लागू नहीं हो सका.",
        "hinglish": "Woh jawab lagu nahi ho saka.",
    },
    "project.created": {
        "english": "Project {name} created ✅{size}. Send its updates now, or tell me what's next.",
        "manglish": "Project {name} undaakki ✅{size}. Ini ithinte updates ayakkaam, allenkil adutha karyam parayoo.",
        "malayalam": "പ്രോജക്റ്റ് {name} ഉണ്ടാക്കി ✅{size}. ഇനി ഇതിന്റെ അപ്ഡേറ്റുകൾ അയയ്ക്കാം, അല്ലെങ്കിൽ അടുത്തത് പറയൂ.",
        "hindi": "प्रोजेक्ट {name} बन गया ✅{size}. अब इसके अपडेट भेजिए, या बताइए आगे क्या करना है.",
        "hinglish": "Project {name} ban gaya ✅{size}. Ab iske updates bhejo, ya batao aage kya karna hai.",
    },
    "site.created": {
        "english": "Site {name} created under {project} ✅. Send its updates now, or tell me what's next.",
        "manglish": "{project}-il site {name} undaakki ✅. Ini ithinte updates ayakkaam, allenkil adutha karyam parayoo.",
        "malayalam": "{project}-ൽ സൈറ്റ് {name} ഉണ്ടാക്കി ✅. ഇനി ഇതിന്റെ അപ്ഡേറ്റുകൾ അയയ്ക്കാം, അല്ലെങ്കിൽ അടുത്തത് പറയൂ.",
        "hindi": "{project} में साइट {name} बन गई ✅. अब इसके अपडेट भेजिए, या बताइए आगे क्या करना है.",
        "hinglish": "{project} mein site {name} ban gayi ✅. Ab iske updates bhejo, ya batao aage kya karna hai.",
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
