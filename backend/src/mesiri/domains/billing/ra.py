"""An RA bill's money (NXT-02): pure, no I/O.

A line: this bill's quantity × the client rate = its amount. The bill:

- **gross** = the lines' amounts added up (what the work done this period is worth at the client's rates);
- **retention** = gross × retention % (held back by the client until the defect period ends);
- **advance recovery** = gross × recovery %, but never more than the mobilisation advance still to recover
  (the advance less what earlier bills recovered);
- **GST** = gross × GST % (on the work's value);
- **TDS** = gross × TDS % (the client deducts it and pays it to the tax department for the contractor);
- **net payable** = gross + GST − retention − advance recovery − TDS.

Every amount is rounded to the paisa, half up. Worked example: 120 m³ M20 at ₹6,500 + 800 m² plaster at ₹420 =
₹7,80,000 + ₹3,36,000 = gross ₹11,16,000; retention 5% ₹55,800; recovery 10% ₹1,11,600 (₹8,50,000 advance, none
recovered yet); GST 18% ₹2,00,880; TDS 2% ₹22,320; net ₹11,27,160.

The suggested quantity of a line = measured to date − already on earlier bills, never below zero.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

PAISA = Decimal("0.01")
_ZERO = Decimal(0)


def money(value: Decimal) -> Decimal:
    return value.quantize(PAISA, rounding=ROUND_HALF_UP)


def suggested(measured_to_date: Decimal, previous: Decimal) -> Decimal:
    return max(Decimal(measured_to_date) - Decimal(previous), _ZERO)


def line_amount(quantity: Any, rate: Any) -> Decimal:
    return money(Decimal(quantity) * Decimal(rate))


def totals(lines: Iterable[Mapping[str, Any]], terms: Mapping[str, Any], advance_left: Decimal) -> dict[str, Decimal]:
    """The bill's money from its lines (``quantity``, ``client_rate``) and its percentages."""
    gross = sum((line_amount(ln["quantity"], ln["client_rate"]) for ln in lines), _ZERO)

    def pct(key: str) -> Decimal:
        return Decimal(terms.get(key) or 0) / 100

    retention = money(gross * pct("retention_pct"))
    recovery = min(money(gross * pct("advance_recovery_pct")), max(money(Decimal(advance_left)), _ZERO))
    gst = money(gross * pct("gst_pct"))
    tds = money(gross * pct("tds_pct"))
    return {"gross": money(gross), "retention": retention, "advance_recovery": recovery, "gst": gst, "tds": tds,
            "net": money(gross + gst - retention - recovery - tds)}
