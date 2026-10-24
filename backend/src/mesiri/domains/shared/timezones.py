"""Time zone names the API accepts (V1 audit DSH-03).

`reporting_timezone` and a company's `timezone` decide when the evening check
and the DPR go out. They were free text, and a name the tz database doesn't
know ("IST", "India") was saved without a word and then read as UTC: the 6 PM
check came at 11:30 PM. A name is now stored only as a real IANA zone; the
words Indian sites type for their own zone are read as Asia/Kolkata.
"""

from __future__ import annotations

from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from pydantic import AfterValidator

INDIA = "Asia/Kolkata"

_ALIASES = {
    "ist": INDIA,
    "india": INDIA,
    "indian standard time": INDIA,
    "india standard time": INDIA,
    "utc+5:30": INDIA,
    "utc+05:30": INDIA,
    "gmt+5:30": INDIA,
    "gmt+05:30": INDIA,
    "+05:30": INDIA,
    "+5:30": INDIA,
    "asia/calcutta": INDIA,
    "kolkata": INDIA,
    "utc": "UTC",
    "gmt": "UTC",
}


def normalize_timezone(value: str) -> str:
    """The IANA name for ``value``, or ValueError when it is none."""
    text = " ".join(str(value or "").split())
    alias = _ALIASES.get(text.casefold())
    if alias is not None:
        return alias
    if text in available_timezones():
        try:
            ZoneInfo(text)
        except (ZoneInfoNotFoundError, ValueError):
            pass
        else:
            return text
    raise ValueError(f"Unknown time zone {text!r}: use a name like Asia/Kolkata")


#: A request field holding a time zone name, normalised or rejected (422).
TimezoneName = Annotated[str, AfterValidator(normalize_timezone)]
