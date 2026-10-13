# Mesiri V1 Tracker — DPR for construction

> **The single list of V1 work.** Every session (Claude Code or human) checks this file
> before starting V1 work and updates it when claiming and finishing an item.
>
> - **What V1 is:** one feature, an automatic daily progress report (DPR) for construction
>   companies, on production-grade foundations (AI layer, tenancy, infra, superadmin,
>   dashboard). Surfaces: **web dashboard + WhatsApp assistant only**. Mobile app parked.
> - **Why and what was decided:** the architecture doc
>   ([Mesiri — Target Architecture](https://claude.ai/code/artifact/399eaa7f-c055-4e17-b3aa-a916670dd901)),
>   the [database map](https://claude.ai/code/artifact/80bacce6-0497-4a75-aa1b-08a5cd93c259)
>   and the [UI design](https://claude.ai/artifact/WW1bwDkePpTp8EWK2EswBu).
> - **Process:** [CLAUDE.md](../../CLAUDE.md) still applies to every item: investigate,
>   plan, wait for approval, implement, test, push to `main`, report.

## How to use this file with several sessions at once

1. **Pull first.** `git pull origin main`, then read this file.
2. **Pick an item** whose status is `todo` and whose **Depends on** items are all `done`
   (or say `—`). Prefer `Must` over `Later`.
3. **Claim it before working.** Change its row to `claimed`, put your name/session in
   **Owner**, then commit and push *only this file* straight away:
   `git commit -m "tracker: claim BE-15"`. If the push is rejected, pull: if someone else
   claimed it first, pick another item.
4. **One item per session at a time.** Don't edit other people's rows, except to add a note.
5. **While working:** `in-progress`. If stuck on a decision or another item: `blocked`
   with the reason in **Notes**.
6. **When finished and pushed:** `done`, with the commit hash(es) in **Notes**. Commit
   messages for the work itself start with the item ID, e.g. `feat(dpr): BE-15 add site_days`.
7. **New work found?** Add a row at the end of the right section with the next free ID,
   status `todo`, and say so in your report. Don't renumber existing IDs.

**Status values:** `todo` · `claimed` · `in-progress` · `blocked` · `done` · `dropped`
**Size (rough, focused days):** S ≈ 1 · M ≈ 2–4 · L ≈ 5–10. Estimates, not commitments.

## Decisions still open (block the items listed)

| Decision | Blocks | Status |
| --- | --- | --- |
| Approve single identity model (retire the assistant's `context_*` copy) | BE-01, and everything that depends on it | **Approved 13 Oct.** The copy is not a digital twin (M6.5 doc: twin state must use control-plane IDs); its useful fields move onto the main tables |
| Who approves a site DPR: engineer only, or engineer then PM/owner | WA-06, WEB-04 | **Decided 13 Oct: the site engineer only.** Evening: if the site DPR is ready it is sent to the site engineer; if not, the engineer is asked for the missing details. Once the engineer confirms, it goes to the owner/PM and the other recipients. No separate owner approval |
| Client logo on project DPRs in V1? | BE-19 | **Decided 13 Oct: yes.** Uploadable from the web dashboard and by sending it on WhatsApp (BE-33, WA-13) |
| Signature/stamp image on approved DPRs in V1? | BE-19 | **Decided 13 Oct: no**, not in V1 |
| Material transfers between sites in V1? | BE-12 | **Decided 13 Oct: yes** (BE-32) |
| Photo storage: VPS disk or Cloudflare R2? | INF-09 | **Decided 13 Oct: VPS disk.** R2 stays available as a setting for later |

---

## INF — Shipping & infrastructure

| ID | Item | Size | Priority | Depends on | Status | Owner | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| INF-01 | Read-only VPS check (RAM, disk, cron, timers, backups, ports, DBs) | S | Must | — | blocked | Claude (session 13 Oct) | Needs Ilan to run the check script; Claude's own SSH is blocked by the safety classifier. Script now in the repo: `infra/deploy/vps_check.sh` (read-only, prints no secrets; also covers BE-30, BE-31, INF-09) |
| INF-02 | Staging environment: `/opt/mesiri-staging`, DB `mesiri_staging`, port 8001, nginx, `staging.mesiri.mercon.tech`, services | M | Must | INF-01 | todo | | Automated tests use simulated WhatsApp; a Meta test number is optional for manual testing |
| INF-03 | Deploy pipeline: push to main → staging → smoke test → prod backup → prod → smoke test | M | Must | INF-02, INF-04 | todo | | Approved 13 Oct 2026 |
| INF-04 | Backup-before-migrate and post-deploy smoke test scripts | S | Must | — | in-progress | Claude (session 13 Oct) | Scripts written and pushed (`94f88fd`, `infra/deploy/`); wiring into `deploy.yml` is part of INF-03 |
| INF-05 | Scheduled jobs as systemd timers in the repo (DPR PDF render, timeline projector, event consumers) | S | Must | INF-01 | todo | | Check the VPS first to avoid double-running existing cron jobs |
| INF-06 | Nightly database backup copied off the VPS (object storage) | S | Must | INF-04 | todo | | |
| INF-07 | Error alerting (Sentry or similar) for API, worker, dashboard | S | Later | — | todo | | Ilan: do this last |
| INF-08 | Uptime monitor | S | Later | — | todo | | |
| INF-09 | **Production photo storage is the FAKE adapter**: `/health` reports `media_storage: fake`, so every WhatsApp photo is kept in memory and lost on restart. Set `MESIRI_OBJECT_STORAGE__PROVIDER=r2` + endpoint/credentials in `/opt/mesiri/.env` | S | Must | — | in-progress | Claude (session 13 Oct, blockers) | Found 13 Oct via `/health`; startup log says the same. Needs VPS access + R2 credentials (Ilan). DPR photos depend on it. (Correction 13 Oct: the settings check that refuses fake storage in production only runs in `backend/.../bootstrap/lifecycle.py`, not in the live app, so prod being in production mode is still likely.) Decided 13 Oct: local-disk adapter instead of R2 **Code pushed (see Done log): provider `local`, `/media` signed links. To switch on, add to `/opt/mesiri/.env`: `MESIRI_OBJECT_STORAGE__PROVIDER=local`, `MESIRI_OBJECT_STORAGE__PUBLIC_BASE_URL=https://mesiri.mercon.tech`, `MESIRI_OBJECT_STORAGE__SIGNING_SECRET=<openssl rand -hex 32>`, then restart mesiri + mesiri-worker. INF-06 must back up `/var/lib/mesiri/media` too** |
| INF-10 | Migrate Mesiri's WhatsApp Business Account billing to INR (Meta: required by 31 Dec 2026, non-INR accounts stop delivering from 1 Jan 2027) | S | Must | — | todo | | Ops task in Meta Business Manager, not code. Found 13 Oct via Meta's pricing docs |

## BE — Backend

### Foundations

| ID | Item | Size | Priority | Depends on | Status | Owner | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| BE-01 | Single identity model: control-plane tables are the only source; move phone identities, default project/site, roles onto them; retire `context_*` copies and the reconcile watchdog | L | Must | — | in-progress | Claude (session 13 Oct, blockers) | Approved 13 Oct. **Step 0 shipped** (`abaa073`, `b3d30f5`): WhatsApp reads identity from the main tables alongside the copy (`MESIRI_IDENTITY_SOURCE`, default `shadow`); differences show on control panel → Sync Health → "WhatsApp copy vs main tables". Same IDs as the copy (`ctx_user_<uuid>` etc.), so nothing downstream changes. Step 2 (move data) needs nothing: roles, permissions and per-user defaults have no writer in the code. **Next:** after ~3 days with no differences, change `DEFAULT_SOURCE` in `context/shadow.py` to `main` (step 1); a few days later delete the copy, projection hooks, watchdog and tables (step 3) |
| BE-02 | One tenant provisioning path (remove the duplicate in `apps/whatsapp-assistant/src/admin/router.py` vs `backend/.../admin/router.py`) | S | Must | — | todo | | Will be done inside SS-03 (one create-company step) |
| BE-03 | Database-level tenant isolation (Postgres row-level security on `organization_id`) | L | Must | BE-01 | todo | | |
| BE-04 | Phone rules: one person in several companies; never file across companies by guess | M | Must | BE-01 | todo | | Loophole #1 |
| BE-05 | Audit log of superadmin actions (who created/changed/suspended what) | S | Must | — | todo | | |
| BE-06 | Module on/off switch per company (`enabled_modules`), enforced by the API | S | Must | — | done | Claude (session 13 Oct, foundations) | `faffdef`, fix `595a162` (gate turned route 401s into 500s, ~15 min in prod), deploy health-check fix `7fa35c9`. Default flipped to V1 in `1129cfc` |
| BE-07 | Normalise status values (`Active` vs `active`) | S | Must | — | done | Claude (session 13 Oct, strategy) | `3b5c8e1`, deployed. Migration 0463 lowercased org + user statuses. Also fixed: auto-DPR query matched no company (`o.status = 'active'` vs stored "Active") |

### DPR data

| ID | Item | Size | Priority | Depends on | Status | Owner | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| BE-08 | `site_days`: one working-day record per site per date, with statuses (collecting → needs confirmation → ready → approved → sent) | M | Must | — | todo | | Engineer confirms, then it goes out (decided 13 Oct): collecting → needs details → ready → with engineer → confirmed → sent |
| BE-09 | Draft/confirmed status on every fact, plus `extractions` (what the AI read, model, confidence) | M | Must | BE-08 | todo | | Save first, confirm later (decided 13 Oct) |
| BE-10 | Labour counted as a snapshot per contractor+trade+day (latest replaces earlier) | S | Must | BE-09 | todo | | Prevents double counting |
| BE-11 | Duplicate detection: repeated work items (Must), re-used photos across days (Later) | M | Must | BE-09 | todo | | |
| BE-12 | Materials: one-time opening stock, approved stock adjustments, flag (not block) usage beyond known stock | M | Must | BE-09 | todo | | Transfers are BE-32 |
| BE-13 | Late entry for an approved day creates a flagged revision; next day's opening shows the adjustment | M | Must | BE-08 | todo | | Keeps frozen DPRs frozen. "Approved" = confirmed by the engineer |
| BE-14 | Tomorrow's plan, weather (manual), hours lost, site working yes/half/no | S | Must | BE-08 | todo | | |
| BE-15 | Report recipients (users and outside contacts) with opt-in records | S | Must | — | todo | | Meta requires opt-in |
| BE-16 | Project DPR roll-up from approved site DPRs, send deadline, "Not reported" sites | M | Must | BE-08 | todo | | Single-site projects: site DPR is the project DPR. Rolls up engineer-confirmed site DPRs |
| BE-17 | Fix labour events being dropped from `timeline_entries` | S | Must | — | todo | | DAILY_REPORTING_PLAN Phase 6.0 |
| BE-18 | AI summary generated only from confirmed facts | S | Must | BE-09 | todo | | |
| BE-19 | DPR PDF with the customer's letterhead (logo, colour, address, GSTIN, signatory) + "Generated with Mesiri" footer | M | Must | BE-20 | todo | | Client logo on project DPRs: yes (BE-33). Signature/stamp image: not in V1 (decided 13 Oct) |
| BE-20 | Branding storage (`organization_settings` "branding") + logo upload to object storage | S | Must | — | todo | | |
| BE-21 | Anomaly flags (manpower jump vs average, material used with no work logged) | M | Later | BE-09 | todo | | |
| BE-22 | Update `docs/execution/DAILY_REPORTING_PLAN.md` rule P2 to save-first | S | Must | — | todo | | |

### Onboarding & visibility

| ID | Item | Size | Priority | Depends on | Status | Owner | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| BE-23 | Onboarding APIs for the wizard steps (company, owner, projects & sites, team, DPR settings, go-live) | M | Must | BE-02 | todo | | Bulk CSV import is Later |
| BE-24 | Construction defaults seeded per new company (materials, units, trades, issue types) | S | Must | — | todo | | Follow the finance seeder pattern |
| BE-25 | Cost tracking: every AI call (model, tokens, cost) and WhatsApp message (category, cost), per company | M | Must | — | todo | | Extend `provider_executions`. Plan, INR prices and official sources are in the 13 Oct session; released unstarted |
| BE-26 | Messages API for superadmin (per company, user, site; linked to what each message created) | S | Must | BE-09 | todo | | |
| BE-27 | Health numbers API (DPRs sent vs expected, gap-check reply rate) | S | Later | BE-08 | todo | | |
| BE-28 | `PostgresDatabase.transaction()` maps every exception raised while open (incl. a route's own `HTTPException` 401/403/404/422) to 500 "postgres unavailable"; routes using `get_db_conn` likely return 500 for ordinary client errors | S | Must | — | todo | | Found 13 Oct while fixing BE-06 (`595a162`); let `HTTPException` pass through unmapped, with a test |
| BE-30 | **Security follow-up:** check production `users` for platform-admin accounts (role `ADMIN`, no `organization_id`) not created by the team, since `/auth/register` let anyone create one until `c669783` | S | Must | — | todo | | Needs DB access. Remove or deactivate any unknown ones. Query is in `infra/deploy/vps_check.sh`. A token minted that way stays valid for 7 days without any DB row, so also change the JWT secret once (logs everyone out once) |
| BE-31 | **Security:** JWT signing falls back to a hardcoded default (`MESIRI_JWT_SECRET` default in `apps/whatsapp-assistant/src/auth/router.py`). Confirm the secret is set in production; refuse to start in production without it | S | Must | — | in-progress | Claude (session 13 Oct, blockers) | If unset in prod, anyone can forge tokens. Check `/opt/mesiri/.env` first (with INF-01) **Step 1 pushed: one shared secret definition (the two copies are gone) and a startup error in the log when the default is in use. Step 2 (refuse to start) after `vps_check.sh` confirms prod sets it** |
| BE-29 | Check the DeepSeek model name: `deepseek-chat` is no longer on DeepSeek's price page (legacy names are served by V4.1 Flash); pin the current name. Also confirm whether production runs Gemini 2.5 Flash or 2.0 Flash (2.0 is gone from Google's price page) | S | Must | — | todo | | Found 13 Oct while pricing BE-25; BE-25's tracking will record the real model per call |
| BE-32 | Material transfers between sites (out of one site's stock, into another's) | M | Must | BE-12 | todo | | Added 13 Oct: transfers decided in for V1 |
| BE-33 | Client logo per project (stored with BE-20's upload) shown on project DPRs | S | Must | BE-20 | todo | | Added 13 Oct: client logo decided in for V1 |
| BE-34 | WhatsApp ignores "explicit sites only" access: anyone on a project can report on all its sites (a site is authorized whenever its project is). Decide whether V1 enforces it | S | Must | BE-01 | todo | | Found 13 Oct in BE-01; kept as-is so the switch changes nothing |

## WA — WhatsApp assistant

| ID | Item | Size | Priority | Depends on | Status | Owner | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| WA-01 | Capture flows save drafts first (work done, labour, materials, issues, photos) | L | Must | BE-09 | todo | | |
| WA-02 | Forwarded batches: one summary reply; assumed to be today unless stated | M | Must | WA-01 | todo | | |
| WA-03 | Quiet daytime: ask only when it can't wait; defer to the evening | S | Must | WA-01 | todo | | |
| WA-04 | Evening gap-check per site, built from missing sections (template) | M | Must | BE-08 | todo | | Asks the engineer why details are missing and to send them (decided 13 Oct) |
| WA-05 | Confirmation message; "Confirm all" only for high-confidence items; "Fix something" flow | M | Must | WA-04 | todo | | Evening DPR to the engineer to confirm; on confirm it goes to owner/PM/recipients (decided 13 Oct) |
| WA-06 | No-update reminder, owner approval message, DPR delivery message (templates) | M | Must | BE-16 | todo | | No owner approval message: owner/PM receive the engineer-confirmed DPR (decided 13 Oct) |
| WA-07 | Polite reply for switched-off features | S | Must | BE-06 | done | Claude (session 13 Oct, foundations) | `1129cfc` (with WEB-02). Gate in process.py + fast path + multi-request plans; menus list only switched-on modules; REVERSE judged by target |
| WA-08 | Ask "which company?" for people in several companies | S | Must | BE-04 | todo | | |
| WA-09 | Welcome and opt-in messages; handle "YES" | S | Must | BE-15 | todo | | |
| WA-10 | Get all templates approved by Meta | S | Must | WA-04, WA-06, WA-09 | todo | | Ops task, not code |
| WA-11 | Reply in the sender's language (check and fix) | S | Must | — | todo | | |
| WA-12 | **Send approved template messages** (outbound has text/list/button/image/document only). Today a scheduled notification to anyone silent for 24 h is skipped with `outside_whatsapp_session_window_needs_template`. Add template sending + a registry of approved templates | M | Must | — | todo | | Found 13 Oct (SS-01 investigation). Blocks WA-04, WA-06, WA-09, SS-06, SS-08 in practice. Queued for Claude (session 13 Oct, strategy) after BE-07 (Stage A, approved 13 Oct). Ask before picking up |
| WA-13 | Set the company or client logo by sending the image on WhatsApp ("this is the client logo for Project X") | S | Must | BE-33 | todo | | Added 13 Oct: logo must be settable from WhatsApp as well as the web |

## WEB — Web dashboard

| ID | Item | Size | Priority | Depends on | Status | Owner | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| WEB-01 | New look and shell (IBM Plex Sans, colour tokens, 6-item sidebar) per the UI design | M | Must | — | done | Claude (session 13 Oct, foundations) | `c0e1fce`. IBM Plex Sans; tokens + dark mode; sidebar V1 order with More; fixed the never-rendering active highlight. Existing pages keep hardcoded status colours |
| WEB-02 | Hide non-V1 modules using the module switch | S | Must | BE-06 | done | Claude (session 13 Oct, foundations) | `1129cfc` (with WA-07 + default flip). Sidebar filtered, 32 module routes guarded, project page finance button hidden |
| WEB-03 | Today page, grouped by project | M | Must | BE-08 | todo | | |
| WEB-04 | Site DPR page: sections, confirm/edit/remove drafts, sources panel, approve & send, versions | L | Must | BE-09 | todo | | "Approve & send" = the engineer's confirm (decided 13 Oct) |
| WEB-05 | Project DPR page | M | Must | BE-16 | todo | | |
| WEB-06 | Daily Reports history (rework existing page) | M | Must | BE-08 | todo | | |
| WEB-07 | Issues page | S | Must | — | done | Claude (session 13 Oct, foundations) | `0a43723`. "What's stuck" view; grid removed; no Assigned column (API has ids only) |
| WEB-08 | Projects & sites settings, incl. DPR settings, recipients, site label (Tower/Block/Phase) | M | Must | BE-15 | todo | | Also client logo upload per project (BE-33) |
| WEB-09 | Team page (roles, sites) | S | Must | BE-01 | todo | | |
| WEB-10 | Company page incl. branding | S | Must | BE-20 | todo | | |
| WEB-11 | Opening stock and stock adjustment screens | S | Must | BE-12 | todo | | Transfers between sites too (BE-32) |
| WEB-12 | Owner login by WhatsApp/SMS code instead of password | M | Later | BE-01 | todo | | |

## SA — Superadmin (control panel)

| ID | Item | Size | Priority | Depends on | Status | Owner | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| SA-01 | Onboarding wizard (7 steps) with DPR letterhead preview | L | Must | BE-23, BE-20 | todo | | Until it exists, onboard via the API |
| SA-02 | Companies list with status and setup progress | S | Must | BE-23 | todo | | |
| SA-03 | Company page: edit, suspend (export is Later) | M | Must | BE-05 | todo | | |
| SA-04 | Messages viewer per company, linked to what each message created | M | Must | BE-26 | todo | | Extend the existing Logs screen |
| SA-05 | Costs view per message, company and day | M | Must | BE-25 | todo | | |
| SA-06 | Health view (DPR delivery, gap-check replies, WhatsApp number quality) | M | Later | BE-27 | todo | | |
| SA-07 | Module toggles per company | S | Must | BE-06 | done | Claude (session 13 Oct, foundations) | `d338389`. Modules card on the company Settings tab; not yet clicked through in a browser (needs a platform-admin login on the live control panel) |
| SA-08 | Audit log viewer | S | Later | BE-05 | todo | | |

## SS — Self-serve signup & trials

Anyone can message the Mesiri WhatsApp number (or sign up on the web) and get their own
company on a free trial; their team joins by link with the owner's approval. Decided
13 Oct 2026: **anyone can sign up**; **trial length and limits are superadmin settings, not
fixed** (default and per company); **conversion to paid is manual for now**, online payment
later. Every path must use the same company-creation step as the superadmin wizard.

| ID | Item | Size | Priority | Depends on | Status | Owner | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| SS-01 | Investigation + plan for self-serve signup and trials | S | Must | — | in-progress | Claude (session 13 Oct, strategy) | Plan presented 13 Oct, waiting on Ilan's approval before any SS code. **Note 13 Oct: plan approved** (owner session to mark done) |
| SS-02 | Company lifecycle model: status (trial / active / expired / suspended), trial start and end, plan, usage limits; defaults set in superadmin | M | Must | BE-07 | done | Claude (session 13 Oct, strategy) | `1c1d116`, deployed (migration 0464). One rule `lifecycle.is_operational` / `operational_sql` now used by every "is this company active?" check. Platform settings store with defaults trial 7 days, retention 30, self-serve off. API/UI for the settings is SS-10 |
| SS-03 | One "create company" service used by the superadmin wizard, the API and self-serve | M | Must | BE-02 | claimed | Claude (session 13 Oct, strategy) | Stage A (approved 13 Oct). Includes BE-02 (remove the duplicate provisioning path) |
| SS-04 | WhatsApp signup for unknown numbers: replaces the "not registered" dead end with "start a free trial / I'm part of a company" | M | Must | SS-02, SS-03, BE-24 | todo | | Phone already verified by WhatsApp |
| SS-05 | Team joins by link or code (`JOIN ACME-4821`), owner approves or rejects | M | Must | SS-03, BE-04 | todo | | A leaked code can't add strangers |
| SS-06 | Web signup: phone → code on WhatsApp → same questions → same creation step; login link | M | Must | SS-03 | todo | | Needs a Meta authentication template |
| SS-07 | Getting-started checklist in the dashboard (team, DPR time, logo, first update) | S | Must | SS-06 | todo | | |
| SS-08 | Trial lifecycle: reminder messages, expiry behaviour (read-only dashboard, WhatsApp reply), data kept N days (setting) | M | Must | SS-02 | todo | | |
| SS-09 | Guardrails: one active trial per phone, signup rate limits, per-trial AI and WhatsApp caps, flag suspicious signups | M | Must | SS-02, BE-25 | todo | | Protects cost and the shared number's quality rating |
| SS-10 | Superadmin: trial defaults, per-company extend / convert / suspend, days used and activity | M | Must | SS-02 | todo | | |
| SS-11 | Superadmin: trials funnel (started → first update → first DPR → converted) and cost per trial | M | Must | SS-10, BE-25 | todo | | |
| SS-12 | Message templates for self-serve: login code (authentication), join request, trial reminders | S | Must | SS-04, SS-05, SS-08 | todo | | Meta approval needed |

---

## Done log

| Date | ID / work | Commit |
| --- | --- | --- |
| 2026-10-13 | Removed empty stub apps and modules (pre-V1 cleanup) | `9cbf157` |
| 2026-10-13 | INF-04 scripts (backup, smoke test), migration rule in DEPLOYMENT.md | `94f88fd` |
| 2026-10-13 | BE-06 module switch, enforced by the API | `faffdef` |
| 2026-10-13 | Deploy health check waits up to 60 s (healthy deploy had been rolled back) | `7fa35c9` |
| 2026-10-13 | BE-06 fix: gate no longer turns route 401s into 500s | `595a162` |
| 2026-10-13 | SA-07 module switches in the control panel | `d338389` |
| 2026-10-13 | Labour: withdraw an attendance report filed on the wrong site (migration 0462, applied in prod); fixes superseded reports double-counting in the DPR and WhatsApp labour query | `6a4b20d` |
| 2026-10-13 | Dashboard: trips / logistics page removed | `15b85fc` |
| 2026-10-13 | WEB-01 new look and V1 shell | `c0e1fce` |
| 2026-10-13 | WEB-02 + WA-07: switched-off modules hidden on dashboard and WhatsApp; default modules = V1 | `1129cfc` |
| 2026-10-13 | WEB-07 Issues page reworked as "What's stuck" | `0a43723` |
| 2026-10-13 | SS-02 company lifecycle (trials) + platform settings (migration 0464) | `1c1d116` |
| 2026-10-13 | BE-07 statuses lowercase (migration 0463); automatic DPR now finds companies | `3b5c8e1` |
| 2026-10-13 | Security: removed unauthenticated `/auth/register` (anyone could mint a platform-admin token) | `c669783` |
| 2026-10-13 | INF-09 local-disk media storage (off until .env switched); BE-31 shared JWT secret + startup warning | `ada65a3` |

| 2026-10-13 | BE-01 step 0: identity from main tables in shadow (migration 0465), Sync Health comparison panel | `abaa073`, `b3d30f5` |