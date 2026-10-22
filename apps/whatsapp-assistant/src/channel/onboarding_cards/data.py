"""View models for the onboarding cards. Pure: plain inputs in, text out.

English and Malayalam. The example messages the owner is asked to send stay
in Manglish in both ("6 mason, 10 helper vannu"): that is how people type it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Lang = Literal["en", "ml"]

#: The six setup steps, in the order they are asked.
STEP_KEYS: tuple[str, ...] = (
    "company_site",
    "first_update",
    "materials",
    "logo",
    "site_engineer",
    "report_time",
)

#: The example the owner sends for their first update (also the card 2 action).
FIRST_UPDATE_EXAMPLE = "6 mason, 10 helper vannu"
STOCK_EXAMPLE = "cement stock ethra?"

_MINUTES_PER_STEP = 1

_WELCOME = {
    "en": {
        "type": "WELCOME",
        "kicker": "Your site, on WhatsApp",
        "headline": "Tell me what happened. I keep the records.",
        "rows": (
            ("Tell", f"“{FIRST_UPDATE_EXAMPLE}”"),
            ("Ask", f"“{STOCK_EXAMPLE}”"),
            ("Get", "today’s report as a PDF"),
        ),
        "footer": "Type or send a voice note · Malayalam or English",
    },
    "ml": {
        "type": "സ്വാഗതം",
        "kicker": "നിങ്ങളുടെ സൈറ്റ്, വാട്ട്സ്ആപ്പിൽ",
        "headline": "എന്താണ് നടന്നതെന്ന് പറയൂ. റെക്കോർഡുകൾ ഞാൻ സൂക്ഷിക്കാം.",
        "rows": (
            ("പറയൂ", f"“{FIRST_UPDATE_EXAMPLE}”"),
            ("ചോദിക്കൂ", f"“{STOCK_EXAMPLE}”"),
            ("നേടൂ", "ഇന്നത്തെ റിപ്പോർട്ട് PDF ആയി"),
        ),
        "footer": "ടൈപ്പ് ചെയ്യൂ അല്ലെങ്കിൽ വോയ്സ് നോട്ട് അയയ്ക്കൂ · മലയാളം അല്ലെങ്കിൽ ഇംഗ്ലീഷ്",
    },
}

_READY = {
    "en": {
        "type": "SITE READY",
        "live": "{site} is live.",
        "company": "Company",
        "site": "Site",
        "report": "Daily report at {time}",
        "on": "On",
        "action": "TRY IT NOW",
        "send": "Send:",
    },
    "ml": {
        "type": "സൈറ്റ് തയ്യാർ",
        "live": "{site} തയ്യാറായി.",
        "company": "കമ്പനി",
        "site": "സൈറ്റ്",
        "report": "ദിവസേനയുള്ള റിപ്പോർട്ട് {time}",
        "on": "ഓൺ",
        "action": "ഇപ്പോൾ പരീക്ഷിക്കൂ",
        "send": "അയയ്ക്കൂ:",
    },
}

_PROGRESS = {
    "en": {
        "type": "SETUP",
        "left": "{site} · about {minutes} min left",
        "all_done": "{site} · all set",
        "action": "NEXT",
        "done_action": "ALL SET",
        "done_send": "Your site is ready. Keep sending updates.",
        "send": "Send:",
        "steps": {
            "company_site": "Company & site",
            "first_update": "First site update",
            "materials": "Materials list",
            "logo": "Company logo",
            "site_engineer": "Site engineer",
            "report_time": "Report time set",
        },
        "next": {
            "first_update": FIRST_UPDATE_EXAMPLE,
            "materials": "add material: TMT steel 12mm",
            "logo": "your logo as a photo, caption: company logo",
            "site_engineer": "a contact card of your site engineer",
            "report_time": "tap 7 pm, 8 pm or 9 pm below",
        },
        "next_send": {"report_time": "Do this:", "site_engineer": "Share:"},
    },
    "ml": {
        "type": "സെറ്റപ്പ്",
        "left": "{site} · ഏകദേശം {minutes} മിനിറ്റ് ബാക്കി",
        "all_done": "{site} · എല്ലാം തയ്യാർ",
        "action": "അടുത്തത്",
        "done_action": "എല്ലാം തയ്യാർ",
        "done_send": "സൈറ്റ് തയ്യാറാണ്. അപ്ഡേറ്റുകൾ അയച്ചുകൊണ്ടിരിക്കൂ.",
        "send": "അയയ്ക്കൂ:",
        "steps": {
            "company_site": "കമ്പനിയും സൈറ്റും",
            "first_update": "ആദ്യ സൈറ്റ് അപ്ഡേറ്റ്",
            "materials": "മെറ്റീരിയൽ ലിസ്റ്റ്",
            "logo": "കമ്പനി ലോഗോ",
            "site_engineer": "സൈറ്റ് എഞ്ചിനീയർ",
            "report_time": "റിപ്പോർട്ട് സമയം",
        },
        "next": {
            "first_update": FIRST_UPDATE_EXAMPLE,
            "materials": "add material: TMT steel 12mm",
            "logo": "നിങ്ങളുടെ ലോഗോ ഫോട്ടോ, caption: company logo",
            "site_engineer": "സൈറ്റ് എഞ്ചിനീയറുടെ contact card",
            "report_time": "താഴെ 7 pm, 8 pm അല്ലെങ്കിൽ 9 pm തൊടൂ",
        },
        "next_send": {"report_time": "ചെയ്യൂ:", "site_engineer": "പങ്കിടൂ:"},
    },
}


@dataclass(frozen=True, slots=True)
class WelcomeCard:
    lang: Lang
    header: str
    kicker: str
    headline: str
    rows: tuple[tuple[str, str], ...]
    footer: str


@dataclass(frozen=True, slots=True)
class ReadyCard:
    lang: Lang
    header: str
    headline: str
    subline: str
    rows: tuple[tuple[str, str | None, bool], ...]  # label, value, done
    action_label: str
    action_text: str


@dataclass(frozen=True, slots=True)
class ProgressFacts:
    """What is done, read from existing data (the six setup steps)."""

    company_site: bool = True  # the card is only ever sent to an existing company
    first_update: bool = False
    materials: bool = False
    logo: bool = False
    site_engineer: bool = False
    report_time: bool = False

    def done(self, key: str) -> bool:
        return bool(getattr(self, key))

    def done_keys(self) -> tuple[str, ...]:
        return tuple(k for k in STEP_KEYS if self.done(k))

    def first_pending(self) -> str | None:
        return next((k for k in STEP_KEYS if not self.done(k)), None)


@dataclass(frozen=True, slots=True)
class ProgressCard:
    lang: Lang
    header: str
    done: int
    total: int
    subline: str
    steps: tuple[tuple[str, bool], ...]
    action_label: str
    action_text: str
    next_step: str | None  # key of the first pending step, None when all done


def _clean(value: str | None) -> str:
    return " ".join(str(value or "").split())


def split_site(site_name: str) -> tuple[str, str]:
    """"Green Villa, Kakkanad" -> ("Green Villa", "Kakkanad"); no place -> ""."""
    name, _, place = _clean(site_name).partition(",")
    return name.strip() or _clean(site_name), place.strip()


def build_welcome_card(lang: Lang = "en") -> WelcomeCard:
    t = _WELCOME[lang]
    return WelcomeCard(
        lang=lang,
        header=f"MESIRI · {t['type']}",
        kicker=t["kicker"],
        headline=t["headline"],
        rows=t["rows"],
        footer=t["footer"],
    )


def build_ready_card(
    *, company: str, site_name: str, report_time: str = "9 pm", lang: Lang = "en"
) -> ReadyCard:
    t = _READY[lang]
    site, place = split_site(site_name)
    company = _clean(company)
    return ReadyCard(
        lang=lang,
        header=f"MESIRI · {t['type']}",
        headline=t["live"].format(site=site),
        subline=f"{company} · {place}" if place else company,
        rows=(
            (t["company"], None, True),
            (t["site"], None, True),
            (t["report"].format(time=report_time), t["on"], True),
        ),
        action_label=t["action"],
        action_text=f"{t['send']} {FIRST_UPDATE_EXAMPLE}",
    )


def build_progress_card(*, site_name: str, facts: ProgressFacts, lang: Lang = "en") -> ProgressCard:
    t = _PROGRESS[lang]
    site, _ = split_site(site_name)
    steps = tuple((t["steps"][key], facts.done(key)) for key in STEP_KEYS)
    done = sum(1 for _, ok in steps if ok)
    pending = facts.first_pending()
    if pending is None:
        subline = t["all_done"].format(site=site)
        label, text = t["done_action"], t["done_send"]
    else:
        minutes = (len(STEP_KEYS) - done) * _MINUTES_PER_STEP
        subline = t["left"].format(site=site, minutes=minutes)
        verb = t["next_send"].get(pending, t["send"])
        label, text = t["action"], f"{verb} {t['next'][pending]}"
    return ProgressCard(
        lang=lang,
        header=f"MESIRI · {t['type']}",
        done=done,
        total=len(STEP_KEYS),
        subline=subline,
        steps=steps,
        action_label=label,
        action_text=text,
        next_step=pending,
    )
