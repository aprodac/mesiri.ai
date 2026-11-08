# Cost control: budget vs actual, every day (GM meeting, 6 Nov 2026)

> **Status:** plan written 6 Nov 2026. **Built:** CC-02 (BOQ), 6 Nov 2026, see section 4a. Tracker section **CC** in
> [V1_TRACKER.md](V1_TRACKER.md). Builds on [procurement-plan.md](procurement-plan.md) (PRC) and on the
> never-wired planning tables from [drawings-to-progress-plan.md](drawings-to-progress-plan.md).
> Decisions D-CC1..D-CC7 (section 9) have a proposed default; rows that need one are marked.
>
> **Source:** sales meeting with a builder's GM (6 Nov 2026). Price discussed: ₹15k onboarding + ₹5k/month.
> He wants a trial on a site that is starting now (a second site is in Chennai). Next: he talks to the MD,
> then a detailed meeting and training for site engineers, QS, accounts and central coordination.

---

## 1. What he said, in one line

> "Just noting down that metal arrived or cement arrived has no real benefit… If your tool solves our real
> tracking problems rather than just digitizing paper registers, it will be very valuable."

A DPR alone is a diary; he values it at the cost of a clerk's overtime. **What he will pay for is cost
control:** every rupee that leaves (labour, material, subcontract, petty expense) is compared with the work
measured on the ground, against the budget, every day, as **green or red**.

The DPR stays: it is **how the data comes in** (WhatsApp voice/text from the engineer, least work for the
person on site). The product is what comes out.

## 2. His asks → what we build

| # | He said | What it means | Exists today | Build |
|---|---|---|---|---|
| A | "4 masons + 2 helpers = ₹6,400. Was ₹6,400 of work done?" | **Labour productivity**: labour cost ÷ measured output vs benchmark, per work item per day | Attendance with trade, headcount, `daily_wage` (0371); activity quantities with unit (0430) | BOQ benchmark (CC-02), labour → work item (CC-05), daily variance (CC-07) |
| B | "Subcontract plastering is ₹14/sq ft. Labour ₹2,000/day: how many sq ft justify it?" | **Benchmark rate per unit** on each BOQ item | `work_package_planned_items.planned_quantity` only, no rate | CC-02 |
| C | "Outside concrete team for ₹15,000: was ₹15,000 of work done?" | **Subcontract / piece work** checked against measured quantity × agreed rate | Expenses with vendor; nothing ties a payment to a quantity | CC-06 |
| D | "5 m³ of 20 poured: 15 left, budget updates itself" | **BOQ burn-down**: planned, done, remaining quantity and cost | `planned_quantity` exists, unused | CC-02, CC-04 |
| E | "Shortage of 4 loads of metal at closeout" | **Material reconciliation**: required (BOQ × norm) vs received vs consumed vs on hand, warned early | Received/consumed/on hand per site (PRC-17); no "required" | CC-03, CC-08 |
| F | "Material consumption register: how many CFT used today" | Daily consumption, tied to the work it went into | `material_usage` with `CONSUMED`; no link to the work | CC-08 |
| G | "M-sand arrived: rate, qty, amount, previous balance, advance, net payable" | **Supplier ledger** with a running balance | Receipts with `unit_cost`/`total_cost` and `vendor_id` (PRC-04); payments as expenses with `vendor_id`; no balance, no advance, no opening balance | CC-09, CC-10 |
| H | "Petrol ₹100 goes to other expenses; material spend goes to materials" | **Cost centres**: every cost lands in one, per project | `expense_categories` (Materials, Subcontractor Labour, Equipment, Fuel…), only on expenses | CC-01 |
| I | "Cost should be logged with the voice note '4 m³ poured'" | Every report line carries its **cost** | Activity logs event only | CC-07 (costing), CC-11 (WhatsApp) |
| J | "Green or red. Profit: incentive. Loss: address it." | Evening **cost card** to GM/MD; engineer-level view | DPR evening flow | CC-11, CC-12 |
| K | "The start is where the core setup happens" | **Project setup**: BOQ, cost centres, suppliers, opening stock and balances from their Excel | PRC-05 import (items, vendors, opening stock) | CC-13 |
| L | MEP detail: fittings, bends, wire length; leftovers returned or wasted | Item-level stock with return/wastage | Categories (PRC-01), sizes, `RETURN_TO_VENDOR`/`WASTAGE` reasons | Mostly done; norms from MEP estimate in CC-03 |
| M | Data on our own server | Dedicated instance | Single multi-tenant VPS | CC-16 (ops) |
| N | Procurement ("everything like that he asked") | Orders, duplicates, delivered-not-billed, rates | PRC-01..05, 17 done | PRC-06..20, unchanged, re-prioritised in §7 |

