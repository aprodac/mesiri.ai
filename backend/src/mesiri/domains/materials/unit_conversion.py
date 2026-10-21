"""Converting a reported quantity into a material's stock unit (WA-41).

A material is stocked in ONE unit (materials_catalog.default_unit_id). A site
reporting in another unit ("40 bags sand", sand stocked in m³) is converted
with ``per_stock_unit``: how many of the reported unit make one stock unit.
It comes from the company's own table (material_unit_conversions, set once by
an admin or project manager) or, for conversions that never vary, from
``built_in_per_stock_unit`` below. Pure: no I/O.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

#: (reported unit, stock unit) -> how many reported units make one stock unit.
#: Only physical facts; anything that depends on the material or the site
#: (bags of sand per m³) is the company's to set.
_FIXED: dict[tuple[str, str], Decimal] = {
    ("kg", "mt"): Decimal("1000"),
    ("kg", "tons"): Decimal("1000"),
    ("cft", "cum"): Decimal("35.3147"),
}

#: A cement bag is 50 kg in India (IS 269 packing).
CEMENT_BAG_KG = Decimal("50")


def built_in_per_stock_unit(reported_unit: str, stock_unit: str, material_name: str) -> Decimal | None:
    """The fixed conversion between two unit codes for this material, or None."""
    pair = (reported_unit.lower(), stock_unit.lower())
    if pair in _FIXED:
        return _FIXED[pair]
    if pair[::-1] in _FIXED:
        return Decimal(1) / _FIXED[pair[::-1]]
    if "cement" in material_name.lower():
        if pair == ("kg", "bags"):
            return CEMENT_BAG_KG
        if pair == ("bags", "kg"):
            return Decimal(1) / CEMENT_BAG_KG
    return None


def to_stock_quantity(quantity: Decimal | float | int | str, per_stock_unit: Decimal) -> Decimal:
    """``quantity`` reported units in stock units, to 3 decimal places."""
    if per_stock_unit <= 0:
        raise ValueError("per_stock_unit must be positive")
    value = Decimal(str(quantity)) / per_stock_unit
    return value.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP).normalize()
