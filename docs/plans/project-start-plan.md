# Project start: from "we won the job" to "work starts on site" (Nov 2026)

> **Status:** built 8 Nov 2026 (ST-01, ST-03..ST-07; ST-02 tables only) (asked in session by Ilan: "the middle part is done in an
> okay way, but the starting and the ending is where we are lacking ... start with the starting part, then
> slowly get to the middle part; make a video with the value proposition"). Tracker items `ST-01`..`ST-10`
> in [V1_TRACKER.md](V1_TRACKER.md). The ending (billing, handover, closeout, defect period) is the next
> plan.

---

## 1. The problem, in the contractor's words

| Who | Says today | What it costs them |
|---|---|---|
| **Owner / MD** | "The contract value, the retention, the advance: it's in the agreement PDF somewhere." | Retention and advance recovery are forgotten; the margin is guessed |
| **Project manager** | "The schedule is an Excel bar chart I made once. Nobody updates it." | Delays are found at the monthly meeting, weeks late; one slab slipping silently moves everything after it |
| **Estimator / QS** | "The BOQ is a 200-line Excel. To use Mesiri I'd have to type it all again." | Software that needs re-typing is not used; the BOQ never reaches the site |
| **Site engineer** | "What should I be doing this week?" | Work is done in the wrong order, materials are ordered late |

**Mesiri's answer:** the day a job is won, the office loads what it already has (the BOQ Excel, the contract
terms, the dates) in under 30 minutes, and from the next morning everything the site sends on WhatsApp is
measured against it automatically. **Nobody types anything twice, and nobody updates the schedule by hand:
the site's daily messages do it.**

## 2. What the "start" of a project contains

| Stage | Module | In this round |
|---|---|---|
| Win the job | Tender pricing from a rate library | Later (ST-09) |
| Contract | **Client and contract**: client, contract value, retention, mobilisation advance and recovery, GST, TDS, defect liability period | **ST-02** |
| Project lifecycle | **Project stage**: Tender → Won → Running → Handover → Defect period → Closed, with start and finish dates | **ST-01** |
| What will be built | **BOQ from Excel**: the estimate sheet loaded as BOQ sections and lines, with rates | **ST-03** (BOQ exists, CC-02) |
| When | **Schedule (Gantt)**: each BOQ section (or a plain activity) with dates, milestones, "starts after"; move one and the ones after it move; progress and lateness from what site reports | **ST-04** |
| Getting ready | **Project start page**: one checklist, what is done and what is next | **ST-05** |
| Site asks | **Schedule on WhatsApp**: "what is planned this week?", "what is late?" | **ST-06** |
| Already built | Sites and team, suppliers and opening stock (PRC-05 import), subcontract work orders (NXT-05) | linked from ST-05 |
| Documents | Contract PDF, permits, drawing register | Later (ST-08; drawings → progress is V2, DRW) |

**Yes, planning and the Gantt chart belong to the start**: the schedule is made before work begins. It is also
the bridge to the middle: once work starts, site updates fill the bars in.

## 3. Investigation (Phase 1, `main` at `536f21e`)

| Area | Exists | Reuse |
|---|---|---|
| BOQ | `work_packages` (section) + `work_package_planned_items` (line, rates 0508), `/projects/{id}/boq`, `PostgresBoqRepository` | Import writes through the same repository; the schedule *is* the BOQ sections |
| Schedule dates | `work_packages.planned_start / planned_end / actual_start / actual_end / status / manual_completion_pct / parent_id` (0420), **never read or written** | The Gantt reads and writes these: no new schedule table |
| Measured work | `activity_quantities.planned_item_id` (0519) and `activities.work_package_id` (0430) | A bar's progress = measured ÷ planned on its lines; first activity = actual start |
| Project | `projects.client` (free text), `status` = health (on_track / at_risk …) | `stage` is a new column next to health, not a replacement |
| Excel import | `domains/materials/importer.py` (PRC-05): template, preview in a rolled-back savepoint, row-by-row errors | Same pattern for the BOQ sheet |
| Roles | `may_view_expenses` (BOQ, money) | Contract and BOQ import: same rule. Schedule read: anyone on the project |
| Assistant | v3: API route + `agent_api/tools.py` `ALLOWED` + SOP rule | Schedule read route added to `ALLOWED` |
| Module map | Project setup, Schedule, Clients: `planned` | Become built pages |

## 4. Implementation plan (Phase 2)

**Objective.** A contractor can take a newly won project from contract to a live schedule in one sitting, and
the schedule then keeps itself up to date from site reports.

**Scope.** ST-01..ST-07. Not in scope: tender pricing, documents, client billing (next plan), resource
levelling, baselines beyond "planned vs actual" dates.

