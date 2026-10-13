# Daily Reporting Module — Master Implementation Plan

**Status:** In progress — Phase 0 complete; product specification adopted
(§1A); WhatsApp workflow decomposition reconciled against existing
architecture (§1B); schema written (`0410`–`0440`) and chain-verified, not
yet applied to a live database. **Next: apply the migrations, then Phase 1's
domain model — see §11.**
**Owner:** Ilan Usman
**Started:** 2026-07-27
**Last updated:** 2026-07-27
**Linear:** _(epic to be created — see §11)_

> **Resuming in a new session?** Read §11 first — it says exactly where work
> stopped and what to do next. Then read §2 (what already exists), §3 (the
> binding principles) and §3A (the finish line).

> **Purpose of this document.** It is the durable memory for this module. If a
> future session — human or AI — loses all conversational context, this file
> alone should explain what exists, what is being built, what remains, why each
> decision was made, and what to do next. Keep it updated as work proceeds;
> a stale plan is worse than none.

---

## 1. What the Daily Reporting module is

Record **what work was done, where, how much of it, and what got in the way** —
and turn a day's worth of that into an approved Daily Progress Report.

This is the module the product is named after. `Mesiri Daily` is this.

It is deliberately **two different things** that must never be conflated in code:

| | Facts | The document |
|---|---|---|
| What | Atomic, immutable, evidence-linked reports filed through the day | A composed, reviewed, approved, frozen DPR |
| Shape | Same as an expense or an attendance record | A composition over *all* modules' facts for one date |
| Surface | WhatsApp-first | Dashboard-first |
| Owned by | §6.1–§6.5 (`progress` domain) | §6.6–§6.7 (`dpr` domain) |

Finance and Labour had only the first. The second is what makes this module
hard, and why it gets its own domain package rather than being bolted onto the
capture path.

**Explicitly out of scope for V1 (future ERP extension points).** The data
model must be designed so each can be added later without migration pain:

BOQ management & import, drawing take-off, cost codes, procurement, purchase
orders, RFQs, scheduling (Gantt) / critical path, resource planning &
levelling, budget & cost control beyond `0340`'s budgets, billing / IPC /
subcontractor RA bills, quality inspections & ITP, snag lists, safety incident
case management, forecasting, earned-value & planned-vs-actual analytics,
weather API integration.

> **Correction applied 2026-07-27.** The product spec's original "future"
> list also named Labour Attendance, Material Inventory, Vendors, Equipment
> Management and Approvals. **Those are already shipped** (workforce +
> attendance; materials catalogue/units/movement ledger `0290`/`0300`/`0310`;
> vendors `0370`; `equipment_events` `0110`; the LangGraph confirmation
> spine). Consequently **Labour / Material / Expense summaries in the DPR, and
> Material / Expense events in the Timeline, are V1 — not future.** They are
> read-only joins to shipped tables (P3), gated only by Phase 6.0. A DPR
> without headcount and material consumption is not a DPR a site manager will
> accept, and the data already exists.

---

## 1A. Product specification — the feature surface

**This section is the authority on _what_ the module contains.** §3 (principles),
§5 (ADRs) and §6 (data model) are the authority on _how_ it is built. Where the
two appear to conflict, the conflict is a bug in this document — resolve it
here rather than in code.

Nine areas, in V1 implementation order:

| # | Area | Features |
|---|---|---|
| 1 | **Activities** | create · edit · archive · status · type · category · location · assigned engineer · contractor · start/end time · work description · quantity · unit · tags · *linked work package (Ph2)* · *linked BOQ item (future)* · *linked cost code (future)* |
| 2 | **Progress Updates** | add update · quantity completed · progress notes · time of update · updated by · completion % · pause · resume · finish · progress history |
| 3 | **Evidence** | photos · videos · voice notes · documents · GPS · timestamp · AI caption · before/after images · media gallery · linked to activity |
| 4 | **Site Issues** | report · category · priority · status · assigned person · due date · resolution notes · attach evidence · issue timeline |
| 5 | **Timeline** | activity · progress · issue · evidence · **material** · **expense** · **labour** events · filters · search · date navigation |
| 6 | **DPR** | AI summary · activities · progress · **labour** · **material** · **expense** · issues summaries · weather · photos · sign-off · export PDF · version history |
| 7 | **Gallery** | photos · videos · voice notes · documents · filter by project/site/activity/date · full-screen preview |
| 8 | **Analytics** | daily/weekly/monthly progress · activity, productivity, delay, issue trends · completion statistics · engineer & contractor activity volume |
| 9 | **AI Assistant** | ask about activities · project progress · find issues · generate DPR · explain delays · search photos · summarise today · continue conversations · smart confirmations |

Bolded items were marked "future" in the original spec and promoted to V1 by
the correction above.

### 1A.1 Three clarifications binding on the spec

1. **The DPR is auto-*drafted*, never auto-published.** The spec's phrase
   "automatically generated site report" means the *draft* is assembled
   automatically at cutoff. Nothing leaves the system without human sign-off
   (PRD §C; P7; ADR-D6).
2. **Completion % is `MANUAL` mode only in V1.** Work Packages are Phase 2, so
   there is no planned quantity to divide by. It is an engineer's stated
   estimate and **must render labelled as an estimate** (P6). Shipping it as
   an apparently-computed figure means owners trust a number whose meaning
   silently changes when denominators arrive.
3. **AI Caption is an insight, not a fact.** Stored in its own column,
   rendered visibly as AI-generated, never merged into the reporter's
   narrative (PRD §6 principle 3).

### 1A.2 Surface split

| WhatsApp (capture) | Dashboard (visibility & management) |
|---|---|
| Site update: text, photo, video, voice, document | Operations Overview |
| AI extraction: activity, quantity, date/time, location, engineer, contractor, issue | Activities — list, details, create |
| Confirmation: review, edit, save | Timeline |
| Progress update: continue activity, update quantity, mark complete, pause, resume | Daily Reports — drafts, published, templates |
| Issue reporting: report, attach evidence, update, resolve | Issues |
| Ask Mesiri: NL queries, report generation, activity lookup, search history | Gallery · Work Packages (Ph2) · Analytics |

Dashboard routes all sit under the **existing** Operations sidebar category
(§2.5). New routes needed: `/operations/activities`, `/operations/daily-reports`,
`/operations/issues`, `/operations/work-packages`.

---

## 2. Reconnaissance findings (2026-07-27)

Read before assuming anything about the current state.

### 2.1 The routing rails already exist — and are unused

Site progress reporting was anticipated when the platform was laid out. These
are **already present and require no invention**:

| Thing | Where | Value |
|---|---|---|
| `SemanticType.GENERAL_SITE_UPDATE` | `shared/contracts/.../assistant/enums.py` | `"general_site_update"` |
| `CanonicalEventType.GENERAL_SITE_UPDATE_REQUESTED` | `shared/contracts/.../assistant/canonical_event.py` | `"GeneralSiteUpdateRequested"` |
| `WorkflowKey.SITE_UPDATE` | `shared/contracts/.../assistant/planner_decision.py` | `"site.update"` |
| Semantic → canonical mapping | `apps/whatsapp-assistant/src/canonicalization/mapping.py:18` | wired |
| Canonical → workflow routing | `apps/whatsapp-assistant/src/planner/routing.py:20` | wired |
| AI extraction slot (Gemini) | `platform/ai/.../gemini/adapter.py:133` | `summary, activity, location, weather, project_name` |
| AI extraction slot (DeepSeek) | `platform/ai/.../deepseek/adapter.py:91` | same |
| Image-purpose list row | `apps/whatsapp-assistant/src/channel/replies.py:132` | `img_site_update` → "Site Update / Progress photo" |
| Empty workflow package | `apps/whatsapp-assistant/src/workflows/field_update/` | `__init__.py` only, **0 bytes** |
| Empty domain packages | `backend/src/mesiri/domains/{reports,sites,approvals}/` | `__init__.py` only, 0 bytes |
| Empty application packages | `backend/src/mesiri/application/{reports,timeline,sites,approvals}/` | `__init__.py` only, 0 bytes |

**The single gap is the compiled graph.** `channel/replies.py:155` already
carries a comment acknowledging that `WorkflowKey.SITE_UPDATE has no compiled
graph` and special-cases around it. Phase 3 closes that.

Note the naming mismatch to resolve in Phase 2: the *contract* calls it
`SITE_UPDATE`, the *workflow package* is called `field_update`, and the
dashboard page is called `FieldReportsPage`. See ADR-D7.

### 2.2 Reporting configuration exists but nothing reads it

Migration `0260_projects_reporting_and_membership.py` added, and **no code
consumes any of them**:

