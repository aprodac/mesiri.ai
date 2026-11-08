# Drawing reader: sheets, levels, rooms and checks from a drawing PDF (Nov 2026)

> **Status:** plan, 8 Nov 2026. One of three independent plans split from
> [connected-project-plan.md](connected-project-plan.md); tracker section **DR** in [V1_TRACKER.md](V1_TRACKER.md).
> **Does not wait on the material plan (MP) or progress by place (LP), nor on the documents register (DOC-01,
> blocked on D-DOC1).** DR-01..DR-05 work on a PDF the user uploads to be read, with nothing stored as a document;
> only DR-07/08 attach to the register once DOC-01 exists.
>
> It is the architectural, text-layer-only first slice of [drawings-to-progress-plan.md](drawings-to-progress-plan.md)
> (DRW, V2): the same rule (numbers from the drawing's own text and geometry, never a model's guess; a person
> confirms), the same code that DRW-03 extends later.

## 1. The problem

A drawing set is 9-80 pages of PDF that the office reads by eye. Mistakes in it (an area label copied from the next
room, a level that differs between two sections) reach site and are built. The levels, room sizes and fixture counts
the BOQ and schedule need are typed again by hand.

**Worked example:** the Kondotty commercial set (Kaleido Architects, 9 sheets, 18.05.2026). Every title block, room
label, size and level is text in the PDF. ROOM-1 is drawn 1740 × 590 cm but labelled 1217 sq ft (it is 1,105;
1,217 is ROOM-2's). Levels −265, ±0, +45, +400, +450, +805, +855, +1167.5, +1270. Toilets 12, urinals 6.

## 2. Investigation (Phase 1, `main` at `e536b87`)

| Area | Exists | Reuse |
|---|---|---|
| PDF text with positions | `pdftotext` on dev machines; production VPS not checked | Use `pypdf` / `pdfplumber` (pure Python, a pinned dependency) so it does not depend on the VPS |
| AI gateway | `platform/ai` vision / extraction ports, routing table | Only to classify a page that has no text, flagged as "from AI"; never a number |
| Schedule quick plan | ST-04 (`schedule/router.py`) | A draft per-floor schedule goes through it as a preview |
| BOQ import | ST-03 preview / import | A draft BOQ goes through the same preview |
| Documents | DOC-01 planned, blocked | DR-07 attaches results to it when built |
| Tests | Kondotty sets on hand | Fixtures with expected answers (DRW-01's golden set starts here) |

## 3. Items

| ID | What | Size |
|---|---|---|
| **DR-01** | **Reader:** `domains/drawings/reader.py`: per page, title-block fields (project, title, drawing no., scale, date, drawn / checked, architect, client, units note), discipline and kind (plan / elevation / section / schedule) from the title, level from the title ("FIRST FLOOR PLAN") | M |
| **DR-02** | **Facts:** levels from sections and elevations (`+400 LVL`), rooms with label and size ("ROOM-2 1740 x 650", "TOILET 120X150"), stated areas ("1217 Sq.ft"), fixture counts (toilet, urinal, wash, lift, stair) per plan; each with page and position | M |
| **DR-03** | **Checks:** stated area vs its dimensions (±3%), the same level differing between sheets, missing scale / date / drawing no. / revision, typical floors whose same room differs. Each check: what, where (page, position), why it matters | M |
| **DR-04** | **Read a drawing set (dashboard + API):** `POST /drawings/read` (multipart PDF, 50 MB, nothing stored) → sheets, facts, checks; Planning › Drawing check page: drop a PDF, see the sheets, the levels table, rooms per floor, fixture counts and "things to ask the architect" | M |
| **DR-05** | **Draft schedule from levels:** floors found → per-floor activities (footing, columns, slab, brickwork, plaster, flooring, finishes; editable template) as a preview into ST-04's quick plan; never overwrites | M |
| **DR-06** | **Draft BOQ quantities from rooms:** room areas → flooring, ceiling plaster, skirting; perimeter × floor height → wall plaster, paint; fixture counts → sanitary lines; as a preview into ST-03's import, or a diff against the existing BOQ | L |
| **DR-07** | **With the documents register (after DOC-01):** one uploaded set → one register entry per sheet; facts and checks saved (`drawing_facts`, additive, RLS) | M |
| **DR-08** | **On WhatsApp (after DR-07 + DOC-04):** "first floor slab level?", "Room-2 size?" from saved facts; v3 `drawing_facts` route in `ALLOWED` | M |

## 4. Implementation plan (Phase 2)

**Objective.** Drop a drawing PDF into Mesiri and in seconds get its sheets, levels, rooms, fixture counts and the
mistakes in it, then turn them into a draft schedule and BOQ.

**Backend.** New `domains/drawings/` (reader, facts, checks: pure functions over the page text with positions, fully
unit tested on fixtures); one route `POST /drawings/read` (auth: anyone who may see project planning; no project data
written). New pinned dependency for PDF text (pure Python). No migration until DR-07.

**Frontend.** Planning › Drawing check (`/planning/drawing-check`): upload, then four panels (Sheets, Levels, Rooms
and fixtures, Checks); "Make a draft schedule" (DR-05) and "Draft BOQ" (DR-06) buttons open the existing previews.

**Risks.** Every office draws differently (title-block layout, cm vs mm, "LVL" vs "FFL"): the reader reports what it
could not read rather than guess; the golden set grows with every customer set. Scanned PDFs have no text: say so.
File size and time: limit 50 MB and 120 pages; read on the request for now, a job (ARQ) if it is slow.

**Testing.** Fixtures: the Kondotty architectural set (9 sheets) with expected sheets, levels, rooms, counts and the
ROOM-1 flag; synthetic small PDFs for edge cases; route test; dashboard checks.

**Rollback.** Revert the commits; nothing is stored before DR-07.

**Labour isolation.** No Labour, Attendance, Payroll or Workforce code or data.

**Success criteria.** On the Kondotty set: 9 sheets named right, all levels listed, rooms with sizes, 12 toilets and
6 urinals, ROOM-1 flagged; under 5 seconds.

## 5. Decisions (defaults used until answered)

| # | Question | Default |
|---|---|---|
| D-DR1 | Checks shown to whom | The person who uploaded; never sent to the architect by Mesiri |
| D-DR2 | Drafts | Always a preview the user confirms; never overwrites a BOQ or schedule |
| D-DR3 | Customer drawings in the test set | Only with the customer's permission; anonymised names |
