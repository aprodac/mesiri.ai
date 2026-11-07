#!/usr/bin/env python3
"""Claude's read-only window on Mesiri's live control plane (SA-16).

Talks to /claude-ops/* on the API (backend domains/admin/claude_ops_router.py)
with MESIRI_CLAUDE_OPS_TOKEN. Read-only: Postgres runs every request in a
READ ONLY transaction. Standard library only.

    python3 scripts/control_plane.py whoami
    python3 scripts/control_plane.py companies
    python3 scripts/control_plane.py tables
    python3 scripts/control_plane.py table daily_reports --limit 5
    python3 scripts/control_plane.py sql "SELECT count(*) FROM users"
    python3 scripts/control_plane.py messages --hours 6 --company Acme
    python3 scripts/control_plane.py traces --hours 6
    python3 scripts/control_plane.py failures --hours 24
    python3 scripts/control_plane.py reports --date 2026-10-24

Add --json to any command for the raw response. MESIRI_OPS_URL overrides the
API address (default https://api.whatsapp.mesiri.ai).
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import urllib.error
import urllib.request

DEFAULT_URL = "https://api.whatsapp.mesiri.ai"
MAX_CELL = 80


def _literal(text: str) -> str:
    """A SQL string literal (the API takes no parameters)."""
    return "'" + text.replace("'", "''") + "'"


def _hours(value: int) -> str:
    return f"now() - interval '{int(value)} hours'"


# ── Built-in queries ───────────────────────────────────────────────────────
# Phone numbers are cut to their last 4 digits. Times are India time.


def q_messages(hours: int, company: str | None, limit: int) -> str:
    where = f"m.received_at > {_hours(hours)}"
    if company:
        where += f" AND o.name ILIKE {_literal('%' + company + '%')}"
    return f"""
SELECT to_char(m.received_at AT TIME ZONE 'Asia/Kolkata', 'DD Mon HH24:MI') AS at_ist,
       o.name AS company, right(coalesce(m.sender_wa_id, ''), 4) AS sender,
       m.message_type AS kind, m.processing_status AS status, m.error_code,
       left(coalesce(m.body_text, (SELECT '🎤 ' || (jt.stage_payload::jsonb->>'text') FROM journey_traces jt
            WHERE jt.correlation_id = m.correlation_id AND jt.stage = 'agent_api_turn'
              AND m.message_type IN ('voice', 'audio') ORDER BY jt.created_at LIMIT 1)), 120) AS text,
       left(m.assistant_reply, 120) AS reply,
       m.correlation_id
FROM inbound_messages m LEFT JOIN organizations o ON o.id = m.organization_id
WHERE {where}
ORDER BY m.received_at DESC LIMIT {int(limit)}"""


def q_traces(hours: int, limit: int) -> str:
    """What the assistant decided per message: v3 (agent_api_turn) and classic (agent_tools). TM-41: this read
    only classic, so every v3 company looked like it had done nothing."""
    calls = ("jsonb_array_elements(CASE WHEN jsonb_typeof(t.stage_payload::jsonb->'calls') = 'array' "
             "THEN t.stage_payload::jsonb->'calls' ELSE '[]'::jsonb END) c")
    return f"""
SELECT to_char(t.created_at AT TIME ZONE 'Asia/Kolkata', 'DD Mon HH24:MI:SS') AS at_ist,
       CASE t.stage WHEN 'agent_api_turn' THEN 'v3' ELSE 'classic' END AS agent,
       o.name AS company, right(coalesce(m.sender_wa_id, ''), 4) AS sender, m.message_type AS kind,
       (SELECT string_agg(c->>'tool' || '=' || left(coalesce(c->>'status', c->'result'->>'status', ''), 24)
               || coalesce(' [by ' || (c->>'by') || ']', ''), '  ') FROM {calls}) AS tools,
       CASE WHEN t.stage = 'agent_api_turn' THEN concat_ws(' ',
           'FAILED ' || (t.stage_payload::jsonb->>'error') || ' -> ' || (t.stage_payload::jsonb->>'handled'),
           'saved ' || nullif(jsonb_array_length(coalesce(t.stage_payload::jsonb->'saved', '[]'::jsonb)), 0),
           'waiting ' || nullif(jsonb_array_length(coalesce(t.stage_payload::jsonb->'pending', '[]'::jsonb)), 0),
           'asked: ' || nullif(t.stage_payload::jsonb->>'asked', ''))
       ELSE concat_ws(' ', 'parked: ' || (t.stage_payload::jsonb->>'parked_by'),
                      'still to do: ' || (t.stage_payload::jsonb->>'still_to_do'))
       END AS outcome,
       t.duration_ms, t.correlation_id
FROM journey_traces t
LEFT JOIN inbound_messages m ON m.correlation_id = t.correlation_id
LEFT JOIN organizations o ON o.id = m.organization_id
WHERE t.stage IN ('agent_tools', 'agent_api_turn') AND t.created_at > {_hours(hours)}
ORDER BY t.created_at DESC LIMIT {int(limit)}"""


def q_why_empty(hours: int) -> str:
    """TM-41: what was there in the window, so an empty answer says whether nothing happened or the query missed it."""
    since = _hours(hours)
    return f"""
