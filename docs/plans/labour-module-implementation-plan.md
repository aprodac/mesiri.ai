> **HISTORICAL (31 Oct 2026).** The WhatsApp assistant is now v2: one agent + skills + tools, see [../architecture/assistant-v2.md](../architecture/assistant-v2.md).
> Banner only: the Labour content is unchanged. This document describes the classic chain (classifier / planner / workflows), now retiring; the body is unchanged.

# Labour Module — Master Implementation Plan

**Status:** In progress — Phases 0–6 substantially complete (Phase 6's routing/
extraction/canonicalization/attachment/wiring items are done; end-to-end
verification against a live database is still outstanding). **Next: Phase 7
(platform integration) or live-DB verification of Phases 4–6 — see §15.**
**Owner:** Alan Raj
**Started:** 2026-07-25
**Last updated:** 2026-07-26
**Linear:** _(issue to be created — see §12)_

> **Resuming in a new session?** Read §12 first — it says exactly where work
> stopped and what to do next. Then read §2 (what already exists), §3
> (the binding principles) and §3A (the finish line).

> **Purpose of this document.** It is the durable memory for this module. If a
> future session — human or AI — loses all conversational context, this file
> alone should explain what exists, what is being built, what remains, why each
> decision was made, and what to do next. Keep it updated as work proceeds;
> a stale plan is worse than none.

---

## 1. What the Labour module is

Record **who worked, where, in what trade, and at what cost.**

It is deliberately *not* a Workforce Management System or an HRMS. V1 has
exactly one operational action: **Record Attendance**.

Explicitly out of scope for V1: payroll, salary generation, leave, overtime,
union/bonus calculation, PF/ESI, shift scheduling, GPS attendance, face
recognition, biometrics, HR management, approval workflows, performance
management.

---

## 2. Reconnaissance findings (2026-07-25)

Read before assuming anything about the current state.

### 2.1 The routing rails already exist

Labour was anticipated when the platform was laid out. These are **already
present and require no invention**:

| Thing | Where | Value |
|---|---|---|
| `WorkflowKey.LABOUR_ATTENDANCE` | `shared/contracts/.../planner_decision.py` | `"labour.attendance"` |
| `CanonicalEventType.LABOUR_ATTENDANCE_REQUESTED` | `shared/contracts/.../canonical_event.py` | `"LabourAttendanceRequested"` |
| `SemanticType.LABOUR_UPDATE` | `shared/contracts/.../enums.py` | `"labour_update"` |
| AI extraction slot | `platform/ai/src/mesiri_ai/adapters/gemini/adapter.py` | `labour_update: headcount, trade, hours, contractor, project_name` |
| Empty workflow package | `apps/whatsapp-assistant/src/workflows/labour_update/` | `__init__.py` only, 0 bytes |
| Empty domain package | `backend/src/mesiri/domains/workforce/` | `__init__.py` only, 0 bytes |

`workflows/state.py`'s own docstring says *"Every v1 graph (material, and later
expense/equipment/labour)"* — the shape was designed with Labour in mind.

### 2.2 Existing labour tables are unusable for this product

Migration **0120** (2026-07-08) created `labour_attendance` and
`labour_attendance_entries`.

**They are unused.** A repo-wide search found only two references, neither
functional:
- `apps/whatsapp-assistant/src/admin/router.py` — a tenant-delete cascade list
- `backend/tests/integration/test_organizations_cascade_delete_schema.py`

No code reads or writes them.

Two hard incompatibilities with the V1 product:

1. **`UniqueConstraint("site_id", "occurred_date")`** — one attendance row per
   site per day. The product requires attendance to be *append-only immutable
   history*. A second report for the same site and day cannot be stored under
   this constraint without overwriting the first.
2. **`labour_attendance_entries.worker_name` is free text** — no link to any
   worker record. The product requires a reusable **workforce register** and
   matching that never relies on name alone.

The 0120 migration's own docstring anticipated this:

> *"Full Workforce (shifts, wages, contracts) is a later module and will very
> likely supersede this table rather than extend it — do not over-build here."*

**Decision:** supersede, do not extend. See ADR-L1.

### 2.3 Canonical reference modules

- **Material** — the most complete operational module; the primary reference.
- **Expense** — newer, partially complete; good reference for images
  (`expense_attachments`), slot-filling (`workflows/expense_capture`), and the
  finance-style domain layer, but **not complete**, so do not assume its
  every pattern is settled.

Where they disagree, prefer Material, and note the divergence here.

**Known divergences observed:**

| Concern | Material | Expense |
|---|---|---|
| Command contract location | `shared/contracts/.../application/commands/material.py` | `backend/.../application/expenses/commands.py` |
| Domain layer shape | thin (`validation.py`, `posting.py`, `router.py`) | rich DDD (`entities.py`, `value_objects.py`, `policies.py`, `events.py`) |
| Handler entry method | `handle()` | `handle_confirmed()` |

### 2.4 Update — 2026-07-25, after merging 34 incoming commits

A large batch of Finance work landed mid-design. Three parts of it directly
affect Labour and **reduce** what must be built:

1. **Image purpose picker already reserves a slot for attendance.**
   `channel/replies.py`'s `IMAGE_PURPOSE_ROWS` sends a "what is this photo
   for?" picker for every uncaptioned image, and its comment states the
   intent explicitly: *"more purposes (attendance, etc.) get their own row
   here later, not a different mechanism."* Labour adds one row — it does
   **not** build its own image-intake path.

2. **Duplicate detection precedent exists, but is field-based.**
   `find_potential_duplicate` (expenses repository) matches on amount + date
   + vendor/category and **warns rather than rejecting**. That confirms the
   interaction pattern for Labour's duplicate handling, but it is not image
   hashing — near-duplicate *image* detection (open question Q3) still has to
   be built.

3. **Attachment + gallery paths are now exercised by tests**
   (`test_expense_attachment_gallery.py`), which strengthens ADR-L3: reusing
   the attachment shape gets gallery integration essentially for free.

Verified after merge: 1046 tests passing, lint clean.

---

## 3. Architectural principles (non-negotiable)

These are binding constraints on the implementation, not preferences.

### P1 — Attendance ≠ Workforce

They are separate concepts and must never be conflated in code.

```
Attendance ──references──> Workforce
```

or, for someone not yet in the register:

```
Attendance ──> Temporary Worker ──optionally promoted──> Workforce
```

