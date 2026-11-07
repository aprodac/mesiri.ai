# Next modules by role: what each user needs next (Nov 2026)

> **Status:** plan written 7 Nov 2026 (asked in session by Ilan: "other important modules each role needs fast,
> from their perspective; add it to the tracker as the next doc"). Tracker items `NXT-01`..`NXT-12` in
> [V1_TRACKER.md](V1_TRACKER.md). Comes **after** Cost Control ([cost-control-plan.md](cost-control-plan.md));
> Procurement ([procurement-plan.md](procurement-plan.md)) is mostly built.
>
> This is a product judgment from the module map (`apps/dashboard/src/lib/module-map.ts`) and the code, not
> from customer interviews. Check each module with a customer before building past its first item.

---

## 1. Each role, in their own words

| Role | What they ask every day | Has today | Missing, most urgent | Next |
|---|---|---|---|---|
| **Owner / MD** | "Am I making or losing money on each site, and when does the client pay me?" | DPR on WhatsApp, Expenses, Money | **Client billing**: RA bills, payments received, receivables (NXT-01..04). Mesiri only tracks money going out | Project P&L; the evening cost card (CC-11) |
| **GM / Project manager** | "Which site is behind, what is waiting on me?" | DPRs, issues, BOQ, requests, orders | **Approvals inbox**: one "waiting for you" list, yes on WhatsApp (NXT-08) | Weekly lookahead (NXT-10) |
| **Site engineer / supervisor** | "Tell Mesiri once and be done." "₹15,000 to the concrete team: was the work done?" | Nearly everything on WhatsApp | **Subcontractors**: work orders, measurement, bill checks (NXT-05..07) | Equipment (WA-68, blocked) |
| **Accountant / finance** | "Who do we owe, what is paid, does it match Tally?" | Expenses, vendors, money accounts | **Supplier ledger and payables** (CC-09, CC-10, PRC-11: already planned) | Tally export (NXT-12) |
| **Storekeeper / purchase** | "What comes today, what did it cost last time, what went back?" | Stock, requests, orders, GRN | **Rates** (PRC-14, PRC-16), pending deliveries | Returns to supplier, central store |
| **Whoever pays labour** | "How much advance did Ravi take this week?" | Attendance, workers | **Wages and advances** (NXT-09): today a notebook | Weekly wage sheet |

## 2. Build order (after Cost Control phase 1–3)

1. **Client billing** (NXT-01..04). The only big gap on the money-in side; it is what the owner, who pays for
   Mesiri, cares about most. Reuses the BOQ client rate (CC-02) and measured quantities (CC-04).
2. **Subcontractors** (NXT-05..07). A daily pain on every Indian site; extends CC-06 and the supplier ledger
   (CC-09) instead of building a second ledger.
3. **Approvals inbox** (NXT-08). Reads what is already pending; no new approval system.
4. **Wages and advances** (NXT-09). As soon as Alan approves the Workforce / Payroll change.
5. **Lookahead tasks** (NXT-10), **Tally export** (NXT-12).

## 3. Investigation: what exists (Phase 1 findings, 7 Nov, `main` at `929e2bd`)

| Area | Exists today | Reuse |
|---|---|---|
| BOQ | `work_package_planned_items` with client / labour / material / subcontract rate, BOQ code (CC-02, migration 0508); `/projects/{id}/boq` | RA bills price measured quantities at the **client rate**; work orders at the **subcontract rate** |
| Measured work | `activity_quantities`; CC-04 links them to a BOQ line (todo) | RA bill quantity = measured to date − previous bill |
| Expenses | `expenses` with `workflow_status` (pending_confirmation …), `payment_status`, `vendor_id`; `expense_payments` (migration 0330) | Subcontract bill = an expense with a work order and measured quantity (CC-06); approvals inbox reads `workflow_status` |
| Vendors | `vendors` with phone, GSTIN, address (PRC-04) | A subcontractor is a vendor of kind "subcontractor": **no second party table** |
| Workforce | `workforce_workers` with `WorkerType.CONTRACTOR`; `labour_attendance_lines` | Labour contractor teams stay in Workforce; NXT-05 links a work order to a vendor, not to workers |
| Advances | `AccountType.EMPLOYEE_ADVANCE` money accounts (finance) | NXT-09 records worker advances against these, not a new money system |
| Requests / orders | `material_requests` status waiting; `purchase_orders` | Approvals inbox lists them |
| Equipment | `equipment_events` table (migration 0110); `domains/equipment/` empty | WA-68 (blocked); not repeated here |
| Approvals | `domains/approvals/` empty | NXT-08 is a read model over existing statuses, not a new table |
| Clients | only `projects.client_logo` (0467) | NXT-01 is new |
| Module map | Clients, RA bills, Variations, Payments received, Receivables, Subcontractors, Work orders, Bills & checks, Wages & advances, Approvals, Tasks, Tally sync: all `planned` pages | Each item turns its planned page into a working one |

## 4. Scope per module

### Client billing (NXT-01..04)
- **Client and contract per project:** client (name, GSTIN, address, contact), contract value, retention %,
  mobilisation advance and its recovery %, GST %, TDS %.
- **RA bill:** per project, numbered RA-01…; each BOQ line: quantity measured to date (CC-04), previous bills,
  this bill, client rate, amount; deductions (retention, advance recovery, TDS); GST; net. Draft → submitted →
  certified (client's certified amount may differ: stored, the difference shown). PDF on the letterhead (the
  PO document's renderer, PRC-26).
- **Payments received:** against a bill or on account; receivables per client with age (0–30, 31–60, 60+);
  "client paid 5 lakh for RA-03" on WhatsApp (v3 `ALLOWED` + SOP).
- **Variations / extra items:** a line outside the BOQ, approved by the client, then billed like a BOQ line.

### Subcontractors (NXT-05..07)
- **Work order:** subcontractor (vendor, kind subcontractor), BOQ lines with agreed rate and quantity, site,
  retention %, advance.
- **Measurement and bill check:** the bill's quantity against what the site recorded for those BOQ lines
  (CC-04); over → flagged; rate against the work order. From WhatsApp: "concrete team bill 15,000 for 40 m³".
- **Payments and ledger:** the supplier ledger (CC-09) with retention held and advances recovered.

### Approvals inbox (NXT-08)
One list per person: material requests waiting (PRC-22), expenses waiting for confirmation, subcontract bills
to check (NXT-06), stock adjustments to approve (BE-12), RA bills to submit (NXT-02). Each row opens the
existing screen; on WhatsApp "what is waiting for me?" lists them with the existing decide tools. Who may
decide stays each module's existing rule.

### Wages and advances (NXT-09)
Advance given to a worker or a labour contractor (WhatsApp: "gave Ravi 500 advance"), weekly sheet: days from
attendance × wage − advances = to pay; paid / unpaid. **Workforce and Payroll: needs Alan's approval.**

### Lookahead (NXT-10), Tally export (NXT-12)
- Weekly lookahead per site: the PM lists this week's tasks (BOQ lines or free text); the engineer's work
  updates tick them; the evening review names what slipped.
- Tally: export of expenses, supplier bills, payments and receipts as Tally vouchers (XML) for the CA; no
  two-way sync in the first step.

## 5. Database, API, frontend (outline; each item writes its own detail when built)

- **Database (all additive):** `clients`, `project_contracts`, `client_bills` + `client_bill_lines`,
  `client_receipts`, `variations`; `vendors.kind`; `work_orders` + `work_order_lines`, `expenses.work_order_id`;
  worker advances on the existing advance accounts (shape decided in NXT-09). RLS on every company table, as
  0503 onwards. Check the migration head (0514 on 7 Nov) right before writing one.
- **API:** routes the dashboard uses, then `agent_api/tools.py` `ALLOWED` lines and SOP rules (assistant v3).
  Money figures only for `may_view_expenses` roles (SEC-01).
- **Frontend:** each planned page in `module-map.ts` becomes a working page in the Requests / Purchase orders
  design (tiles, tabs, filters, detail panel, phone sheet).

## 6. Decisions needed (proposed default in **bold**)

| # | Question | Default |
|---|---|---|
| D-N1 | RA bill quantity: from site-measured quantities, or typed by the office? | **Measured, editable by the office before submit, change recorded** |
| D-N2 | Subcontractor: a vendor kind, or a Workforce contractor? | **Vendor kind** (no Workforce change); Workforce contractor teams link to it later |
| D-N3 | Who sees client bills and receivables? | **Owner, admin, finance** (needs Alan: permissions) |
| D-N4 | Wages and advances: in Mesiri, or left to payroll? | Needs Alan (Workforce / Payroll) |

## 7. Risks

- Client billing touches money owed to the company: a wrong RA bill is worse than none. Office edits before
  submit; every bill shows its source quantities.
- Subcontract checks depend on CC-04 (quantities linked to BOQ lines); without it the check has nothing to
  compare.
- Approvals inbox could duplicate each module's buttons; it must only link to them.
- Workforce / Payroll (NXT-09) is isolated by CLAUDE.md: no change until Alan approves.

## 8. Testing, rollback, labour isolation, success

- **Testing:** real-Postgres API tests per route, agent_api tool tests per `ALLOWED` line, browser check at
  1440 / 390 px, the full verification list in CLAUDE.md before every push.
- **Rollback:** each item is its own commits plus an additive migration: revert, then `alembic downgrade` to
  the previous head.
- **Labour isolation:** only NXT-09 touches Workforce / Payroll and waits for approval. NXT-05 links to vendors,
  not workers.
- **Success:** the owner sees what each client owes; the PM sees one "waiting for you" list; the engineer
  checks a subcontract bill against the work recorded, from WhatsApp.
