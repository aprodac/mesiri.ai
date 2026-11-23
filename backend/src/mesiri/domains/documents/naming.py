"""Guess a document's folder, number, title and revision (DOC-01), and match "the latest column drawing" (DOC-05).

From the file name ("S-101 Rev C Column Layout.pdf", "Building permit 2026.pdf") and, for a drawing PDF, the title
block the drawing reader found on page 1. A guess only: the person sees it and can change it. Pure: no database.
"""

from __future__ import annotations

import datetime
import re
from collections.abc import Mapping
from typing import Any

FOLDERS = ("contract", "drawing", "approval", "boq", "work_order", "test_report", "handover", "other")
#: D-DOC1: money and contract papers, seen only by owner, admin, finance and project managers.
RESTRICTED_FOLDERS = frozenset({"contract", "boq", "work_order"})
DISCIPLINES = ("architectural", "structural", "mep", "other")

#: Words that put a file in a folder, checked in this order (a "work order" is not a plain "order").
_FOLDER_WORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("work_order", ("work order", "workorder", "wo-", "wo ")),
    ("contract", ("agreement", "contract", "loa", "letter of award", "tender")),
    ("boq", ("boq", "estimate", "bill of quantities", "abstract")),
    ("test_report", ("test", "cube", "report", "lab ", "soil")),
    ("handover", ("as built", "as-built", "asbuilt", "warranty", "guarantee", "handover", "completion")),
    ("approval", ("permit", "approval", "sanction", "noc", "licence", "license", "insurance", "occupancy")),
    ("drawing", ("drawing", "dwg", "plan", "elevation", "section", "layout", "detail", "column", "beam", "slab",
                 "footing", "foundation", "plumbing", "electrical", "struct", "arch", "gfc", "ga ")),
)
_DISCIPLINE_WORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("structural", ("struct", "column", "beam", "slab", "footing", "foundation", "reinforcement", "rcc", "bbs")),
    ("mep", ("electrical", "plumbing", "mep", "hvac", "sanitary", "drainage", "fire")),
    ("architectural", ("arch", "plan", "elevation", "section", "door", "window", "furniture")),
)
_NUMBER = re.compile(r"\b([A-Z]{1,4}-?\d{1,4}(?:[-/.]\d{1,3})?)\b")
_REVISION = re.compile(r"(?:\brev(?:ision)?[\s._-]*|(?<=[_-])r)([A-Z0-9]{1,3})\b", re.IGNORECASE)
_EXTENSIONS = {
    "pdf": "application/pdf", "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "heic": "image/heic",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "dwg": "application/acad",
}


def content_type(file_name: str) -> str | None:
    """The type a file is stored as, from its extension; None when the kind is not taken (D-DOC4)."""
    ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
    return _EXTENSIONS.get(ext)


def _stem(file_name: str) -> str:
    stem = file_name.rsplit(".", 1)[0] if "." in file_name else file_name
    return " ".join(re.sub(r"[_]+", " ", stem).split())


def folder_of(words: str, *, is_drawing: bool = False) -> str:
    text = f" {words.lower()} "
    for folder, keys in _FOLDER_WORDS:
        if any(k in text for k in keys):
            return folder
    return "drawing" if is_drawing else "other"


def discipline_of(words: str) -> str | None:
    text = words.lower()
    if re.search(r"\bs[-\s]?\d", text):
        return "structural"
    if re.search(r"\ba[-\s]?\d", text):
        return "architectural"
    for discipline, keys in _DISCIPLINE_WORDS:
        if any(k in text for k in keys):
            return discipline
    return None


def _first_token(value: str | None, longest: int) -> str | None:
    """A title-block value as read can run into the next field ("B S-101"): keep its first word when short."""
    if not value:
        return None
    first = value.split()[0].strip(" :.-")
    return first if 0 < len(first) <= longest else None


