"""[210]: the company's own material list decides which material a line is.

3 Nov (Mesiri Test Builders): "2 drum primer vannu" was saved as Paint, the nearest item in the list, without a
question, so the stock and costs of both went wrong. The model picks ``material_id``; this checks it against the
word the person used (``material_said``, or their own words when the model left it out):

- the material's name or a name the company taught it (``material_aliases``) -> the line goes through, no question;
- the word is part of exactly one material's name ("cement" -> "Cement OPC 53") -> the same;
- anything else is a new material (WA-194): the model holds ``add_material`` (English name) and the line in the
  same turn, with no question; one Save adds both. "It's Paint" moves the line and teaches the alias.
- [217]: "Add" holds the new material AND its line (and a container's size) in one list; the line names the
  material ``new:<name>`` until Save creates it.
"""

from __future__ import annotations

import difflib
import re
from typing import Any

from mesiri.domains.materials.names import alias_key

from .client import ApiClient
from .fill import other_script

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


async def catalogue(client: ApiClient) -> list[dict[str, Any]]:
    """The company's active materials (name, aliases, id), the one place this package reads the list. Unreadable:
    [] (the API's own checks then decide)."""
    try:
        response = await client.call("GET", "/materials", params={"limit": 200, "is_active": True})
    except Exception:  # noqa: BLE001 -- the list unreadable: the API's own checks decide
        return []
    items = response.body.get("items") if response.ok and isinstance(response.body, dict) else None
    return [r for r in items or [] if isinstance(r, dict) and r.get("id")]


async def material_name(client: ApiClient, material_id: str) -> str:
    """The listed name of ``material_id`` ("Paint"), or "" when it is not in the list."""
    return next((str(r.get("name") or "") for r in await catalogue(client) if str(r["id"]) == material_id), "")


async def already_listed(client: ApiClient, name: str) -> str:
    """[243]: the company's material that ``name`` already is (its name or a taught alias, singular or plural), or "".
    A new material is never a second "Cement"."""
    if not name.strip():
        return ""
    row = next((r for r in await catalogue(client) if any(_same(name, n) for n in _names(r))), None)
    return f"{row['name']} (material_id {row['id']})" if row else ""


async def settle_material(client: ApiClient, body: dict[str, Any], said: str, words: str,
                          taught: list[tuple[str, str]]) -> tuple[str, list[str]]:
    """Check ``body["material_id"]`` is the material they meant. ``taught``: (material_id, alias) pairs already
    prepared this conversation (the person just chose). Returns ("", []) when it is, else what to tell the model
    and the buttons. The list unreadable: ("", []), and the API's own checks decide."""
    rows = await catalogue(client)
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
    if other_script(said):
        # [243]: "സിമന്റ്" is matched in English ("cement" -> the listed Cement), never offered as a new material.
        return ("material_said is not in English. Nothing is prepared. Call it again now with material_said in English "
                "(their word translated: സിമന്റ് = cement, മണൽ = sand, കമ്പി = steel); the code matches it to the "
                "company's list.", [])
    near = nearest(said, rows, row)
    word = title(said)
    names = [str(r["name"]) for r in near]
    # WA-194: a material not in the list never blocks the update ("should never become a blocker"). It is held
    # as a new material WITH its line, so one Save adds it to the catalogue and records the line; a person who meant
    # another one says so and the line moves there (``change_ready_entry``; the code drops the new material).
    return (f"{word!r} is not in the company's material list (nearest: {', '.join(names)}). Never record it as another "
            f"material, and do NOT ask: in this same turn prepare `add_material` with its English name (translate "
            f"Manglish/Malayalam to the English trade name: manal = Sand, kambi = Steel, chokk = Chalk; never the "
            f"Manglish word, never Malayalam script), default_unit_id the unit they said (unless it is plainly counted "
            f"in another unit), AND the line itself with material_id \"{NEW}<that English name>\" and material_said "
            f"{said!r}, in the unit they said. Everything saves in one Save, the new material first. Your reply says "
            f"in ONE line, in their language, that it is new and Save adds it to their material list, and that if it "
            f"is {' or '.join(names)} they can just say so. No buttons, no question.", [])


def name_key(text: str) -> str:
    """WA-201: how a vendor's name is matched: case, spaces and punctuation aside, each word singular ("Ravi
    Traders." = "ravi trader")."""
    words = _WORD.findall(alias_key(text))
    return " ".join(w[:-1] if len(w) > 3 and w.endswith("s") else w for w in words)


async def known_vendor(client: ApiClient, said: str) -> str:
    """WA-201: the company's active vendor that ``said`` already names ("ravi trader." -> "Ravi Traders"), else "".
    The API matches a vendor by its exact name and makes a new one otherwise, so the name goes in as it is listed.
    The list unreadable (the finance module off): "", and the API decides as before."""
    key = name_key(said)
    if not key:
        return ""
    try:
        response = await client.call("GET", "/finance/vendors")
    except Exception:  # noqa: BLE001
        return ""
    rows = response.body if response.ok and isinstance(response.body, list) else []
    return next((str(r["name"]) for r in rows if isinstance(r, dict) and r.get("status", "active") == "active"
                 and r.get("name") and name_key(str(r["name"])) == key), "")
