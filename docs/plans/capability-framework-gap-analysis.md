# Capability framework vs Mesiri: what is built, what is missing

Every capability in the *Construction Software Capability Framework* (32 modules, 19-page PDF), checked
against Mesiri's code on `main` at `786023f` (9 Nov 2026). The PDF's **Phase 1 "Operational foundation"**
is the current build target.

**How this was checked:** I read the backend routes, migrations and domain code and the dashboard pages and
module map (`apps/dashboard/src/lib/module-map.ts`). I did not click through the app, so ✅ means "the code
does it", not "tested in the app".

- ✅ Done: the capability exists (route + page or WhatsApp)
- 🟡 Part: some of it exists; what is missing is named
- ❌ Missing: nothing in the code

Module verdict: **Done** (everything ✅) · **Mostly done** (most of it ✅, gaps are small) · **Partly done** · **Not started**.

---

## Summary

| # | Module | PDF phase | ✅ | 🟡 | ❌ | Verdict |
|---|---|---|---|---|---|---|
| 01 | Project Management | **1** | 3 | 2 | 0 | Mostly done |
| 02 | BOQ Management | 2 | 5 | 1 | 0 | Mostly done |
| 03 | Estimation & Rate Analysis | 2 | 0 | 3 | 3 | Partly done |
| 04 | Planning & Scheduling | 3 | 6 | 0 | 0 | Done |
| 05 | Task & Work Management | **1** | 0 | 1 | 5 | Not started |
| 06 | Daily Progress Report | **1** | 4 | 2 | 0 | Mostly done |
| 07 | Procurement | **1** | 4 | 1 | 2 | Partly done |
| 08 | Inventory & Stock | **1** | 2 | 3 | 2 | Partly done |
| 09 | Vendor & Supplier | **1** | 2 | 3 | 1 | Partly done |
| 10 | Subcontractor | 2 | 5 | 1 | 0 | Mostly done |
| 11 | Workforce & Attendance | **1** | 2 | 4 | 1 | Partly done |
| 12 | Equipment & Machinery | 3 | 6 | 0 | 0 | Done |
| 13 | Expense | 2 | 5 | 1 | 0 | Mostly done |
| 14 | Budget & Cost | 2 | 6 | 1 | 0 | Mostly done |
| 15 | Billing & Invoicing | 2 | 5 | 1 | 0 | Mostly done |
| 16 | Quality | 3 | 0 | 2 | 4 | Partly done (small) |
| 17 | Safety | 3 | 0 | 2 | 4 | Partly done (small) |
| 18 | Document & Drawing | 3 | 4 | 1 | 1 | Mostly done |
| 19 | Finance & Accounts | — | 6 | 1 | 0 | Mostly done |
| 20 | Communication & Notifications | **1** | 1 | 3 | 2 | Partly done |
| 21 | Reports & Analytics | 4 | 3 | 3 | 0 | Partly done |
| 22 | User Management & Admin | **1** | 2 | 3 | 1 | Partly done |
| 23 | Measurement Book | 2 | 3 | 1 | 2 | Partly done |
| 24 | Contract Management | 2 | 2 | 2 | 2 | Partly done |
| 25 | Change Order & Variation | 2 | 0 | 0 | 7 | Not started |
| 26 | RFI & Technical Query | 3 | 0 | 0 | 6 | Not started |
| 27 | Drawing Revision & Technical Control | — | 3 | 1 | 2 | Partly done |
| 28 | Project Handover & Closeout | 4 | 0 | 2 | 4 | Partly done (small) |
| 29 | Project Risk | 3 | 0 | 0 | 6 | Not started |
| 30 | Client & Consultant | 3 | 0 | 3 | 3 | Partly done |
| 31 | Legal, Permits & Compliance | 3 | 1 | 2 | 3 | Partly done |
| 32 | Asset & Facility | 4 | 0 | 0 | 6 | Not started |
| | **Total (197 capabilities)** | | **80** | **50** | **67** | |

