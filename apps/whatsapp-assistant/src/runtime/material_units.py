"""A reported material unit against the material's stock unit (WA-39/WA-41).

One home for the rule, used by the classic unit gate
(runtime/inbound_journey/seeding.py) and the agent's direct material entry
(runtime/agent/material_entry.py, ARCH-01): a material is stocked in ONE unit,
so a report in that unit (or none) goes through as it is, a unit the company
or physics can convert is converted (keeping what was reported), and anything
else is a mismatch the caller asks about.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

_log = logging.getLogger(__name__)

#: Stock units of whole things: a conversion into one never gives a fraction.
COUNTED_UNITS = frozenset({"nos", "pcs", "rolls"})


@dataclass(slots=True)
class UnitFit:
    #: "ok": ``fields`` now carry ``unit_id`` (converted if needed).
    #: "mismatch": nothing changed; ask, using the units below.
    #: "unknown": a lookup failed -- let the report through unresolved.
    kind: str
    stock_unit: dict | None = None
    reported_unit: dict | None = None
    #: WA-61: a saved conversion that turned whole things into a fraction
    #: ("1 load" -> 0.333 nos): wrong, so it is asked again instead.
    doubtful: Any = None


async def fit_stock_unit(
    fields: dict[str, Any],
    material: dict[str, Any],
    *,
    catalog_query: Any,
    organization_id: str,
    correlation_id: str | None = None,
) -> UnitFit:
    """Settle ``fields["unit_id"]`` for ``material``; mutates ``fields`` on "ok"."""
    stock_unit_id = material.get("default_unit_id")
    if stock_unit_id is None or fields.get("unit_id") is not None:
        # No stock unit set up yet (nothing to enforce), or already settled.
        return UnitFit("ok")
    unit_text = fields.get("unit")
    if not unit_text:
        # Omitted: the stock unit, shown on the confirmation like any field.
        fields["unit_id"] = str(stock_unit_id)
        return UnitFit("ok")
    try:
        reported = await catalog_query.resolve_unit(unit_text)
    except Exception:  # noqa: BLE001 -- a failed lookup lets it through, as before
        _log.exception("unit_gate.lookup_failed correlation_id=%s", correlation_id)
        return UnitFit("unknown")
    if reported is not None and str(reported["id"]) == str(stock_unit_id):
        fields["unit_id"] = str(stock_unit_id)
        return UnitFit("ok")
    try:
        stock_unit = await catalog_query.get_unit(str(stock_unit_id))
    except Exception:  # noqa: BLE001
        _log.exception("unit_gate.lookup_failed correlation_id=%s", correlation_id)
        return UnitFit("unknown")
    qty = fields.get("quantity")
    if reported is not None and stock_unit is not None and qty is not None:
        # WA-41: the company said (or physics says) how many of this unit make
        # one stock unit: convert, keep what was reported, no question.
        per_stock_unit = await _conversion(catalog_query, organization_id, material, reported, stock_unit, correlation_id)
        if per_stock_unit is not None:
            from mesiri.domains.materials.unit_conversion import to_stock_quantity

            converted = to_stock_quantity(qty, per_stock_unit)
            if str(stock_unit.get("code") or "").lower() in COUNTED_UNITS and converted != converted.to_integral_value():
                _log.warning(
                    "unit_gate.doubtful_conversion material=%s converted=%s correlation_id=%s",
                    material.get("id"), converted, correlation_id,
                )
                return UnitFit("mismatch", stock_unit=stock_unit, reported_unit=reported, doubtful=converted)
            fields["reported_quantity"] = qty
            fields["reported_unit"] = str(unit_text)
            fields["quantity"] = float(converted)
            fields["unit"] = stock_unit["code"]
            fields["unit_id"] = str(stock_unit_id)
            return UnitFit("ok")
    return UnitFit("mismatch", stock_unit=stock_unit, reported_unit=reported)


def ask_amount_text(
    material: dict[str, Any], fields: dict[str, Any], fit: UnitFit, *, role: str | None
) -> str:
    """WA-39, under the agent: "40 bags sand" against sand counted in m³.
    Nothing is held: the model is told the fact and asks; the answer comes
    back as a new save. Someone who may set a conversion is asked for it once,
    for the company (WA-41)."""
    from mesiri.authorization.roles import may_set_unit_conversions

    stock = fit.stock_unit
    unit_display = stock["display_name"] if stock else "its stock unit"
    qty = fields.get("quantity")
    unit_text = fields.get("unit")
    said = " ".join(p for p in (str(qty) if qty is not None else "", str(unit_text)) if p)
    head = f"Not saved yet: {material['name']} is counted in {unit_display} here, so {said} can't be saved as it is."
    if fit.doubtful is not None:
        head = (
            f"Not saved yet: the company's saved conversion makes {said} of {material['name']} "
            f"{fit.doubtful.normalize():f} {unit_display}, which can't be right."
        )
    if fit.reported_unit is not None and may_set_unit_conversions(role):
        # WA-61: asked the way people know it ("1 load = 300 nos"); "how many
        # loads make 1 nos?" was unanswerable and got saved upside down.
        unit_word = str(fit.reported_unit.get("display_name") or unit_text).lower()
        return (
            f"{head} How many {unit_display} is 1 {unit_word} of {material['name']} (or how many "
            f"{unit_word} make 1 {unit_display})? I'll remember it for the company, "
            f"or tell me the amount in {unit_display}."
        )
    return (
        f"{head} How much is that in {unit_display}? (Your admin or project manager can "
        f"tell me how many {unit_text} make 1 {unit_display}, so this works next time.)"
    )


async def _conversion(
    catalog_query: Any,
    organization_id: str,
    material: dict,
    from_unit: dict,
    stock_unit: dict,
    correlation_id: str | None,
) -> Any:
    """How many ``from_unit`` make one stock unit, or None. Never raises: a
    failed lookup asks, as before."""
    find = getattr(catalog_query, "find_conversion", None)
    if find is None:
        return None
    try:
        return await find(
            organization_id=str(organization_id),
            material=material,
            from_unit=from_unit,
            stock_unit=stock_unit,
        )
    except Exception:  # noqa: BLE001
        _log.exception("unit_gate.conversion_lookup_failed correlation_id=%s", correlation_id)
        return None
