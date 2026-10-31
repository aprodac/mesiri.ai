> **HISTORICAL (31 Oct 2026).** The WhatsApp assistant is now v2: one agent + skills + tools, see [../architecture/assistant-v2.md](../architecture/assistant-v2.md).
> This document describes the classic chain (classifier / planner / workflows), now retiring; the body is unchanged.

# Self-improving WhatsApp assistant — Implementation Plan

> Status: **WA-14 and WA-15 built** (14 Oct). WA-16–17 await approval.
> Tracker: WA-14 … WA-17 in [V1_TRACKER.md](V1_TRACKER.md).
> Requested 14 Oct 2026: "listen to the messages sent to the assistant, have Claude Code judge
> every reply, and keep improving it — speed, replies, UX, and adding workflows too — with as
> little human in the loop as possible."

## Objective

A scheduled loop in which Claude Code reads every real WhatsApp conversation, judges whether it
was handled well, finds recurring problems and unmet needs, and fixes them. Fixes include reply
copy, prompts, latency, and **new workflows**. Each fix is proven against replayed real
conversations before it reaches users.

**Watch → Judge → Diagnose → Fix → Check → Ship**, once a day (plus an hourly error alarm).
It does not run per message: one-off reactions chase noise, and a daily batch sees patterns.

## Business value

- Problems are found from real traffic, not from someone noticing a bad reply.
- The regression suite grows automatically from real failures, so fixes stop regressing.
- New capabilities are driven by what workers actually ask for, measured in counts.
- The least work for the construction worker: they never rate anything. Signals come from their
  behaviour.

## What already exists (reuse, don't duplicate)

| Need | Existing piece |
| --- | --- |
| Every message + reply | `inbound_messages` (`backend/postgres/message_logger.py`, `log_reply`) |
| Per-stage timings, AI calls | `journey_traces`, `provider_executions` (`trace_logger.py`) |
| Admin read API, platform-admin guard | `admin/logs_router.py`, `admin/perf_router.py`, `require_platform_admin` |
| Speed aggregates (p50/p95, worst offenders) | `perf_router.py` → `get_stage_summary`, `get_worst_offenders` |
| "I can't do that" path (unmet demand) | `channel/replies.py:render_unsupported_reply`, `runtime/capability_help.py` |
| Single table that defines a workflow | `workflows/registry.py` (`WorkflowDefinition`) |
| Per-company on/off switch | `enabled_modules` (BE-06) + gate in `inbound_journey/process.py` (WA-07) |
| Scenario/golden tests | `apps/whatsapp-assistant/tests/scenario`, `scenarios/`, `scripts/run_m4_golden_scenario.py` |
| Scheduled automation | Claude Code Routines (cloud, cron) or GitHub Actions (as `fetch-perf-logs.yml`) |

## Stages (each is its own phase; each waits for approval)

### WA-14 — Read-only review report (no product code changes)

- **API:** `GET /admin/review/export?since=…`, platform-admin only. It returns conversations
  grouped by sender over a window: messages, replies, workflow key/phase, stage timings, AI calls
  and error codes. Phone numbers are **hashed** and names masked. It reads through the existing
  `message_logger` / `trace_logger` (no new SQL owner).
- **Service account:** a platform-admin token for the reviewer, stored only as a Routine/Actions
  secret.
- **Reviewer:** a nightly Claude Code Routine (fresh session each run) follows
  [`docs/ops/assistant-review.md`](../ops/assistant-review.md), pulls the export with
  `apps/whatsapp-assistant/scripts/fetch_review_export.py` and scores each conversation against
  [`docs/product/assistant-review-rubric.md`](../product/assistant-review-rubric.md):
  1. Understood the request?
  2. Right action / right workflow?
  3. Reply short, clear, in the sender's language, right for someone on site?
  4. Fewest possible turns?
  5. Fast enough (per-stage p95 against baseline)?
- **Output:** a dated report (artifact + `docs/reviews/YYYY-MM-DD.md`) listing the worst
  conversations, recurring problems with counts, unmet requests clustered by intent, and latency
  regressions.
- **Alerts:** folded into the nightly report (an **ALERT** first line on failures or a p95 that
  doubled) rather than a separate hourly session, which would cost a full session every hour.
  A real-time alarm can come later if the nightly cadence proves too slow.
- Run it for 1–2 weeks. Alan checks that the scores match his own judgement and tunes the rubric.

### WA-15 — Friction signals + replay suite (built 14 Oct)

