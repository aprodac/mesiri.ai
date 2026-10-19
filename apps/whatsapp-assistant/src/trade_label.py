"""How a trade is shown to a person: "steel_bender" -> "Steel bender".

Trades are stored as lowercase codes (``steel_bender``) and the code stays the
button / row id, so a tap still maps back. Everything a person reads -- list
rows, the "Recorded:" line, the receipt, the DPR -- goes through this one
helper rather than formatting the code on each screen. The label is English;
reply_language translates the surrounding wording and keeps common English
work words (mason, helper) as site people say them.
"""

from __future__ import annotations


def trade_label(trade: object) -> str:
    """Sentence-case label for a trade code; "" when there is none."""
    text = " ".join(str(trade or "").replace("_", " ").replace("-", " ").split())
    return text[:1].upper() + text[1:].lower() if text else ""
