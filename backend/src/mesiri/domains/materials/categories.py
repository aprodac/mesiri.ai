"""Material categories: the builder's standard list and how a material finds its place (PRC-01, PRC-03).

A company's categories are its own rows (``material_categories``): it renames, adds
and switches them off. This module holds only the starting point every company
gets, and the fixed rules that put an existing material into it:

1. a starter material by its name ("PVC Pipe" -> Plumbing & CP > Pipes);
2. otherwise the material's old free-text group, when it is exactly one this list
   knows ("Masonry" -> Structural > Masonry).

Nothing else is guessed (decision D5 in docs/plans/procurement-plan.md): a material
that matches neither stays without a category for the company to place.
"""

from __future__ import annotations

#: Main category -> its sub-categories, in the order a builder works through a project.
STANDARD_CATEGORIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Structural", ("Masonry", "Concrete", "Steel", "Shuttering")),
    ("Electrical", ("Wires & cables", "Switches & sockets", "Conduits & boxes", "DB & MCBs", "Lights & fittings")),
    ("Plumbing & CP", ("Pipes", "Pipe fittings", "Valves", "Sanitaryware", "CP fittings & accessories", "Tanks")),
    ("Fire protection", ("Pipes & fittings", "Sprinklers", "Hydrants & hoses", "Extinguishers", "Alarms & detectors")),
    ("Gas", ("Pipes & fittings", "Regulators & valves")),
    ("Lift", ()),
    ("Finishing", ("Tiles & flooring", "Paint & putty", "Waterproofing", "Doors & windows", "Hardware")),
)

#: (main, sub or None)
Path = tuple[str, str | None]

#: Rule 1: starter materials (domains/materials/defaults.py) whose old group is too broad.
_BY_MATERIAL_NAME: dict[str, Path] = {
    "pvc pipe": ("Plumbing & CP", "Pipes"),
    "electrical wire": ("Electrical", "Wires & cables"),
    "tiles": ("Finishing", "Tiles & flooring"),
    "paint": ("Finishing", "Paint & putty"),
    "wall putty": ("Finishing", "Paint & putty"),
    "waterproofing compound": ("Finishing", "Waterproofing"),
}

#: Rule 2: the old free-text groups the starter list and the dashboard used.
_BY_OLD_GROUP: dict[str, Path] = {
    "masonry": ("Structural", "Masonry"),
    "concrete": ("Structural", "Concrete"),
    "steel": ("Structural", "Steel"),
    "shuttering": ("Structural", "Shuttering"),
    "structural": ("Structural", None),
    "electrical": ("Electrical", None),
    "plumbing": ("Plumbing & CP", None),
    "finishing": ("Finishing", None),
}


def _key(value: str | None) -> str:
    return " ".join((value or "").split()).lower()


def standard_path_for(material_name: str, old_group: str | None) -> Path | None:
    """Where a material goes in the standard list, or None when no fixed rule places it."""
    return _BY_MATERIAL_NAME.get(_key(material_name)) or _BY_OLD_GROUP.get(_key(old_group))


def clean_category_name(name: str) -> str:
    """One space between words, no outer spaces. Empty means no name."""
    return " ".join((name or "").split())


# ---------------------------------------------------------------------------
# PRC-02: the category for a NEW material, suggested from its name
# ---------------------------------------------------------------------------
#: Joiners in category names ("Wires & cables"): never a word that places a material.
_JOINERS = frozenset({"&", "and"})


def _words(text: str) -> list[str]:
    """Lower-case words, each singular ("Wires" -> "wire", "Boxes" -> "box"), joiners left out."""
    out = []
    for word in _key(text).replace("&", " & ").replace("/", " ").split():
        word = word.strip(".,;:()[]-")
        if not word or word in _JOINERS:
            continue
        if len(word) > 4 and word.endswith("es") and (word[-3] in "sxz" or word[-4:-2] in ("ch", "sh")):
            word = word[:-2]
        elif len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
        out.append(word)
    return out


def _contains(name: list[str], phrase: list[str]) -> bool:
    n = len(phrase)
    return n > 0 and any(name[i:i + n] == phrase for i in range(len(name) - n + 1))


def _starter_paths() -> list[tuple[list[str], Path]]:
    """Every starter material name (as words) and where it goes, longest first ("Binding Wire" before "Wire")."""
    from mesiri.domains.materials.defaults import STARTER_MATERIALS

    paths = []
    for starter in STARTER_MATERIALS:
        path = standard_path_for(starter.name, starter.category)
        if path is not None:
            paths.append((_words(starter.name), path))
    return sorted(paths, key=lambda p: -len(p[0]))


def suggest_path(material_name: str) -> Path | None:
    """Where a new material most likely goes in the standard list, from its name alone, or None.

    1. The name holds a starter material's name ("Cement OPC 53" -> Structural > Masonry, "TMT Steel 12mm" ->
       Structural > Steel); the longest starter name wins ("Binding Wire" is Steel, not a wire).
    2. Else a word of the name is a word of exactly ONE category ("Ceramic tiles" -> Finishing > Tiles & flooring,
       "MCB 32A" -> Electrical > DB & MCBs). A word shared by several ("pipe": plumbing, fire, gas; "fitting") places
       nothing, and neither do two words pointing to different categories.

    Nothing else is guessed: the caller may ask the model next, and a material may stay without a category.
    """
    name = _words(material_name)
    if not name:
        return None
    for phrase, path in _starter_paths():
        if _contains(name, phrase):
            return path
    owners: dict[str, set[Path]] = {}
    for main, subs in STANDARD_CATEGORIES:
        for word in _words(main):
            owners.setdefault(word, set()).add((main, None))
        for sub in subs:
            for word in _words(sub):
                owners.setdefault(word, set()).add((main, sub))
    found = {next(iter(owners[w])) for w in name if len(owners.get(w, ())) == 1}
    return next(iter(found)) if len(found) == 1 else None


def find_category(categories: list[dict], path: Path) -> dict | None:
    """The company's switched-on category at ``path`` (names compared ignoring case and spaces), or None. A path whose
    sub-category the company doesn't have falls back to its main category."""
    main, sub = path
    active = [c for c in categories if c.get("is_active", True)]
    top = next((c for c in active if c.get("parent_id") is None and _key(c["name"]) == _key(main)), None)
    if top is None:
        return None
    if sub:
        child = next((c for c in active if c.get("parent_id") == top["id"] and _key(c["name"]) == _key(sub)), None)
        if child is not None:
            return child
    return top


def read_hint(categories: list[dict], hint: str | None) -> dict | None:
    """The model's own category in words ("Plumbing & CP > Pipes", "Pipes", "Electrical") read against the company's
    switched-on categories: main > sub; else a name only one category has (a sub under two mains places nothing);
    else None. Never creates a category."""
    text = _key(hint).replace("›", ">").replace("/", ">")
    if not text:
        return None
    active = [c for c in categories if c.get("is_active", True)]
    parts = [p.strip() for p in text.split(">") if p.strip()]
    if len(parts) >= 2:
        found = find_category(active, (parts[0], parts[1]))
        if found is not None and _key(found["name"]) == _key(parts[1]):
            return found
        parts = parts[-1:]
    same = [c for c in active if _key(c["name"]) == parts[0]] if parts else []
    return same[0] if len(same) == 1 else None


def category_label(categories: list[dict], category: dict) -> str:
    """"Main › Sub", or the main category's name."""
    parent = next((c for c in categories if c["id"] == category.get("parent_id")), None)
    return f"{parent['name']} › {category['name']}" if parent else str(category["name"])
