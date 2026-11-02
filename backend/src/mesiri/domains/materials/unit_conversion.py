"""Converting a reported quantity into a material's stock unit (WA-41).

A material is stocked in ONE unit (materials_catalog.default_unit_id). A site
reporting in another unit ("40 bags sand", sand stocked in m³) is converted
with ``per_stock_unit``: how many of the reported unit make one stock unit.
It comes from the company's own table (material_unit_conversions, set once by
an admin or project manager) or, for conversions that never vary, from
``built_in_per_stock_unit`` below. Pure: no I/O.
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal

#: (reported unit, stock unit) -> how many reported units make one stock unit.
#: Only physical facts; anything that depends on the material or the site
#: (bags of sand per m³) is the company's to set.
_FIXED: dict[tuple[str, str], Decimal] = {
    ("kg", "mt"): Decimal("1000"),
    ("kg", "tons"): Decimal("1000"),
    ("cft", "cum"): Decimal("35.3147"),
    # A brass is 100 cubic feet (2.83168 m³): how sand and metal are bought in Kerala.
    ("cft", "brass"): Decimal("100"),
    ("cum", "brass"): Decimal("2.83168"),
}

#: A cement bag is 50 kg in India (IS 269 packing).
CEMENT_BAG_KG = Decimal("50")


#: 2 Nov 2026 (Ilan, Paraclette: "10 TMT steel bars used", TMT stocked in kg): a steel bar's weight follows from its
#: diameter: D x D / 162 kg per metre (IS 1786 unit mass), and bars come in 12 m lengths. Only when the material's
#: name gives the diameter ("TMT 12mm", "Fe500 16 mm rod"); otherwise the company says it once.
BAR_LENGTH_M = Decimal("12")
_COUNT_UNITS = frozenset({"nos", "pieces", "pcs", "no", "numbers"})
_WEIGHT_IN_KG = {"kg": Decimal(1), "mt": Decimal(1000), "tons": Decimal(1000)}
_STEEL = re.compile(r"\b(tmt|steel|rebar|rod|rods|bar|bars|fe\s?\d{3}d?)\b", re.IGNORECASE)
_DIAMETER = re.compile(r"(\d{1,2}(?:\.\d)?)\s*mm\b", re.IGNORECASE)


def steel_bar_kg(material_name: str) -> Decimal | None:
    """The weight of one 12 m bar of this steel material, from the diameter in its name; None when not given."""
    if not _STEEL.search(material_name or ""):
        return None
    found = _DIAMETER.search(material_name or "")
    if not found:
        return None
    d = Decimal(found.group(1))
    if not Decimal(6) <= d <= Decimal(40):
        return None
    return (d * d / Decimal(162) * BAR_LENGTH_M).quantize(Decimal("0.001"))


def built_in_per_stock_unit(reported_unit: str, stock_unit: str, material_name: str) -> Decimal | None:
    """The fixed conversion between two unit codes for this material, or None."""
    pair = (reported_unit.lower(), stock_unit.lower())
    if pair in _FIXED:
        return _FIXED[pair]
    if pair[::-1] in _FIXED:
        return Decimal(1) / _FIXED[pair[::-1]]
    if pair[0] in _COUNT_UNITS and pair[1] in _WEIGHT_IN_KG:
        bar = steel_bar_kg(material_name)
        if bar:
            # How many bars make one stock unit (1 kg, or 1 tonne).
            return _WEIGHT_IN_KG[pair[1]] / bar
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
