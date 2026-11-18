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

Asked the same day: "the Today page looks so boring". A dark day card on top (`components/home/today-hero.tsx`):
greeting and day, a ring of sites reported, the time left to the cutoff, the day's four figures, what the day still
needs as chips, Tell Mesiri / Live / day moves. Then two columns: This week, tasks and the sites as cards on the left;
the role's figures, time saved and open issues on the right (one column on a phone). Same data, same tour markers.

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
