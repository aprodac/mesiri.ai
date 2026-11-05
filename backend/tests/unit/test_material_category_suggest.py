"""PRC-02: the category for a NEW material, suggested from its name (fixed rules first), then from a hint in words.

Only one of the company's own switched-on categories is ever returned; nothing is created, and a name that fits
several categories places nothing (the material is added without one, as before)."""

from __future__ import annotations

import uuid

from mesiri.domains.materials.categories import (
    STANDARD_CATEGORIES,
    category_label,
    find_category,
    read_hint,
    suggest_path,
)
from mesiri.domains.materials.defaults import STARTER_MATERIALS


def _tree(*, without: tuple[str, ...] = (), off: tuple[str, ...] = ()) -> list[dict]:
    rows = []
    for main, subs in STANDARD_CATEGORIES:
        top = {"id": uuid.uuid4(), "name": main, "parent_id": None, "is_active": main not in off}
        rows.append(top)
        rows += [{"id": uuid.uuid4(), "name": s, "parent_id": top["id"], "is_active": s not in off}
                 for s in subs if s not in without]
    return rows


# -- the rule ------------------------------------------------------------------------------------------------------


def test_a_starter_name_inside_the_new_name_places_it() -> None:
    assert suggest_path("Cement OPC 53 grade") == ("Structural", "Masonry")
    assert suggest_path("TMT Steel Bars 12mm") == ("Structural", "Steel")
    assert suggest_path("Binding Wire 18 gauge") == ("Structural", "Steel")  # longest starter name wins, not "wire"
    assert suggest_path("pvc pipes 4 inch") == ("Plumbing & CP", "Pipes")


def test_a_word_of_exactly_one_category_places_it() -> None:
    assert suggest_path("Ceramic floor tiles") == ("Finishing", "Tiles & flooring")
    assert suggest_path("MCB 32A") == ("Electrical", "DB & MCBs")
    assert suggest_path("Switch board 6 module") == ("Electrical", "Switches & sockets")
    assert suggest_path("Sprinkler head") == ("Fire protection", "Sprinklers")
    assert suggest_path("Lift") == ("Lift", None)


def test_a_shared_or_unknown_word_places_nothing() -> None:
    assert suggest_path("CPVC pipe 1 inch") is None  # pipes: plumbing, fire and gas
    assert suggest_path("Elbow fitting") is None  # fittings: several
    assert suggest_path("Primer") is None and suggest_path("Fevicol") is None and suggest_path("") is None


def test_every_starter_material_is_placed_where_the_standard_list_puts_it() -> None:
    for material in STARTER_MATERIALS:
        assert suggest_path(material.name) is not None, material.name


# -- the company's own categories ---------------------------------------------------------------------------------


def test_only_the_companys_switched_on_category_is_found() -> None:
    tree = _tree()
    found = find_category(tree, ("Electrical", "DB & MCBs"))
    assert found is not None and category_label(tree, found) == "Electrical › DB & MCBs"
    # no such sub-category: the main one; the main one switched off: none
    assert find_category(_tree(without=("DB & MCBs",)), ("Electrical", "DB & MCBs"))["name"] == "Electrical"
    assert find_category(_tree(off=("Electrical",)), ("Electrical", "DB & MCBs")) is None
    assert find_category([], ("Electrical", None)) is None  # a company without categories


def test_the_models_hint_in_words() -> None:
    tree = _tree()
    assert read_hint(tree, "Plumbing & CP > Pipes")["name"] == "Pipes"
    assert read_hint(tree, "plumbing & cp › pipes")["name"] == "Pipes"
    assert read_hint(tree, "Valves")["name"] == "Valves"  # one category has this name
    assert read_hint(tree, "Pipes & fittings") is None  # under fire protection AND gas: ambiguous
    assert read_hint(tree, "Gas > Pipes & fittings")["parent_id"] == next(c["id"] for c in tree if c["name"] == "Gas")
    assert read_hint(tree, "Carpentry") is None and read_hint(tree, "") is None  # never a new category
