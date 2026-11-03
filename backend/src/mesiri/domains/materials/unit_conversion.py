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
#: Units that count pieces (WA-166: one container of a material counted this way is at least one piece).
COUNT_UNITS = frozenset({"nos", "pieces", "pcs", "no", "numbers"})
_COUNT_UNITS = COUNT_UNITS
_WEIGHT_IN_KG = {"kg": Decimal(1), "mt": Decimal(1000), "tons": Decimal(1000)}
_STEEL = re.compile(r"\b(tmt|steel|rebar|rod|rods|bar|bars|fe\s?\d{3}d?)\b", re.IGNORECASE)
_DIAMETER = re.compile(r"(\d{1,2}(?:\.\d)?)\s*mm\b", re.IGNORECASE)


#: WA-166 (Paraclette, 31 Oct: "1 load TMT" made TMT a material counted in loads, so every "10 bars used" was refused;
#: sand, M-sand and P-sand were counted in bags, so every "1 load" was). The unit a construction material is naturally
#: counted in, by what it is: a new material from WhatsApp gets this one, and what the site says converts into it.
#: Only kinds whose unit does not vary between companies; anything else keeps the unit the person used.
_NATURAL: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(tmt|steel|rebar|rods?|kambi|fe\s?\d{3}d?|binding\s*wire)\b|കമ്പി|സ്റ്റീൽ", re.IGNORECASE), "kg"),
    (re.compile(r"\b(m[\s-]?sand|p[\s-]?sand|sand|manal|metal|jelly|aggregate|gravel|quarry\s*dust)\b|മണൽ|എംസാ|പിസാ|"
                r"മെറ്റൽ", re.IGNORECASE), "cft"),
    (re.compile(r"\bcement\b|സിമ", re.IGNORECASE), "bags"),
    (re.compile(r"\b(bricks?|blocks?|hollow\s*bricks?|holo\s*bricks?|chenkallu|laterite|ishtika)\b|ഇഷ്ടിക|ചെങ്കല്ല",
                re.IGNORECASE), "nos"),
    (re.compile(r"\b(paint|primer|thinner|emulsion|enamel|varnish)\b|പെയിന്റ്|പ്രൈമർ", re.IGNORECASE), "litres"),
)


def natural_stock_unit(material_name: str) -> str | None:
    """The unit code this material is naturally counted in (TMT -> kg, M-sand -> cft), or None when its name does
    not tell (then the person's own unit is kept)."""
    for pattern, code in _NATURAL:
        if pattern.search(material_name or ""):
            return code
    return None


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