As built:
- **Friction signals** (`apps/whatsapp-assistant/src/admin/friction.py`, pure, no AI): repeat
  within 3 min, strong negative ("wrong", "galat", "thettu"…), weak negative (a bare "no"
  after a reply), correction/reverse workflow, abandoned workflow (conversation ends in an open
  phase), "can't do that" reply, failed message or stage, slow (> 15 s text, > 30 s media).
  Weighted into a score per conversation; every export conversation carries it, and the
  summary carries totals and friction rate per workflow.
- **Trend:** `GET /admin/review/friction?days=14` gives friction per local day and per
  workflow, so WA-16 can tell whether a fix helped.
- **Findings:** table `assistant_review_findings` (migration 0473, additive), one row per
  *problem* keyed by the reviewer's `fingerprint`, with occurrences, days seen, examples
  (pseudonymous refs only), linked replay cases, status (`open`/`fixing`/`fixed`/`wont_fix`)
  and fix commit. Recording a `fixed` problem again reopens it, so regressions are visible.
  `GET/POST /admin/review/findings`, `PATCH /admin/review/findings/{fingerprint}`; script
  `scripts/review_findings.py`. SQL owner: `backend/postgres/review_findings.py`.
- **Export:** each message now has a scrubbed `understanding` (type, language, fields), so a
  failure can be turned into a case.