| Column / table | Purpose |
|---|---|
| `projects.reporting_timezone` | which day boundary applies |
| `projects.reporting_cutoff_time` | default `"18:00"` — when a day's report is due |
| `projects.auto_generate_dpr` | default `false` — assemble a draft automatically |
| `projects.required_report_types` (JSONB) | which report types a site owes daily |
| `project_members` (`role`, default `SITE_ENGINEER`) | who owes the report |

Phase 7 (compliance & nudges) is where these finally get a reader. Do **not**
add new configuration columns before checking these.

### 2.3 `timeline_entries` is the substrate, not a new table

`0150_core_add_timeline_entries.py` created the read-model projection of
confirmed Domain Events, with the docstring: *"Downstream systems react to
Domain Events only — never query business tables directly."* Columns include
`event_type`, `summary`, `payload` (JSONB), `occurred_at`, `correlation_id`,
`source_aggregate_type`, `source_aggregate_id`.

**Verified 2026-07-27 — the projection is largely NOT happening. This is a
prerequisite slice, not an assumption.** Findings:

| Module | Writes `outbox_events`? | Reaches `timeline_entries`? |
|---|---|---|
| Materials | yes — `material_execution.py:203` | **yes** — `material_receipt`, `material_usage` are the only two entries in `AGGREGATE_TABLES` |
| Labour | yes — `labour_execution.py:179`, `aggregate_type="labour_attendance_report"` | **no** — no `AGGREGATE_TABLES` entry, so `source_table` is `None`, the row hits the `source is None` branch (`timeline_projector.py:154`) and is **marked published and silently discarded** |
| Finance (expenses, transfers, petty cash, reversals) | **no** — no `INSERT INTO outbox_events` anywhere in the finance/expense repositories | no |
| Equipment | no | no |

Two further facts:

- `events/consumers/timeline_projector.py` is a **manually/cron-invoked
  idempotent batch** (`make project-timeline`), by deliberate design — not a
  running worker. `backend/apps/worker/consumers/` is empty. Whatever invokes
  it in production must be confirmed before the DPR depends on its freshness.
- The projector is well-built for extension: adding a domain is one entry in
  `AGGREGATE_TABLES` (the table must expose `organization_id`, `project_id`,
  `site_id`, `occurred_date`, `occurred_time`) plus one in
  `EVENT_SUMMARY_BUILDERS`. Both are explicitly labelled "Extension point".

**Consequence for this plan:** Phase 6 gains a prerequisite — **Phase 6.0**,
below. The labour silent-discard is a live bug that exists independently of
this module and should be fixed regardless.

### 2.4 Canonical reference modules

Copy these patterns; do not invent new ones.

| For | Copy from |
|---|---|
| Workflow graph + nodes + state + transitions | `workflows/expense_capture/` (richest), `workflows/labour_update/` (most recent) |
| Resolution gate against reference data with a create-gate | `runtime/material_catalog_query.py` + `inbound_journey.py` |
| Register-vs-record separation | Labour's `workforce` (register) vs `attendance` (immutable record) — plan §3 P1 |
| Immutable ledger + reversal | `materials` movements (`0300`/`0310`) |
| Attachment / evidence pattern | `expense_attachments` → `media_object_key` + `attachment_type` |
| Rendered document → PNG | `channel/receipt/` (Jinja2 → Playwright → PNG, in-process) |
| Dashboard module shape | `apps/dashboard/src/pages/Labour*.tsx` + `app-sidebar.tsx` Operations group |
| Statement generation + CSV export | `FinanceReportsPage.tsx` + `domains/finance/router.py` |

### 2.5 Dashboard placement already exists

`app-sidebar.tsx:74` defines an **Operations** category with routes already
present: `Overview`, `Timeline`, `Field Reports`, `Gallery`, `Analytics`.
`FieldReportsPage.tsx` is a 128-line static placeholder with nine hardcoded
category chips and no data binding.

**No new sidebar category is needed.** Daily Reporting fills Operations.

---

## 3. Architectural principles (non-negotiable)

These are binding constraints on the implementation, not preferences.

### P1 — Three layers, never collapsed

```
Work Package  (planning)   lives months     — what a manager watches
     │ 1..n
Activity      (execution)  lives a day      — what an engineer reports
     │ 1..n
Progress Update (timeline) lives a moment   — append-only, never edited
```

A Work Package and an Activity are **not** the same entity at different
granularities. `Block A Foundation` and `plastering, Floor 2, 180 sqm, today`
have different lifetimes, different owners, different mutability. Collapsing
them into one table produces special-cases within a month.

**There must never be code that edits a Progress Update.** Corrections append
a new update that supersedes the prior one, exactly as Labour's attendance and
Materials' movements are immutable.

### P2 — Universal operational pattern

Daily Reporting uses the same end-to-end shape as every other operational
module:

```
Module → Action → Project → Site → Capture → AI Understanding
       → Preview → Confirmation → Save
```

of which the last four are the non-negotiable core:

```
AI Extraction → Structured Preview → User Confirmation → Persistence
```

Nothing is persisted before an explicit confirmation. A supervisor who has
learned Material or Labour has already learned this module.

### P3 — Daily Reporting is never a second writer

This is the most important rule in this document.

Activities **reference** workforce, material, equipment and expense records.
They never create, mutate, or post into those ledgers.

```
Activity ──references──> attendance_records
         ──references──> material_movements
         ──references──> equipment_events
         ──references──> expenses
```

Materials already has a confirmation gate, a reversal path, unit-of-measure
resolution, a catalogue create-gate and a stock gate — all tested
(`test_material_stock_gate.py`, `test_material_create_gate.py`,
`test_material_unit_gates.py`). A second write path bypassing those produces
two writers into an immutable ledger with different validation.

If a user reports material consumption *inside* a progress message, the
correct behaviour is to invoke **the existing material command handler with
its existing gates** and then store the resulting movement id as a reference —
never to insert a movement row from progress code.

Rationale: an earlier version of this project was discarded because modules
grew write paths into each other's data. See `AGENTS.md`.

### P4 — Capture must work with zero configuration

An engineer must be able to file a useful progress report on day one, with no
Work Package register, no Location tree, and no planned quantities configured.

Therefore: `work_package_id`, `location_id`, `activity_type_id` are all
**nullable and backfillable**. The dashboard can attach an orphan activity to a
package later; the activity's own quantities are unaffected.

If Work Packages were required first, nobody could report anything until
someone sat down and built a WBS — and that is how this module never ships.

### P5 — Planned quantity is planning-layer data

Planned quantity is entered by a PM or planning engineer, **in the dashboard,
on the Work Package**, as a set of `(work_type, unit, planned_quantity)` lines.

- **Never** inferred by AI. A fabricated denominator produces a fabricated
  completion %, and that % is the number an owner makes decisions on.
- **Never** captured through the WhatsApp flow. The engineer is mid-shift
  reporting what he *did*; planning data entered under time pressure is
  garbage and it corrupts every historical %.
- **Never** required. Absence means the package reports absolute quantities
  with no %, which is a valid and common state.

### P6 — Completion % must always declare its provenance

```
work_packages.completion_mode
├── NONE       default. No plan entered. Cumulative done only, no %.
├── QUANTITY   planned items exist. % = Σ done / Σ planned per line, weighted.
├── MILESTONE  no quantities; N activities marked required. % = done / N.
└── MANUAL     an engineer's stated estimate. Stored as a claim.
```

A package starts at `NONE` and is upgraded whenever someone bothers.
Historical activities roll up retroactively, because activities carry their own
quantities regardless of whether a plan existed when they were filed.

**A rolled-up 62% and an eyeballed 60% must never render identically.** Every
surface that displays a % also displays its mode.

### P7 — Freeze on approval

An approved DPR is a frozen snapshot, not a live query.

If a material movement is reversed tomorrow, yesterday's published DPR does not
change. Corrections produce a **new revision** with a visible diff against the
prior one. The same applies to planned quantities: a revised take-off does not
silently rewrite the completion % printed in an already-approved report.

### P8 — Project DPR is a composition of Site DPRs

The project-level DPR is built **from approved site DPRs**, never independently
re-assembled from raw facts. Two assemblers drift, and a project DPR that
contradicts its own site DPRs destroys trust in the whole feature.

It pins `site_daily_report_version_id`, not the live row (P7).

A site that has not approved by cutoff is included and marked
**`NOT_REPORTED`**. The project DPR publishes anyway. A missing site report is
the single most important line on the page, and blocking would let one slow
site hold an entire project's reporting hostage.

**Single-site projects auto-compose and auto-approve the project DPR from the
site DPR.** One approval, not two. Making the same person approve two
near-identical documents will kill adoption.

