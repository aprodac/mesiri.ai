# Mesiri architecture review: revised plan vs current code

> Prepared for Adarsh · 2 November 2026 · based on `main` at `4de146b5`.
> Reviews *Mesiri Revised Architecture & Incremental Migration Plan* (2 Nov 2026) against the
> repository. Static review of code and docs: no code was changed, production was not inspected,
> and no load tests were run.

**Verdict:** the revised plan is the right direction and fits the repository. Use it after the ten
fixes in section 2. Items marked **(R)** come from the
[21 Oct codebase review](docs/architecture/codebase-review-2026-10-21.md) and were not re-checked.

## 1. What's good in the revised plan

| # | Good point | Why it matters |
|---|---|---|
| 1 | Builds on the existing repo instead of a rewrite | Lower risk, and the product keeps working |
| 2 | One write path: AI and dashboard use the same API | Rules can't drift between WhatsApp and the web |
| 3 | Keeps the DPR state machine and versions | Tested logic isn't rebuilt |
| 4 | LangGraph only for new long-running processes | No extra complexity for simple saves |
| 5 | Small router: taps, commands, greetings only | The classic word-list problem doesn't come back |
| 6 | Keeps the AI provider resolver, fallback and cost tracking | Already works across 4 providers |
| 7 | v3 becomes primary only after measurement | Decided on results, not code cleanliness |
| 8 | Industry packs wait for a second industry | Shared parts come from real overlap |
| 9 | MCP, vector search and multi-company users wait | No work before there's a need |
| 10 | Production safety is P0 | Data loss and tenant leaks come first |
| 11 | Keeps the "mesiri bad ux" feedback loop | Real problems reach the team |
| 12 | Lists what is still unverified | It doesn't overclaim |

## 2. What needs fixing in the revised plan

| # | Problem in the plan | Fix |
|---|---|---|
| 1 | Save step drawn after the API | AI prepares → ready list → Save → API → checks → database |
| 2 | Classic missing from the diagram | Show classic; it's the default and every real customer uses it |
| 3 | No feature check against classic | List each classic workflow and mark it moved, kept elsewhere or dropped |
| 4 | "Measured validation" has no numbers | Agree targets: correct saves, wrong saves, reply time, fallback rate |
| 5 | P0 items in no order, some missing | Put them in order; add duplicate handling and failed jobs |
| 6 | "Replace fake photo storage" is outdated | Update it to match the tracker (INF-09) |
| 7 | Identity drawn before the queue; no deduplication | Queue → worker → sender lookup; add deduplication |
| 8 | No approvals named | Tenant rules, ordering and pipeline changes need Ilan's approval (Alan has left, 8 Nov 2026); backup storage needs owner credentials |
| 9 | Project rules still say "v2 skills, no router" | Ilan updates `CLAUDE.md` |
| 10 | No rule for building the second industry | Don't copy construction code |

## 3. What's strong in the current architecture

| # | Strength | Where it lives |
|---|---|---|
| 1 | v3 acts as the sender, with the same checks as the dashboard | `apps/whatsapp-assistant/src/agent_api/client.py` |
| 2 | AI can call only 28 allowed routes | `ALLOWED` in `agent_api/tools.py` |
| 3 | Nothing saved without Save; a repeat tap records once | `agent_api/whatsapp.py` |
| 4 | A refused entry stays in the list with a reason | v3 Save flow |
| 5 | DPR days freeze; late entries create a new version | `backend/src/mesiri/application/dpr/late_entries.py`, migration 0440 |
| 6 | Row-level security on 38 company tables, plus a test for new tables | migration 0484 |
| 7 | 4 AI providers with fallback; models set in the control panel | `platform/ai/src/mesiri_ai/resolver.py` |
| 8 | AI cost tracked per company without slowing replies | `platform/ai/src/mesiri_ai/usage.py`, migration 0478 |
| 9 | Assistant mode switched per company instantly | `assistant_mode` setting |
| 10 | Outage → queued and retried; other v3 errors → v2 | `runtime/ai_outage.py`, `FallBackToV2` |
| 11 | Staging on production data, restore point, auto rollback | `.github/workflows/deploy.yml` |
| 12 | Webhook and worker separated through Redis + ARQ | `apps/whatsapp-assistant/src/worker.py` |
| 13 | A message backlog is sorted by send time | `ingress/receiver.py` |
| 14 | v3 starts with sites, materials, today's records, 3 days of chat | `agent_api/whatsapp.py`, `agent_api/memory.py` |
| 15 | About 600 test files, boundary tests, tracing by message | `tests/`, `admin/logs_router.py` |
| 16 | User feedback → team bot → automatic build plans | `teammate/brain/src/prod_watch.js` |

## 4. Other improvements

| # | Area | Improvement | Priority |
|---|---|---|---|
| 1 | Reliability | Per-sender ordering across processes (lock in Redis or Postgres) | P0 |
| 2 | Reliability | Database-backed duplicate check for when Redis is down | P0 |
| 3 | Reliability | Outgoing message log so a retry can't send twice | P0 |
| 4 | Reliability | Failed-job store and replay (`backend/src/mesiri/events/dead_letter.py` is empty) | P0 |
| 5 | AI / v3 | Feature check between classic and v3 | P1 |
| 6 | AI / v3 | Pass or fail numbers before customers move | P1 |
| 7 | Testing | Tests on saved records for 50-100 real messages; Undo and Fix taps become new test cases (R) | P1 |
| 8 | Speed | Fast acknowledgement, text before card, parallel reads, timing v3's steps | P1 |
| 9 | Monitoring | Set `SENTRY_DSN` in production so error alerts actually run | P1 |
| 10 | Monitoring | AI tracing, such as Langfuse (R) | P1 |
| 11 | Code | Shrink `runtime/message_journey.py` (3,048 lines) as classic and v2 are retired | P2 |
| 12 | Code | Remove the duplicate login, users, projects and admin code (R) | P2 |
| 13 | Code | uv workspace instead of `PYTHONPATH` | P2 |
| 14 | Code | One background-job system instead of five (R) | P2 |
| 15 | Process | Deploy in batches, gated by the full test set (R) | P2 |
| 16 | Docs | Fill in `dependency-rules.md` and `module-boundaries.md` (empty); update `CLAUDE.md` for v3 | P2 |
| 17 | Tooling | Node 24 in CI and one pinned Python version (R) | P3 |

## 5. Recommended order

| Step | Work | Items in section 4 | Approval needed |
|---|---|---|---|
| 1 | Ordering, duplicates, delivery, failed jobs | 1–4 | Alan (the shared message path) |
| 2 | Prove v3 is ready | 5–10 | Product decision before customers move |
| 3 | Clean up code and process | 11–17 | No, except changes to shared modules |

## Not verified

| Item | Next action |
|---|---|
| Items marked (R) | Re-check before starting; some may be fixed since 21 Oct |
| v3 reply time and accuracy | Measure on real tester messages |
| Capacity | No load tests were run |
