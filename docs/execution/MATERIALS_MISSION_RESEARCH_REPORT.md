> **HISTORICAL (31 Oct 2026).** The WhatsApp assistant is now v2: one agent + skills + tools, see [../architecture/assistant-v2.md](../architecture/assistant-v2.md).
> This document describes the classic chain (classifier / planner / workflows), now retiring; the body is unchanged. Treat workflow / router / planner wording as the classic path.

# Materials Module Mission — Research Report

**Status:** RESEARCH REPORT — awaiting approval. No implementation plan, no code.
**Author:** Claude (Opus 5), 2026-07-30.
**Branch:** `feature/phase-4-invoice-capture` @ `c24eccb` (synced with `origin/main` @ `8078b39`).
**Mission:** make the Materials Module complete, production-ready and fully functional.

---

## Headline

**Roughly 70% of the mission's end-goal already exists and works.** The Materials Module is not
a half-built module needing completion — it is a well-built module with **four specific holes**
and **one shipped-but-dead feature**.

The single most important finding: **object storage is fully built and already holds every
WhatsApp image.** The earlier instruction to design a placeholder was based on a premise that
does not hold. Invoice viewing will work the day the provider is configured, with no
placeholder to build and none to remove.

---

## 1. What already exists and is reusable as-is

### 1.1 Inventory — essentially complete

| End-goal item | State | Evidence |
|---|---|---|
| Material catalogue | **Done** | `materials_catalog`, org-scoped, enforced Stock Unit |
| Stock levels | **Done** | Derived by `SUM` over the ledger, never stored |
| Material movements | **Done** | `material_movements`, immutable, one canonical writer |
| Receipts / Issues | **Done** | `RECEIVED`, `CONSUMED` + reasons |
| Returns | **Done** | `RETURN_IN`, `RETURN_TO_VENDOR` already in the reason set |
| Reversals | **Done** | Opposite-direction rows via `reverses_movement_id` |
| Stock history | **Done** | `get_ledger` with running balance |
| Validation | **Partial** | Catalogue/unit/role enforced; **no stock-level or duplicate guards** |
| Data integrity | **Gap** | See § 2.1 |

Returns and issues were on the mission's list as if missing. **They are not** — they exist as
movement reasons and post through the same ledger.

### 1.2 The AI pipeline — more complete than expected

Every stage of invoice processing already exists for other document types:

| Capability | Location | Note |
|---|---|---|
| WhatsApp media download (images **and PDFs**) | `ingress/media_ingestion.py` | `MetaMediaDownloader` is media-type agnostic |
| Upload to object storage | `ingress/media_handoff.py` | Key `media/{message_id}/{media_id}`, returns `MediaReference` |
| "What is this photo for?" picker | `interactions/image_purpose.py` | **3 rows** — no materials/invoice row |
| Vision that **already classifies `invoice`** | `adapters/gemini/adapter.py` `_VISION_PROMPT` | The word is literally in the classification list |
| Vision extracting a **repeating array** | Same prompt, `workers[]` for attendance sheets | A `line_items[]` array is the same shape, proven in production |
| Purpose hint → vision call | `adapter.py` | `"The sender says this image is: {hint}"` |
| Confidence scoring | `mesiri_ai/confidence.py` | Per-field |
| Confirm-before-record | `workflows/material/nodes.py` | Works |
| **Correcting a machine misread at the confirmation, in one message** | `interactions/handler.py::_maybe_correct_worker_names` + `name_corrections.py` | The mission's "correct on the same screen" requirement — already built for attendance |

### 1.3 Object storage — **fully built** (corrects an earlier premise)

| Piece | Location |
|---|---|
| `ObjectStoragePort` protocol | `shared/contracts/.../common/storage.py` |
| **Cloudflare R2 adapter** | `backend/src/mesiri/infrastructure/objectstorage/r2.py` |
| Provider factory (fake ↔ r2 by config) | `objectstorage/__init__.py::build_object_storage` |
| FastAPI dependency | `objectstorage/dependency.py::get_object_storage` |
| Presigned-URL retrieval + misconfiguration guard | `domains/expenses/router.py:538`, `domains/shared/media.py` |

**Every WhatsApp image is already in object storage before understanding runs**, and its
`object_key` is already threaded through the pipeline as
`UnderstandingResult.original_content_reference`.

