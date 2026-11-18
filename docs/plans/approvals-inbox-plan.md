# Approvals inbox and the bell (NXT-08)

> Module 20 (Communication & Notifications) of the capability framework, first in Adarsh's build order
> ([gap analysis](capability-framework-gap-analysis.md)), merged with tracker NXT-08. Approved in session by Ilan,
> 9 Nov 2026 (the bell goes in the top bar, a shared component; WhatsApp read only).

## What it is

One "waiting for you" list: a bell in the top bar with a count, a panel grouped by kind, urgent first then oldest,
each row opening the record where it is decided. On WhatsApp, "what is waiting for me?" / "enikku enthokke pending"
answers from the same API (tool `waiting`).

| Kind | Waiting when | For whom (the module's own rule) | Urgent when | Opens |
| --- | --- | --- | --- | --- |
| `site_report` | a site day (today, yesterday) has entries to confirm | anyone who reaches the site (BE-42) | it is yesterday's | `/reports/:date/sites/:id` |
| `material_request` | status `waiting` | `may_act_on_material_requests` (admin, owner, PM) | its urgency is `late` | `/materials/requests?id=` |
| `subcontract_bill` | check `waiting` or `flagged` | `may_view_expenses` (the approve route's rule) | flagged | the work order's bills |
| `ra_bill` | status `draft` | `may_manage_money` | made 7+ days ago | `/billing/ra-bills?bill=` |
| `task` | mine, live, due today or before (tasks module) | the assignee | overdue | `/tasks?id=` |
| `wage_sheet` | a past week in draft, or approved with money due | `may_view_expenses` | approved, pay day passed | `/labour/wages?week=` |
| `labour_split` | BOQ-02c: last 7 days' labour put on lines by Mesiri, or on none | `may_view_expenses` | never | the Budget page |
| `stock_count` | UX-62: open, something counted | the count's `may_approve` (admin, owner) | open 3+ days | `/materials/counts?id=` |

## How

- `backend/src/mesiri/domains/approvals/` (`inbox.py`, `router.py`): `GET /approvals/waiting` (`kind`, `limit`).
  No table. **Each source calls its module's own list route as the caller** (`list_site_days`, `list_requests`,
  `bills_waiting`, `list_ra_bills`, `list_tasks`), so project and site access, role rules and filters are the
  module's, never a copy. Module switches: a source of a switched-off module is not asked.
- A source that fails is named in `unavailable` (the panel says "could not check …") and never hides the others
  (each runs in a savepoint); a 403 / 404 means "not yours" and is left out quietly.
- Wording ("8 Nov", "900 kg", "Was due 7 Nov") is made in the backend, so the bell and WhatsApp say the same.
- Web: `components/inbox-bell.tsx` (top bar, polls every minute), `lib/approvals.ts`; record links are lines in
  `lib/links.ts` (`recordUrl.siteReport/task/raBill/workOrderBills`).
- WhatsApp v3: `waiting` on `ALLOWED` (added with `scripts/allow_route.py`), one SOP line (not `my_requests`);
  mounted in `runtime/lifecycle.py` and `agent_api/app.py`.

## The Approvals page (UX-62, 18 Nov 2026)

`/site/approvals` (`pages/ApprovalsPage.tsx`) is the bell's list as a page: kind tiles (`KIND_LOOK` in
`lib/approvals.ts`: one colour and icon per kind), project filter, Urgent only, rows grouped Urgent / Today / Waiting
longer. The simple decisions are taken on the row **with each module's own route and dialog**, never a copy:

| Kind | On the row | Route |
| --- | --- | --- |
| `subcontract_bill` | Approve / Reject (the module's `DecideDialog`: flags shown, a reason required) | `POST /subcontracts/bills/{id}/approve\|reject` |
| `wage_sheet` (draft) | Approve; an approved week shows Pay, which opens Wages (it needs the account to pay from) | `POST /labour/wage-sheets/{id}/approve` |
| `task` | Done | `POST /tasks/{id}/status` |
| `material_request` | Decide: Requests' own `RequestDetail` in a side panel (order, quotes, send from a site, no with a reason) | `POST /procurement/requests/{id}/decide`, orders |
| the rest | Confirm / Check / Review: open the record | — |

Never in bulk: one tap, one row. After any decision the list is read again, so a row someone else decided goes.
New approval rules (an expense above a limit needing a PM, orders above a value needing the owner) do not exist yet:
a product decision for Ilan.

## Not in this item (later, module 20)

- Pushing a WhatsApp message when something new waits (PRC-25 already tells the office of a new request).
- Comments with @mentions on records; meeting minutes that become tasks; notification settings per person.
- Acting from the WhatsApp list in one step (each kind's own tool still does it, with its own confirm).

## Rollback

Revert the commits: no migration, no data. The bell disappears; every module works as before.
