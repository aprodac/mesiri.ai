"""Places in words (LP-02): "first floor Room-2", "FF R2", "onnam nila bedroom" -> the place.

The one resolver for place words (the same idea as BOQ items and material categories): the API takes a place in
words and this decides, so the assistant never keeps its own list. Pure: no database.

Floors are matched by their number, whatever they are called ("First Floor", "1st floor", "FF", "L1", "onnam nila"
are all floor 1; "Ground", "GF", "thazhe" floor 0; "Basement", "cellar" floor -1). Rooms by their name with spaces,
dashes and case ignored ("Room-2" = "room 2" = "R2" = "rm2"). A room named without a floor is that room when only
one floor has it; otherwise the answer is the rooms to choose from.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field

#: Ordinal words -> floor number. English, short forms, Malayalam (Manglish) ordinals.
_ORDINALS: dict[str, int] = {
    "first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3, "fourth": 4, "4th": 4, "fifth": 5,
    "5th": 5, "sixth": 6, "6th": 6, "seventh": 7, "7th": 7, "eighth": 8, "8th": 8, "ninth": 9, "9th": 9,
    "tenth": 10, "10th": 10,
    "onnam": 1, "onnaam": 1, "randam": 2, "randaam": 2, "moonnam": 3, "moonam": 3, "munnam": 3, "naalam": 4,
    "nalam": 4, "anjam": 5, "anchaam": 5,
}
_FLOOR_WORDS = r"(?:floor|flr|fl|level|lvl|nila|nilay?il|storey|story|nilam)"
_SHORT_FLOORS: dict[str, int] = {"gf": 0, "ff": 1, "sf": 2, "tf": 3, "bf": -1, "lgf": -1, "ugf": 0}
_GROUND = r"(?:ground|thazhe|thazhathe|thazhatthe|tharanila|plinth)"
_BASEMENT = r"(?:basement|cellar|underground|lower\s+ground)"
_TERRACE = r"(?:terrace|roof|mattuppavu|tterrace)"
#: A floor number from the words, and the span of the words used (so a room is looked for in the rest).
_FLOOR_PATTERNS: tuple[tuple[re.Pattern[str], object], ...] = (
    (re.compile(rf"\b{_BASEMENT}(?:\s*{_FLOOR_WORDS})?\b"), -1),
    (re.compile(rf"\b{_GROUND}(?:\s*{_FLOOR_WORDS})?\b"), 0),
    (re.compile(rf"\b{_TERRACE}(?:\s*{_FLOOR_WORDS})?\b"), "terrace"),
    (re.compile(rf"\b({'|'.join(sorted(_ORDINALS, key=len, reverse=True))})\s*{_FLOOR_WORDS}\b"), "ordinal"),
    (re.compile(rf"\b{_FLOOR_WORDS}\s*-?\s*(\d{{1,2}})\b"), "number"),
    (re.compile(r"\b(?:l|f)\s*-?\s*(\d{1,2})\b"), "number"),
    (re.compile(r"\b(" + "|".join(_SHORT_FLOORS) + r")\b"), "short"),
)


def floor_number(words: str) -> tuple[int | str | None, tuple[int, int] | None]:
    """The floor the words name (an int, or "terrace"), and where in the words it was said."""
    text = _norm(words)
    for pattern, kind in _FLOOR_PATTERNS:
        m = pattern.search(text)
        if not m:
            continue
        if kind == "ordinal":
            return _ORDINALS[m.group(1)], m.span()
        if kind == "number":
            return int(m.group(1)), m.span()
        if kind == "short":
            return _SHORT_FLOORS[m.group(1)], m.span()
        return kind, m.span()  # -1, 0 or "terrace"
    return None, None


def _norm(words: str) -> str:
    return " ".join(re.sub(r"[_/,.;:()]+", " ", (words or "").lower()).split())


def compact(words: str) -> str:
    """A room name as compared: lower case, no spaces or dashes, "room"/"rm" -> "r" before a number."""
    text = re.sub(r"[\s\-_.#]+", "", (words or "").lower())
    return re.sub(r"^(?:room|rm|r)(\d)", r"r\1", text)


@dataclass(frozen=True)
class Place:
    id: uuid.UUID
    name: str
    parent_id: uuid.UUID | None
    level_label: str = ""


@dataclass
class Match:
    """``place``: the one place meant. ``options``: the places to choose from when the words fit several."""

    place: Place | None = None
    options: list[Place] = field(default_factory=list)
    reason: str | None = None


def label(place: Place, by_id: dict[uuid.UUID, Place]) -> str:
    """A place as people say it: "First Floor / Room-2"."""
    names = [place.name]
    parent = by_id.get(place.parent_id) if place.parent_id else None
    while parent is not None:
        names.append(parent.name)
        parent = by_id.get(parent.parent_id) if parent.parent_id else None
    return " / ".join(reversed(names))


def resolve(words: str, places: list[Place]) -> Match:
    """The place the words name, among the project's places (not archived)."""
    text = _norm(words)
    if not text or not places:
        return Match(reason="no_places" if not places else "no_words")
    by_id = {p.id: p for p in places}
    roots = [p for p in places if p.parent_id is None]

    # Exact full label or exact name first ("First Floor / Room-2", "Kitchen").
    key = compact(text.replace(" / ", ""))
    exact = [p for p in places if compact(label(p, by_id).replace(" / ", "")) == key] or \
            [p for p in places if compact(p.name) == key]
    if len(exact) == 1:
        return Match(place=exact[0])

    floor, span = floor_number(text)
    floor_places: list[Place] = []
    if floor is not None:
        floor_places = [p for p in roots if floor_number(p.name)[0] == floor]
    rest = text if span is None else (text[: span[0]] + " " + text[span[1]:]).strip()

    pool = places if not floor_places else [p for p in places if p.parent_id in {f.id for f in floor_places}]
    rooms = _rooms_in(rest, pool) if rest else []
    if rooms:
        if len(rooms) == 1:
            return Match(place=rooms[0])
        return Match(options=rooms, reason="several")
    if floor_places:
        if len(floor_places) == 1:
            return Match(place=floor_places[0])
        return Match(options=floor_places, reason="several")
    if floor is not None:
        return Match(options=roots, reason="no_such_floor")
    return Match(options=[], reason="not_found")


def _rooms_in(text: str, pool: list[Place]) -> list[Place]:
    """Rooms (non-root places) whose name is said in the words, longest names first."""
    candidates = [p for p in pool if p.parent_id is not None]
    whole = compact(text)
    tokens = _norm(text).split()
    found: list[Place] = []
    for p in sorted(candidates, key=lambda q: -len(q.name)):
        name = compact(p.name)
        if not name:
            continue
        if name == whole or any(compact("".join(tokens[i:j])) == name
                                for i in range(len(tokens)) for j in range(i + 1, min(len(tokens), i + 4) + 1)):
            found.append(p)
    if not found:
        return []
    # "bedroom 2" must not also count as "bedroom": keep only the longest names that matched.
    best = max(len(compact(p.name)) for p in found)
    return [p for p in found if len(compact(p.name)) == best]
