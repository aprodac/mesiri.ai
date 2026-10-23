"""Request 93: is this message a plain question about stock?

The model sometimes answers a stock question from the "Stock now at ..." line
in its prompt instead of calling ``query_materials``, so no Stock card is drawn.
``turn.py`` uses this to run the lookup itself when the model did not. It is
true only for a question with no quantity being reported: a number, a
received/used word or a "need more" word means an entry or a shortage, which
the model handles as before.
"""

from __future__ import annotations

import re

_STOCK_WORDS = re.compile(
    r"\bstocks?\b|\binventory\b|\bbalance\b|\bmaterials?\b|\bbaaki\b|\bbaki\b|\bbacha\b|\bshesham\b"
    r"|\bleft\b|\bremaining\b|\bethra\b.*\b(?:und|undu|unde|undo|ondo)\b"
    r"|സ്റ്റോക്ക്|ബാക്കി|എത്ര.*ഉണ്ട്|स्टॉक|बाकी|कितना",
    re.IGNORECASE,
)
#: A quantity being reported, or an entry's verb: not a question.
_REPORTING = re.compile(
    r"\d|\bvannu\b|\bvanu\b|\bethi\b|\beththi\b|\birakki\b|\breceived?\b|\bcame\b|\barrived\b"
    r"|\bdelivered\b|\bused?\b|\buse\s+(?:cheythu|aayi)\b|\bconsumed\b|\blaga\w*",
    re.IGNORECASE,
)
#: Wanting more, or running out: a shortage to report, not a question.
_SHORTAGE = re.compile(
    r"\bvenam\b|\bveno\b|\bkooduthal\b|\bneed\w*\b|\brequire\w*\b|\border\b|\bran out\b|\brunning\b"
    r"|\btheer\w*|\bkazhinj\w*|\bkhatam\b|\bchahiye\b",
    re.IGNORECASE,
)
#: Money, not materials ("account balance", "petty cash balance").
_MONEY = re.compile(
    r"\b(?:account|cash|money|petty|bank|wallet|ledger|expenses?|payments?|salary|wage\w*)\b", re.IGNORECASE
)


def is_stock_question(text: str | None) -> bool:
    text = (text or "").strip()
    if not text or _REPORTING.search(text) or _SHORTAGE.search(text) or _MONEY.search(text):
        return False
    return bool(_STOCK_WORDS.search(text))
