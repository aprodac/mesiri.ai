# Dashboard cleanup: phone first, fewer tabs, real filters, full CRUD (Nov 2026)

> Asked by Ilan, 5 Nov 2026: "overall in mobile view all pages are very bad: too much description, some repetition,
> not so easy to understand, template-like pages, especially Today. Materials is split into too many tabs; some tabs
> should be filter dropdowns; proper filters; proper CRUD everywhere."
>
> Follows `docs/DESIGN.md` (WEB-25..WEB-41 rules) and continues WEB-25, which stopped before Finance, Labour and
> Materials. Tracker: WEB-48 .. WEB-52.

## What the 390 px screenshots showed (5 Nov, demo company, admin)

| Page | Problem |
|---|---|
| **Finance (all 12 pages)** | Old template look (DESIGN.md "Status of pages": not done). **Hard-coded figures shown as real**: "+12.4% MoM" and "85.8% Settled" on Expenses, "July 2026" on Petty cash, decorative trend lines that are not data. Jargon headers ("Portfolio Scope (Executive CFO Financial Command Center)", "Finance Module", "Field Treasury", "Auto-Discovery Ratio"). Monospace and ALL-CAPS labels. Four big stat cards before any content on a phone. 12 separate pages for one module. Now on for every company (PRC-21), so every customer sees it. |
| **Today** | "Getting started" takes the first screen with five long paragraphs; "Tell Mesiri" box in monospace capitals; stat strip, project block and "Open issues: No open issues" box each repeat a little; site rows tall with an "Open" button each. |
| **Materials** | Four views (Ledger, By category, Catalogue, Sizes) plus a "Stock now" button that duplicates By category; three-line subtitle; By category period is a pill row (DESIGN.md: filters are dropdowns); the by-category table wraps on a phone; Catalogue rows are tall. |
| Reports, Issues, Site log, Labour, Projects, Team, WhatsApp | Acceptable (done in WEB-25..35); a repeated one-line subtitle under each title ("What's stuck, most severe first · All projects") that the top bar already says. |

## Order

| ID | Item | Why first |
|---|---|---|
| **WEB-48** | **Finance honesty pass**: remove every hard-coded figure, fake trend line and jargon header; plain titles; no monospace / ALL-CAPS | Shows false numbers to every customer today |
| **WEB-49** | **Today, phone first**: getting started folded to one line (progress + the next step) and expandable; Tell Mesiri in the page's own type; one stat strip; compact site rows (tap the row, no separate Open button); empty "Open issues" is one line | Named by Ilan; the first page everyone opens |
| **WEB-50** | **Materials: three views, filters as dropdowns**: **Stock** (default: by category, with category, period and "running low only" dropdowns, search; stacked rows on a phone; replaces the Stock now panel), **Movements** (the ledger, as now), **Items** (catalogue, categories, sizes and the Excel import on one page, filtered by category); no subtitle | Named by Ilan |
| **WEB-51** | **Finance: 12 pages to 4, full CRUD**: *Expenses* (bills and receipts are a filter, not a page; edit, take back, attach), *Money* (accounts, petty cash, transfers, transactions as one ledger with filters), *Vendors* (list with phone / GSTIN, what was bought from each, edit, switch off), *Finance settings* (categories, approval and WhatsApp settings). Reports move into PRC-19 | Needs a yes on the page list before building (pages and links change) |
| **WEB-52** | **Every page: no repeated subtitle; CRUD audit**: each record a page lists can be added, opened, edited and removed (or switched off / taken back where history must stay) from that page; gaps listed and closed per module | Sweeps what WEB-48..51 leave |

## Rules kept from DESIGN.md

White ground, flat sections, one primary button, filters are dropdowns (`FilterSelect`, `PeriodSelect`) and pills only
switch a page's views, plain words, colours from tokens, checked at 390 px and 1440 px, light and dark.

## Not changed

Labour's pages beyond the shared header rule (they follow WEB-22). The WhatsApp assistant. Any API behaviour, except
where a CRUD gap needs a route (each one listed in its item).