> ### ⚠️ SUPERSEDED 2026-07-29 — read this before the paragraph below
>
> **Attendance now creates a worker row for every named person, immediately.**
> Decided by Alan and implemented in roadmap phase 4
> (`labour_execution.py::_ensure_worker_identities`). The paragraph below is
> kept because the reasoning behind it is still worth knowing, not because it
> is still in force.
>
> **What broke.** P1 left a temporary worker with `worker_id = NULL`, so their
> history was keyed on the *name string*. Promotion then inserted a brand-new
> register row, and the days they had already worked stayed attached to the
> old key while everything afterwards accrued to the new id — one person, two
> partial histories, and no way to merge them after the fact. Production on
> 2026-07-29: **26 people in attendance, 8 linked to a register row.**
>
> **What replaces it.** Every named line resolves to a durable id at the
> moment of recording — reusing an existing worker when normalized name and
> trade match, creating one marked `worker_type='temporary'` otherwise.
> Promotion flips that same row to `'permanent'`; the id never changes and no
> history moves.
>
> **P1's concern is answered, not ignored.** The register is still not
> polluted *indistinguishably*: auto-created workers are `temporary` and the
> Workers page filters on type. The trade was deliberate — a register that
> needs filtering is recoverable, a fragmented history is not.
>
> **What still holds from P1:** attendance remains immutable, promotion
> remains an explicit user-confirmed act (it just updates instead of
> inserting), and headcount groups still create nobody.

**There must never be code that assumes "attendance creates workers."**
Recording attendance never silently mutates the workforce register. Promotion
into the register is always an explicit, separately-confirmed act.

Rationale: attendance is immutable historical fact; the workforce register is
current mutable reference data. Letting one write the other makes history
depend on the present, and pollutes the register with one-off names.

### P2 — Universal operational pattern

Every operational module in Mesiri gives the user the same experience,
end to end:

```
Module → Action → Project → Site → Capture → AI Understanding
       → Preview → Confirmation → Save
```

of which the last four are the non-negotiable core:

```
AI Extraction → Structured Preview → User Confirmation → Persistence
```

The Labour workflow **must never bypass this**. Nothing is persisted before an
explicit confirmation.

This is why Labour must behave like Material and Expense rather than inventing
its own shape: a supervisor who has learned one module has already learned
this one. Consistency across modules *is* the feature.

### P3 — Temporary workers are first-class

Temporary workers are expected to be **30–60% of construction attendance**,
not an edge case. They are modelled as a proper worker type with full support
throughout matching, preview and persistence — never as a degraded or
special-cased path.

### P4 — Workers are never matched by name alone

Matching produces a **confidence score** from multiple signals:

```
name + trade + contractor + previous attendance + project + site → confidence
```

Low confidence → **ask the user**. Never guess, never auto-merge.

**A trade mismatch lowers confidence; it does not prove a different person.**
Trades genuinely change on site — a helper is promoted to mason, someone lays
brick one day and does carpentry the next. Treating a mismatch as
disqualifying would quietly create a second register entry for the same
person and split their history in two. Treating it as the same person is
equally wrong. So a changed trade *always* asks, however much else
corroborates it, and the question names both trades: *"the register says
mason, today's report says carpenter — same worker with an updated trade, or
a different Ravi?"*

The goal is to **ask fewer questions, not better ones.** If supervisors are
being asked on most reports, the fix is stronger corroborating signals — never
a lower threshold.

### P5 — Attendance is immutable

Never overwrite a previous attendance record. Corrections are new records, not
mutations. This is why 0120's one-row-per-site-per-day constraint is
disqualifying.

### P6 — Reuse, don't duplicate

Images reuse the existing object-storage + attachments pattern exactly as
receipts do. No special-case image pipeline. Where Material/Expense already
share a shape, extract it rather than writing a third copy (see §7).

### P7 — Activity is the connective tissue

Attendance optionally links to **activity / work item / construction stage**
even though V1's UI does not expose all of it.

This is more important than it looks. Activity is what eventually joins every
operational module together:

```
                Activity
                   │
      ┌────────────┼────────────┐
   Materials    Labour      Expenses
```

Once all three reference the same activity, questions like *"what did slab
casting actually cost us?"* become answerable across material, labour and
spend at once. That is the foundation of construction analytics, and it is
only possible if the link is captured at the moment of recording — it cannot
be reconstructed afterwards.

**Model the relationship now; do not build the features on top of it now.**
Capturing an activity must stay optional and must never slow down recording
(see P9).

### P10 — Accept the detail the user can give today

**Mesiri accepts the level of detail the user can provide today, rather than
forcing a single reporting style.**

One supervisor sends names::

    Ravi - Mason
    Arun - Helper

Another sends counts::

    12 Helpers
    4 Masons

A third sends both in one message. All are valid. Requiring names would push
away everyone who doesn't have them to hand; accepting only counts would
throw away worker history that other sites *can* provide.

So a line is **either** a named person **or** a headcount group, and one
attendance may freely mix them. There is no "mode" to choose and no second
workflow — the difference is data, not flow.

This principle is not Labour-specific. It is how every Mesiri module should
treat partial information.

### P8 — Future integration readiness

Labour **does not implement** Timeline, Analytics, Image Gallery, Dashboard,
Reports or AI Search in V1.

However, all attendance data must be stored such that those modules can
consume it later **without requiring changes to the Labour module**.

Practically, this means: store the facts, with their scope (organization,
project, site, date, activity) and provenance (who recorded it, from which
message, with which attachments) — because that is what every future consumer
will need, and retrofitting provenance onto historical records is impossible.

**Expected future consumers** — documented so their needs are anticipated, not
so they are built:

| Consumer | What it will want from Labour |
|---|---|
| Timeline | attendance events, scoped to project/site, with a human summary |
| Analytics | headcount and cost, grouped by trade / activity / period |
| Image Gallery | attendance sheet photos via the shared attachment shape |
| Reports | cost roll-ups, exportable |
| AI Search | attendance answerable in natural language, like inventory is today |
| Payroll | days worked per worker — **explicitly not V1**, but the shape must not preclude it |

### P9 — Optimize for speed of recording, not completeness of information

The person using this is standing in the sun, on a site, and is busy.

**If recording attendance takes five minutes, it will not be used. If it takes
thirty seconds, it will be used every day.**

Every design decision should be weighed against this. Prefer a fast capture
with a few unknowns over a thorough capture that nobody completes. Optional
fields stay genuinely optional. Never ask a question the system can answer
itself.

**Known tension with P4.** "Never guess, always ask" and "be fast" pull against
each other: asking about every uncertain worker would make a 10-worker
attendance unusable. The resolution is that **P4 governs correctness, P9
governs how often it triggers** — invest in matching being confident enough
that asking is rare, rather than in making the asking pleasant. If a
supervisor is answering questions on most reports, matching is too weak; fix
the matching, do not relax the rule.

---

## 3A. Definition of Done — when is Labour V1 finished?

The finish line. Everything else in this document describes *how*; this
section defines *when we stop*.

**Labour V1 is complete when all of the following are true:**