def guess(file_name: str, first_sheet: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """folder, discipline, number, title, revision for a new file. ``first_sheet``: the drawing reader's page 1."""
    stem = _stem(file_name)
    raw = file_name.rsplit(".", 1)[0] if "." in file_name else file_name
    sheet = first_sheet or {}
    number = _first_token(sheet.get("number"), 20)
    revision = _first_token(sheet.get("revision"), 3)
    rev_m = _REVISION.search(raw)  # before "_" becomes a space: "A-201_R2"
    if not revision and rev_m:
        revision = rev_m.group(1).upper()
    rest = _stem(_REVISION.sub(" ", raw)) if rev_m else stem
    if not number:
        num_m = _NUMBER.search(rest.upper())
        if num_m and any(c.isalpha() for c in num_m.group(1)):
            number = num_m.group(1).replace(" ", "-")
            rest = rest[: num_m.start()] + rest[num_m.end():]
    title = sheet.get("title") or " ".join(re.sub(r"^[\s\-–_.]+|[\s\-–_.]+$", "", rest).split()) or stem
    title = title.strip(" -–_.") or stem
    is_drawing = bool(sheet.get("kind") or sheet.get("number") or sheet.get("scale"))
    folder = folder_of(f"{stem} {sheet.get('title') or ''}", is_drawing=is_drawing)
    discipline = None
    if folder == "drawing":
        # The number's prefix says it plainest ("S-101" structural, "A-201" architectural), then the sheet's words.
        by_number = discipline_of(number) if number and re.match(r"^[AS][-\s]?\d", number, re.I) else None
        by_sheet = sheet.get("discipline") if sheet.get("discipline") in DISCIPLINES else None
        discipline = by_number or by_sheet or discipline_of(f"{stem} {title}") or "other"
    return {"folder": folder, "discipline": discipline, "number": (number or None),
            "title": title[:200].title() if title.isupper() else title[:200], "revision": (revision or None)}


def _tokens(words: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", words.lower()) if t]


#: Words that say which document, never what it is called: "send me the latest column drawing".
_FILLER = frozenset("""send me the latest last new current drawing drawings dwg pdf copy file please pls a an of for
show give share it its tha thaa ayakku ayakkoo ayachu tharu tharoo venam veno onnu ithu athu ente our evide eviduthe
""".split())


def find_score(query: str, doc: Mapping[str, Any]) -> float:
    """How well a current document fits the words (0: not at all). Number first, then title words, then folder and
    discipline words."""
    q = [t for t in _tokens(query) if t not in _FILLER]
    if not q:
        return 0.0
    number = (doc.get("number") or "").lower()
    compact_q = re.sub(r"[^a-z0-9]", "", query.lower())
    score = 0.0
    if number and re.sub(r"[^a-z0-9]", "", number) in compact_q:
        score += 10
    hay = set(_tokens(f"{doc.get('title') or ''} {doc.get('file_name') or ''} {number}"))
    hits = sum(1 for t in q if t in hay or (len(t) > 3 and any(h.startswith(t[:5]) for h in hay)))
    score += 3 * hits / len(q) * min(len(q), 3)
    extra = set(_tokens(f"{doc.get('folder') or ''} {(doc.get('folder') or '').replace('_', ' ')} "
                        f"{doc.get('discipline') or ''}"))
    if doc.get("folder") == "approval":
        extra |= {"permit", "approval", "sanction", "noc", "licence", "license", "insurance"}
    if doc.get("folder") == "contract":
        extra |= {"agreement", "contract"}
    if doc.get("discipline") == "structural":
        extra |= {"structural", "str", "rcc", "column", "beam", "slab", "footing"}
    if doc.get("discipline") == "architectural":
        extra |= {"architectural", "arch", "plan", "elevation"}
    score += sum(1 for t in q if t in extra)
    return score


# --- Revisions: one letter per revision (Step 7 test, 23 Nov 2026) -------------------------------------------------

def same_revision(a: str | None, b: str | None) -> bool:
    """"b" and "B ", or two blanks: the same revision letter."""
    return (a or "").strip().upper() == (b or "").strip().upper()


def next_revision(revision: str | None) -> str:
    """The letter after this one, as architects number them: A -> B, Z -> AA, 0 -> 1, R2 -> R3, P09 -> P10.
    No letter yet -> A."""
    rev = (revision or "").strip().upper()
    if not rev or rev == "-":
        return "A"
    m = re.match(r"^(.*?)(\d+)$", rev)
    if m:
        digits = m.group(2)
        return f"{m.group(1)}{str(int(digits) + 1).zfill(len(digits))}"
    if rev.isalpha():
        letters = list(rev)
        i = len(letters) - 1
        while i >= 0 and letters[i] == "Z":
            letters[i] = "A"
            i -= 1
        if i < 0:
            return "A" + "".join(letters)
        letters[i] = chr(ord(letters[i]) + 1)
        return "".join(letters)
    return f"{rev}-1"


# --- A permit's last day, read from its text (Step 7 test, 23 Nov 2026) ---------------------------------------------

_MONTHS = {m: i + 1 for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov",
                                            "dec"))}
