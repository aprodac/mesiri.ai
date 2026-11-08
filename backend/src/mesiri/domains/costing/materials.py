"""Material reconciliation (CC-08). Pure, no I/O.

Per material, for a project: what the BOQ needs in all (planned x norm x (1 + wastage)), what the work done so far
should have used (done x norm x (1 + wastage), the BOQ lines' norms, MP-01), against what was received, consumed
(used on site) and is on hand, from the stock ledger (PRC-17). Two answers the GM asked for:

- **Used against the work** ("was that much metal needed for what was built?"): consumed against should-have-used,
  coloured with the labour thresholds (``variance.colour_of``): green when the work accounts for what was used,
  amber within 10%, red beyond. Nothing used yet, or no work done on a line with norms: grey, said.
- **Short at completion** ("4 loads of metal short at closeout", warned early): the need still to come
  (total - should-have-used) against on hand + on open orders; short_by > 0 is what to order beyond what is coming.

Quantities are in the material's stock unit (norms are written in it, MP-01). When the stock ledger holds the
material in another unit than the norm, nothing is compared (``unit_differs``): never a conversion made up.

Worked example: plastering 18,000 sq ft at 0.0045 bags of cement per sq ft + 5% wastage needs 85.05 bags; 640 sq ft
done should have used 3.02 bags. 4 bags used: 3.02 / 4 = 0.76, red, 0.98 bags more than the work accounts for.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from mesiri.domains.costing.variance import COLOUR_ORDER, colour_of

_Q = Decimal("0.01")
_ZERO = Decimal(0)


def _q(v: Decimal) -> Decimal:
    return v.quantize(_Q, rounding=ROUND_HALF_UP)


def reconcile(lines: Iterable[Mapping[str, Any]], stock: Mapping[Any, Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Per material: need, should-have-used, received, used, on hand, on order, the colour and the shortage.

    ``lines``: BOQ lines with ``planned``, ``done`` and ``norms`` [{material_id, material, unit, per_unit,
    wastage_pct}]. ``stock``: per material_id {unit, received, used, on_hand, on_order} for the project to date."""
    need: dict[Any, dict[str, Any]] = {}
    for line in lines:
        planned, done = Decimal(line["planned"]), Decimal(line.get("done") or 0)
        for n in line["norms"]:
            per = Decimal(n["per_unit"]) * (1 + Decimal(n.get("wastage_pct") or 0) / 100)
            row = need.setdefault(n["material_id"], {"material_id": n["material_id"], "material": n["material"],
                                                     "unit": n["unit"], "required_total": _ZERO,
                                                     "should_have_used": _ZERO, "lines": 0})
            row["required_total"] += planned * per
            row["should_have_used"] += done * per
            row["lines"] += 1
    out = []
    for material_id, row in need.items():
        held = stock.get(material_id) or {}
        unit_differs = bool(held.get("unit")) and held["unit"] != row["unit"]
        received, used = Decimal(held.get("received") or 0), Decimal(held.get("used") or 0)
        on_hand, on_order = Decimal(held.get("on_hand") or 0), Decimal(held.get("on_order") or 0)
        should = row["should_have_used"]
        if unit_differs:
            colour, ratio, reason = "grey", None, "unit_differs"
        elif used <= 0 and should <= 0:
            colour, ratio, reason = "grey", None, "nothing_yet"
        elif should <= 0:
            colour, ratio, reason = "red", _ZERO, "used_no_work"
        elif used <= 0:
            colour, ratio, reason = "grey", None, "no_usage_recorded"
        else:
            colour, ratio = colour_of(should, used)
            reason = {"green": "within_norm", "amber": "near_norm", "red": "over_norm"}[colour]
        still_needed = max(row["required_total"] - should, _ZERO)
        short_by = max(still_needed - on_hand - on_order, _ZERO) if not unit_differs else None
        out.append({
            **row, "required_total": _q(row["required_total"]), "should_have_used": _q(should),
            "received": _q(received), "used": _q(used), "on_hand": _q(on_hand), "on_order": _q(on_order),
            "used_over_work": _q(used - should) if not unit_differs else None,
            "still_needed": _q(still_needed), "short_by": _q(short_by) if short_by is not None else None,
            "stock_unit": held.get("unit"), "ratio": ratio, "colour": colour, "reason": reason,
        })
    return sorted(out, key=lambda r: (COLOUR_ORDER[r["colour"]], -(r["used_over_work"] or _ZERO), r["material"]))