| # | Criterion | Verified by |
|---|---|---|
| 1 | A site engineer can record attendance entirely via WhatsApp | Real message on production, end to end |
| 2 | Project and site selection works, reusing the existing gate chain | Same gates Material uses; no Labour-specific selection UI |
| 3 | AI extracts labour details from **text, voice, and images** | One test per input path producing the same structured result |
| 4 | Workers are matched correctly, never by name alone | Confidence model (P4); `Ravi (Mason)` ≠ `Ravi (Painter)` |
| 5 | Temporary workers are fully supported as first-class | Recorded without entering the register; promotion is a separate explicit act |
| 6 | The user receives a structured preview before anything is saved | P2 |
| 7 | The user confirms before saving; nothing persists without it | P2 |
| 8 | Attendance is stored, append-only | P5 — a second report for the same site and day is a second record |
| 9 | Attendance images are attached to the record | Via the shared attachment shape (ADR-L3) |
| 10 | Stored data is **future-ready** for Timeline, Analytics, Image Gallery and AI Search | P8 |

**Note criterion 10 carefully: future-*ready*, not implemented.** Timeline,
Analytics, Gallery, Dashboard and AI Search are explicitly *not* built in V1.
The test is whether they could later be built against the stored data
*without changing the Labour module*.

**Not part of Done:** dashboard UI, CSV/Excel import, payroll, cost reports,
any of §Deferred. Those are follow-on work and do not gate V1.

---

## 4. Implementation order

**Deliberately not database-first.** Mesiri is architected around the
assistant, so the workflow defines what the database needs — not the reverse.

```
Business Model
   ↓
Domain Model
   ↓
Contracts
   ↓
Workflow
   ↓
Persistence
   ↓
Repositories
   ↓
Application Layer
   ↓
WhatsApp Flow
   ↓
Tests
```

Tests are listed last as a phase, but each layer ships with its own tests as
it is written; the final phase is end-to-end coverage.

---

## 5. Architecture decisions (ADRs)

### ADR-L1 — Supersede the 0120 labour tables rather than extend them

**Status:** Accepted
**Context:** 0120's tables cannot express append-only history or a workforce
register (see §2.2). They are unused by any code.
**Decision:** Leave 0120's tables in place (preserving migration history; no
destructive drop) and create the real Labour schema alongside. Do not alter
0120's tables.
**Consequences:** Two unused tables remain in the schema. Accepted as the cost
of preserving migration history and avoiding any risk to environments whose
contents were not inspected. A later cleanup migration may drop them once
production is confirmed empty.
**Rejected alternatives:**
- *Extend 0120* — the aggregate-headcount shape fights the named-worker model
  at every layer, and dropping a uniqueness constraint on a live table is
  riskier than never needing one.
- *Drop and replace* — destructive; production contents were not verified from
  this machine (no DB access), so deletion cannot be justified.

### ADR-L2 — Workforce register is its own domain concept

**Status:** Accepted
**Decision:** The workforce register lives in `domains/workforce/` (the empty
package already reserved for it), separate from attendance recording.
**Consequences:** Enforces P1 structurally — the register can be read by
attendance, but attendance code has no write path into it except an explicit
promotion command.

### ADR-L3 — Attendance images reuse the attachment pattern

**Status:** Accepted
**Context:** `expense_attachments` stores `media_object_key` + `attachment_type`
against the parent record; the object itself lives in existing object storage.
**Decision:** Labour uses the identical shape for attendance sheet photos.
**Consequences:** Timeline and Image Gallery integration come for free, since
they consume the same attachment shape.

### ADR-L4 — _(reserved: shared operational abstraction — see §7, pending approval)_

---

## 6. Data model (design — not yet implemented)

> Driven by the workflow, per §4. Recorded here after the workflow design so
> the reasoning is traceable; implemented in Phase 4.

### 6.1 Workforce register

Operational fields only. **Not an HR record.**

| Field | Notes |
|---|---|
| `name` | |
| `trade` | mason, painter, helper, … |
| `worker_type` | `permanent` \| `temporary` \| `contractor` |
| `default_daily_wage` | nullable |
| `contractor` | nullable; free text or FK — see open question Q2 |
| `status` | active / inactive |

Nothing beyond operational requirements. No address, no ID documents, no
next-of-kin, no bank details.

### 6.2 Attendance

Append-only. One record per report, **not** per site-day.

| Field | Notes |
|---|---|
| `date` | the day worked |
| `project`, `site` | scope |
| `attendance_image` | optional but strongly recommended; via attachments |
| `workers` | line items — see 6.3 |
| `notes` | |
| `recorded_by`, `timestamp` | provenance |
| `activity` / `work_item` / `stage` | optional; P7 |

### 6.3 Attendance line items

Each links to **either** a registered worker **or** a temporary worker
captured inline. Carries trade and daily wage *as recorded at the time* — a
historical record must not change when the register is later edited.

---

## 7. Proposed shared abstraction — **awaiting approval before implementation**

Reconnaissance found that Material and Expense already duplicate the same
execution scaffolding almost exactly. Adding Labour would create a third copy.

**Evidence of duplication:**

| File | Material | Expense | Difference |
|---|---|---|---|
| `dispatcher.py` | `MaterialExecutionDispatcher` | `ExpenseExecutionDispatcher` | class name, log prefix, and the handler's method name (`handle` vs `handle_confirmed`) |
| `recovery.py` | `recover_confirmed_instances` | same, "mirrors materials/recovery.py exactly" per its own docstring | workflow-key set |
| `repository.py` | `MaterialExecutionRepository` | `ExpenseExecutionRepository` | command type only; identical three abstract methods |
| `resolution.py` | `ResolutionResult` + `MaterialResolver` | `ResolutionResult` + `ExpenseCategoryResolver` | `ResolutionResult` is **defined twice, identically** |

**Proposal:** extract a small `application/_operational/` package providing:
- a generic `ExecutionDispatcher[TCommand]` wrapping any handler
- a generic `ExecutionRepository[TCommand]` port (the three abstract methods)
- one shared `ResolutionResult`
- one shared `recover_confirmed_instances(db, handler, workflow_keys)`

and normalise the handler entry point to a single method name.

**Benefit:** Labour adds no new scaffolding; Material and Expense each shed a
file's worth of near-duplicate code; the `handle`/`handle_confirmed`
inconsistency disappears.

**Risk:** touches two working modules. Mitigated by their existing test
coverage, and by doing it as a separate, isolated commit *before* Labour is
built on top.

**Status:** ✅ **Implemented** 2026-07-26 as an isolated commit before Labour.

### 7.1 What was actually extracted — and what wasn't

**Correction to the original proposal.** It claimed `ResolutionResult` was
"defined twice, identically". That was wrong: reading only the class name and
assuming. The three are genuinely different and share only `reasons`:

| Module | Payload |
|---|---|
| materials | `material_id`, `unit_id`, `reasons` |
| expenses | `category_id`, `reasons` |
| finance | `target_account_id`, `reasons` |

A base class for one common field would be ceremony, not reuse. **Not
extracted.**

**Extracted** into `backend/src/mesiri/application/shared/execution.py`:

1. `OperationalExecutionDispatcher` — the dispatcher failure contract. This is
   load-bearing: by the time an exception reaches the dispatcher the Handler's
   transaction has already rolled back, so reporting `FAILED` rather than
   raising is what leaves the workflow at `CONFIRMED` and recoverable. Having
   that right in one module and subtly wrong in another stays invisible until
   a crash.
2. `recover_confirmed_instances` — the replay sweep, whose bodies were
   byte-identical across modules.

**Also not extracted:** the execution repository ports. Same three method
names, but each typed to its own command; a generic port would need a TypeVar
and would document the duplication rather than remove it.

**Design note.** Per-module dispatchers remain as thin subclasses declaring a
log label and how to invoke their handler. That indirection exists because the
handlers genuinely disagree — Material exposes `handle()`, Expense and Finance
expose `handle_confirmed()`. Renaming one would ripple through handlers,
recovery and tests in a module the refactor otherwise leaves alone; one line
per module keeps the blast radius at zero.

**Result:** 124 lines removed, 67 added across five files. 1046 tests passing,
behaviour unchanged. **Labour adds no execution scaffolding of its own.**

Merged with an incoming change from Ilan (`e4f6cf5`) that moved
`list_confirmed_by_workflow_keys` from the assistant package into
`mesiri.infrastructure.postgres` to fix a `ModuleNotFoundError`; the shared
module adopts that new path.

---

## 8. Phase checklist

Update as work proceeds. `[x]` = done and pushed.

### Phase 0 — Reconnaissance & design
- [x] Reverse-engineer Material module end to end
- [x] Reverse-engineer Expense module end to end
- [x] Identify existing Labour foundations
- [x] Identify 0120 incompatibilities
- [x] Identify shared-abstraction opportunities (§7)
- [x] Master implementation plan (this document)
- [x] Dashboard plan document (`labour-dashboard-plan.md`)
- [x] Shared-abstraction proposal approved and implemented (§7.1)

### Phase 1 — Business & domain model
- [x] Worker types, trades, statuses as domain enums
- [ ] Workforce entity + invariants
- [ ] Attendance entity + line items + invariants
- [x] Worker-matching confidence model (P4), incl. trade-change handling
- [ ] Domain validation rules
- [x] Unit tests (29)

### Phase 2 — Contracts
- [x] `DraftActionType.RECORD_LABOUR_ATTENDANCE`
- [x] `RecordLabourAttendanceCommand` + `LabourAttendanceLine`
- [x] Contract tests (20)

### Phase 3 — Workflow
- [x] `workflows/labour_update/` graph + nodes
- [x] Worker-matching node (asks on low confidence — P4)
- [x] Temporary-worker handling (P3)
- [x] Preview / confirmation node (P2)
- [x] Register in `workflows/registry.py`
- [x] Unit tests (35) + LangGraph integration tests (5)

See §13 for the one structurally new thing Phase 3 introduced (a re-entrant,
variable-length slot loop) and why it was done that way.

### Phase 4 — Persistence
- [x] Migration: workforce register (`workforce_workers`)
- [x] Migration: attendance + line items + attachments
      (`labour_attendance_reports` / `_lines` / `_attachments` — new names,
      0120 untouched, ADR-L1)
- [ ] Duplicate-image detection support — deferred; `labour_attendance_attachments`
      deliberately mirrors `expense_attachments` exactly (no hash column) since
      Q3 (exact-hash vs perceptual) is still open. Add the column when Q3 is
      resolved, not speculatively.
- [x] Cascade-delete wiring (mirror 0361) — `ON DELETE CASCADE` set directly in
      migration 0371 on all four tables' path to `organizations.id`; no
      changes to `admin/router.py` needed (`delete_organization` already
      relies purely on the DB cascade). `test_organizations_cascade_delete_schema.py`
      extended to cover the two child tables.

Migration 0371. See §14 for the full schema explanation and the two
decisions the user approved before this was built (Attendance ID, `recorded_via`).

### Phase 5 — Repositories & application layer
- [x] Repository port + Postgres implementation
      (`application/labour/repository.py`, `infrastructure/postgres/repositories/labour_execution.py`)
- [x] Mapper, handler, dispatcher, recovery (`application/labour/`) —
      dispatcher and recovery reuse the shared scaffolding
      (`application/shared/execution.py`) added before Labour started, so
      neither is new code, only two thin subclasses
- [x] Domain validation (`domains/workforce/validation.py`, mirrors
      `domains/materials/validation.py`)
- [x] Idempotency — `idempotency_keys` shared table, identical claim pattern
      to Material
- [x] Fakes for testing (`application/labour/fakes.py`)
- [x] Tests — mapper (17), domain validation (8), handler (6), e2e (6, real
      dispatcher now — the temporary stub and its test were deleted)
- [x] `runtime/dependencies.py` wired to the real `LabourExecutionDispatcher`
      — **the stub is gone.** Confirming an attendance now actually writes
      `labour_attendance_reports`/`_lines`/`_attachments`.
- [x] Bonus, not originally scoped for this phase: **`recorded_via`** now
      carries the real input modality (text/voice/image) end to end, from
      `UnderstandingResult.input_modality` at canonicalization through to the
      stored row — see §14.3. Needed doing now because the mapper needed
      something to put in that column.

### Phase 6 — WhatsApp flow
- [x] Canonicalization mapping + required fields — done in the earlier
      "read named workers" work (`canonicalization/builder.py`'s
      `_normalize_labour_fields`) and extended this phase for `recorded_via`
- [x] Planner routing — pre-existing (§2.1's reconnaissance finding, verified
      still true: `planner/routing.py` already maps
      `LABOUR_ATTENDANCE_REQUESTED` -> `WorkflowKey.LABOUR_ATTENDANCE`)
- [x] Extraction prompt: named workers, not just headcount — done earlier
- [x] Image attachment path — reuses the existing `IMAGE_PURPOSE_ROWS`
      mechanism ("Attendance" row, done earlier) end to end through to
      storage: photo -> `media_object_key` -> mapper's
      `_attachment_object_keys` -> `labour_attendance_attachments` row
- [x] Runtime wiring (`dependencies.py`) — the real `LabourExecutionDispatcher`
      is registered; the temporary stub is deleted
