# The control panel's Overview (SA-18)

> Built 27 Oct 2026. Tracker: SA-18. Code: `application/organizations/platform_overview.py`
> (rules), `infrastructure/postgres/repositories/platform_activity.py` (counts),
> `domains/admin/overview_router.py` (`GET /admin/overview`), control panel `Overview.tsx`.

The super admin's morning screen. It answers four questions, in this order, and every
number opens the screen where the admin acts on it.

1. **Is anything broken right now?** Message worker (from `/admin/queue/health`; Redis,
   so only the assistant app can answer), typical reply time in the last hour, failed
   messages in the last 24 h, messages still waiting for a reply.
2. **What needs me today?** The "needs attention" list, most urgent first.
3. **How is the business doing?** Today (messages, DPRs sent of due, companies and people
   reporting, cost), companies by status, new trials, conversions, companies active this
   week, 7-day cost, 14 days of activity, the onboarding funnel.
4. **Who needs a nudge?** Most active companies this week, and companies gone quiet.

## Needs attention: the rules

| Item | Severity | Rule | Opens |
| --- | --- | --- | --- |
| Messages failed | critical | `processing_status = 'failed'`, last 24 h | Logs, `?status=failed` |
| Messages with no reply | critical | still `pending` 10+ min after arriving (last 24 h); a photo held for "what is this for?" counts | Logs, `?status=pending` |
| DPRs late today | critical | auto-DPR project in an operational company, past its own send deadline + 30 min in its own timezone, not sent for its local date (the DPR sender's rule) | the company |
| Message worker down | critical | `/admin/queue/health`: queue on, worker not alive (added by the page) | Queue Health |
| Want to continue with Mesiri | warning | open `continue_requests` (SA-10) | the company |
| Trials ending soon | warning | on trial, 3 days or less left | the company |
| Trials with no site update yet | warning | on trial 3+ days, no first update | the company |
| Stuck in setup | info | trial or active, created 2+ days ago, no site or no site reporter | the company |
| Letterhead requests | info | open branding requests (SA-09) | Branding requests |
| Expired trials to clean up | info | `eligible_for_deletion` (SA-10); nothing is deleted on its own | Companies |

Company status, trial days and setup progress all come from `list_companies` (SA-02), so
the Overview and the Companies page can't disagree.

## Other definitions

- **Days** are Indian calendar days. "Today" for a DPR is the project's own local date.
- **Gone quiet:** a trial or active company with no message for 3+ days (or never, if it
  was created 3+ days ago). Expired and suspended companies are not "quiet", they're over.
- **Onboarding funnel:** companies whose trial started in the last 30 days, and how many
  have a site, a site reporter, a first update, a first DPR, and are paying. The step that
  loses the most companies is flagged.
- **Reply time** is the Reply Insights number (SA-17): received → processed.

Read-only, platform admin only, no migration. The page refreshes every minute while
"Live" is on.
