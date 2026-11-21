# Project setup gaps: plan (PS-01 … PS-10)

*Drafted 20 Nov 2026 from the QA-04 lifecycle test and the "what does a CEO / PM need to start a project" review.
Status: plan only. Nothing built, nothing committed.*

## Objective

Make a project's setup carry everything a construction company agrees and decides before day 1, so that cash flow,
penalties, approvals and cost per sq ft come out of Mesiri by themselves instead of from someone's head or Excel.

## What the review found (verified in code, 20 Nov)

**Already there, so no work is needed:** contract value, number and signed date; client GST % and GSTIN; **client TDS %**
(the RA bill nets it); retention %, mobilisation advance and its recovery %, defect liability months; start and handover
dates; project stage (tender → handover → defect period); BOQ with a labour / material / subcontract budget; schedule
with `slip_days` and `forecast_finish`; **client certification of RA bills** (`POST /billing/ra-bills/{id}/certify`);
variations; documents with `valid_until` and an "expiring" query.

**Missing or half there**, and what each plugs into:

| # | Gap | Today | Reuse |
|---|---|---|---|
| PS-01 | Client payment days | `payment_terms` is free text; cash flow assumes 30 days ("the contract has no payment term yet") | `accounts/cashflow.py` `client_days`, receivables |
| PS-02 | Contract type | — | `project_contracts` |
| PS-03 | Delay penalty (LD) | — | schedule `slip_days` / `forecast_finish`, `/lifecycle/projects` |
| PS-04 | Price escalation clause | — | Variations (an escalation claim is a variation) |
| PS-05 | Project size (type, built-up area, floors) → cost per sq ft | — | `projects`, project books (`/accounts/projects`) |
| PS-06 | Contingency % on the budget | — | BOQ budget strip, cost control |
| PS-07 | Approval limits that work | `auto_approval_limit` (₹5,000) is stored and shown on Finance settings, but **no code reads it**; purchase orders have no approval step at all | approvals inbox (`approvals/inbox.py` `KINDS`), the existing setting |
| PS-08 | Bank guarantees and insurance with expiry reminders | only as document names | `project_documents.valid_until`, `documents/store.expiring` |
| PS-09 | Approved brands list ("make list") | — | BOQ line materials, PO lines |
| PS-10 | Site setup costs (preliminaries) | possible by hand as a BOQ section | BOQ "Add section" |

**To check before planning work:** petty cash per site (today it is held per person: a cash or employee-advance
account with a holder, and expenses carry the project), and opening balances for a project already running when it
moves to Mesiri (Bring your data covers opening stock; ACC-12 vouchers cover company opening balances).

## Scope

In: PS-01 … PS-10 as below. Out: computing escalation from price indices (a claim is entered, not computed), cost-plus
billing logic (PS-02 records the type only; billing per type is a later item), anything in Payroll or Workforce.

## Phases

### Phase A: contract and project terms (PS-01, 02, 03, 04, 05, 06) · one additive migration

**Database (migration 0563, additive only; the head today is 0562):**
- `project_contracts` + `client_payment_days integer` (0–365), `contract_type text` (`item_rate` / `lump_sum` /
  `cost_plus`), `ld_pct_per_week numeric(5,2)`, `ld_cap_pct numeric(5,2)`, `escalation_applies boolean`,
  `escalation_terms text`; each with a CHECK like the existing ones.
- `projects` + `project_type text`, `built_up_area_sqft numeric(12,2)`, `floors integer`, `contingency_pct numeric(5,2)`.

**Backend:**
- `domains/billing/contracts.py` `TERM_FIELDS` and `domains/billing/router.py` contract in / out: the six new terms.
- `accounts/cashflow.py`: a client bill is expected on its date + the contract's `client_payment_days` (30 only when it
  is not set); receivables mark a bill **overdue** once that passes.
- `domains/schedule/router.py` (`/lifecycle/projects`, project start): **penalty risk** =
  contract value × `ld_pct_per_week` × (weeks of slip past `planned_finish`), capped at `ld_cap_pct`; 0 when on time.
- Project create / update (both routers; production serves `apps/whatsapp-assistant/src/projects/router.py`, see
  QA-05): the size fields and contingency.
- Project books (`/accounts/projects`): **cost per sq ft** = cost booked ÷ built-up area, and the BOQ value per sq ft.
- BOQ budget: budget + contingency shown as "Budget with contingency"; budget-vs-actual reads it.

**API:** no new routes; `GET/PUT /projects/{id}/contract` and `PATCH /projects/{id}` carry the new fields.
**v3 assistant:** add `project_contract` (GET) and `set_project_contract` (PUT) to `agent_api/tools.py` `ALLOWED`, so
"client pays in 45 days, 0.5% a week penalty" works on WhatsApp; SOP line only if the model needs one; a scripted test
in `tests/agent_api/`.

