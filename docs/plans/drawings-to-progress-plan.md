# Drawings → Progress: plan

> **Status:** **V2** (decided by Ilan, 23 Oct 2026), so V1 reaches clients first. Nothing
> built. Mockups and sample WhatsApp cards are used to explain the concept in client demos.
> Tracker section: **DRW** in [V1_TRACKER.md](V1_TRACKER.md).
> Mockups (sample data, real drawing): footing plan, footing photo history, owner evening
> card, photo pinning, whole building, slab pour readiness, material check, milestone message.

## Objective

Turn a project's structural drawings into **the list of what has to be built**, so that
every DPR entry, photo and material movement counts *against* something. The daily report
stops being a diary and becomes progress: "footings 12 / 23 poured", "ground floor slab
72%, pour Friday, cement short by 420 bags".

## Business value

- **Owner:** sees the building fill in, level by level, with photos as proof, without
  reading a report.
- **Contractor:** knows before a pour what is missing (steel not tied, materials short,
  inspection not booked), so a costly pour doesn't fail halfway. Stage completion ties to
  the stage bill.
- **Site engineer:** no extra typing. "B5 poured" plus a photo is enough, and Mesiri answers
  with what the drawing requires.
- **Mesiri:** a reason to stay in the product from foundation to handover. Today we only
  cover the daily diary.

## What we found (investigation)

1. **The planning layer already exists and is empty.** `location_nodes` (0410, shared
   `core` tree), `work_packages` + `work_package_planned_items` (0420, with
   `completion_mode` NONE/QUANTITY/MILESTONE/MANUAL and revision history), and
   `activities.work_package_id` / `activities.location_id` (0430). These were designed in
   [DAILY_REPORTING_PLAN.md](../execution/DAILY_REPORTING_PLAN.md) as "Phase 9 — Work
   Packages" and never wired. **This plan is that Phase 9, fed by drawings.** No parallel
   planning tables.
2. **Photos already attach to activities** (`progress_attachments`, parent ACTIVITY). An
   activity with a `location_id` = a photo pinned to an element. No new photo store.
3. **AI goes through one gateway** (`platform/ai`: vision, extraction, tool-calling ports;
   Gemini, DeepSeek, OpenAI, Sarvam adapters; routing table, usage costs, fallbacks). Drawing
   reading is a new *route* on that gateway, not a new pipeline.
4. **The WhatsApp agent** (ADR "wrap, don't rebuild") turns messages into tool calls. Element
   progress is one more thin tool on it.
5. **Image and PDF rendering already exists** (Playwright, `channel/dpr_document`,
   `channel/receipt`). Plan images for WhatsApp use the same renderer.
6. **CAD-exported PDFs carry a text layer with exact coordinates.** On the Kondotty set
   (15 pages, De Framez), `pdftotext -bbox` gives every grid bubble (A–E, 1–9), every element
   label (`F1-250X250`, `C4`) and every schedule row (footing table, column `REINF`, slab
   table) as text with positions. Counting labels gives exactly 23 footings
   (F1×7, F2×3, F3×7, F4×2, F5×3, F6×1). A visual read had the F3 count wrong. **This is the
   core design choice: read the vector data first; use vision AI to understand and verify,
   never as the only source of a number.**

## How it works: the AI and non-AI parts

The rule for "perfect": **every number comes from the drawing's own data or from a
formula, never from a model's guess; every extracted value carries where it came from
(page + position); nothing is used until a person confirms it.**

