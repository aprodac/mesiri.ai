# 09 · Dashboard — V1 audit

10 problems found in the Dashboard; the biggest is that the menu is not the V1 menu:
Attendance and Materials are hidden inside "More", and "More" still lists about 25 old
pages, empty ones included, for every role.

- **Audited:** 24 Oct 2026, `main` at `373d70a4` · **Original sheet:** [Dashboard — test sheet](https://claude.ai/artifact/N87zhBa5VB8YFaC555Pbp1)
- **Not verified:** a real browser session against live data.
- **Not repeated here** (logged in other modules): absent workers and "0 helpers" counted (ATT-01, ATT-03), later-day work missing (WRK-01), open-issue count vs DPR and engineer questions listed as issues (ISS-04, ISS-06), new project with no automatic DPR (DPR-01).

## V1 menu (scope) vs today

| V1 scope item | Who | Today |
| --- | --- | --- |
| Today | Everyone | Top menu |
| Daily Reports | Everyone | Top menu |
| Issues | Everyone | Top menu |
| Attendance | Everyone | **More → Labour & Workforce → Attendance** |
| Materials | Everyone | **More → Materials → Overview** |
| Projects & Sites | Admin | Setup (Admin only) |
| Team | Admin | Setup (Admin only) |
| Company & Branding | Admin | Setup → Company (Admin only) |

## Summary

| ID | Problem | Severity | Approval | Verified |
| --- | --- | --- | --- | --- |
| DSH-01 | Menu isn't the V1 menu; old and empty pages under "More" for every role | Serious | None (Workers Roster hiding is in the approved scope list) | Code read |
| DSH-02 | Report details / confirm / publish / revise check only the company, not the project | Serious | Alan: security | Code read |
| DSH-03 | Time zone is free text; "IST" or "India" quietly means UTC | Serious | None — **fixed (WEB-18), retest** | Scripted run |
| DSH-04 | Today says a site "hasn't reported" when it sent materials, issues or progress | Serious | None — **fixed (WEB-19), retest** | Code read |
| DSH-05 | Attendance page is about wages (₹0), not counts | Other | Alan: Labour | Code read |
| DSH-06 | "Development only" delete button on every attendance row | Other | Alan: Labour | Code read |
| DSH-07 | WhatsApp Inbox listed for everyone; admin-only on the server | Other | None | Code read |
| DSH-08 | Team offers a "Finance / Accountant" role | Other | None | Code read |
| DSH-09 | Daily Reports CSV has an always-0 "Labour cost" column | Other | None | Code read |
| DSH-10 | Today's open-issue list loads only the latest 100 issues | Other | None | Code read |

## Before you test

Three logins in three browsers or private windows:

- Admin (the Owner)
- Project Manager, on Project A only
- Site Engineer, on Project A's Site 1 only
- Project B exists with its own site (a project the engineer is not on)
- Earlier today on WhatsApp for Site 1: `20 bags cement came` → Save, `Crane breakdown` → Save. No new work, no labour.

For each login check the left menu (and inside "More"), and whether Today, Daily Reports,
Issues, Attendance and Materials match what was sent on WhatsApp.

## Problems

### DSH-01 · The menu isn't the V1 menu

- **Severity:** Serious · **Approval:** None (hiding Workers Roster is already on the approved V1 change list)
- **Repro:** log in as the Site Engineer; open "More".
- **Actual:** no Attendance or Materials at the top. "More" lists WhatsApp Inbox; Operations (Dashboard, Activities, Timeline, Gallery, Analytics, Settings); Labour (Overview, Attendance, Workers Roster, Analytics, WhatsApp Automations, Reports, Settings); Materials (Overview, Inventory, Purchases, Suppliers, Categories). Inventory/Purchases/Suppliers/Categories open an empty placeholder page.
- **Code:** `PRIMARY_ITEMS`, `ROOT_MANAGEMENT_ITEMS`, `MORE_CATEGORIES` in `apps/dashboard/src/components/app-sidebar.tsx`; placeholder routes in `apps/dashboard/src/App.tsx` (`OperationalPlaceholder`).
- **Fix direction:** add Attendance (`/labour/attendance`) and Materials (`/materials`) to `PRIMARY_ITEMS`; drop "More" for non-admins, or hide it behind a company flag (routes stay, per the scope's "nothing is deleted").

### DSH-02 · Report actions check only the company

- **Severity:** Serious · **Approval:** Alan: security
- **Repro (needs the Mesiri team):** with the Site Engineer's login (Project A), call confirm on a Project B daily-report ID.
- **Expected:** 404, as `GET /dpr/daily-reports/{id}/versions` already does.
- **Actual (code):** the server would answer "success" and Project B's day becomes Confirmed.
- **Code:** in `backend/src/mesiri/domains/dpr/router.py`, `get_daily_report_detail`, `submit_daily_report_for_review`, `approve_daily_report`, `publish_daily_report` and `revise_daily_report` scope by `organization_id` only; `list_daily_report_versions` adds `_site_denied(…)`; `confirm_fact` / `reject_fact` use `_fact_in_scope`.
- **Fix direction:** the same `get_report_scope` + `_site_denied` check on all five routes.

### DSH-03 · Time zone is free text; a wrong word means UTC

- **Severity:** Serious · **Approval:** None
- **Repro:** Projects & Sites → a project → Reporting. Type `IST`, keep cutoff 18:00, Save.
- **Actual:** saved with no warning; the evening check comes at 11:30 PM, not 6 PM.
- **Code:** text input in `apps/dashboard/src/components/project-reporting-tab.tsx` (placeholder "e.g. UTC, Asia/Kolkata", state defaults to `'UTC'`); the API doesn't validate it; `local_now` in `backend/src/mesiri/application/automations/scheduling.py` silently falls back to UTC.
- **Evidence (scripted run):** 13:00 UTC → `Asia/Kolkata 18:30 IST`, `Asia/Calcutta 18:30 IST`, `IST 13:00 UTC`, `India 13:00 UTC`, `UTC+5:30 13:00 UTC`.
- **Fix direction:** a select of IANA zones (India first); reject unknown zones in `ProjectCreate` / `ProjectUpdate`.
- **Fixed (WEB-18):** picker on both forms; the API stores IST/India as Asia/Kolkata and refuses other unknown names. Existing bad values are not rewritten.

### DSH-04 · Today says a site "hasn't reported"

- **Severity:** Serious · **Approval:** None
- **Repro:** the setup messages (cement + crane breakdown only).
- **Actual:** Today shows Site 1 "Nothing received today" and "Site 1 hasn't reported today".
- **Code:** `hasUpdates` in `apps/dashboard/src/lib/site-day.ts` is `work_items > 0 || workers > 0 || site_working === 'none'`; `list_site_days` (`dpr.py`) counts only activities created that day (WRK-01).
- **Fix direction:** return materials, issues, photos and progress-update counts from `list_site_days` and count them in `hasUpdates`.
- **Fixed (WEB-19, with WA-65 for progress updates).** Retest.

### DSH-05 · Attendance page is about wages

- **Severity:** Other · **Approval:** Alan: Labour
- **Repro:** More → Labour & Workforce → Attendance.
- **Actual:** "Labour Cost in Range" ₹0, "Excludes … man-days with no wage recorded", a "Total Daily Cost" column of ₹0. The V1 scope asks for headcount by contractor and trade per site per day.
- **Code:** `apps/dashboard/src/pages/AttendancePage.tsx` (KPI cards, cost column, CSV header "Total Daily Cost (INR)").

### DSH-06 · "Development only" delete button

- **Severity:** Other · **Approval:** Alan: Labour
- **Repro:** Attendance → click the bin on any row.
- **Actual:** tooltip "Delete this attendance report (development only)"; the click fails (the server allows it only with a dev flag and ADMIN).
- **Code:** unconditional `{(` block around the delete `TableCell` in `AttendancePage.tsx`; server gate `_assert_may_delete_labour` in `backend/src/mesiri/domains/workforce/router.py`.

### DSH-07 · WhatsApp Inbox listed for everyone

- **Severity:** Other · **Approval:** None
- **Repro:** Site Engineer → More → WhatsApp Inbox.
- **Actual:** an error or an empty page: the `/whatsapp/messages` route uses `require_admin`.
- **Code:** `renderLink({ title: 'WhatsApp Inbox', … })` in `app-sidebar.tsx`; `list_messages` in `backend/src/mesiri/domains/organizations/router.py`.

### DSH-08 · Team offers a "Finance / Accountant" role

- **Severity:** Other · **Approval:** None
- **Repro:** Team → add a person → Role list.
- **Actual:** "Finance / Accountant" is offered though Finance is off in V1.
- **Code:** `apps/dashboard/src/components/project-dialogs.tsx` (role `SelectItem`s), filter in `apps/dashboard/src/pages/Users.tsx`.

### DSH-09 · Daily Reports CSV has a "Labour cost" column

- **Severity:** Other · **Approval:** None
- **Repro:** Daily Reports → Export.
- **Actual:** a "Labour cost" column full of 0.
- **Code:** `exportCsv` headers in `apps/dashboard/src/pages/DailyReportsPage.tsx`.

### DSH-10 · Today's open-issue list loads only the latest 100

- **Severity:** Other · **Approval:** None · **Code read**
- **Repro:** needs a company with over 100 issues.
- **Actual:** the "Open issues" count is higher than the issues listed under it.
- **Code:** `fetchSiteIssuesApi({ projectId, limit: 100 })` with no status filter in `apps/dashboard/src/pages/TodayPage.tsx`, filtered to OPEN/ACKNOWLEDGED in the browser.
- **Fix direction:** ask the API for open issues only.

## Already works

Projects & Sites, Team and Company are refused by the server for non-admins, not only
hidden; only admins and project managers can change DPR recipients; the Today worker count
uses the same rule as the DPR, so they agree; Today's "Mark as no work" and "Send now";
Daily Reports lists site and project DPRs with history, filters and the PDF; Issues can be
resolved with notes; Materials has stock, transfers and the catalogue; the Company page
letterhead (checked in a browser earlier, tracker WEB-10).

## Test results

| ID | Problem | Result | What the dashboard showed |
| --- | --- | --- | --- |
| DSH-01 | Menu not V1; old and empty pages under More | Not tested | |
| DSH-02 | Other project's DPR can be confirmed | Not tested | |
| DSH-03 | "IST" time zone quietly means UTC | Not tested | |
| DSH-04 | Site with only materials or issues "hasn't reported" | Not tested | |
| DSH-05 | Attendance page shows wages, ₹0 | Not tested | |
| DSH-06 | "Development only" delete button | Not tested | |
| DSH-07 | WhatsApp Inbox fails for non-admins | Not tested | |
| DSH-08 | Finance role offered | Not tested | |
| DSH-09 | CSV has a Labour cost column | Not tested | |
| DSH-10 | Open-issue list misses older issues | Not tested | |
