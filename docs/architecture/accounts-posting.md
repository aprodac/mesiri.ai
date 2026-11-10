# Accounts: how the books are posted (ACC-01..05, 9 Nov 2026)

The company's double-entry books are **posted from the records the site and office already make**. Nobody types a
journal for something Mesiri already knows. Plan: [accounts-plan.md](../plans/accounts-plan.md). Code:
`backend/src/mesiri/domains/accounts/`.

## The pieces

| Piece | File | What it does |
|---|---|---|
| Chart | `chart.py` | Tally's primary groups and the construction ledgers, seeded per company on first use (`code` keeps them findable however renamed); linked ledgers (supplier, client, money account, expense category, staff) made by the sweep and named after their record |
| Rules | `posting.py` | Pure: one function per source kind, record in, balanced entries out. Ledgers by reference (`("code", "input_gst")`, `("link", "vendor", id)`) |
| Sweep | `sweep.py` | Reads every source, works out each one's entries and fingerprint, writes only what changed; per-company advisory lock; closed months untouched |
| Months | `periods.py` | Financial year April–March; months open or closed; the first open day after closed months |
| Reports | `reports.py` | Trial balance (company / project / site), day book, ledger statement, ledger balances, checks against the modules |
| Excel | `export.py` | Trial balance, ledger statement, day book |
| API | `router.py` | `/accounts/*`, behind the `accounts` module (off by default), money roles |

Tables (migration 0531): `ledger_groups`, `ledgers`, `accounting_periods`, `journal_entries`, `journal_lines`. A
deferred constraint trigger refuses any entry whose debits and credits differ, at commit. Every line carries its
project, site and cost centre.

## The rule table

| Source | Voucher | Debit | Credit |
|---|---|---|---|
| Confirmed expense with a supplier | Purchase | its category (amount less claimable GST, D-CC8) + Input GST | the supplier |
| … paid from a staff member's own pocket (`reimbursable` / `reimbursed`) | Journal | same | "<name> (own pocket)" |
| … with no supplier | Journal | same | Expenses payable |
| Money movement `expense_payment` (a bill payment, an on-account payment) | Payment | who the expense is owed to (above), or the supplier for on account | the account |
| … from the TDS payable account (TDS deducted on a subcontract bill) | Journal | the subcontractor | TDS payable (194C) |
| `transfer` | Contra | the receiving account | the paying account |
| `fund_received` from a client receipt | Receipt | the account | the client, or Mobilisation advance received |
| `fund_received`, nothing behind it | Receipt | the account | Funds introduced |
| `adjustment` | Journal | the account or Money balance adjustments | the other |
| `reversal` | as the original, sides swapped, on the reversal's day |
| RA bill submitted or certified | Sales | client net, TDS receivable, Retention receivable, Mobilisation advance received (recovery) | Contract revenue (gross), Output GST |
| Money account opening balance | Journal | the account | Opening balance difference |
| Supplier opening balance | Journal | Opening balance difference | the supplier |
| Manual voucher (ACC-12), posted | Journal | as typed | as typed (never a bank or cash ledger) |
| Bank line booked (ACC-13): a money movement `adjustment`, `source_type` `bank_statement_line` | Journal | the account, or the ledger chosen (Bank charges ...) | the other |
| Deliveries not billed at a month's end (ACC-15) | Journal, on the last day; reversed the next day | Materials received, bill awaited | Goods received not invoiced |
| Fixed asset (ACC-16): cost from a bill | Journal, on the bill's date | the class ledger (Plant & machinery ...) | the bill's expense category |
| … owned before the books | Journal, on `books_from` | the class ledger (cost less written off before) | Opening balance difference |
| … depreciation of a finished year (or of the year it was sold, on the sale day) | Journal | Depreciation | the class ledger |
| … sold or scrapped | Journal | Assets sold, money to receive (what it fetched), Loss or gain on assets sold | the class ledger (book value) |

**Bank and cash come from `money_transactions`**, the rows Finance › Money adds up, so an account's balance in the
books is its balance in Finance by construction. An applied advance (an on-account payment used on a bill) moves no
money and posts nothing: the supplier's balance already holds it. A subcontract bill is its expense (gross) plus its
TDS payment; its retention stays in what is owed (the supplier ledger's terms). A hire bill is in the books through
its expense. A supplier's records dated before their opening date post to Opening balance difference, because the
opening balance stands for them.

## Re-posting and closed months (D-ACC2)

Each source's entries carry a fingerprint (the rules' version + every line). When it differs, the sweep re-posts:

- entries in **open** months are rewritten in place, keeping their voucher number when the type and year are the same;
- entries in **closed** months are never changed. What the record should post into closed months, less what they
  hold, is posted as one `after_close` journal on the first open day after them (`periods.first_open_day`).

A record removed after close gets its whole closed entry reversed the same way. The sweep posts the oldest first, so
a first posting numbers vouchers in date order.

## Checks

`GET /accounts/checks` compares each money account (books vs opening + movements), each supplier (books vs the
supplier ledger's bills and payments; deliveries not billed wait for the month-end accrual, ACC-15) and each client
(books vs Receivables). A difference is shown, never hidden: typically a payment row saved without its money
movement (older data), which the books do not count because no money left an account.

## Phase B: statements (`statements.py`)

All read from the journal lines. **P&L**: top groups map to Tally's layout (`PL_SECTION`): Sales / Direct income less
Purchases / Direct expenses is the gross profit; plus Indirect income less Indirect expenses, the net profit; custom
groups follow their top group. **Balance sheet**: balances on a day; P&L ledgers fold into capital as "this year"
(since 1 April) and "earlier years". **Cash and bank**: linked money-account ledgers held as assets (the TDS payable
account is a liability and stays out). **Project position**: the project's own lines (client and supplier balances,
retention / TDS receivable, advances, receipts and payments for it). **Home**: those, plus GST of the month and TDS
to deposit.

