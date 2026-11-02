"""A test company's conversation as it happened: each message, Mesiri's reply, and what v3 did (2 Nov 2026).

For the team's OWN test companies only (Paraclette, Mesiri Test Builders, demo companies): customer
conversations are never printed by this script. Read-only, through the ops API (control_plane.py).

Usage: test_conversation.py <company name> [hours]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import control_plane as cp  # noqa: E402

TEST_COMPANIES = ("paraclet", "mesiri test builders", "demo")


def main() -> None:
    company = (sys.argv[1] if len(sys.argv) > 1 else "").strip()
    hours = int("".join(ch for ch in (sys.argv[2] if len(sys.argv) > 2 else "2") if ch.isdigit()) or 2)
    if not company or not any(t in company.lower() for t in TEST_COMPANIES):
        sys.exit("Only the team's own test companies (Paraclette, Mesiri Test Builders, demo companies).")
    name = cp._literal("%" + company + "%")
    sql = f"""
SELECT to_char(m.received_at AT TIME ZONE 'Asia/Kolkata', 'HH24:MI:SS') AS at_ist, m.message_type AS kind,
       m.processing_status AS status, left(coalesce(m.body_text, ''), 400) AS said,
       left(coalesce(m.assistant_reply, ''), 900) AS reply,
       (SELECT string_agg(c->>'tool' || coalesce('=' || left(c->'result'->>'status', 30), ''), ', ')
          FROM journey_traces t, jsonb_array_elements(CASE WHEN jsonb_typeof(t.stage_payload::jsonb->'calls') = 'array'
               THEN t.stage_payload::jsonb->'calls' ELSE '[]'::jsonb END) c
         WHERE t.correlation_id = m.correlation_id AND t.stage = 'agent_api_turn') AS tools,
       (SELECT t.stage_payload::jsonb->'pending' FROM journey_traces t
         WHERE t.correlation_id = m.correlation_id AND t.stage = 'agent_api_turn' LIMIT 1) AS waiting,
       m.correlation_id
FROM inbound_messages m JOIN organizations o ON o.id = m.organization_id
WHERE o.name ILIKE {name} AND m.received_at > now() - interval '{hours} hours'
ORDER BY m.received_at"""
    res = cp._call("POST", "/claude-ops/sql", {"sql": sql})
    cols = res["columns"]
    for row in res["rows"]:
        r = dict(zip(cols, row, strict=True))
        print(f"--- {r['at_ist']}  {r['kind']}  {r['status']}  {r['correlation_id']}")
        print(f"  THEY: {r['said']}")
        print(f"  MESIRI: {r['reply']}")
        print(f"  v3 tools: {r['tools'] or '-'}   waiting after: {r['waiting']}")
    print(f"\n{len(res['rows'])} message(s)")


if __name__ == "__main__":
    main()
