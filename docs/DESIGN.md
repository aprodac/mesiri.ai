# Mesiri Dashboard — Design Rules

> The rules every dashboard page follows. Short on purpose: if a rule is not
> here, copy what the **Site DPR** and **Project DPR** pages do
> (`apps/dashboard/src/pages/SiteDayPage.tsx`, `ProjectDayPage.tsx`) — they
> are the reference pages (tracker WEB-19).
>
> Replaces `docs/DESIGN_SYSTEM.md` for the web dashboard. That document is a
> wider wish-list (mobile, libraries we do not use, a lime accent we do not
> ship) and no longer describes the product.

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
  column, 320px, sticky on desktop; it drops under the page on phones.
  `DprAside` does this.
- **Width:** `max-w-6xl`, padding `p-4` on phones, `p-8` from `sm`.

### Page header (every detail page)

```
← Back link                                   (muted, small)
Kind of page · parent                        (muted, small)   e.g. "Site DPR · Green Villa"
Big name  [status chip]                      (text-3xl semibold)
Date / subtitle                              (muted)
                                  [Primary action]  ← right on desktop, below on phone
1 ─── 2 ─── 3   progress steps (where this item is in its life)
```

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
- Page title `text-3xl font-semibold tracking-tight`; section title
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
| Status / severity chips | `siteStatus`, `severityChip`, `CHIP` | `lib/site-day.ts` |
| Buttons, inputs, dialogs, sheets | shadcn/ui | `components/ui/*` |

Reuse these before writing new ones. If a page needs something new twice,
add it here and to this table.

---

## 11. Checklist before pushing a page

- [ ] White ground; no card-per-section stack.
- [ ] State visible at a glance (status chip + row icons + steps if it has a life cycle).
- [ ] Exactly one primary button in the header.
- [ ] No hard-coded palette colours, no monospace, no ALL-CAPS labels.
- [ ] Checked at 1440px and 390px, light and dark.

---

## Status of pages

| Page | Follows these rules |
|---|---|
| Site DPR, Project DPR | Yes (WEB-19) |
| Today, Daily Reports, Issues | Mostly (WEB-01/03/06/07 style); not yet moved to sections/steps |
| Projects, Team, Company, Labour, Materials, others | No — old template look; to be reworked page by page |
