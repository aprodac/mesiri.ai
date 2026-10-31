> **HISTORICAL (31 Oct 2026).** The WhatsApp assistant is now v2: one agent + skills + tools, see [../architecture/assistant-v2.md](../architecture/assistant-v2.md).
> This document describes the classic chain (classifier / planner / workflows), now retiring; the body is unchanged. Treat workflow / router / planner wording as the classic path.

# Phase 4 — AI Invoice & Purchase Capture

**Status:** PLAN — awaiting approval. No code until approved.
**Author:** Claude (Opus 5), 2026-07-30.
**Replaces:** the roadmap phase formerly named "Cost & Supplier Intelligence".
**Roadmap:** [MATERIALS_MODULE_ROADMAP.md](MATERIALS_MODULE_ROADMAP.md) · **Hardening:** [MATERIALS_PHASE_2_HARDENING_PLAN.md](MATERIALS_PHASE_2_HARDENING_PLAN.md)

---

## 1. Objective

Let a site engineer photograph a supplier invoice in WhatsApp and have Mesiri read it,
propose the purchase conversationally, and — from **one confirmation** — update inventory,
create one purchase per material, and **record the matching unpaid expense in Finance**, all
linked to that single invoice.

Built by **extending the media and understanding pipeline that already exists**, not by
adding an invoice pipeline beside it.

> **Approved 2026-07-30 — Finance integration is in this phase, not a later one.**
> One upload, one confirmation, both departments updated. Nobody re-keys the same invoice into
> Finance. Architecture and evidence:
> [MATERIALS_FINANCE_INVOICE_LINKAGE.md](MATERIALS_FINANCE_INVOICE_LINKAGE.md).
> Confirmed: the expense is **always** created, **unpaid**, **one per invoice** for the invoice
> total; category `"Materials"`; **no reversal cascade in V1**.

---

## 2. Existing Architecture Analysis

I traced the full path an image takes today. The finding that matters: **almost every piece
of this feature already exists and is in production for another document type.**

### 2.1 The path an image already takes

```
WhatsApp image/PDF
   └─ ingress/receiver.py → MetaMediaDownloader.download()      [handles images AND documents]
        └─ ingress/media_handoff.py → object storage, returns object_key
             └─ interactions/image_purpose.py → holds it, asks "What is this photo for?"
                  └─ user taps a row → IMAGE_PURPOSE_SEMANTIC_HINT
                       └─ understanding/pipeline.py:  vision → extraction
                            └─ canonicalization → planner → workflow graph
                                 └─ request_confirmation → "Reply YES"
                                      └─ interactions/handler.py → ExecutionDispatcher
                                           └─ application/materials/handlers.py (transaction,
                                              idempotency) → material_execution.py → INSERT
```

**Every stage is reusable. Not one needs replacing.**

### 2.2 What already exists — verified, not assumed

| Capability | Where | State |
|---|---|---|
| Download WhatsApp images **and PDFs** | `ingress/media_ingestion.py` | Works. `MetaMediaDownloader` is media-type agnostic |
| Upload to object storage, return `object_key` | `ingress/media_handoff.py` | Works |
| "What is this photo for?" picker | `interactions/image_purpose.py`, `channel/replies.py:179` | Works. **3 rows today** |
| Batch handling (10 photos → one picker) | `interactions/pending_media.py` | Works |
| Vision model that **already classifies `invoice`** | `adapters/gemini/adapter.py:32` `_VISION_PROMPT` | **The word "invoice" is already in the classification list** |
| Vision extracting a **repeating array of line items** | Same prompt, `workers` array for attendance sheets | **Works in production.** A `line_items` array is the same shape, not a new capability |
| Purpose hint threaded into the vision call | `adapter.py:656-658` | Works |
| Structured extraction with per-field confidence | `understanding/pipeline.py`, `mesiri_ai/confidence.py` | Works |
| Conversational confirm-before-record | `workflows/material/nodes.py` | Works |
| Disambiguation picker when a name is ambiguous | `runtime/material_catalog_query.py` | Works (OPC vs PPC cement) |
| Vendors CRUD | `domains/vendors/` | Works |
| Attachment types incl. `BILL` and `RECEIPT` | `domains/expenses/entities.py:39` | **Already exist — no enum change needed** |
| Idempotent execution, one transaction | `application/materials/handlers.py` | Works |

### 2.3 The precedent that decides the design

