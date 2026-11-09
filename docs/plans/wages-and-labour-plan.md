# Labour, wages and advances: the full module (Nov 2026)

> **Status:** plan written 9 Nov 2026 (asked in session: "cover the wages and advances and the full labour or
> workforce module with connection to others and full features and UX the users will need"). Tracker items
> `LW-01`..`LW-10` in [V1_TRACKER.md](V1_TRACKER.md). Replaces NXT-09 (Wages and advances).
>
> **Approved 9 Nov 2026 by Ilan (in session):** the plan and the defaults D-W1..D-W7 in §9, unchanged. It changes
> Workforce / Payroll behaviour (CLAUDE.md Module Isolation; D-N4 in [next-modules-plan.md](next-modules-plan.md)).

---

## 1. Who needs what

| Who | Asks | Today |
|---|---|---|
| **Whoever pays labour** (site engineer, PM, accountant) | "How much advance did Ravi take this week?" "What do I pay Suresh's team on Saturday?" | A notebook. Mesiri knows the days (attendance) but not advances, deductions or what was paid |
| **Owner / Director** | "What does labour cost me per project, and what do I still owe?" | Labour cost exists (attendance × wage, CC-01) but the books never see it: no wages payable, no payments |
| **Accountant** | "Wages paid in cash this week, by site, for Tally" | Nothing to import: wage payments are not records |
| **Site engineer** | "Who is on my site today, who is new, who left?" | Attendance yes; the register has no phone, no home site, no team |
| **Labour contractor** (Suresh, by WhatsApp) | "How many days did my team do, and what's due?" | Nothing to send them |

## 2. What exists (investigation, 9 Nov, `main` at `8dc196e`)

| Area | Exists | Reuse |
|---|---|---|
| Register | `workforce_workers`: name, trade, worker_type, default_daily_wage, contractor (**text**), status | Extend: phone, home project/site, team (a vendor), wage basis |
| Attendance | `labour_attendance_reports` (project, site, date, via, corrects/void) + `labour_attendance_lines` (worker or headcount per trade, daily_wage, contractor text, **vendor_id**, attendance_status, overtime_hours) | **The source of days**, never typed twice |
| Labour cost | `finance/costs.py`: attendance × wage per project/site (CC-01); `labour_boq_allocations` puts man-days on BOQ lines (CC-05); Green / red (CC-07) | Unchanged: cost stays "attendance at its wage" (accrual) |
| Contractors | `vendors` (kinds supplier, subcontractor, hire, service); subcontract `team_days` reads attendance lines by `vendor_id` | A labour contractor **is a vendor** (new kind `labour`), as D-N2 decided for subcontractors |
| Money | Money accounts incl. `employee_advance`; expenses; payments | An advance or a wage payment **comes out of a money account** (petty cash, bank) |
| Books | `accounts/posting.py` rules for expenses, money, RA bills, openings, overheads; nothing for labour | Add rules: wages accrual, wage payment, advance, recovery |
| WhatsApp (v3) | `labour_attendance`, `list_workers`, `record_attendance` in `agent_api/tools.py` | Add routes to `ALLOWED` + SOP rules; no workflow |
| Dashboard | `/labour` (Attendance · Workers views), worker sheet with stats, Linked strip to attendance and cost | Add Wages, Advances, team pages; muster roll |

## 3. The module, in the story

```
SITE    attendance (WhatsApp / web) ──► days per worker / team
            │
MONEY   advances given (cash / bank) ──► wage sheet for the week:
            │                              days × wage + overtime − advances − deductions = to pay
            ▼                                        │ approved
        cost (attendance × wage, BOQ lines)          ▼
                                             paid from a money account ──► books (wages payable, cash)
                                                                       ──► Tally, P&L, project cost settled
```

## 4. Features

### 4.1 Register: workers and teams (LW-01)
- Worker: name, **phone** (optional; WhatsApp share), trade, wage (per day; per month for staff), **home project and site**,
  **team** (a labour contractor), status (active / left), joined / left dates.
- **Team** = a vendor of kind `labour` (Suresh's team): phone, GSTIN optional, its workers, its rate per trade, how it is
  paid (to the contractor, or each worker). Attendance lines that name the contractor link to it (`vendor_id`, already a
  column); the text `contractor` field is matched to it once, as suppliers were (PRC unlinked names).
- Promote a "temporary" name from attendance into the register (exists) keeps its history (fix: inventory gap 9).

### 4.2 Muster roll (LW-02)
The site's month as the grid every Indian site keeps: workers down, days across, P / A / ½ / OT, totals per worker, per
trade and per team; from attendance, never typed again. Corrections on a day go through the existing attendance
correction (`corrects_report_id`). PDF and Excel (the format the labour office and contractors expect).

### 4.3 Advances (LW-03)
- "Gave Ravi 500 advance" (WhatsApp) or the web: to a worker or a team, amount, date, **from which money account**
  (site petty cash by default), note. The money account goes down; the payee's advance balance goes up.
- Each worker / team shows advances given, recovered, outstanding. A cap per worker (setting, optional) warns.

### 4.4 Wage sheet (LW-04)
- Per site (or project), per **pay period** (weekly by default, the company's pay day; fortnightly / monthly settable).
- One row per payee: a worker paid directly, or a team paid through its contractor.
  `days (from attendance, ½ days counted) × wage + overtime (hours × wage / 8) − advances recovered (all outstanding by
  default, editable) − deductions (with a reason) = net to pay`.
- Draft (anyone who pays) → **approved** (PM / owner / finance) → **paid** (from a money account, in full or part).
  A changed attendance after approval reopens the row with what changed.
- Drill into any row: its days (each a link to that day's attendance), its advances, its deductions.

### 4.5 Payment (LW-05)
- Pay a row, a team or the whole sheet from a money account; a payment slip (PDF / WhatsApp text) per payee:
  "Suresh team, 2–8 Nov: 48 days, ₹38,400, advance ₹5,000, paid ₹33,400". Sent to the contractor on WhatsApp.
- Unpaid balance carries to the next sheet.

### 4.6 Books and cost (LW-06)
- Posting rules (`accounts/posting.py`, one per source, as the others):
  attendance month → **Labour wages Dr / Wages payable Cr** (per project, site; the same figure cost control shows);
  advance → **Advance to <payee> Dr / Cash or bank Cr**; payment → **Wages payable Dr / Cash or bank Cr**,
  recovery → **Wages payable Dr / Advance Cr**.
- Cost control is unchanged (attendance at wage). The project P&L gains the settled / owed split for labour.
- Tally export: the new vouchers follow automatically (ACC-19 reads the journals).

### 4.7 WhatsApp (LW-07, v3: routes in `ALLOWED` + SOP rules, no workflow)
- "Gave Ravi 500 advance" → advance (asks which account only if the site has more than one).
- "What do I pay Suresh's team this week?" → the sheet row, as text.
- "Paid Suresh 33,400" → the payment against the approved row; a mismatch is asked about, never guessed.
- "Send Suresh his slip" → the slip to the contractor.
- Who may: the existing money-role rules (SEC-01): a site engineer can record an advance from their own petty cash;
  approving and paying sheets is PM / owner / finance.

### 4.8 Connections (LW-08)
- Links (`lib/links.ts`): worker / team ↔ attendance days ↔ wage sheet row ↔ payment ↔ cash book; team ↔ vendor
  account (one ledger, as subcontractors); worker ↔ BOQ labour (CC-05) ↔ Green / red; worker ↔ tasks given to them.
- Home tiles (`role-home.tsx`): **Wages due this week** and **Advances outstanding** (Director, Finance, PM); **Your
  site's labour today** for the site engineer. Project hub: **Labour** tile (days this week, wages owed).
- Help entries and WhatsApp lines for every new page in `module-map.ts`.

### 4.9 Dashboard (LW-09)
Labour module in SITE (attendance, muster roll, workers & teams) and MONEY (wages, advances) as one drawer
"Labour" with: **Attendance · Muster roll · Workers & teams · Wages · Advances**. Built on the page kit (ModuleTitle,
StatStrip, ListDetail pattern of Requests / Orders, LinkedStrip), phone first: the payer pays from a phone on site.

### 4.10 Reports (LW-10)
Labour by project / site / trade / team for a period (days, cost, paid, owed); per worker statement (shareable);
part of the period report (PRC-19).

## 5. Database (all additive)
- `workforce_workers` + `phone`, `project_id`, `site_id`, `vendor_id` (team), `wage_basis`, `joined_on`, `left_on`.
- `vendors.kind` gains `labour`.
- `labour_advances` (id, org, project, site, worker_id | vendor_id, amount, given_on, account_id, note, source,
  created_by, voided_at…).
- `wage_sheets` (id, org, project, site, period_from, period_to, status, approved_by/at) + `wage_sheet_rows` (payee,
  days, half_days, overtime_hours, wage, gross, advances_recovered, deductions JSON, net, paid, status) +
  `wage_payments` (row, amount, account_id, paid_on, by).
- RLS on every table, as 0503 onwards. Check the migration head right before writing one.

## 6. API
`/labour/advances` (CRUD), `/labour/wage-sheets` (draft from attendance, edit row, approve, reopen), `/labour/wage-
sheets/{id}/pay`, `/labour/muster` (grid), `/labour/teams` (vendor kind labour + its workers), each added to `ALLOWED`
where WhatsApp needs it. Money figures only for money roles; a site engineer sees their site's advances.

## 7. Risks
| Risk | Mitigation |
|---|---|
| Changes Workforce / Payroll behaviour | Ilan's approval before building (CLAUDE.md) |
| Double counting labour (cost vs payments) | Cost stays attendance × wage; payments only settle wages payable; a test pins it |
| Attendance corrected after a sheet is paid | The row reopens with the difference; the difference goes to the next sheet, never edits a paid row |
| Cash leaving without a record | Every advance and payment names its money account; the cash book shows it |
| Statutory pay (PF / ESI / minimum wage) | Out of scope for this plan (a later item); the sheet's deductions can hold them by reason |

## 8. Testing, rollback, success
- Backend unit tests per rule (days, half days, overtime, advance recovery, reopen); posting balanced; RLS; WhatsApp
  replay cases (advance, ask, pay, slip) in `tests/agent_api/`; screenshot check on the new pages; one week end to end
  against a local API.
- Rollback: new tables only; reverting the commits removes the pages and rules; nothing existing is rewritten.
- Success: a payer records advances and pays a week's sheet from a phone in under five minutes, with no figure typed
  that Mesiri already had; the cash book, the contractor's ledger and Tally agree.

## 9. Decisions (proposed default in **bold**)
| # | Question | Default |
|---|---|---|
| D-W1 | Pay period | **Weekly, pay day Saturday**, per company setting |
| D-W2 | Team paid through the contractor or each worker | **Through the contractor**, per team setting |
| D-W3 | Advance recovery | **All outstanding recovered on the next sheet**, editable per row |
| D-W4 | Overtime rate | **Hours × daily wage / 8** (1×), settable |
| D-W5 | Who approves / pays a sheet | **Prepare: anyone who pays; approve and pay: PM, owner, finance** |
| D-W6 | Books | **Accrue wages monthly from attendance; payments settle** |
| D-W7 | PF / ESI / statutory | **Not now** |
