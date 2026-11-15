# Learn Mesiri: walkthroughs by role, workflow, module and page

> **Status: approved 15 Nov 2026 in session; being built.** Order changed 15 Nov in session: the page tours (phase 2)
> come first, since each tour is useful the day it ships; SS-41 (Learn page) and SS-42 (engine) were also built 15 Nov
> in a parallel session (section 9). Done: **SS-41, SS-42, SS-44 Planning**.
> Tracker: **SS-41 to SS-49** in [V1_TRACKER.md](V1_TRACKER.md). Builds on
> [guided-onboarding-plan.md](guided-onboarding-plan.md) (SS-26..SS-40, built and on `main`).
>
> Asked 15 Nov: "not only page-wise but module, workflow and user-wise too; a dedicated page where we pick one
> walkthrough and run it; and the places where we can send a WhatsApp message or enter something and test it, so a
> full learning is done."

## 1. Decisions (15 Nov 2026, in session)

| # | Decision | Answer |
|---|---|---|
| D-L1 | Walkthroughs by page, module, workflow and role, from one Learn page | **Yes** |
| D-L2 | Page tours hand-written or automatic | **All hand-written** (61 still to write; no automatic tours) |
| D-L3 | Where practice entries go | **Real entries, then take back**: each practice ends by showing how to undo it. No Practice site (that would need a new site flag kept out of reports, cost and accounts, and Ilan's approval) |
| D-L4 | Which module's hand-written tours come first after the engine | **Planning** |
| D-L5 | Estimates in Claude Opus 5.5 usage, not days | Section 8 |

## 2. What already exists (built 15 Nov, on `main`)

- **Spark tours** (SS-40): `apps/dashboard/src/components/tour.tsx` draws them; content in `src/lib/tours.ts`. Dims the
  screen, lights one element, the Spark (Live's character, `components/live/spark.tsx`) explains; Next, Back, Skip,
  "2 of 5". Remembered per person in `users.guide_seen` (`/tour/...`, migration 0553). Replay from Help.
- **App tour** (sidebar, Search, project picker, On WhatsApp, Help) and **15 hand-written page tours**: Today, Daily
  reports, Issues, Materials, Labour, BOQ, Projects, Team (SS-40); Project start, Schedule, Material plan, Live plans,
  Places, Drawing check, Documents (SS-44).
- **A tour waits for its page** (`startWhen`, SS-44): it starts by itself only once one of its markers is on screen,
  so it never plays (and is never marked seen) on a project picker or a loading skeleton; picking a project starts it.
  Replay from Help shows whatever is there, and every Planning tour's first step points at the project list
  (`planning.pick`) for that case.
- **Markers**: steps point at `data-guide="..."` on the element (or `guide="..."` on `Segmented` / `StatStrip`).
  A step whose element is not on screen is skipped. **The build fails** when a step's (or `startWhen`'s) marker is on
  no element (`apps/dashboard/vite.config.ts`, `checkTourMarkers`). A marker set by a condition counts
  (`data-guide={next ? 'setup.next' : undefined}`), for "the one that is lit up".
- **WhatsApp examples on every page** (SS-39): `module-map.ts` `whatsapp` examples (save / answer, what to say,
  the reply, the assistant tools), shown in the "On WhatsApp" pop-up; `whatsapp-assistant/tests/agent_api/
  test_module_map_whatsapp.py` keeps them true.
- **Start modes** (SS-27/28): who gets tours is `MODES[mode].tours` in `src/lib/start-mode.ts`.

## 3. The Learn page (SS-41)

`/learn`, in the sidebar's everyday pages and opened from Help ("Learn Mesiri").

- Four tabs: **For you** (the person's role path first), **Workflows**, **Modules**, **Pages**.
- A card per walkthrough: title, one line on what it teaches, minutes, number of steps, **Start**, and done / not
  started (from `guide_seen` key `/learn/<id>`). Replay any time.
- A **Try it** section per page: the WhatsApp messages to send (from `module-map.ts` examples, with Copy and Try it
  on WhatsApp) and the dashboard actions to try there.

## 4. The walkthrough engine (SS-42), extending `tour.tsx`

One definition for every kind (`src/lib/walkthroughs.ts`):

```ts
interface Walkthrough { id: string; kind: 'role' | 'workflow' | 'module' | 'page'; title: string; about: string;
  minutes: number; roles?: string[]; steps: WalkStep[] }
interface WalkStep extends TourStep {   // TourStep: target?, title, text, mood?
  page?: string                          // go to this page first (the engine navigates and waits for the target)
  try?: TryWhatsApp | TryHere            // a practice step
  takeBack?: string                      // after a practice: how to undo it (WhatsApp words or the dashboard button)
}
```

- **Across pages**: a step with `page` navigates there (react-router), waits up to ~4 s for its target, then shows.
- **Page walkthrough** = that page's hand-written tour. **Module walkthrough** = its pages' tours back to back.
  **Role path** = its workflows in order. One runner for all; progress saved per walkthrough.
- **Try on WhatsApp**: the bubble shows the message, **Copy**, **Try it on WhatsApp** (wa.me with Mesiri's number,
  `waLink`), and **I've sent it**. Optional `check`: the engine reads an API list before and polls it every ~4 s;
  when a new record appears it says "Got it" and lights it up on the page.
- **Try here**: the Spark lights the real button ("Record delivery") and the spotlight lets clicks through; when a
  dialog opens the tour shrinks to a small Spark chip; when that dialog closes (saved) the tour comes back and moves
  on. **Done** / **Skip** always available.
- **Take back** (D-L3): each practice ends with a step that shows the undo, and points at it:
  WhatsApp: "take back the last delivery" (assistant tools `undo_receipt`, `undo_usage`, `undo_transfer`,
  `undo_expense`; **check the exact words against `agent_api/SOP.md` before writing them**); dashboard: the record's
  reverse / delete button.
- The build check (`checkTourMarkers`) also covers walkthrough steps; every `page` must be a built page in
  `module-map.ts` (`guideLink`).

## 5. Catalogue

### 5.1 Role paths (4)

| Role (system role) | Path |
|---|---|
| Owner / admin (ADMIN) | App tour → W6 Start a project → W1 Site update to daily report → W9 Cost control → W8 Billing the client |
| Project manager (PROJECT_MANAGER) | W6 Start a project → W1 Daily site review → W2 Material → W5 Subcontractor → W9 Cost control |
| Site engineer / supervisor (SITE_ENGINEER) | Mostly WhatsApp: W1 daily update → people (W4 first half) → material in and used (W2 last half) → W7 an issue → asking for material (W2 first step) |
| Accounts / finance (FINANCE) | W3 Supplier bill to payment → W4 wages paid → W8 billing → W11 Month end |

### 5.2 Workflows (11)

| # | Workflow | Pages in order | Practice steps |
|---|---|---|---|
| W1 | Site update to daily report | WhatsApp → Today → Site log → Daily reports | WhatsApp: "6 masons, 4 helpers, slab shuttering done" → Save; take back |
| W2 | Material, from asking to using | Requests → Purchase orders → GRN → Materials (Stock, Movements) | WhatsApp: request, order, delivery, use; take back each |
| W3 | Supplier bill to payment | Expenses → Suppliers → link deliveries → pay | Here: record an expense with a bill photo; take back |
| W4 | Labour to wages | Attendance → Wages → approve → pay; Advances | WhatsApp: attendance, an advance; take back |
| W5 | Subcontractor | Work orders → measure → Bills & checks → approve → advance | WhatsApp: work order, measurement |
| W6 | Start a new project | Project start → BOQ import → Schedule → Team → first report | Here: new project; WhatsApp: add a person |
| W7 | An issue, start to finish | Issues: report → seen → fixed | WhatsApp: report and close an issue |
| W8 | Billing the client | RA bills → Receivables (client payment) | WhatsApp: "Client paid 5 lakh for RA-03"; take back |
| W9 | Cost control | BOQ lines → Green / red → Budget vs actual → Materials vs BOQ | Ask on WhatsApp: "How is Green Villa doing on cost?" |
| W10 | Machines and hire | Equipment daily log → Hire check | WhatsApp: "JCB 6 hrs, 30 L diesel"; take back |
| W11 | Month end | Weekly & monthly → Accounts → Months → Tally export | Ask: "Send me October's report" |

### 5.3 Modules (13)

Site, Tasks, Planning, Cost control, Materials, Procurement, Labour, Subcontract, Finance, Accounts, Client billing,
Equipment, Settings: each = its pages' tours back to back (sidebar order).

### 5.4 Page tours: all hand-written (D-L2), in build order (Planning first, D-L4)

Built (15): Today, Daily reports, Issues, Materials (Stock/Movements/Items), Labour (4 views), BOQ & budget, Projects &
sites, Team; **Planning (SS-44, 15 Nov)**: Project start, Schedule, Material plan, Live plans, Places, Drawing check,
Documents.

| Order | Module | Pages to write (61; 54 left) | Count |
|---|---|---|---|
| 1 | Planning | Project start, Schedule, Material plan, Live plans, Places, Drawing check, Documents | 7 (**done**) |
| 2 | Procurement | Requests, Purchase orders, Goods received (GRN), Pending deliveries, Rates, Quotations, Suppliers, Returns | 8 |
| 3 | Cost control | Overview, Green / red, Budget vs actual, Materials vs BOQ, Cost centres | 5 |
| 4 | Accounts | Accounts home, Project P&L, Ledgers, Receivables, Cash & bank book, Day book, Tally export, GST, TDS, Profit & loss, Balance sheet, Trial balance, Chart of accounts, Months | 14 |
| 5 | Site | Weekly & monthly, Site log, Analytics | 3 |
| 6 | Tasks | Tasks (all 4 views share one tour) | 1 |
| 7 | Materials | Stock count, Stock value | 2 |
| 8 | Labour | Wages, Advances | 2 |
| 9 | Subcontract | Subcontractors, Work orders, Bills & checks | 3 |
| 10 | Finance | Expenses, Money, Finance settings | 3 |
| 11 | Client billing | Clients, RA bills, Client view | 3 |
| 12 | Equipment | Machines, Daily log, Hire check, Vehicles, Shuttering & tools | 5 |
| 13 | Settings | Settings, Company, WhatsApp, Bring your data, Activity log | 5 |

**How to write one page tour** (the recipe, so any session can continue):

1. Read the page component (`apps/dashboard/src/pages/...`) and its `module-map.ts` entry (`about`, `example`,
   `whatsapp`).
2. Pick 3–6 things a new person must know: the view tabs, the key numbers, the main action, the list, filters.
3. Add `data-guide="<page>.<thing>"` to each element (or `guide="..."` on `Segmented` / `StatStrip`).
4. Add the tour to `PAGE_TOURS` in `src/lib/tours.ts`, keyed by the page path (no `?view=`): `introFromPage: true`,
   `startWhen` (the markers of the page's real content: what shows once a project is picked and the data loaded,
   including its empty state when that state teaches something), then the steps; a page that needs a project starts
   with the `planning.pick` step; the last step can point at `app.whatsapp` with the page's WhatsApp example; plain words, construction terms are explained by the glossary on their own; give a Spark mood.
   A step may mention the WhatsApp message from the page's `whatsapp` example.
5. `npx tsc -b --noEmit && npx oxlint src/ && npx vite build` (the build fails on a missing marker), then click it
   through in a browser: Playwright against `vite` with `/me/preferences` stubbed (`start_mode: 'guided'`,
   `guide_seen: {'/tour/app': 1}`), `/projects` + `/lifecycle/projects` with two projects (so the picker shows) and the
   page's own route with sample data; check picker → no tour, pick → tour, every step, phone and dark, and the empty
   state.

## 6. Rollout and safety

- No database change (progress uses `users.guide_seen`, migration 0553). No backend change except, if a `check`
  needs it, reading existing list routes.
- Practice is real data, taken back at the end (D-L3). Never on a company in trial read-only mode.
- Who sees what: role paths filter by `me.role`; a step for a page the role cannot open is skipped.
- Rollback: revert the commits; tours and the Learn page are front-end only.

## 7. Phases and tracker

Build order since 15 Nov (in session: "we need to complete the rest pages first"): SS-44 → SS-45 → SS-46 → SS-47,
then SS-41 → SS-42 → SS-43, then SS-48 → SS-49.

| ID | Item | Phase |
|---|---|---|
| SS-41 | Learn page (`/learn`): tabs, cards, progress, Try it lists | 1 |
| SS-42 | Engine: across pages, Try on WhatsApp (with check), Try here (dialog watch), Take back, walkthrough definitions | 1 |
| SS-43 | Workflows W1, W2, W4 + role paths Site engineer, Owner | 1 |
| SS-44 | Planning page tours (7) | 2 |
| SS-45 | Procurement (8) and Cost control (5) page tours | 2 |
| SS-46 | Accounts page tours (14) | 2 |
| SS-47 | The other page tours (27: Site, Tasks, Materials, Labour, Subcontract, Finance, Client billing, Equipment, Settings) | 2 |
| SS-48 | Workflows W3, W5–W11 + role paths Project manager, Finance | 3 |
| SS-49 | Module walkthroughs (13) | 3 |

## 8. Estimate (Claude Opus 5.5: $4 / 1M input, $0.20 / 1M cached input, $20 / 1M output)

Rough, from this session (guided onboarding + WhatsApp pop-ups + 8 tours ≈ 50–70 M tokens processed, ≈ $25–45).

| Phase | Tokens processed | At API prices |
|---|---|---|
| 1 (SS-41..43) | ~35–55 M | ~$20–35 |
| 2 (SS-44..47, 61 tours) | ~100–200 M | ~$60–120 |
| 3 (SS-48..49) | ~40–70 M | ~$25–45 |
| **Total** | **~175–325 M** | **~$105–200** |

Per item: one page tour ~$1–2 (Accounts ~$2); one workflow ~$2–4. Fresh sessions per phase keep cost low (a long
session re-reads more each step). On a Claude plan this is usage-limit time, not money: phase 2 alone is several
5-hour windows.

## 9. Built (SS-41, SS-42, 15 Nov 2026)

- **Learn page** `/learn` (`pages/LearnPage.tsx`): For you / Workflows / Modules / Pages (`?view=`), a card per
  walkthrough (kind, minutes, steps, "You try it", Done / Not started, Start / Play again). Pages tab: every built page
  the person can open that has a tour or WhatsApp examples, by module, with **Tour**, **Try it** (the same
  `WhatsAppPreview` as the "On WhatsApp" pop-up: Copy, Try it on WhatsApp) and **Open**. In the sidebar's everyday
  pages for every start mode but "I'll find my way"; in Help for everyone ("Learn Mesiri: walkthroughs to try").
- **Definitions** `lib/walkthroughs.ts`: page walkthroughs and module walkthroughs are **made from `PAGE_TOURS`**
  (views of one page share its tour and start on the first view), so each new page tour (SS-44..47) appears on the
  Learn page and in its module with no other change; a module card says "N of M pages so far" until all are written.
  Workflows and role paths are written by hand.
- **Engine** `components/walkthrough.tsx`, drawing with the page tours' overlay (`TourOverlay`, now exported from
  `components/tour.tsx`, so both look and place the bubble the same way). Across pages (navigates once per step,
  waits up to 4 s for the target, else skips the step in the direction of travel); a step on a page the role can't
  open is skipped; leaving the walkthrough's page by hand ends it; page tours don't start by themselves while a
  walkthrough runs. **Try on WhatsApp**: the message, Copy, Try it on WhatsApp, "I've sent it"; with a `check`, reads
  the list route before and every 4 s, says "Got it. It's saved." and reloads the page's data so the next step shows
  the record. **Try here**: clicks pass through to the lit button; while the page's dialog is open the tour is a
  small Spark chip; when it closes, a new record moves on, none says "Nothing saved yet". **Take back** block: the
  WhatsApp words (Copy, Try it) and/or the dashboard way. On a read-only account, practice and take-back steps are
  skipped. Progress: `guide_seen` `/learn/<id>` on Done (not on Stop).
- **Guards**: the build check (`vite.config.ts`) covers walkthrough markers too, and fails when a step's `page` is
  not a built page in `module-map.ts`; `test_module_map_whatsapp.py` checks each walkthrough practice / take-back
  names real WhatsApp-assistant tools that write.
- **First workflow** (to prove the engine end to end): *A delivery, from site to stock*: WhatsApp delivery with
  check → it in Movements → take back on WhatsApp (`undo_receipt`, the receipts card label "Take back delivery";
  SOP.md has no fixed words, the model maps "take back") → Record delivery here → Correct to take it back → Record
  use. It is W2's second half; SS-43 writes W1, W2 in full and W4 and the first role paths.
- **Not done here**: lighting up the new record itself on the page ("Got it" reloads the list but does not point at
  the row); W1's take-back (a site update has no WhatsApp undo, and the Site log has no undo button: work entries
  can only be voided from the old Activities page, which now redirects; SS-43 must settle this before writing W1).