_DAY_MONTH_YEAR = r"(\d{1,2})(?:st|nd|rd|th)?[\s.\-/]+([A-Za-z]{3,9})\.?,?[\s.\-/]+(\d{4})"
_MONTH_DAY_YEAR = r"([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})"
_NUMERIC = r"(\d{1,2})[./\-](\d{1,2})[./\-](\d{4})"
_ISO = r"(\d{4})-(\d{2})-(\d{2})"
_ANY_DATE = re.compile(f"{_ISO}|{_NUMERIC}|{_DAY_MONTH_YEAR}|{_MONTH_DAY_YEAR}")
_NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "ten": 10, "twelve": 12}
#: "Valid up to 31/03/2029", "Validity: till 31 March 2029", "Expiry date 2029-03-31", "expires on ...".
_UNTIL = re.compile(r"(?:valid(?:ity)?\s*(?:date\s*)?[:\-]?\s*(?:up\s*to|upto|till|until|through|to)|expir(?:y|es|ing|"
                    r"ation)(?:\s*date)?(?:\s*on)?|valid\s*(?:up\s*)?to)\s*[:\-]?\s*", re.IGNORECASE)
#: "Validity 3 years from the date of issue", "valid for three years from the date of this permit".
_FOR = re.compile(r"valid(?:ity)?\s*[:\-]?\s*(?:for\s*|of\s*)?(\d{1,2}|" + "|".join(_NUMBER_WORDS) +
                  r")\s*(year|month)s?\s*from\s*(?:the\s*)?(?:date\s*of\s*)?(?:issue|this|permit|sanction|approval)",
                  re.IGNORECASE)
#: Where the issue date is written: "Date 30 September 2026", "Issued on ...", "Date of issue: ...".
_ISSUED = re.compile(r"(?:date\s*of\s*issue|issue\s*date|issued\s*on|dated?)\s*[:\-]?\s*", re.IGNORECASE)


def _date_at(text: str, start: int, within: int = 40) -> datetime.date | None:
    m = _ANY_DATE.search(text, start, start + within + 25)
    if m is None or m.start() - start > within:
        return None
    g = m.groups()
    try:
        if g[0]:
            return datetime.date(int(g[0]), int(g[1]), int(g[2]))
        if g[3]:  # Indian order: day / month / year
            return datetime.date(int(g[5]), int(g[4]), int(g[3]))
        if g[6]:
            month = _MONTHS.get(g[7][:3].lower())
            return datetime.date(int(g[8]), month, int(g[6])) if month else None
        month = _MONTHS.get(g[9][:3].lower())
        return datetime.date(int(g[11]), month, int(g[10])) if month else None
    except ValueError:
        return None


def _add_months(day: datetime.date, months: int) -> datetime.date:
    month0 = day.month - 1 + months
    year, month = day.year + month0 // 12, month0 % 12 + 1
    last = (datetime.date(year + (month == 12), month % 12 + 1, 1) - datetime.timedelta(days=1)).day
    return datetime.date(year, month, min(day.day, last))


def valid_until_of(text: str) -> tuple[datetime.date, str] | None:
    """A permit, licence or NOC's last day from its own words, and how it was read (shown to the person to check):
    "valid up to 31/03/2029" as written, or "validity 3 years from the date of issue" counted from the issue date
    (the day before the anniversary). None when the paper does not say."""
    text = " ".join(text.split())
    for m in _UNTIL.finditer(text):
        day = _date_at(text, m.end())
        if day is not None:
            return day, f"“{text[m.start():m.end()].strip(' :-')} {day.strftime('%d %b %Y')}”"
    m = _FOR.search(text)
    if m is None:
        return None
    count = int(m.group(1)) if m.group(1).isdigit() else _NUMBER_WORDS[m.group(1).lower()]
    months = count * 12 if m.group(2).lower() == "year" else count
    issued = None
    for d in _ISSUED.finditer(text):
        issued = _date_at(text, d.end(), within=15)
        if issued is not None:
            break
    if issued is None:
        return None
    unit = "year" if m.group(2).lower() == "year" else "month"
    return (_add_months(issued, months) - datetime.timedelta(days=1),
            f"{count} {unit}{'s' if count > 1 else ''} from issue ({issued.strftime('%d %b %Y')})")
