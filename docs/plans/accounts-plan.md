# Accounts: a full accounting and finance module (plan, 9 Nov 2026)

> Asked by Ilan, 9 Nov 2026: "create a plan and let's create full accounting and finance module with rich UX".
> Status: **approved by Ilan, 9 Nov 2026, with every recommended default; Phases A to F built** (A, B, C on 9 Nov;
> D, E, F on 10 Nov: ACC-12, 13, 15..21; ACC-14's checklist is another session's; see
> [accounts-posting.md](../architecture/accounts-posting.md) for what was built and how it differs from §5).
> Was: plan, waiting for approval (Phase 2 of the protocol). Accounts is security-sensitive (who can post,
> close and reopen the books) and touches shared components (roles, module map, every money record as a source),
> so it does not start in autonomous mode. Decisions D-ACC1..D-ACC12 below each carry a recommended default.

## 1. Objective

The company's books in Mesiri: every rupee that moves on site (expenses, supplier bills and payments, client bills
and receipts, transfers, advances) becomes a balanced double-entry journal automatically, so the owner and the
accountant get a trial balance, P&L, balance sheet, GST and TDS figures, cash and bank books and party ledgers
without retyping, and the CA can still take everything to Tally.

**The rule that makes it work:** the site and office keep recording what they already record (nothing new to type);
accounting is *posted from those records*, never a second place to enter a cost. An accountant adds only what has no
site record: manual journals, depreciation, opening balances, bank charges found on reconciliation.

## 2. What exists today (investigated 9 Nov)

| Area | Built | Where |
|---|---|---|
| Money accounts (cash, bank, employee advance, other) with opening balance; balance = opening + transactions (never stored) | yes | `money_accounts`, `money_transactions` (0320, 0340), Finance › Money |
| Money movements: fund received, transfer, expense payment, adjustment, reversal | yes | `money_transactions.transaction_type`, `POST /finance/transfers` |
| Expenses: category, vendor, project / site, GST (`tax_amount`, inclusive), paid / unpaid / own pocket, reverse | yes | `expenses`, `expense_payments` (0100, 0330, 0380), Finance › Expenses |
| Supplier ledger: opening balance, deliveries not billed, bills, payments, advances, running balance, payables | yes (read model) | `domains/vendors/ledger.py` (CC-09, CC-10) |
| Subcontract bills with retention, advance recovery, TDS 194C (paid "from" a TDS payable account) | yes | `work_order_bills`, `domains/subcontracts` (NXT-05..07) |
| Machine hire bills | yes | `equipment_hire_bills` (NXT-15) |
| Client RA bills (gross, GST, retention, advance recovery, TDS, net) and money received | yes | `ra_bills`, `client_receipts` (NXT-02, NXT-03) |
| Cost read model (Full cost, cost centres, before claimable GST) | yes | `finance/costs.py`, `costing/` (CC-01, D-CC8) |
| Tally export (expenses, payments, RA bills, receipts as vouchers) | yes | `finance/tally.py` (NXT-12) |
| Budgets (project spending limits) | yes, light | `budgets` (0340) |
| Chart of accounts, double entry, periods, trial balance, P&L, balance sheet, GST / TDS registers, bank reconciliation, fixed assets, year end | **no** | planned pages in the module map's Accounts group (WEB-75) |
| Wages payable from attendance | no | NXT-09, blocked (Payroll / Workforce decision D-N4) |

## 3. Scope

**In:** chart of accounts; financial years and monthly periods; a posting engine that turns every money record into
journals; manual journal vouchers; day book; ledger statements (any ledger, any party); trial balance; P&L (company,
per project, per cost centre); balance sheet; cash and bank books; receivables and payables ageing on the books;
GST summary (output, input, net payable per month, ready for GSTR-3B); TDS registers (deducted on subcontract bills,
deducted by clients); bank reconciliation with a statement import; period close with a checklist; changes after
close; fixed assets and depreciation; year-end close and carry forward; cash flow; Tally export from the posted
books; Accounts home dashboard; WhatsApp answers for the owner and accountant; PDF / Excel of every report.