### P9 — Locations are shared infrastructure, not Daily Reporting's

The location tree is referenced by attendance, material outflows, equipment
events and activities. It belongs to `core`/`projects`, not to this module.
If it lives here, Labour builds a second one within a month.

It is a **self-referential tree with a level label**, never fixed
Block/Floor/Room columns — road and linear projects have chainage
(`km 12+400`), not floors; tunnels have rings; plots have boundaries.

```
location_nodes
├── id, project_id, site_id
├── parent_id  (self-FK, nullable)
├── level_label  "Block" | "Floor" | "Zone" | "Chainage" | free text
├── name         "A" | "2" | "km 12+400"
└── path         materialized, for "everything under Block A" queries
```

### P10 — Optimize for speed of recording

Ask a follow-up question **only** when the record is unusable without it.
Missing quantity on a "started plastering" update is fine — that update is
still worth having. Missing project when the user has access to six projects
is not.

Accept the detail the user can give today. A progress update with only a
narrative and a photo is a valid, useful record.

### P11 — One context resolution, reused by every graph

Every Daily Reporting graph (activity creation, progress update, correction,
issue, evidence, DPR Q&A) begins by consuming the **existing M4 Context
Resolver** output — organization, project, site, identity, confidence,
ambiguity — never a module-local re-implementation of any part of it.

`ContextConfidence` (`VERY_HIGH → UNRESOLVED`, already defined in
`context_enums.py`) is the *only* confidence vocabulary this module uses.
"Ask one clarifying question" logic (§1B.9) thresholds against this existing
enum; it does not invent a parallel scoring scheme.

Rationale: a second context-resolution layer, built module-local because it
felt easier than reading the existing one, is the exact failure mode
`AGENTS.md`'s Module Placement Log exists to prevent — and centralizing it is
what makes "continue", "same place", "finished it" tractable in the first
place, because every graph agrees on what "the current activity" means.

### P12 — Cross-module calls go through the existing dispatcher seam, never around it

When a progress message names another module's fact — *"used 40 cement bags"*,
*"excavator broke down"* — the Activity graph **calls that module's own
command handler** (the same `ExecutionDispatcher` shape already proven by
`MaterialExecutionDispatcher`) and stores the returned record id as a
reference (P3, ADR-D2).

This governs **undo** too: undoing a cross-module-triggered record calls that
module's own reversal/correction command. Daily Reporting never deletes or
mutates another module's row directly, even to undo its own trigger.

```
Activity Graph                    Material Module
     │  "40 bags cement used"          │
     ├──────────────────────────────►  ExecuteConfirmedMaterialAction
     │  ◄──────────────────────────    movement_id
     │
     └── activity_links(MATERIAL_MOVEMENT, movement_id)
```

No new dispatcher abstraction is introduced by this module — Finance, Labour
and Equipment already have (or will have, per their own plans) the identical
shape. This module is a *caller*, not a second implementation.

---

## 1B. WhatsApp workflow decomposition

**Added 2026-07-27**, reconciling an external proposal against this codebase.
Two claims in that proposal turned out to already be true here — not
proposals but existing architecture — and are recorded as such rather than
rebuilt:

- **"Small independent graphs, one per business capability"** is not a new
  idea for this module; it is already how every workflow in this repository
  works (`workflows/registry.py` compiles one graph per `WorkflowKey`,
  cached once). Daily Reporting follows the same convention — see §1B.1.
- **"A Context Resolution graph that runs before every business graph"**
  already exists as the M4 Context Resolver (P11) — it is reused, not built.

What follows is genuinely new: it decomposes the single `site_update`
workflow key from §2.1 into several graphs (matching the existing one-graph-
per-capability convention) and lists the field-reality workflows an earlier
pass of this plan didn't cover.

### 1B.1 Graphs

One `WorkflowKey` was reserved for this module (`SITE_UPDATE`); it is not
granular enough for what a real graph needs to model without becoming one
giant conditional. Each of these compiles independently, registers in
`workflows/registry.py` next to `material`, `labour_update`, etc., and shares
nodes via `workflows/shared/` (a new package — see §1B.2):

| Graph | Handles | New / existing rail |
|---|---|---|
| `activity_creation` | New Activity — the default path when no open activity matches | fills the `SITE_UPDATE` gap (§2.1) |
| `activity_continuation` | *"completed another 40 sqm"*, *"finished the remaining work"* — appends a Progress Update to an existing Activity | new |
| `activity_correction` | *"quantity is 180 not 150"*, *"wrong location"* — mutates the Activity header, **not** a Progress Update (reconciled against P1 below) | new |
| `activity_status` | started / paused / resumed / completed | folds into `activity_continuation` — same append shape, `update_kind` discriminates (§6.4) |
| `evidence` | photo / video / voice / document, single or batched (§1B.6) | new |
| `issue` | report / classify / duplicate-check / assign | new |
| `dpr_generation` | assemble draft → AI summary → hand to dashboard review | Phase 6, already planned |
| `qa` (`progress_query`) | Ask-Mesiri over activities/timeline/issues/DPRs | Phase 11, already planned as the `ask_mesiri/` stub |

**New `WorkflowKey` values needed** (Phase 2 contract work):
`ACTIVITY_CONTINUATION`, `ACTIVITY_CORRECTION`, `SITE_ISSUE` (already listed
in the original checklist), `PROGRESS_QUERY`. `SITE_UPDATE` stays as the
entry key for `activity_creation` to keep the AI extraction slot and routing
map entry unchanged (ADR-D7 already resolved this name).

### 1B.2 Shared nodes — `workflows/shared/`

Extracted once new graphs would otherwise duplicate them, following the same
"extract when duplication would occur, not before" rule from `AGENTS.md`'s
Refactor principle:

```
workflows/shared/
├── resolve_context.py      -- P11: wraps the M4 resolver call
├── resolve_activity.py     -- P10's "continue vs new" candidate ranking
├── resolve_location.py     -- gate + create-gate, materials_catalog_query pattern
├── confirmation.py         -- P2's non-negotiable core, one implementation
├── attach_evidence.py      -- shared by activity_creation and evidence graphs
├── cross_module_trigger.py -- P12's dispatcher-call wrapper
└── audit_log.py            -- correction/undo trail (shared shape, §1B.5/1B.7)
```

Do **not** create this package speculatively in Phase 1 — build the first two
graphs, extract into `shared/` at the point a third graph would duplicate
logic, exactly as `AGENTS.md` prescribes.

### 1B.3 Multi-Activity — one message, several activities

*"Completed plastering in Block A, started painting in Block B, repaired two
damaged columns."*

The `activity_creation` graph splits the message into candidate segments
**before** entity extraction, runs extraction per segment, and presents **one
confirmation covering all segments** — not N separate confirmation
round-trips, which would be a worse experience than not splitting at all.

```
Message → Split → [Segment₁, Segment₂, Segment₃] → parallel extraction
        → single combined preview → one confirmation → save all
```

Partial confirmation (user corrects segment 2, accepts 1 and 3) is in scope
for V1 — the confirmation UI must support per-segment edit, not just
accept/reject the whole batch.

### 1B.4 Reply-based continuation — fills an existing stub

*"Started slab concrete."* → (WhatsApp reply, hours later) → *"Completed."*

`ReplyContextProvider`'s `NullReplyContextProvider` (§2.1 table) already
documents the intended shape: *"mapped when a message is answered"*. This
module is the first consumer that needs the real implementation. Build the
authoritative store here (message_id → activity_id, not just → project/site
as the port currently returns) rather than inventing a parallel mapping.
This is **more reliable than NLP-guessed continuation** and should be tried
first in `resolve_activity.py` before falling back to ranking.

### 1B.5 Correction — reconciled against P1's append-only rule

P1 says Progress Updates are never edited. A correction like *"quantity is
180 not 150"* is **not** a Progress Update correction — it targets the
**Activity's** header fields (`work_type`, initial quantity estimate at
creation, `location_id`, contractor), which are mutable planning-adjacent
data, not immutable timeline fact.

```
Progress Update  → immutable, corrections APPEND a new update (P1, unchanged)
Activity header  → mutable, corrections UPDATE the row + audit_log entry
```

`activity_correction` writes an audit row (who, when, field, old → new) on
every mutation — same shape as ADR-D5's planned-quantity revision trail.
**A correction never targets a value already rolled into an approved DPR
version** (P7) — corrections after freeze become a new DPR revision, not a
silent edit of history.

### 1B.6 Batch media