- **Replay suite** (`apps/whatsapp-assistant/tests/replay/`): one message plus the recorded
  AI understanding, run through the real pipeline after the AI step (context,
  canonicalization, gates, planner, workflow registry, reply). Deterministic and offline. Cases
  are `passing` (regression guard) or `known_failure` (strict xfail: CI stays green while the
  bug exists, and turns red when it's fixed until the case is flipped). Seeded with 5 cases,
  including one real known failure: confirmations print internal field names
  (`material_name: cement`).
- **Runbook:** the nightly reviewer reads in friction order, records findings, writes a replay
  case for each recurring problem, and reports the 14-day trend.

**Different from the original plan:**
- Replay is "one real message, paraphrased onto the seed company", not a literal replay of
  production. A literal replay would need a copy of production data, and recorded raw AI
  responses, which aren't stored.
- Multi-turn replay (follow-up answers, button taps) is not done. It goes through
  `runtime/message_journey.py`, which takes about 45 dependencies → **WA-15b**.
- **CI gap:** CI installs without the `workflow` extra, so cases that reach a real workflow
  are skipped there. They run locally and in the nightly session. Adding `workflow` to
  `ci-python.yml` is a shared-CI change awaiting approval.

### WA-16 — Claude fixes what it finds (copy, prompts, examples, latency)

Each nightly run takes the top recurring problems (≥3 occurrences) and, for each one:
1. adds the replay case(s) that reproduce it (failing);
2. makes the smallest fix that turns them green;
3. runs the full verification set from CLAUDE.md Phase 5, plus the whole replay suite;
4. ships according to the tier below;
5. records it in the daily report and the tracker.

The **next day's** friction scores for the affected intent are compared with the day before. If
they got worse, the commit is reverted automatically (`git revert`, verified, pushed).

### WA-17 — Claude adds new workflows from unmet demand

- **Source:** clusters of unmet requests from WA-14/15 (unsupported replies, capability-help
  misses, requests forced into the wrong workflow). A cluster becomes a candidate at ≥5 requests
  from ≥2 companies in 14 days.
- **Build:** a new workflow follows the registry pattern exactly. That means a `WorkflowKey`
  value, a `WorkflowDefinition` row, `graph.py`/`nodes.py` (no AI or queries in nodes), and an
  application/validation layer in `backend` where a record is written. It comes with unit tests
  and replay cases built from the **actual messages that asked for it**.
- **Ships dark:** a new module key in `enabled_modules`, off for every company except the Mesiri
  team's own (pilot). The existing WA-07 gate already keeps it invisible and unusable elsewhere.
  No new flag system.
- **Promotion:** after N successful pilot uses with no friction signals, Claude proposes turning
  it on for everyone, with the evidence.
- **Hard limits:** never inside Labour/Attendance/Payroll/Workforce. Never a change to an
  existing table's columns; new tables only. Never anything that sends messages on its own
  schedule (templates, automations) without approval.

## Ship tiers (needs Alan's explicit override of CLAUDE.md for tier A)

| Tier | Covers | How it ships |
| --- | --- | --- |
| **A — auto** | Reply copy, prompts, classifier examples, capability-help text, latency fixes with no behaviour change; **a new workflow that ships switched off (pilot only)** | Pushed to `main` once all checks pass; listed in the daily report; auto-reverted if friction rises |
| **B — one-tap approval** | Changes to an existing workflow's logic, planner/routing rules, shared contracts beyond adding a `WorkflowKey`, turning a pilot workflow on for everyone, any migration | Fix written, tested, held as a patch in the report; pushed on approval |
| **C — always a person** | Labour/Attendance/Payroll/Workforce, money calculations, auth/tenancy, deletes, outbound template sends | Report only |

CLAUDE.md today requires approval at every phase and before touching shared components. Tier A
is an **exception to that rule** and only takes effect if Alan approves it in writing (to be
recorded in CLAUDE.md). Without it, everything runs as tier B: still automatic up to "ready
fix + evidence", with a human pressing go.

## Files expected to change

- New: `apps/whatsapp-assistant/src/admin/review_router.py`,
  `backend/postgres/review_findings.py`, `runtime/friction_signals.py`,
  `tests/replay/` (harness + cases), `docs/product/assistant-review-rubric.md`,
  `docs/reviews/`, one additive migration (WA-15)
- Modified: `admin/router` wiring (include the new router), `message_logger.py` /
  `trace_logger.py` (export read methods only), `docs/plans/V1_TRACKER.md`, `CLAUDE.md` (tier
  A exception, only if approved)
- Not touched by this plan: Labour, Attendance, Payroll, Workforce modules; dashboard

## Backend / API / Database work

- API: `GET /admin/review/export`, `GET /admin/review/findings`,
  `POST /admin/review/findings/{id}/status`
- DB: `assistant_review_findings` (additive, WA-15). WA-14 needs no DB change.
- Frontend: none for WA-14–16. A control-panel "Reviews" tab can come later under SA.

## Risks

| Risk | Mitigation |
| --- | --- |
| Auto-pushes break prod (no branches) | Full CLAUDE.md verification + replay suite before every push; auto-revert on friction rise; tier limits |
| Overfitting to one loud user | ≥3 occurrences before a fix; ≥2 companies before a new workflow |
| Customer data sent to Claude | Hash phones, mask names; confirm customer terms allow AI review (messages already go to Gemini/DeepSeek) |
| Admin token leakage | Read-only endpoint; dedicated token in Routine/Actions secrets only; rotate |
| Concurrent pushes by others | Pull → re-verify → push each time, per CLAUDE.md |
| Migration fork from an autonomous run | Head-number check right before writing; chain-fork check before push; migrations are tier B |
| Cost (AI review of every conversation) | Daily batch; send only flagged conversations plus a sample of healthy ones for full rubric review |
| Unattended new workflow writes bad records | Ships dark (pilot company only), save-first drafts with UNDO (WA-01) still apply |

## Testing strategy

- Unit tests for the export shaping, anonymisation (no raw phone ever leaves), friction signals.
- Replay suite in the normal pytest run; every fix must add a failing case first.
- Full Phase 5 verification set (backend, ruff, dashboard if touched, platform/ai, WhatsApp suite
  with PYTHONPATH).
- WA-14 dry run against a copy of yesterday's traffic before the Routine is scheduled.

## Rollback strategy

- WA-14: disable the Routine; the endpoint is read-only and can be removed with one revert.
- WA-15: the table is additive; the migration has a downgrade; the signals are read-only.
- WA-16: every fix is one commit; auto-revert on friction rise; disable the Routine to stop all
  activity at once.
- WA-17: switch the module off in `enabled_modules` (instant, no deploy); revert the commit.

## Labour isolation

The reviewer may **read** labour conversations to score them. It may never change Labour,
Attendance, Payroll or Workforce code; problems there are reported only (tier C).

## Success criteria

- WA-14: a daily report arrives for 7 consecutive days, and Alan agrees with ≥80% of its
  "bad conversation" picks.
- WA-15: every reviewed failure can be replayed deterministically; ≥20 real cases in the suite.
- WA-16: median turns per completed task and the friction rate fall week over week; zero
  regressions shipped that the replay suite should have caught.
- WA-17: at least one new workflow built from measured demand, used successfully in pilot.

## Decisions needed from Alan

1. Approve WA-14 to start (read-only, low risk).
2. Tier A auto-ship, including dark-launched new workflows: yes / no / later.
3. Confirm that customer conversations may be reviewed by Claude (anonymised).
4. Where the reviewer runs: Claude Code Routine (recommended: same environment as this repo) or
   GitHub Actions.