## 3. Objective, scope, business value

**Objective:** for every project, show each day whether the money spent got the work done, per BOQ item, per
cost centre and per supplier, from what engineers already send on WhatsApp.

**Scope (V1 of cost control):**
- BOQ per project: items, unit, quantity, client rate, internal budget rates (labour, material, subcontract),
  material norms per unit. Imported from their Excel.
- Every cost (labour day, material consumed, subcontract bill, expense) attributed to a project, a cost
  centre and, where known, a BOQ item.
- Daily variance per BOQ item and per site: earned (measured qty × budget rate) vs actual cost. Green/red.
- Material reconciliation: required vs received vs consumed vs on hand per material per project.
- Supplier ledger: opening balance, deliveries, payments, advances, running balance, net payable.
- Evening cost card on WhatsApp; four new dashboard screens (section 6).

**Not in scope now:** client billing / RA bills, retention, GST returns, payroll, scheduling (Gantt),
drawings extraction (DRW, V2), on-premise install.

**Business value:**
- **GM / MD:** knows the same day when a team, a subcontractor or a material is over budget, before
  releasing payment. "Was ₹15,000 of work done?" is answered on the screen.
- **Accounts:** supplier balances and payables at a glance; nothing paid twice; material without a bill
  is visible (PRC-11).
- **QS:** measured quantities against the BOQ without a separate sheet.
- **Site engineer:** no new typing beyond what they already say ("plastered 400 sq ft first floor, 4
  masons 2 helpers"); one question at most when the work item is unclear.
- **Mesiri:** moves from "digital register" (~₹5k/month ceiling) to cost control, which pays for itself
  the first time it catches a bad day. It is also what makes the sale.

## 4. Database work (all additive; head is `0507` on 6 Nov, re-check before writing)

Reuse first. The planning layer exists (0420): `work_packages` (project/site, name, code, status, planned
dates, `manual_completion_pct`) and `work_package_planned_items` (`work_type`, `planned_quantity`, revisions);
`activities.work_package_id` (0430). **The BOQ is these tables, not a new one.**

| Change | Item | Notes |
|---|---|---|
| `work_package_planned_items`: `unit`, `client_rate`, `labour_rate`, `material_rate`, `subcontract_rate`, `boq_code`, `cost_category_id` (all nullable) | CC-02 | Budget per unit split three ways; client rate gives margin |
| New `boq_material_norms` (planned_item_id, material_id, quantity_per_unit, wastage_pct) + RLS | CC-03 | e.g. 1 m³ M20 → 8 bags cement, 15 cft M-sand, 30 cft 20 mm metal |
| `activity_quantities.planned_item_id` (nullable) | CC-04 | Measured quantity counts against a BOQ line |
| `labour_attendance_lines.planned_item_id` (nullable) | CC-05 | **Labour module** (allowed without approval since 3 Nov, said in the report). Workforce tables untouched |
| `expenses.planned_item_id`, `expenses.measured_quantity` (nullable) | CC-06 | Subcontract / piece work |
| `material_usage.planned_item_id` (nullable) | CC-08 | Consumption register tied to work |
| `vendors.opening_balance`, `opening_balance_date`, `credit_days`, `kind`; `expense_payments.vendor_id` / `advance_id` (built 8 Nov, migration 0516, instead of `expenses.is_advance`) | CC-09 / CC-10 | Advances are payments with no bill yet: a payment row with no expense; applying it to a bill moves no money |
| `expense_categories.kind` (`MATERIAL`/`LABOUR`/`SUBCONTRACT`/`EQUIPMENT`/`OVERHEAD`/`OTHER`, nullable) | CC-01 | Lets receipts and attendance land in the right cost centre without new tables |

No column is dropped, renamed or rewritten. Every new table gets tenant RLS (as 0484).

### 4a. As built: BOQ (CC-02, 6 Nov 2026)

- **Migration 0508** (additive): on `work_package_planned_items`, `organization_id` (filled from the
  section, then NOT NULL, row-level security as 0484), `boq_code`, `client_rate`, `labour_rate`,
  `material_rate`, `subcontract_rate` (numeric, >= 0, nullable), `sort_order`; `sort_order` on
  `work_packages`. Downgrade drops exactly these.
- **Words used:** a BOQ *section* is a `work_packages` row; a BOQ *line* is a
  `work_package_planned_items` row; `work_type` holds the line's wording ("Internal plastering 12 mm").
- **Money** (`domains/progress/boq.py`, pure): contract value = quantity x client rate; budget cost =
  quantity x (labour + material + subcontract); margin = the difference. A rate left empty is "not
  priced", never zero; totals add the priced lines and count the unpriced ones; the project margin only
  shows when every line has both. Sent as exact strings ("756000.00").
- **Revisions (ADR-D5):** a new planned quantity keeps the old row as history and adds `revision_no + 1`;
  every other field changes in place. Only the current revision is shown or editable.
- **Routes** (`domains/progress/boq_router.py`, module `dpr`): `GET /projects/{id}/boq`;
  `POST/PATCH/DELETE .../sections[/{id}]`; `POST .../sections/{id}/lines`; `PATCH/DELETE .../lines/{id}`.
  409 for the same work and unit twice in a section, or a section code used twice; 409 when removing a
  section that has logged activities; 422 for an unknown unit (units resolved by the shared alias table:
  "sq ft", "m3", "cum").
- **Who:** read and write by the roles that see the company's spending (`may_view_expenses`: owner,
  admin, finance, project manager), within their projects; 403 for site engineers. D-CC4 (who else sees
  rates) is still open; this is the most restrictive default.
