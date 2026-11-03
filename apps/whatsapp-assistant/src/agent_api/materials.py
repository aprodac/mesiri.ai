"""[210]: the company's own material list decides which material a line is.

3 Nov (Mesiri Test Builders): "2 drum primer vannu" was saved as Paint, the nearest item in the list, without a
question, so the stock and costs of both went wrong. The model picks ``material_id``; this checks it against the
word the person used (``material_said``, or their own words when the model left it out):

- the material's name or a name the company taught it (``material_aliases``) -> the line goes through, no question;
- the word is part of exactly one material's name ("cement" -> "Cement OPC 53") -> the same;
- anything else is only a suggestion: nothing is prepared, and the person gets buttons (the nearest two and
  "➕ Add <word>"). Their choice is remembered as an alias (``add_material_alias``), so it never asks twice.
- [217]: "Add" holds the new material AND its line (and a container's size) in one list; the line names the
  material ``new:<name>`` until Save creates it.
"""

from __future__ import annotations

import difflib
import re
from typing import Any

from mesiri.domains.materials.names import alias_key

from .client import ApiClient

ADD = "➕ Add "
ADD_TOOL = "add_material"
#: [217]: a line for a material that is only in the ready list (``add_material``, not saved yet) names it
#: ``new:<name>``; ``confirm`` puts the new material's id in once it is saved.
NEW = "new:"
_WORD = re.compile(r"[^\W_]+")


def pending_ref(value: Any, names: list[str]) -> str | None:
    """``new:<name>`` when ``value`` ("new:Primer", "Primer", "primer") names a material waiting to be added."""
    said = alias_key(str(value or "").removeprefix(NEW))
    return next((f"{NEW}{n}" for n in names if said and alias_key(n) == said), None)


def _words(text: str) -> set[str]:
    return set(_WORD.findall(alias_key(text)))


def _names(row: dict[str, Any]) -> list[str]:
    return [str(row.get("name") or ""), *(str(a) for a in row.get("aliases") or [])]


def _same(a: str, b: str) -> bool:
    """One name: exact, or the same word in singular and plural ("brick" / "Bricks")."""
    a, b = alias_key(a), alias_key(b)
    return bool(a) and (a == b or a in (b + "s", b + "es") or b in (a + "s", a + "es"))


def _part_of(said: set[str], row: dict[str, Any]) -> bool:
    return bool(said) and any(said <= _words(n) for n in _names(row))


def is_material(said: str, row: dict[str, Any], rows: list[dict[str, Any]]) -> bool:
    """``said`` names ``row``: its name or alias, or its words are in this one material's name and no other's."""
    if any(_same(said, n) for n in _names(row)):
        return True
    words = _words(said)
    return _part_of(words, row) and not any(_part_of(words, r) for r in rows if r is not row)


def in_their_words(words: str, row: dict[str, Any], rows: list[dict[str, Any]]) -> bool:
    """No ``material_said``: the person's own words name ``row`` (a whole name or alias in them, or a word of
    its name that no other material has)."""
    said = _words(words)
    if any(_words(n) and _words(n) <= said for n in _names(row)):
        return True
    others = set().union(*(_words(n) for r in rows if r is not row for n in _names(r))) if rows else set()
    return any(len(w) >= 3 and w not in others for n in _names(row) for w in _words(n) & said)


def nearest(said: str, rows: list[dict[str, Any]], first: dict[str, Any] | None, k: int = 2) -> list[dict[str, Any]]:
    """The ``k`` materials nearest ``said`` (the model's pick first, when it made one)."""
    key = alias_key(said)

    def score(row: dict[str, Any]) -> float:
        return max((difflib.SequenceMatcher(a=key, b=alias_key(n)).ratio() + len(_words(said) & _words(n))
                    for n in _names(row)), default=0.0)

    ranked = sorted((r for r in rows if r is not first), key=score, reverse=True)
    return ([first] if first else [])[:k] + ranked[: k - (1 if first else 0)]


def title(said: str) -> str:
    return " ".join(said.split())[:1].upper() + " ".join(said.split())[1:]


async def settle_material(client: ApiClient, body: dict[str, Any], said: str, words: str,
                          taught: list[tuple[str, str]]) -> tuple[str, list[str]]:
    """Check ``body["material_id"]`` is the material they meant. ``taught``: (material_id, alias) pairs already
    prepared this conversation (the person just chose). Returns ("", []) when it is, else what to tell the model
    and the buttons. The list unreadable: ("", []), and the API's own checks decide."""
    try:
        response = await client.call("GET", "/materials", params={"limit": 200, "is_active": True})
    except Exception:  # noqa: BLE001
        return "", []
    items = response.body.get("items") if response.ok and isinstance(response.body, dict) else None
    rows = [r for r in items or [] if isinstance(r, dict) and r.get("id")]
    if not rows:
        return "", []
    picked = str(body.get("material_id") or "")
    row = next((r for r in rows if str(r["id"]) == picked), None)
    said = " ".join(str(said or "").split())
    if row is not None:
        if said and (is_material(said, row, rows) or any(m == picked and _same(a, said) for m, a in taught)):
            return "", []
        if not said and in_their_words(words, row, rows):
            return "", []
    if not said:
        return ("say which material they named: pass material_said, their own word for it. Nothing is prepared yet.",
                [])
    hit = next((r for r in rows if is_material(said, r, rows)), None)
    if hit is not None:  # the word is another material in the list: that one, never the near one
        body["material_id"] = str(hit["id"])
        return "", []
    near = nearest(said, rows, row)
    word = title(said)
    names = [str(r["name"]) for r in near]
    buttons = [n[:20] for n in names] + [f"{ADD}{word}"[:20]]
    return (f"{word!r} is not in the company's material list, and it is not {' or '.join(names)}. Nothing is "
            f"prepared. Never record it as another material. Ask with `ask`, in their language: \"{word} isn't in "
            f"your list. Same as {' or '.join(names)}, or add {word}?\" with options {buttons}. When they pick a "
            f"material: prepare `add_material_alias` (that material_id, alias {said!r}) and the line on that "
            f"material with material_said {said!r}. When they pick Add, in that same turn: prepare `add_material` "
            f"named {word} (in English, its stock unit), AND the line itself with material_id \"{NEW}{word}\" and "
            f"material_said {said!r}, in the unit they said. If that unit is a container (drum, tin, load, trip, "
            f"bundle) of unknown size, ask its size; then prepare `set_unit_conversion` with material_id "
            f"\"{NEW}{word}\". Everything saves in one Save, the new material first.", buttons)