Engineers commonly send 10–15 photos in one burst. WhatsApp delivers these as
separate webhook events; the `evidence` graph buffers arrivals within a short
window (mirroring the dedup store's existing debounce pattern in
`ingress/deduplication.py`), clusters by proximity in arrival time, and
matches the cluster to the most recent open Activity rather than resolving
one activity match per photo — 15 separate resolution round-trips would be
unusable.

### 1B.7 Undo

Scope: **undo an Activity or Progress Update the reporter just created**, not
an open-ended rollback engine. Covers the realistic case (*"ignore that",
"wrong", "delete that"*) within the same conversation/session window.

- Undoing an Activity/Progress Update: soft-delete with an audit trail
  (never a hard delete — matches the immutability principle everywhere else).
- Undoing a cross-module-triggered record (P12): calls that module's own
  reversal command. Daily Reporting has no reversal logic of its own for
  another module's ledger.
- **Undo is unavailable once a DPR version has frozen the record** (P7) — at
  that point the only path is a correction that produces a new DPR revision.

### 1B.8 Duplicate detection — semantic, not message-level

Distinct from the **existing** `ingress/deduplication.py`, which catches
WhatsApp redelivering the same webhook (message-id keyed). This is: *did the
engineer describe the same real-world activity twice* (network hiccup →
resend in different words). Similarity check against same
project/site/activity_date/work_type within a short time window; on a
likely match, ask rather than silently create a duplicate or silently
discard — silent discard risks losing genuinely distinct work reported close
together.

### 1B.9 Low-confidence gate

Every extraction feeds `ContextConfidence` (P11, reused — not a new scale).
Below a threshold: ask exactly one targeted question, never a generic "please
clarify." Above it: save without interrupting (P10). The threshold and its
tuning is an operational decision, not an architectural one — do not hardcode
it in graph logic; make it configuration read once per graph.

---

## 3A. Definition of Done — when is Daily Reporting V1 finished?

V1 is complete when **all** of the following are true:

1. A site engineer sends *"plastering done on 2nd floor, about 180 sqm, 16 workers"*
   by text or voice, in any supported language, and gets a structured
   confirmation preview and a receipt card — with **no** work packages,
   locations or planned quantities configured anywhere.
2. A photo sent with `img_site_update` purpose attaches as evidence to that
   activity and appears in the dashboard alongside it.
3. Progress updates append to an activity through the day without editing it.
4. An issue/blocker (`rain`, `material shortage`, `drawing pending`) is
   recorded with a duration and shows as a delay attribution.
5. At the project's `reporting_cutoff_time`, a **site DPR draft** is assembled
   from that day's activities, updates, issues, attendance, material movements
   and expenses.
6. The site engineer reviews and approves it in the dashboard; it freezes, gets
   a version, and renders to a shareable document.
7. A multi-site project composes an approved **project DPR** from its site
   DPRs, marking non-reporting sites `NOT_REPORTED`; a single-site project does
   this automatically with one approval.
8. That DPR includes **labour headcount, material consumption and expenses**
   for the day, read from the already-shipped modules via `timeline_entries`
   (Phase 6.0) — not stubbed, not "future".
9. Every completion % on every surface renders with its `completion_mode`
   visible; in V1 that is always `MANUAL` / "estimate" (§1A.1).
10. A message describing three separate activities produces one combined
    confirmation covering all three, with per-segment edit (§1B.3).
11. Replying to a specific earlier WhatsApp message continues that message's
    activity, without re-asking which one (§1B.4).
12. A same-session "wrong, delete that" undoes the just-created record; an
    already-frozen record cannot be undone, only revised (§1B.7).
13. Full test suite green: `pytest tests/ --ignore=tests/integration -q` in both
    `apps/whatsapp-assistant` and `backend`, plus `shared/contracts` and
    `platform/ai`. `ruff check` clean on every `src/` touched.

Not required for V1 (Phases 9–11): Work Packages, planned quantities,
`QUANTITY`/`MILESTONE` completion modes, analytics, productivity trends,
Ask-Mesiri progress queries, compliance escalation ladders, batch media
clustering beyond the naive case, forwarded-message confidence adjustment,
concurrent-edit conflict resolution beyond last-write-with-audit.

---

## 4. Implementation order

Deliberately capture-first. Planning layer lands *after* reporting works.

The spec's nine product areas (§1A) map onto engineering phases as follows.
The spec order is preserved; phases 0–2 and 6.0 are the engineering
prerequisites it does not name.

| Phase | Name | §1A area | Delivers | Depends on |
|---|---|---|---|---|
| 0 | Reconnaissance & design | — | this document | — |
| 1 | Business & domain model | — | entities, value objects, completion-mode logic | 0 |
| 2 | Contracts | — | naming resolution (ADR-D7), new canonical types, AI extraction slots | 1 |
| 3 | Workflow + persistence + app layer | **1, 2, 4** | `site_update` graph (the 0-byte gap), migrations `0410`–`0440`, repositories, REST | 2 |
| 4 | Evidence | **3** | attachments, gallery storage, AI caption (labelled), before/after | 3 |
| 5 | Timeline | **5** | activity/progress/issue/evidence feed | 3, 4 |
| 6.0 | **Outbox projection prerequisite** | — | labour + finance + progress events actually reach `timeline_entries` | 3 |
| 6 | DPR assembly, approval, freeze | **6** | draft → review → approve → freeze → render; site → project composition | 5, 6.0 |
| 7 | Dashboard — Operations | **1–7** | Activities, Timeline, Daily Reports, Issues, Gallery | 3, 6 |
| 8 | Compliance & nudges | — | finally reads `0260`'s `reporting_*` columns | 6, 7 |
| 9 | Work Packages | **(Ph2)** | WBS, planned items, `QUANTITY`/`MILESTONE` completion modes | 7 |
| 10 | Analytics | **8** | progress trends, delay/issue trends, activity volume | 9 |
| 11 | AI Assistant refinements | **9** | `progress_query`, Ask-Mesiri, DPR generation by request | 10 |

Phase 6.0 can run in parallel with 4 and 5 — it touches no Daily Reporting
code, only the projector and the finance/labour repositories. Phase 7 can
start against Phase 3's API before Phase 6 completes.

**Work Packages moved from Phase 1-adjacent to Phase 9** per the product spec
(`Linked Work Package (future)`, `Work Packages (Phase 2)`). This reinforces
P4 — capture must work with zero configuration — and makes P6's `MANUAL`-only
constraint for V1 explicit (§1A.1).

---

## 5. Architecture decisions (ADRs)

### ADR-D1 — Three-level hierarchy, not two

**Status:** Accepted
**Context:** An earlier draft proposed a single flat "Activity Register" serving
both planning and daily execution.
**Decision:** Work Package (planning) → Activity (execution) → Progress Update
(timeline), as three separate tables.
**Consequences:** More tables, but each has one owner and one mutability rule.
A Work Package is mutable planning data; an Activity is a day's work item; a
Progress Update is immutable.
**Rejected alternatives:**
- *Flat activity register* — forces one row to be both a four-month planning
  node and a one-day work item, with a `type` discriminator and diverging
  validation. This is the special-case explosion the module split exists to
  prevent.

### ADR-D2 — Daily Reporting never writes to other modules' ledgers

**Status:** Accepted
**Context:** A proposed design had activities automatically posting material
consumption into inventory.
**Decision:** P3. Activities hold nullable FK references to
`material_movements`, `attendance_records`, `equipment_events`, `expenses`.
Creating any of those from a progress message goes through that module's
existing command handler and gates.
**Consequences:** A progress message containing material consumption produces
*two* confirmed records via two handlers, linked by `correlation_id` — not one
row with a side effect.
**Rejected alternatives:**
- *Activity writes inventory directly* — bypasses the stock gate, unit
  resolution, catalogue create-gate and reversal path. Two writers into an
  immutable ledger with different validation.

### ADR-D3 — Locations live in `core`, not in Daily Reporting

**Status:** Accepted
**Decision:** P9. A shared, self-referential, level-labelled
`location_nodes` tree owned by `projects`/`core`.
**Consequences:** Daily Reporting depends on `core` for locations. Labour and
Materials can adopt location references later without a migration from a
Daily-owned table.
**Rejected alternatives:**
- *Fixed Block/Floor/Room/Zone columns* — cannot express road chainage, tunnel
  rings, or plot boundaries. The proposal that suggested it also listed
  "Road Works" as an example work package, which the same schema cannot model.
- *Daily-owned locations* — Labour will build a second tree within a month.

### ADR-D4 — Planned quantities are a child table, not a column

