# One story: brand, navigation and flow for the whole dashboard (Nov 2026)

> **Status:** plan written 9 Nov 2026 (asked in session: "give this software a proper start, proper UI, proper
> feel overall; like a story has a start and a middle, it should feel properly connected and properly divided,
> especially UI and UX: brand, theme, sidebar, the first screens"). Tracker items `UX-01`..`UX-10` in
> [V1_TRACKER.md](V1_TRACKER.md). Continues WEB-25 / WEB-52 and closes WEB-14.
>
> Phase 1 (investigation) findings are in §2. The plan is §3 onward. Decisions needed before building are in §9.

---

## 1. The story Mesiri should tell

A construction company lives one story per project. The dashboard should follow it, so the person always
knows where they are and what comes next:

| Act | The user's question | Mesiri today |
|---|---|---|
| **1. Arrive** | "What is this, and is it for me?" | Login and signup have their own editorial look (monospace, a voice-note demo); unlike the app behind them |
| **2. Set up** | "What do I do first?" | Welcome screen, a "Finish setup" checklist, Project start, Projects & Sites, Team, Company, WhatsApp: five separate places, no single path |
| **3. Every day** | "What happened on site, what needs me?" | Today, Daily reports, Issues: the strongest part (WEB-25) |
| **4. Run the project** | "Are we on plan, on stock, on budget?" | Planning, Materials, Procurement, Labour, Subcontract, Equipment, Cost control: built, but as nine separate drawers |
| **5. Money** | "Who owes us, who do we owe, are we making money?" | Finance, Client billing, Accounts: built, three drawers with overlapping pages |
| **6. Close** | "Is this project finished and settled?" | Closeout report planned (CC-14) |

The aim: every screen belongs to one act. The sidebar shows the acts in order. Each record links forward and back
along the chain (request → order → delivery → bill → payment → ledger).

## 2. What exists today (investigation, 9 Nov, `main` at `786023f`)

Screenshots: desktop 1440 px and phone 390 px, owner role with every module on, API stubbed.

### Brand
- **Three brand directions in the repo, one shipped.** Shipped: hazard yellow `#facc15` primary, charcoal sidebar
  `#3E3C3D`, yellow/black hazard stripe on the top bar, Unbounded wordmark, IBM Plex Sans UI, Geist Mono numbers
  (`index.css`, WEB-18/19/76). `docs/DESIGN_SYSTEM.md` still describes a lime `#7ED957` brand (marked superseded).
  WEB-14 showed three directions on 15 Oct (Warm Site, Blueprint, Mesiri Green); none was chosen.
- **The comments in `index.css` still say "site orange"** for what is now yellow.
- **No favicon:** `index.html` points at `/favicon.svg`, and there is no `public/` folder. No app icon or web manifest,
  so "Add to home screen" on a phone shows a blank tile.
- **1,497 hard-coded palette classes** (`emerald-600`, `amber-50`, `rose-500` …) across the dashboard bypass the tokens,
  so a theme change does not reach most pages.
- **Rainbow sidebar:** every item has its own icon colour (orange, sky, rose, amber, teal, violet, indigo, green …).
  This conflicts with DESIGN.md's rule that colour carries meaning only.
- **Login / signup look like a different product:** monospace capitals, an editorial timeline, a white right panel.
  The app behind them is charcoal and yellow.

### Navigation (`components/app-sidebar.tsx`, `lib/module-map.ts`)
- For an owner with every module on, the sidebar shows **3 items + "Site records" + 12 more entries in one list**:
  Site log, Analytics, Attendance, then Planning, Materials, Procurement, Equipment, Subcontract, Finance, Cost control,
  Client billing, Accounts as collapsed drawers. The order is the order they were built, not the order of the work.
- **The same page appears in two drawers:** BOQ & budget (Planning and Cost control), Requests (Materials and
  Procurement), Suppliers (Procurement and Finance). Two doors to one room make the map harder to learn.
- **Setup is invisible to an owner:** the Setup group (Projects & Sites, Team, Company, WhatsApp) requires the `ADMIN`
  role in `app-sidebar.tsx`. An `OWNER` sees none of it in the screenshot.
- **Labour is a single "Attendance" link** under "Site records", while every other module is a drawer.
- **Live (`/live`) has no sidebar entry**, though it is the most striking screen Mesiri has.
- **The preview toggle** (map icon) shows planned pages with a hollow dot. That is useful internally, but the switch
  sits next to the user's name, where a customer can find it.

### First run
- An empty company lands on **Today: "No active sites yet"** in a dashed box, with one button to Projects & Sites.
  The Welcome page (`WelcomePage.tsx`), the getting-started card and the first-report moment exist, but they are
  separate pieces, not one guided path.
- Most module pages have no empty state that says what to do first. Accounts rendered blank on a phone with no data.
  The stubbed API sends `[]` for everything, so a real empty company needs re-checking, but the gap is real.

### Page kit
- `components/ui` has shadcn primitives plus `kpi-card`, `bulk-action-bar`, `combobox`. There is **no shared
  `PageHeader`, `Section`, `StatStrip`, `EmptyState`, `FilterBar` or `ListDetail`**. Only the DPR pages have them,
  inside `dpr-page.tsx`. Every module page rebuilds its own header and empty state, so pages drift apart.

## 3. Objective, scope, business value

**Objective.** One brand, one navigation shaped like the project's story, one first-run path, and one page kit, so
every module (built and future) looks and behaves like part of the same product.

**In scope.** Brand tokens and assets, sidebar and top bar, login / signup / welcome / setup path, shared page
components, empty states, cross-links between records, phone layout. Every dashboard page gets the kit,
group by group.

**Out of scope.** API behaviour and data (except a read for setup progress if one is missing). The WhatsApp
assistant. The control panel (`apps/control-panel`) and the mobile app (`apps/mobile`): they follow once the brand
is decided. Marketing website.

**Business value.** The owner who pays decides in the first ten minutes, and today those minutes cross three visual
styles and a dead-end empty screen. A connected product also makes a demo easier: one path, start to finish. Every
module built after this one gets the kit for free instead of inventing its own page again.

## 4. The new navigation (proposal)

The sidebar follows the acts. A drawer opens to its pages. Each page has **one home**; the other places link to it.

```
Mesiri                                  (wordmark; company switcher under it)
─────────────
Today                    · badge: to confirm
Daily reports
Issues                   · badge: open
Live
─────────────
PLAN
  Project start · Schedule · BOQ & budget · Material plan · Documents · Places & live plans · Drawing check
SITE
  Site log · Attendance & workers · Stock & movements · Equipment · Analytics
BUY
  Requests · Purchase orders · Goods received · Rates · Suppliers · Subcontract (work orders, bills & checks)
MONEY
  Cost control · Client billing · Expenses & money · Accounts
─────────────
Settings  (bottom; a page with tabs: Projects & sites · Team · Company · WhatsApp · Automations · Modules)
User menu (theme, sidebar look, sign out; the planned-modules preview only for super admins)
```

Rules:
- **Acts are labels, not drawers.** PLAN, SITE, BUY and MONEY are section headings. Under them, a module with several
  pages (Cost control, Accounts, Subcontract, Equipment) is a drawer, and a module with one page is a link.
  Six sections of 2 to 7 entries replace one list of fifteen.
- **Role order.** The same sections, ordered by the role's day: a site engineer gets SITE right after the daily block,
  an accountant gets MONEY. Nothing is hidden by the order alone. Roles still hide what they may not see (existing
  `roles` in `module-map.ts`).
- **One home per page.** BOQ & budget lives in PLAN, and Cost control links to it. Requests lives in BUY, and Stock
  links to it. Suppliers lives in BUY, and Accounts links to it. `module-map.ts` keeps `related` links for these.
- **Settings for owner and admin**, fixing the owner who sees no setup today.
- **Old addresses keep working** (redirects in `App.tsx`, as DESIGN.md requires).
- **Search / jump (⌘K):** one box that finds any page, project, site, supplier or worker. This needs `cmdk`, which
  DESIGN_SYSTEM.md already recommended. It is the only new library, and it is optional (decision D-UX4).

## 5. Work items

| ID | Item | Size | What changes |
|---|---|---|---|
| **UX-01** | **Brand decision and foundation** | M | Decide the identity (D-UX1). Then: one token set in `index.css` (light + dark), the hard-coded palette re-pointed to tokens (Tailwind v4 lets `--color-emerald-*` etc. be redefined at the token layer, per the WEB-14 note), stale comments fixed, `DESIGN_SYSTEM.md` reduced to a pointer. Brand page in DESIGN.md: logo use, colours, type, voice |
| **UX-02** | **Brand assets** | S | `public/` with favicon (SVG + PNG), apple-touch icon, web manifest (name, theme colour, icons), social preview image, the sign-in page's tab title. Same mark everywhere: sidebar, login, PDFs' footer |
| **UX-03** | **Calm sidebar** | S | One icon colour (muted, the active item in the brand colour), no rainbow tones; same look in the charcoal and light themes; the preview toggle moves to the super-admin user menu |
| **UX-04** | **Navigation by the story** | M | §4: sections PLAN / SITE / BUY / MONEY, one home per page, Settings page with tabs (owner and admin), Live in the sidebar, role order, redirects. `module-map.ts` gets a `section` per group and stays the one list |
| **UX-05** | **Page kit** | M | Lift `PageHeader`, `Section`, `StatStrip`, `EmptyState`, `FilterBar`, `ListDetail` (list + detail panel, a sheet on a phone) out of `dpr-page.tsx` and the Requests / Purchase orders pages into `components/page/`; DESIGN.md points to them. No page changes yet except the DPR pages switching to the shared copies |
| **UX-06** | **First-run story** | M | Login, signup and welcome in the app's brand (keeping the voice-note demo, but in the app's type and colours); after signup, one path: Welcome → *Your first project* (Project start) → *Who reports from site* (Team) → *Connect WhatsApp* → *Your first update* (first-report moment) → Today. Each step can be skipped; the checklist stays in the sidebar ("Finish setup 3/5") until done. Today's empty state becomes the next setup step, not a dead end |
| **UX-07** | **Empty states that lead** | S | Every module page with no data says what it is for, the one thing to do first, and the WhatsApp sentence that fills it ("Send *JCB 6 hrs, 30 L diesel* and it shows here"). Uses `EmptyState` from UX-05 |
| **UX-08** | **Pages onto the kit, section by section** | L | PLAN, then SITE, BUY, MONEY: each page uses the kit, the tokens and the one-primary-button rule; the repeated subtitles go (WEB-52). One commit per section, each checked at 390 px and 1440 px, light and dark |
| **UX-09** | **Connected records** | M | Each record links along its chain: request ↔ order ↔ GRN ↔ supplier bill ↔ payment ↔ ledger; BOQ line ↔ work done ↔ cost ↔ RA bill; worker ↔ attendance ↔ cost. A "Linked" strip in the detail panel from `ListDetail`. Reads existing ids; a missing link that needs an API field is listed, not built here |
| **UX-10** | **Screenshot check for every page** | S | A Playwright script (`apps/dashboard/scripts/screens.mjs`) with a stubbed API that opens every built page in `module-map.ts` at 390 and 1440 px, light and dark, and fails on a blank page or a console error. Run before each UX push; images go in the phase report |

