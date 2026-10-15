# Materials Module — Complete Implementation Roadmap (V1)

**Status:** ROADMAP — awaiting approval. No code until a phase is approved.
**Technical lead:** Claude (Opus 5). **Created:** 2026-07-30.
**Supersedes as the planning index:** [MATERIALS_PHASE_2_HARDENING_PLAN.md](MATERIALS_PHASE_2_HARDENING_PLAN.md)
(that document remains the detailed spec for Phase 2).
**Context:** [MATERIALS_CATALOGUE_PLAN.md](MATERIALS_CATALOGUE_PLAN.md) — V1 catalogue/units/ledger, done.

---

## Where the module stands today

**Done (V1 core):** catalogue with enforced Stock Units, fixed units-of-measure, immutable
`material_movements` ledger, inflows/outflows, derived inventory, per-material ledger,
append-only corrections, WhatsApp capture with disambiguation, mobile read views.

**Done (Phase 1):** Purchase History, Purchase Details, KPI cards, search, filter, sort,
responsive layout, empty states. *Currently uncommitted in the working tree.*

**Done (V1 tracker, 15 Oct 2026):**
- **Units:** `cft` and `load` units (BE-39, migration 0474).
- **Opening stock (BE-12, 0477):** an `OPENING_STOCK` inflow reason, ADMIN/PM only, once per
  site+material; it can be entered again after a correction.
- **DPR stock lines (BE-12):** the DPR materials section shows opening, received, adjusted, used
  and closing per material. Opening stock and adjustments are no longer counted as deliveries.
  Usage beyond known stock is flagged (`beyond_stock`, `stock_flags`, a PDF line), never blocked.
- **Transfers between sites (BE-32, 0479):** `POST /materials/transfers` writes both halves in
  one transaction, linked by `transfer_id`, and works across projects. A transfer is corrected
  only as a pair.
- **Dashboard (WEB-11):** opening stock in Record Inflow, a Transfer dialog, a Transfers tab, and
  transfer-aware corrections.
- **Bugs fixed on the way:**
  - Corrections crashed: the repository tables had no `unit_id`.
  - The ledger endpoint used `sa.coalesce`, which isn't SQLAlchemy API.
  - The catalog response had no `default_unit_id`, so dashboard writes had no unit.
- **Still open:**
  - No WhatsApp transfer command.
  - No approval queue for adjustments a supervisor proposes.
  - The starter sand/aggregate unit is still `cum`, pending clients (BE-40).

**Architecture that must not be disturbed:** one canonical ledger writer
(`posting.py::post_material_movement`), one transaction per request, stock derived by `SUM`
and never stored, corrections as opposite-direction rows and never edits. Everything in this
roadmap works with that grain, not against it.

### Two findings that shaped the ordering

**1. Phase 1 shipped a column that can never fill.** `purchase-history-view.tsx` renders a
"Total Purchase Value" KPI and a "Total Cost" column — but `POST /materials/inflows` does not
accept `unit_cost` or `total_cost`, and the record-inflow dialog does not send them. The
columns exist on `material_receipts` and in the response model; **nothing has ever written
them from the web path.** Every web-recorded purchase has NULL cost, so that KPI reads "—"
permanently.

This is already suppressing a downstream feature: `application/dpr/assembly.py` deliberately
omits material cost from Daily Progress Reports because `unit_cost` is *"nullable and
inconsistently recorded... a partial cost figure would read as complete and mislead."*

**Cost history cannot be reconstructed after the fact.** Every week without capture is a week
of purchases permanently missing their price. This is why a small slice of cost capture is
recommended for Phase 2 rather than waiting for Phase 4 (see § Sequencing Decision).

**2. Suppliers are free text, but a `vendors` domain already exists.** `material_receipts.supplier`
is an unconstrained string; `backend/src/mesiri/domains/vendors/` has entities, a router, and
full CRUD. "Supplier History" must **reuse vendors**, not build a parallel supplier concept.
That is the difference between a feature and a second source of truth.

---

## Phase map

| # | Phase | Theme | Depends on | Est. size |
|---|---|---|---|---|
| ~~1~~ | ~~Purchase History~~ | ~~UX~~ | — | **Done** |
| **2** | **Production Hardening & Data Integrity** | Stability | — | Large |
| **3** | **Inventory Experience & Scale** | Scalability + UX | 2 | Medium-large |
| **4** | **AI Invoice & Purchase Capture** | V1 feature | 2 (cost slice) | Large |
| **5** | **Material Details & Timeline** | V1 feature | 3, 4 | Medium |
| **6** | **Dashboard, Analytics & Alerts** | V1 feature | 4, 5 | Medium |
| **7** | **Final Polish & Release Readiness** | Quality | all | Small-medium |

