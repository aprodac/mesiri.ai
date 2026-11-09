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

## Not built yet

GST
and TDS registers (ACC-10, 11), manual vouchers (ACC-12), bank reconciliation (ACC-13), the close checklist
(ACC-14's rest), the delivery accrual (ACC-15), year end (ACC-16..18), Tally from the journals (ACC-19), WhatsApp
reads (ACC-20). The sweep runs before each read, not yet on the scheduler.
