# Reports: one period-report engine (RPT, PRC-19, PRC-20, CC-14)

> Phase 2 plan. Approved by Ilan in session, 9 Nov 2026 ("Go with it": every recommendation below).
> Visual proposal with the screens: https://claude.ai/artifact/9oVjifJ7pUDHTgNCyVo2nz (private to Ilan).
> Investigation: [reports-handoff.md](reports-handoff.md).

## Objective

Reports that answer in ten seconds and come to the user. One engine produces every report: a **period** × a
**scope** × an **audience** × **sections** × **outputs**. Each section is read from the module that owns the data,
through that module's own functions, so a report never disagrees with the module's page.

## Business value

The owner and PM stop assembling weekly and monthly reports by hand (Excel, photos, WhatsApp forwards). Everything
in the report is already recorded by site on WhatsApp; nobody types anything new. It is Must item PRC-19 and
Adarsh's #10 (owner's one page).

## Decisions (Ilan, 9 Nov 2026)

| # | Decision |
| --- | --- |
| D-R1 | Audiences: internal / owner first (R1, R2); client copy in R3 through the client view's allow-list. |
| D-R2 | Weekly and monthly both, plus custom dates. Week = Monday to Sunday, company time zone. |
| D-R3 | PDF page 1: letterhead, headline, four numbers, one status row per area, up to four photos, PM note. Detail from page 2. |
| D-R4 | Excel: one sheet per section (Summary, Work, Labour, Materials, Money, Schedule, Issues), plain columns. |
| D-R5 | WhatsApp: a short summary, the PDF attached, the link. Scheduled sends wait for the Meta template (PRC-13). |
| D-R6 | Photos: up to 6 per project, approved site days only (the client view's rule), spread over the period. None: no section. |
| D-R7 | The headline sentence is made by fixed rules in R1 (cannot invent a number). AI rewording later, behind a switch. |
| D-R8 | Only Admin and PM send to a client, always with a preview; default "send it to me to check first". |

## UX principles (every phase)

- **Answer first:** headline sentence, the few numbers compared with plan and with the last period, then "Needs you",
  then sections. Green rows fold away.
- **Nothing to type:** period, scope and audience default from the role and the page you came from.
- **Every number links** to the module page behind it, filtered to the period.
- **Is the data complete?** days with no confirmed site report or no attendance are shown, with a link to the day.
- **Never a fake green:** no plan or no budget shows "No plan" / "No budget", never "on track".
- **Respect roles:** money sections only for the roles that see spending (`may_view_expenses`); module switches hide
  their section.

## Phases

| Phase | Scope | Tracker |
| --- | --- | --- |
| R1 | Engine, project period report page, PDF, Excel | PRC-19 |
| R2 | Owner's Monday brief (all projects), send sheet, frozen copies, MONTHLY in automations, v3 tool + SOP | RPT-01, PRC-20 |
| R3 | Client monthly report (client allow-list), preview-before-send, share link | RPT-02 (approval: security) |
| R4 | Cost & margin, cash & receivables outlook, labour productivity, materials & waste, procurement, equipment, subcontractors | RPT-03 |
| R5 | Closeout, delay register | CC-14, RPT-04 |

## Status

| Phase | Status |
| --- | --- |
| R1 | **Done** 9 Nov 2026 (`89606f2` backend, `a9eeddb` dashboard). |
| R2..R5 | todo |

**R1 as built, differences from the plan:** "Needs you" also lists what the approvals inbox has waiting in the
project. Client bills are left out of the figures when a project has none (₹0 billed, ₹0 received is noise). The
PDF's page 1 carries the top five "Needs you" items. **Known limits:** an activity's state (late / behind) is as
of today, not as of the period's end, because the Gantt read is to date; a past month's report shows today's
schedule state. Fonts: rupees print as "Rs" in the PDF.

## R1 in detail (PRC-19)

### Scope

- `GET /reports/period` for one project (optionally one site), a week, a month or custom dates (max 92 days).
- Sections: **work** (BOQ work done in the period, progress vs plan), **schedule** (late / behind activities,
  forecast finish), **labour** (man-days by trade and day, wages for money roles), **materials** (received, used,
  running low), **money** (money roles: spent by cost centre, labour green / red, billed, received, owed),
  **issues** (raised and still open), **photos** (approved, up to 6), **completeness**.
- Headline and "Needs you" from fixed rules plus the approvals inbox filtered to the project.
- Compared with the previous period of the same length; man-days trend over 8 periods.
- `GET /reports/period/pdf` and `GET /reports/period/xlsx`: the same read, rendered.
- Dashboard: `/reports/period` becomes a built page.
- **Not in R1:** all-projects brief, sending, schedules, client copy, PM notes (need the frozen copy, R2).

### Backend

`backend/src/mesiri/domains/reports/period/`:

- `periods.py`: pure date logic (week / month / custom, previous period, labels, trend windows).
- `sections.py`: one async function per section, each calling the owning module:
  - work + schedule: `schedule.store.load` (progress, expected, state, forecast) and `progress.boq_router.counted_work`
  - labour: `workforce.pay_store.attendance_lines` (the wage sheet's own counted lines)
  - materials: `materials.router.stock_summary` (PRC-17), as the caller
  - money: `costing.centres.cost_centres`, `costing.router.variance_for`, `billing` bills / receipts / receivables
  - issues: `progress.router.list_issues`, as the caller
  - photos: `client_view.view.approved_photos` (the client view's own approved-only query, now with dates)
  - needs you: `approvals.inbox.waiting`, filtered to the project
- `headline.py`: pure rules: the headline sentence and the rule-made "Needs you" items.
- `engine.py`: runs the sections (one savepoint each, as the inbox does; a failing section is named in
  `unavailable`, never hides the rest).
- `pdf.py` (fpdf2, as the DPR), `xlsx.py` (openpyxl, as the cost export).
- `router.py`: mounted in `backend/http/app.py` and `apps/whatsapp-assistant/src/runtime/lifecycle.py`.

### Frontend

`apps/dashboard/src/lib/period-report.ts`, `pages/PeriodReportPage.tsx`; module map: `/reports/period` built;
route in `App.tsx`. Period control (Week / Month / Dates, ← → to step), project and site from the scope bar,
headline, KPI strip with deltas, "Needs you", completeness, section tabs, PDF and Excel buttons.

### Database

None in R1. R2 adds `report_snapshots` (additive).

### API

Added: `GET /reports/period`, `GET /reports/period/pdf`, `GET /reports/period/xlsx`. Modified: none (the client
view's photo query gains optional dates; its own output is unchanged).

### Risks

- A figure differing from the module page: avoided by calling the module's functions; tests compare.
- Slow on a long period: periods capped at 92 days; the schedule and BOQ reads are the same the Gantt makes.
- Fonts: the PDF core fonts are Latin-1, so rupees print as "Rs" (as the DPR PDF does).

### Testing

Unit tests for periods and headline rules (pure); engine tests with stubbed sections (a failing section is named,
others still show; money hidden for site roles); PDF and Excel render tests; route registered in both apps (the
assistant suite's router-mounting test). Dashboard: `tsc`, `oxlint`, `vite build`; a browser look on 390 / 1280 px.

### Rollback

Revert the commits. No migration, no data change.

### Labour isolation

Labour, Attendance, Payroll and Workforce are **read only** (`attendance_lines`, unchanged). Nothing in those
modules changes.

### Success criteria

A PM opens `/reports/period` for a project and in one screen sees what happened that week or month, what needs
them, and whether the data is complete; downloads the same as PDF and Excel; every figure matches the module page.