Sequenced so that **irreversible data risk is retired first**, **data capture starts before
the features that consume it**, and **presentation comes last** — presentation built on
incomplete data has to be rebuilt.

### Sequencing decision requiring approval

**Recommendation: pull cost *capture* (not cost reporting) forward into Phase 2.**

Adding `unit_cost`/`total_cost` to the inflow API and dialog is two optional fields with zero
interaction with the integrity work. Cost *reporting* — supplier price history, rate trends,
valuation — stays in Phase 4 where it belongs. The reason to split them is that capture is
time-sensitive and reporting is not: data not captured in August cannot be reported in
October.

The alternative — keep all cost work in Phase 4 — is cleaner on paper and costs roughly two
months of unrecoverable purchase prices. **I recommend the split; confirm before Phase 2
scope is frozen.**

---

# Phase 2 — Production Hardening & Data Integrity

*Full technical spec: [MATERIALS_PHASE_2_HARDENING_PLAN.md](MATERIALS_PHASE_2_HARDENING_PLAN.md).
Summarised here for roadmap continuity.*

### Objective
Close every known route to permanent, silent stock corruption, and make the write path safe
under real-world concurrency and unreliable site connectivity.

### Business Value
Right now the system can quietly get your stock wrong in ways nobody notices until a count
doesn't match — and because material records can never be edited or deleted, only corrected,
a wrong number today is still wrong next year unless someone spots it and a manager fixes it.

Three specific ways that happens today: a correction can be applied twice (leaving stock
wrong by double the original amount), a slow connection can turn one delivery into two
identical records nobody can tell apart, and "Cement" typed with a capital C becomes a
different material from "cement" — splitting one stockpile into two half-empty ones.

After this phase, none of those are possible. This is the phase that makes the module
trustworthy enough to run a site on.

### Scope
**Included:** duplicate-reversal prevention (DB constraint + friendly error); request
idempotency for web/mobile writes; case-insensitive material names with a reviewed merge of
existing duplicates; over-stock confirmation on outflows with correct concurrency handling;
performance indexes for the list queries; the concurrency audit's advisory-lock mitigation.
**Plus, if the sequencing decision is approved:** optional `unit_cost`/`total_cost` on the
inflow API and dialog, with `total_cost` auto-calculated and editable.

**Excluded:** all reporting and analytics; supplier linking; images; alerts; any UI beyond
what these guards require; the `PATCH` unit-lock race (documented as an accepted low risk).

### Files Expected To Change
Backend: `domains/materials/router.py`, `repositories/materials.py`,
`domains/materials/responses.py`, one new migration.
Frontend: `lib/materials.ts`, `record-inflow-dialog.tsx`, `record-outflow-dialog.tsx`,
`correction-dialog.tsx`, `movement-details-sheet.tsx`, `inventory-view.tsx`.

### Backend Work
Already-reversed pre-check returning 409 on both reverse endpoints, with the database partial
unique index as the authoritative guard and `IntegrityError` mapped to the same 409.
`Idempotency-Key` header support reusing the existing `idempotency_keys` claim pattern from
the CQRS path — no new abstraction. Case-insensitive `get_by_name`. New
`GET /materials/stock-check` and an optional `allow_negative` flag on outflows, protected by
`pg_advisory_xact_lock` on `(site_id, material_id)` so the check cannot be defeated by two
simultaneous requests.

### Frontend Work
Idempotency key generated when a dialog opens (not per click), submit lockout, available-stock
display and an inline over-stock confirmation step in the outflow dialog, "Correct" hidden on
already-corrected movements, 409s handled without losing typed input.

### Database Work
**One migration.** No new tables, no new columns *(except the two cost fields if the
sequencing decision is approved — and those already exist, they were simply never written)*.
Case-insensitive unique index on `materials_catalog` after a reviewed duplicate merge; partial
unique indexes on `reverses_movement_id` for both operational tables; two composite indexes
matching the inflow/outflow list access pattern. Steps that touch data abort with the offending
ids rather than guessing.

### APIs
**Reused:** all authorization helpers, `post_material_movement`, every repository.
**Modified:** both POST endpoints (optional header/flag), both reverse endpoints (409 on
repeat), `GET /materials/inventory` (pagination — see Phase 3 note below).
**Added:** `GET /materials/stock-check` — justified because no existing endpoint returns one
material's balance without fetching the entire inventory list.

