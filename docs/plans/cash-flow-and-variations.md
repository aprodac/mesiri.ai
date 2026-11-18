# Cash flow ahead and variations (MP-06, NXT-04, CC-24)

> Asked 18 Nov 2026 in session: "Cash flow for the coming weeks, extra work the client asked for (variations): let's
> build these two properly in good UI/UX, if they're not there." Neither existed (both planned in the page map).
> Built in one change: backend, migration 0561 (additive), two pages, tests.

## Cash flow ahead: `/accounts/cash-flow`

**Question it answers:** "Will I have the money to pay what is due in the coming weeks, and which week runs short?"

**Where the figures come from:** no table of its own. Every expected payment is read from what the modules already
keep, with the module's own working (`backend/src/mesiri/domains/accounts/cashflow.py`):

| Kind | From | Expected on |
|---|---|---|
| Client bills (in) | RA bills sent and not paid (`billing/receivables.settle`) | bill date + "clients pay in" (30 days by default; a setting on the page) |
| Work not billed (in, off by default) | measured work on no bill (`billing/bills.unbilled_lines`) | today + client days, if billed now |
| Supplier bills (out) | supplier and subcontractor bills not paid (`vendors/ledger`, a subcontract bill only once checked, never its retention) | bill date + the supplier's credit days (30 when none: marked ≈) |
| Delivered, not billed (out) | deliveries the supplier has not billed (`vendors/ledger`) | delivery date + credit days |
| Orders to come (out) | what is left on open purchase orders at their rates (`procurement/orders.describe`) | expected date (a week out when none) + credit days |
| Wages owed (out) | wage sheets with something left to pay | the week after the sheet ends |
| Wages ahead (out, estimate) | the last four weeks' wage sheets, a week | each coming week with no sheet yet |

Money already paid to a supplier on account pays their earliest bills first, so it is not counted twice. Anything due
before today is counted this week and marked overdue. The weeks start on Monday; the first one is "this week".
Opening cash is every cash box and bank account today (`money_accounts` balances). With one project picked, there is
no opening cash: a bank account is the company's, so the page shows the project's own money in and out.

**Who:** owner, admin, finance (`may_manage_money`), behind the Accounts module switch, the same as Cash & bank. This was
the open decision D-MP3; the request to build it settled it.

**The page:** four figures (cash today, coming in, going out, the lowest point and its week); one to-do: the week the
cash runs short (or, when it doesn't, client money past its day); one chart (in up in green, out down in red, the cash
at each week's end as a line, one rupee axis, hover for the week); the kinds as switches (off moves the balance at
once, no reload); the weeks as rows that open into every payment with a link to its page. Weeks (8, 12, 26), client
days, supplier days, the kinds and the opened week are all in the address. Export of every payment counted.

**Not yet:** spend that is planned on the BOQ but not ordered (MP-06's "plan × rates"); payment terms stored on the
contract (today a page setting); the past period's cash flow statement for the CA (ACC-18); a WhatsApp answer.

## Variations: `/billing/variations`

**Question it answers:** "What extra work did the client ask for, is it priced and approved before we build it, and
has it been billed?"

**Data:** `variations` (migration 0561, row-level security like 0522): numbered per project (VO-01...), `new` (work not
in the BOQ) or `more` (more of a BOQ line), quantity × client rate (amount), our cost (margin), days added, who asked
and when; draft → sent → approved / rejected; cancel before a decision; a draft can be removed.

**Approval changes the BOQ through its own repository** (`domains/billing/variations.py` `_apply_to_boq`):

- `new` → a line in the project's "Variations" section (made the first time), code VO-xx, at the client rate;
- `more` → a revision of the line with its planned quantity raised; the revision's reason is "VO-xx approved by the
  client", so the BOQ's own history says why it grew (CC-24).

From then on the site's work on it is measured and billed on RA bills like any line (`bills.unbilled_lines`): there is
no second way to bill. The page shows, for an approved new item, the work measured on its line and what RA bills took.

**Who:** owner, admin, finance (the people who see client bills).

**The page** (list kit): four figures (with the client, approved, billed of approved with the rest to bill, rejected);
one to-do (with the client 14+ days, else drafts not sent); the state bar with search, sort, export; rows with the
VO, the kind, the price, a margin pill (green 15%+, amber under, red at a loss, grey when our cost is not priced), a
billed bar, the state and days waiting; a panel with the price, its story (asked, sent, decided, on the BOQ, billed),
links to the BOQ and RA bills, and its actions (sent, approved, rejected with who and when, edit, cancel, remove).
New / edit: kind as two tiles, the BOQ line picker with its rate, the amount and margin worked out as it is typed.

**Not yet:** omissions (work taken out of the contract); a client-facing variation document (PDF to sign); WhatsApp
("the client wants a balcony"); approval by the client from the Client view link.

## Tests

- `backend/tests/unit/test_cashflow.py`: the week maths (Monday weeks, overdue, the docstring's worked example, the
  first short week, work not billed only when asked, no opening with a project, advances, the wage estimate).
- `backend/tests/contract/test_variations_cashflow_contract.py` (live Postgres): a new item sent, approved, put on the
  BOQ, measured, billed on an RA bill and shown billed; more of a line as a revision with its reason; the rules on
  states, input and roles; the cash flow from an RA bill, work not billed, suppliers with and without credit days,
  slower clients, one project without the bank, and a project manager refused.
- Both pages clicked through against the real API on a local database (a seeded company), 1440 and 390, light and dark.

## Rollback

Revert the commits. The migration's downgrade drops `variations` only while it is empty; with variations recorded,
keep the table (the pages and routes go with the revert; BOQ lines made by approvals stay as ordinary BOQ lines).
