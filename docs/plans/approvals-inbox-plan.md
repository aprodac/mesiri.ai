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

## Not in this item (later, module 20)

- Pushing a WhatsApp message when something new waits (PRC-25 already tells the office of a new request).
- Comments with @mentions on records; meeting minutes that become tasks; notification settings per person.
- Stock adjustments: there is no approval step for them today.
- Acting from the WhatsApp list in one step (each kind's own tool still does it, with its own confirm).

## Rollback

Revert the commits: no migration, no data. The bell disappears; every module works as before.