SELECT (SELECT count(*) FROM inbound_messages WHERE received_at > {since}) AS messages,
       (SELECT count(*) FROM journey_traces WHERE stage = 'agent_api_turn' AND created_at > {since}) AS v3_turns,
       (SELECT count(*) FROM journey_traces WHERE stage = 'agent_tools' AND created_at > {since}) AS classic_turns,
       (SELECT count(*) FROM journey_traces WHERE created_at > {since} AND succeeded = false) AS failed_stages,
       (SELECT to_char(max(received_at) AT TIME ZONE 'Asia/Kolkata', 'DD Mon HH24:MI') FROM inbound_messages)
         AS last_message_ever_ist"""


def q_failures(hours: int, limit: int) -> str:
    since = _hours(hours)
    return f"""
SELECT 'message' AS what, to_char(m.received_at AT TIME ZONE 'Asia/Kolkata', 'DD Mon HH24:MI') AS at_ist,
       o.name AS company, coalesce(m.error_code, m.processing_status) AS error,
       left(m.body_text, 100) AS detail, m.correlation_id
FROM inbound_messages m LEFT JOIN organizations o ON o.id = m.organization_id
WHERE m.received_at > {since} AND m.processing_status = 'failed'
UNION ALL
SELECT 'stage:' || t.stage, to_char(t.created_at AT TIME ZONE 'Asia/Kolkata', 'DD Mon HH24:MI'),
       NULL, t.error_code, left(t.error_message, 100), t.correlation_id
FROM journey_traces t
WHERE t.created_at > {since} AND t.succeeded = false
UNION ALL
SELECT 'provider:' || p.provider || '/' || p.operation,
       to_char(p.created_at AT TIME ZONE 'Asia/Kolkata', 'DD Mon HH24:MI'),
       o2.name, p.error_code, p.model, p.correlation_id
FROM provider_executions p LEFT JOIN organizations o2 ON o2.id = p.organization_id
WHERE p.created_at > {since} AND p.succeeded = false
UNION ALL
-- 7 Nov 2026: a v3 tool whose API call crashed (e.g. list_issues on a bad status)
-- is a succeeded turn with a wrong reply; it showed up nowhere else.
SELECT 'tool:' || (c->>'tool'), to_char(j.created_at AT TIME ZONE 'Asia/Kolkata', 'DD Mon HH24:MI'),
       o3.name, 'tool_failed', left(c->>'arguments', 100), j.correlation_id
FROM journey_traces j
CROSS JOIN LATERAL jsonb_array_elements(coalesce(j.stage_payload->'calls', '[]'::jsonb)) c
LEFT JOIN inbound_messages m3 ON m3.correlation_id = j.correlation_id
LEFT JOIN organizations o3 ON o3.id = m3.organization_id
WHERE j.created_at > {since} AND j.stage = 'agent_api_turn' AND c->'result'->>'error' = 'the tool failed'
ORDER BY at_ist DESC LIMIT {int(limit)}"""


def q_reports(date: str | None, company: str | None, limit: int) -> str:
    day = _literal(date) + "::date" if date else "(now() AT TIME ZONE 'Asia/Kolkata')::date"
    where = f"r.report_date = {day}"
    if company:
        where += f" AND o.name ILIKE {_literal('%' + company + '%')}"
    return f"""
SELECT r.report_date, o.name AS company, s.name AS site, r.level, r.status, r.code,
       r.missing_sections,
       to_char(r.updated_at AT TIME ZONE 'Asia/Kolkata', 'DD Mon HH24:MI') AS updated_ist