- **Dashboard:** `/projects/:id/boq` (`ProjectBoqPage`): totals (contract value, budget cost, margin),
  one table per section with section totals, add/edit/remove dialogs, a plain-language explainer; a
  "BOQ and budget" summary on the project page for the same roles. No sidebar change (D-CC5 open).
- **Not built yet:** Excel import (CC-13), cost centre per line (CC-01), material norms (CC-03), work
  done against lines (CC-04), WhatsApp access (later, through v3 `ALLOWED`).

### 4b. As built: work done against the BOQ, web (CC-04, 8 Nov 2026)

- **No migration.** Reuses `activity_quantities.planned_item_id` and the work-order tables (0519).
- **Done on a line** (`boq_router._done_by_line`): site work updates put on the line, plus confirmed
  work-order measurements on a work-order line that points at the BOQ line and did not come from a work
  update (`source <> 'activity'`; that update is already counted). Each quantity counts once. Only the
  line's own unit is added; work in another unit is counted as `done_in_other_unit`, never converted.
  Work counted before a quantity revision stays on the line (revision chain followed). Removed work
  (`activities.deleted_at`) is left out.
- **Earned** (`boq.line_progress`, pure): done x labour / material / subcontract budget rate, kept apart,
  so CC-07 can set labour cost against labour earned. A rate not given earns None, never zero. More done
  than planned is said (`over_planned`).
- **Putting work on a line:** `GET /projects/{id}/boq/work?unlinked=true` lists recorded quantities with a
  suggested line (`boq.suggest_line`: same unit, most shared words, the activity's section breaks a tie,
  none on a tie); `PUT .../boq/work/{quantity_id}` `{line_id | null}` saves it. A person always confirms.
  Same roles as the BOQ (money roles, D-CC4 open).
- **Web:** BOQ page Done (quantity, %, bar) and Earned columns, "Earned so far" tile, a "Work done, not
  on a BOQ line yet" list with a line picker and Count.

