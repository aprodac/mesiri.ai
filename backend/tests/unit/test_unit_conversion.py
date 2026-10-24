"""WA-41: a reported quantity in the material's stock unit."""

from __future__ import annotations

from decimal import Decimal

import pytest

from mesiri.authorization.roles import may_set_unit_conversions
from mesiri.domains.materials.unit_conversion import built_in_per_stock_unit, to_stock_quantity


@pytest.mark.parametrize(
    ("reported", "stock", "material", "per"),
    [
        ("kg", "mt", "Steel", Decimal("1000")),
        ("mt", "kg", "Steel", Decimal("0.001")),
        ("cft", "cum", "Sand", Decimal("35.3147")),
        ("kg", "bags", "Cement", Decimal("50")),  # 50 kg make one bag
        ("bags", "kg", "OPC Cement 53", Decimal("0.02")),  # 0.02 bag make one kg
        ("bags", "cum", "Sand", None),  # depends on the site: the company says
        ("bags", "kg", "Lime", None),
    ],
)
def test_only_fixed_facts_are_built_in(reported, stock, material, per):
    assert built_in_per_stock_unit(reported, stock, material) == per


def test_forty_bags_of_sand_at_twenty_eight_a_cubic_metre():
    assert to_stock_quantity(40, Decimal(28)) == Decimal("1.429")


def test_two_bags_of_cement_stocked_in_kg_are_a_hundred_kg():
    assert to_stock_quantity(2, Decimal("0.02")) == Decimal("100")


@pytest.mark.parametrize(("role", "may"), [("ADMIN", True), ("PROJECT_MANAGER", True), ("owner", True),
                                           ("SITE_ENGINEER", False), ("FINANCE", False), (None, False)])
def test_admins_and_project_managers_set_conversions(role, may):
    assert may_set_unit_conversions(role) is may


def test_a_brass_is_100_cubic_feet():
    from decimal import Decimal

    from mesiri.domains.materials.unit_conversion import built_in_per_stock_unit, to_stock_quantity

    assert built_in_per_stock_unit("cft", "brass", "M sand") == Decimal("100")
    assert to_stock_quantity(300, built_in_per_stock_unit("cft", "brass", "M sand")) == Decimal("3")
    # and the other way: 2 brass of sand counted in cft
    assert to_stock_quantity(2, built_in_per_stock_unit("brass", "cft", "M sand")) == Decimal("200")