**Out (V1 of Accounts):** filing GST or TDS returns with the government (the CA files; we give the figures and
files), e-invoicing / e-way bills, payroll processing (Payroll is a protected module: NXT-09 / D-N4), multi-currency,
inventory valuation in the books beyond deliveries and materials expense (stock stays in Materials), two-way Tally
sync (import from Tally), consolidation of several companies.

## 4. Business value

- The owner sees profit, cash and what is owed and owing **today**, not when the CA sends the quarter.
- The accountant stops retyping site expenses into Tally: one confirmed record on site is one voucher in the books.
- Project P&L (billed against every cost booked to the project) answers "which site makes money", absorbing CC-20.
- GST and TDS figures ready each month: fewer missed input credits, no surprise at filing time.
- It is the module customers compare with Tally: "Mesiri keeps the books" is a reason to pay for V1.1 (V1_SCOPE).

## 5. Design (how it works)

### 5.1 Chart of accounts (`ledger_groups`, `ledgers`)
- **Groups** in a tree, seeded with Tally's primary groups (Capital Account, Loans, Current Liabilities › Sundry
  Creditors / Duties & Taxes / Provisions, Fixed Assets, Current Assets › Sundry Debtors / Bank Accounts /
  Cash-in-Hand / Loans & Advances / Deposits, Sales Accounts, Direct / Indirect Income, Purchase Accounts, Direct /
  Indirect Expenses), each with its nature (asset, liability, income, expense, equity), so reports and the Tally
  export line up with what the CA knows.
- **Ledgers** belong to a group. Seeded for construction: Contract revenue, Output GST (CGST / SGST / IGST),
  Input GST, TDS receivable, TDS payable 194C / 194J, Retention receivable, Retention payable, Mobilisation advance
  received, Advances to suppliers, Expenses payable, Wages payable, Bank charges, Depreciation, Round off, Opening
  balance difference.
- **Linked ledgers** are made, never typed: each supplier and client gets its party ledger, each money account its
  bank / cash ledger, each expense category its expense ledger (`ledger_links`: source kind + id → ledger). A company
  can rename, regroup or merge ledgers; links follow.

### 5.2 Journals (`journal_entries`, `journal_lines`)
- An entry: date, voucher type (Journal, Payment, Receipt, Contra, Sales, Purchase, Debit / Credit note), number per
  type and year, narration, **source** (kind + id + a fingerprint of what was posted), project, status
  (posted, reversed), who and when.