### 4c. As built: Cost control as a module (CC-17, CC-01 centres, 8 Nov 2026)

- **Module `cost`** ("Cost control"), on by default (V1), switched off per company from the control panel like
  Equipment. Migration 0521 adds it where a module list is stored and records where, so the downgrade takes it
  off exactly there. Asked in session by Adarsh; Alan not asked yet (shared module settings).
- **Backend `domains/costing/`** (`require_module("cost")`, mounted in `http/app.py` and the production app):
  `GET /cost/centres` (`centres.split` over `finance.costs.project_costs`: centres + not set always equal the
  read model's total), `GET/PATCH /cost/categories` (`expense_categories.cost_centre`: materials, labour,
  subcontract, equipment, fuel, overhead, other, or not set), `GET /cost/projects/{id}/budget` (per kind: BOQ
  budget, earned by the work on lines, spent in that centre to date; spending with no BOQ rate listed apart).
- **Sidebar:** Cost control group (money roles only): BOQ & budget (moved from Planning), Budget vs actual, Cost
  centres; Green / red and Closeout still planned.
- **Not yet:** spending per BOQ line (needs CC-05 labour allocation), green / amber / red (CC-07, thresholds
  D-CC6), material norms (CC-03).

## 5. API work (each route used by the dashboard; WhatsApp gets it through v3 `ALLOWED`)

| Route | Item | What |
|---|---|---|
| `GET/POST/PATCH /projects/{id}/boq`, `POST /projects/{id}/boq/import` (preview, commit) | CC-02, CC-13 | BOQ lines with rates and norms; Excel import like PRC-05 |
| `GET /projects/{id}/cost-ledger?from&to&category&item` | CC-01 | One read model over expenses, material receipts/usage (valued), attendance (headcount × wage); **no new ledger table** |
| `GET /projects/{id}/boq/progress` | CC-04 | Planned / done / remaining quantity and budget per BOQ line |
| `GET /sites/{id}/cost/daily?date`, `GET /projects/{id}/cost/variance?from&to` | CC-07 | Earned vs actual per item, labour and material separately, green/red, reasons |
| `GET /projects/{id}/materials/reconciliation` | CC-08 | Required / received / consumed / on hand / expected shortage per material |
| `GET /finance/vendors/{id}/ledger?date_from&date_to`, `GET /finance/vendors/payables` (built 8 Nov) | CC-09 | Dated lines with running balance; net payable per vendor |
| `POST /vendors/{id}/payments` (reuses expenses + payments) | CC-10 | "Paid Malabar 20,000 advance" |

v3 assistant: `ALLOWED` lines for `boq_progress`, `daily_cost`, `vendor_balance`, `vendor_payables`,
`material_reconciliation`, `record_vendor_payment`; `record_activity` and `record_attendance` take a BOQ
item in words, the code matches it (same pattern as material categories, PRC-02). SOP rules: when the work
item is unclear, ask once with the site's open BOQ items as buttons; never invent a quantity or rate.
No workflow, router or word list.

## 6. Frontend work (dashboard)

The team's view (6 Nov): the dashboard is a list of registers (~29 pages) that shows what was typed in,
not what it means. Market tools lead with answers. **Restructure around the GM's five questions**, keep the
registers as drill-downs. Proposed (needs D-CC5):