**Consequence:** no placeholder field, no placeholder storage system, nothing to migrate later.
A `material_invoice_attachments` row storing the same `media_object_key` makes the invoice
viewable the moment `object_storage.provider = r2` is set — and if it is misconfigured,
`assert_downloadable_url` raises a clear 500 rather than emitting a broken image.

### 1.4 The attachment pattern — established and documented as reusable

Three tables exist: `expense_attachments`, `labour_attendance_attachments`,
`progress_attachments`. **There is no generic attachments table** — the convention is one table
per domain, all sharing an identical shape:

```
id · <parent>_id (FK) · media_object_key · attachment_type · created_at · created_by
+ index on parent_id + check constraint on type
```

`0430`'s own docstring settles whether replicating this counts as duplication:

> *"`progress_attachments` mirrors expense_attachments' shape exactly (**evidence pattern
> reuse**)"*

So a `material_invoice_attachments` table **is** "using the existing attachment
infrastructure" as the mission requires — the infrastructure being `ObjectStoragePort` +
`get_object_storage` + `assert_downloadable_url`, with the table shape as documented convention.
**One file in storage, referenced by both Materials and Finance — no file duplication.**

### 1.5 Finance integration — verified clean

`RecordExpenseHandler.handle(conn, cmd)` **takes a connection**, so Materials can create the
expense inside its own transaction. `AttachmentType` already has `BILL`/`RECEIPT`; `expenses`
already has `vendor_id`, `receipt_media_object_key`, tax fields, and `PaymentStatus.UNPAID` with
optional `account_id`. Duplicate detection (`find_potential_duplicate`) already exists.
Full analysis: [MATERIALS_FINANCE_INVOICE_LINKAGE.md](MATERIALS_FINANCE_INVOICE_LINKAGE.md).

### 1.6 One-document-to-many-records — already solved next door

`labour_execution.py` does parent + N lines + attachments in one transaction. One invoice → one
invoice record → N purchases → attachment reference is the identical shape.

### 1.7 Timeline

`timeline_projector.py` already registers `material_receipt` and `material_usage` and captions
them (*"X received"*, *"X used"*). Material events reach the timeline today.

---

## 2. The actual gaps

### 2.1 Data integrity — four ways stock can go silently wrong

| # | Gap | Consequence |
|---|---|---|
| **G1** | A movement can be **reversed twice**. No guard; the `0310` unique constraint guards a different thing (each reversal mints a fresh `source_id`) | Stock wrong by **2×** the original, permanently |
| **G2** | **No idempotency on the REST path.** Server mints the row id; a retry creates a second real movement. WhatsApp *is* protected | Phantom stock, unattributable |
| **G3** | **Case-variant catalogue names.** Unique constraint is exact-case. Worse: WhatsApp's lookup *is* case-insensitive and takes `.first()`, so with duplicates present it resolves **arbitrarily** | One stockpile split in two |
| **G4** | **No stock check on outflow.** Any quantity accepted silently | Typos become permanent, PM-only to fix |

### 2.2 Cost tracking — shipped, but dead

`purchase-history-view.tsx` renders a "Total Purchase Value" KPI and a "Total Cost" column.
**`POST /materials/inflows` does not accept `unit_cost` or `total_cost`, and the dialog does not
send them.** The columns exist on `material_receipts` and in the response model; nothing has
ever written them from the web path.

This already suppresses a downstream feature — `application/dpr/assembly.py` deliberately omits
material cost because *"`unit_cost` is nullable and inconsistently recorded... a partial cost
figure would read as complete and mislead."*

**Cost history cannot be reconstructed retrospectively.** Every week without capture is a week
of purchases permanently missing their price.

### 2.3 Scale

`GET /materials/inventory` has **no limit, offset or search** and returns every row; the UI
renders all of them and computes KPIs from array length. Also: no index supports the
inflow/outflow list's actual filter+sort shape.

### 2.4 Invoice capture — the genuinely new work

Three real gaps, everything else is wiring:

- **Extraction is singular.** `_EXTRACTION_PROMPT`'s `material_update` asks for one
  `material_name`/`quantity`/`unit`. An invoice has many.
- **Execution is singular.** `material_execution.py` inserts one receipt per command.
- **No route in.** The purpose picker has no materials/invoice row; a supplier invoice today
  lands as **Expense**.

