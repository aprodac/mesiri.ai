"""Standard materials per unit for common BOQ work (BOQ-04). Pure, no I/O.

The material plan (MP-02) needs each BOQ line's materials per unit (MP-01 norms), and an office typing them for
every line is why most projects had no plan. These are the usual Indian site consumption figures (nominal mixes, dry
volume 1.54 x wet for concrete, 1.27 x for mortar, cement 1,440 kg/m³ = 0.0347 m³ a 50 kg bag), offered for a line
whose work they clearly fit and put on only when the office says so, with the assumption written on each one
("M20 nominal 1:1.5:3") so it can be changed on the BOQ.

A figure is given per reference unit of work (m³, m², kg) in a reference material unit (bags, m³, nos, kg) and
converted to the line's own unit and the company material's stock unit; a material whose unit can't be converted
(sand bought by the "load") is left out and said, never guessed.

Worked example: "M20 RCC in slab", 1 cum -> 8.06 bags cement, 0.42 m³ sand, 0.84 m³ 20 mm aggregate. A line of
"Internal plastering 12 mm 1:4" in sqft -> per sqft 0.0084 bags cement and 0.0012 m³ sand (per m² 0.09 and 0.0125).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

D = Decimal

#: Work units: how many of the reference unit one of these is (the line's unit -> m³, m² or kg).
_WORK_UNIT = {
    "cum": ("cum", D(1)), "cft": ("cum", D("0.0283168")),
    "sqm": ("sqm", D(1)), "sqft": ("sqm", D("0.0929030")),
    "kg": ("kg", D(1)), "mt": ("kg", D(1000)), "tons": ("kg", D(1000)),
}

#: Material units: one reference unit (bags, cum, kg, nos, sqm, litres) in the material's stock unit.
_MATERIAL_UNIT = {
    ("bags", "bags"): D(1), ("bags", "kg"): D(50),
    ("cum", "cum"): D(1), ("cum", "cft"): D("35.3147"), ("cum", "brass"): D("0.353147"),
    ("kg", "kg"): D(1), ("kg", "mt"): D("0.001"), ("kg", "tons"): D("0.001"),
    ("nos", "nos"): D(1), ("nos", "pieces"): D(1),
    ("sqm", "sqm"): D(1), ("sqm", "sqft"): D("10.7639"),
    ("litres", "litres"): D(1),
}

#: Which of the company's materials each kind is, best first (names as the starter list spells them, BE-24).
_KINDS: dict[str, tuple[str, ...]] = {
    "cement": ("cement", "opc cement", "ppc cement", "opc", "ppc"),
    "sand": ("m sand", "sand", "p sand", "river sand"),
    "plaster_sand": ("p sand", "m sand", "sand", "river sand"),
    "aggregate_20": ("aggregate 20mm", "20mm aggregate", "metal 20mm", "aggregate"),
    "aggregate_40": ("aggregate 40mm", "40mm aggregate", "metal 40mm", "aggregate 20mm", "aggregate"),
    "bricks": ("bricks", "brick", "wire cut bricks", "country bricks"),
    "blocks": ("solid blocks", "solid block", "concrete blocks", "blocks"),
    "steel": ("tmt", "tmt steel", "steel", "tmt bars", "rod"),
    "binding_wire": ("binding wire",),
    "tiles": ("tiles", "floor tiles", "vitrified tiles"),
    "paint": ("paint", "emulsion"),
}


@dataclass(frozen=True, slots=True)
class Uses:
    kind: str
    quantity: Decimal
    unit: str  # reference material unit
    wastage: Decimal


@dataclass(frozen=True, slots=True)
class Standard:
    name: str  # the assumption, shown on each norm
    per: str  # reference work unit: cum, sqm or kg
    uses: tuple[Uses, ...]


def _u(kind: str, quantity: str, unit: str, wastage: str = "0") -> Uses:
    return Uses(kind, D(quantity), unit, D(wastage))


def _concrete(name: str, cement: str, sand: str, aggregate: str, size: str) -> Standard:
    return Standard(name, "cum", (_u("cement", cement, "bags", "2"), _u("sand", sand, "cum", "5"),
                                  _u(f"aggregate_{size}", aggregate, "cum", "5")))


PCC_148 = _concrete("PCC 1:4:8 nominal", "3.41", "0.47", "0.95", "40")
M10 = _concrete("M10 / 1:3:6 nominal", "4.44", "0.46", "0.92", "40")
M15 = _concrete("M15 / 1:2:4 nominal", "6.34", "0.44", "0.88", "20")
M20 = _concrete("M20 / 1:1.5:3 nominal", "8.06", "0.42", "0.84", "20")
BRICKWORK = Standard("Brickwork in CM 1:6, 500 bricks a m³", "cum",
                     (_u("bricks", "500", "nos", "5"), _u("cement", "1.32", "bags", "2"), _u("sand", "0.27", "cum", "5")))
HALF_BRICK = Standard("Half-brick wall 115 mm in CM 1:4", "sqm",
                      (_u("bricks", "58", "nos", "5"), _u("cement", "0.21", "bags", "2"), _u("sand", "0.03", "cum", "5")))
BLOCKWORK = Standard("Solid block 400x200x200 in CM 1:6", "cum",
                     (_u("blocks", "58", "nos", "3"), _u("cement", "0.38", "bags", "2"), _u("sand", "0.08", "cum", "5")))
STEEL = Standard("Reinforcement: 3% cutting waste, 8 kg binding wire a tonne", "kg",
                 (_u("steel", "1", "kg", "3"), _u("binding_wire", "0.008", "kg")))
TILES = Standard("Tiles, 5% cutting waste", "sqm", (_u("tiles", "1", "sqm", "5"),))
PAINT = Standard("Two coats of emulsion, about 10 m² a litre a coat", "sqm", (_u("paint", "0.2", "litres", "5"),))


def _plaster(mm: int, ratio: int) -> Standard:
    """Cement mortar plaster: dry mortar = thickness x 1.3; cement and sand from the ratio."""
    dry = D(mm) / 1000 * D("1.3")
    cement_cum = dry / (1 + ratio)
    bags = (cement_cum / D("0.0347")).quantize(D("0.001"), rounding=ROUND_HALF_UP)
    sand = (cement_cum * ratio).quantize(D("0.0001"), rounding=ROUND_HALF_UP)
    return Standard(f"Plaster {mm} mm in CM 1:{ratio}", "sqm",
                    (_u("cement", str(bags), "bags", "2"), _u("plaster_sand", str(sand), "cum", "5")))


_RATIO3 = re.compile(r"1\s*:\s*(\d(?:\.\d)?)\s*:\s*(\d+)")
_RATIO2 = re.compile(r"1\s*:\s*(\d)(?!\s*[:.\d])")
_GRADE = re.compile(r"\bm\s*-?\s*(\d{2})\b")
_MM = re.compile(r"(\d{2})\s*mm")


def standard_for(work: str | None, unit_code: str | None) -> Standard | None:
    """The standard a BOQ line's work clearly is, or None (a work, a grade or a unit it doesn't fit: never a guess).

    Concrete needs its grade or mix (M20, 1:1.5:3): plain "RCC" or a design mix above M20 is not guessed.
    """
    w = (work or "").lower()
    per = _WORK_UNIT.get((unit_code or "").lower(), (None,))[0]
    words = set(re.findall(r"[a-z]+", w))
    if per == "kg" and words & {"steel", "reinforcement", "rebar", "tmt", "bars"}:
        return STEEL
    if per == "sqm" and "plaster" in w:
        mm = int(m.group(1)) if (m := _MM.search(w)) else 12
        ratio = int(m.group(1)) if (m := _RATIO2.search(w)) else 6
        return _plaster(mm, ratio) if 6 <= mm <= 30 and 3 <= ratio <= 8 else None
    if per == "sqm" and words & {"tile", "tiles", "tiling", "vitrified"}:
        return TILES
    if per == "sqm" and words & {"paint", "painting", "emulsion"}:
        return PAINT
    if per == "sqm" and words & {"brick", "brickwork"} and (words & {"half"} or re.search(r"\b(4\.5|115|110)\b", w)):
        return HALF_BRICK
    if per != "cum":
        return None
    if words & {"brick", "brickwork"}:
        return BRICKWORK
    if words & {"block", "blocks", "blockwork"} and "solid" in w:
        return BLOCKWORK
    mix = _RATIO3.search(w)
    grade = _GRADE.search(w)
    by_mix = {("4", "8"): PCC_148, ("3", "6"): M10, ("2", "4"): M15, ("1.5", "3"): M20}
    if mix and (found := by_mix.get((mix.group(1), mix.group(2)))):
        return found
    if grade:
        return {"10": M10, "15": M15, "20": M20}.get(grade.group(1))
    return None


def _material_for(kind: str, materials: list[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    by_name = {str(m["name"]).strip().lower(): m for m in materials if m.get("is_active", True)}
    for name in _KINDS[kind]:
        if name in by_name:
            return by_name[name]
    for name in _KINDS[kind]:  # a longer name that starts with it ("Cement OPC 53", "TMT steel bars")
        found = sorted(n for n in by_name if n.startswith(name + " "))
        if found:
            return by_name[found[0]]
    return None


def suggest(work: str | None, unit_code: str | None, materials: Iterable[Mapping[str, Any]]) -> dict[str, Any] | None:
    """The norms to offer for one line: ``standard`` (the assumption), ``norms`` (material_id, material, unit,
    quantity_per_unit per ONE of the line's unit in the material's stock unit, wastage_pct, note) and ``missing``
    (kinds the company has no material for, or in a unit that can't be converted). None when no standard fits.

    ``materials``: the company's catalogue (id, name, unit = stock unit code, is_active).
    """
    standard = standard_for(work, unit_code)
    if standard is None:
        return None
    _, per_line_unit = _WORK_UNIT[(unit_code or "").lower()]
    listed = list(materials)
    norms, missing = [], []
    for use in standard.uses:
        material = _material_for(use.kind, listed)
        factor = _MATERIAL_UNIT.get((use.unit, str(material["unit"]).lower())) if material else None
        if material is None or factor is None:
            missing.append(use.kind.replace("_", " "))
            continue
        quantity = (use.quantity * per_line_unit * factor).quantize(D("0.0001"), rounding=ROUND_HALF_UP)
        if quantity <= 0:
            missing.append(use.kind.replace("_", " "))
            continue
        norms.append({"material_id": material["id"], "material": material["name"], "unit": material["unit"],
                      "quantity_per_unit": quantity, "wastage_pct": use.wastage, "note": f"Standard: {standard.name}"})
    return {"standard": standard.name, "norms": norms, "missing": missing}
