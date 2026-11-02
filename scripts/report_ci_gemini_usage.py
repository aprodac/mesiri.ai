"""Tell the team bot what a CI run's live tests spent on Gemini (TM-20).

The live tests call Gemini directly, so nothing records them in production's
cost rows. With MESIRI_USAGE_LOG set, tests/conftest.py writes one JSON line per
call; this reads the file, totals it per model at the prices in
mesiri.domains.usage.prices and posts each total to the listener, so
`@bot cost` shows a Testing line.

    PYTHONPATH=backend/src python scripts/report_ci_gemini_usage.py

Needs TEAMMATE_TOKEN (TEAMMATE_API has the same default as teammate/inbox.py).
A lost report must never fail the run: every problem is a warning and exit 0.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from mesiri.domains.usage.prices import ai_cost

DEFAULT_API = "https://api.whatsapp.mesiri.ai/teammate"
KIND = "ci_tests"


def totals(lines: list[str], *, at: dt.datetime) -> list[dict[str, Any]]:
    """One body for POST /ai/usage per model. `usd` is left out for a model we
    have no price for, and the listener then uses its own."""
    models: dict[str | None, dict[str, Any]] = {}
    for line in lines:
        if not line.strip():
            continue
        call = json.loads(line)
        if call.get("provider") != "gemini":
            continue
        model = call.get("model")
        row = models.setdefault(
            model, {"calls": 0, "input": 0, "output": 0, "usd": 0.0, "priced": True}
        )
        cost = ai_cost(
            provider="gemini",
            model=model,
            at=at,
            input_tokens=call.get("input_tokens"),
            cached_input_tokens=call.get("cached_input_tokens"),
            audio_input_tokens=call.get("audio_input_tokens"),
            output_tokens=call.get("output_tokens"),
        )
        row["calls"] += 1
        row["input"] += call.get("input_tokens") or 0
        row["output"] += call.get("output_tokens") or 0
        row["usd"] += float(cost.amount)
        row["priced"] = row["priced"] and cost.priced
    return [
        {
            "project": "mesiri",
            "kind": KIND,
            "model": model,
            "calls": row["calls"],
            "usage": {"promptTokenCount": row["input"], "candidatesTokenCount": row["output"]},
            **({"usd": row["usd"]} if row["priced"] else {}),
        }
        for model, row in models.items()
    ]


def post(body: dict[str, Any], *, api: str, token: str) -> None:
    request = urllib.request.Request(
        f"{api.rstrip('/')}/ai/usage",
        data=json.dumps(body).encode(),
        headers={"authorization": f"Bearer {token}", "content-type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20):
        pass


def main() -> int:
    path = Path(os.environ.get("MESIRI_USAGE_LOG", ""))
    if not path.is_file():
        print("No Gemini calls recorded in this run.")
        return 0
    token = os.environ.get("TEAMMATE_TOKEN", "")
    if not token:
        print("::warning::TEAMMATE_TOKEN is not set: this run's Gemini spend was not reported")
        return 0
    api = os.environ.get("TEAMMATE_API", DEFAULT_API)
    for body in totals(path.read_text(encoding="utf-8").splitlines(), at=dt.datetime.now(dt.UTC)):
        try:
            post(body, api=api, token=token)
            print(f"Reported {body['calls']} call(s) on {body['model']}")
        except (urllib.error.URLError, TimeoutError) as err:
            print(f"::warning::Gemini spend on {body['model']} not reported: {err}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