**Order:** UX-01 + UX-02 + UX-03 (look) → UX-05 (kit) → UX-04 (navigation) → UX-06 + UX-07 (first run) → UX-08
(pages, section by section) → UX-09 (links). UX-10 is built first, alongside UX-01, so every later step is checked.

## 6. Files expected to change

- `apps/dashboard/src/index.css`, `index.html`, new `apps/dashboard/public/`
- `components/app-sidebar.tsx`, `components/app-layout.tsx`, `components/scope-bar.tsx`, `lib/module-map.ts`, `App.tsx`
- New `components/page/*` (kit) and `components/brand/*` additions
- `pages/Login.tsx`, `Signup.tsx`, `WelcomePage.tsx`, `TodayPage.tsx`, `components/getting-started-card.tsx`,
  `components/first-report-moment.tsx`, a new Settings page wrapping the existing Projects / Team / Company / WhatsApp
- Every page in `pages/` during UX-08, group by group
- `docs/DESIGN.md`, `docs/DESIGN_SYSTEM.md`, this plan, the tracker

**Backend / database / API:** none planned. If the setup path needs a step's status that no route gives, it is
listed and done as a separate additive item.

## 7. Risks

| Risk | Mitigation |
|---|---|
| Moving pages in the sidebar confuses current users | Redirect every old address; the moved pages keep their names; short "Moved" note in the release update |
| Re-pointing 1,497 hard-coded colours changes meaning somewhere (a red that should stay red) | Map by meaning (emerald → success, amber → draft, rose → destructive, sky/blue → info, indigo → ai), check every page in UX-10's screenshots before and after |
| A big change lands on `main` with no review branch | Small commits per item; UX-10 screenshots in every report; one section per push in UX-08 |
| Labour pages (Attendance, Workers) restyled | Labour is a normal module now (3 Nov). Only its look changes, no behaviour; listed in the report |
| Payroll / Workforce behaviour | Not touched. Wages & advances stays blocked on its own approval |
| Phone layout breaks while pages move to the kit | UX-10 at 390 px on every page, every push |