> **Scope boundary note:** the Phase 2 plan document included inventory pagination. In this
> roadmap that work moves to **Phase 3**, where it sits with the rest of the inventory
> experience. Phase 2 keeps only the integrity and safety work. This keeps Phase 2's diff
> reviewable and its rollback clean.

### Risks
**Technical:** the duplicate-catalogue merge is the only irreversible step in the whole
roadmap — dry-run against a production snapshot, human-reviewed report, abort on ambiguity,
backup first. **Business:** the over-stock 409 changes existing API behaviour; recommendation
is to default it off for WhatsApp/mobile so only the dashboard tightens this phase.
**Regression:** an incorrect merge would repoint history to the wrong material — mitigated by
a stock-parity assertion proving every material's balance is identical before and after.

### Testing Plan
**Unit:** idempotency replay, double-reversal, case-variant rejection, stock guard boundaries.
**Integration:** two real concurrent connections proving exactly one of each competing pair
succeeds — plus a control test proving unlocked semantics are unchanged.
**Regression:** full backend, WhatsApp and dashboard suites; migration run against messy
seeded data with stock parity asserted.
**Manual:** record, correct, double-click, over-issue, verify Labour pages unchanged.

### Definition of Done
A movement cannot be reversed twice by any route including simultaneous requests; a
double-submitted record creates exactly one movement; case-variant names are impossible and
existing duplicates are merged with parity proven; over-stock requires confirmation and holds
under concurrency; all suites pass; zero files changed under Labour paths or `components/ui/`.

---

# Phase 3 — Inventory Experience & Scale

### Objective
Make inventory and the movement lists fast, searchable and filterable at real data volumes,
and unify the filtering experience across every Materials view.

### Business Value
Today the inventory screen loads **every single material at every single site, all at once**.
With a handful of sites nobody notices. With fifty sites and two years of history it gets
slower every month — there is no sudden failure, just a screen your storekeeper stops opening.

There is also no way to ask the obvious questions: "what did we receive last week?", "show me
just the cement", "which materials have gone negative?" The date filters actually already
exist in the system — the screens simply never used them.

After this phase, finding anything takes seconds regardless of company size, and the module is
ready to grow with the business rather than degrade as it does.

### Scope
**Included:** server-side pagination, search and stock-state filtering on inventory;
server-computed KPI summary; date-range filtering wired into inflows, outflows and purchases;
one shared filter bar and one shared pagination control across all Materials views; query
optimisation; distinct empty states for "nothing yet" versus "nothing matches".

**Excluded:** new columns or metrics; charts; export; saved filter presets; cross-site
aggregation views; anything requiring a schema change.

### Files Expected To Change
Backend: `repositories/materials.py` (`get_stock_levels` + summary), `router.py`,
`responses.py`.
Frontend: `inventory-view.tsx`, `inflows-view.tsx`, `outflows-view.tsx`,
`purchase-history-view.tsx`, `lib/materials.ts`; new `materials/date-range-filter.tsx`,
`materials/table-pagination.tsx`, `materials/materials-filter-bar.tsx`.
Mobile: `src/services/materialsService.ts` (inventory response shape).

### Backend Work
`get_stock_levels` gains `search`, `stock_state`, `limit`, `offset` and returns
`(items, total, summary)`. **The summary is computed over the whole filtered set, not the
page** — this is the single most important correctness detail in the phase. Page clamping
when a filter change shrinks the result set.

### Frontend Work
Replace client-side slicing with server pagination; debounced search; the three existing views
adopt the shared filter bar so filtering behaves identically everywhere; KPI cards read the
server summary instead of counting the loaded array.

### Database Work
**None.** No schema change, no migration. Phase 2's indexes already cover these queries. Stated
explicitly because it makes this phase cheap to review and trivial to roll back.

### APIs
**Reused:** inflow/outflow list endpoints unchanged — `date_from`/`date_to` already exist and
are already scope-checked.
**Modified:** `GET /materials/inventory` gains filters and returns `{items, total, summary}` —
a breaking response-shape change with exactly two consumers, both in this repo, both updated
in this phase.
**Added:** none.

### Risks
**Technical:** pagination without the server-side summary would silently turn "Negative Stock:
7" into "Negative Stock: 2" — wrong numbers presented confidently, which is worse than the
current slow-but-correct screen. Guarded by a test asserting the summary across a multi-page
dataset. **Business:** none — no behaviour a user relies on is removed. **Regression:** the
inventory response shape change breaks mobile if missed; both consumers ship together.