**Database (one additive migration, 0521).**
- `projects.stage` text (tender / won / running / handover / defects / closed, default `running` so every
  existing project keeps working), `projects.start_date`, `projects.planned_finish`.
- `clients` (per company: name, contact person, phone, email, GSTIN, address).
- `project_contracts` (one per project: client, contract number, value, signed on, retention %, mobilisation
  advance, advance recovery %, GST %, TDS %, defect liability months, payment terms, notes).
- `work_packages.is_milestone`; `work_package_links` (predecessor → successor, lag days). Both tables have
  row-level security like 0519.

**API.**
- `GET/PATCH /projects/{id}/start`: stage, dates, the checklist (what is done, counts, next step).
- `GET/POST/PATCH /clients`; `GET/PUT /projects/{id}/contract` (money roles).
- `GET /projects/{id}/boq/import/template`, `POST /projects/{id}/boq/import?commit=` (preview, then commit).
- `GET /projects/{id}/schedule`; `POST /projects/{id}/schedule/activities`;
  `PATCH /projects/{id}/schedule/activities/{id}` (dates, milestone, done, "starts after", push the ones after).
- v3: `GET /projects/{id}/schedule` in `ALLOWED`, SOP rule for "what is planned / late".

**Frontend.** Planning › Project start (checklist page), Planning › Schedule (Gantt: bars, today line,
milestones, progress fill, late in red, critical path, edit panel; a list on phones), Client billing › Clients,
the project stage on the Projects list, BOQ page "Import from Excel".

**Risks.** (1) A schedule nobody updates is worse than none: progress comes only from site data, never typed
percentages, unless the PM marks a bar done. (2) "Push the ones after" moves many bars at once: it is shown
before it is saved and only moves later bars, never earlier ones. (3) Contract figures are money: same roles as
the BOQ (D-N3 default, Ilan to confirm). (4) Excel files vary: unknown columns are reported, never guessed.

**Testing.** Pure unit tests for the schedule maths (progress, lateness, push, critical path, cycles) and the
BOQ sheet reader; real-Postgres contract tests for every route and role; v3 tool test for the new `ALLOWED`
line; dashboard type check, lint, build, and a browser check at 1440 and 390 px.

**Rollback.** Revert the commits and `alembic downgrade 0520`; the migration only adds, and its downgrade
drops only what it added (refuses while contracts exist, so no contract data is lost by accident).

**Labour isolation.** Nothing in Labour, Attendance, Workforce or Payroll changes.

**Success.** A 200-line BOQ Excel becomes a priced BOQ and a schedule in under 30 minutes; the Gantt shows which
section is late on the morning after a site report; the engineer asks "what's planned this week?" on WhatsApp.

## 5. Value proposition (used for the video)

1. **Start in 30 minutes, not 3 days**: the BOQ Excel you already have becomes the BOQ, the budget and the
   schedule.
2. **The schedule updates itself**: site engineers keep sending WhatsApp updates as today; the bars fill in.
3. **See the delay the day it happens**: late and at-risk work in red, and what it pushes.
4. **The contract never gets lost**: retention, advance recovery and defect period are recorded once and used
   later by billing and closeout.
5. **One system from the first day**: the same BOQ lines carry through to purchase, subcontract work orders,
   cost control and client bills.

## 6. What was built (8 Nov 2026)

- **Backend:** `domains/schedule/` (`logic.py` pure maths, `store.py`, `router.py`, `reminders.py`),
  `domains/progress/boq_import.py`; migration 0521. Progress per BOQ line = work updates counted on the line
  (CUMULATIVE replaces, ACHIEVED adds) + confirmed subcontract measurements not from a work update: the same
  "measured to date" for the Gantt and later for RA bills.
- **Rules settled while building:** a milestone may fall on the day its predecessor ends; "mark finished" on past
  work dates it to site's last report (else the planned end), never today; a move pushes only later work, never
  earlier or finished work, and is always previewed; forecasts count days of work before today (today's work is not
  reported yet).
- **Dashboard:** Planning › Project start, Planning › Schedule (Gantt on desktop, list on phones), the BOQ import
  dialog (BOQ page, Project start, Schedule), stage and on-time/late on the Projects list, Planning in the sidebar.
- **WhatsApp:** delay note (daily, owner / admin / PM), "this week" (Monday, site team), v3 tools and SOP rule 15.
- **Not built (see tracker):** client and contract screens (with billing), documents register, tender pricing,
  translated notes, bar resize and baselines.

## 7. Next (the middle, then the end)

After ST: CC-04 progress per BOQ line on the Gantt (done here for bars), NXT-10 weekly lookahead from the
schedule, then the ending plan: RA bills (NXT-02), payments received (NXT-03), variations (NXT-04), snag list,
closeout (CC-14), defect period and retention release.
