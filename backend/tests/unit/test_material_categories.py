"""PRC-01 / PRC-03: the builder's standard categories and the fixed rules that place a material."""

from __future__ import annotations

from mesiri.domains.materials.categories import (
    STANDARD_CATEGORIES,
    clean_category_name,
    standard_path_for,
)
from mesiri.domains.materials.defaults import STARTER_MATERIALS


def test_every_starter_material_has_a_place_in_the_standard_list() -> None:
    known = {(main, None) for main, _ in STANDARD_CATEGORIES} | {
        (main, sub) for main, subs in STANDARD_CATEGORIES for sub in subs
    }
    for material in STARTER_MATERIALS:
        path = standard_path_for(material.name, material.category)
        assert path in known, material.name


def test_the_name_rule_beats_the_broad_old_group() -> None:
    assert standard_path_for("PVC Pipe", "Plumbing") == ("Plumbing & CP", "Pipes")
    assert standard_path_for("  electrical   wire ", "Electrical") == ("Electrical", "Wires & cables")
    assert standard_path_for("Cement", "masonry") == ("Structural", "Masonry")


def test_nothing_is_guessed() -> None:
    # D5: only exact old groups the list knows; a near word or an unknown group stays unplaced.
    assert standard_path_for("Door handle", "Hardware") is None
    assert standard_path_for("Cement", None) is None
    assert standard_path_for("PVC pipes", None) is None


def test_names_inside_a_main_category_are_unique() -> None:
    for _, subs in STANDARD_CATEGORIES:
        assert len({s.lower() for s in subs}) == len(subs)
    assert len({m.lower() for m, _ in STANDARD_CATEGORIES}) == len(STANDARD_CATEGORIES)


def test_category_names_are_tidied() -> None:
    assert clean_category_name("  Switches   & sockets ") == "Switches & sockets"
    assert clean_category_name("   ") == ""