### Testing Plan
**Unit:** pagination boundaries, page clamping, search matching, stock-state filter, and
explicitly that `summary` is set-wide rather than page-wide.
**Integration:** contract tests for the new response shape.
**Regression:** full suites; mobile inventory list verified against the new shape.
**Manual:** paginate a large seeded dataset, filter by date, search, confirm KPIs stay
constant while paging.

### Definition of Done
Inventory returns bounded pages with working search and filters; KPI cards reflect the whole
filtered set at every page; all three movement views filter by date through one shared control;
mobile still works; no schema change; all suites pass; Labour untouched.

---

# Phase 4 — AI Invoice & Purchase Capture

> **Full technical spec:** [MATERIALS_PHASE_4_INVOICE_CAPTURE_PLAN.md](MATERIALS_PHASE_4_INVOICE_CAPTURE_PLAN.md).
> Summarised here for roadmap continuity. Renamed from "Cost & Supplier Intelligence" —
> analytics and rate-trend reporting move to Phase 6.

### Objective
Let a site engineer photograph a supplier invoice in WhatsApp and have Mesiri read it, propose
the purchase conversationally, and — only after confirmation — create one purchase per
material, all linked to that one invoice, with inventory and purchase history updated. Built by
extending the media and understanding pipeline that already exists.

### Business Value
Materials are usually the largest line of spend on a construction project, and today the
system tracks quantities beautifully and money not at all — the Purchase History screen has a
"Total Purchase Value" box that shows a dash, because nothing has ever recorded a price.

The obvious fix is to make someone type prices in. The better fix is that they never type
anything: the delivery already arrives with a piece of paper listing exactly what came, how
much, and at what rate. Photograph it, check what Mesiri read, tap yes.

That is seconds instead of minutes, and it changes who can do the job — a storekeeper with a
phone rather than someone at a desk with a keyboard. It also means the data actually gets
captured, because the easy path and the correct path are the same path.

### Scope
**Included:** an invoice route in the existing "what is this photo for?" picker; line-item
extraction reusing the existing vision and extraction models; conversational confirmation
before anything is recorded; one purchase per material, all linked to one invoice; vendor
matching against the existing Vendors domain; an invoice attachment reference that will
resolve to a viewable document the day storage is connected; manual cost entry on the web
inflow dialog; Purchase History showing supplier, cost, invoice total, invoice date and a
reserved attachment slot.

**Excluded:** GST/HSN/bank/vehicle/tax/freight extraction (V1 field list only); purchase
orders, RFQs, approvals, payment tracking; permanent file storage (reference designed now,
provider connected later); web drag-and-drop invoice upload; supplier price-trend analytics
(Phase 6); inventory valuation/FIFO — ERP territory, out of V1.

### Files Expected To Change
AI platform: `adapters/gemini/adapter.py` (prompt text only).
WhatsApp: `channel/replies.py`, `canonicalization/`, `workflows/material/`,
`runtime/inbound_journey/`, `runtime/material_catalog_query.py`; new `vendor_match_query.py`.
Backend: `application/materials/`, `repositories/material_execution.py`,
`domains/materials/router.py` + `responses.py`, one migration.
Dashboard: `purchase-history-view.tsx`, `purchase-details-sheet.tsx`,
`record-inflow-dialog.tsx`, `lib/materials.ts`; new `invoice-attachment.tsx`,
`supplier-picker.tsx`.

### Backend Work
A `material_invoices` parent table with `material_receipts.invoice_id` as a nullable child
link — the same parent/lines/attachment shape `labour_execution.py` already uses for
attendance sheets. Multi-line execution inside the existing single transaction and idempotency
claim, so an invoice lands whole or not at all. Vendor matching mirroring the existing material
disambiguation. Manual `unit_cost`/`total_cost` on the inflow API.

### Frontend Work
Purchase History gains supplier, unit cost, line total, invoice total, invoice date and an
invoice column that shows a placeholder until storage is live — the slot is reserved now so no
redesign is needed later. Rows from one invoice group visually. Cost fields with live
calculation in the inflow dialog. NULL costs render "Not recorded", never ₹0.

### Database Work
**One migration.** New `material_invoices` table; nullable `invoice_id` FK on
`material_receipts`; supporting indexes. `unit_cost`/`total_cost` already exist and were simply
never written. No change to `material_movements` — the ledger and Phase 2's guarantees carry
over untouched. No backfill, no new attachment type (`BILL` already exists), therefore trivially
reversible.