### 2.5 Supplier

`material_receipts.supplier` is free text while a full `vendors` domain exists with CRUD.

---

## 3. Blocker — unchanged and now more urgent

Another agent shipped **Entity Resolution** (`ENTITY_RESOLUTION_PLAN.md`) and is actively
extending it — `origin/main` moved twice during this session, most recently `8078b39`
*"close the two PlanStep gaps blocking composite-request plans"*.

Their sequencing:

| Their phase | Work | Status |
|---|---|---|
| 3 | **Migrate MATERIAL** — *"the strongest correctness check... If it can't, the design is wrong"* | **Not started** |
| 4 | **Migrate VENDOR** (+ ACCOUNT, AUDIENCE, PROJECT, SITE) — *"delete each bespoke resolver as it moves"* | **Not started** |

`EntityType` currently holds `PROJECT, SITE, USER, MEMBERSHIP, ACTIVITY` — **no `MATERIAL`, no
`VENDOR`**.

My invoice plan would build a bespoke vendor resolver (scheduled for deletion) and rework
`material_catalog_query.py` (scheduled for migration). The mission says *"Never duplicate...
Extend existing systems whenever possible"* — which rules that out.

**Also:** `adapters/gemini/adapter.py` — the file the invoice prompt needs — was modified twice
by that agent this week. Concurrent-edit risk is real, not theoretical.

---

## 4. Proposed sequencing

Ordered so nothing waits on another team and nothing gets built twice. **The invoice work is
split** — everything independent of entity resolution ships first.

| Phase | Work | Blocked? |
|---|---|---|
| **A — Integrity & Safety** | G1 duplicate reversals, G2 idempotency, G3 case-insensitive names, G4 stock guard, perf indexes, concurrency (advisory lock) | **No** |
| **B — Cost Capture** | `unit_cost`/`total_cost` on the inflow API + dialog; Purchase History KPI becomes real | **No** |
| **C — Invoice Backbone** | `material_invoices` + `material_invoice_attachments`, multi-line execution, **Finance expense via `RecordExpenseHandler`**, invoice viewing, Purchase Details | **No** |
| **D — Invoice Conversation** | Picker row, `line_items` extraction, one-screen confirmation with inline correction, vendor + material resolution | **Yes** — needs their Phase 3/4 |
| **E — Inventory Scale** | Pagination, search, server-side KPI summary, date filters | **No** |
| **F — Polish** | Errors, mobile, accessibility, docs | **No** |

**Recommended start: Phase A.** It is unblocked, it is the only work that prevents *permanent,
silent* data corruption, and every later phase writes into the ledger it protects. Building
invoice capture on top of a ledger that can double-reverse would mean shipping a faster way to
create wrong data.

**On Phase B's urgency:** cost capture is two optional fields with no interaction with anything
else, and the data is unrecoverable if not captured. Worth folding into Phase A rather than
waiting.

**On Phase D:** by the time A–C are done, their Phase 3/4 may well have landed. If not, D can
start with a targeted request to that agent rather than a duplicate implementation.

---

## 5. Corrections to earlier guidance

Stated plainly, because both changed the design:

1. **"Storage infrastructure has not yet been connected — do not implement permanent file
   storage; use a placeholder."** The R2 adapter, the port, the factory, the dependency and the
   presigned-URL retrieval **all exist and are wired**, and WhatsApp images are already stored.
   Only provider *configuration* is outstanding. **No placeholder should be built** — one would
   be the parallel system the mission forbids.
2. **"Keep Finance separate."** Superseded by your later decision to integrate. Verified clean
   and now in scope for Phase C.

---

## 6. Open items

1. **Which phase do I start?** Recommendation: **A** (with B folded in).
2. **Entity-resolution collision** — accept the A→C-first sequencing, or coordinate with that
   agent to pull their Phase 3/4 forward?
3. **No Linear issues exist** for any of this. The workflow requires updating one per phase;
   none exist to update. Recommend creating an epic plus one issue per phase before Phase A.
4. **`interactions/handler.py`** — shared file, needed in Phase D (approved verbally; re-flag at
   that point).
5. **Cost visibility by role** — needed before the Phase B dashboard work.
6. **PDF support** — to be verified against the vision adapter during Phase D.

---

**Status: research complete, awaiting approval of the phase sequencing before any implementation
plan is written.**