- A line: ledger, debit or credit amount (one of them), project, site, cost centre (CC-01's centres), party.
- Every entry balances (database check: sum of debits = sum of credits). Amounts in paise-exact numerics.

### 5.3 The posting engine (`domains/accounts/posting/`)
One rule table, one function per source kind, each pure (record in, balanced lines out), the way `tally.py` already
maps them:

| Source | Voucher | Lines |
|---|---|---|
| Expense (confirmed) | Purchase / Journal | Dr category ledger (net of claimable GST) + Dr Input GST; Cr supplier / staff (own pocket) / Expenses payable |
| Expense payment, supplier payment, advance | Payment | Dr party (or Advances to suppliers); Cr bank / cash |
| Applied advance (no money) | Journal | Dr supplier; Cr Advances to suppliers |
| Subcontract bill | Purchase | Dr Subcontract work (gross); Cr subcontractor net, Cr TDS payable 194C, Cr Retention payable, Cr their advance |
| Machine hire bill | Purchase | Dr Machine hire; Cr hirer |
| Transfer between accounts | Contra | Dr receiving account; Cr paying account |
| Fund received | Receipt | Dr account; Cr Capital / Loan / the ledger the office picks (asked once, remembered per source) |
| RA bill sent | Sales | Dr client net, Dr TDS receivable, Dr Retention receivable, Dr Mobilisation advance received; Cr Contract revenue, Cr Output GST |
| Client receipt | Receipt | Dr bank / cash; Cr client or Mobilisation advance received |
| Deliveries not billed at month end (D-ACC5) | Journal, reversing | Dr Materials; Cr Goods received not invoiced |
| Opening balances (suppliers, accounts, clients) | Journal | against Opening balance difference |

**How posting runs (D-ACC1):** a *posting sweep* finds source records new or changed since they were posted
(fingerprint differs), and posts, re-posts or reverses them; it runs on the existing 15-minute scheduler and before
any Accounts report is read. No write path in Expenses, Vendors, Billing or Subcontracts changes, so those modules
stay untouched and a missed hook can never leave the books behind. Each journal points back at its source, and every
report line opens it ("drill down").

### 5.4 Periods, close and late changes (`accounting_periods`, D-ACC2)
- Financial year April–March (D-ACC7), months as periods: open, closing, closed.
- **Close a month:** a checklist page (every source posted, bank reconciled, GST figures checked, deliveries not
  billed accrued, suspense ledgers empty) then Close; owner / admin / finance. Reopen: owner / admin, with a reason.
- **A source changed after its month closed** (a bill edited in December for October): its old journal stays; the
  difference is posted on the first open day, marked "changed after close", and listed on the close page and the
  home. Nothing on site is blocked.

### 5.5 Reports (all from journal lines; every figure drills down)
Trial balance · P&L (month, quarter, year, comparisons; per project; per cost centre) · Balance sheet · Day book ·
Ledger statement (any ledger or party, opening, lines, running balance, closing) · Cash book and bank book ·
Receivables and payables ageing (from the books, matching the existing pages) · GST summary (output by rate, input
claimable, net payable, per month, GSTR-3B layout; GSTIN-wise purchase list for 2B matching) · TDS registers (194C
deducted with challan status; TDS deducted by clients for 26AS matching) · Cash flow (direct method from bank / cash
lines) · Fixed asset register with depreciation.

### 5.6 Bank reconciliation
Import the bank statement (Excel / CSV of the major Indian banks, column mapping remembered per bank), match lines to
posted bank journals (amount, date ±3 days, UTR / cheque in the narration), suggest, confirm in one tap; what the bank
has and the books do not (charges, interest) becomes a journal with one tap; reconciled balance and difference shown.

### 5.7 Fixed assets and year end
Asset register (from an expense marked capital, or added), WDV depreciation at Income-tax rates by default (D-ACC9),
monthly or yearly; disposal. Year end: closing entries move P&L to capital / reserves, the next year opens with the
balances, the year locks.

### 5.8 Company-wise and project-wise (Ilan, 9 Nov: "company wise and project wise also needed")

Every journal line carries its **project, site and cost centre** (taken from the source record: an expense's project
and site, a bill's project, a receipt's project). So every book can be read three ways, with the same scope bar the
dashboard already has (All projects / a project / a site):

| Report | Company | Project | Site |
|---|---|---|---|
| Trial balance, day book, ledger statements | yes | yes (lines of that project) | yes |
| P&L | yes | **yes: billed − every cost booked to it, by cost centre, against the BOQ budget and forecast** | yes (cost side) |
| Balance sheet | yes (the legal one) | **Project position** instead: work billed, received, receivable, retention held by the client, advances, what the project owes suppliers and subcontractors, retention held by us, cost to date vs billed (WIP) | — |
| Cash and bank books | yes | money paid or received for the project | the site's petty cash |
| Receivables / payables ageing | yes | yes | — |
| GST, TDS | yes (returns are per GSTIN) | yes (for review; filing stays company-wise) | — |
| Accounts home | yes | yes (the project's own home) | — |

**Money with no project** (head office rent, salaries of office staff, bank interest, capital, loans) stays on the
company's books as "Head office" and is never forced onto a project. **Overheads to projects (D-ACC11):** an optional
monthly allocation journal shares head-office expenses over projects (by cost or by billing, the company picks), so
project P&L can be shown before and after overheads; off by default.

**Several companies (D-ACC12):** each company in Mesiri already has its own books (row-level security per company,
as today). A group owner with several legal companies sees each company's books separately; a consolidated group view
is later.

## 6. UX and UI (rich, but the least work for the user)

| Screen | What it does | Notes |
|---|---|---|
| **Accounts home** | Cash and bank today, receivables / payables by age, this month's P&L against last, GST payable this month, "needs attention" (unposted, unreconciled, changed after close, uncategorised, suspense) | One screen for the owner; cards drill down |
| **Day book** | Every voucher of a day or range, filters (type, project, party, ledger), search, totals | The accountant's main list; keyboard: ↑↓ to move, Enter to open |
| **Voucher view** | The journal with its lines, the source record it came from (photo of the bill), history | Read-only for posted; "Reverse" for manual ones |
| **New voucher** | Manual journal / contra with ledger search-as-you-type, Dr / Cr columns that balance live, project and cost centre per line | Tally-like speed: Tab between cells, Ctrl+Enter to save |
| **Ledger statement** | Any ledger or party: opening, lines, running balance; share on WhatsApp / PDF | Party statements to suppliers and clients |
| **Trial balance / P&L / Balance sheet** | Period picker, compare columns, expand groups, drill to ledger, Excel / PDF | Same visual language as Cost control |
| **Project P&L and Project position** | Billed, cost by centre, margin, against BOQ budget (CC-18 forecast); billed / received / receivable / retention / advances / payables of the project | Replaces CC-20; every report also switches Company / Project / Site with the scope bar |
| **GST** | Month view: output, input, net payable; purchase list by GSTIN; missing GSTIN warnings | Export for the CA |
| **TDS** | Deducted (to deposit) by section and month; deducted by clients | Due dates shown |
| **Bank reconciliation** | Upload statement, auto-match, confirm, create missing journals | Progress bar to "reconciled" |
| **Close the month** | Checklist with each item's state and a link to fix it; Close button | Reopen with reason |
| **Chart of accounts** | Tree, rename, regroup, merge, add; where each ledger is used | Mapping suggestions for categories |
| **Fixed assets** | Register, depreciation schedule, disposals | |
| **Year end** | Guided close and carry forward | |

All pages: Indian number format (₹1,23,456.00), financial-year aware date pickers, Excel and PDF export, phone width
without page scroll, dark mode, the dashboard's design system (`DprHeader`, `StatStrip`, `Callout`).

**WhatsApp (v3: API routes in `ALLOWED` + SOP lines, no workflow):** "cash balance?", "bank balance HDFC", "profit
this month", "how much GST this month", "send Malabar their statement", "who owes us / who do we owe" (exists),
"TDS to pay this month". Reads only; posting a manual journal stays on the dashboard.

## 7. Database work (all additive; head is `0529` on 9 Nov; re-check before writing)

`ledger_groups`, `ledgers`, `ledger_links`, `financial_years`, `accounting_periods`, `journal_entries`,
`journal_lines` (CHECK debit xor credit, a deferred constraint or a trigger that the entry balances),
`posting_state` (source kind, id, fingerprint, entry id), `bank_statements`, `bank_statement_lines`,
`bank_matches`, `fixed_assets`, `depreciation_runs`. RLS on every table like 0529. Seeds per company on first use
(the way expense categories seed), never a migration that rewrites existing data. No column added to an existing
money table.

## 8. API work (each used by the dashboard; reads also in v3 `ALLOWED`)

`/accounts/groups`, `/accounts/ledgers` (CRUD, merge, links), `/accounts/years`, `/accounts/periods` (close, reopen),
`/accounts/journals` (list = day book, get, manual create, reverse), `/accounts/post` (run the sweep now; status),
`/accounts/reports/{trial-balance|pl|balance-sheet|cash-flow|project-pl|ledger}`, `/accounts/gst/summary`,
`/accounts/tds/register`, `/accounts/bank/{statements|matches}`, `/accounts/assets`, `/accounts/year-end`,
`/accounts/home`. Tally export switches to the posted journals (one source of truth).

## 9. Backend and frontend files expected

- Backend: new `domains/accounts/` (`chart.py`, `periods.py`, `posting/` with one module per source, `reports/`,
  `gst.py`, `tds.py`, `bank_reco.py`, `assets.py`, `router.py`), repositories under `infrastructure/postgres/
  repositories/accounts*.py`, migrations 0530+; mounted in both apps (the mounting test holds them together);
  `finance/tally.py` reads journals; scheduler hook beside `queue_reminders`.
- Dashboard: `pages/accounts/*` (one per screen above), `components/accounts/*` (voucher grid, ledger picker,
  period picker, report table with drill-down), `lib/accounts.ts`; the module map's Accounts pages turn from planned
  to built one by one.
- Assistant: `agent_api/tools.py` reads + SOP rule; tests in `tests/agent_api/`.
- Docs: this plan, tracker ACC rows, `docs/architecture/accounts-posting.md` (the rule table).

## 10. Build order

| Phase | Items | Why this order |
|---|---|---|
| A. Foundation | ACC-01 chart of accounts + seeds + links · ACC-02 years and periods · ACC-03 journals + balance check · ACC-04 posting engine: expenses, payments, transfers, receipts, RA bills, client receipts, subcontract and hire bills · ACC-05 trial balance + day book + ledger statement | Nothing reports without journals |
| B. Statements | ACC-06 P&L + balance sheet · ACC-07 cash & bank books · ACC-08 project P&L + project position (absorbs CC-20) · ACC-09 Accounts home · ACC-22 company / project / site scope on every report · ACC-23 overhead allocation | What the owner looks at, for the company and each project |
| C. Tax | ACC-10 GST summary + purchase list · ACC-11 TDS registers | Monthly filing support |
| D. Control | ACC-12 manual vouchers · ACC-13 bank reconciliation · ACC-14 period close + changes after close · ACC-15 deliveries-not-billed accrual | What the accountant needs to trust it |
| E. Year end | ACC-16 fixed assets + depreciation · ACC-17 year end + carry forward · ACC-18 cash flow | Once a year |
| F. Out | ACC-19 Tally export from journals · ACC-20 WhatsApp reads · ACC-21 PDF / Excel and party statements on WhatsApp | Uses everything above |

Each item is its own commits, tested, pushed, with its tracker row; the first demo is after Phase B.

## 11. Decisions needed (recommended default in **bold**)

| ID | Question | Default |
|---|---|---|
| D-ACC1 | How journals are made | **A posting sweep from source records (new or changed since posted), on the scheduler and before reports; no write path in other modules changes** |
| D-ACC2 | A record changed after its month is closed | **Old journal kept; the difference posted on the first open day, flagged "changed after close"; nothing on site blocked** |
| D-ACC3 | Books in Mesiri or Tally | **Mesiri keeps the books; the Tally export stays (from the journals) for CAs who file from Tally** |
| D-ACC4 | Wages | **Booked when paid (expenses, advances) until NXT-09 / Payroll decides; no accrual from attendance** |
| D-ACC5 | Deliveries without a bill at month end | **Accrue "Goods received not invoiced", reversed on the 1st of the next month** (matches D-CC3) |
| D-ACC6 | Who can do what | **Owner, admin, finance: view, post manual vouchers, reconcile, close; owner and admin: reopen a period, year end; PM: project P&L of their projects only; a read-only "CA" login later** |
| D-ACC7 | Year and money | **April–March, INR only, GST as recorded on each bill (CGST + SGST when the place of supply is the company's state, IGST otherwise)** |
| D-ACC8 | Chart of accounts | **Tally's primary groups + construction ledgers seeded; the company renames, adds and regroups** |
| D-ACC9 | Depreciation | **WDV at Income-tax rates; SLM (Companies Act) as a company setting** |
| D-ACC11 | Head-office overheads in project P&L | **Optional monthly allocation by cost share (or billing share), off by default; project P&L shows before and after** |
| D-ACC12 | Several companies of one owner | **Separate books per company (as today); a consolidated group view later** |
| D-ACC10 | Module switch | **A new module `accounts` (off by default, V1.1 paid add-on per V1_SCOPE), separate from `finance`, so existing companies see no change until it is switched on** |

## 12. Risks

- **Wrong books destroy trust** (V1_SCOPE's reason to wait). Mitigation: every entry balances by database check;
  trial balance must tie to the supplier ledger, receivables and money account balances (tested on every change);
  first customers run it beside Tally for a month and compare.
- **Double counting** between a delivery accrual and its bill, or a bill and its expense. Mitigation: the same rules
  as the cost read model and supplier ledger (D-CC3, `BILLED_SQL`), one posting function per source, tests per pair.
- **Sources changing under closed months.** Mitigation: D-ACC2 adjustments, listed for the accountant.
- **GST correctness** (rates, place of supply, input not claimable without GSTIN). Mitigation: figures shown with
  their source bills; the CA files; missing GSTINs flagged.
- **Performance** of the sweep for large companies. Mitigation: fingerprint index, incremental by `updated_at`,
  report reads on journal lines with indexes per org / date / ledger.
- **Scope creep** (payroll, inventory valuation, e-invoicing). Out of V1, said in §3.
- **Parallel sessions** touching Finance, Billing, Vendors. Mitigation: Accounts only reads them; pull and re-read
  before each item.

## 13. Testing strategy

- Unit: every posting function with worked examples (the RA-01 bill, a GST-inclusive bill from a GSTIN supplier, a
  subcontract bill with TDS and retention, an advance applied, a transfer); every entry balances; reports from fixed
  journals (TB, P&L, BS tie: assets = liabilities + equity + profit).
- Contract (Postgres, CI money-paths step): post from real records through the real routes; trial balance ties to
  the supplier ledger, receivables and money account balances; period close blocks manual vouchers in it; a change
  after close posts an adjustment; RLS (another company never sees a ledger); roles (engineer, PM 403s).
- Regression: Expenses, Vendors, Billing, Subcontracts, Cost control and Tally suites unchanged.
- Browser: every page at desktop and phone width; keyboard voucher entry.
- Pilot: one customer's month posted in Mesiri against their Tally, line by line.

## 14. Rollback strategy

Additive migrations only, each with a downgrade that refuses while it holds data (as 0528 / 0529). The module is off
by default (D-ACC10): switching it off hides it and stops the sweep; journals are derived, so they can be deleted and
re-posted from the source records at any time. Each ACC item is its own commits; revert per item.

## 15. Labour isolation

Labour, Attendance, Workforce and Payroll are **not changed**. Wages reach the books only as money paid (expenses,
advances, payments) (D-ACC4). An accrual from attendance waits for NXT-09 and its Payroll decision.

## 16. Success criteria

- A pilot company's month: the trial balance ties to every money account balance, the supplier ledger, receivables
  and payables, to the rupee.
- The CA agrees the P&L and GST summary with their Tally within rounding.
- No new typing on site: every journal for that month came from records the site and office already made, except
  the accountant's manual vouchers.
- Month close in under an hour with the checklist; bank reconciliation auto-matches at least 80% of lines.
- The owner answers "profit this month", "cash today" and "who owes us" from the home or WhatsApp in seconds.