### APIs
**Reused:** the entire Vendors API; `post_material_movement`; all authorization helpers; the
inflow list and detail endpoints.
**Modified:** `POST /materials/inflows` accepts `unit_cost`, `total_cost`, `vendor_id`,
`invoice_id`; `GET /materials/inflows` gains invoice/vendor filters.
**Added:** `POST /materials/invoices`, `GET /materials/invoices/{id}`,
`GET /materials/invoices/{id}/attachment`. Each does something no existing endpoint does; the
invoice endpoint composes the inflow logic rather than re-implementing it.

### Risks
**Technical:** the vision and extraction prompts are **shared with attendance, expenses and
equipment** — a careless edit degrades attendance-sheet transcription, which is Labour's
highest-value existing behaviour. Mitigated by additive-only edits, the existing prompt-parity
test, and before/after regression fixtures for every semantic type.
**Business:** a cement invoice is both a bill and a material receipt, so recording it as both
an expense and a purchase would double-count spend. V1 keeps them separate and does not
auto-create an expense from a material invoice.
**Regression:** `line_items` is additive; the existing single-material WhatsApp flow and all 46
assistant tests must pass unchanged.

### Testing Plan
**Unit:** line-item parsing at 0/1/15 lines; line totals legitimately not summing to invoice
total; NULL cost rendering; vendor matching; unit mismatch against Stock Unit; partial
confirmation.
**Integration:** fixture invoice through the full path to correct stock; rollback leaves
nothing; double-YES is idempotent; cross-org ids 404; document text containing instructions
changes no behaviour.
**Regression:** existing 46 WhatsApp and 45 backend tests unchanged; prompt-parity test;
extraction fixtures for expenses/attendance/equipment score no worse; Vendors and Labour suites.
**Manual:** real invoices — clean, poorly lit, handwritten challan, multi-page, no prices, and
one with an uncatalogued material.

### Definition of Done
Photographing an invoice produces the specified summary; nothing records before confirmation;
confirmation creates one purchase per material linked to one invoice with inventory updated;
only V1 fields extracted; vendors matched and never duplicated; every purchase carries an
invoice reference that will work the day storage connects, with no Materials change; no new
OCR/AI/WhatsApp pipeline exists; existing extraction quality is unchanged with evidence; all
suites pass; Labour untouched and verified.

---

# Phase 5 — Material Details & Timeline

### Objective
Give every material a single page answering "what is this, where is it, what has happened to
it, and what does it cost" — consolidating data that exists today but is scattered across four
screens.

### Business Value
Today, understanding one material means visiting Inventory for the balance, Inflows for
deliveries, Outflows for consumption, Purchase History for prices, and the ledger sheet for
the audit trail. Five places for one question.

This phase creates one page per material: current stock at every site, full movement history,
purchase prices over time, who supplied it, and a photo so the person receiving it can confirm
they are looking at the right thing. When there is a dispute about what arrived or where it
went, it is all on one screen with dates and names attached.

### Scope
**Included:** a material detail page (stock across sites, movement timeline, cost history,
supplier list, catalogue metadata); a unified timeline reusing the existing ledger data;
material images (one primary image per catalogue entry) reusing the existing attachment and
object-storage infrastructure; deep links from Inventory, Inflows, Outflows and Purchase
History.

**Excluded:** multiple images or galleries per material, document attachments (spec sheets,
certificates), per-material notes or comments, barcode/QR, material variants or grouping,
editing history from the detail page (corrections keep their existing flow).

### Files Expected To Change
Backend: `domains/materials/router.py`, `repositories/materials.py`, `responses.py`, one
migration; read-only reuse of `domains/shared/media.py` and the existing object-storage adapter.
Frontend: new `pages/MaterialDetailPage.tsx` plus `materials/material-detail-*.tsx` components;
`App.tsx` route; link additions across the four existing views; `catalogue-view.tsx` for image
upload.

### Backend Work
One detail endpoint assembling catalogue metadata, per-site stock and recent movements —
composed from existing repository methods rather than new SQL where possible. Image upload and
retrieval reusing the existing attachment pattern, including `assert_downloadable_url` so a
misconfigured storage adapter fails loudly instead of rendering broken images. Cost history
reuses Phase 4's queries.

### Frontend Work
A detail page with tabbed sections (Overview / Movements / Purchases / Suppliers), a timeline
component reusing the existing ledger fetch and its running balance, image upload in the
catalogue view with client-side resize and type/size validation, and clickable material names
everywhere they already appear.

### Database Work
**One migration** adding a nullable `image_url` (or attachment reference, matching the pattern
`expenses`/`progress` already use — to be confirmed against that code at implementation time)
to `materials_catalog`. Nothing else. No change to any movement or ledger table.

