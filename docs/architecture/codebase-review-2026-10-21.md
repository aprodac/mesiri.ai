# Mesiri codebase review — 21 Oct 2026

> Current mistakes and the recommended approach, for the V1 (construction DPR) launch.
> Prepared for Adarsh VP · 21 October 2026 · based on `main` at `a59eb62f` · Confidential, internal.
> Source: `Mesiri_Codebase_Review.pdf` (repo root), converted to Markdown 24 Oct 2026. Content
> unchanged; line numbers refer to `a59eb62f` and may have moved since.

## Summary

The product's foundations are sound: a modular single app, ports-and-adapters design,
multi-provider AI with fallback, database-level company separation (row-level security,
live since 19 Oct), a staging gate, and 4,134 passing unit tests with clean lint and type
checks. The problems are not old technology. They are two generations of the WhatsApp
assistant stacked on top of each other, gaps in production safety (backups, alerts, deploy
checks), and quality measured on reply wording rather than saved data.

- **Biggest risk before launch:** no backup leaves the server, no error alerts, and deploys
  can ship untested code or a half-loaded API.
- **Biggest product issue:** replies take 12 to 16 seconds, and two quick messages from one
  sender can be processed out of order.
- **Biggest developer slowdown:** the new AI agent feeds the old rule chain, so every fix
  touches both designs; about 1,600 lines of server code exist twice.

## A. The chatbot (AI design)

| # | Current mistake | Evidence | Recommended approach |
| --- | --- | --- | --- |
| 1 | **Two brains stacked.** The AI agent does not save anything itself: each tool call is turned into a fake "understanding" and pushed through the entire old rule chain. | Agent ADR: tools run through `process_inbound_message` | Tools call the business services directly; checks (unit, site, duplicates, permissions) live inside the services. |
| 2 | **The old rule chain is still the default for everyone.** The agent is on for one test company only. | `assistant_mode` defaults to off; migration 0485 enables "Mesiri Test Builders" only | Make the agent the default for construction once it passes the test set. |
| 3 | **Patching conversations rule by rule.** 16 tracker items in a row (WA-18 to WA-33) are conversation fixes, each adding special cases. | `message_journey.py` 2,777 lines; `seeding.py` 2,426 lines | Language understanding is the model's job; code enforces business rules only. Improve tools, context and examples, measured by tests. |
| 4 | **The AI sees every tool, even for switched-off modules,** and is refused afterwards. | `runtime/agent/runner.py:92` passes all 16 tool specs | Give the model only the tools the company has switched on. |
| 5 | **Photos go through two AI calls in a row** (read image, then extract). | Latency plan: image replies about 23 s | One call with the image and tools. |
| 6 | **Documented limits don't match the code:** the ADR says about 12 s per message; the code allows 25 s. | `runtime/agent/runner.py:36` | One agreed limit, written down and tested. |

## B. Reliability of the chatbot

| # | Current mistake | Evidence | Recommended approach |
| --- | --- | --- | --- |
| 7 | **No ordering per sender.** Messages are de-duplicated only by message ID and the worker runs several jobs at once. A quick correction ("12 masons" then "sorry, 14") or a forwarded batch can be processed at the same time and out of order. | `runtime/queue.py:151` job id is per message; no per-sender lock found | One message at a time per sender, in arrival order (per-sender lock in Redis or Postgres); different senders still run in parallel. |
| 8 | **Slow replies:** 8.6 s for "hi", 12 to 16 s for a site note; the reply waits for the receipt card. | Team board item B-7, 19 Oct measurements | Acknowledge within 1 s, send the text reply first and the card second, run saves in parallel, keep connections warm. |

## C. Measuring quality

| # | Current mistake | Evidence | Recommended approach |
| --- | --- | --- | --- |
| 9 | **Tests check what the reply says, not what was saved.** A reply can read well while wrong numbers are stored. | `tests/conversation/general_sequences.yaml` checks words; 13 replay cases for save flows | 50 to 100 real-style messages (Malayalam, Manglish, voice, photos) with the exact expected database records; run on every change and block deploys on a drop. |
| 10 | **Real-use mistakes are not fed back.** | No path from Undo / Fix taps to test cases | Every Undo or Fix tap becomes a candidate test case, reviewed weekly. |
| 11 | **No AI tracing and no error alerts.** Latency is found by searching server logs over SSH. | Custom `journey_traces`; `fetch-perf-logs.yml`; INF-07/08 still todo | Langfuse for prompts, tool calls, cost and time per message; Sentry for errors. |

## D. Code structure