FROM daily_reports r
LEFT JOIN organizations o ON o.id = r.organization_id
LEFT JOIN sites s ON s.id = r.site_id
WHERE {where}
ORDER BY o.name, s.name LIMIT {int(limit)}"""


# ── HTTP ───────────────────────────────────────────────────────────────────


def _call(method: str, path: str, body: dict | None = None) -> dict:
    token = os.environ.get("MESIRI_CLAUDE_OPS_TOKEN", "").strip()
    if not token:
        sys.exit(
            "MESIRI_CLAUDE_OPS_TOKEN is not set. Add it to the Claude Code environment secrets"
            " (the same value as MESIRI_CLAUDE_OPS_TOKEN in /opt/mesiri/.env on the server)."
        )
    url = os.environ.get("MESIRI_OPS_URL", DEFAULT_URL).rstrip("/") + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode()).get("detail")
        except Exception:  # noqa: BLE001
            detail = None
        hint = {
            401: "the token was refused (wrong value?)",
            404: "the API is off on the server (MESIRI_CLAUDE_OPS_TOKEN not set there) or the path is wrong",
        }.get(exc.code, "")
        sys.exit(f"HTTP {exc.code}: {detail or exc.reason}{' — ' + hint if hint else ''}")
    except urllib.error.URLError as exc:
        sys.exit(f"Cannot reach {url}: {exc.reason}")


# ── Output ─────────────────────────────────────────────────────────────────


def _cell(value: object) -> str:
    if value is None:
        return ""
    text = json.dumps(value, ensure_ascii=False) if isinstance(value, dict | list) else str(value)
    text = " ".join(text.split())
    return text if len(text) <= MAX_CELL else text[: MAX_CELL - 1] + "…"


def print_table(columns: list[str], rows: list[list[object]]) -> None:
    cells = [[_cell(v) for v in row] for row in rows]
    widths = [max([len(c)] + [len(r[i]) for r in cells]) for i, c in enumerate(columns)]
    print("  ".join(c.ljust(w) for c, w in zip(columns, widths, strict=True)))
    print("  ".join("-" * w for w in widths))
    for row in cells:
        print("  ".join(v.ljust(w) for v, w in zip(row, widths, strict=True)))


def print_result(res: dict) -> None:
    if not res.get("columns"):
        print(f"(no columns) row_count={res.get('row_count')}")
        return
    print_table(res["columns"], res["rows"])
    more = f" — first {res.get('max_rows')} shown" if res.get("truncated") else ""
    print(f"\n{len(res['rows'])} row(s){more}, {res.get('duration_ms')} ms")


# ── Commands ───────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true", help="print the raw JSON response")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("whoami", help="check the token and the connection")
    sub.add_parser("companies", help="every company: status, trial, setup progress")
    sub.add_parser("tables", help="every table with estimated rows and size")
    t = sub.add_parser("table", help="a table's columns and newest rows")
    t.add_argument("name")
    t.add_argument("--limit", type=int, default=20)
    s = sub.add_parser("sql", help="one read-only SQL statement ('-' reads it from stdin)")
    s.add_argument("statement")
    m = sub.add_parser("messages", help="recent WhatsApp messages and the replies")
    m.add_argument("--hours", type=int, default=24)
    m.add_argument("--company")
    m.add_argument("--limit", type=int, default=50)
    tr = sub.add_parser("traces", help="what the assistant decided per message (tools called)")
    tr.add_argument("--hours", type=int, default=6)
    tr.add_argument("--limit", type=int, default=50)
    f = sub.add_parser("failures", help="failed messages, stages and provider calls")
    f.add_argument("--hours", type=int, default=24)
    f.add_argument("--limit", type=int, default=100)
    r = sub.add_parser("reports", help="daily reports (DPRs) of a day (default today, India)")
    r.add_argument("--date")
    r.add_argument("--company")
    r.add_argument("--limit", type=int, default=200)
    args = parser.parse_args(argv)

    if args.cmd == "whoami":
        res = _call("GET", "/claude-ops/whoami")
        print(json.dumps(res, indent=2) if args.json else f"OK — read-only access to database {res['database']}")
        return
    if args.cmd == "companies":
        res = _call("GET", "/claude-ops/companies")
        if args.json:
            print(json.dumps(res, indent=2))
            return
        rows = res["companies"]
        cols = ["name", "status", "effective_status", "trial_days_left", "signup_source", "created_at", "id"]
        cols = [c for c in cols if rows and c in rows[0]] or (list(rows[0]) if rows else ["name"])
        print_table(cols, [[row.get(c) for c in cols] for row in rows])
        print(f"\n{len(rows)} companies")
        return
    if args.cmd == "tables":
        res = _call("GET", "/claude-ops/tables")
        if args.json:
            print(json.dumps(res, indent=2))
            return
        print_table(
            ["table", "estimated_rows", "size_kb"],
            [[t["name"], t["estimated_rows"], t["size_bytes"] // 1024] for t in res["tables"]],
        )
        return
    if args.cmd == "table":
        res = _call("GET", f"/claude-ops/tables/{args.name}?limit={args.limit}")
        if args.json:
            print(json.dumps(res, indent=2))
            return
        print("columns: " + ", ".join(f"{c['name']} {c['type']}{' PK' if c['primary_key'] else ''}" for c in res["column_info"]))
        print()
        print_result(res)
        return

    if args.cmd == "sql":
        statement = sys.stdin.read() if args.statement == "-" else args.statement
    elif args.cmd == "messages":
        statement = q_messages(args.hours, args.company, args.limit)
    elif args.cmd == "traces":
        statement = q_traces(args.hours, args.limit)
    elif args.cmd == "failures":
        statement = q_failures(args.hours, args.limit)
    else:
        statement = q_reports(args.date, args.company, args.limit)
    res = _call("POST", "/claude-ops/sql", {"sql": statement})
    print(json.dumps(res, indent=2) if args.json else "", end="")
    if not args.json:
        print_result(res)
        if not res.get("rows") and args.cmd in ("messages", "traces", "failures"):
            # TM-41: "nothing" is never left unexplained: was there no traffic, or does the query miss it?
            why = _call("POST", "/claude-ops/sql", {"sql": q_why_empty(args.hours)})
            print("\nNothing found. In the same window:")
            print_result(why)


if __name__ == "__main__":
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)  # `| head` ends quietly
    main()
