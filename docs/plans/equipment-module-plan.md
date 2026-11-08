# Equipment & machinery module: plan (NXT-11, NXT-13, NXT-14, NXT-15)

> Phase 1 + Phase 2 of the development protocol, 8 Nov 2026. Asked in session: "Machines / equipment module: plan
> and build with all features, rich UI/UX, connection with other modules, all the pages." Content per machine per
> day was decided by Ilan on 7 Nov (D-N5): name, owned or hired, hours worked, idle / breakdown hours, diesel, hire rate.

## 1. Phase 1: what exists (investigated on `main` at `bdab93a`)

| Area | Exists | Use |
|---|---|---|
| `equipment_events` (0110, RLS 0484) | arrived / departed / usage / moved / refueled, hours, fuel qty / unit / cost, `paid_from_account_id`, from/to site. **No code reads or writes it.** | Reuse as the event log; additive columns only |
| `domains/equipment/`, `application/equipment/` | empty packages | The module's code goes here |
| `vendors.kind` (0516) | `'hire'` already reserved for NXT-11 | A hire company is a vendor of kind `hire`; no new vendor table |
| Supplier ledger (CC-09/CC-10, `vendors/ledger.py`) | bills = expenses with the vendor, payments, advances | A hire bill is an expense with the hire vendor; paid through the ledger, no second ledger |
| Cost read model (CC-01, `finance/costs.py`) | expenses + priced deliveries + labour per site | Add a **machines** bucket (hire earned but not yet billed + diesel not on an expense) |
| DPR (`application/dpr/assembly.py`, WhatsApp `channel/dpr_document/`) | labour, materials, issues; `equipment_items` always `[]` | Add a **Machinery** section from the day's logs |
| Site issues | issue type `EQUIPMENT_BREAKDOWN` exists | A breakdown on a log can raise / link an issue; no new issue system |
| v3 assistant (`agent_api/tools.py`, `SOP.md`) | no equipment tools; "JCB 6 hrs" has nowhere to go | Add routes to `ALLOWED` + an SOP rule |
| Classic runtime (`runtime/agent/equipment.py`) | replies "Equipment isn't recorded on WhatsApp yet" | Left alone (classic gets live-breakage fixes only) |
| Dashboard | Equipment group in `module-map.ts` with 3 `planned` pages; Purchase orders page = the agreed design (tiles, tabs, filters, list + detail, phone sheet) | Planned pages become working pages in that design |
| Roles | `may_act_on_material_requests` (office), `may_view_expenses` (money, SEC-01) | Reused as is; no role rule changes |
| Materials transfers (BE-32) + stock | site-to-site moves with stock | Shuttering & tools (NXT-14) reuse them |

Regression risks: DPR document (sent to clients daily), cost read model (Expenses "Full cost"), vendor page, the
assistant's tool list (a new tool changes what the model picks). Each gets a guard test.

## 2. Phase 2: implementation plan

**Objective.** Every machine on every site recorded once a day ("JCB 6 hrs, 2 hrs breakdown, 30 L diesel"), on
WhatsApp or the dashboard; the owner sees hours, idle time, diesel and hire cost per machine and per site; the hire
bill is checked against the hours recorded; the DPR has a Machinery section.

**Business value.** Machine hire and diesel are among the biggest site costs and today nobody can answer "the bill
says 8 hours a day; how many did it work?" or "why is diesel ₹18,000 this month?".

### Pages (dashboard, Equipment group)

