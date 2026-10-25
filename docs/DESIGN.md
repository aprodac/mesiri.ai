# Mesiri Dashboard — Design Rules

> The rules every dashboard page follows. Short on purpose: if a rule is not
> here, copy what the **Site DPR** and **Project DPR** pages do
> (`apps/dashboard/src/pages/SiteDayPage.tsx`, `ProjectDayPage.tsx`) — they
> are the reference pages (tracker WEB-25).
>
> Replaces `docs/DESIGN_SYSTEM.md` for the web dashboard. That document is a
> wider wish-list (mobile, libraries we do not use, a lime accent we do not
> ship) and no longer describes the product.

---

## 0. Pages and routes (V1, WEB-21; sorted to 11 entries, WEB-33)

V1 is one loop — sites send updates on WhatsApp, the engineer confirms, the
owner gets the DPR — plus setup. The sidebar has no "More", and **one entry
per subject**: a subject with several ways of looking at it is one page with
a view switch (`Segmented`), not several sidebar entries.

| Sidebar | Address | What it is |
|---|---|---|
| **Today** | `/today` | what's in, what's missing, what needs me |
| **Reports** | `/reports` | every DPR, newest first |
| | `/reports/:date/sites/:id` | one site's day: review, confirm, approve; Review / Document |
| | `/reports/:date/projects/:id` | one project's DPR: preview, send; Review / Document |
| **Issues** | `/issues` | what's stuck |
| *Site records* **Site log** | `/site-log` (`?view=photos`, `?view=all`) | Work · Photos · Everything (was Activities, Gallery, Timeline) |
| **Analytics** | `/analytics` | trends |
| **Labour** (module) | `/labour` (`?view=workers`) | Attendance · Workers (was 7 pages, WEB-22) |
| **Materials** (module) | `/materials` | Ledger · Catalogue; Stock now panel (WEB-30) |
| *Setup* **Projects & Sites** | `/projects`, `/projects/:id` | |
| **Team** | `/team`, `/team/:id` | |
| **Company** | `/company` | details, letterhead |
| **WhatsApp** | `/whatsapp` (`?view=messages`, `?view=automations`) | Conversations · All messages · Automations (module) (was WhatsApp Inbox, Automations, Company > messages) |
| Finance | `/finance/...` | only when the company has the module |

Rules:
- One address per thing, named as the sidebar names it. No section prefixes
  (`/operations/...`).
- A report's address is its date and site, not "today".
- A page outside V1 is removed, not hidden under "More". A module a
  company has not bought is hidden by the module switch (WEB-02).
