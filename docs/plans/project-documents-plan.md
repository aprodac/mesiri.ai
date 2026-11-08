# Project documents and drawings (DMS): one register that the rest of Mesiri uses (Nov 2026)

> **Status:** plan, 8 Nov 2026 (asked in session by Ilan: "what about adding docs or diagrams and using that somewhere,
> DMS and all ... let's plan"). Part of the start of a project ([project-start-plan.md](project-start-plan.md), ST-08).
> Tracker items `DOC-01`..`DOC-08` in [V1_TRACKER.md](V1_TRACKER.md). Decisions D-DOC1..D-DOC4 below; each item uses the
> proposed default until Ilan answers.

---

## 1. The problem, in the contractor's words

| Who | Says today | What it costs |
|---|---|---|
| Site engineer | "Which is the latest column drawing? The one in the WhatsApp group from last month?" | Work built from a superseded drawing: demolish and redo, the most expensive mistake on site |
| Project manager | "The consultant mailed rev C; half the site still has rev B printouts." | Nobody is told a revision changed |
| Owner | "Where is the building permit? When does the CAR insurance run out?" | Permits and insurance lapse unnoticed; a stop-work notice or an uncovered accident |
| Office | "The client wants the as-built drawings and warranties at handover." | Days of searching email, WhatsApp and pen drives at the end of the job |
| Everyone | Sends a PDF to Mesiri on WhatsApp | Mesiri answers that it can't take documents yet (`channel/replies.py`): the file is lost |

**Mesiri's answer:** every project has one place for its papers. Drawings know their revision, and the site is told on
WhatsApp the moment one changes. Anyone can send a PDF to Mesiri, or ask "send me the latest column drawing" and get it
back in seconds. Permits remind before they lapse, and at handover the documents pack is already there.

## 2. Value per role

- **Site engineer:** always the current drawing, on the phone, in one message. No hunting in groups.
- **Project manager:** issues a revision once; Mesiri tells the site and marks the old one out of date.
- **Owner:** contract, permits and insurance in one place, with a reminder before anything expires.
- **Office / QS:** the estimate behind the BOQ, work orders, test reports and handover documents filed by themselves.

## 3. Investigation (Phase 1, `main` at `25ab8a6`)

| Area | Exists | Reuse |
|---|---|---|
| File storage | `ObjectStoragePort` (local disk on the VPS, R2 available, fake in tests), signed short-lived links (`domains/shared/media.py`, `media_router.py`) | Documents are objects under `documents/{org}/{project}/{doc}/{file}`; downloads are signed links. No new storage |
| WhatsApp media in | `ingress/media_handoff.py` downloads and stores every supported media (`media/{message}/{media_id}`); `ingress/normalization.py` maps `document` to UNKNOWN unless it is audio, so PDFs are declined | Map PDFs (and Office files) to the existing `InputModality.DOCUMENT` for v3 companies only; the stored key reaches the agent like a bill photo's (`PHOTO_FIELD`, `agent_api/bill_photo.py`) |
| WhatsApp media out | `channel/whatsapp/outbound.py` uploads and sends documents (PO PDF, PRC-26; DPR PDF) | `send_document` sends the stored file the same way |
| Attachments | `progress_attachments` (photos on site updates), expense bill photos, GRN challan photos, labour sheets | Stay where they are: they belong to their record. The register is for project papers, not every photo |
| Drawings plan (V2) | `drawings-to-progress-plan.md` proposes `project_drawings`; step DRW-02 is a drawing register | **This register is DRW-02.** `project_documents` (folder drawing) replaces `project_drawings`; DRW's `drawing_sheets` will reference it |
| Links | `work_packages` (schedule activities / BOQ sections), `work_orders`, `vendors`, `sites` | A document may point at one of each, nullable |
| Reminders | the one reminder pass (`application/procurement/alerts.queue_reminders`), the schedule notes (ST-06) | Revision alerts and expiry reminders are two more notes in the same pass |
| Upload | Excel imports post base64 JSON (5 MB cap); `python-multipart` is installed but unused | Documents up to 25 MB: multipart upload (base64 would add 33% and hold it all in memory twice) |
| PDF text | `pdftotext` exists on this machine; production VPS not checked | Read the first page's text (title block: drawing number, title, revision) with `pypdf` (pure Python) so it does not depend on the VPS; falls back to the file name |
| Module map | Planning › Documents, Planning › Drawings: `planned` | Documents becomes built; Drawings stays V2 (the AI reading) and links to Documents › Drawings |

## 4. Implementation plan (Phase 2)

**Objective.** One document register per project, with drawing revisions, used by the schedule, project start, BOQ,
work orders and WhatsApp, so the current drawing is always one message away and nothing expires unnoticed.

**Scope (this round).** DOC-01..DOC-06. **Later:** DOC-07 handover pack (with the end-of-project plan), DOC-08 search
inside documents, then DRW-03+ (AI reading of drawings), markup, comments.

**Database (migration 0523, additive; head is 0522 on 8 Nov: check again right before writing it).**
- `project_documents`: id, organization_id, project_id, site_id (nullable), **folder** (contract, drawing, approval,
  boq, work_order, test_report, handover, other), **discipline** (architectural, structural, mep, other; drawings only),
  **number** (drawing or document number, "S-101"), title, **revision** ("C"), revision_date, **status** (current,
  superseded, archived), supersedes_id, **valid_until** (permits, insurance, guarantees), **restricted** (money and
  contract papers, D-DOC1), object_key, file_name, content_type, size_bytes, sha256 (duplicate upload check), pages,
  source (web, whatsapp), uploaded_by, created_at; links: work_package_id, work_order_id, vendor_id (all nullable).
- One current document per project and number: partial unique index on (project_id, lower(number)) where status =
  current and number is not null.
- Row-level security like 0519/0522. Downgrade refuses while documents exist.

**API (backend `domains/documents/`).**
- `GET /projects/{id}/documents`: list (folder, status, q, site, activity), folder counts, expiring soon.
- `POST /projects/{id}/documents` (multipart): upload one or more files; folder, number, title, revision guessed from
  the file name and the first page's title block, editable. Duplicate (same sha256 in the project) is refused with a
  link to the existing one.
- `GET /documents/{id}`: detail, signed link, revision history (the supersedes chain).
- `PATCH /documents/{id}`: folder, number, title, revision, dates, links, restricted, valid_until.
- `POST /documents/{id}/revisions` (multipart): a new revision; the old one becomes superseded; the revision alert is
  queued (DOC-02).
- `DELETE /documents/{id}`: archive (kept, hidden), never a hard delete from the dashboard.
- `GET /projects/{id}/documents/find?q=`: the best current matches for "latest column drawing", "building permit"
  (number, title, folder, discipline words; current revisions first). Used by WhatsApp.
- `POST /documents/{id}/send`: send the file on WhatsApp to the asker (or to a team member), through the outbound
  channel (DOC-05).
- v3 `ALLOWED`: `list_documents`, `find_documents`, `save_document` (write, held for Save), `send_document`; SOP rule:
  a PDF or a drawing photo sent with words like drawing / permit / agreement / rev is offered as a document to save;
  "send me the latest X" is `find_documents` then `send_document`; a bill stays an expense (rule unchanged).

**Frontend (dashboard).**
- **Planning › Documents** (`/planning/documents`): folders with counts on the left (Drawings split by discipline);
  list with number, title, revision chip, date, who uploaded and how (web or WhatsApp), linked activity; search and
  filters; "Expiring soon" strip; drag-and-drop upload of many files with the guessed number, title, revision and folder
  shown for a quick check before saving; detail panel with an inline PDF / image preview, revision history, "Upload new
  revision", links, expiry. Phone: list and bottom sheet, like the other pages.
- **Connections:**
  - Schedule activity panel: a "Drawings and documents" section (linked to that activity), current revision shown.
  - Project start: a step "Contract and drawings" (done when the contract and at least one drawing are in).
  - BOQ import: the uploaded estimate is kept as a document (folder boq) so the BOQ's source is always there.
  - Work order page: its documents (signed work order, the subcontractor's drawings).
  - Projects list: nothing new (kept quiet).
- Module map: Planning › Documents built; Planning › Drawings stays V2 and points to Documents › Drawings.

**WhatsApp (DOC-04/05/06).**
- **In (v3 companies only):** a PDF or Office file is stored by the existing media hand-off; the agent gets its name,
  pages and first-page text; it prepares `save_document` (folder, number, revision guessed) and the person taps Save.
  Classic companies keep today's reply (no regression for customers not on v3).
- **Out:** "send me the latest column drawing" / "building permit evide?" finds the current document and sends the
  file. A restricted document is sent only to the roles that may see it.
- **Revision alert:** a new revision of a drawing tells the site team and the PM on WhatsApp: "New structural drawing
  S-101 rev C for Green Villa. Rev B is out of date: use rev C." with the PDF when inside the 24-hour window, text and a
  dashboard link otherwise.
- **Expiry reminder:** 15 days and 3 days before `valid_until`, to owner / admin: "Building permit for Green Villa
  expires Thu 3 Dec."

**Files expected to change.** New: `backend/migrations/versions/0523_project_documents.py`,
`backend/src/mesiri/domains/documents/{__init__,store,router,reminders,naming}.py`, tests (unit + contract),
`apps/dashboard/src/pages/DocumentsPage.tsx`, `apps/dashboard/src/lib/documents.ts`,
`apps/dashboard/src/components/documents/*`, `apps/whatsapp-assistant/tests/agent_api/test_api_documents_doc04.py`.
Changed: `http/app.py` and `runtime/lifecycle.py` (mount the router in both), `agent_api/{tools,app,SOP,links,
record_links,receipts}.py`, `ingress/normalization.py` (DOC-04, needs approval), `application/procurement/alerts.py`
(two notes), `domains/progress/boq_import.py` (keep the source file), schedule activity panel, Project start steps,
work order page, `module-map.ts`, `App.tsx`, sidebar, tracker, this plan, `drawings-to-progress-plan.md` (DRW-02 = this).

## 5. Decisions (proposed default in **bold**)

| # | Question | Default |
|---|---|---|
| D-DOC1 | Who sees what | **Drawings, approvals, test reports: everyone on the project. Contract, BOQ / estimate, work orders and anything marked restricted: owner, admin, finance, PM (`may_view_expenses`).** Upload: anyone on the project; revise, archive, restrict: owner, admin, PM. *Permissions: needs Ilan* |
| D-DOC2 | Where files live | **VPS disk now (decided 13 Oct for photos)**; switch the provider to R2 when the disk passes 70%. A drawing set is 20-80 MB per project; check free space before DOC-01 ships |
| D-DOC3 | PDFs on WhatsApp | **v3 companies only**; classic keeps declining. Changes the shared ingress normaliser: *needs Ilan* |
| D-DOC4 | Limits | **25 MB per file; PDF, images (JPG, PNG, HEIC), Office (DOCX, XLSX), DWG (download only, no preview)** |

## 6. Risks

- **Sending a superseded drawing** is worse than sending none: `find` returns current revisions only and says the
  revision in the reply; an archived or superseded document is never sent unless asked by its exact revision.
- **A restricted paper reaching the site** (contract value, rates): the API filters by role on every read and on
  `send`; tests for each role.
- **Disk filling up** on the VPS: size cap, duplicate check (sha256), a usage figure on the company page; R2 switch
  ready.
- **Large uploads** holding memory: multipart streamed to storage, 25 MB cap enforced before reading the body fully.
- **WhatsApp 24-hour window:** files can only be sent inside it; outside, the alert is text with a dashboard link (the
  same rule as the other reminders).
- **Classic regression** from the ingress change: the mapping is behind the company's assistant mode; classic tests
  must stay unchanged.
- **Wrong guesses** of number / revision from file names: always shown for a check before saving (dashboard) or on the
  Save card (WhatsApp); nothing is guessed silently.

## 7. Testing

- Unit: file-name and title-block parsing ("STR-GA-S101-RevC.pdf", "Column Layout R2.pdf", "Permit 2026.pdf"),
  revision ordering, find ranking, expiry windows, the two WhatsApp note texts.
- Contract (real Postgres): upload, duplicate refused, revision supersedes and alerts, archive, restricted hidden from
  an engineer on list / detail / find / send, cross-project and cross-company refused, links to activity and work
  order, BOQ import keeps its file.
- Agent: the four tools are the dashboard's routes; "send me the latest column drawing" reads then sends; a PDF is
  offered as a document and held for Save; a bill PDF is still an expense; classic unchanged.
- Dashboard: type check, lint, build; browser at 390 / 1280 / 1440 px: upload many files, preview, new revision,
  schedule panel section.
- The full verification list in CLAUDE.md before every push.

## 8. Rollback

Revert the commits; `alembic downgrade 0522` (refuses while documents exist; archive or export them first). Files in
storage are left in place (harmless, under `documents/`). The ingress change is a single mapping behind the assistant
mode and reverts on its own.

## 9. Labour isolation

Nothing in Labour, Attendance, Workforce or Payroll changes. Labour sheets and team photos stay where they are.

## 10. Success criteria

- A site engineer gets the current column drawing on WhatsApp within 10 seconds of asking.
- A new revision reaches everyone on the project the same day, and the old one shows as out of date everywhere.
- No permit or insurance on a project expires without two reminders.
- The schedule's Foundation bar shows the foundation drawing and its revision.
- A PDF sent to Mesiri is saved in two taps instead of being refused.

## 11. Order of work

1. **DOC-01** register (table, storage, API, Documents page, upload, preview, folders, search).
2. **DOC-02** revisions (supersede, history, the revision alert).
3. **DOC-03** connections (schedule panel, project start step, BOQ source file, work orders).
4. **DOC-05** WhatsApp out (find and send), then **DOC-04** WhatsApp in (after D-DOC3).
5. **DOC-06** expiry reminders.
6. Later: **DOC-07** handover pack (end-of-project plan), **DOC-08** search inside documents, DRW-03+ (AI reads the
   drawings).