**Overheads (ACC-23)**: a second posting pass, after every other source, builds one `overhead` entry per finished
month: the head-office project's expense lines plus expense lines with no project, shared over the other projects by
their cost or billing that month, on the ledger "Head office overheads allocated" (Dr each project, Cr the head
office): nil company-wide. Settings in `accounting_settings` (migration 0532); off removes the entries (closed months
through the after-close rule).

Who: the company's statements are the money roles'; `/accounts/projects`, `/accounts/projects/{id}`, a project's
`/accounts/pl` and `/accounts/home?project_id` are also its project manager's (D-ACC6).

## Phase C: GST and TDS (`tax.py`)

GST is read from the records (they carry the GSTIN and rate) and tied to the Output / Input GST ledgers. Claimable
input follows D-CC8 (supplier GSTIN and GST said as included), the same rule as posting; the rest is "credit missed"
with its reason. Place of supply: the company's GSTIN (letterhead, `branding.gstin`) against the other party's first
two digits: same state CGST + SGST, else IGST, unknown without both. TDS deducted is the payments from the TDS payable
money account; deposits are transfers into it, applied oldest month first; due on the 7th (March: 30 April).

## Phases D to F (10 Nov 2026): every new entry is a record

The rule that kept Phases A to C honest holds for the rest: **nothing writes a journal directly**. Each new kind of
entry is a source record the sweep posts like an expense, so a closed month is never changed (D-ACC2), the books can be
deleted and re-posted from the records (the rollback), and bank and cash keep tying to Finance › Money.

| Item | Record (migration 0544) | Code | Notes |
|---|---|---|---|
| ACC-12 manual vouchers | `account_vouchers`, `account_voucher_lines` | `vouchers.py` | Balanced to the paisa, two lines at least, one side per line. **Never a bank or cash ledger** (a transfer is a movement in Finance; it posts as a contra). Not in a closed month (409). Cancel keeps it, with who and why; after close the difference posts on the first open day. Ledgers by id (`posting.ledger_id`); the sweep nets after-close differences by ledger id. |
| ACC-13 bank reconciliation | `bank_statements`, `bank_statement_lines`, `bank_bookings` | `bank.py` | Excel / CSV read by its header words (HDFC, SBI, ICICI layouts tested); the columns remembered per account; a line imported twice skipped (`dedupe_key`). Auto-match: same amount and direction, ±3 days, one clear candidate (the UTR breaks a tie, then the nearer date; a true tie waits for a tap); a movement undone in Finance and its reversal are never offered. **Booking** a bank-only line records a money movement through Finance's own repository (`adjustment`); `bank_bookings` keeps the ledger with the movement (its id is the movement's `source_id`), so undo (a Finance reversal) and booking again never relabel what was posted. The reconciliation: books − paid not in the bank + received not in the bank + bank-only lines = what the statement should show; the difference is said. |
| ACC-15 delivery accrual | none (read from `material_receipts`) | `sweep.accrual_sources` | Each finished month: priced deliveries received by its last day whose bill (a confirmed expense on their invoice) was not dated by then, by project and site, the supplier ledger's filters. A later bill does not change a closed month's accrual: "billed by then" is read from the bill's date. Reversed on the 1st. GST on a delivery is accrued as recorded; the bill settles the claim. |
| ACC-16 fixed assets | `fixed_assets`; `accounting_settings.depreciation_method` | `assets.py`, `depreciation.py`, `posting.asset_entries` | WDV at Income-tax rates by default (half rate under 180 days in the first year; nothing in the year of sale), or SLM by days in use, never below salvage. A year is posted once it is over (31 March), the year of sale on the sale day. Class defaults in `chart.ASSET_CLASSES` (rates and lives to be checked by the CA). |
| ACC-17 year end | `accounting_years` (snapshot) | `years.py` | Owner or admin, once 31 March is past. Closes every month and locks them (a month of a closed year cannot be reopened until the year is). Carry forward is Tally's: no closing journal; P&L ledgers restart at nil, the profit joins capital (the statements already read it so). Checklist: only "the year is not over" blocks; the rest are warnings acknowledged on closing. A closed year's snapshot is compared with its balances (drift: always nil unless something bypassed the sweep). |
| ACC-18 cash flow | none | `statements.cash_flow` | Direct method from the cash and bank lines; each entry's cash shared over its other lines by amount; heads in `CASH_HEADS` (clients, suppliers, labour, staff, taxes, other; assets; capital, loans; own accounts and opening balances under Other). Opening + net = Cash & bank's closing, checked (`agrees`). |
| ACC-19 Tally from the books | none | `tally_books.py`, `finance/tally_router.py` | With Accounts on, Finance › Tally export is the posted journals (every voucher type), masters with Tally's own group names, custom groups as GROUP masters parents first, `REMOTEID` the journal's id (kept on re-post). Without Accounts, NXT-12's export is unchanged. |
| ACC-20 WhatsApp | none | `agent_api/tools.py` (`books_home`, `profit_and_loss`, `cash_bank_book`, `cash_flow`, `gst_summary`, `tds_register`), SOP rule 27 | Reads only; the API refuses other roles and companies without Accounts. |
| ACC-21 files | none | `export.py` (`Doc` → `render`: Excel or PDF) | One description per report, two writers. Every report route has `/export?format=xlsx|pdf`; a supplier's or client's statement has "Send on WhatsApp" (the person's own WhatsApp, with the PDF). |

## Not built yet

The close checklist (ACC-14's rest, another session). The sweep runs before each read, not yet on the scheduler.
Vouchers of other types (payment, receipt) stay records of their modules: Finance, Billing, Subcontracts.