| # | Step | What happens | How | AI? |
|---|---|---|---|---|
| 1 | **Upload** | PDF arrives from the dashboard or as a WhatsApp document | Stored like photos (VPS disk / R2 setting); hashed to avoid duplicates | No |
| 2 | **Read the file** | Text with coordinates, lines and rectangles; each page also rendered to an image | `pdfplumber` / `pypdfium2` (vector); `pdftoppm`-style render for the review screen | No |
| 3 | **Sort the pages** | Which pages are key plans, schedules, sections; which level each plan is (footing, basement, ground floor…) | Title-block text first ("KEY PLAN - GROUND FLOOR", drawing no. `66/ST/03/01`, date, revision); **Gemini Flash** (vision port) classifies the page image and must agree with the text | Yes, verified |
| 4 | **Read the schedules** | Footing table, column schedule, slab table, beam marks into structured rows | Table parsing from text positions; **Gemini Pro** (extraction port, JSON schema) structures the same table from the image. **Both must agree**; any difference goes to review | Yes, cross-checked |
| 5 | **Find elements on plans** | Each footing/column at its grid point; each slab panel between beams | Deterministic: grid bubbles + element labels + rectangles from vector paths → "F1 at B5". The model only names what can't be read (fallback, flagged) | Mostly no |
| 6 | **Quantities** | Concrete m³, steel kg per bar size, shuttering m² | Plain formulas from confirmed specs (A×B×D, n × length × d²/162). Mix ratios per company setting | No |
| 7 | **Review** | Overlay of found elements on the real drawing page; the engineer confirms or fixes; counts per type shown next to the schedule | Dashboard screen. Creates `location_nodes` (Building → Level → Element) and `work_packages` only on confirm | Human |
| 8 | **Daily reporting** | "B5 poured", "C3 at B3 steel done", Malayalam voice, a photo with caption | Existing agent (Gemini function calling) + new tool `report_element_progress`; a deterministic grid-reference parser runs first; voice through the existing speech port (Sarvam). Unclear → buttons, never a guess | Yes, existing |
| 9 | **Photo → element** | Photo pinned to the element named in the caption or the last message; else Mesiri asks which one | Same agent tool; records an activity with `location_id` + attachment | Partly |
| 10 | **Photo stage hint** *(later)* | "This looks like steel mesh, not poured concrete" | Gemini vision suggestion shown as a hint; bar counting only after an eval proves it (same approach as the labour photo eval) | Yes, gated |
| 11 | **Images** | Coloured plan, whole-building view, evening owner card | SVG built from confirmed geometry → PNG via the existing Playwright renderer. **No generative image AI**: it invents details | No |
| 12 | **Forecasts and readiness** | "Footings done by ~1 Nov", "cement short by 420 bags" | Pace arithmetic; quantities vs `material_inventory` stock (read only) | No |
| 13 | **Questions** | "Send me the column details" | Agent tool returns the right sheet (or a crop) from the register | Yes, existing |

Models are chosen on the control panel's routing table (a new `drawing_extraction`
route), costs land in the BE-25 usage rows like every other call, and a drawing set is read
once, not per message.

## Scope, in order

| Step | Delivers | Tracker |
|---|---|---|
| 0 | Golden set: this drawing set + 10 more from customers (different consultants draw differently), with hand-checked answers; an eval script | DRW-01 |
| 1 | **Drawing register**: upload (dashboard + WhatsApp), sheet list with number/title/revision/date, newer revision supersedes, "send me drawing X" on WhatsApp | DRW-02 |
| 2 | **Extraction** of footings, columns, slab panels, schedules, with provenance and confidence | DRW-03 |
| 3 | **Review screen**: overlay, confirm/fix, creates the element tree | DRW-04 |
| 4 | **Element progress from WhatsApp** + photo pinning | DRW-05 |
| 5 | **Plan view per level + whole-building view** on the dashboard | DRW-06 |
| 6 | **Evening owner card** image on WhatsApp | DRW-07 |
| 7 | **Stages** = `work_packages` in MILESTONE mode (Phase 9 wiring) | DRW-08 |
| 8 | **Quantities, pour readiness, material check** against stock | DRW-09 |
| Later | Stage bills (finance), revision diff ("Rev B changed F1 depth; 3 poured footings affected"), photo stage hints, beams as elements, 3D view | DRW-10 to DRW-12 |

**Concierge first:** for the first customers, the Mesiri team does step 3 (review) for them.
Accuracy is proven on real projects before contractors self-serve.

## Backend work

- New `drawings` domain (router, application service, repository), following the
  `progress` domain's shape. Upload, sheet list, review actions and element list endpoints.
- Extraction job on the existing ARQ worker (not in the request): read → classify → extract
  → write drafts → notify.
- Element progress service: writes `activities` (with `location_id`) through the existing
  progress execution path, plus attachments. No second activity writer.
- Phase 9: wire `work_packages`/`planned_items` (QUANTITY + MILESTONE modes, mode badge per
  ADR-D10).

## Frontend work (dashboard)

Drawings page (register + review overlay), level plan view, whole-building view, element
side panel with photo history, pour readiness card. Same design system tokens.

## Database work (additive only)

- `project_drawings` (file, hash, uploaded by, status).
- `drawing_sheets` (drawing, page, sheet number, title, revision, date, level, page image
  key, review status).
