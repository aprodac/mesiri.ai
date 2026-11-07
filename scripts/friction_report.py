#!/usr/bin/env python3
"""Understanding + friction scores per company, from live WhatsApp traffic.

Ilan, 7 Nov 2026: "reliable means it understanding and not causing frictions".
This is the baseline every fix is measured against, rerun daily or after a
deploy. Read-only: it goes through the ops API like control_plane.py (needs
MESIRI_CLAUDE_OPS_TOKEN) and prints counts only, no message text.

    python3 scripts/friction_report.py            # last 7 days
    python3 scripts/friction_report.py --days 1   # today-ish

Columns (per company; the team's daily self-tests are left out):
  msgs       messages people sent (typed, voice, photos, taps)
  saves      taps answered with a save confirmation
  per_save   messages + taps per saved entry (target: 2 = one message + one tap)
  p50/p90 s  reply time for typed/voice messages (target p90 < 8 s)
  retype     replies asking the person to send / type it again (target 0)
  contra     replies saying "ready" and "not saved" at once (target 0)
  errors     replies showing an internal error (target 0)
  tool_err   AI tool calls that failed (each is a possible wrong reply)
  script     typed in Latin letters, answered with Malayalam script (target 0)
  noreply    messages with no reply after 5 minutes (target 0)

These are text patterns over the replies, so they undercount (a new wording
of "send again" is missed); a rise is a real signal, a zero is not proof.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from control_plane import _call  # noqa: E402

MALAYALAM = "[ഀ-ൿ]"

QUERY = r"""
WITH m AS (
  SELECT o.name AS company, im.correlation_id, im.message_type, im.body_text,
         coalesce(im.assistant_reply, '') AS reply, im.processing_status,
         extract(epoch FROM (im.processed_at - im.received_at)) AS secs,
         im.received_at
  FROM inbound_messages im JOIN organizations o ON o.id = im.organization_id
  WHERE im.received_at > now() - interval '{days} days'
    AND coalesce(im.body_text, '') NOT ILIKE '%SELFTEST-%'
    AND coalesce(im.body_text, '') NOT ILIKE '%daily check%'
), tool_err AS (
  SELECT j.correlation_id, count(*) AS n
  FROM journey_traces j, jsonb_array_elements(coalesce(j.stage_payload->'calls', '[]'::jsonb)) c
  WHERE j.stage = 'agent_api_turn' AND j.created_at > now() - interval '{days} days'
    AND c->'result' ? 'error'
  GROUP BY j.correlation_id
)
SELECT company,
  count(*) AS msgs,
  count(*) FILTER (WHERE message_type = 'interactive' AND reply ~* '(save aayi|saved)') AS saves,
  round((percentile_cont(0.5) WITHIN GROUP (ORDER BY secs) FILTER (WHERE message_type IN ('text','voice','audio')))::numeric, 1) AS p50,
  round((percentile_cont(0.9) WITHIN GROUP (ORDER BY secs) FILTER (WHERE message_type IN ('text','voice','audio')))::numeric, 1) AS p90,
  count(*) FILTER (WHERE reply ~* '(full line|onnu koodi ayakk|veendum ayakk|send (it|this|the line) again|type cheyy)'
                   AND reply NOT LIKE '👋%') AS retype,
  count(*) FILTER (WHERE reply ~* '(ready)' AND reply ~* '(save aayittilla|not saved|record aayilla)') AS contra,
  count(*) FILTER (WHERE reply ~* '(tool failed|traceback|exception|internal error)') AS errors,
  coalesce(sum(t.n), 0) AS tool_err,
  count(*) FILTER (WHERE message_type = 'text' AND body_text !~ '{ml}' AND reply ~ '{ml}') AS script,
  count(*) FILTER (WHERE reply = '' AND received_at < now() - interval '5 minutes') AS noreply
FROM m LEFT JOIN tool_err t USING (correlation_id)
GROUP BY company ORDER BY msgs DESC
"""

COLUMNS = ["company", "msgs", "saves", "per_save", "p50", "p90", "retype", "contra", "errors", "tool_err", "script", "noreply"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    res = _call("POST", "/claude-ops/sql", {"sql": QUERY.format(days=max(1, args.days), ml=MALAYALAM)})
    rows = [dict(zip(res["columns"], r, strict=False)) if isinstance(r, list) else r for r in res.get("rows", [])]
    for r in rows:
        r["per_save"] = round(r["msgs"] / r["saves"], 1) if r["saves"] else "-"
    if args.json:
        print(json.dumps(rows, indent=2, default=str))
        return 0
    widths = {c: max(len(c), *(len(str(r.get(c, ""))) for r in rows)) for c in COLUMNS} if rows else {}
    print("  ".join(c.ljust(widths.get(c, len(c))) for c in COLUMNS))
    for r in rows:
        print("  ".join(str(r.get(c, "")).ljust(widths[c]) for c in COLUMNS))
    print(f"\nlast {args.days} day(s); targets: per_save 2, p90 < 8 s, every other column 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