**Status:** Accepted
**Context:** `Ground Floor` has no single planned quantity — it has plastering
in sqm, concrete in m³, blockwork in m², doors in nos.
**Decision:** `work_package_planned_items (work_type, unit_id, planned_quantity)`,
with `unit_id` FK to the existing `units_of_measure` (`0290`).
**Consequences:** Effectively a lightweight BOQ, which is also the natural
integration seam for Mesiri ERP later. Activity quantities roll up by matching
`work_type + unit`. Anything reported with no matching planned line still
displays as work done but contributes to no %.
**Rejected alternatives:**
- *Single `planned_quantity` column* — wrong on day one for any package
  spanning more than one trade.

### ADR-D5 — Planned quantities are revisable with history

**Status:** Accepted
**Context:** Variation orders and revised drawings change denominators
mid-project, which would silently rewrite every historical completion %.
**Decision:** Revisions are recorded (who, when, why, old → new). A frozen DPR
retains the denominator in effect on its date (P7).
**Consequences:** `work_package_planned_items` needs revision rows or an
`effective_from` / audit table. Decide the exact shape in Phase 1.

### ADR-D6 — Site DPR and Project DPR are one table with a level discriminator

**Status:** Accepted
**Decision:** `daily_reports` with `level ∈ {SITE, PROJECT}`, plus
`daily_report_versions` for the frozen snapshots, plus
`daily_report_sources` linking a PROJECT version to the SITE versions it
composed (P8).
**Consequences:** One state machine, one approval API, one renderer. The
composition rule is data, not a second code path.
**Rejected alternatives:**
- *Two separate tables* — duplicates the state machine, the versioning, the
  freeze logic and the renderer.

### ADR-D7 — Resolve the `site_update` / `field_update` / `field-reports` naming split

**Status:** Accepted
**Context:** The contract says `SITE_UPDATE`, the workflow package is
`field_update`, and the dashboard page is `FieldReportsPage` — three names for
one concept, already in the codebase.
**Decision:** The **contract name wins** for anything crossing a module
boundary. Rename the workflow package `field_update/` → `site_update/` in
Phase 3 (it is 0 bytes; the rename is free). Leave `FieldReportsPage.tsx` and
its `/operations/field-reports` route alone — it is user-facing copy, not a
contract, and "Field Reports" is the better product word.
**Consequences:** One rename, done before any code exists in the package.
**Rejected alternatives:**
- *Rename the contract* — `WorkflowKey.SITE_UPDATE` is referenced by the
  planner routing map and a comment in `replies.py`; changing a shipped
  contract enum for cosmetics is not worth it.

### ADR-D8 — Reuse the receipt renderer for DPR documents

**Status:** Accepted
**Context:** `channel/receipt/` already renders Jinja2 HTML/CSS to PNG via
in-process headless Playwright, with no additional service.
**Decision:** DPR rendering extends that pipeline rather than introducing a
PDF library or a rendering service.
**Consequences:** Multi-page output needs verifying against the current
single-card template — an open item for Phase 6. If PDF proves necessary,
Playwright's `page.pdf()` is available on the same Chromium instance.

### ADR-D9 — Already-shipped modules are V1 DPR content, not future work

**Status:** Accepted (2026-07-27, correcting the product spec)
**Context:** The product spec listed Labour Attendance, Material Inventory,
Vendors and Equipment Management as future ERP extension points, and
correspondingly marked Labour/Material/Expense summaries in the DPR and
Material/Expense events in the Timeline as "(future)". All of those modules
are already shipped and carrying production data.
**Decision:** They are **V1**. The DPR and Timeline read them through
`timeline_entries` (P3 — reference, never write), gated only by Phase 6.0.
**Consequences:** Phase 6.0 becomes load-bearing rather than housekeeping.
The DPR is materially more useful at launch, at the cost of one prerequisite
slice that had to be built anyway.
**Rejected alternatives:**
- *Ship the DPR without labour/material/expense sections* — a daily report
  with no headcount and no material consumption is not one a site manager
  will accept, and the data already exists. Deferring would be shipping a
  knowingly worse product to avoid a prerequisite that Phase 6 needs anyway.

### ADR-D10 — Completion % is `MANUAL`-only in V1, and always labelled

**Status:** Accepted
**Context:** The product spec places Work Packages at Phase 2, so V1 has no
planned quantities and therefore no denominator.
**Decision:** V1 stores only engineer-stated estimates (`completion_mode =
MANUAL`). Every rendering surface displays the mode alongside the number.
**Consequences:** When Phase 9 introduces `QUANTITY` mode, both kinds coexist
and remain visually distinguishable. Existing `MANUAL` values are never
retroactively recomputed.
**Rejected alternatives:**
- *Render a bare %* — owners would trust a number for months whose meaning
  silently changes the day denominators arrive. This is the single most
  likely way for this module to lose credibility.

### ADR-D11 — _(reserved: DPR templates — see §10 open decision #6)_

### ADR-D12 — One `SITE_UPDATE` workflow key, several graphs behind it

**Status:** Accepted (2026-07-27)
**Context:** §2.1 reserved a single `WorkflowKey.SITE_UPDATE`. Real field
usage needs distinct handling for creation, continuation, correction,
evidence and issues — collapsing them into one graph's conditionals would
produce the special-case sprawl P1 exists to avoid, just one layer up.
**Decision:** §1B.1's graph list. `SITE_UPDATE` remains the entry key for
`activity_creation` only; `ACTIVITY_CONTINUATION`, `ACTIVITY_CORRECTION`,
`SITE_ISSUE`, `PROGRESS_QUERY` are new `WorkflowKey` values added in Phase 2.
**Consequences:** More graphs to register, but each stays small and each
follows the repository's existing one-graph-per-capability convention
(`workflows/registry.py`) rather than inventing a different shape for this
module.
**Rejected alternatives:**
- *One graph with a large router node* — every module in this repo already
  rejected this shape; no reason for Daily Reporting to reintroduce it.

### ADR-D13 — Context resolution and the event bus are reused, not rebuilt

**Status:** Accepted (2026-07-27)
**Context:** An external architecture proposal suggested a new "Context
Resolution Graph" and a new "Event Bus" as prerequisite systems for this
module. Both already exist: M4 (`context/resolver.py`) and `outbox_events` →
`timeline_projector.py` respectively (§2.1, §2.3).
**Decision:** P11/P12. Every Daily Reporting graph consumes M4's output and
`ContextConfidence` directly; every downstream consumer (Timeline, Search,
Notifications, DPR) subscribes to the existing outbox pattern from Phase 6.0
rather than a module-local equivalent.
**Consequences:** No new cross-cutting infrastructure ships with this module.
**Rejected alternatives:**
- *Module-local context resolution* — the second implementation of exactly
  the thing `AGENTS.md`'s Module Placement Log exists to prevent, and the
  reason "continue"/"same place" phrasing would work differently depending
  on which module the user was last talking to — a worse user experience,
  not just worse code.

### ADR-D14 — Correction targets the Activity header; Progress Updates stay append-only

**Status:** Accepted (2026-07-27)
**Context:** §1B.5. A proposed "Activity Correction Workflow" risked
conflicting with P1's append-only rule for Progress Updates if implemented
without this distinction.
**Decision:** Corrections to `work_type`, `location_id`, contractor, or the
Activity's initial estimate mutate the Activity row directly, with an audit
trail (who/when/field/old→new — same shape as ADR-D5). Progress Updates
remain immutable; a correction to a stated quantity-at-a-moment is a new
update, not an edit. A correction can never target a value already frozen
into an approved DPR version (P7) — that path is a DPR revision instead.
**Consequences:** Two different code paths for "the user said this was
wrong," selected by *what* was wrong, not by a generic "edit" verb.

### ADR-D15 — Undo is scoped to same-session reversal, not a rollback engine

**Status:** Accepted (2026-07-27)
**Context:** §1B.7. "Undo" as a generic capability is unbounded scope;
construction reality only needs the common case.
**Decision:** Undo covers an Activity/Progress Update the reporter just
created, soft-deleted with audit (never hard delete), unavailable once a DPR
version has frozen it. Undo of a cross-module-triggered record composes
through that module's own reversal command (P12) — Daily Reporting never
implements Material's or Labour's reversal logic itself.
**Consequences:** No generic event-sourced rollback system. If broader undo
is needed later, it is scoped and decided then, against real usage data.
**Rejected alternatives:**
- *General rollback engine* — unbounded scope for a need that, in practice,
  is "I mistyped, let me fix the last thing I sent."

---

## 6. Data model (design — not yet implemented)

Migration numbers are provisional; current head is `0401`.

### 6.1 Locations — `core`, migration `0410`