- Moving a page means a redirect from the old address (`App.tsx`, "Old
  addresses"); unknown addresses land on Today.
- No "coming soon" placeholder pages.

---

## 1. Who we design for

A site engineer or owner, often on a phone, often outdoors, with five minutes.
Every screen answers three questions, in this order:

1. **What state is this in?** (draft, confirmed, sent, stuck)
2. **What needs me?** (the one thing to do next)
3. **What are the numbers?** (workers, work, materials, issues)

If a screen makes the reader hunt for any of those, it is wrong.

---

## 2. The page

- **White ground.** `--background` is `#ffffff`. No beige, no grey page
  behind white cards.
- **One page, not a stack of cards.** A page is a header, then flat
  **sections** separated by a thin rule (`border-t`). Do not wrap every
  section in its own bordered, shadowed card.
- **Borders only where they group.** Use a bordered box only for: the
  stat strip, the side column, tables, and callouts. Nothing else.
- **Side column for "settings of this thing".** Forms and history that
  are not the main job (day conditions, versions, PDF) go in a right-hand
  column, 300px, sticky on desktop; it drops under the page on phones.
  `DprAside` does this.
- **Width:** `max-w-6xl`; side column 300px.

### Page header (every detail page)

```
← Today / Site DPR · Green Villa                         (muted, small)
Tower 1  [Collecting]  Sat, Oct 24, 2026      [Primary action]
( ✓ Updates from site ── ② Engineer confirms ── 3 Sent to owner )   one slim bar
```

### Density: less scrolling

Empty space costs a scroll on a phone. The Site DPR page fits on one laptop
screen; keep new pages to that standard.

- **Don't pad twice.** `AppLayout` already pads every page by 16px; a page
  adds no top padding of its own (`pb-4 sm:px-2` only).
- **Header in three short lines:** back link + breadcrumb on one line;
  title, status chip and date on one line, with the primary action on the
  same row (`DprHeader`).
- **Steps in one slim bar** (`DprSteps`), with short labels on phones
  ("Updates · Confirm · Sent").
- **An empty section is one line**: its header plus "None reported" beside
  the title. No body, no separate "No items" paragraph.
- **Spacing scale:** page gap `gap-4`; sections `py-4` (`py-3` when
  empty); list rows `py-2`; table cells `py-1.5`; side column `p-4`.
- **Don't repeat information.** If a row already says "24 workers · mason 8,
  helper 12", don't add a summary line above it saying the same.
- **Phones:** stat strip stays one row; callouts show their first sentence;
  row actions sit beside the text unless a quantity or Confirm button needs
  the line.

---

## 3. Visual cues (the important part)

Colour is for **meaning only**. Each meaning has one colour, everywhere.

| Meaning | Token | Looks like | Use for |
|---|---|---|---|
| Needs action / draft | `draft` / `draft-soft` | orange | drafts, "to confirm", missing |
| Done / confirmed / sent | `success` / `success-soft` | green | confirmed items, approved, sent |
| In progress / info | `info` / `info-soft` | blue | collecting, sending, medium severity |
| Bad / critical | `destructive` | red | critical issues, over stock, remove |
| AI | `ai` / `ai-soft` | indigo | AI summary, "what the AI read" |
| Neutral | `muted` | grey | no updates, not reported, low severity |
| Primary action | `primary` | site orange `#c2410c` | **one** main button per page |

Rules:

- **Status icon on every reviewable row**, left side:
  `CircleDashed` orange = draft (not yet confirmed); `CircleCheck` green =
  confirmed / in the report. A reader scanning the left edge knows the state
  of the whole page.
- **Draft rows are tinted** (`bg-draft-soft/40`) so unconfirmed work stands
  out without reading.
- **Progress steps** (`DprSteps`) on every page about something with a
  life cycle: *Updates in → Engineer confirms → Sent*. Done = green tick,
  current = orange with a halo, to-do = grey outline.
- **Callout** (`Callout`) for the one sentence that needs the reader:
  orange for "to do", green for "done", grey for information. At most one or
  two per page; never stack four.
- **Severity chips** come from `severityChip()` in `lib/site-day.ts`:
  Critical red, High orange, Medium blue, Low grey. Do not invent others.
- **Status chips** come from `siteStatus()` in `lib/site-day.ts` and use
  the `CHIP` class. Same label, same colour on every page.
- **Numbers that need attention get coloured**: a count of open issues is
  orange (red if any are high/critical); "0 of 2 sites" is orange.

---

### Sidebar and top bar (WEB-20)

- **Sidebar icons are coloured, nothing else is.** Each item has its own
  icon colour (Today orange, Daily Reports blue, Issues red, Projects green,
  Team violet, Company amber, WhatsApp green, and the More sections as
  before). No coloured tiles or backgrounds behind them: that was tried and
  rejected (24 Oct). These are identity colours, so palette classes are
  allowed in `app-sidebar.tsx` only.
- **Live counts as badges:** Today shows drafts still to confirm (orange),
  Issues shows open issues (red); a dot on the icon when collapsed.
  `lib/nav-counts.ts`, sharing the Today page's query.
- **Top bar** stays on screen while scrolling; a 3px orange→yellow stripe on
  top; the scope picker's icon is coloured by level (all projects blue, a
  project green, a site orange); on the right, today's date with the drafts
  count, and the open-issues button with its count.

### Charts (WEB-24, Analytics)

Follow the dataviz method: pick the form first, colour last, and **run the
validator** on any multi-colour palette instead of judging by eye.

- **One series = one hue**: `--chart-2` (navy; light blue in dark mode).
  Thin bars, 4px rounded top, horizontal gridlines only, axes muted.
- **Issue severity in charts** is an *ordinal* one-hue ramp, not four
  hues: `--sev-critical`, `--sev-high`, `--sev-medium`, `--sev-low`
  (validated `--ordinal`, light and dark; darker = worse on white, brighter =
  worse on dark). The text chips elsewhere keep `severityChip()`.