**Module verdicts:** Done 2 · Mostly done 9 · Partly done 16 · Not started 5.

### PDF Phase 1 only (9 modules, 56 capabilities)

| | ✅ | 🟡 | ❌ |
|---|---|---|---|
| Phase 1 | 20 | 22 | 14 |

The one Phase 1 module with nothing built is **Task & Work**. The biggest gaps in the others are the approvals
inbox, quotations (RFQ), reorder alerts and stock count, vendor rating, wages, and in-app notifications.

---

## Part I: Core modules (01–22)

### 01. Project Management (Phase 1): Mostly done

| Capability | Status | In Mesiri / what is missing |
|---|---|---|
| Create projects, sites, phases, work packages | ✅ | Projects, sites, Places (blocks, floors, rooms), BOQ sections as work packages |
| Project details, client info, team, key contacts | 🟡 | Client per project (Client billing), project members. **Missing:** a key-contacts list (architect, consultant, client's engineer) |
| Scope, objectives, milestones, responsibilities | 🟡 | Scope = BOQ, milestones in Schedule. **Missing:** objectives and who is responsible for what |
| Track status, progress, key dates, issues | ✅ | Project start, Schedule (on time / late), Issues |
| Project dashboard and activity history | ✅ | Project details, Today, Site log (all events), Cost overview |

### 02. BOQ Management (Phase 2): Mostly done

| Capability | Status | In Mesiri / what is missing |
|---|---|---|
| Create manually or import from Excel | ✅ | BOQ & budget: sections and lines, Excel import with preview and template |
| Organise by section, trade, floor, block, location | 🟡 | By section and BOQ code. **Missing:** a BOQ line tied to a floor or block (Places carry work, not BOQ lines) |
| Descriptions, units, quantities, rates, amounts | ✅ | Unit, quantity, client / labour / material / subcontract rates |
| Original, revised, approved, executed quantities | ✅ | A new planned quantity is a new revision with a reason; executed = measured |
| Compare BOQ with measured and billed | ✅ | BOQ progress (measured), RA bills (billed) |
| Revisions and approval trail | ✅ | Revision history with reason. An approve step for revisions is not there |

### 03. Estimation & Rate Analysis (Phase 2): Partly done

| Capability | Status | In Mesiri / what is missing |
|---|---|---|
| Estimates from BOQ items and quantities | 🟡 | BOQ amounts give the total. **Missing:** a separate estimate document / versions |
| Rate analysis (material, labour, equipment, wastage, overhead) | 🟡 | Material norms per BOQ unit with wastage % (`boq_material_norms`). **Missing:** labour, equipment and overhead build-up |
| Standard item rates, reusable templates | ❌ | Rate library is a placeholder page (`/planning/rates`) |
| Compare with vendor quotes and history | 🟡 | Supplier rate history (Procurement › Rates). **Missing:** compared against the estimate rate |
| Taxes, overheads, contingency, margin | ❌ | Not there |
| Estimate summaries and revisions | ❌ | Tendering is a placeholder (Later) |

### 04. Project Planning & Scheduling (Phase 3): Done

| Capability | Status | In Mesiri / what is missing |
|---|---|---|
| WBS, phases, activity schedule | ✅ | Schedule built on BOQ sections; can be drafted from a drawing |
| Planned start, finish, duration, milestones | ✅ | |
| Dependencies and critical activities | ✅ | Links with lag, critical path, conflicts |
| Calendar / timeline / Gantt view | ✅ | Schedule page |
| Baseline vs actual | ✅ | Planned vs actual start/end, progress from site measurements |
| Slippage and forecast completion | ✅ | Forecast end, knock-on to later activities, daily delay alert on WhatsApp |

### 05. Task & Work Management (Phase 1): Not started

| Capability | Status | In Mesiri / what is missing |
|---|---|---|
| Tasks, subtasks, recurring work | ❌ | No `tasks` table or API. `/planning/tasks` is a placeholder |
| Assign to people, supervisors, contractors, teams | ❌ | |
| Priority, due date, location, expected quantity | ❌ | |
| Status, % complete, blockers, remarks | 🟡 | Only at schedule-activity level (progress, done). Not per person |
| Photos, files, checklists on tasks | ❌ | |
| Escalate overdue, task history | ❌ | |

Related tracker item: NXT-10 (weekly lookahead per site, todo).

### 06. Daily Progress Report (Phase 1): Mostly done

| Capability | Status | In Mesiri / what is missing |
|---|---|---|
| Work done and quantities by BOQ item | ✅ | Work updates measured against BOQ lines |
| Labour strength, equipment, materials used | ✅ | Attendance, machine day logs, material usage in the report |
| Site conditions, weather, interruptions | ✅ | Site-day conditions, weather, issues with delay hours |
| Time-stamped photos, notes, documents | ✅ | Site log photos, gallery |
| Delays, visitors, instructions, key events | 🟡 | Delays and issues. **Missing:** visitors and instructions given on site |
| Review, approve, daily or period reports | 🟡 | Submit for review → approve → publish, revise, versions, PDF. **Missing:** weekly / monthly report (PRC-19) |

### 07. Procurement (Phase 1): Partly done

| Capability | Status | In Mesiri / what is missing |
|---|---|---|
| Material / service requisitions from site | ✅ | Materials › Requests (dashboard and WhatsApp) |
| RFQs sent to selected vendors | ❌ | Quotations is a placeholder (V1.5) |
| Receive and record quotations | ❌ | |
| Compare price, tax, delivery, terms | 🟡 | Rate history and last purchase rate only. **Missing:** a quotation comparison sheet |
| Route requests and quotes for approval | ✅ | Request decide (approve / reject / buy outside) |
| POs, amendments, delivery status | ✅ | Purchase orders: edit, cancel, close, reopen, part deliveries, PO document. Pending deliveries page is still a placeholder |
| Link GRN, inventory, supplier invoice check | ✅ | GRN, stock, bill matched to deliveries, not-billed list (PRC-11) |

### 08. Inventory & Stock (Phase 1): Partly done

| Capability | Status | In Mesiri / what is missing |
|---|---|---|
| Item catalogue, units, categories, locations | ✅ | Items, categories tree, unit conversions, per-site stock |
| Opening stock, receipts, issues, transfers, returns | 🟡 | Opening (Excel import), receipts, usage, transfers, reversals. **Missing:** return to supplier (`/procurement/returns` placeholder) |
| Available, reserved, damaged, minimum stock | 🟡 | Available per site; lost/damaged for returnable items. **Missing:** reserved and minimum stock levels |
| Batch, lot, serial details | ❌ | |
| Consumption against project, activity, BOQ item | ✅ | Usage per project/site; Materials vs BOQ in Cost control |
| Stock ledger, reorder alerts, valuation | 🟡 | Stock ledger per site and material, stock for a period. **Missing:** reorder alerts and a stock valuation report |
| Physical stock count and reconciliation | ❌ | Reconciliation page planned; no count entry |

### 09. Vendor & Supplier (Phase 1): Partly done

| Capability | Status | In Mesiri / what is missing |
|---|---|---|
| Profiles, contacts, address, tax details, categories | ✅ | Suppliers with phone, GSTIN, contacts, kind (supplier / hire / subcontractor), merge |
| Materials supplied, catalogues, quoted rates | 🟡 | Rate history per supplier. **Missing:** a catalogue per supplier and quoted rates |
| Store quotes, POs, invoices, certificates | 🟡 | POs and bills on the supplier page. **Missing:** quotations and certificates |
| Delivery performance, quality issues, pending | 🟡 | Pending orders and bills. **Missing:** on-time and quality tracking |
| Vendor rating / evaluation | ❌ | |
| Vendor purchases, outstanding, history | ✅ | Supplier ledger, statement, payments and advances |

### 10. Subcontractor (Phase 2): Mostly done

| Capability | Status | In Mesiri / what is missing |
|---|---|---|
| Profiles, scope, work packages | ✅ | Subcontractors, work orders on BOQ lines |
| Work orders with rates, quantities, milestones | ✅ | Work order document, issue / complete moves |
| Progress and attendance | ✅ | Site work and attendance per work order |
| Measurements, RA bills, deductions | 🟡 | Measurements (confirm / reject), bills checked against site. **Missing:** deductions (NXT-19, todo) |
| Advances, retention, recoveries, payments | ✅ | Advances, retention release, payments on the ledger |
| Performance, compliance documents, history | ✅ | Statement, history; documents in the work-order folder. No performance score |

### 11. Workforce & Attendance (Phase 1): Partly done

| Capability | Status | In Mesiri / what is missing |
|---|---|---|
| Employee, worker, crew, supervisor records | ✅ | Workers, trades, contractors |
| Attendance, shifts, overtime, leave, absence | 🟡 | Attendance, shifts, overtime. **Missing:** leave |
| Site-, contractor-, trade-wise attendance | ✅ | |
| Wage rates, advances, wage calculation | 🟡 | Daily wage stored. **Missing:** advances and wage sheet (NXT-09, blocked: Payroll) |
| Deployment and daily labour strength | 🟡 | Headcount per site per day. **Missing:** a deployment plan |
| Muster, timesheet, OT, payroll-input reports | 🟡 | Worker statistics. **Missing:** muster / timesheet exports |
| Verification (supervisor, location, device) | ❌ | Attendance sheet photos only; no location or device check |

### 12. Equipment & Machinery (Phase 3): Done

| Capability | Status | In Mesiri / what is missing |
|---|---|---|
| Register, ownership, hire status, specs | ✅ | Machines, vehicles; owned or hired with the hire company |
| Allocate to projects, sites, activities | ✅ | Move between sites |
| Hours, utilisation, idle, movement | ✅ | Daily log: worked, idle, breakdown hours, meter, trips |
| Fuel, maintenance, inspections, breakdowns | ✅ | Diesel, service, breakdown with reason (raises an issue) |
| Preventive maintenance reminders | ✅ | Service every N hours; service due shown |
| Rental charges, costs, downtime | ✅ | Hire rate, hire bills checked against logs (Hire check) |

### 13. Expense (Phase 2): Mostly done

| Capability | Status | In Mesiri / what is missing |
|---|---|---|
| Petty cash, site purchases, travel, misc. | ✅ | Expenses, petty cash vouchers |
| Category, amount, date, project, cost code | ✅ | Categories map to cost centres |
| Receipts and evidence | ✅ | Receipt photos |
| Submit for review and approval | 🟡 | Pending confirmation step. Part of the approvals inbox (NXT-08) is missing |
| Advances, settlements, reimbursements | ✅ | Payments against an expense, money transfers |
| Site-, category-, period-wise summaries | ✅ | Finance reports |

### 14. Budget & Cost (Phase 2): Mostly done

| Capability | Status | In Mesiri / what is missing |
|---|---|---|
| Budgets from estimate, BOQ, cost plan | ✅ | Budget from BOQ rates |
| By cost code, package, material, labour, trade | ✅ | Cost centres; labour / material / subcontract |
| Committed, actual, pending, forecast cost | ✅ | Committed (open POs, work orders), forecast at completion (CC-18) |
| Budget vs actual and variances | ✅ | Budget vs actual, Green / red |
| Cost-to-complete, projected final cost | ✅ | Forecast at completion |
| Impact of quantity changes, delays, variations | 🟡 | Quantity revisions flow in. **Missing:** variations (none built) and delay cost |
| Alerts over threshold | ✅ | Green / amber / red thresholds |

### 15. Billing & Invoicing (Phase 2): Mostly done

| Capability | Status | In Mesiri / what is missing |
|---|---|---|
| Client RA and milestone bills | ✅ | RA bills (submit, certify, cancel), RA bill document |
| Bill quantities from measurements and BOQ | ✅ | Measured to date − previous bills |
| Tax, deductions, retention, advances, terms | ✅ | GST, TDS, retention, advance recovery from the contract |
| Supplier invoices matched to PO and GRN | ✅ | Bill matched to deliveries, mismatch flag |
| Submission, certification, rejection, payment | ✅ | Bill statuses, receipts |
| History, documents, outstanding | 🟡 | Receivables with age. Procurement › Bills page is a placeholder |

### 16. Quality (Phase 3): Partly done (small)

| Capability | Status | In Mesiri / what is missing |
|---|---|---|
| Inspection and test plans, checklists | ❌ | Quality checks is a placeholder (`/site/quality`) |
| Schedule and record inspections | ❌ | |
| Test results, defects, NCRs | 🟡 | Issues have a QUALITY type; test reports can be stored in Documents. No NCR record |
| Corrective / preventive actions with due dates | ❌ | |
| Re-inspection, closure, approval | 🟡 | Issues: acknowledge, resolve, won't fix. No re-inspection |
| Quality records and certificates | ❌ | |

### 17. Safety (Phase 3): Partly done (small)

| Capability | Status | In Mesiri / what is missing |
|---|---|---|
| Safety inspections and observations | ❌ | Safety is a placeholder (Later) |
| Incidents, near misses, unsafe conditions | 🟡 | Issues have a SAFETY type (with photo). No near-miss / incident form |
| Toolbox talks, inductions, training | ❌ | |
| PPE and safety checklists | ❌ | |
| Corrective actions and closure | 🟡 | Through Issues (resolve) |
| Incident reports and safety summaries | ❌ | |

### 18. Document & Drawing (Phase 3): Mostly done

| Capability | Status | In Mesiri / what is missing |
|---|---|---|
| Store contracts, specs, permits, method statements | ✅ | Documents: folders contract, drawing, approval, BOQ, work order, test report, handover, other |
| Organise drawings by discipline | ✅ | Architectural, structural, MEP |
| Numbers, revisions, issue dates, approval status | ✅ | Number, revision, revision date, status |
| Transmittals, distribution, acknowledgements | ❌ | |
| Superseded vs current | ✅ | Current / superseded / archived with history |
| Access control and history | 🟡 | Money folders restricted to owner, admin, finance, PM. No per-person access |

### 19. Finance & Accounts (not in the PDF's phase table): Mostly done

| Capability | Status | In Mesiri / what is missing |
|---|---|---|
| Chart of accounts, project / cost-centre mapping | ✅ | Chart of accounts, ledger groups, project books |
| Receipts, payments, journals, ledgers | ✅ | Journal entries, ledgers, day book |
| Customer and supplier balances, due dates | ✅ | Receivables, supplier ledgers |
| Reconcile advances, petty cash, bank | 🟡 | Advances and petty cash. **Missing:** bank reconciliation (Later) |
| Tax records, export to accounting | ✅ | GST, TDS, Tally export |
| Project financials, cash flow | ✅ | Project P&L, P&L, balance sheet, trial balance. Cash flow page is Later |
| Approval controls, audit trail | ✅ | Month close / reopen, reversals (never delete) |

### 20. Communication & Notifications (Phase 1): Partly done

| Capability | Status | In Mesiri / what is missing |
|---|---|---|
| Project, site, task, team channels | 🟡 | WhatsApp groups per project, WhatsApp inbox. No channels inside the web app |
| Reminders for deadlines, approvals, deliveries | 🟡 | Bill reminders, missing-DPR nudges, schedule delay alerts, automations. **Missing:** approval reminders |
| Meeting minutes, decisions, action items | ❌ | |
| Notify about task updates, delays, exceptions | ✅ | Notification queue, escalations, delay alerts, announcements (all on WhatsApp) |
| Attachments, comments, acknowledgements | 🟡 | Issue acknowledge, comments on DPR. No comment thread per record |
| Link communication to the record | ❌ | No in-app notification centre linked to records |

### 21. Reports & Analytics (Phase 4, advanced): Partly done

| Capability | Status | In Mesiri / what is missing |
|---|---|---|
| Progress, DPR, productivity reports | 🟡 | Daily reports, Analytics, weekly / monthly report (PRC-19, page + PDF + Excel). **Missing:** sending it on a schedule (PRC-20), labour productivity (RPT-03) |
| BOQ, measurement, billing status | ✅ | BOQ progress, RA bills, receivables |
| Procurement, vendor, stock, consumption | 🟡 | Stock for a period, supplier statements. Procurement reports is a placeholder |
| Labour, equipment, expenses | ✅ | Attendance, equipment log, finance reports |
| Budget vs actual, cash flow, outstanding | ✅ | Cost control, Accounts |
| Dashboards, filters, exports, role-based | 🟡 | Excel exports (BOQ, cost, accounts), role-based pages. **Missing:** cross-module dashboard |

### 22. User Management & Administration (Phase 1): Partly done

| Capability | Status | In Mesiri / what is missing |
|---|---|---|
| Users, teams, roles, project memberships | ✅ | Team, roles, project and site members, join by QR |
| Role- and permission-based access | ✅ | Fixed roles (Admin, PM, Site Engineer, Finance…), all-projects or selected projects |
| Organisation, project, site settings | 🟡 | Company settings, modules on/off, branding. Few per-project settings |
| Approval hierarchies, workflow permissions | ❌ | No approval chain; who-may-order is blocked (PRC-12) |
| Login, activity, audit logs | 🟡 | Superadmin audit log only; no log companies can see (SA-08 todo) |
| Notifications, master data, preferences | 🟡 | Preferences, report time, categories. No notification settings page |

---

## Part II: Extended modules (23–32)

### 23. Measurement Book (Phase 2): Partly done

| Capability | Status | In Mesiri / what is missing |
|---|---|---|
| Measurements by item, location, date, person | ✅ | Measured quantities on BOQ lines, by place and who reported |
| Dimensions (L, B, H, area, volume) | ❌ | Only the final quantity is kept |
| Quantities from formulas | ❌ | |
| Compare with BOQ and previous measurements | ✅ | BOQ progress, measured to date |
| Checking, certification, approval | 🟡 | Subcontractor measurements: confirm / reject. No check step for site measurements |
| Measurement sheets linked to RA bills | ✅ | RA bills use measured quantities |

### 24. Contract Management (Phase 2): Partly done

| Capability | Status | In Mesiri / what is missing |
|---|---|---|
| Agreement, scope, value, parties | ✅ | Project contract (client, value), work orders for subcontractors |
| Payment terms, milestones, retention, advance | ✅ | Retention %, mobilisation advance and its recovery, GST, TDS |
| Start / end dates, obligations, deliverables | 🟡 | Project dates. **Missing:** obligations and deliverables |
| Amendments, extensions, approvals | ❌ | |
| Insurance, bonds, guarantees | 🟡 | Can be stored in Documents with an expiry date. No register |
| Key dates and contract status | ❌ | |

### 25. Change Order & Variation (Phase 2): Not started

All 7 capabilities missing (raise a change, reason and evidence, cost impact, schedule impact, approval,
history, update the BOQ and budget). `/billing/variations` is a placeholder (Later). Tracker item NXT-04.

### 26. RFI & Technical Query (Phase 3): Not started

All 6 capabilities missing. No page in the module map.

### 27. Drawing Revision & Technical Control (not in the PDF's phase table): Partly done

| Capability | Status | In Mesiri / what is missing |
|---|---|---|
| Drawing register by discipline, package, location | ✅ | Documents (drawing folder, discipline) |
| Revision, issue purpose, date, approval | ✅ | Revision, date, status |
| Compare revisions, highlight changes | ❌ | |
| Transmittals and who received each revision | ❌ | |
| Flag superseded drawings | ✅ | |
| Link RFIs, instructions, work packages | 🟡 | Drawing → places and schedule (Drawing check). No RFIs to link |

### 28. Project Handover & Closeout (Phase 4): Partly done (small)

| Capability | Status | In Mesiri / what is missing |
|---|---|---|
| Completion and handover checklists | ❌ | |
| Snag / punch list | ❌ | Snag list is a placeholder |
| As-built drawings, test certificates, manuals | 🟡 | Documents has handover and test-report folders |
| Warranties, guarantees, maintenance info | 🟡 | Same: stored, no register |
| Final measurements, final accounts | ❌ | Closeout report placeholder (CC-14); work-order final account NXT-22 todo |
| Client inspection, completion certificate, sign-off | ❌ | |

### 29. Project Risk (Phase 3): Not started

All 6 capabilities missing.

### 30. Client & Consultant (Phase 3): Partly done

| Capability | Status | In Mesiri / what is missing |
|---|---|---|
| Client, architect, engineer, consultant directory | 🟡 | Clients only |
| Meetings, commitments, decisions | ❌ | |
| Submissions, approvals, comments | ❌ | |
| Share approved progress reports and documents | 🟡 | DPR sent to project recipients on WhatsApp; client view link shows photos from approved site reports (CV-02) |
| Client requests, complaints, feedback | ❌ | |
| Controlled client access | ✅ | Client view (CV-01..CV-03, 9 Nov 2026): a revocable secret link per project, read only, no rates or costs |

### 31. Legal, Permits & Compliance (Phase 3): Partly done

| Capability | Status | In Mesiri / what is missing |
|---|---|---|
| Permit, licence, certificate registers | 🟡 | Stored in Documents (approval folder). No register view |
| Authority, reference, validity, renewal dates | 🟡 | Document number and `valid_until`. No issuing authority |
| Inspection records and evidence | ✅ | Documents |
| Labour, safety, environmental documents | ❌ | |
| Responsibilities and renewal reminders | ❌ | `valid_until` is stored, but nothing reminds anyone |
| Audit-ready submission history | ❌ | |

### 32. Asset & Facility (Phase 4): Not started

All 6 capabilities missing. (Equipment covers the company's own machines, not the client's building after
handover. Fixed assets in Accounts is Later.)

---

## What to build for Phase 1, in order

1. **Task & Work** (module 05): the only Phase 1 module with nothing built. New module, same pattern as Cost
   control (CC-17): module switch, sidebar group, backend domain, v3 tool in `agent_api/tools.py`.
2. **Approvals inbox** (NXT-08): one "waiting for you" list for requests, expenses, bills and measurements
   (modules 07, 13, 22).
3. **Quotations / RFQ** (module 07): request quotes, record them, compare, pick one into a PO. Planned 9 Nov: [procurement-phase2-plan.md](procurement-phase2-plan.md) (PRC-40..52, with returns, reorder, stock count, vendor rating).
4. **Reorder levels, stock count, returns** (module 08).
5. **Vendor rating** (module 09): on-time delivery and quality, worked out from GRNs and issues.
6. **In-app notifications and meeting minutes** (module 20).
7. **Company audit log** (module 22, SA-08) and **DPR visitors and instructions** (module 06).

Needs Alan's approval first (CLAUDE.md): wages and advances (Payroll, NXT-09), who may order and
approval hierarchies (permissions, PRC-12).
