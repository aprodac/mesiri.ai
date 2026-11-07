"""MK-02: an impossible company size is refused with the usual one; a possible or unknown one is not.

The cases are the real ones from production (31 Oct - 7 Nov 2026). The reference here mirrors migration 0515's seed;
``tests/integration/test_material_plausibility_postgres.py`` runs the same cases on the seeded tables.
"""

from __future__ import annotations

from decimal import Decimal

from mesiri.domains.materials.plausibility import Kind, Range, Reference, implausible, kind_of

TMT = Kind("tmt_bar", "TMT steel bar", ("tmt", "steel", "rod", "rods", "bar", "bars", "kambi", "fe500", "കമ്പി"),
           {"rule": "round_bar", "divisor": 162, "length_m": 12, "tolerance": 0.10})
SAND = Kind("sand", "Sand (M-sand, P-sand, river sand)", ("sand", "msand", "m sand", "p sand", "manal", "മണൽ"))
REF = Reference(
    kinds=(TMT, SAND),
    ranges={
        ("tmt_bar", "nos"): Range(Decimal(2), Decimal(100), "kg", "IS 1786"),
        ("sand", "load"): Range(Decimal(50), Decimal(600), "cft", "suppliers"),
        ("sand", "bags"): Range(Decimal("0.5"), Decimal(2), "cft", "site"),
    },
    facts={("tons", "kg"): Decimal(1000), ("cum", "cft"): Decimal("35.3147")},
)


def _check(name: str, from_code: str, stock_code: str, value: str) -> str | None:
    return implausible(REF, material_name=name, from_code=from_code, from_label=from_code, stock_code=stock_code,
                       stock_label=stock_code, one_unit_equals=Decimal(value))


def test_new_indias_sixty_cum_load_is_refused_with_the_usual_size() -> None:
    """New India, 5 Nov: "1 Loads M Sand = 60 Cubic Meters" was saved (about 2,119 cft)."""
    reason = _check("M Sand", "load", "cum", "60")
    assert reason is not None
    assert "2119" in reason and "50 to 600 cft" in reason and "as the bill or the supplier says" in reason


def test_a_usual_load_is_accepted_in_any_stock_unit() -> None:
    assert _check("M Sand", "load", "cum", "2") is None  # test company, 29 Oct: 70.6 cft
    assert _check("M Sand", "load", "cft", "150") is None  # a Kerala 150 cft load


def test_a_bag_of_sand_is_checked_too() -> None:
    assert _check("M Sand", "bags", "cum", "0.0357") is None  # 28 bags a cum (test company, 21 Oct)
    assert _check("P Sand", "bags", "cum", "1") is not None  # a bag of 1 m³


def test_a_bar_with_its_size_must_weigh_what_the_size_says() -> None:
    """A 12 mm bar of 12 m is ~10.67 kg (D²/162 x 12)."""
    assert _check("TMT 12mm", "nos", "kg", "10.5") is None
    reason = _check("TMT 12mm", "nos", "kg", "50")  # test company, 31 Oct: 20 bars = 1 ton
    assert reason is not None and "10.67 kg" in reason
    assert _check("TMT 12mm", "nos", "tons", "0.05") is not None  # the same 50 kg, stocked in tons


def test_a_bar_without_its_size_is_held_to_the_wide_range_only() -> None:
    """Without the size, 50 kg is possible (a 25 mm bar is ~46 kg): never refused on a guess."""
    assert _check("TMT steel bars", "nos", "tons", "0.05") is None
    assert _check("Steel", "nos", "kg", "12") is None  # "1 rod = 12 kg" (27 Oct)
    assert _check("Steel", "nos", "kg", "500") is not None


def test_what_the_reference_does_not_know_is_never_blocked() -> None:
    assert _check("Hollow Bricks", "load", "nos", "100000") is None  # no kind
    assert _check("M Sand", "bucket", "cum", "50") is None  # no range for this unit
    assert _check("Binding Wire", "nos", "kg", "500") is None  # not a bar


def test_the_kind_comes_from_the_items_own_name() -> None:
    assert kind_of("TMT steel bars", REF.kinds) is TMT
    assert kind_of("Rod steel", REF.kinds) is TMT
    assert kind_of("കമ്പി 8mm", REF.kinds) is TMT
    assert kind_of("M-Sand", REF.kinds) is SAND
    assert kind_of("Crowbar", REF.kinds) is None  # whole words only
    assert kind_of("Cement", REF.kinds) is None