```
location_nodes
  id, organization_id, project_id, site_id (nullable)
  parent_id        → location_nodes.id, nullable
  level_label      "Block" | "Floor" | "Zone" | "Chainage" | free text
  name             "A" | "2" | "km 12+400"
  path             materialized ltree/text, for subtree queries
  created_at, updated_at, created_by
  UNIQUE (parent_id, name)
```

### 6.2 Work Packages — `progress`, migration `0420`

```
work_packages
  id, organization_id, project_id, site_id (nullable)
  parent_id        → work_packages.id, nullable (hierarchical)
  code             sequential per project — WP-001 (reuse 0400's generator)
  name             "Block A Foundation"
  location_id      → location_nodes.id, nullable
  assigned_user_id → users.id, nullable
  planned_start, planned_end          date, nullable
  actual_start, actual_end            date, nullable — derived from activities
  status           NOT_STARTED | IN_PROGRESS | ON_HOLD | COMPLETED
  completion_mode  NONE | QUANTITY | MILESTONE | MANUAL   (P6, default NONE)
  manual_completion_pct  numeric, only when mode = MANUAL
  created_at, updated_at, created_by

work_package_planned_items
  id, work_package_id
  work_type        "plastering" | "concreting" | ...
  unit_id          → units_of_measure.id   (0290 — reuse, do not duplicate)
  planned_quantity numeric
  revision_no, superseded_by_id, revision_reason, changed_by  (ADR-D5)
  UNIQUE (work_package_id, work_type, unit_id) WHERE superseded_by_id IS NULL
```

### 6.3 Activities — `progress`, migration `0430`

```
activities
  id, organization_id, project_id, site_id
  work_package_id  → work_packages.id, NULLABLE (P4 — backfillable)
  location_id      → location_nodes.id, NULLABLE
  work_type        text, nullable
  activity_date    date, NOT NULL       — the reporting day
  started_at, ended_at  time, nullable
  status           PLANNED | IN_PROGRESS | COMPLETED | STOPPED
  narrative        text                 — what the engineer actually said
  reported_by_user_id, source ('whatsapp'|'dashboard'), correlation_id
  deleted_at       timestamptz, nullable  -- soft-delete only, ADR-D15 undo
  created_at, updated_at

activity_quantities
  id, activity_id
  work_type, unit_id → units_of_measure.id, quantity numeric
  measurement_type  ACHIEVED | CUMULATIVE   -- "180 today" vs "1840 to date"

activity_links                            -- ADR-D2 / P3: references only
  id, activity_id
  linked_type   ATTENDANCE | MATERIAL_MOVEMENT | EQUIPMENT_EVENT | EXPENSE
  linked_id     uuid  (no FK — polymorphic across domains, resolved in app layer)

activity_corrections                      -- ADR-D14: header edits, audited
  id, activity_id
  field_name, old_value, new_value        -- jsonb old/new for typed fields
  reason, corrected_by_user_id, correlation_id, created_at
  -- rejected once daily_report_versions.payload has frozen this activity (P7)
```

### 6.4 Progress Updates — `progress`, migration `0430`

```
progress_updates                          -- APPEND ONLY (P1)
  id, activity_id
  occurred_at      timestamptz
  update_kind      STARTED | PROGRESS | PAUSED | RESUMED | COMPLETED | NOTE
  narrative        text
  quantity, unit_id            nullable — incremental quantity at this moment
  supersedes_id    → progress_updates.id, nullable (corrections)
  reported_by_user_id, source, correlation_id, created_at
```

### 6.5 Issues & Blockers — `progress`, migration `0430`

```
site_issues
  id, organization_id, project_id, site_id
  activity_id      → activities.id, NULLABLE (a blocker can precede any activity)
  work_package_id  → work_packages.id, nullable
  location_id      → location_nodes.id, nullable
  issue_type       WEATHER | MATERIAL_SHORTAGE | LABOUR_SHORTAGE
                 | DRAWING_PENDING | EQUIPMENT_BREAKDOWN | INSPECTION_WAITING
                 | ACCESS | OTHER
  severity         LOW | MEDIUM | HIGH | CRITICAL
  narrative        text
  delay_duration_minutes  integer, nullable   -- feeds delay attribution
  occurred_at, resolved_at
  status           OPEN | ACKNOWLEDGED | RESOLVED | WONT_FIX
  assigned_user_id, reported_by_user_id, correlation_id
```

Issues get their own table rather than an update kind because they have a
lifecycle (open → assigned → resolved) that an append-only update cannot express.

### 6.6 Evidence — reuse the attachment pattern (ADR-D8 rationale)

```
progress_attachments        -- identical shape to expense_attachments
  id, parent_type (ACTIVITY | PROGRESS_UPDATE | SITE_ISSUE), parent_id
  media_object_key, attachment_type, mime_type
  caption          text  -- the REPORTER's caption (a fact)
  ai_caption       text  -- AI-generated (an insight) — §1A.1(3), never merged
  role             nullable: BEFORE | AFTER | GENERAL   -- open decision #8
  captured_at, gps_lat, gps_lon        -- nullable; WhatsApp rarely supplies GPS
  uploaded_by_user_id, created_at
```

`caption` and `ai_caption` are separate columns, not one field with a flag.
PRD §6 principle 3 (strict facts/insights boundary) is a schema-level
constraint here, not a rendering convention.

Timeline and Gallery integration come for free by reusing this shape.

### 6.7 Daily Reports — `dpr`, migration `0440`

```
daily_reports
  id, organization_id, project_id, site_id (NULL when level = PROJECT)
  level            SITE | PROJECT                      (ADR-D6)
  report_date      date
  code             sequential — DPR-001 (reuse 0400's generator)
  status           DRAFT | NEEDS_DETAILS | READY | IN_REVIEW | APPROVED | PUBLISHED | NOT_REPORTED
                   (NEEDS_DETAILS, READY added in 0466 -- BE-08)
  missing_sections JSONB, nullable   -- {"blocking": [...], "optional": [...]} (0466)
  weather, hours_lost, site_working (full|half|none), tomorrow_plan   -- nullable (0468, BE-14)
  current_version_id → daily_report_versions.id, nullable
  UNIQUE (project_id, site_id, report_date, level)

daily_report_versions                     -- FROZEN on approval (P7)
  id, daily_report_id, version_no
  payload          JSONB   -- the complete frozen snapshot
  narrative_summary text   -- AI-generated, engineer-edited
  approved_by_user_id, approved_at
  supersedes_version_id, revision_reason
  rendered_object_key      -- ADR-D8 output
  created_at

daily_report_sources                      -- P8 composition
  id, project_version_id → daily_report_versions.id
  site_daily_report_id, site_version_id (NULL ⇒ NOT_REPORTED)
```

**The site's working day (V1, BE-08, 13 Oct 2026).** A SITE-level
`daily_reports` row *is* the site day; there is no separate `site_days`
table. Rules live in `backend/src/mesiri/application/dpr/site_day.py`:

| V1 step | Status | Set by |
| --- | --- | --- |
| collecting | `DRAFT` | a draft refreshed before cutoff |
| needs details | `NEEDS_DETAILS` | cutoff: no work item, or no labour count |
| ready | `READY` | cutoff: at least one work item and a labour count |
| with engineer | `IN_REVIEW` | `submit-for-review`; a refresh no longer resets it |
| confirmed | `APPROVED` | the site engineer (only approver); stamps `approved_by_user_id`/`approved_at` |
| sent | `PUBLISHED` | `publish` |

At cutoff, `open_site_days` gives every active site its day, including sites
that logged nothing (labelled, no version). Photos and materials are listed
in `missing_sections.optional` but never block. `GET /dpr/site-days?date=`
lists every active site's day.

**Site conditions (BE-14).** `PATCH /dpr/site-days/{site_id}/conditions?date=`
sets weather, hours lost, site working and tomorrow's plan on the day row
(refused once confirmed). They are copied into each version's
`payload.conditions`. Hours lost not entered = the day's issue delays added up
(`hours_lost_source: "issues"`). `site_working = none` ("no work today") makes
the day ready with nothing required; weather and tomorrow's plan are optional
missing items.

**Sending the project DPR (BE-16).** The cutoff only builds drafts; nothing is
sent then. The DPR goes to the project's ADMIN/PROJECT_MANAGER users when every
active site is confirmed, at `projects.dpr_send_deadline` (default 21:00, local
time), or on "Send now" (`POST /dpr/projects/{id}/send`), whichever is first,
once per local day (`projects.dpr_last_sent_on`). A single-site project whose
site is confirmed sends that site DPR; otherwise the PROJECT roll-up is built
from confirmed site versions only, unconfirmed sites recorded not reported, and
is approved by composition. The WhatsApp tick (`runtime/project_auto_dpr.py`
`send_due_project_dprs`) renders the PDF if needed, claims one notification per
recipient (subject = recipient), and marks the report and its confirmed sites
PUBLISHED. Backend half: `application/projects/auto_dpr.py`.