### APIs
**Reused:** ledger, inventory, inflow/outflow list endpoints; the existing attachment upload
flow.
**Modified:** `PATCH /materials/{id}` accepts the image reference.
**Added:** `GET /materials/{id}/details` — one round trip instead of five, justified by mobile
and slow-connection use.

### Risks
**Technical:** a detail endpoint composing five queries is the easiest place in the roadmap to
create an accidental N+1 or an unbounded fetch — movement lists must be capped and paginated
from day one, not "for now". **Business:** low; this is presentation of existing data.
**Regression:** image handling touches shared media infrastructure used by expenses and
progress — read-only reuse only; if a shared media file needs modifying, work stops and it is
reported first.

### Testing Plan
**Unit:** detail assembly with missing data (no movements, no cost, no image), authorization
scoping on the detail endpoint, image validation.
**Integration:** detail endpoint returns consistent stock versus the inventory endpoint for the
same material — a real divergence risk worth an explicit assertion.
**Regression:** full suites plus expenses/progress attachment regression, since media infra is
shared.
**Manual:** open a material from every entry point, upload an image, verify the timeline
matches the ledger sheet exactly.

### Definition of Done
Every material has a detail page reachable from all four views; stock shown there always
matches the inventory screen; images upload and display, with clear failure when storage is
misconfigured; movement history is paginated; all suites pass; Labour and shared media
consumers untouched.

---

# Phase 6 — Dashboard, Analytics & Alerts

### Objective
Turn the accumulated data into the small number of signals that actually change a decision —
and tell people about problems instead of waiting to be asked.

### Business Value
Everything so far requires someone to go and look. This phase makes the module speak up: which
sites are about to run out, which materials keep going negative (usually a sign of unrecorded
deliveries rather than theft), where spend is concentrated, and which suppliers you depend on.

The key discipline is restraint. A dashboard with thirty charts gets ignored the same way no
dashboard does. This phase ships a small number of things a site manager would act on the same
day.

### Scope
**Included:** a Materials overview with a handful of decision-driving cards (stock health,
recent purchase value, top materials by consumption, negative-stock exceptions); consumption
and purchase trend over a selectable period; a low-stock threshold per material with an alert
when crossed; a negative-stock exception list; alert delivery reusing the existing automations
infrastructure.

**Excluded:** forecasting, reorder-point calculation, automatic purchase suggestions, ML or
anomaly detection, custom report builders, scheduled email reports, cross-module dashboards,
export to Excel/PDF (candidate for Phase 7 or post-V1).

### Files Expected To Change
Backend: `domains/materials/router.py`, `repositories/materials.py`, `responses.py`, one
migration; read-only integration with `domains/automations/`.
Frontend: new `materials/materials-overview.tsx` and chart components; `MaterialsPage.tsx`
(new Overview tab); `catalogue-view.tsx` (threshold field).

### Backend Work
Aggregation endpoints computing stock health, consumption trend and purchase trend over a date
range — server-side aggregation only, never "fetch everything and sum in the browser", which is
the mistake Phase 3 exists to undo. A per-material reorder threshold on the catalogue and an
evaluation that fires when a movement crosses it, delivered through existing automations rather
than a new notification system.

### Frontend Work
An Overview tab as the Materials landing view, using the existing chart library already present
in the dashboard (confirm which at implementation time — do **not** add a second charting
dependency). Threshold configuration in the catalogue. An exceptions list linking straight to
the relevant material detail page.

### Database Work
**One migration** adding a nullable `reorder_threshold` to `materials_catalog`. Nullable means
alerts are opt-in per material, which is correct — a threshold guessed by the system produces
noise, and an alert people learn to ignore is worse than no alert.

### APIs
**Reused:** inventory, movement and cost queries; the automations dispatch path.
**Modified:** `POST`/`PATCH /materials` accept `reorder_threshold`.
**Added:** `GET /materials/analytics/summary` and `GET /materials/analytics/trends`. Justified:
these are genuine aggregations; computing them client-side would reintroduce exactly the
unbounded-fetch problem Phase 3 removes.

### Risks
**Technical:** analytics queries scan more history than anything else in the module — they must
be date-bounded by default and index-supported, with a maximum range enforced server-side.
**Business:** alert fatigue. Thresholds are opt-in, alerts are deduplicated, and an alert fires
on crossing rather than on every subsequent movement below the line. **Regression:** touching
automations affects a shared subsystem — read-only integration through its public dispatch
path, no modification to automations code; if that proves impossible, work stops and it is
reported.

