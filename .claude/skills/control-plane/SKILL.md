---
name: control-plane
description: Look at Mesiri's live production data (read-only) to investigate and debug. Use whenever a question or bug depends on what is actually in production ("why didn't Acme's DPR go out?", "which trials haven't sent an update?", "what did the bot do with Ravi's message?", "is anything failing?", "how many sites does X have?"), before guessing from code, and after a deploy to check it behaves.
---

# Control plane (live data, read-only)

`scripts/control_plane.py` reads the live database through the API's `/claude-ops/*` endpoints
(SA-16). Postgres runs every request read-only, so nothing you run can change data.

```bash
python3 scripts/control_plane.py <command>      # add --json for the raw response
```

It needs `MESIRI_CLAUDE_OPS_TOKEN` in the environment (the user adds it to the Claude Code
environment secrets). If it's missing, or the API answers 404 (turned off on the server), say so
and stop; don't guess what production holds.

## Commands

| Need | Command |
| --- | --- |
| Check access | `whoami` |
| Companies: status, trial days left, signup source, setup | `companies` |
| What tables exist | `tables` |
| A table's columns + newest rows | `table daily_reports --limit 5` |
| Recent WhatsApp messages and the bot's replies | `messages --hours 6 --company Acme` |
| What the assistant decided per message (tools called, parked, still to do) | `traces --hours 6` |
| What failed (messages, pipeline stages, AI/WhatsApp calls) | `failures --hours 24` |
| DPRs of a day and their status | `reports --date 2026-10-24 --company Acme` |
| Anything else | `sql "SELECT …"` (one statement; `sql -` reads it from stdin) |

Times in the built-in commands are India time; phone numbers are cut to the last 4 digits.

## Rules

- **Read-only.** SELECT / WITH / EXPLAIN / SHOW only, one statement, 15 s, 500 rows. To change
  data, tell the user what to run on the control panel's Database page (dry run first) or fix
  it in code; never look for a way round.
- **Secrets stay hidden.** Password hashes, provider API keys and login codes are refused or
  shown as `[hidden]`. Don't try to recover them.
- **Every SQL read is in the admin audit log** as "Claude (ops token)". Query what you need, not
  whole tables "just in case".
- **Customer data is real.** Quote only what the task needs. Names, numbers and message text
  stay out of commits, tracker notes and WhatsApp updates; refer to rows by id, company name or
  the correlation id instead.

## How to investigate

1. Start narrow: `companies` or `messages --company X` to find the right company and time.
2. Follow one message end to end by its `correlation_id`:
   `sql "SELECT stage, succeeded, error_code, left(error_message,120), duration_ms FROM journey_traces WHERE correlation_id = '…' ORDER BY created_at"`.
3. Check the code path that produced what you see, then say what you found (with the ids and
   times) before fixing anything. A fix follows the normal process (`CLAUDE.md`).

Useful tables: `organizations`, `users`, `projects`, `sites`, `inbound_messages` (every WhatsApp
message: `processing_status`, `error_code`, `assistant_reply`), `journey_traces` (per-stage trace,
`stage = 'agent_tools'` holds the assistant's tool calls), `provider_executions` (every AI /
WhatsApp call, cost, failures), `daily_reports` (DPRs: `status`, `missing_sections`),
`timeline_entries`, `activities`, `admin_audit_log`, `organization_settings`.