- Every chart has a **tooltip** on each mark and a **Table** view of the same
  numbers (the accessible view); a stacked chart has a legend.
- Figures come from the server, aggregated over the whole range — never the
  first page of a list counted in the browser. No sparkline or trend that is
  not real data.

## 4. Numbers

- **Stat strip** (`StatStrip`): 3–5 key numbers in **one** bordered strip
  with dividers — not one card per number. 2×2 grid on phones.
- `tabular-nums` on every number that sits in a column or strip.
- Show `—` for zero/empty in stats and tables, not `0`.
- Quantities are shown with their unit, bold, right side of the row:
  **180 sqm**.
- Money: `₹1,20,000` (`en-IN` grouping), no decimals.

---

## 5. Rows and actions

- A list row is: status icon · title (medium weight) · chips · muted detail
  underneath · value on the right · actions on the far right.
- **Do not repeat yourself.** If the description equals the title, show it
  once.
- **Secondary actions are icon buttons** (ghost, `size-8`, muted, with
  `title` + `aria-label`): sources, edit, remove. Remove turns red on hover.
- **The one action that moves the item forward is a real button** with a
  label: *Confirm*, *Review*, *Approve and send*, *Send now*.
- One primary (filled orange) button per header. Inside lists, the filled
  button appears only on rows that need action (drafts); the rest are
  outline.
- Tables: header row on `bg-muted/50`, small muted header text, rows split
  by `border-t`, wrapped in a rounded border. On phones, prefer stacking the
  numbers under the name over horizontal scrolling.

---

## 6. Type

- **IBM Plex Sans** everywhere.
- Page title `text-2xl font-semibold tracking-tight`; section title
  `text-[15px] font-semibold`; body `text-sm`; meta `text-xs text-muted-foreground`.
- Weights: 400 body, 500 row titles, 600 headings and numbers. Avoid 700+.
- **No monospace for numbers or labels** in the UI, and **no ALL-CAPS
  tracking-wide labels** — both read as a developer template.
- Sentence case for everything ("Day conditions", not "Day Conditions").

---

## 7. Words

- Plain words a site engineer uses: *work done, labour, materials, issues,
  confirm, send*. No internal terms (no "fact", "payload", "tenant",
  "module", role codes, IDs).
- Say what happens next: "Approving the day confirms them all", "Sends by
  9:00 pm".
- Empty states say what will appear and when: "Issues show here once a site
  is confirmed."

---

## 8. Phone

- Design at 390px first for the daily pages (Today, Site DPR, Project DPR).
- The primary action is reachable without scrolling past content.
- Touch targets ≥ 32px; primary buttons `h-11`.
- Steps go vertical; the stat strip becomes 2×2; table columns collapse into
  a line under the name.

---

## 9. Dark mode

Every colour comes from a token in `apps/dashboard/src/index.css`, which
has a `.dark` set. **Never hard-code a palette class** (`text-emerald-600`,
`bg-blue-50`, hex values) in a page: use `success`, `draft`, `info`, `ai`,
`destructive`, `muted`. That is what keeps light and dark both readable,
and lets the whole product be re-themed from one file.

---

## 10. Building blocks

| Need | Use | File |
|---|---|---|
| Section with icon + title + count | `DprSection` | `components/dpr-page.tsx` |
| Key numbers | `StatStrip` | `components/dpr-page.tsx` |
| Life-cycle progress | `DprSteps` | `components/dpr-page.tsx` |
| The one sentence that needs attention | `Callout` | `components/dpr-page.tsx` |
| Side column | `DprAside` | `components/dpr-page.tsx` |
| AI summary | `DprSummaryCard` | `components/dpr-summary-card.tsx` |
| Versions + PDF | `DprVersionsCard` | `components/dpr-versions-card.tsx` |
| The DPR as a page of paper, live | `DprDocument`, `DprViewToggle` | `components/dpr-document.tsx` |
| Status / severity chips | `siteStatus`, `severityChip`, `CHIP` | `lib/site-day.ts` |
| Buttons, inputs, dialogs, sheets | shadcn/ui | `components/ui/*` |

Reuse these before writing new ones. If a page needs something new twice,
add it here and to this table.