`labour_execution.py` already does **exactly** the one-document-to-many-records shape this
feature needs, and has done since `0371`:

```
one confirmed action
   ├─ INSERT labour_attendance_reports        (the parent — the document)
   ├─ for line in cmd.lines:                  (N children — one per worker)
   │     INSERT labour_attendance_lines
   └─ for object_key in cmd.attachment_object_keys:
         INSERT labour_attendance_attachments  (the evidence)
```

One attendance sheet → one report → N worker lines → attachment references.
One invoice → one invoice record → N purchases → attachment reference.

**Same problem, already solved, in production, by the team next door.** Materials should
follow this structure rather than invent one. (Reading it as a pattern is not modifying it —
§ 15.)

### 2.4 The three genuine gaps

| Gap | Detail |
|---|---|
| **G1 — extraction is singular** | `_EXTRACTION_PROMPT`'s `material_update` asks for `material_name, quantity, unit` — **one material per message.** An invoice has many. The vision prompt has no `line_items` instruction. |
| **G2 — execution is singular** | `material_execution.py` inserts **one** receipt per command. No parent invoice concept, no iteration. |
| **G3 — no invoice route into the module** | `IMAGE_PURPOSE_ROWS` offers Expense / Attendance / Site Update. A supplier invoice today lands as **Expense**. There is no materials route for a document. |

Everything else is wiring.

---

## 3. Components to Reuse

**Reused unchanged:** `MetaMediaDownloader`, `media_handoff`, `PendingMediaStore`,
`UnderstandingPipeline`, `ConfidencePolicy`, the Gemini vision + extraction adapters (prompt
text extended, adapter code untouched), `material_catalog_query.py`'s resolution and picker,
the project/site gates, `post_material_movement`, `application/materials/handlers.py`'s
transaction + idempotency orchestration, the whole `vendors` domain, `AttachmentType`,
`ObjectStoragePort`, `assert_downloadable_url`, `DraftActionV2`.

**Contract change avoided:** `DraftActionV2.fields` is `dict[str, Any]`, so a `line_items`
array travels through the existing draft/confirm machinery with **no contract change at
all**. This is the single biggest reuse win in the plan.

**Not built:** no new OCR service, no new AI service, no second WhatsApp flow, no separate
invoice pipeline, no supplier table, no new storage abstraction, no new confirmation
mechanism.

---

## 4. Files to Modify

**AI platform** — `adapters/gemini/adapter.py` (prompt text only: `line_items` in
`_VISION_PROMPT`, a multi-line materials shape in `_EXTRACTION_PROMPT`); `models.py` if the
extraction result needs a typed line-item shape.

**WhatsApp assistant** — `channel/replies.py` (a 4th picker row + hint mapping);
`canonicalization/builder.py` + `mapping.py` (fold `line_items` into the canonical event);
`workflows/material/nodes.py` (multi-line confirmation text); `workflows/material/graph.py`
(vendor + per-line resolution gates); `runtime/inbound_journey/process.py` (route the
invoice hint); `runtime/material_catalog_query.py` (resolve a *set* of names in one pass);
new `runtime/vendor_match_query.py`.

**Backend** — `application/materials/mapper.py`, `resolution.py`, `repository.py`;
`infrastructure/postgres/repositories/material_execution.py` (parent + N lines, following
the labour precedent); `domains/materials/router.py` + `responses.py` (invoice fields on
reads); one migration.

**Dashboard** — `purchase-history-view.tsx`, `purchase-details-sheet.tsx`,
`record-inflow-dialog.tsx`, `lib/materials.ts`; new `materials/invoice-attachment.tsx`,
`materials/supplier-picker.tsx`.

**Shared contracts** — `commands/material.py` (a lines list on the command), extraction
candidate shapes.

---

## 5. New Files

`runtime/vendor_match_query.py` (mirrors `material_catalog_query.py`);
`workflows/material/invoice_nodes.py` if multi-line confirmation outgrows `nodes.py`;
`materials/invoice-attachment.tsx`, `materials/supplier-picker.tsx`;
one migration; tests per § 16.

---

## 6. Backend Plan

### 6.1 Data model — invoice as parent, purchases as children

Following § 2.3's precedent exactly:

- **`material_invoices`** (new): `id`, `organization_id`, `project_id`, `site_id`,
  `vendor_id` (nullable FK), `supplier_name` (free text as extracted — always kept, even
  when a vendor matches, so the document's own words survive), `invoice_date`,
  `invoice_total`, `invoice_object_key`, `source` (`whatsapp`/`web`), `correlation_id`,
  `created_by`, `created_at`.
- **`material_receipts.invoice_id`** (new nullable FK). Nullable is load-bearing: manual and
  WhatsApp-text inflows have no invoice and must keep working untouched.

**One purchase per material, all linked to one invoice** — exactly as specified, and it
falls out of this shape naturally rather than needing special handling.

### 6.2 Invoice attachment — the storage decision

**Store `invoice_object_key` (a storage reference), not a URL.**

This is not a placeholder — it is what the codebase already does everywhere
(`expense_attachments.media_object_key`, `labour_attendance_attachments`). The WhatsApp
ingress path **already uploads media to object storage and already carries `object_key`**
(`understanding/pipeline.py` threads `message.media.object_key` through as
`original_content_reference`). So on the WhatsApp path the reference exists from day one at
zero cost.

What is not yet connected is the **production storage provider**. That is a deployment
concern, not a schema one. Resolving a key to a downloadable URL goes through the existing
`ObjectStoragePort` + `assert_downloadable_url`, which already fails loudly rather than
silently emitting broken links.

**Result: when storage is configured, invoice viewing begins working with no Materials
change whatsoever.** No redesign, no migration, no placeholder to clean up.

### 6.3 Execution — one command, N inserts

`material_execution.py` gains an invoice-aware path mirroring `labour_execution.py`: insert
the parent invoice, iterate lines inserting a receipt + calling `post_material_movement` for
each, then the outbox event — **all inside the single existing transaction**. Either the
whole invoice lands or none of it does. Idempotency reuses the existing key claim, so a
retried confirmation cannot produce a second set of purchases.

The existing single-material path is untouched.

### 6.4 Vendor matching

New `vendor_match_query.py` mirroring `material_catalog_query.py`: exact
case-insensitive match → accept; ambiguous or weak → picker over candidates plus "None of
these"; no match → keep free text and offer vendor creation as a separate, explicit step.
**Never auto-creates a vendor**, per the same rule the material catalogue already follows.

### 6.5 Extraction

`_VISION_PROMPT` gains a `line_items` instruction for invoices, written to mirror the
`workers` block that already works: transcribe every row, never total, never invent, omit
unknown keys. `_EXTRACTION_PROMPT` gains a multi-line materials shape carrying
`supplier_name`, `invoice_date`, `invoice_total`, and `line_items[]` of
`{material_name, quantity, unit, unit_cost, line_total}`.

**Nothing outside the V1 field list is extracted.** GST, HSN, bank details, vehicle numbers,
tax and freight breakdowns are explicitly *not* requested — they remain in the stored image
if ever needed.

---

## 7. API Plan

**Reused:** the entire vendors API; `post_material_movement`; every authorization helper;
inflow list and detail endpoints.
**Modified:** `POST /materials/inflows` accepts optional `unit_cost`, `total_cost`,
`vendor_id`, `invoice_id`; `GET /materials/inflows` gains `vendor_id` and `invoice_id`
filters and returns invoice fields.
**Added:** `POST /materials/invoices` (create invoice + lines in one transaction — the web
equivalent of a confirmed WhatsApp invoice); `GET /materials/invoices/{id}`;
`GET /materials/invoices/{id}/attachment` (resolves the object key to a signed URL, returns
a clear "not yet available" state while storage is unconfigured).

Three endpoints, each doing something no existing endpoint does. No duplication of the
inflow API — the invoice endpoint composes it rather than re-implementing it.

---

## 8. Database Plan

**One migration**, number claimed at implementation time (§ 15.1).

1. `CREATE TABLE material_invoices` (+ indexes on `organization_id`,
   `(organization_id, vendor_id)`, `(organization_id, invoice_date)`)
2. `ALTER TABLE material_receipts ADD COLUMN invoice_id UUID NULL REFERENCES material_invoices(id)`
3. `CREATE INDEX ix_material_receipts_invoice_id`

**No changes to `material_movements`** — the ledger is untouched, so stock semantics,
reversal behaviour and Phase 2's integrity guarantees all carry over unchanged.
**No backfill.** **No new attachment type** (`BILL` already exists). **No data migration**,
therefore trivially reversible.

---

## 9. UI & User Flow

### 9.1 WhatsApp — the flow the product principle describes

```
[engineer sends invoice photo]

📷 What is this photo for?
   › Expense            — Receipt or bill you paid
   › Material Delivery  — Supplier invoice or challan     ← NEW ROW
   › Attendance         — Who worked today
   › Site Update        — Progress photo

[taps Material Delivery]

I found the following purchase.

*Supplier:* ABC Traders

*Materials:*
 • UltraTech Cement — 200 Bags @ ₹312.50/Bag
 • River Sand — 15 Cu.M @ ₹850/Cu.M

*Invoice Total:* ₹118,484
*Invoice Date:* 27 Jan 2026

Is this correct? Reply YES to record, or NO to cancel.
```

Confirmation renders **only** the V1 fields. Nothing is recorded before YES.

### 9.2 One confirmation screen — VERIFIED, with corrections folded in

**Verified 2026-07-30: yes. And the mechanism already exists.**

`interactions/handler.py::_maybe_correct_worker_names` + `interactions/name_corrections.py`
already let a supervisor fix machine-misread values **at the confirmation step, in one message,
without restarting**. Its docstring states the reasoning:

> *"OCR and speech will never read every attendance sheet perfectly, and a supervisor who spots
> two wrong names in the preview should be able to fix them in one message rather than
> restarting the report."*

That method is scoped to attendance deliberately, because it was *"the only workflow whose
fields are a list of names read by a machine, where a one-character misread is both likely and
expensive."* **An invoice is now the second.** The rationale extends exactly.

So resolution does **not** run as sequential pickers before confirmation — the earlier
numbered-picker design in this plan is **withdrawn**. Everything read is shown once, anything
unresolved is marked inline, and the user confirms or corrects in the same breath:

```
I found the following purchase.

*Supplier:* ABC Traders

*Materials:*
 • UltraTech Cement — 200 Bags @ ₹312.50/Bag
 • River Sand — 15 Cu.M @ ₹850/Cu.M
 • ⚠️ "TMT Steel 12mm" — not in your catalogue

*Invoice Total:* ₹118,484
*Invoice Date:* 27 Jan 2026

_Also records an unpaid expense of ₹118,484 against ABC Traders._

Reply YES to record (the flagged line is skipped),
or fix it: "TMT Steel 12mm -> TMT Bar 12mm"
```

**One screen. One YES. One confirmation covers inventory, purchases and the Finance expense.**
A correction costs one extra message *only when the model got something wrong*, and it rebuilds
the same preview rather than restarting.

**Partial confirmation is allowed** — YES records the matched lines and names what was skipped.
Blocking a whole invoice on one unrecognised line would push people back to typing.

**Two interactions still precede this screen, both pre-existing and both conditional:** the
"what is this photo for?" tap, and the project/site gate (fires only when scope is ambiguous).
See § 14.4.

### 9.3 Dashboard — Purchase History

Columns as specified: Supplier · Material · Quantity · Unit Cost · Line Total · Invoice
Total · Invoice Date · Invoice. Rows from one invoice are visually grouped and expandable.
The Invoice column shows a thumbnail when storage is live, and **a reserved placeholder
("Invoice attached — viewing not yet available") when it is not.** The place is reserved
now, so connecting storage requires no UI change.

---

## 10. User Experience Considerations

- **Seconds reviewing, not minutes typing** — that is the whole point. Every added question
  spends the feature's value; resolution is batched (§ 9.2) for exactly that reason.
- **Never record without confirmation.** Non-negotiable, and it matches every other Mesiri
  write path.
- **Show what was read, not a form to fill.** The confirmation is a summary to check, not
  fields to complete.
- **Partial success beats total failure** on a 12-line invoice.
- **Say plainly when reading failed.** A blurry photo gets "I couldn't read this clearly —
  send a sharper photo, or record it manually", never a half-invented record.
- **Never present extracted numbers as verified.** They are the model's reading of a
  photograph, awaiting a human's yes.

---

## 11. Edge Cases

| # | Case | Handling |
|---|---|---|
| E1 | **Line totals don't sum to invoice total** | **Expected and normal** — tax, freight and discounts are deliberately not extracted. Store `invoice_total` exactly as printed; never derive it, never reconcile it, never show a discrepancy warning. *(The example in the brief itself totals ₹75,250 across its lines against a stated ₹118,484 — the gap is tax and freight, and treating it as an error would flag almost every real invoice.)* |
| E2 | **Unit on invoice ≠ material's Stock Unit** | V1 has no unit conversion. Cannot silently coerce. Ask once naming the correct unit (the existing mismatch gate), or skip that line. |
| E3 | Material not in catalogue | Picker; never auto-create. Skippable per § 9.2 |
| E4 | Vendor name unmatched or ambiguous | Picker; keep free text; never auto-create |
| E5 | Same invoice photographed twice | Warn on `(vendor, invoice_date, invoice_total)` near-match: "This looks like an invoice you already recorded on 27 Jan. Record it again?" Advisory, not blocking — genuine same-day repeat deliveries exist |
| E6 | Multi-page invoice / photo burst | Existing batch handling groups them; pages combine into one invoice |
| E7 | PDF instead of image | `MetaMediaDownloader` is media-type agnostic. **Confirm the vision adapter accepts PDF bytes** — if not, V1 accepts images only and says so clearly rather than failing opaquely |
| E8 | Handwritten challan | Same path; lower confidence; more clarification. Acceptable |
| E9 | Zero line items extracted | "I couldn't read the materials on this — record manually?" Never an empty invoice |
| E10 | No cost printed | `unit_cost`/`line_total` stay NULL. Rendered "Not recorded", **never ₹0** |
| E11 | Storage not yet connected | Purchase records fine; attachment column shows the reserved placeholder |
| E12 | User replies NO | Nothing written. Draft discarded, image retained per existing media policy |
| E13 | Confirmation retried / double YES | Existing idempotency key claim — one invoice, one set of purchases |
| E14 | Invoice spans two sites | V1: one invoice → one site (the active scope). Split invoices are out of scope; documented |
| E15 | Extraction succeeds, execution fails mid-invoice | One transaction — full rollback, workflow stays confirmable, nothing partially written |

---

## 12. Performance Considerations

- One vision call per invoice — same cost as today's expense receipt path, no new round
  trips. Line items come back in the **same** call that already classifies the document.
- Catalogue and vendor resolution for all lines run as **one batched query each**, not per
  line — a 12-line invoice must not become 24 queries.
- Execution: one transaction, N inserts. `labour_execution.py` already does this for
  attendance sheets with more lines than a typical invoice.
- Purchase History grouping is computed server-side; the frontend does not re-group an
  unbounded fetch (the Phase 3 lesson).
- Vision latency is ~7s on real images per the adapter's own notes — acceptable, and the
  user is told the document is being read rather than left in silence.

---

## 13. Security & Permissions

- Invoice endpoints reuse `get_auth_context`, `_resolve_project_ids`, `_site_filter_denied`,
  `_authorize_write` — no new authorization model.
- `vendor_id` and `invoice_id` are resolved **within the caller's organization**; a
  cross-org id must 404, not 403 (never confirm another org's ids exist). Explicit test.
- Attachment retrieval is authorization-checked on **every** request and returns a
  short-lived signed URL — an invoice shows supplier pricing, which is commercially
  sensitive.
- `assert_downloadable_url` reused so a misconfigured provider fails loudly.
- Extracted text is **data, never instruction.** A document containing text like "ignore
  previous instructions" must never influence behaviour — extraction output is parsed as
  structured fields only, never concatenated into a subsequent prompt as trusted content.
  Worth an explicit test, since this is the first Materials feature reading attacker-
  influenceable content.
- Cost visibility follows the existing role model — **decision required (§ 14)**.

---

## 14. Regression Risk Analysis

### 14.4 One-confirmation follow-ups (from the § 9.2 verification)

**`interactions/handler.py` is a shared file — REQUIRES APPROVAL BEFORE IMPLEMENTATION.**
Folding invoice corrections into the confirmation means adding a
`_maybe_correct_invoice_lines` branch to `handle_fast_path`. That file is the shared WhatsApp
interaction layer every workflow routes through, and attendance's name-correction path lives
inside it. A mistake in the fast-path ordering breaks attendance name corrections — Labour
behaviour, without touching a Labour file. Mitigation: a **new sibling method**, never an edit
to `_maybe_correct_worker_names`; the invoice branch checks `workflow_key` first and returns
`None` for everything else, exactly as the attendance one does; attendance correction tests run
before and after.

**Skipping the image-purpose picker for high-confidence invoices — considered, not taken in
V1.** Vision already classifies `invoice`, so the tap could be skipped on a confident
classification, saving one interaction. Rejected for now because the picker exists on a
documented deliberate decision (`FINANCE_MODULE_PLAN.md`'s note on why a vision guess is not
reliable enough alone), and changing it affects expenses and attendance too. Revisit once real
invoice classification confidence has been measured.

### 14.5 Risk table

| Risk | Severity | Mitigation |
|---|---|---|
| **Prompt changes degrade existing extraction.** `_VISION_PROMPT` and `_EXTRACTION_PROMPT` are shared by expenses, attendance, equipment and site updates. A careless edit degrades attendance-sheet transcription — the highest-value existing behaviour. | **High** | Additive-only edits; `test_extraction_prompt_parity.py` already exists and must pass; regression fixtures for every existing semantic type before and after |
| **Shared `interactions/handler.py` change breaks attendance name corrections** | **High** | § 14.4 — new sibling method, workflow-key guard, attendance tests before/after |
| **Finance expense created wrongly or twice** | **High** | Materials never writes `expenses`; calls `RecordExpenseHandler` with a deterministic idempotency key derived from the invoice id. One expense per invoice, for the invoice total, never per line |
| **Expense vs material double-count.** "Expense — receipt or bill" already exists; a cement invoice is both a bill and a material receipt. Recorded twice = spend counted twice. | **High (business)** | Sharpen both picker labels; **do not auto-create an expense from a material invoice in V1**; flag when an expense and a material invoice share supplier+date+total |
| Existing single-material WhatsApp flow breaks | High | `line_items` is additive; single-material path untouched; existing 46 assistant tests must pass unchanged |
| Multi-line confirmation text becomes unreadable at 15 lines | Medium | Cap displayed lines with "…and 6 more"; full detail on the dashboard |
| `invoice_id` FK breaks existing inflow writes | Medium | Nullable, no backfill, existing insert paths untouched |
| Vendors domain regression | Medium | Read-only reuse; vendors suite run and reported |
| Extraction confidently misreads a quantity | **High (business)** | Confirmation is the control. Never auto-record. Quantities shown prominently with units |

---

## 15. Labour Module Isolation

**No Labour file is modified.** `labour_execution.py` is read as a *pattern* (§ 2.3) — copying
a proven structure into `material_execution.py` changes nothing in Labour.

**Shared surfaces — flagged, as required:**

1. **`adapters/gemini/adapter.py` prompts are shared with attendance extraction.** This is
   the one place where Materials work could damage Labour's behaviour. Mitigation: additive
   edits only, the existing parity test must pass, and attendance regression fixtures run
   before and after. **If a change to the `workers` block itself ever proves necessary, work
   stops and it is reported.**
2. **Alembic numbering.** Head is `0456`; `0454`/`0456` are Labour's. This phase needs a
   migration. Same standing coordination issue as every other phase.
3. **`AttachmentType`** — no change needed; `BILL` and `RECEIPT` already exist. Noted
   because extending it *would* touch a Labour-shared enum.

**Verification:** `git diff --stat` must show zero files under `workforce/`, `labour`,
`attendance`, `payroll` or `components/ui/`, plus a full Labour suite run, reported.

---

## 16. Testing Plan

**Unit** — line-item parsing including empty, single and 15-line invoices; line totals not
summing to invoice total is accepted silently (E1); NULL cost renders "Not recorded" never
₹0; vendor matching exact/ambiguous/none; unit mismatch against Stock Unit; partial
confirmation records matched lines only; multi-line confirmation formatting and truncation.

**Integration** — full path from a fixture invoice image through vision, extraction,
resolution, confirmation and execution; one invoice → N receipts → N movements → correct
stock; rollback leaves nothing written; idempotent double-YES; cross-org id returns 404;
prompt-injection text in a document changes nothing.

**Regression** — existing 46 WhatsApp and 45 backend material tests pass **unchanged**;
`test_extraction_prompt_parity.py` passes; expense/attendance/equipment/site-update
extraction fixtures score no worse than before; vendors and Labour suites pass.

**Manual** — real invoices: clean printed, poor lighting, handwritten challan, multi-page,
one with no prices, one with a material not in the catalogue. Verify Purchase History
grouping and the attachment placeholder.

---

## 17. Success Criteria

1. Photographing an invoice in WhatsApp produces the specified conversational summary.
2. Nothing is recorded before explicit confirmation.
3. Confirmation creates one purchase per material, all linked to one invoice, with inventory
   updated through the existing ledger.
4. Only V1 fields are extracted.
5. Vendors are matched, never duplicated, never auto-created.
6. Every purchase carries an invoice reference that will resolve to a viewable document the
   day storage is connected — **with no Materials change**.
7. Purchase History shows all specified columns with a reserved attachment slot.
8. No new OCR service, AI service, WhatsApp flow, or invoice pipeline exists.
9. Existing extraction quality for expenses and attendance is unchanged, evidenced.
10. All suites pass; Labour untouched and verified.

---

## Priority Matrix

| Item | Impact | Effort | Priority |
|---|---|---|---|
| Invoice data model + attachment reference | Critical (foundation) | Medium | **P0** |
| Vision/extraction `line_items` | Critical | Medium | **P0** |
| Picker row + invoice routing | Critical | Low | **P0** |
| Multi-line execution (labour pattern) | Critical | Medium | **P0** |
| Multi-line confirmation text | High | Low | **P1** |
| Batched catalogue resolution + partial confirm | High | Medium | **P1** |
| Vendor matching | High | Medium | **P1** |
| Purchase History invoice columns | High | Medium | **P1** |
| Attachment placeholder UI | Medium | Low | **P2** |
| Duplicate-invoice warning | Medium | Low | **P2** |
| Web invoice upload | Low | Medium | **P3 — out of V1 scope** |

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Shared prompt edits degrade attendance extraction | Medium | **High** | Additive only; parity test; before/after fixtures |
| Expense/material double-counting | Medium | **High** | Picker wording; no auto-expense; overlap flag |
| Extraction accuracy below usable on real invoices | Medium | High | Confirmation is the control; measure on real documents in week one and report honestly |
| Too many clarifying questions kills the value | Medium | High | Batched resolution; partial confirmation |
| Alembic branch with Labour | Medium | High | Claim the number at phase start |
| PDF unsupported by the vision adapter | Medium | Medium | Verify early (E7); images-only V1 with a clear message if so |
| Scope creep into GST/tax/PO territory | Medium | Medium | Explicit exclusion list |

## Recommended Implementation Order

1. **Data model + migration** — parent/child/attachment reference. Nothing else can be
   tested until this exists.
2. **Extraction** — prompt changes + parity and regression fixtures. Done early and alone,
   because this carries the Labour-adjacent risk and must be proven before anything is built
   on it.
3. **Routing** — picker row, hint, canonicalization. Small, and makes the path exercisable
   end to end.
4. **Execution** — multi-line insert following the labour precedent, inside the existing
   transaction and idempotency.
5. **Conversation** — multi-line confirmation, batched resolution, partial confirm, vendor
   matching. The UX-heavy step, on proven foundations.
6. **Dashboard** — Purchase History columns, invoice grouping, attachment placeholder.
7. **Hardening** — duplicate warning, error messages, real-invoice testing.

---

## Decisions — status

**Settled 2026-07-30:**

1. ~~Expense vs Material invoice~~ → **Integrate.** A confirmed material invoice always creates
   one unpaid Finance expense for the invoice total. Nobody re-keys it. Double-counting is
   handled by one-expense-per-invoice plus the source-document link and the existing
   `find_potential_duplicate`.
2. ~~Partial confirmation~~ → **Allowed.** YES records matched lines and names what was skipped.
3. ~~One confirmation screen~~ → **Verified achievable** (§ 9.2); sequential pickers withdrawn
   in favour of inline correction at the confirmation, reusing the attendance pattern.

**Still open — needed before or during implementation:**

4. **`interactions/handler.py` is shared — approval needed to touch it** (§ 14.4). This is the
   only blocking item.
5. **PDF support in V1** — I will verify whether the vision adapter accepts PDF bytes as the
   first task of Step 2. If not, V1 is images-only with a clear message.
6. **Cost visibility by role** — can everyone who records materials see rates, or is cost
   restricted to ADMIN/PROJECT_MANAGER/FINANCE? Needed before the dashboard step (Step 6), not
   before Step 1.
7. **Web invoice upload** — recommend deferring; WhatsApp is the product principle.
8. **Manual cost capture in Phase 2** — still recommended; not every purchase arrives with a
   photographed invoice.

---

**Status: awaiting approval. No implementation begins until this plan is approved.**