- `drawing_elements` (sheet, `location_node_id`, element type, mark e.g. F1, grid ref,
  position on page, `spec_json`, confidence, confirmed by/at).
- Step vocabulary per element type (footing: excavation → PCC → steel → shuttering → pour;
  slab panel: shuttering → steel → conduits → pour), seeded as construction defaults like
  BE-24.
- **Reused:** `location_nodes`, `work_packages`, `work_package_planned_items`, `activities`,
  `progress_attachments`, `units_of_measure`, material inventory (read only).
- Every new table gets the tenant row-level security policy (0484). That is
  security-sensitive, so it needs approval per CLAUDE.md.

## API work

`POST /projects/{id}/drawings`, `GET /projects/{id}/drawings`, `GET /drawings/{id}/sheets`,
`POST /sheets/{id}/review` (confirm / fix elements), `GET /projects/{id}/elements?level=`,
`GET /projects/{id}/progress/building`. Agent tools: `report_element_progress`,
`send_drawing`.

## Code layout

Mapped against the current code on 24 Oct 2026 (after ARCH-06: the classic pipeline is gone,
every company runs the agent, and agent tools call services directly).

### Data flow

```
SETUP (once per project)
Dashboard upload / WhatsApp PDF
  → backend drawings API ── stores file, writes DrawingUploaded (outbox)
  → background job: pdf_reader → domain rules (grid, schedules) → AI cross-check
  → drafts saved ── reviewer notified
  → review page → ConfirmSheetReview command
  → location_nodes (Building → Level → Element) + drawing_elements + work_packages
  → DrawingElementsConfirmed (outbox)

EVERY DAY
WhatsApp "B5 poured" + photo
  → agent → report_element_progress → element_entry.py
  → backend progress service: activity with location_id + progress_attachments
  → activity event → DPR, timeline, evening card react
```

Core rules kept (Core-architecture.md): AI only writes drafts, a person's confirm writes the
records; business rules in `domains/` with no SQL; every write emits its event through the
outbox in the same transaction; downstream (timeline, cards) reacts to events; Labour untouched.

### Files by layer

**Shared contracts:** `shared/contracts/src/mesiri_contracts/events/schemas/`: event schemas
`DrawingUploaded`, `DrawingSheetsExtracted`, `DrawingElementsConfirmed`,
`ElementProgressRecorded`.

**AI:** `platform/ai/src/mesiri_ai/`: reuse the vision port (page classification) and the
extraction port (table structuring); add a `drawing_extraction` route in `resolver.py` so the
control panel picks the model and BE-25 records the cost. If neither port can return a
schema-bound result from an image, extend the vision port with one method; no new port, no
second pipeline. Decide during DRW-03's investigation.

**Backend:** `backend/src/mesiri/`

| Where | File | Job |
|---|---|---|
| `infrastructure/drawings/` | `pdf_reader.py` | Words, lines and rectangles with positions per page (pdfplumber / pypdfium2) |
| | `page_render.py` | Page → PNG for review, stored through `infrastructure/objectstorage` |
| `domains/drawings/` | `grid.py` | Grid bubbles, element labels placed at intersections. Pure, no SQL |
| | `schedules.py` | Footing / column / slab tables from positioned words |
| | `elements.py` | Element and element-type rules, step vocabulary per type |
| | `quantities.py` | Concrete, steel, shuttering formulas |
| | `router.py`, `responses.py` | API endpoints and shapes (same pattern as `domains/progress/`) |
| `application/drawings/` | `handlers.py` | Upload, confirm review, fix element: transaction + outbox |
| | `extraction.py` | Job: reader → domain rules → AI cross-check → drafts |
| | `repository.py` | Port the application depends on |
| `application/progress/` | extend `handlers.py` | Record element progress (activity with `location_id`); Phase 9 work-package wiring |
| `infrastructure/postgres/repositories/` | `drawings.py`, `drawing_execution.py`, `work_packages.py`, `locations.py` | SQL |
| `migrations/versions/` | `04xx_drawings_register_and_elements.py` | `project_drawings`, `drawing_sheets`, `drawing_elements`; additive; RLS policies (approval) |
| `http/app.py` | one `include_router` | Wire the drawings router |

The extraction job is triggered by `DrawingUploaded`. Which worker process hosts backend
jobs today must be checked before DRW-03 places it.

**WhatsApp assistant:** `apps/whatsapp-assistant/src/`