- [x] End-to-end tests (fakes-backed, no live DB — see Phase 4/5's same
      caveat: **run against a real database before calling Phase 6 fully
      verified**)

### Phase 7 — Platform integration
- [ ] Timeline events
- [ ] Image Gallery
- [ ] AI context / searchability
- [ ] Analytics data exposure

### Deferred (documented, not built)

**Dashboard implementation is intentionally postponed.** During Labour
implementation, the only obligation is that the backend exposes sufficient
data for a future dashboard — so that building the UI later requires
**minimal backend change**. No frontend work of any kind is in scope.

- [ ] Web Dashboard — fully specified in `labour-dashboard-plan.md`
- [ ] Control Panel UI, Mobile UI, Analytics UI, Timeline UI, Gallery UI
- [ ] CSV / Excel import
- [ ] Payroll, cost reports, productivity — separate modules, not extensions

---

## 9. Open questions

| # | Question | Status |
|---|---|---|
| Q1 | Should the AI extract named workers from a photographed attendance sheet, or is headcount + trade sufficient for V1? | **Partly addressed 2026-07-26 — still the top risk.** The path a photo travels was audited and four defects fixed (vision had no attendance-sheet classification and would likely reject a legible roster as unreadable; it asked for flat key/values a 15-row roster cannot fit; structure was destroyed by `repr` in the hand-off to extraction; and the user's own "Attendance" tap was never passed to the vision model). Harness + method + decision thresholds are in `labour-attendance-photo-eval.md`. **The measurement has NOT been run — it needs 10–15 real photos. No accuracy figure exists; do not quote one.** |
| Q2 | Is `contractor` free text or a proper entity? | **Resolved 2026-07-26: free text in V1.** Site vocabulary is inconsistent ("Kumar Team", "ABC Contractors", "Local Labour", "Self"), and normalizing it now adds complexity without operational gain. Converting free text into a Contractor entity later is straightforward; the reverse is not. |
| Q3 | Should duplicate-image detection be exact-hash only (cheap, reliable) or perceptual/near-duplicate (catches re-photographs, more false positives)? Spec says "nearly identical", implying perceptual. | Open |
| Q4 | Is a daily wage recorded per attendance line, or always inherited from the register? Recording it per line preserves history correctly (P5) but allows drift. **Recommend: inherit as default, store the value used.** | Open |
| ~~Q5~~ | **Resolved 2026-07-26: support both, mixed in one report.** See P10. A line is either a named worker or a headcount group; `headcount=1` plus a name is one person, `headcount=12` without a name is a group. ~~Should V1 support headcount-only attendance when individual names aren't available — e.g. "10 helpers, 4 masons, 2 painters"? Many sites genuinely work this way, especially with contractor-supplied labour. This is also the fastest possible capture (P9), and notably it is exactly what the *existing* 0120 table and the current AI extraction prompt already assume. Supporting both named and headcount-only reports in one model is a real data-model decision, not a UI one — a line item would need to represent either a person or a count. ~~ | ✅ Resolved |

---

## 10. Known risks

| Risk | Impact | Mitigation |
|---|---|---|
| AI extraction of named workers from photos is unreliable | High — it is the primary input path | Test early with real sheets; fall back to headcount + manual naming if accuracy is poor |
| Worker matching produces false merges | High — corrupts historical records | P4 confidence model; never auto-merge on low confidence |
| Scope: this module is ≈ Material + Expense combined | Schedule risk against 9 Aug MVP | Phased delivery; Phases 1–6 give a usable WhatsApp flow; dashboard deferred by design |
| Shared-abstraction refactor destabilises Material/Expense | Medium | Isolated commit, before Labour; rely on existing test coverage |
| Temporary workers pollute the register | Medium | P1 — promotion is explicit and separately confirmed |

---

## 11. Change log

| Date | Change |
|---|---|
| 2026-07-25 | Document created. Phase 0 complete: reconnaissance, ADR-L1 to L3, principles P1–P7, shared-abstraction proposal (§7) pending approval. |
| 2026-07-25 | Merged 34 incoming Finance commits. Added §2.4: attendance already has a reserved slot in the image-purpose picker, duplicate-detection precedent is field-based (image hashing still to build), attachment/gallery paths now test-covered. 1046 tests passing. |
| 2026-07-26 | **Phase 1 (domain) and Phase 2 (contracts) complete.** Workforce vocabulary + worker matching with confidence scoring; `RecordLabourAttendanceCommand` with lines that are either a named worker or a headcount group. Four decisions taken: shared abstraction approved, Q5 resolved (support both, mixed — now P10), Q2 resolved (contractor free text), and P4 amended so a trade mismatch lowers confidence rather than proving a different person. 1091 tests passing. |
| 2026-07-26 | Shared execution scaffolding extracted (§7.1) as an isolated commit before Labour: dispatcher failure contract + recovery sweep. Corrected the earlier wrong claim that `ResolutionResult` was duplicated — it is not, and was left alone. 124 lines removed, 1046 tests passing. |
| 2026-07-26 | **Phase 3 (workflow) complete.** `workflows/labour_update/` graph + nodes, registered under `WorkflowKey.LABOUR_ATTENDANCE`. Introduced the module's one structurally new pattern: a re-entrant matching node that asks about one worker per pass, since Labour is the first workflow whose number of questions depends on the message (§13). 35 unit tests + 5 LangGraph integration tests. Lint clean. |
| 2026-07-26 | Product-clarity pass following design review. Added §3A **Definition of Done** (the finish line, 10 criteria), **P8 Future integration readiness** with expected-consumer table, **P9 Optimize for speed of recording** including its acknowledged tension with P4, strengthened **P7** to name Activity as the connective tissue between all operational modules, expanded **P2** to the full Module→Action→Project→Site→Capture→AI→Preview→Confirm→Save pattern, added **Q5** (headcount-only attendance — flagged decide-early as it affects the domain model), and made the dashboard deferral explicit. No architectural changes; scope unchanged. |

---

## 12. Resume here — state as of 2026-07-26

**Read this first if you are picking this up in a new session.**

### Done

| Phase | What landed | Commit |
|---|---|---|
| 0 | Reconnaissance, this plan, `labour-dashboard-plan.md` | `42191af`, `931508d` |
| — | Shared execution scaffolding (§7.1) — extracted *before* Labour so it adds no scaffolding of its own | `ddb20dd` |
| 1 | `domains/workforce/workers.py` + `matching.py`, 29 tests | `08e3cee` |
| 2 | `DraftActionType.RECORD_LABOUR_ATTENDANCE`, `RecordLabourAttendanceCommand`, 20 tests | `2f78ca9` |
| 3 | `workflows/labour_update/` graph + nodes, registered; 35 unit + 5 integration tests | _(local commit — not yet pushed)_ |

**Verified after Phase 3: 1138 passing, 0 failing, lint clean across the repo.**

### Run the suite on a machine that can actually run it

This cost real time on 2026-07-26 and is worth not repeating. The suite was
initially reporting *9 failures and 15 collection errors*, all of which
looked pre-existing and unrelated — and all of which were **missing optional
dependencies**, not code problems. Worse, the missing dependencies were
*hiding a genuine regression* (see below).

On a fresh Windows machine, install these before trusting any result:

```
pip install --user passlib bcrypt asyncpg langgraph google-genai tzdata
```

- `passlib`, `bcrypt`, `asyncpg` — 43+ modules fail to *collect* without them
- `langgraph` — optional `workflow` group; without it **every graph
  integration test silently skips**, including Labour's
- `google-genai` — the *new* SDK. Installing `google-generativeai` (the
  legacy package) does **not** satisfy `import google.genai` and leaves 7
  Gemini adapter tests failing
- `tzdata` — Windows ships no timezone database, so `ZoneInfo("Asia/Kolkata")
  raises and the greeting test fails locally while passing on CI (Linux)

**The lesson, stated plainly: a skipped test is not a passing test, and a
collection error is not a "pre-existing failure".** Both were masking real
signal here.

### What Phase 3 built

`apps/whatsapp-assistant/src/workflows/labour_update/`:

- **`nodes.py`** — `match_workers`, `build_draft`, `request_confirmation`.
- **`graph.py`** — `START -> match_workers -> (ask_slot -> END | continue)
  -> build_draft -> request_confirmation -> END`.
- Registered in `workflows/registry.py` under `WorkflowKey.LABOUR_ATTENDANCE`
  (the key already existed; until now it resolved to `None` and the user got
  "not supported yet").

Registering the graph also flipped `labour_update` to **implemented** in the
admin System Graph, which derives that flag live from
`workflows.registry.is_implemented()` (`admin/system_graph_router.py`). The
`labour.attendance` node now renders as built rather than "not built yet",
and `test_system_graph_semantic_types.py` was updated to match. Equipment and
general-site-update remain the only routed-but-unbuilt workflows.

The design and its one genuinely novel element are documented in §13 — read
that before changing `match_workers`.

### Not started

**Phase 4 onwards.**

Phase 4 persistence (migration — **do not touch 0120's tables**, see ADR-L1),
Phase 5 repositories + application layer, Phase 6 WhatsApp wiring
(canonicalization mapping, planner routing, extraction prompt rewritten for
named workers *and* headcount, image attachment via the existing
`IMAGE_PURPOSE_ROWS` mechanism), Phase 7 platform readiness.

### What Phase 3 leaves for its callers (mostly Phase 6)

The graph is complete and correct but is not yet *fed* by anything. Three
seeding obligations, none of which the graph can do for itself because a node
must never query a repository (`workflows/runtime.py`):

1. **`collected_fields['lines']`** — AI extraction must produce the list-of-
   lines shape (§13.1). Today the Gemini adapter's `labour_update` slot
   extracts flat `headcount, trade, hours, contractor, project_name`, which
   cannot express named workers at all. **This is the single biggest
   remaining piece of Labour**, and it is where open question Q1 gets
   answered.
2. ~~**`collected_fields['worker_candidates']`**~~ — ✅ **done 2026-07-26.**
   `runtime/workforce_query.py` + `_seed_worker_candidates` in
   `inbound_journey.py`, mirroring `_seed_account_candidates`. Reads are
   **stubbed** (`StubWorkforceQueryService`) since the register has no tables
   until Phase 5; swapping in the Postgres reader is one line in
   `dependencies.py`.

   The stub's default is an **empty register**, deliberately. A stub that
   returned plausible workers would make matching *look* like it works while
   attaching real attendance to people who don't exist — the corruption P4
   exists to prevent, arriving through test scaffolding. To exercise matching
   before Phase 5, set an explicit roster via `MESIRI_LABOUR__STUB_WORKERS`
   (JSON; see the module docstring). Opt-in, visible in config, logged at
   WARNING when active.

   Also note: a headcount-only report never reads the register at all —
   nobody is named, so there is nothing to match (P9/P10).
3. **`collected_fields['project_name']` / `['site_name']`** — optional, for
   the confirmation preview. Omitted rather than showing a raw UUID.

### Working agreements in force

- **Do not `git push` unless explicitly asked.** Commit locally and say what
  is ready. (Ilan was stabilising the CI/deploy pipeline on 2026-07-26.)
- **Pull often** — this repo takes frequent concurrent commits from Ilan.
  Check for migration-number collisions on every pull; it has already
  happened once.
- Run the full suite the way CI does (from a scratch dir, `-P`,
  `--rootdir`) — running it from the repo root makes the repo's own
  `platform/` directory shadow Python's stdlib `platform` module.
- Explain before implementing; plain language first, technical second.
- Record finished work in Linear, assigned to ALAN RAJ, marked Done.

### Still open

- **Q1** — can the AI reliably extract *named* workers from a photographed
  attendance sheet? Untested, and it is the least predictable part of the
  build. **Test with a real sheet early in Phase 6.**
- **Q3** — image duplicate detection: exact-hash or perceptual? The existing
  precedent (`find_potential_duplicate`) is field-based, not image-based.
- **Q4** — wage per line vs inherited. Current design stores the value used
  on the line so history cannot drift; flagged to Alan, not yet confirmed.

---

## 13. Phase 3 design — the worker-matching loop

Recorded here rather than only in code comments because it is the one place
Labour departs from an established platform pattern, and a future session
that doesn't understand *why* will very reasonably try to "fix" it back into
the shape every other workflow uses.

### 13.1 The input shape

`collected_fields['lines']` is a list of dicts, each **either** a named person
**or** a headcount group (P10), freely mixed in one attendance:

```python
{"worker_name": "Ravi", "trade": "mason",  "headcount": 1,  "daily_wage": 800}
{"worker_name": None,   "trade": "helper", "headcount": 12, "daily_wage": 600}
```

The node adds two keys as it works: `worker_id` (the resolved register entry,
or `None` for a temporary worker) and `worker_match_resolved` (bookkeeping,
stripped in `build_draft` so it never reaches the `extra: forbid` command).

### 13.2 The problem: a variable number of questions

Every other v1 workflow asks a **fixed** number of questions.
`expense_capture` has exactly two slots — `account_id` and
`duplicate_confirm` — each its own node with its own conditional edge, each
keyed on a constant slot name.

Labour cannot work that way. One attendance may name seven workers, of whom
any number between zero and seven are ambiguous, and **the graph is compiled
once and cached** (`registry.py` — "a WhatsApp message must never trigger a
graph recompilation"). The shape of the graph therefore cannot depend on the
message.

Compounding it: the graph is compiled **without a checkpointer** and is
re-invoked from scratch on every inbound message. The only thing that
survives between the question and the answer is `collected_fields`, persisted
as `WorkflowState.v1`.

### 13.3 The resolution: one re-entrant node, one question per pass

`match_workers` is a single node that, on each pass:

1. Applies the answer to the previous question, if one is pending.
2. Scans the lines **in order**, resolving everything it can silently —
   `AUTO_MATCHED` stamps the `worker_id`, `NO_MATCH` marks a temporary worker.
3. Stops at the first `ASK_USER` line, emits the question, and ends the pass.

The line being asked about is encoded **in the slot name** —
`worker_match:2` — because `awaiting_slot` is the only routing signal both
the graph and the runtime can see. The graph's conditional edge therefore
**prefix-matches** rather than comparing a constant, which is what lets one
edge serve every line. It is still slot-*specific* (a stale `account_id`
slot does not trigger it), which is the bug expense_capture's
`_route_after_account_resolution` documents.

**Why resolve-then-ask, rather than asking about each line as it is reached:**
this is P9 made concrete. A ten-worker report with nine confident matches
asks exactly one question. Asking per line as encountered would be simpler to
write and unusable on site.

**Why it terminates:** every pass either records a decision on at least one
line or asks about one. There is no state in which it does neither.

**Why the option list is recomputed on resume rather than persisted:**
`match_worker` is pure and the candidate list is unchanged between passes, so
re-scoring reproduces exactly the list the user was shown. Persisting it
would be a second source of truth that could drift.

### 13.4 Two rules the node enforces that are easy to break later

- **"Someone new" is always the last option.** Without it the user cannot say
  "none of these", and a temporary worker becomes unrecordable rather than
  first-class (P3). Choosing it sets `worker_id = None` and writes **nothing**
  to the register (P1).
- **Option labels are bare names.** A WhatsApp list row title over 24
  characters makes the send side drop the entire list back to plain text
  (`runtime/inbound_journey.py`'s `_render_reply`). Match *reasons* therefore
  go in the prompt body, never the label. Two candidates sharing a name are
  disambiguated by trade — the one case where a bare name genuinely cannot
  identify the choice.

### 13.5 The one architectural exception, stated plainly

`nodes.py` imports `mesiri.domains.workforce.matching` — **the first workflow
node to import backend domain code.** The rule nodes obey is "no I/O, no SQL,
no repository access"; `match_worker` is a pure scoring function over
candidates the *caller* seeded, so it breaks none of that. The alternative
considered and rejected was having the runtime pre-compute match results and
seed those too, which would split one loop across two layers for no gain in
purity.

### 13.6 A calibration finding worth knowing

Phase 1's scoring means **a trade mismatch does not always produce a
question.** "Ravi, carpenter" against a registered "Ravi Kumar, mason" scores
below the ask threshold entirely (partial name 0.30, mismatch −0.15,
seen-on-site +0.15 = 0.30 < ASK 0.35) and resolves to a **temporary worker**.

That is the safe outcome — it keeps two histories separate, which a later
promotion can still merge, whereas a wrong merge cannot be undone — but it
is easy to misread P4 as "a trade mismatch always asks". It does not; the
mismatch *lowers confidence*, and only an otherwise-strong match lands in the
ask band. Both behaviours are pinned by tests
(`test_trade_change_question_names_both_trades` and
`test_partial_name_with_changed_trade_is_a_new_worker`).

---

## 14. Phase 4 — the database schema, and why it's shaped this way

Approved by the user 2026-07-26 after a plain-language design review before
any code was written. Recorded here so a future session doesn't have to
re-derive it.

### 14.1 Two tables that must never write to each other

**`workforce_workers`** — the editable register. Name, trade, worker_type
(permanent/temporary/contractor), default_daily_wage, contractor (free text —
Q2), status (active/inactive). No address, ID documents, bank details, next
of kin — operational reference data, not an HR record.

**`labour_attendance_reports`** — one immutable row per WhatsApp report.
Deliberately **not** unique on (site_id, occurred_date) — that constraint is
exactly what made 0120 unusable. A second report for the same site and day is
a second row.

The only relationship between them is `labour_attendance_lines.worker_id`,
nullable, read-only from the attendance side. There is no write path from
attendance into the register anywhere in the schema — principle P1 enforced
structurally, not by convention.

### 14.2 Table names had to change

The old 0120 tables are named `labour_attendance` / `labour_attendance_entries`
and are left in place, untouched (ADR-L1 — no destructive drop, unverified
production contents). So the new tables use different names entirely:
`labour_attendance_reports`, `labour_attendance_lines`,
`labour_attendance_attachments`. The two schemas can never collide or be
mistaken for each other.

### 14.3 Two additions from the 2026-07-26 design review

The user approved the design with two requirements, both incorporated:

1. **Every report gets its own unique Attendance ID.** This is the table's
   UUID primary key — already the plan's design, made explicit in the
   migration's comments as *the* Attendance ID. Went further than asked:
   added `corrects_report_id`, a nullable self-reference on
   `labour_attendance_reports`, so a future correction workflow can point a
   new report back at the one it corrects **without either row being
   mutated**. No correction workflow exists yet — the column is reserved
   because provenance cannot be added retroactively (P8), and this was the
   cheapest possible moment to reserve it.

2. **Store how the report was recorded.** `recorded_via` on
   `labour_attendance_reports`: `whatsapp_text` / `whatsapp_voice` /
   `whatsapp_image` / `dashboard`. Not a foreign key to the assistant's
   internal `InputModality` enum — dashboard entry has no modality, and this
   column must never need a migration just because the application side adds
   a new capture path.

### 14.4 Line-level detail

`labour_attendance_lines`: `worker_id` (nullable — temporary worker or
headcount group), `worker_name`, `worker_name_original` (non-Latin source
script, per the Malayalam work), `trade`, `headcount`, `daily_wage`,
`contractor`, `activity` (P7, free text — no activities table exists yet).

`trade` and `daily_wage` are **copied onto the line**, never read from
`workforce_workers` at query time — this is P5's corollary. If a line
pointed at the register instead, raising a worker's wage next month would
silently change what last month's attendance appears to have cost.

Check constraints: `headcount > 0`, `daily_wage IS NULL OR daily_wage >= 0`.

### 14.5 Attachments

`labour_attendance_attachments` is intentionally byte-for-byte the same
shape as `expense_attachments` (ADR-L3) — same columns, same audit pattern —
so Timeline and Image Gallery integration come for free later by consuming
an attachment pattern they already consume for receipts. No image-hash
column: Q3 (exact-hash vs perceptual duplicate detection) is still open, and
speculatively adding a column for an undecided algorithm would be building
ahead of a decision that hasn't been made. Add it when Q3 resolves.

### 14.6 Cascade delete

All four tables get `ON DELETE CASCADE` on their path to `organizations.id`
directly in migration 0371 — `workforce_workers` and
`labour_attendance_reports` from their own `organization_id`; the two child
tables from their parent `report_id`. `admin/router.py`'s
`delete_organization` needed **zero changes**: it already does a bare
`DELETE FROM organizations` and relies entirely on the DB-level cascade
(0361). `test_organizations_cascade_delete_schema.py` was extended with the
two child-table entries so this stays guarded automatically.

### 14.7 Verification without a live database

No Postgres was available in this session. Verified instead:

- Python syntax and the full down_revision chain (0371 is the sole new head
  off 0370, no branch).
- No index/constraint name collisions anywhere in the migration history.
- **Real Postgres DDL**, rendered via `alembic upgrade 0370:0371 --sql` and
  `alembic downgrade 0371:0370 --sql` (offline mode) — both produced clean,
  valid SQL for every table, index, FK and check constraint. This is
  materially stronger than a Python parse check.
- `test_organizations_cascade_delete_schema.py` updated but not run (needs a
  live DB — `pytest.mark.integration`, skipped by default). **Run this
  against a real database before considering Phase 4 fully verified.**

### 14.8 What Phase 4 explicitly did not build

No SQLAlchemy ORM models, no repository, no application handler/mapper/
dispatcher, no wiring into `runtime/dependencies.py`. The codebase's own
convention (confirmed by reading `material_execution.py`) is raw SQL via
SQLAlchemy Core inside repositories, not an ORM layer — so there's nothing
to add here beyond the migration. That's Phase 5.

---

## 15. Phase 5/6 — the application layer, and the stub's replacement

### 15.1 What was built

Mirrors `application/materials/` almost exactly — same file names, same
responsibilities, same orchestration order in the Handler (map → validate →
open the one transaction → check idempotency → persist). Two real
differences from Material, both because Labour's shape is genuinely simpler
at this layer:

- **No resolver.** Material's Handler resolves `material_id`/`unit_id`
  against a catalog *at execution time*, as defense-in-depth. Labour has
  nothing equivalent to resolve: a line's `worker_id` was already decided by
  `match_workers` in the workflow, before the user ever confirmed (P4), and
  attendance never writes the register regardless (P1). There is nothing left
  to look up.
- **Two repository methods matter, a third writes many rows.** Where
  Material inserts one row plus one `material_movements` ledger row,
  `persist_success` here inserts one `labour_attendance_reports` row, then
  loops the command's `lines` and `attachment_object_keys` — an attendance
  report is naturally one-to-many, and the repository just reflects that.

`recover_confirmed_instances` and the dispatcher's failure contract are
**not new code** — both come from `application/shared/execution.py`, the
scaffolding extracted *before* Labour started specifically so it wouldn't
need to write its own (see §7.1). `LabourExecutionDispatcher` is a five-line
subclass.

### 15.2 The stub is gone

`runtime/labour_execution_stub.py` and its test are deleted.
`runtime/dependencies.py` now registers the real `LabourExecutionDispatcher`
for `DraftActionType.RECORD_LABOUR_ATTENDANCE`. **Confirming an attendance on
a deployed build now actually writes `labour_attendance_reports` /
`_lines` / `_attachments`** rather than logging and returning a fake
`stub-` id. The gap flagged as acceptable "only while behind an internal
test flow" (§ the stub's own docstring) no longer exists.

The e2e confirmation test (`test_labour_confirmation_e2e.py`) was rewritten
in place to wire the real `LabourExecutionDispatcher` +
`FakeLabourExecutionRepository` instead of the stub — same assertions
(nothing executes before YES, exactly once after, a blocked second report
neither executes nor overwrites), now proving the real Phase 5 code path
rather than a placeholder.

### 15.3 `recorded_via` — threaded through, not left as a TODO

Building the mapper meant deciding what to put in the `recorded_via` column
(§14.3's reservation). The honest options were: fabricate a value, leave the
column unpopulated, or actually thread the real input modality through. The
third one turned out to be nearly free.

`UnderstandingResult.input_modality` already exists and is already populated
correctly for every message (text/voice/image) by the time
`build_canonical_event` runs — nothing new needed there. So
`canonicalization/builder.py`'s `_normalize_labour_fields` gained one new
parameter, mapped once via `_RECORDED_VIA_BY_MODALITY`
(TEXT/INTERACTIVE → `whatsapp_text`, VOICE → `whatsapp_voice`,
IMAGE/DOCUMENT → `whatsapp_image`), and it is set **once**, at the message
that starts the workflow — a later slot-filling reply (always TEXT/
INTERACTIVE) never overwrites it, since `provide_input()` never re-runs
canonicalization.

`workflows/labour_update/nodes.py`'s `_DISPLAY_HIDDEN_FIELD_KEYS` gained
`"recorded_via"` so this provenance metadata never appears as a raw line in
the confirmation text — the supervisor confirming a headcount has no reason
to see it.

`dashboard` is reserved in the check constraint and the mapping table for
when a dashboard write path exists; nothing produces it yet.

### 15.4 A near-miss worth recording

The stub roster documented in `runtime/workforce_query.py`'s docstring used
short example ids like `"w-ravi"`. Once the mapper existed and started
building a real, typed `LabourAttendanceLine.worker_id: CanonicalUuid`, a
value like that would fail pydantic validation the moment a line actually
matched against it. Caught before it shipped and fixed by rewriting the
docstring's example to real UUIDs, with a note explaining why: **this fails
safely** (the whole command rejects, transaction rolls back, workflow stays
CONFIRMED and recoverable — no corrupted data), but a copy-pasted example
that can't actually be confirmed is still worth avoiding.

### 15.5 What's still open

- **Live-database verification.** Everything in Phases 4–6 has been tested
  against fakes and, for the migration, against real rendered Postgres DDL
  (§14.7) — but no code here has run against an actual live Postgres
  instance yet, because none was available in this session. Before treating
  Labour as production-ready: run the migration for real, confirm an
  attendance end to end against it, and run
  `test_organizations_cascade_delete_schema.py` (currently only verified by
  inspection).
- **Worker matching still reads a stub register** (§ Phase 3's "not started"
  section, unchanged) — `StubWorkforceQueryService` defaults to empty unless
  `MESIRI_LABOUR__STUB_WORKERS` is set. Phase 5 built the *save* path for
  real; the *read* path for the register is still Phase 5's original
  remaining item, now that persistence exists to promote a temporary worker
  into.
- **Q1 (photo extraction accuracy) is unchanged** — still blocked on real
  attendance sheet photographs (`labour-attendance-photo-eval.md`).
