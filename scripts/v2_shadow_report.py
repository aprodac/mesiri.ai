#!/usr/bin/env python3
"""Request 174 (Phase B): print the v2 shadow side-by-side for the team.

    python3 scripts/v2_shadow_report.py --hours 24          # reads the live control plane (read-only)
    python3 scripts/v2_shadow_report.py --file rows.json    # rows saved earlier

Needs the control plane token (scripts/control_plane.py) unless --file is used.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "apps" / "whatsapp-assistant" / "src"))

from agent_v2.report import side_by_side  # noqa: E402

SQL = (
    "SELECT created_at, correlation_id, stage_payload FROM journey_traces "
    "WHERE stage = 'agent_v2_shadow' AND created_at > now() - interval '{hours} hours' "
    "ORDER BY created_at LIMIT {limit}"
)


def fetch(hours: int, limit: int) -> list[dict]:
    out = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "control_plane.py"), "sql", SQL.format(hours=hours, limit=limit), "--json"],
        capture_output=True, text=True, check=True,
    ).stdout
    res = json.loads(out)
    return [dict(zip(res["columns"], row, strict=True)) for row in res["rows"]]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--file", help="a JSON list of rows (created_at, correlation_id, stage_payload)")
    args = parser.parse_args()
    rows = json.loads(Path(args.file).read_text(encoding="utf-8")) if args.file else fetch(args.hours, args.limit)
    print(side_by_side(rows) if rows else "No shadow rows in that time.")


if __name__ == "__main__":
    main()
