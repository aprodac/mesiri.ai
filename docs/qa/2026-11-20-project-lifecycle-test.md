# Project lifecycle test, production test company (20 Nov 2026)

One new project taken from start to handover on the live site
(`app.whatsapp.mesiri.ai`), in a test company, as the people who would really do each step.
Test records are named `QA-2011 …` so they are easy to find and remove.

## Script

| # | Stage | Role | Pages | What must hold |
|---|---|---|---|---|
| 1 | Company ready | Owner | Settings, Team, Users | Invite PM, site engineer, accountant; each sees only their pages |
| 2 | New project | Owner | Projects → new, Planning › Project start | Project + sites + client + contract value saved; appears in the project picker everywhere |
| 3 | Estimate | PM | BOQ, Planning › Places | BOQ lines with qty/rate; total matches contract; materials per unit |
| 4 | Plan | PM | Schedule, Tasks, Material plan, Documents | Activities linked to BOQ; material plan derived from BOQ |
| 5 | Buy | PM / owner | Requests, Quotations, Purchase orders, Approvals | Request → quote → PO → approved; PO PDF |
| 6 | Receive | Site engineer | Pending deliveries, GRN, Stock | Partial delivery; stock goes up; rate over PO flagged |
| 7 | Daily work | Site engineer | Today, Site log, Labour, Issues, Gallery | Work done on a BOQ line, attendance, an issue raised and resolved, DPR |
| 8 | Subcontract | PM | Subcontract › Work orders, Bills | Work order, measured bill, approval |
| 9 | Spend | Accountant | Expenses, Petty cash, Vendor bills | Expense in a category with a cost centre; vendor bill against PO |
| 10 | Client billing | PM / accountant | RA bills, Variations, Receivables | RA bill from work done; a variation; payment received |
| 11 | Books | Accountant | Accounts (Day book, Ledgers, TB, P&L, GST, TDS, Tally) | Every step above posted once; TB balances; project P&L matches |
| 12 | Control | Owner | Cost control, Cash flow, Home, Approvals | Budget vs actual, margin, cash ahead are consistent with 3–11 |
| 13 | Handover | PM / owner | Project close, final bill, retention | Project can be finished; final figures; nothing left open |

## Problems found

| # | Step | Role | Page | What happened | Expected | Severity | Status |
|---|---|---|---|---|---|---|---|
| 1 | 2 | Owner | Projects → New project | QA-2011 Sunrise Residency created in "cd" (Asia/Kolkata, Green Villa's DPR on) got **UTC, DPR off**: "Day closes 6:00 pm" = 11:30 pm IST, "send by 9 pm" = 2:30 am. Lake View also UTC. Root cause: production serves the assistant app's `/projects` (`apps/whatsapp-assistant/src/projects/router.py`); [259] fixed only the backend router, which production does not mount | Company zone, report as the company has it | High | Fixed (code); existing UTC projects need a data fix (approval) |
| 2 | 2 | Owner | Projects vs Home | Lake View Apartments: "On Track" on Projects & Sites, "Over budget / 69% over" on Home | One status for a project everywhere | Medium | Open |
| 3 | 2 | Owner | Project page | A brand-new project with no data is "On Track" | No status until there is something to judge ("Not started") | Low | Open |
