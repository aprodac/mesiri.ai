"""MAT-07: "50 bags cement arrived" is a receipt; it is never asked.

The prompt says so, and the live model still asked "Received or used?" on a
clear message in 2 of 4 runs. The words that settle it are checked here, in
code: a message that says the material came and does not say it was used is a
receipt, whatever the model decided to ask or to call.
"""

from __future__ import annotations

import re

_RECEIVED = (
    r"came|come|arrived|arrive|arriving|delivered|delivery|received|receive|got|unloaded|reached|"
    r"vannu|vanu|vannittund|ethi|eththi|ethiyittund|irakki|irakkiyittund|aaya|mila|"
    r"aa gaya|aagaya|ആയി വന്നു|വന്നു|എത്തി|ഇറക്കി"
)
_USED = (
    r"used|use|uses|consumed|consume|spent|laga|lagaya|lag gaya|use cheythu|use aayi|"
    r"upayogichu|ഉപയോഗിച്ചു|ഉപയോഗം"
)
_WORD = r"(?<![\w]){}(?![\w])"
_RECEIVED_RE = re.compile(_WORD.format(f"(?:{_RECEIVED})"), re.IGNORECASE)
_USED_RE = re.compile(_WORD.format(f"(?:{_USED})"), re.IGNORECASE)
_ASKS_DIRECTION = re.compile(r"\b(received|arrived|came)\b.*\bused\b|\bused\b.*\b(received|arrived|came)\b", re.IGNORECASE | re.DOTALL)


def says_received(text: str | None) -> bool:
    """The message says material came, and does not say it was used."""
    text = text or ""
    return bool(_RECEIVED_RE.search(text)) and not _USED_RE.search(text)


def says_used(text: str | None) -> bool:
    """The message says material was used, and does not say it came."""
    text = text or ""
    return bool(_USED_RE.search(text)) and not _RECEIVED_RE.search(text)


def asks_direction(question: str | None) -> bool:
    """The model's question is the "Received or used?" one."""
    return bool(_ASKS_DIRECTION.search(question or ""))


_HOW_MANY = re.compile(r"\bhow (?:many|much)\b|\bquantity\b|\bkitn[ae]\b|\bethra\b|എത്ര", re.IGNORECASE)
_MATERIAL_UNITS = re.compile(r"\b(?:bags?|kgs?|nos|pcs|pieces|loads?|cum|cft|tons?|tonnes?|litres?|liters?|brass)\b", re.IGNORECASE)

#: Typical quantities, as the buttons of a "how many?" about a material.
QUANTITY_GUESSES = ("10", "25", "50", "Other")
DIRECTION_OPTIONS = ("Received", "Used")


def default_options(question: str | None, user_text: str | None) -> tuple[str, ...]:
    """MAT-08: a material question always carries options. The model's own are
    used when it gave any; with none, the ones the question itself implies:
    "Received or used?", or "how many?" about material the message names
    (a receipt/usage word or a unit)."""
    if asks_direction(question):
        return DIRECTION_OPTIONS
    text = user_text or ""
    about_material = bool(_RECEIVED_RE.search(text) or _USED_RE.search(text) or _MATERIAL_UNITS.search(text))
    if about_material and _HOW_MANY.search(question or ""):
        return QUANTITY_GUESSES
    return ()
