"""Guess a document's folder, number, title and revision (DOC-01), and match "the latest column drawing" (DOC-05).

From the file name ("S-101 Rev C Column Layout.pdf", "Building permit 2026.pdf") and, for a drawing PDF, the title
block the drawing reader found on page 1. A guess only: the person sees it and can change it. Pure: no database.
"""

from __future__ import annotations

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