## 8. Testing, rollback, success

**Testing.** `npx tsc -b --noEmit`, `npx oxlint src/`, `npx vite build` on every push. UX-10 screenshots (every built
page, 2 widths, 2 themes) before and after each item. A real empty company and the demo company checked against a
local API for UX-06 / UX-07. Backend suites are run as CLAUDE.md asks, though no backend change is planned.

**Rollback.** Each item is its own commit(s); revert them in reverse order. Tokens are one block in `index.css`, so
the brand can go back in one revert. Navigation changes keep redirects, so a revert never breaks a bookmarked address.

**Labour isolation.** Labour and Attendance get the visual kit only; no data, permission or workflow change.
Payroll and Workforce are not touched.

**Success criteria.**
1. A new owner goes from signup to their first DPR on Today without hitting a dead end or leaving the guided path.
2. The sidebar for an owner with every module shows at most 4 daily entries + 4 sections + Settings, with each page in
   exactly one place.
3. No page uses a hard-coded palette colour for meaning (lint check: `rg "(emerald|amber|rose|sky)-[0-9]"` finds
   only the token file).
4. Login, signup, the app, the favicon, the phone home-screen icon and the DPR PDF use the same mark and colours.
5. Every built page passes UX-10 at 390 px and 1440 px in light and dark: no blank page, no console error, no
   sideways scroll.

## 9. Decisions needed (proposed default in **bold**)

| # | Question | Default |
|---|---|---|
| D-UX1 | Brand direction: keep the shipped **site yellow + charcoal** (hazard yellow `#facc15`, charcoal, Unbounded wordmark, IBM Plex), or choose again among WEB-14's directions (Warm Site, Blueprint, Mesiri Green)? | **Keep yellow + charcoal and make it consistent.** It is what customers have seen since 24 Oct and reads as construction. A new direction would be decided with mockups first |
| D-UX2 | Sidebar sections: PLAN / SITE / BUY / MONEY as in §4? | **Yes**, names to confirm (could be Plan / Site / Purchase / Money) |
| D-UX3 | Setup into one Settings page with tabs, opened from the bottom of the sidebar? | **Yes** |
| D-UX4 | Add `cmdk` for a ⌘K jump box? | **Yes, in UX-04**, the only new library |
| D-UX5 | Login and signup: keep the editorial voice-note demo, restyled in the app's brand? | **Yes, keep the demo, change the look** |
