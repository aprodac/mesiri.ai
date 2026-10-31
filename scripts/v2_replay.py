#!/usr/bin/env python3
"""Replay real conversations and measure the assistant's UX (request 185).

    # 1. fetch the last N days of real conversations (read-only, via the control plane)
    python3 scripts/v2_replay.py fetch --days 5
    # 2. score what production actually answered (no model, no key)
    python3 scripts/v2_replay.py baseline
    # 3. replay them through v2 on the real model (needs GEMINI_API_KEY), same checks:
    MESIRI_REPLAY_CORPUS=~/.mesiri/replay/corpus.jsonl GEMINI_API_KEY=... \\
        pytest -m live apps/whatsapp-assistant/tests/agent_v2/test_replay_live.py -s

The corpus holds real customer words: it lives in ~/.mesiri/replay (outside the repository)
and is never committed. Needs MESIRI_CLAUDE_OPS_TOKEN for ``fetch``.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "whatsapp-assistant" / "src"))

from agent_v2.replay import corpus as cp  # noqa: E402
from agent_v2.replay.checks import check_conversation  # noqa: E402
from agent_v2.replay.report import Scored, details, summary  # noqa: E402

DEFAULT_CORPUS = cp.DEFAULT_DIR / "corpus.jsonl"


def _control_plane():
    spec = importlib.util.spec_from_file_location("control_plane", ROOT / "scripts" / "control_plane.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _query(day_from: str, day_to: str) -> str:
    return f"""
SELECT m.correlation_id, m.received_at, o.name AS org, right(m.sender_wa_id, 4) AS s,
       m.message_type AS t, m.processing_status AS st, m.error_code AS e,
       left(coalesce(m.body_text, m.normalized_message->>'text', ''), 1500) AS body,
       left(m.assistant_reply, 2000) AS reply,
       (SELECT array_agg(c->>'tool') FROM journey_traces j,
               jsonb_array_elements(j.stage_payload::jsonb->'calls') c
         WHERE j.correlation_id = m.correlation_id AND j.stage IN ('agent_tools', 'agent_v2_live')) AS tools
FROM inbound_messages m LEFT JOIN organizations o ON o.id = m.organization_id
WHERE m.received_at >= '{day_from}' AND m.received_at < '{day_to}'
ORDER BY m.received_at"""


def fetch(days: int, out: Path) -> None:
    from datetime import date, timedelta

    cpl = _control_plane()
    rows: list[dict] = []
    today = date.today()
    for back in range(days, -1, -1):  # one day per call: the API returns at most 500 rows
        day = today - timedelta(days=back)
        res = cpl._call("POST", "/claude-ops/sql", {"sql": _query(day.isoformat(), (day + timedelta(days=1)).isoformat())})
        if res.get("truncated"):
            print(f"warning: {day} has more than {res.get('max_rows')} messages; the rest are left out", file=sys.stderr)
        rows += [dict(zip(res["columns"], r, strict=True)) for r in res["rows"]]
    conversations = cp.group(rows)
    cp.save(conversations, out)
    turns = sum(len(c.turns) for c in conversations)
    print(f"{len(conversations)} conversations, {turns} turns -> {out}")


def baseline(corpus: Path, show: bool, which: str = "all") -> None:
    scored = []
    for conv in cp.split(cp.load(corpus), which):
        texts = [t.text for t in conv.turns]
        replies = [t.reply for t in conv.turns]
        kinds = [t.kind for t in conv.turns]
        scored.append(Scored(conv.key, len(conv.turns), check_conversation(texts, replies, kinds)))
    print(summary(f"production (what customers got), split={which}", scored))
    if show:
        print()
        print(details(scored))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("--days", type=int, default=5)
    f.add_argument("--out", type=Path, default=DEFAULT_CORPUS)
    b = sub.add_parser("baseline")
    b.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    b.add_argument("--details", action="store_true")
    b.add_argument("--split", choices=cp.SPLITS, default="all", help="tune: all but the newest day; holdout: the newest day")
    args = parser.parse_args(argv)
    if args.cmd == "fetch":
        fetch(args.days, args.out)
    else:
        baseline(args.corpus, args.details, args.split)


if __name__ == "__main__":
    main()
