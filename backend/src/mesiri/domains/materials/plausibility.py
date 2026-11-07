"""Is a company size possible? (MK-02, slice 1 of ADR-material-knowledge.)

"1 load M-sand = 60 cum" (New India, 5 Nov 2026) was saved: about 2,100 cft, more than four full tippers. A site clerk
would have stopped at it. The knowledge is data (``ref_unit_facts``, ``ref_material_kinds``, ``ref_kind_ranges``,
migration 0515, each row with its source); this module only knows how to apply it:

- which kind a catalogue item is: a word of the kind in the item's name ("TMT 12mm" -> TMT bar, "M Sand" -> sand);
- a round bar whose size is in its name: its weight follows from the mass rule, within the rule's tolerance;
- otherwise the kind's usual range for that unit, compared in the range's own unit (through the unit facts).

Anything it cannot place (an unknown kind, a unit with no range, no unit fact to compare with) is allowed: the check
catches the impossible, never the unusual, and never blocks what it does not know.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

_DIAMETER = re.compile(r"(\d{1,2}(?:\.\d)?)\s*mm\b", re.IGNORECASE)


@dataclass(frozen=True)
class Kind:
    code: str
    name: str
    words: tuple[str, ...]
    mass_rule: dict[str, Any] | None = None


@dataclass(frozen=True)
class Range:
    low: Decimal
    high: Decimal
    unit: str
    source: str


@dataclass(frozen=True)
class Reference:
    kinds: tuple[Kind, ...] = ()
    #: (kind code, from unit code) -> range
    ranges: dict[tuple[str, str], Range] = field(default_factory=dict)
    #: (from code, to code) -> how many ``to`` one ``from`` is
    facts: dict[tuple[str, str], Decimal] = field(default_factory=dict)


async def load_reference(conn: AsyncConnection) -> Reference:
    kinds = (await conn.execute(text("SELECT code, name, words, mass_rule FROM ref_material_kinds"))).mappings().all()
    ranges = (await conn.execute(text(
        "SELECT kind_code, from_unit_code, to_unit_code, min_value, max_value, source FROM ref_kind_ranges"
    ))).mappings().all()
    facts = (await conn.execute(text("SELECT from_code, to_code, factor FROM ref_unit_facts"))).mappings().all()
    return Reference(
        kinds=tuple(
            Kind(r["code"], r["name"], tuple(r["words"] or ()),
                 r["mass_rule"] if isinstance(r["mass_rule"], dict | None) else json.loads(r["mass_rule"]))
            for r in kinds
        ),
        ranges={(r["kind_code"], r["from_unit_code"]): Range(Decimal(r["min_value"]), Decimal(r["max_value"]),
                                                             r["to_unit_code"], r["source"]) for r in ranges},
        facts={(r["from_code"], r["to_code"]): Decimal(r["factor"]) for r in facts},
    )


def kind_of(material_name: str, kinds: tuple[Kind, ...]) -> Kind | None:
    """The kind a catalogue item's name says it is; the longest matching word wins ("m sand" over "sand")."""
    name = f" {re.sub(r'[^0-9a-zഀ-ൿ]+', ' ', (material_name or '').casefold())} "
    best: tuple[int, Kind] | None = None
    for kind in kinds:
        for word in kind.words:
            key = re.sub(r"[^0-9a-zഀ-ൿ]+", " ", word.casefold()).strip()
            if key and f" {key} " in name and (best is None or len(key) > best[0]):
                best = (len(key), kind)
    return best[1] if best else None


def factor(facts: dict[tuple[str, str], Decimal], from_code: str, to_code: str) -> Decimal | None:
    """How many ``to_code`` one ``from_code`` is, from the unit facts (either direction); None when unknown."""
    if from_code == to_code:
        return Decimal(1)
    if (from_code, to_code) in facts:
        return facts[(from_code, to_code)]
    if (to_code, from_code) in facts:
        return Decimal(1) / facts[(to_code, from_code)]
    return None


def _num(value: Decimal) -> str:
    """Said the way a person says it: whole numbers from 100 up ("2119 cft", not "2118.88"), else two decimals."""
    step = Decimal("1") if abs(value) >= 100 else Decimal("0.01")
    return f"{value.quantize(step).normalize():f}"


@dataclass(frozen=True)
class Verdict:
    """Why a size cannot be right, and what is usual: ``reason`` in plain words; ``low``..``high`` ``unit`` the usual
    size (for a sized bar, the expected weight both ways of its tolerance); ``value`` the size said, in that unit."""

    reason: str
    low: Decimal
    high: Decimal
    unit: str
    value: Decimal


def assess(
    reference: Reference,
    *,
    material_name: str,
    from_code: str,
    from_label: str,
    stock_code: str,
    stock_label: str,
    one_unit_equals: Decimal,
) -> Verdict | None:
    """The verdict on "1 ``from`` of the material = ``one_unit_equals`` ``stock``"; None when it is possible or the
    reference has nothing to say."""
    kind = kind_of(material_name, reference.kinds)
    if kind is None:
        return None
    said = f"1 {from_label} of {material_name} = {_num(one_unit_equals)} {stock_label}"
    rule = kind.mass_rule or {}
    size = _DIAMETER.search(material_name or "")
    to_kg = factor(reference.facts, stock_code, "kg")
    if rule.get("rule") == "round_bar" and size and to_kg is not None and (kind.code, from_code) in reference.ranges:
        diameter = Decimal(size.group(1))
        length = Decimal(str(rule["length_m"]))
        expected = diameter * diameter / Decimal(str(rule["divisor"])) * length
        tolerance = Decimal(str(rule.get("tolerance", "0.1")))
        weight = one_unit_equals * to_kg
        if abs(weight - expected) <= expected * tolerance:
            return None
        return Verdict(
            reason=(f"{said} looks wrong: that is {_num(weight)} kg a piece, and a {diameter.normalize():f} mm bar of "
                    f"{_num(length)} m weighs about {_num(expected)} kg. How much does one piece weigh, as the bill "
                    "says?"),
            low=expected * (1 - tolerance), high=expected * (1 + tolerance), unit="kg", value=weight,
        )
    limits = reference.ranges.get((kind.code, from_code))
    if limits is None:
        return None
    to_range_unit = factor(reference.facts, stock_code, limits.unit)
    if to_range_unit is None:
        return None
    value = one_unit_equals * to_range_unit
    if limits.low <= value <= limits.high:
        return None
    return Verdict(
        reason=(f"{said} looks wrong: that is {_num(value)} {limits.unit}, and 1 {from_label} of "
                f"{kind.name.split(' (')[0]} is usually {_num(limits.low)} to {_num(limits.high)} {limits.unit}. How "
                f"much is 1 {from_label}, as the bill or the supplier says?"),
        low=limits.low, high=limits.high, unit=limits.unit, value=value,
    )


def implausible(reference: Reference, **said: Any) -> str | None:
    """``assess``'s reason only (the size route's 422)."""
    verdict = assess(reference, **said)
    return verdict.reason if verdict else None