| Where | File | Job |
|---|---|---|
| `runtime/agent/tools.py` | add 2 tool specs | `report_element_progress`, `send_drawing` |
| `runtime/agent/` | `element_entry.py` | Same shape as `site_entry.py`: sender scope → resolve the element among confirmed ones → backend service; `ask_user` buttons when unclear |
| | `element_ref.py` | Deterministic parser: "B5", "C3 at B3", "B-5 footing", typos |
| `ingress/` | extend | Inbound PDF document → drawing upload |
| `channel/cards/` | `plan_svg.py`, `footings.py`, `pinned.py`, `building.py`, `pour_check.py`, `milestone.py` | The five cards on the existing `base.html` + renderer |
| `runtime/send_pending_notifications.py` | extend | Evening card in the existing evening flow |

Photos were kept out of the agent by the ADR; pinning a photo to an element changes that and
needs Alan's approval.

**Dashboard:** `apps/dashboard/src/`: `pages/DrawingsPage.tsx` (register, upload),
`pages/DrawingReviewPage.tsx` (overlay, confirm/fix), `pages/BuildingPage.tsx` plus a plan tab
in the project page, `components/drawings/` (`plan-svg.tsx`, `element-panel.tsx`,
`pour-readiness-card.tsx`), additions in `lib/api.ts`.

**Tests and eval:** `backend/tests/unit/drawings/` (grid, schedules, quantities); integration
tests that RLS blocks other companies on the new tables; `apps/whatsapp-assistant/tests/` for
`element_entry` with a golden set of real phrasings (as in ARCH-02); `scripts/eval_drawings.py`
scoring extraction against hand-checked answers. **Customer PDFs never go in the repo** (the
consultant owns them): keep them in private storage; commit only synthetic samples and the
expected answers.

### Commit order

1. Tables + `pdf_reader` + grid/schedule rules + eval script (no user-visible change; proves
   accuracy).
2. Upload + extraction job + review page.
3. WhatsApp tool + photo pinning.
4. Cards + evening card.
5. Phase 9 stages + pour readiness + materials.

One tracker item per step (DRW-01 to DRW-09), each behind the per-company switch.

## Risks

| Risk | Mitigation |
|---|---|
| Scanned or photographed drawings have no text layer | Vision-only path, every value flagged for review; tell the customer CAD PDFs work best |
| Each consultant labels differently (`F1-250X250` vs a separate legend) | Golden set from many consultants before claiming accuracy; unknown formats fall back to review |
| A wrong element list poisons every % after it | Nothing is used until confirmed; counts shown next to the schedule; revisions keep history (ADR-D5) |
| Engineers won't name elements in messages | The agent asks with buttons for the nearest unfinished elements; photo stage hint later |
| Scope creep past V1 DPR | Ship behind a per-company flag; the DPR keeps working with zero drawings (P4) |
| Model cost | One read per drawing set; routed and metered like other calls |

## Testing strategy

Golden-set eval (exact counts per type, schedule values, grid refs; target: zero silent
errors, every miss flagged); unit tests for the grid parser, formulas and step vocabulary;
repository tests for RLS on the new tables; agent tool tests in the WhatsApp suite;
end-to-end on the test company with the Kondotty set; regression run of the DPR suite
(activities without a location must still behave exactly as today).

## Rollback strategy

Per-company switch (like `assistant_mode`), off by default: off = no drawings UI, no agent
tool, DPR unchanged. New tables are additive and unused when off; each step is its own
commit, revertible. No existing data is rewritten.

## Labour isolation

No change to Labour, Attendance, Payroll or Workforce. The evening card reads the worker
count from the existing DPR data, read only.

## Success criteria

- Golden set: element counts and schedule values exact after review on ≥ 10 drawing sets;
  no value used without a person's confirmation.
- Review of a 15-page set takes a person under 15 minutes.
- On a live site: ≥ 80% of footing/column/slab progress messages pinned to the right element
  without a follow-up question.
- An owner can tell where the building is from one image.

## Decisions needed (Alan / Ilan)

1. ~~Scope~~ **Decided 23 Oct: V2.**
2. **Drawings:** can we collect 5–10 real structural sets from customers for the golden set?
3. **Who reviews extraction** for the first customers: the Mesiri team (concierge) or the
   contractor?
4. **Stage payments:** in scope (touches finance), or progress only for now?
5. **BOQ:** do customers have BOQs in Excel? If so, importing one may be a second source for
   quantities (step 8).