---

## 10a. The DPR document (WEB-27)

The DPR the owner receives is a PDF. The Site DPR and Project DPR pages show
it **as that PDF**, live, under a **Review | Document** switch (`?view=document`).

- **One template, two uses.** The page shows the HTML the PDF is printed from
  (`apps/whatsapp-assistant/src/channel/dpr_document/template.py`), served by
  `GET /dpr/site-days/{id}/document` and `GET /dpr/project-days/{id}/document`.
  Never rebuild the document in React: the page and the PDF must not drift.
- **Live.** A day that is not confirmed re-reads every 30 seconds
  (`LIVE_REFRESH_MS`); its code line reads "Live preview · not confirmed yet"
  (project: "Preview · not sent yet"). Once confirmed or sent it shows the
  report's code and stops refreshing. The review data on the page refreshes on
  the same 30 seconds.
- **Safe.** Shown in a sandboxed frame without scripts; the template escapes
  every value (BE-36).
- **Print / PDF.** Print works on any day (the browser's own PDF). The stored
  PDF button appears only once confirmed: a draft's stored PDF is older than
  the live page.

The template's look:

| Part | Rule |
|---|---|
| Letterhead band | Logo + company (brand colour) left; "Site report / Daily Progress Report / code" right; 3px brand rule under it |
| Project block | Project · Site · Date (said as people say it) · Client, one bordered row |
| Day in figures | Tinted tiles; open issues and hours lost turn red only when non-zero; "Not set" greyed |
| Sections | Numbered (1 Work done, 2 Manpower, 3 Materials, 4 Site Issues, 5 Tomorrow's Plan, Late entries); counts on the right |
| Tables | Tinted header, zebra rows, numbers right-aligned, total row for several trades; header repeats on every page, rows never split |
| Status / severity | Pills: green done, amber in progress, red stopped/open, grey planned; severity critical/high in red |
| Values | `5th Floor` not `5Th Floor`; `180 sqm` not `180.000 sqm —`; cost as `₹14,400`, hidden when zero |

---

## 10b. Basics every page must have (WEB-26)

What anyone expects from software. Checked on Site DPR, Project DPR,
Activities, Gallery and Timeline on 24 Oct; every page reworked later must
pass the same.

| Basic | How |
|---|---|
| Its own browser tab title | Default per route in `lib/page-title.ts`; a page about one thing names it: `usePageTitle('Tower 1 · Site DPR')` |
| Filters and search survive Back, refresh and a shared link | Keep them in the address with `useUrlState('q', '')` (`lib/url-state.ts`). Several keys at once (Clear filters) = one `setSearchParams` call |
| Loading looks like the page, not a line of text | Skeletons (`DprPageSkeleton`, row/tile skeletons) |
| A failure says what failed, with **Try again** and a way out | `PageError` (full page) or a `Callout` with a Try again action (list pages). Never show "nothing here" when the request failed |
| An empty page says what will appear and when; with filters on, offers Clear | Dashed box with icon, one line, one action |
| Long lists don't load everything | "Load more" (Gallery, Timeline) |
| Every button does something | No buttons that only show a toast ("Exporting…") — build it or remove it |
| Keyboard | "Skip to content" link (AppLayout); visible focus; toggles have `aria-pressed`; icon buttons have `aria-label` + `title`; viewers take ← / → |
| Phone | Header actions stay on the title row; nothing wider than the screen |
| Dark mode | Colours from tokens only |
| Destructive actions ask first and say what happens | Remove dialogs with a reason |
| Plain words, no internal terms | "This page isn't available", not "Invalid Scope Context" |

## 11. Checklist before pushing a page

- [ ] White ground; no card-per-section stack.
- [ ] Main content fits on one laptop screen where it can; no double padding, empty sections are one line.
- [ ] State visible at a glance (status chip + row icons + steps if it has a life cycle).
- [ ] Exactly one primary button in the header.
- [ ] No hard-coded palette colours, no monospace, no ALL-CAPS labels.
- [ ] Passes "Basics every page must have" (10b).
- [ ] Checked at 1440px and 390px, light and dark.

---

## Status of pages

| Page | Follows these rules |
|---|---|
| Site DPR, Project DPR | Yes (WEB-25); Document view (WEB-27) |
| Today, Reports, Issues | Yes (WEB-25 step 3) |
| Activities, Gallery, Timeline, Analytics | Yes (WEB-24, WEB-26) |
| Projects & Sites, a project, Team, a person, Company | Yes (WEB-28): one page each, sections instead of tabs |
| Site log (Work, Photos, Everything), WhatsApp (Conversations, All messages, Automations) | Yes (WEB-33, WEB-35): Conversations and Automations redone; All messages keeps its older look |
| Labour (one page: Attendance, Workers) | Yes (WEB-22) |
| Materials (Ledger, Catalogue, Stock now, sheets) | Yes (WEB-29, WEB-30, invoice sheet WEB-35) |
| Sign in, Start a free trial | Yes (WEB-35): `components/auth/auth-shell.tsx` |
| Finance | No — old template look (module, off by default) |
| Dialogs (project, site, person, access, WhatsApp number, record delivery / use / move, correction) | Yes (WEB-29): sentence case, plain words, no fake buttons |

### WhatsApp chat, Automations, sign in (WEB-35)

- **Conversations** is a chat, not a monitoring console: the person's
  messages on the left (white), Mesiri's replies on the right (green, headed
  "Mesiri"), a pill per day, the site each update was filed to, and a red
  sentence under a message Mesiri could not handle (`ERROR_WORDS`; the code
  is in the tooltip). No guessed "intent" badges and no side panel: who the
  person is sits in the thread header with **Profile** or **Add to team**.
  The open thread is in the address (`?with=<number>`); on phones the list
  and the thread are one screen each, with Back.
- **Automations** read as sentences ("Every day at 6:00 pm, send the DPR to
  me"), with On / Paused, the site and when it last ran, and words for
  buttons (History, Pause, Delete). The form picks people and roles from
  lists; History is a side panel with skip reasons in words.
- **Sign in / Start a free trial** share `AuthShell`: on wide screens a dark
  panel (the sidebar colour) shows a WhatsApp message turning into a DPR
  line; the form sits on white. Signup says "Step 1 of 2". Only the look
  changed; the forms and their calls are the same.

### Setup pages (WEB-28)

- **One page, no tabs.** A project, a person and the company each fit on one
  page of sections (`DprSection`), with a side column for details. Old
  `?tab=` links scroll to the matching section (`id` on `DprSection`).
- **Rows say what matters for Mesiri to work**: a project's sites, people and
  cutoff; a person's projects and WhatsApp number. What is missing is in the
  draft (orange) colour: "No sites yet", "No projects yet", "No WhatsApp
  number" — with a callout and the action that fixes it.
- **Who reaches what comes from `project_members`**, the table access is
  checked against (`lib/team.ts useMemberships`), not `users.access_policy`,
  which goes stale when someone is added from a project page. Admins show
  "All projects" (their role reaches every project).
- **Destructive actions confirm in a dialog** that says what is kept
  (archive, deactivate, delete, remove from project); never `confirm()` or
  `alert()`.
- **Removed:** count tiles, grid/list toggles, bulk select and bulk delete on
  Team, placeholder tabs (project "WhatsApp", person "Activity"), the fake
  "Delete project" button, "Technical Infrastructure Claims", the unused
  "Required report types" checklist (nothing read it; its stored value is
  kept on save).

### Materials (WEB-29, ledger WEB-30)

- **Two views: Ledger and Catalogue.** The Ledger is the page: every
  delivery, use, move between sites and correction in one table, newest
  first, filtered by material, site, dates and In / Out (all in the
  address). **In is green, Out is red**, each in its own tinted column.
- **Pick a material** and the table becomes its stock book: a "Stock
  after" column (per site, from the material's whole history, so it is
  right whatever the dates) and a totals row (in, out, net, spent).
- **Phones** get one line per entry with the quantity in green or red on
  the right and "left N" under it, instead of a table cut off at the side.
- **Stock now** (what each site holds) opens in a side panel; a stock row
  opens that material's stock book for the site.
- **CSV** downloads exactly the lines shown.
- Words for reasons live in `lib/materials.ts REASON_WORDS`; moves read
  "Moved to Block B" / "Moved from Block A". Never show the codes.
- **No bulk actions.** Corrections are one at a time from an entry.
