# Each role's home and sidebar (UX-65)

> Asked 18 Nov 2026 in session: "the home dashboard of each role, their sidebar, and them being able to keep a custom
> sidebar which they like and want, in good UI/UX with good visual cues, following the design system".

## Home: "This week" for every role

`components/home/this-week.tsx` was the owner's to-do (UX-61). It is now every role's, made from data the dashboard
already reads (no new API):

| Who | Lines |
|---|---|
| Everyone | What waits on them to decide (`GET /approvals/waiting`), one line per kind: site reports, material requests, subcontractor bills, RA bills in draft, wage weeks, labour on the BOQ, stock counts. Tasks keep their own card. |
| Owner / admin | Work done not billed, clients to chase, projects heading over budget, late work, materials to order, suppliers overdue, late deliveries |
| Project manager | Late work, materials to order, work lines in the red this week, late deliveries |
| Site engineer | Deliveries late or due today, their requests past the date needed |
| Finance | Suppliers overdue, delivered not billed, clients to chase, the books' checks (accounts home `attention`), the last month still open |

Worst first (red, amber, blue edge), six shown, "Show all". A project picked in the top bar narrows it.

## Today's look (UX-66)

Asked the same day: "the Today page looks so boring". A dark day card was tried and rejected ("I hate it"); the
look picked from three light ones (A): the greeting and the day on the page, the day's moves beside it, then five
figure cards (sites reported with a bar and the time left to the cutoff; workers, work done, photos, open issues with
their own icon colours) and what the day still needs as chips (`components/home/today-hero.tsx`). Then two columns: This week, tasks and the sites as cards on the left;
the role's figures, time saved and open issues on the right (one column on a phone). Same data, same tour markers.

## Home and Today, separated (UX-68)

Asked: "is Today supposed to be the home page?" No: Today was doing two jobs. Now:

- **Home** (`/home`, first in the sidebar, where people land): the greeting, the role's figures first, This week,
  "Your projects" (owners and project managers: one line each with budget state, % done, late activities, sites
  reported today, people on site, open issues, report sent; it opens that project's Today), tasks, suppliers and bills
  waiting, time saved, getting started.
- **Today** (`/today`): the site's day only: the day's figures, the site cards, the daily report, open issues, other
  days.
- **Landing:** everyone opens Home; a site engineer opens Today (their job is the day's report). Unknown addresses go
  to the same place.

## Sidebar: "Your pages" and Customise

- **Your pages** sits under the everyday pages. Each role starts with its own (`lib/sidebar-prefs.ts` `ROLE_PINS`):
  owner: Approvals, Cost overview, Cash flow, Receivables, RA bills, Variations; project manager: Approvals, Material
  requests, Pending deliveries, Green / red, Schedule, Subcontract bills; site engineer: Material requests, Stock,
  Attendance, Pending deliveries, Site log; finance: Expenses, Suppliers, Receivables, Cash & bank book, Cash flow, GST.
- **Pin from anywhere:** the pin on any row (mouse over it), on a drawer's page, or beside the page name in the top
  bar. A pinned page shows a small pin in its drawer; a new pin flashes in Your pages. 12 at most.
- **Customise** (the sliders on "Your pages", or "Customise" at the bottom): Pages (drag or arrows, unpin, add by
  search) and Sections (drag or arrows, show or hide; hidden sections stay in search). "Back to the <role> sidebar"
  forgets the changes. Every change shows at once and is saved behind it.
- **Saved on the account** (follows the person to any device): `users.sidebar` (migration 0562, additive, nullable;
  NULL = the role's default), `PUT /me/sidebar`, `DELETE /me/sidebar`, `sidebar` in `GET /me/preferences`. Self only,
  like the start mode. It only changes what the sidebar shows: a pinned page the role may not open is never shown, and
  every page stays reachable.

## Tests

- `backend/tests/unit/test_sidebar_prefs_ux65.py`: input rules (pages and known sections only, no duplicates, the cap),
  cleaning a stored value, self-only read and write, reset, 404.
- Against the real API on a local Postgres 16 (0562 up, down, up): save, read back, a bad link refused, reset; the
  four roles' Today and sidebar at 1440 (light, dark) and 390; pin from a row, a drawer and the top bar, drag, hide a
  section, reload (kept), reset.

## Rollback

Revert the commit. The migration's downgrade drops `users.sidebar` (people go back to their role's sidebar).