### Testing Plan
**Unit:** aggregation maths including empty and single-row periods, threshold crossing
(including crossing back up, and no re-fire while still below), date-range clamping.
**Integration:** analytics figures reconcile exactly with the inventory and purchase screens —
two numbers disagreeing on the same fact is the classic dashboard failure.
**Regression:** full suites plus an automations regression run.
**Manual:** set a threshold, drive stock below it, confirm exactly one alert; verify trend
charts against hand-calculated values on seeded data.

### Definition of Done
The overview surfaces stock health, spend and consumption from server-side aggregation;
figures reconcile with the detailed screens; thresholds are configurable and alerts fire once
per crossing; no new charting dependency; all suites pass; automations and Labour untouched.

---

# Phase 7 — Final Polish & Release Readiness

### Objective
Close the gap between "all features work" and "this is ready to hand to a construction company
that has never seen it before."

### Business Value
The difference between software people tolerate and software people trust is almost entirely in
this phase: messages that say what to do rather than what failed, screens that work on the
phone a storekeeper actually holds, nothing that spins forever without explanation, and help
text where a new user gets stuck.

This is also where a fresh pair of eyes goes over the whole module for anything the
feature-by-feature work missed — the seams between phases, not the phases themselves.

### Scope
**Included:** an error-message pass converting developer language to instructions ("Cement is
tracked in bags — change the unit to bags to record this"); consistent loading, empty and error
states across every view; mobile-responsive verification of every screen on real dimensions;
keyboard and screen-reader accessibility on the core flows; help text and tooltips for
construction-specific concepts (Stock Unit, why corrections cannot be deleted, what negative
stock means); performance verification against a realistically large seeded dataset; a
full-module security and permissions review; documentation refresh (`AGENTS.md`, the module
plan docs); removal of any dead code the roadmap left behind.

**Excluded:** new features of any kind; visual redesign; internationalisation; a design system
refactor; anything requiring a schema change.

### Files Expected To Change
Broad but shallow: every `components/materials/*` file, `lib/materials.ts`,
`domains/materials/router.py` (error detail strings only), docs. **Low regression risk by
construction** — this phase changes wording, states and styling, not logic.

### Backend Work
Rewrite `HTTPException` detail strings for a non-technical audience while keeping status codes
and machine-readable structure unchanged. Verify every endpoint applies organization and
project/site scoping — a full-module authorization sweep now that the surface is complete.
Confirm no endpoint can return unbounded results.

### Frontend Work
One loading pattern, one empty-state pattern, one error-state pattern across all views. Mobile
verification at real breakpoints. Focus order, labels and keyboard operability on record,
correct and search flows. Contextual help where domain concepts appear.

### Database Work
**None.** No schema change, no migration. Stated explicitly.

### APIs
**Reused:** everything. **Modified:** error message text only — no contract, status code or
field change. **Added:** none.

### Risks
**Technical:** very low; the main risk is scope creep, since "polish" attracts feature
requests — anything discovered that is not polish gets logged for post-V1, not built.
**Business:** none. **Regression:** message-text changes can break tests asserting exact
strings — those assertions get updated deliberately, not loosened to make them pass.

### Testing Plan
**Unit:** updated assertions for changed messages.
**Integration:** authorization sweep across every Materials endpoint with a
deliberately under-privileged caller.
**Regression:** full suites; performance run against a large seeded dataset with timings
recorded.
**Manual:** complete end-to-end walkthrough on desktop and mobile, ideally with someone who
has not used the module — the only reliable test of whether the help text works.

### Definition of Done
Every error tells the user what to do next; loading, empty and error states are consistent;
every screen works on a phone; core flows are keyboard-accessible; performance verified at
scale with numbers recorded; authorization verified endpoint by endpoint; docs current; no dead
code; all suites pass; Labour untouched.

---

## Git workflow — applies to every phase, without exception

**Work directly on `main` — no feature branches.** `main` is what deploys to the VPS, so work
parked on a branch reaches nothing. The trade-off is that there is no branch acting as a safety
net, which makes the verification step below non-negotiable rather than a formality.

**At phase start**
1. `git pull` on `main`; resolve conflicts; verify the build and full test suite pass **before
   any new work** — so a pre-existing failure is never mistaken for one I introduced.
2. Check the current Alembic head and **claim the migration number explicitly** (see Standing
   Risks). Migrations run automatically on deploy, so a wrong number breaks production, not a
   branch.

**During**
3. Implement only the approved scope. Anything else discovered is logged, not built.
4. Clean, logical commits — one concern each, present-tense messages explaining *why*, matching
   the existing repo style (`feat(materials):` / `fix(materials):`).

**At phase end — all of it, before pushing**
5. Full automated suite: backend, WhatsApp, dashboard build + typecheck + lint.
6. Manual verification per that phase's testing plan.
7. **Labour isolation check:** the diff must show zero files under `workforce/`, `labour`,
   `attendance`, `payroll`, or `components/ui/` — plus a Labour suite run, reported.
8. `git pull` again (others push constantly); re-verify if it brought changes.
9. Commit and push to `main`. Confirm the remote SHA matches local — tracking info can lie.
10. Report: commit hashes, commit messages, files changed, test results, Labour verification,
    **what could not be verified**, remaining risks.
11. **Stop. Wait for approval before the next phase.**

**Never:** a push with failing tests; `--no-verify`; a migration whose head was not re-checked
immediately before pushing; silence about a check that could not be run.

---

## Reporting template — after every phase

**Executive Summary** — what was accomplished, in plain English.

**Technical Summary** — files modified, files created, APIs changed, database changes, tests
executed with results, performance improvements, security improvements, remaining risks.

**Git Summary** — commit hashes and messages, push confirmation verified against the remote SHA.

**Founder Summary** — what users will notice, what improved, why this phase mattered, what
comes next. No jargon.

---

## Standing risks across all phases

**Alembic migration numbering — the one thing outside my control.** The head is `0456`, and
`0454`/`0456` are the Labour team's own migrations; they are adding more right now. Four phases
in this roadmap need a migration. If one is written against a head that Labour then moves, the
result is a **branched history that blocks deployment for both modules**. Mitigation: claim the
number at the start of each phase and notify the Labour team. **This needs an agreed
coordination method — it cannot be solved by care on my side alone.**

**Shared UI primitives.** `components/ui/*` is used by Attendance, Labour Overview and Labour
Analytics. Every new Materials component in this roadmap goes under `components/materials/` —
narrower reuse, zero blast radius. If a shared primitive genuinely must change, work stops and
it is reported first, as required.

**Shared subsystems.** Phase 5 reads shared media infrastructure; Phase 6 reads automations.
Both are read-only integrations through public interfaces. Same stop-and-report rule.

**Shared AI prompts (Phase 4).** `adapters/gemini/adapter.py`'s vision and extraction prompts
are shared by expenses, attendance, equipment and site updates. Phase 4 extends them, which
makes it the one phase whose changes could degrade Labour's attendance-sheet transcription
without touching a single Labour file. Additive edits only, the existing prompt-parity test must
pass, and before/after extraction fixtures are run for every semantic type. If the `workers`
block itself ever needs changing, work stops and it is reported.

**Phase 1 is uncommitted.** `purchase-history-view.tsx`, `purchase-details-sheet.tsx` and edits
to `AGENTS.md` / `MATERIALS_CATALOGUE_PLAN.md` are sitting in the working tree, in a directory
other agents also touch. These should be committed or confirmed as ours **before Phase 2
starts**, so each phase's diff is reviewable in isolation.

**Scope discipline.** Every phase has an explicit exclusion list. The most likely failure mode
for this roadmap is not technical — it is Phase 4 drifting toward purchase orders or Phase 6
drifting toward forecasting. Both are explicitly out of V1.

---

## Decisions required before Phase 2 begins

1. **Cost capture in Phase 2?** Recommended: yes, capture only (two optional fields), reporting
   stays in Phase 4. Every week of delay is unrecoverable purchase-price history.
2. **Inventory pagination moved from Phase 2 to Phase 3** — confirm this regrouping.
3. **Over-stock guard default** — recommended `allow_negative` defaults to on for
   WhatsApp/mobile so only the dashboard tightens in Phase 2.
4. **Alembic coordination method** with the Labour team.
5. **Commit Phase 1 before Phase 2 starts?**
6. **Phase 4:** expense vs material invoice — recommended: keep separate in V1, sharpen the
   picker wording, never auto-create an expense from a material invoice (double-count risk).
7. **Phase 4:** which roles can see cost figures?
8. **Phase 4:** partial confirmation of an invoice (record matched lines, skip unmatched) —
   recommended yes.

*Full Phase 4 decision list in [MATERIALS_PHASE_4_INVOICE_CAPTURE_PLAN.md](MATERIALS_PHASE_4_INVOICE_CAPTURE_PLAN.md).*

---

**Status: roadmap awaiting approval. No implementation begins until Phase 2's scope is
approved and frozen.**
