# Reports: handoff for a new session (9 Nov 2026)

> **9 Nov, later:** discussed and approved; the plan is [reports-plan.md](reports-plan.md) and R1 (PRC-19) is built.
>
> Written at the end of a long session so a new one can start the **reports** work with Ilan. **Discuss first, then
> plan, then build** (CLAUDE.md phases). Nothing here is built yet; it is the investigation and a proposal.

## The question (Ilan, 9 Nov)

"Should we focus on reports, the different types of reports that will be needed?" Proposed: yes, before
Variations (module 25). PRC-19 (weekly / monthly report) is a **Must** still `todo`; the data mostly exists.

## What exists already (one day or one module each)

- **Site:** daily report, site and project DPR (PDF, sent on WhatsApp) `domains/dpr`; Analytics `/analytics`; Site log.
- **Money:** Cost control `/cost` (green / red, budget vs actual, materials vs BOQ, cost centres); evening cost card
  on WhatsApp (CC-11).
- **Accounts:** project P&L, trial balance, balance sheet, ledgers, day book, cash & bank book, GST, TDS,
  receivables, Tally export (`/accounts/*`).
- **Stock / labour / subcontract:** stock for any period (PRC-17, done: opening, received, used, closing per
  category and site), wages `/labour/wages`, subcontractor statement (NXT-17).
- **Planned placeholders** in `apps/dashboard/src/lib/module-map.ts`: `/reports/period` (Weekly & monthly),
  `/labour/productivity`, `/procurement/reports`, `/accounts/cash-flow`, `/accounts/bank-reco`, `/cost/closeout`.

## What is missing (proposal, in order)

| # | Report | For | Tracker |
| --- | --- | --- | --- |
| 1 | **Weekly / monthly project report**: work done vs plan, man-days, materials in / used / stock, money spent / billed / received, delays and issues, photos. Page, PDF, Excel | Owner, PM | PRC-19 (Must) |
| 2 | **Sent on WhatsApp on a schedule** (Monday weekly, monthly on the 1st) | Owner, MD | PRC-20; Meta template PRC-13 (ops) |
| 3 | **Owner's one page across sites**: progress, green / red, cash, receivables, delays, top issues | Owner | Adarsh #10 (module 21) |
| 4 | **Client monthly report**: report 1 with the client view's allow-list (no rates, costs) | Client | new; reuse `domains/client_view/view.py` rules |
| 5 | **Labour productivity**: man-days vs measured output vs benchmark | PM, Owner | CC-05 / CC-07 page |
| 6 | **Procurement reports**: by supplier, price trend, ordered vs received vs billed, late deliveries | Purchase | `/procurement/reports` |
| 7 | **Cash flow** next 4–8 weeks | Owner, Finance | planned |
| 8 | **Closeout report**: BOQ planned vs done, budget vs actual, leftover stock, still owed | Owner | CC-14 |
| Later | Delay register for extension-of-time claims; bank reconciliation | | |

## Proposed architecture (to discuss)

**One period-report engine, not eight reports.** A report = a period × an audience × sections × outputs.
- **Sections** come from the module that already owns the data (call its own functions, as the approvals inbox
  does: `domains/approvals/inbox.py` calls each module's own list route as the caller, so access and module switches
  are the module's): stock period (PRC-17), cost green / red, labour man-days and wages, RA bills and receipts
  (`domains/billing`), schedule and delays (`domains/schedule/store.py` `load`), approved photos (the client view's
  approved-only query), issues.
- **Audience** filters fields: internal / owner / client (client = the client view's allow-list idea).
- **Outputs:** page, PDF (existing PDF helpers in `domains/reports/`, `domains/dpr/pdf.py`), Excel, WhatsApp (v3:
  a route on `ALLOWED` + an SOP line; scheduled via the `automations` module).
- Reports 1, 2, 3, 4, 8 are then compositions; a new module adds one section.

## Questions to settle with Ilan first

1. Which audiences first (owner only, or owner + client)?
2. Weekly and monthly both, or monthly first? Week = Mon–Sun?
3. What must be on page 1 of the PDF (the owner's 10-second view)?
4. Excel: one sheet per section, or one flat sheet?
5. WhatsApp: the PDF, a text summary with a link, or both? (Template approval is an ops step.)
6. Photos in the PDF: how many, chosen how?

## Things learned this session (save time)

- Work on `main`; run ALL of CLAUDE.md's checks before every push, **including the WhatsApp assistant suite**: it
  holds `test_production_app_router_mounting`, which caught a router mounted in `backend/http/app.py` but not in
  `apps/whatsapp-assistant/src/runtime/lifecycle.py` (production serves the dashboard API from there: a 404 in
  production). Mount every new router in both (and `agent_api/app.py` if WhatsApp should call it).
- The assistant suite needs the `workflow` extra (`uv pip install --system -e ".[workflow]"`) or 24 tests fail
  on `langgraph`. Don't pass `-p no:logging` to it (a test needs `caplog`).
- Local Postgres: `pg_ctlcluster 16 main start` (it stops when the container sleeps), role `mesiri` /
  `mesiri_local_dev`, then `alembic -c backend/alembic.ini upgrade head` with `PYTHONPATH=backend/src:shared/contracts/src:platform/ai/src`.
  Contract tests: `pytest backend/tests/contract/<file> -m integration`.
- Contract suites leave `money_accounts` behind (billing), which breaks `test_material_requests_api_contract`
  run after them (INF-33): `TRUNCATE money_accounts CASCADE` locally.
- The activity log (ADM-01, `mesiri/http/activity.py`) records every 2xx write. A POST that saves nothing (a
  preview, a "generate PDF" that stores nothing) must be marked `@saves_nothing` or call `mark_saved_nothing(response)`.
- `scripts/allow_route.py` adds a WhatsApp v3 tool in one step (fixed 9 Nov to keep apostrophes).
- The dashboard's UX-10 check: `node apps/dashboard/scripts/screens.mjs` (stubbed API). `/today` fails there
  already on main (role-home reads `buckets['61_90']` of an empty reply): known, not yet fixed.
- Run the real app for a look: uvicorn `mesiri.http.app:create_app --factory` with
  `MESIRI_OBJECT_STORAGE__PROVIDER=local` (+ `LOCAL_ROOT`, `SIGNING_SECRET`, `PUBLIC_BASE_URL`), and
  `VITE_API_URL=http://localhost:8000 npx vite` in `apps/dashboard`.

## Related plans

[capability-framework-gap-analysis](capability-framework-gap-analysis.md) (module 21),
[procurement-plan](procurement-plan.md) (PRC-17..20), [cost-control-plan](cost-control-plan.md) (CC-07, CC-14),
[client-view-plan](client-view-plan.md), [approvals-inbox-plan](approvals-inbox-plan.md).