| Screen | Answers | Item |
|---|---|---|
| **Project cost** (project home) | Budget vs spent vs earned; BOQ lines with planned / done / remaining, colour per line; cost by cost centre | CC-12 |
| **Today** (replaces Today/Live as landing) | Each site's day: work done, its cost, green/red per item and team, issues | CC-12 |
| **Payables** (built 8 Nov as Finance › Suppliers and each supplier's page) | Who we owe, how much, oldest first; vendor ledger with running balance; advances | CC-09 |
| **Material position** | Required vs received vs consumed vs on hand; shortage forecast; delivered not billed | CC-08 |
| **Issues & approvals** | Existing issues page, moved up | — |
| Project setup | BOQ import, norms, cost centres, suppliers with opening balances | CC-13 |

Materials, Labour, Expenses, Vendors, Daily reports, Gallery, Timeline stay, one level down, each linked from
the number it explains. Visual quality pass (CC-15) on these screens only, not all pages.

WhatsApp: evening **cost card** to GM/MD (per site: work done, cost, earned, green/red, top 3 reasons, link);
answers to "Malabar balance?", "how much plastering left?", "metal enough for the slab?". Three languages.

## 7. Build order (pilot first)

**Goal:** a working loop on the client's new site in ~3 weeks. Then widen.

| Phase | Items | Why first |
|---|---|---|
| 0 — inputs | CC-00: get their BOQ/estimate, rate card, CA's cost-centre list, supplier register sample, MEP estimate | Build on their sheets, not guesses |
| 1 — budget | CC-01 cost centres, CC-02 BOQ, CC-03 norms, CC-13 import | Nothing compares without a budget |
| 2 — actuals | CC-04 quantities → BOQ, CC-05 labour → BOQ, CC-06 subcontract, CC-08 consumption | The engineer's existing messages, now attributed |
| 3 — the answer | CC-07 daily variance, CC-11 evening cost card, CC-12 Project cost + Today | **The demo for the second meeting** |
| 4 — money | CC-09 supplier ledger, CC-10 payments/advances, PRC-11 not billed, PRC-14/16 rates, PRC-18 petty cash | Accounts team's asks |
| 5 — procurement | PRC-06..10 orders, PRC-07 duplicates, PRC-19/20 period reports | Already planned |
| 6 — polish | CC-14 closeout report, CC-15 visual pass | |

## 8. Files expected to change

- Backend: `domains/progress/` (BOQ routes, quantities), `domains/materials/` (usage link, reconciliation),
  `domains/vendors/` (ledger, payables), `domains/expenses/` + `domains/finance/` (cost centre kind,
  advances, cost ledger), a new `domains/costing/` for variance (read-only over the others), labour
  attendance write path (one nullable field), `agent_api/tools.py` + `agent_api/SOP.md`, migrations 0508+.
- Dashboard: new pages `ProjectCostPage`, `PayablesPage`, `MaterialPositionPage`, `ProjectSetupPage`;
  `TodayPage` reworked; sidebar order (D-CC5).
- Docs: this plan, tracker, architecture notes for the cost read model.

## 9. Decisions needed (proposed default in **bold**)

| ID | Question | Default | Blocks |
|---|---|---|---|
| D-CC1 | Material cost: when bought or when consumed? | **Both, shown separately:** spend = receipts; cost of work = consumed × weighted average rate | CC-07 |
| D-CC2 | Labour on a day with several work items and no split said | **Ask once with buttons; if no answer, split by man-days the engineer named, else mark "unallocated"** (never guessed) | CC-05 |
| D-CC3 | Supplier liability from deliveries or bills? A material bill paid as an expense must not count twice | **Deliveries create the liability; bills confirm it; payments reduce it; an expense linked to a material bill is a payment, not a second cost** | CC-01, CC-09 |
| D-CC4 | Who sees rates, margins, profit/loss, supplier balances | **Owner, Admin, Finance, PM; engineers see quantities and their own site's green/red, no client rate** — **needs Ilan (permissions)** | CC-07, CC-09, CC-12 |
| D-CC5 | Restructure the dashboard navigation around the five screens | **Yes, registers become drill-downs** — product decision, shared layout | CC-12, CC-15 |
| D-CC6 | Green/red threshold | **Green ≥ 100% of benchmark, amber 90–100%, red < 90%**, per company setting | CC-07 |
| D-CC7 | Dedicated hosting for clients who ask | **Dedicated cloud instance (own DB, backups), no on-premise in V1**; priced separately | CC-16 |
| D-CC8 | Cost before or after GST we can claim back | **Before claimable GST when the bill has a GSTIN and a tax amount, else the full amount, flagged** — needs Ilan | CC-25, CC-07 |

## 10. Risks

- **Bad budget in, bad colours out.** If BOQ rates or norms are wrong, every day is red. Mitigation: import
  their own estimate; QS signs off rates; show "no benchmark" instead of a colour.
- **Attribution burden on engineers.** Asking "which BOQ item?" every message kills adoption. Mitigation:
  match from words and site's open items; ask at most once per line; allow unallocated.
- **Double counting** money between receipts, bills and expenses (D-CC3). Mitigation: one cost read model
  with explicit rules and tests per source.
- **Weighted average rate** gaps when a delivery has no rate. Shown as "unpriced", never zero.
- **Scope creep into accounting** (RA bills, GST). Out of scope; say so in the pilot.
- **Data sensitivity:** margins and supplier balances are more sensitive than DPRs; D-CC4 before showing
  them to engineers.
- **Parallel work:** PRC items are being built by other sessions; CC rows depend on PRC-04 (done) and touch
  `materials/` and `vendors/`. Pull and re-read before each item.

## 11. Testing strategy

Unit tests for every costing rule (earned value, weighted average, allocation, ledger balance, advance,
double-count rules) with worked examples from the meeting (₹6,400 masons/helpers; ₹14/sq ft plaster; 20 m³
with 5 poured; M-sand ledger with advance). API tests per route with tenant isolation. Assistant journey
tests for "plastered 400 sq ft, 4 masons 2 helpers" and "paid Malabar 20,000 advance". Regression: DPR,
stock, expenses and labour suites unchanged. Pilot: compare one week of the client's manual sheet with
Mesiri's numbers line by line.

## 12. Rollback strategy

Every migration is additive (nullable columns, new tables), with a downgrade that drops only what it added.
Costing is a read model; turning it off is hiding the screens and the evening card (company setting).
Each CC item is its own commits; revert per item.

## 13. Labour isolation

Labour and Attendance are **not changed** (revised 8 Nov for CC-05): costing keeps its own table
(`labour_boq_allocations`: site, day, trade → BOQ line, man-days) and reads attendance through the Labour
module's own counted rule (`live_report_sql`, `counted_line_sql`). A column on attendance lines was the first
idea and was dropped: a re-sent list replaces the earlier lines (BE-10), so the link would be lost on every
correction. **Workforce and Payroll are not touched.** Stated in each phase report.

## 14. Success criteria

- On the pilot site, for one week, the evening card shows green/red per BOQ item and the QS agrees with the
  numbers within 5%.
- The GM can answer "was ₹15,000 of work done?" for any subcontract payment from the screen.
- Supplier balances match accounts for every pilot supplier.
- A material shortage against the BOQ is warned at least one delivery cycle before it runs out.
- The engineer's typing does not grow: no more than one extra question per day on average.

## 15. Order after 8 Nov, and a later Accounts module (Ilan, 8 Nov 2026)

Cost control is finished before a Finance / Accounts module: it is what the client said he pays for, it is
three items from the demo, and accounting is larger, riskier and compared with Tally.

| Step | Items |
|---|---|
| 0 | SEC-04 (needs Ilan), CC-17 review (needs Ilan), D-CC8, CC-25 |
| 1. Core | CC-05 labour → BOQ, CC-07 daily green / red, CC-11 evening card, CC-22 Cost control home |
| 2. Depth | CC-08 material reconciliation, CC-18 committed + forecast, CC-19 portfolio, CC-21 export |
| 3. Bridge | NXT-12 Tally export |
| 4. Accounts (V1.1) | Chart of accounts, posting from site records, party ledgers (on CC-09), Project P&L (absorbs CC-20), GST / TDS, closed months |

**Rules so Accounts reuses this work, not redoes it:**

- Cost control reads costs only through `domains/finance/costs.py`; switching "actual" to posted books later is
  one change there ("Site (live)" vs "Books (posted)", with the difference listed).
- Each cost line carries project, cost centre, date, source type and id: what a journal entry needs.
- No stored balances in cost control (CC-09 is a read model); the books own balances.
- Cost centres stay as an analysis tag; Accounts maps each expense category to a ledger account beside it.
- Committed cost, budget, earned and forecast stay cost control only; accounting has none of them.
- Labour: cost control counts attendance × wage (as worked); the books count what Payroll pays. The difference
  is shown, never hidden. Payroll is not changed for cost control.
- Margin (CC-20) is built once, as Project P&L.
