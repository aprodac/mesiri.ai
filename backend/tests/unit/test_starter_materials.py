"""BE-24: the starter materials list is usable as-is (no database)."""

from __future__ import annotations

from mesiri.domains.materials.defaults import STARTER_MATERIALS

# Seeded by migration (0290 + the units_of_measure follow-ups); platform-wide.
_KNOWN_UNIT_CODES = {
    "bags", "kg", "tons", "litres", "pieces", "rolls",
    "boxes", "cum", "sqm", "sqft", "mt", "nos",
}  # fmt: skip


def test_names_are_unique_ignoring_case_and_spaces() -> None:
    # The catalogue's own uniqueness rule (uq_materials_catalog_org_name_ci).
    keys = [" ".join(m.name.lower().split()) for m in STARTER_MATERIALS]
    assert len(keys) == len(set(keys))


def test_every_unit_exists() -> None:
    assert {m.unit_code for m in STARTER_MATERIALS} <= _KNOWN_UNIT_CODES


def test_names_are_clean_and_categorised() -> None:
    for material in STARTER_MATERIALS:
        assert material.name == material.name.strip() and material.name
        assert material.category


def test_day_one_words_are_present() -> None:
    names = {m.name.lower() for m in STARTER_MATERIALS}
    assert {"cement", "sand", "m sand", "steel", "bricks", "solid blocks"} <= names
