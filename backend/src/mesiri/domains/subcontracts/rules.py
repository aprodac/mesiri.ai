"""Subcontract rules (NXT-06 / NXT-07): the bill check and what is deducted from a bill. Pure, no I/O.

**The check** (one rule; a bill is checked when it is recorded and again when anything changes): per work-order line,
- billed so far (every bill not rejected, this one included) above what was measured so far -> ``over_measured``;
- nothing measured on a line that is billed -> ``not_measured``;
- billed so far above the quantity agreed on the work order -> ``over_agreed``;
- a rate above the agreed rate -> ``rate_above``;
and for the bill: its amount different from its lines by more than ₹1 -> ``total_differs``.
No flag: the bill ``passed`` (payable). Any flag: ``flagged`` until a person approves it with a reason or rejects it.

**Deductions** on a payable bill (decisions D-S1, D-S2, approved 8 Nov 2026):
- retention: the work order's % of the bill, held until released (on completion / after the defect period);
- advance recovered: the work order's recovery % of the bill (by default the advance's share of the work order's
  value, so it is recovered evenly), never more than the advance still to recover;
- TDS (194C): when the company has it on, the bill's % (the work order's, else the subcontractor's, else 1%);
- net payable = bill - retention - advance recovered - TDS.

Worked example: bill ₹15,200; retention 5% = ₹760; advance ₹20,000 on a ₹1,52,000 work order recovers 13.16% =
₹2,000; TDS 1% = ₹152; net payable ₹12,288.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

_C = Decimal("0.01")
DEFAULT_TDS_PCT = Decimal("1")
DEFAULT_RETENTION_PCT = Decimal("5")

FLAG_WORDS = {
    "over_measured": "billed {extra} {unit} more than measured on {line}",
    "not_measured": "nothing measured yet on {line}",
    "over_agreed": "billed {extra} {unit} more than agreed on {line}",
    "rate_above": "rate ₹{rate} on {line}, agreed ₹{agreed}",
    "total_differs": "the bill says ₹{gross}, its lines add up to ₹{lines}",
}


def money(v: Decimal | int | str | None) -> Decimal:
    return Decimal(v or 0).quantize(_C, rounding=ROUND_HALF_UP)


def qty(v: Decimal) -> str:
    return format(Decimal(v).normalize(), "f")


def check_bill(
    lines: Mapping[Any, Mapping[str, Any]],
    measured: Mapping[Any, Decimal],
    billed_before: Mapping[Any, Decimal],
    bill_lines: Iterable[Mapping[str, Any]],
    gross: Decimal,
) -> list[dict[str, Any]]:
    """``lines``: work-order line id -> {description, unit, quantity, rate}. ``measured``: confirmed quantity per
    line. ``billed_before``: quantity on earlier bills (not rejected). ``bill_lines``: this bill's {line_id, quantity,
    rate}. Returns the flags (empty: passed), each {code, line_id, words}."""
    flags: list[dict[str, Any]] = []
    total = Decimal(0)
    for bl in bill_lines:
        line = lines[bl["line_id"]]
        name, unit = line["description"], line["unit"]
        q, rate = Decimal(bl["quantity"]), Decimal(bl["rate"])
        agreed = Decimal(line["rate"])
        total += q * rate
        to_date = Decimal(billed_before.get(bl["line_id"], 0)) + q
        done = Decimal(measured.get(bl["line_id"], 0))
        # ``excess``: the rupees this flag is about (what would be paid for work not done, or above the rate) --
        # summed as "over-billing caught" (the value strip).
        if done <= 0:
            flags.append(_flag("not_measured", bl["line_id"], q * rate, line=name))
        elif to_date > done:
            extra = min(to_date - done, q)
            flags.append(_flag("over_measured", bl["line_id"], extra * rate, extra=qty(to_date - done), unit=unit, line=name))
        if to_date > Decimal(line["quantity"]):
            extra = min(to_date - Decimal(line["quantity"]), q)
            flags.append(_flag("over_agreed", bl["line_id"], extra * rate, extra=qty(to_date - Decimal(line["quantity"])),
                               unit=unit, line=name))
        if rate > agreed:
            flags.append(_flag("rate_above", bl["line_id"], (rate - agreed) * q, rate=qty(rate), agreed=qty(agreed), line=name))
    if abs(money(total) - money(gross)) > Decimal("1"):
        flags.append(_flag("total_differs", None, max(money(gross) - money(total), Decimal(0)), gross=qty(money(gross)),
                           lines=qty(money(total))))
    return flags


def caught(flags: list[dict[str, Any]], gross: Decimal) -> Decimal:
    """What a bill's flags put at risk, once: the largest of each line's flags (a line billed above measured *and* at a
    higher rate is not counted twice), never more than the bill."""
    per_line: dict[Any, Decimal] = {}
    for f in flags:
        key = f.get("line_id") or "_bill"
        per_line[key] = max(per_line.get(key, Decimal(0)), Decimal(str(f.get("excess") or 0)))
    return min(money(sum(per_line.values(), Decimal(0))), money(gross))


def _flag(code: str, line_id: Any, excess: Decimal, **words: Any) -> dict[str, Any]:
    return {"code": code, "line_id": str(line_id) if line_id else None, "words": FLAG_WORDS[code].format(**words),
            "excess": str(money(excess))}


def recovery_pct(advance_agreed: Decimal | None, order_value: Decimal, set_pct: Decimal | None) -> Decimal:
    """The share of each bill that recovers the advance: as set on the work order, else the advance's share of the
    work order's value."""
    if set_pct is not None:
        return Decimal(set_pct)
    if not advance_agreed or order_value <= 0:
        return Decimal(0)
    return min(Decimal(100), Decimal(advance_agreed) / order_value * 100)


def deductions(
    gross: Decimal, *, retention_pct: Decimal, recovery_pct_: Decimal, advance_outstanding: Decimal,
    tds_pct: Decimal | None,
) -> dict[str, Decimal]:
    """What is held / recovered / deducted from a bill, and what is left to pay. ``tds_pct`` None: TDS off."""
    gross = money(gross)
    retention = money(gross * Decimal(retention_pct) / 100)
    advance = min(money(gross * Decimal(recovery_pct_) / 100), money(max(advance_outstanding, Decimal(0))))
    tds = money(gross * Decimal(tds_pct) / 100) if tds_pct else Decimal("0.00")
    net = gross - retention - advance - tds
    if net < 0:  # never below zero: the advance gives way first
        advance = max(Decimal(0), advance + net)
        net = gross - retention - advance - tds
    return {"gross": gross, "retention": retention, "advance": money(advance), "tds": tds, "net": money(net)}