**Save first, confirm later (BE-09, migration 0470).** `extractions` records
what the AI read from a message (model, structured output, ContextConfidence).
`fact_reviews` is an append-only review log for activities, site issues, labour
reports and material receipts/usage: a fact's state is its latest row, and no
row means confirmed (everything saved confirm-first). Facts' own tables are not
changed. Confirm: `POST /dpr/facts/{type}/{id}/confirm`. Reject (drafts only,
not on a confirmed day): `POST /dpr/facts/{type}/{id}/reject` with a reason;
it calls the owning module's undo (`void_activity`, `cancel_issue`,
`void_attendance_report`, `reverse_material_record`) and records why.
Confirming a site day confirms its remaining drafts and rebuilds the version
first. The payload marks each activity/issue `review` and counts `drafts` per
section. The site DPR now leaves out cancelled issues and reversed material
movements (with their reversals). WA-01 is what starts saving drafts.

---

## 7. WhatsApp side — responsibilities

| Capability | Phase | Notes |
|---|---|---|
| Route `general_site_update` to a compiled graph | 3 | closes the 0-byte gap |
| Extract `work_type`, `quantity`, `unit`, `location`, `status`, `duration` | 2 | extend the existing `general_site_update` slot |
| Resolve location text → `location_nodes` | 3 | resolution gate, `material_catalog_query.py` pattern |
| Resolve work package (best-effort, never blocking) | 3 | P4 — nullable |
| Attach photo/voice as evidence | 3 | existing `img_site_update` list row |
| Structured preview + confirmation | 3 | P2 — non-negotiable |
| Receipt card on save | 3 | reuse `channel/receipt/` |
| Report an issue/blocker with duration | 3 | same graph, `issue` branch |
| Evening DPR-ready nudge + approve-by-button | 6/8 | |
| Progress questions ("how much brickwork this month?") | 9 | new `progress_query` workflow, V2 |

The graph must **not** ask for quantity, location or work package when absent
(P10). It asks for project/site only when the existing resolver cannot decide.

---

## 8. Dashboard side — responsibilities

All under the existing **Operations** sidebar category (§2.5).

| Route | Page | Phase | State today |
|---|---|---|---|
| `/operations/overview` | Portfolio & project pulse, compliance strip | 7/8 | placeholder |
| `/operations/timeline` | Activity + update feed with evidence | 7 | placeholder |
| `/operations/field-reports` | Activities list, filters, detail sheet | 7 | 128-line static placeholder |
| `/operations/work-packages` | **new** — WBS tree, planned items, % | 7 | does not exist |
| `/operations/daily-reports` | **new** — DPR draft → review → approve | 7 | does not exist |
| `/operations/gallery` | Evidence gallery | 7 | placeholder |
| `/operations/analytics` | S-curve, productivity, delay analysis | 9 | placeholder |

Reuse `Labour*.tsx` page structure, `kpi-card.tsx`, `bulk-action-bar.tsx`,
`chart.tsx`, and the detail-sheet pattern from `attendance-detail-sheet.tsx`.

---

## 9. Phase checklist

### Phase 0 — Reconnaissance & design
- [x] Confirm existing rails (§2.1)
- [x] Confirm `0260` reporting columns unused (§2.2)
- [x] Confirm dashboard placement (§2.5)
- [x] Principles, ADRs, data model (§3, §5, §6)
- [x] Product specification adopted as the feature surface (§1A), 2026-07-27
- [x] Add Module Placement Log row in `AGENTS.md`
- [ ] Create Linear epic

### Phase 1 — Business & domain model
- [ ] `backend/src/mesiri/domains/progress/` entities & value objects
- [ ] Completion-mode logic — pure, fully unit-tested, no DB (V1: `MANUAL` only,
      but the enum and the provenance label ship now — ADR-D10)
- [ ] Decide ADR-D5's revision shape (revision rows vs `effective_from`) — Ph9 input
- [ ] `backend/src/mesiri/domains/dpr/` state machine — pure

### Phase 2 — Contracts
- [ ] Rename `workflows/field_update/` → `site_update/` (ADR-D7)
- [ ] Extend `general_site_update` extraction slots in both AI adapters:
      activity, quantity, unit, date/time, location, engineer, contractor, issue
- [ ] Add `WorkflowKey.ACTIVITY_CONTINUATION`, `ACTIVITY_CORRECTION`,
      `SITE_ISSUE`, `PROGRESS_QUERY` + matching `CanonicalEventType`s (ADR-D12)
- [ ] Multi-activity segmentation is upstream of routing — decide whether it's
      an understanding-layer step (one message → N CanonicalEvents) or an
      activity_creation-graph-internal step (§1B.3) before writing extraction
      prompts
- [ ] Contract tests in `shared/contracts`

### Phase 3 — Workflow + persistence + application layer (§1A areas 1, 2, 4; §1B)
- [x] Domain/application package scaffolding: `domains/{progress,dpr}/`,
      `application/{progress,dpr}/` (empty `__init__.py`, reserved — matches
      the convention already used for `domains/reports/` etc.), 2026-07-27
- [x] Migration `0410` — `location_nodes` (P9, shared `core` tree), 2026-07-27
- [x] Migration `0420` — `work_packages` + `work_package_planned_items`
      (built now so `activities.work_package_id` has a real FK target; no
      application code reads/writes until Phase 9), 2026-07-27
- [x] Migration `0430` — `activities`, `activity_quantities`,
      `activity_links`, `activity_corrections`, `progress_updates`,
      `site_issues`, `progress_attachments`, 2026-07-27
- [x] Migration `0440` — `daily_reports`, `daily_report_versions`,
      `daily_report_sources`, 2026-07-27
- [x] Verified: `alembic history` resolves the chain to `0430 -> 0440 (head)`
      with no forks. **Not verified:** actually applying `alembic upgrade
      head` against a live database — no DB reachable from this machine
      (same limitation as ADR-L1). Run this in an environment with DB access
      before building anything on top of these tables.
- [ ] `workflows/activity_creation/{state,graph,nodes,transitions,policies}.py`
      — the `site_update` gap (§2.1), multi-activity split (§1B.3)
- [ ] `workflows/activity_continuation/` — append-only progress updates,
      status transitions (started/paused/resumed/completed)
- [ ] `workflows/activity_correction/` — Activity header mutation + audit
      (ADR-D14; must NOT touch `progress_updates`)
- [ ] `workflows/issue/` — classify, priority, duplicate-check
- [ ] `workflows/shared/` — extract on third-graph duplication, not before
      (§1B.2): `resolve_context` (P11), `resolve_activity`, `resolve_location`,
      `confirmation`, `cross_module_trigger` (P12)
- [ ] `resolve_activity`: reply-based continuation first (§1B.4, fills the
      `NullReplyContextProvider` stub with a real message_id → activity_id
      store), ranking fallback second, ask only on ambiguity (P10)
- [ ] Semantic duplicate-activity check (§1B.8) — distinct from the existing
      message-id `ingress/deduplication.py`
- [ ] Low-confidence gate (§1B.9) reusing `ContextConfidence` — no new scale
- [ ] Undo (§1B.7/ADR-D15): same-session soft-delete for activities/updates;
      cross-module undo calls that module's own reversal command, never a
      local delete
- [ ] Location resolution gate + create-gate
- [ ] Register all graphs in `workflows/registry.py`; remove the
      `replies.py:155` workaround
- [ ] Migrations `0410` locations · `0420` work packages · `0430`
      activities/updates/issues/attachments/`activity_corrections` · `0440`
      daily reports
- [ ] Sequential codes via `0400`'s generator (ACT-, WP-, DPR-)
- [ ] `application/progress/{commands,handlers,dispatcher,mapper,repository,resolution}.py`
- [ ] `domains/progress/router.py` REST
- [ ] `activity_links` polymorphic resolution (P3 — read-only) +
      `cross_module_trigger.py` calling existing dispatchers (P12) for
      material/equipment mentions inside a progress message
- [ ] Integration test mirroring `test_labour_attendance_graph.py`, plus one
      per new graph (continuation, correction, issue, multi-activity split)

### Phase 4 — Evidence (§1A area 3)
- [ ] `workflows/evidence/` graph
- [ ] `progress_attachments`, reusing the `expense_attachments` shape
- [ ] `caption` vs `ai_caption` as separate columns (§1A.1(3))
- [ ] Before/after `role` — resolve open decision #8
- [ ] GPS best-effort — resolve open decision #7
- [ ] Voice note + document attachment paths
- [ ] Batch media clustering (§1B.6) — buffer window + arrival-time clustering,
      match cluster to most recent open Activity rather than per-photo resolution