| # | Current mistake | Evidence | Recommended approach |
| --- | --- | --- | --- |
| 12 | **Duplicate server code:** login, users, projects and admin exist twice; one copy is never deployed. | `backend/src/mesiri/domains/{identity,users,projects,admin}/router.py` vs `apps/whatsapp-assistant/src/...` | Keep one copy, delete the other. |
| 13 | **"Two apps" that are really one:** they import each other 75 and 76 times. | Import count across the two source trees | One app: business logic in `backend/`, WhatsApp as a thin channel. |
| 14 | **Code glued together with import-path settings;** tests fail with `ModuleNotFoundError` without them. | CLAUDE.md warns about this | A proper uv workspace with named packages. |
| 15 | **Five background-job systems:** ARQ, outbox consumers, timeline projector, systemd timers, and an automation loop inside the web server. | `runtime/lifecycle.py`, `infra/*.timer` | One system (ARQ jobs and scheduled tasks); nothing inside the web server. |
| 16 | **Design documents are wrong or empty:** 4 of 6 architecture documents are empty, and `Core-architecture.md` states a different V1 scope from the tracker. | `docs/architecture/` | Rewrite to match reality: short, current, one owner. AI sessions rely on these. |

## E. Production and operations

| # | Current mistake | Evidence | Recommended approach |
| --- | --- | --- | --- |
| 17 | **No backup leaves the server;** photos sit on one disk. | INF-06 in progress; `/var/lib/mesiri/media` | Managed Postgres with point-in-time restore, or at least a nightly off-server copy; photos in object storage. |
| 18 | **A deploy can ship untested code:** the server takes the newest `main`, not the tested commit. | `.github/workflows/deploy.yml`: `git reset --hard origin/main` | Deploy the exact tested commit (`github.sha`). |
| 19 | **Parts of the API can fail to load silently** and the health check still passes. | `runtime/lifecycle.py`: each router in try/except with a warning | Fail startup loudly; the health check confirms every part loaded. |
| 20 | **Every push goes to production** (up to 178 a day) and is reviewed only after it is live. | Git log; CLAUDE.md process | Deploy in batches with the test set and all checks as a gate. |
| 21 | **Login weaknesses:** unlimited password attempts, 7-day tokens that cannot be cancelled, server accepts requests from any website. | `domains/shared/auth.py`; CORS `*` in `lifecycle.py` | Limit attempts; shorter tokens with refresh and revocation; allow only Mesiri's own sites. |
| 22 | **Behind on runtimes and model:** Node 20 (end of life) in CI; Python 3.11 in CI vs 3.14 locally; Gemini 2.5 Flash (two generations old). | Workflows; `ai_active_routes` | Node 24 LTS; one pinned Python everywhere; test then switch to a current model. |

## Recommended order of fixes

| Stage | # | Action | Fixes |
| --- | --- | --- | --- |
| Before V1 launch | 1 | Off-server backups of the database and photos | #17 |
| Before V1 launch | 2 | Deploy the tested commit; fail startup when part of the API does not load | #18, #19 |
| Before V1 launch | 3 | Sentry error alerts and an uptime monitor | #11 |
| Before V1 launch | 4 | Per-sender message ordering (data-correctness risk) | #7 |
| Before V1 launch | 5 | Meta template approval and INR billing (owner tasks) | audit |
| After launch | 6 | Test set that checks saved records, run on every change | #9, #10 |
| After launch | 7 | Faster replies: instant acknowledgement, text first, parallel saves | #8 |
| After launch | 8 | Agent as default for construction; tools call services directly; retire the old chain flow by flow | #1 to #4 |
| V1.1 | 9 | Remove duplicate code; one app; proper packages; one background-job system | #12 to #15 |
| Any time | 10 | Rewrite the architecture documents | #16 |

## Approvals needed

Under the project's rules ([CLAUDE.md](../../CLAUDE.md)), these need Alan's approval before work starts:

- **#7 per-sender ordering and #8 WhatsApp pipeline changes:** Labour and Attendance flows run through this shared path.
- **#21 login and CORS changes:** security-sensitive.
- **#17 managed Postgres or new storage:** needs owner decision and credentials (Ilan).
- **#2 making the agent the default:** changes how every company's messages are handled (product decision).

Safe to start without approval: #10, #16, #22, and the deploy fixes #18 and #19.

## What was not verified

- Production's actual Python version, live data and today's reply times; latency figures come from the team's 19 Oct measurements.
- The per-sender ordering race (#7) was found by reading the queue and worker code; it has not been reproduced live. First check: two quick messages from one phone.
- GitHub CI history (the `gh` tool is not installed on this machine).
- The parked mobile app was not reviewed.

**Method:** automated checks across the whole repository (ruff, TypeScript, oxlint, the full
unit suite, a dashboard build, a secrets scan, dependency version checks) plus hand reading of
the deploy pipeline, server startup, authentication, the WhatsApp webhook and queue, the AI
agent, database connections and the V1 tracker.