**Dashboard:** `components/billing/contract-dialog.tsx` (payment days, contract type, penalty, escalation);
`pages/ProjectDetails.tsx` details (type, area, floors, contingency); penalty risk on Project start and the owner's
Home; overdue client bills on Receivables and Home; cost per sq ft on project books. A `<Hint>` for LD, escalation,
contingency (glossary); tour markers kept (`LEARN_AND_TOURS.md`).

### Phase B: approval limits (PS-07) · **needs Ilan's approval** (permissions; changes Procurement behaviour)

- One rule, in one place: `approval_limit` per company (reuse `auto_approval_limit`), optionally per role.
- **Purchase orders:** an order above the limit placed by someone other than the owner or admin is saved as
  `awaiting_approval`; it joins the approvals inbox (`KINDS` + `purchase_order`), cannot be received or sent until
  approved; approve / reject routes beside the order's own.
- **Expenses / bills:** above the limit they wait for approval the same way (where the existing "approve it first"
  check lives in `expenses/router.py`).
- Every reader of order status follows: GRN receive, material plan, cash flow `orders`, pending deliveries.
- WhatsApp: "PO for 200 bags" above the limit says it is waiting for the owner, never that it was placed.
- Until this lands, the Finance settings field should say it is not used yet, or be hidden (it misleads today).

### Phase C: reuse only, no new tables (PS-08, 09, 10)

- **PS-08** Guarantees and insurance: document folders "Bank guarantee" and "Insurance" with `valid_until` (and an
  amount in the title or notes); the existing `expiring` query feeds the owner's Home and the approvals inbox
  30 days before expiry.
- **PS-09** Approved brands: a "brand / make" text on a BOQ line's material, shown on the request and the PO it
  becomes; a PO for another brand shows a warning (not a block).
- **PS-10** Site setup costs: "Add section" offers a ready "Preliminaries" section (site office, temporary water and
  power, mobilisation, safety) with empty quantities; nothing new in the database.

## Business value

Cash flow uses the real client terms; the owner sees penalty exposure before it is deducted; spending above a limit
needs a yes; every owner's first question ("what is my cost per sq ft?") has an answer; guarantees stop expiring
unnoticed.

## Files expected to change

`backend/migrations/versions/0563_project_setup_terms.py` (new) · `backend/src/mesiri/domains/billing/{contracts,router}.py`
· `backend/src/mesiri/domains/accounts/cashflow.py` · `backend/src/mesiri/domains/billing/receivables.py` ·
`backend/src/mesiri/domains/schedule/router.py` · `backend/src/mesiri/domains/projects/router.py` ·
`apps/whatsapp-assistant/src/projects/router.py` · `backend/src/mesiri/domains/accounts/*` (project books) ·
`apps/whatsapp-assistant/src/agent_api/tools.py` (+ SOP if needed) · dashboard: `components/billing/contract-dialog.tsx`,
`pages/ProjectDetails.tsx`, `pages/ProjectStartPage.tsx`, BOQ strip, Receivables, Home, `lib/billing.ts`, `lib/glossary.ts`.
Phase B adds `domains/procurement/orders_router.py`, `domains/approvals/inbox.py`, `domains/expenses/router.py`.
Phase C: `domains/documents/*`, BOQ materials, PO lines.

## Risks

- Two project routers (backend and assistant; production serves the assistant's). Every project field goes into both
  until they are merged; a test asserts the production app's route carries it (`test_production_app_router_mounting`).
- Cash flow and receivables change their numbers for projects that set payment days: intended, but say it in the report.
- Phase B changes who can place an order without waiting: the largest behaviour change; approval first.
- LD as "risk" only: Mesiri does not deduct it from bills (the client does); wording must not suggest it is booked.

## Testing strategy

Unit tests per rule (worked examples: 45 payment days; 3 weeks late at 0.5% capped at 5%; cost per sq ft); Postgres
integration for 0563 up and down; contract PUT/GET contract test; `tests/agent_api/` for the two v3 tools; dashboard
`tsc`, `oxlint`, `vite build` (tour and marker checks); full backend and assistant suites; then on production in the
test company "cd" with QA-2011 Sunrise Residency (QA-04).

## Rollback

Phase A: revert the commits; `alembic downgrade` drops only the new columns (nothing else reads them). Phase B: one
switch, the limit unset = today's behaviour. Phase C: no schema; revert the commits.

## Labour isolation

Nothing in Labour, Attendance, Payroll or Workforce changes. Wage sheets keep their own approval; Phase B does not
touch them.

## Success criteria

On QA-2011: set "client pays in 45 days, item rate, 0.5% a week LD capped at 5%"; the cash flow puts RA-01's money 45
days out; a bill past 45 days shows overdue; a 3-week slip shows penalty risk = 1.5% of the contract value; 12,000 sq ft
gives cost per sq ft on project books; (Phase B, once approved) a ₹60,000 PO by a PM waits in the owner's inbox; a bank
guarantee expiring in 20 days shows on Home.

## Order and tracker rows to add when approved

PS-01, PS-05, PS-03 first (cash, cost per sq ft, penalty), then PS-02, 04, 06 (same migration); PS-07 after Ilan's
yes; PS-08, 09, 10 last.