| Page | URL | What it does |
|---|---|---|
| **Machines** | `/equipment` | Register + today's board. Tiles: on site, working today, broken down, not logged today, service due. Tabs: on site / off hire / all. Filters: site, type, owned/hired, hire company. Row: machine, site, today's hours bar (worked / idle / breakdown), diesel, cost. Detail panel (sheet on phone): today, last 14 days chart, utilisation, L/hr, month cost, quick actions **Log today · Move · Off hire · Edit**. New machine dialog. CSV export |
| **Machine** | `/equipment/:id` | One machine: KPIs (hours, idle, breakdown, utilisation %, diesel L and L/hr, hire earned), 30-day hours chart, logbook, movements, breakdowns (linked issues), hire bills, service |
| **Daily log** | `/equipment/log` | One date, one screen: every machine on site with inline hours / idle / breakdown / diesel / operator; save all at once (fewest taps for the engineer); copy yesterday |
| **Hire check** | `/equipment/hire` | NXT-13: per hired machine and period: hours and days recorded × rate (with the hire company's minimum hours/day) vs the bill; difference flagged; link to the bill expense and the vendor's ledger |
| **Shuttering & tools** | `/equipment/assets` | NXT-14: returnable items (materials in a returnable category) per site; send to another site (BE-32 transfer); lost / damaged |
| **Vehicles** | `/equipment/vehicles` | NXT-15 part: machines of kind `vehicle`, with trips and diesel per day (same register and log) |

### Connections to other modules

- **Vendors / supplier ledger:** hire company = vendor `kind='hire'`; Vendor page shows "Machines hired from them";
  hire bill = expense with that vendor, paid via the ledger.
- **Finance / cost centres:** machines bucket in `GET /finance/costs`; diesel can be paid from a money account
  (`paid_from_account_id`, already in the table) by recording it as an expense through the existing expense route.
- **Progress / issues:** breakdown hours with a reason can raise an `EQUIPMENT_BREAKDOWN` issue; the log links it.
- **DPR:** Machinery section (machine, owned/hired, worked, idle, breakdown, diesel) on site and project DPRs.
- **Labour / workforce:** operator by name or picked from the worker register (read only; no Workforce change).
- **Projects / sites:** a machine is at one site at a time; moves are events; site day shows its machines.
- **Materials:** shuttering & tools are materials in a returnable category, moved with transfers.
- **WhatsApp v3:** tools `machines`, `log_machine_day`, `move_machine`, `add_machine`; one SOP rule, three languages.

### Database (additive only; next head after 0516)

- `equipment`: id, organization_id, number (EQ-0001 per company), name, type, kind (`machine`/`vehicle`),
  ownership (`owned`/`hired`), vendor_id (hire company), rate + rate_unit (`hour`/`day`/`month`),
  min_hours_per_day, registration_no, make_model, fuel_type, current project/site, status
  (`active`/`off_hire`/`retired`), on_hire_from / off_hire_on, service_every_hours, last_service_on /
  last_service_hours, notes, audit columns. Unique (organization_id, number). RLS.
- `equipment_events` add: equipment_id, idle_hours, breakdown_hours, breakdown_reason, operator_name,
  operator_worker_id, trips, meter_reading, expense_id, issue_id, notes, voided_at; `event_type` gains `day_log`
  and `serviced`. One live `day_log` per machine per date (partial unique index).
- `equipment_hire_bills`: id, org, equipment_id, vendor_id, period_from / period_to, billed_hours, billed_days,
  rate, amount, bill_ref, expense_id, notes, audit. RLS.
- Shuttering: `material_categories.returnable boolean default false` (NXT-14 phase).

### API (`domains/equipment/router.py`, module gate)

`GET/POST /equipment`, `GET/PATCH /equipment/{id}`, `POST /equipment/{id}/move`, `POST /equipment/{id}/off-hire`,
`GET /equipment/logs`, `POST /equipment/logs` (one or many lines; upsert per machine per day),
`DELETE /equipment/logs/{id}` (void), `GET /equipment/summary` (tiles, per-site totals), `GET/POST
/equipment/hire-bills`, `GET /equipment/hire-check`. Rates, costs and bills only for `may_view_expenses`;
register changes by the office (`may_act_on_material_requests`); logs by anyone who can write at the site.

### Phases of the build

1. **NXT-11 core:** migration, register, day logs, moves, summary; Machines, Machine and Daily log pages; DPR
   Machinery; cost bucket; vendor page link; v3 tools + SOP; tests.
2. **NXT-13 hire check:** hire bills, check page.
3. **NXT-15 part:** vehicles (kind + trips) and service due. Fixed assets with depreciation stay *Later* (Accounts).
4. **NXT-14:** shuttering & tools over materials.

**Risks.** Cost double count: diesel typed as an expense *and* priced on a log (same known overlap as deliveries;
the log's "On expense" link removes it, said on the page). The assistant picking the new tools for work/labour
messages (guarded by scripted tests). DPR layout for clients (empty section hidden when no machines).

**Testing.** Backend unit + contract tests for each route (scope, roles, upsert, void, hire maths, cost bucket); DPR
assembly + PDF tests; `tests/agent_api/` scripted tests (the reported message, a sibling, the guard that "concreted
20 cum with the mixer" stays work); dashboard `tsc`, `oxlint`, `vite build`; full verification list from CLAUDE.md.

**Rollback.** Code: revert the commits (pages fall back to `planned`). Migration downgrade drops only the new
tables/columns and refuses while day logs exist (would lose data).

**Labour isolation.** Workforce is only read (operator picker). No Payroll / Workforce behaviour changes.

**Success criteria.** "JCB 6 hrs, 2 hrs breakdown, 30 L diesel" saves one day log from WhatsApp; the dashboard shows
it on Machines, the Machine page and the Daily log; the DPR shows it; Expenses "Full cost" includes hire and diesel;
the hire check shows recorded vs billed for a hired machine.

## 3. What was built (8 Nov 2026)

All four phases, as planned, pushed to `main` (commits tagged `NXT-11`).

| Part | Where |
|---|---|
| Migration 0518 (additive) | `equipment`, `equipment_hire_bills`, new columns on `equipment_events`, `material_categories.returnable`, module `equipment` on for every company (recorded in `equipment_switched_on_0518`) |
| Rules (pure, unit-tested) | `backend/src/mesiri/domains/equipment/rules.py`: hire earned per hour / day / month, state, service due, the hire check |
| API | `domains/equipment/router.py` (+ `store.py` SQL, `reads.py` for DPR and cost) |
| DPR | `application/dpr/assembly.py` `machinery` (site + project), `repositories/dpr.py`, WhatsApp PDF template Machinery section (hidden when empty) |
| Cost centres | `domains/finance/costs.py` machines bucket; Full cost and site day Money spent show it |
| Vendors | `VENDOR_LINKS` (delete refused / merge moves machines and hire bills); Machines hired on the supplier page |
| WhatsApp (v3) | `agent_api/tools.py` 7 routes, `SOP.md` rule 13, slip kind `machine`, record links; router mounted on `runtime/lifecycle.py` and `agent_api/app.py` |
| Dashboard | Machines (`/equipment`), Machine (`/equipment/:id`), Daily log (`/equipment/log`), Hire check (`/equipment/hire`), Vehicles (`/equipment/vehicles`), Shuttering & tools (`/equipment/assets`); site day Machines card |

**Decisions taken while building** (say if any should change):

- A machine's name is unique per company among machines not retired ("JCB", "JCB 2"): it is how the site says it.
- Breakdown hours raise one `EQUIPMENT_BREAKDOWN` issue per day log, only for today or yesterday, and without a
  site delay (a machine broken is not the site stopped; the DPR's hours lost adds issue delays up).
- A log at another site, for today or yesterday, moves the machine there (no separate "moved" message needed).
- A second message the same day changes only what it says ("JCB 30 L diesel" keeps the 6 hrs).
- Diesel priced on a log counts in Machines cost until it is linked to its expense (`expense_id`); a day on a hire
  bill linked to an expense is not counted again. Same known overlap as priced deliveries (CC-01).
- Monthly hire is spread at rate ÷ 30 per calendar day on hire.

**Rollback.** Revert the commits (the pages go back to the placeholders). `alembic downgrade 0517` drops the new
tables and columns and takes the module off exactly the companies 0518 switched on; it refuses while any machine
exists (it would lose the logs).

**Left / not verified.** NXT-15 fixed assets with depreciation. The SOP rule was not run on the live model here (the
SOP eval needs the provider key). Classic runtime still answers "Equipment isn't recorded on WhatsApp yet" (classic
gets only live-breakage fixes until it is deleted).
