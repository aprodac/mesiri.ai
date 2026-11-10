"""WA-265: keep the real-model eval's Gemini spend small and known.

The "SOP eval" workflow runs saved conversations on the real model. Each one costs a few rupees (see Prices), so the
workflow keeps a ledger for the day (a small JSON file in the Actions cache) and gives every run what is left of
the day's cap. ``replays/conftest.py`` reads the same usage log during the run and skips the conversations the
budget no longer covers. Standard library only: the workflow runs this file before anything is installed.

    python evalbudget.py remaining <ledger.json> <cap in rupees>     -> USD left today ("0" when none)
    python evalbudget.py add <ledger.json> <usage log.jsonl>         -> adds the run's spend, prints it in rupees
    python evalbudget.py told <ledger.json> <what>                   -> exit 0 the first time today, 1 after

Prices: on purpose on the high side. 10 Nov 2026: one run (36 calls, 1.4 million input tokens, 8,000 output) was
20 rupees by the Gemini 2.5 Flash table with cached input discounted, 95 rupees on the team bot's cost line, and the
key's top-ups ran out faster than the low figure allows. Until the real bill is known, input is counted at the
rate the team bot's figure implies and cached input gets no discount, so the cap stops a run early, not late.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

USD_PER_M_INPUT = 0.75
USD_PER_M_CACHED = 0.75
USD_PER_M_OUTPUT = 3.00
#: Rupees per dollar for the cap (an estimate; the cap is in rupees because that is what the team reads).
INR_PER_USD = 88.0


def call_usd(call: dict[str, Any]) -> float:
    cached = call.get("cached_input_tokens") or 0
    fresh = max((call.get("input_tokens") or 0) - cached, 0)
    out = call.get("output_tokens") or 0
    return (fresh * USD_PER_M_INPUT + cached * USD_PER_M_CACHED + out * USD_PER_M_OUTPUT) / 1_000_000


def spent_usd(log: str | Path) -> float:
    """What the calls in a usage log (one JSON object per line, tests/conftest.py) cost. A missing file is 0."""
    path = Path(log)
    if not path.is_file():
        return 0.0
    total = 0.0
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            total += call_usd(json.loads(line))
    return total


def _today() -> str:
    return dt.datetime.now(dt.UTC).date().isoformat()


def read_ledger(path: str | Path, today: str | None = None) -> dict[str, Any]:
    """Today's ledger; a ledger of another day (or none, or an unreadable one) starts again at zero."""
    today = today or _today()
    try:
        ledger = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        ledger = {}
    if not isinstance(ledger, dict) or ledger.get("date") != today:
        return {"date": today, "usd": 0.0, "told": []}
    return {"date": today, "usd": float(ledger.get("usd") or 0.0), "told": list(ledger.get("told") or [])}


def write_ledger(path: str | Path, ledger: dict[str, Any]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(ledger), encoding="utf-8")


def remaining_usd(ledger: dict[str, Any], cap_inr: float) -> float:
    return max(cap_inr / INR_PER_USD - ledger["usd"], 0.0)


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[0] not in {"remaining", "add", "told"}:
        print(__doc__)
        return 2
    command, path, value = argv
    ledger = read_ledger(path)
    if command == "remaining":
        print(f"{remaining_usd(ledger, float(value)):.4f}")
    elif command == "add":
        run = spent_usd(value)
        ledger["usd"] += run
        print(f"{run * INR_PER_USD:.2f}")
    else:
        if value in ledger["told"]:
            write_ledger(path, ledger)
            return 1
        ledger["told"].append(value)
    write_ledger(path, ledger)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
