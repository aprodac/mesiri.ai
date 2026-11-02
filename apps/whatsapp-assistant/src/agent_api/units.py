"""WA-124 follow-up (request 203): a unit the model names becomes a real unit id, in code.

``unit_id`` goes to the API as a UUID of an active unit. The model was handed no ids (the
units list answers ``{"items": [...]}``, which the facts read as nothing), so it wrote
"bags" or an invented id and the API refused every material line. The words people use
("bags", "chaakku", "nos", "ennam") are matched here, through the shared unit-word table
the card path uses (``runtime.unit_words``), so there is one resolver, not a second one.
"""

from __future__ import annotations

import uuid
from typing import Any


def unit_rows(body: Any) -> list[dict[str, Any]]:
    """The units from the API's answer: ``{"items": [...]}`` (what it sends) or a bare list."""
    rows = body.get("items") if isinstance(body, dict) else body
    return [u for u in rows or [] if isinstance(u, dict) and u.get("id") and u.get("is_active", True)]


def resolve_unit(units: list[dict[str, Any]], value: Any) -> dict[str, Any] | None:
    """The active unit ``value`` names (its id, code, display name, or a word sites use), else None."""
    from runtime.unit_words import canonical_unit, fold

    text = str(value or "").strip()
    if not text:
        return None
    for unit in units:
        if str(unit["id"]).casefold() == text.casefold():
            return unit
    word = fold(text)
    for unit in units:
        if word and word in (fold(unit.get("code")), fold(unit.get("display_name"))):
            return unit
    canon = canonical_unit(text)
    if canon:
        for unit in units:
            if canonical_unit(unit.get("code")) == canon or fold(unit.get("code")) == fold(canon):
                return unit
    return None


def is_uuid(value: Any) -> bool:
    try:
        uuid.UUID(str(value))
    except ValueError:
        return False
    return True


def unit_choices(units: list[dict[str, Any]], limit: int = 12) -> str:
    return ", ".join(str(u.get("code") or u.get("display_name")) for u in units[:limit])


# What the person is told when the API refuses a line: plain words, their language, the line kept.
_PLAIN = {
    "english": "I could not save this line. Tell me what is missing or wrong and I will fix it.",
    "manglish": "Ee line save cheyyan pattiyilla. Entha illathathu ennu para, njan sheriyakkam.",
    "malayalam": "ഈ വരി സേവ് ചെയ്യാൻ പറ്റിയില്ല. എന്താണ് കുറവെന്ന് പറയൂ, ഞാൻ ശരിയാക്കാം.",
    "hinglish": "Yeh line save nahi ho saki. Bataiye kya missing hai, main theek kar dunga.",
    "hindi": "यह लाइन सेव नहीं हो सकी। बताइए क्या कमी है, मैं ठीक कर दूंगा।",
}
_UNIT = {
    "english": "I am not sure which unit this is (bags, kg, nos...). Tell me the unit and I will fix this line.",
    "manglish": "Ethu unit aanennu urappilla (bag, kg, nos...). Unit para, njan ee line sheriyakkam.",
    "malayalam": "ഏത് യൂണിറ്റ് ആണെന്ന് ഉറപ്പില്ല (ചാക്ക്, കിലോ, എണ്ണം...). യൂണിറ്റ് പറയൂ, ഞാൻ ശരിയാക്കാം.",
    "hinglish": "Yeh kaunsa unit hai pata nahi (bag, kg, nos...). Unit bataiye, main line theek kar dunga.",
    "hindi": "यह कौन सी इकाई है पता नहीं (बैग, किलो, नग...)। इकाई बताइए, मैं ठीक कर दूंगा।",
}


def plain_refusal(reason: str, language: str | None) -> str:
    """The API's refusal as something a site person can act on; never the raw validation text."""
    lang = language if language in _PLAIN else "english"
    low = reason.casefold()
    if "unit" in low and ("valid" in low or "match" in low or "stock unit" in low):
        return _UNIT[lang]
    if reason and not any(t in low for t in ("_id", "valid", "uuid", "field", "422", "must be")):
        return reason[:160]  # already written for people (stock too low, not allowed)
    return _PLAIN[lang]
