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