- [ ] Smart follow-up: "upload a completion photo?" after a `COMPLETED` status
      update with no attached evidence (low-complexity rule node)

### Phase 5 — Timeline (§1A area 5)
- [ ] Activity / progress / issue / evidence events in the feed
- [ ] Filters, search, date navigation
- [ ] Material / expense / labour events arrive via Phase 6.0

### Phase 6.0 — Outbox projection prerequisite (§2.3, ADR-D9)
- [ ] Fix the labour silent-discard: add `labour_attendance_report` to
      `AGGREGATE_TABLES` + a `LabourAttendanceRecorded` summary builder
      (live bug, independent of this module)
- [ ] Emit `outbox_events` from the finance/expense execution repositories
      (expenses, transfers, petty cash, reversals) — currently none do
- [ ] Emit `outbox_events` from the new `progress` repositories (Phase 5)
      and register their aggregates
- [ ] Confirm what invokes `make project-timeline` in production, and at what
      cadence — the DPR assembler's freshness depends on it
- [ ] Backfill projection for existing rows

### Phase 6 — DPR assembly, approval, freeze (§1A area 6)
- [ ] Day-log assembler — activities, progress, issues, evidence
- [ ] **Labour, material and expense summaries** from `timeline_entries` (ADR-D9)
- [ ] Weather field (manual entry in V1; no API — out of scope §1)
- [ ] AI narrative summary (facts/insights boundary — PRD §6 principle 3)
- [ ] State machine + version freeze + revision diff + sign-off
- [ ] Project composition from site versions, `NOT_REPORTED` handling,
      single-site auto-approve (P8)
- [ ] Export PDF via `channel/receipt/` (verify multi-page — ADR-D8)
- [ ] Templates — resolve open decision #6, or defer to Phase 8

### Phase 7 — Dashboard, Operations category (§1A areas 1–7)
- [ ] Activities — list, details, create (`/operations/activities`)
- [ ] Bind `FieldReportsPage.tsx` to real data (replace the 9 hardcoded chips)
- [ ] Timeline binding (`/operations/timeline`)
- [ ] Daily Reports — drafts, published, templates (`/operations/daily-reports`)
- [ ] Issues (`/operations/issues`)
- [ ] Gallery (`/operations/gallery`)
- [ ] Overview — project pulse
- [ ] Sidebar entries in `app-sidebar.tsx`, routes in `App.tsx`

### Phase 8 — Compliance & nudges
- [ ] Read `reporting_cutoff_time` / `auto_generate_dpr` / `required_report_types`
- [ ] "Who owes a report today" from `project_members`
- [ ] Cutoff nudges + escalation
- [ ] Operations Overview compliance strip

### Phase 9 — Work Packages (spec "Phase 2")
- [ ] `work_packages` + `work_package_planned_items` wired (tables land in `0420`)
- [ ] WBS tree page, attach orphan activities, enter planned quantities
- [ ] `QUANTITY` + `MILESTONE` completion modes; `MANUAL` values never recomputed
- [ ] Mode badge on every % surface (ADR-D10)

### Phase 10 — Analytics (§1A area 8)
- [ ] Daily / weekly / monthly progress, completion statistics
- [ ] Activity, productivity, delay and issue trends
- [ ] Engineer / contractor **activity volume** — see open decision #9
- [ ] S-curve (needs Phase 9's planned quantities)

### Phase 11 — AI Assistant refinements (§1A area 9)
- [ ] `progress_query` workflow; fill the `ask_mesiri/` stub
- [ ] Generate DPR on request, explain delays, search photos, summarise today
- [ ] Conversation continuation, smart confirmations

---

## 10. Open decisions

| # | Question | Owner | Blocking |
|---|---|---|---|
| 1 | ADR-D5 revision shape: revision rows vs `effective_from` interval | Phase 1 | Phase 4 |
| 2 | ~~Is `timeline_entries` actually being projected?~~ **Resolved 2026-07-27: only Materials. Labour is silently discarded; Finance never emits.** Now Phase 6.0. | — | resolved |
| 3 | Does the receipt renderer handle multi-page output, or is `page.pdf()` needed? | Phase 6 | Phase 6 |
| 4 | Is `work_type` a free-text string or a reference table? (free text V1, promote later?) | Phase 1 | Phase 4 |
| 5 | Should a progress message containing material consumption auto-invoke the material handler, or just prompt the user to send it separately? (P3 permits both; the first is better UX, the second is simpler) | Phase 3 | Phase 3 |
| 6 | **DPR Templates** (§1A, `Daily Reports → Templates`) — what is configurable? Section on/off, ordering, letterhead/branding, custom fields? Scope not yet defined. Candidate for deferring to Phase 8. | Phase 6 | Phase 6 |
| 7 | Evidence **GPS** — WhatsApp supplies location only for explicit location messages, not on photos. Is GPS best-effort (usually null), or does it need a prompt? | Phase 4 | Phase 4 |
| 8 | **Before/After images** (§1A area 3) — an attachment `role` enum, or a separate pairing table? | Phase 4 | Phase 4 |
| 9 | Analytics frames "Engineer / Contractor Performance" as scoring people on **self-reported** data, which invites gaming. Recommend shipping as neutral *activity volume*, not performance ranking. | Phase 10 | no |
| 10 | Multi-activity segmentation (§1B.3) — split at the understanding layer (one message → N `CanonicalEvent`s, reusing existing single-event confirmation) or inside `activity_creation` (one event, N segments, new combined-confirmation UI)? Affects Phase 2 contract shape. | Phase 2 | Phase 3 |
| 11 | Low-confidence threshold (§1B.9) — where does the per-graph `ContextConfidence` cutoff live: static config, per-organization setting, or per-work-type? Start static; revisit once real extraction accuracy is observed. | Phase 3 | no |
| 12 | Same-session window for undo (§1B.7/ADR-D15) — how long after creation is "wrong, delete that" still unambiguous? Candidate: same WhatsApp conversation turn or a short fixed window (e.g. 10 minutes), not "any time today." | Phase 3 | Phase 3 |

---

## 11. Where work stopped / what to do next

**Stopped at:** end of Phase 0. This document is the only artefact. No code,
no migrations, no contract changes.

**Next actions, in order:**

1. ~~Add the Module Placement Log row to `AGENTS.md`~~ — done 2026-07-27.
2. ~~Verify the `timeline_entries` projection~~ — done 2026-07-27, see §2.3.
   Result: only Materials projects; Labour is silently discarded; Finance
   never emits. Became **Phase 6.0**.
3. ~~Adopt the product specification~~ — done 2026-07-27, §1A. It is now the
   authority on *what*; §3/§5/§6 remain the authority on *how*.
4. ~~Reconcile the WhatsApp workflow-decomposition proposal~~ — done
   2026-07-27, §1B + P11/P12 + ADR-D12–D15. Two of its proposed systems
   (context resolution, event bus) turned out to already exist and are reused
   rather than rebuilt (ADR-D13) — this was the one finding worth checking
   before agreeing to build anything new.
5. Resolve open decision #4 (`work_type` free text vs reference table) and
   #10 (multi-activity segmentation layer) — both are Phase 2 inputs now.
   #1 stays at Phase 9 with Work Packages.
6. ~~Schema~~ — done 2026-07-27: domain/application folders scaffolded,
   migrations `0410`–`0440` written and chain-verified via `alembic history`
   (`0430 -> 0440 (head)`, no forks). **Run `alembic upgrade head` against a
   real database before building on these tables** — not yet done from this
   machine (no DB access here).
7. Begin Phase 1 proper — pure domain model (completion-mode logic, DPR state
   machine) and Phase 3's application layer, fully unit-tested, against the
   now-settled schema.

Phase 6.0's first item (the labour silent-discard) is a live bug that can be
fixed at any time, independently of this module, by anyone.

**Parallelisation note.** The product spec assigns WhatsApp + backend to
"Agent 1". Phase 3 is the largest single phase and the natural boundary: the
graph (`apps/whatsapp-assistant/`) and the persistence/application layer
(`backend/`) can proceed in parallel once Phase 2's contracts land, because
contracts are the only thing they share. Phase 7 (dashboard) can start against
Phase 3's REST API before Phase 6 completes. Do **not** parallelise Phase 1 —
the domain model is the thing everything else agrees on.

**Do not** start Phase 4 migrations before Phase 1's model is settled; the
`0410`–`0440` numbering assumes head is still `0401`, which should be
re-checked (`git log backend/migrations/versions/`) since main moves fast.
