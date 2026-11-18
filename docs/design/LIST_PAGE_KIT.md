# The list page kit: how to build or upgrade a page

> UX-45, 18 Nov 2026. Written so a page in any module (Planning next) can be brought to the standard of
> Cost control by following this file alone. The rules of the whole app are in [DESIGN.md](../DESIGN.md);
> this file is the recipe for pages that show **a list of things with figures and states**.
>
> **Reference page:** `apps/dashboard/src/pages/CostMaterialsPage.tsx` (Materials vs BOQ) uses every part.
> The other Cost control pages (`CostHomePage`, `CostVariancePage`, `CostBudgetPage`, `CostCentresPage`) are built
> from the same parts. Read one before starting.

---

## 1. The idea in one line

**Colour and shape first, words last.** A person should see what is wrong, how much, and what to do about it
before reading a sentence. Every sentence that only repeats what a colour, a bar or a figure already says is cut.

---

## 2. The shape of a list page (top to bottom)

| # | Block | Part | When |
|---|---|---|---|
| 1 | Header: title, the period or project, one primary action, Excel | `DprHeader` / `PageHeader`, `ActionButton` | Always |
| 2 | Key figures | `KpiStrip` | Always; 3 to 5 figures |
| 3 | What needs a person | `ActionChip` (one line each, two side by side on a laptop) | Only when something does |
| 4 | Notes on the figures (what they leave out) | `NoteChip` | Only when there are any |
| 5 | The split by state, which also filters | `StateBar` (+ `ToggleChip`) | When rows have a state (red / amber / green, a stage, a status) |
| 6 | Search, filters, sort, view, export | `ListToolbar` *or* the `right` slot of `StateBar` | Always for a list |
| 7 | The rows | A white table (`bg-card`) or `NumbersTable` | Always |
| 8 | Pages | `Pager` with `usePagedUrl` / `useServerPage` | Always (it hides itself under one page) |
| 9 | What the colours mean | `Legend` | When colours carry a meaning |

Everything sits on the sand ground; every box (strip, chips, table) is white (`bg-card`) with a border.

---

## 3. The parts

Import every part from the page kit: `import { … } from '@/components/page/page-kit'`.

### Figures

| Part | Use it for | Notes |
|---|---|---|
| `KpiStrip` | The page's 3 to 5 key figures | `tone` = state (`good`, `attention`, `bad`, `info`); `of` draws "x of y" as segments; `share` (0 to 1) a bar; `hint` a few words, or a change against before (`▲ ₹13,000 vs before`, green when better, red when worse). An icon per figure (`kind` or `icon`). |
| `Pill` | A row's state as a word or figure: "₹3.6 L over", "Enough", "Too early" | `tone`, `icon`, `size="xs"` in tables |
| `ReasonChip` | *Why* a row is its state, in 2 to 5 words, with its fix as a link | Full sentence in `title` (hover). `fix={{ to, label }}`: "Set the rate →", "Record use →". |

### Things to do and notes

| Part | Use it for | Notes |
|---|---|---|
| `ActionChip` | Something a person should do: "**9** BOQ lines have no materials set · not counted here → Set them" | Figure in bold, a few words, grey context after `·`, one verb as the link. Replaces a `Callout` paragraph. |
| `NoteChip` | What the figures leave out: "**₹84,200** GST left out: it can be claimed back" | `tone="attention"` + `to` when it can be fixed; grey when it is only information. |

### Filtering and finding

| Part | Use it for | Notes |
|---|---|---|
| `StateBar` | How the rows split by state, one bar, a chip per state that filters | `items` = `{ value, label, count, icon, tone }`; `extra` for a `ToggleChip`; `right` for the toolbar items. |
| `ToggleChip` | A dashed chip for "rows needing something": "**3** need a fix", "**8** short to finish" | Hides itself at 0. |
| `ListToolbar` | The row of search, filters and sort when there is no `StateBar` | `right` sits at the end (sort, view, export). |
| `SearchBox` | Search | **"/" jumps to it, Esc clears.** One per page (`slash={false}` on a second). |
| `FilterPill` | A filter with options and counts (section, supplier, centre) | From `components/requests/parts`. Options carry `count`, and `dot` / `swatch` for colour. |
| `SortSelect` | The page's own orders: "Worst first", "Most spent", "Name" | First option = the default order. |
| `ClearButton` | Clears every filter and the search | Shown only while one is on. |
| `NoMatch` | Filters left nothing | "No *material* matches" + Clear filters. An empty page with no filters is `EmptyState`. |

### Viewing and moving through rows

| Part | Use it for | Notes |
|---|---|---|
| `ShowSwitch` + `useShowMode('page-key')` | Bars (a glance) or Numbers (every figure in its own column) | Kept in `?show=`, remembered per page in the browser. Use it when a row has more than ~4 figures. |
| `NumbersTable` + `useColumnSort()` + `sortByColumn()` | The Numbers view | First column (the name) stays put while figures scroll; any header sorts (biggest first, then the other way, then back); blanks always last; a fade shows more columns off screen; `onOpen` opens the row's page. |
| `Pager` + `usePagedUrl(rows)` | Lists the page already has | 25 a page (50, 100 offered); `?page=` in the address; back to page 1 when a person changes a filter. |
| `Pager` + `useServerPage({ size })` | Lists the server pages (`limit` / `offset`) | `server.pager(total, rows.length)`. Never "Load more". |
| `BulkBar` | Rows ticked with checkboxes: "**2** picked · Move to [ ] · Clear" | Only when an action applies to many rows at once. |
| `ActionButton kind="export-excel"` | Export | Exports **what is shown** (filters and sort applied): label "Export shown" when filtered. |

### Hooks and tables in `lib/`

| What | File |
|---|---|
| A filter in the address: `useUrlState('q', '')` | `lib/url-state.ts` |
| Several address changes at once: `updateParams(setParams, p => …)` | `lib/url-state.ts` |
| Paging: `usePagedUrl`, `useServerPage`, `PAGE_SIZES` | `lib/paging.ts` |
| Bars / Numbers, column sort: `useShowMode`, `useColumnSort`, `sortByColumn` | `lib/numbers-view.ts` |
| Tones (`good`, `attention`, `bad`, `info`, `muted`) and "/" focus: `TONE`, `useSlashFocus` | `lib/list-kit.ts` |
| Cost colours → tones: `COLOUR_TONE`, `COLOUR_DOT`, `COLOUR_TEXT` | `lib/cost-colours.ts` |
| A module's own colours (cost centres, materials …): one table per module | e.g. `CENTRE_COLOURS` in `lib/cost.ts` |
| Today's date: `appNow()` (never `new Date()` / `Date.now()`: the sample company has its own clock) | `lib/clock.ts` |

---

## 4. Rules

**Colour**
- One meaning per colour, everywhere: **green** good / within, **amber** watch / within 10%, **red** over / short /
  late, **blue** work done or earned (data, not a state), **grey** not judged / not known. Never a made-up colour
  for "no data": grey and a reason.
- Colours come from tokens and the tone table (`TONE`, `COLOUR_TONE`), never raw palette classes on a page
  (`bg-red-500`). A module's own category colours live in one table in `lib/` (like `CENTRE_COLOURS`).
- A state shows in three places at most: the row's colour edge, a pill or icon, and the figure's colour.

**Words**
- Cut any sentence a cue already says. Long explanations go in `title` (hover) or the page's help, not on the page.
- Chips: the figure in **bold**, then 2 to 6 words, then grey context after `·`.
- A fix is a verb: "Set the rate", "Record use", "Put on lines".
- Sentence case. No ALL-CAPS labels. No internal words.

**Figures**
- Large figures in the KPI strip use `compact` (₹33 L, ₹1.2 Cr); exact figures (`formatRupees`) in the Numbers
  view and exports.
- Show `—` for "not there", `0` (grey) for a real zero.
- A change against before: same number of days just before the period, ▲ / ▼, green when better.

**Behaviour (the software basics)**
- Search, filters, sort, page and view live in the address (`useUrlState`), so Back, refresh and a shared link keep
  them. Clear removes them all at once.
- Every list has pages. Every list can be exported as shown. Every row that has a page opens it on click.
- "/" focuses search; Esc clears it. Headers that sort say so (`aria-sort`).
- Loading looks like the page (skeletons); a failure says what failed with Try again; an empty page says what will
  appear; filters with no result say "No x matches" with Clear.
- Phones (390 px): nothing wider than the screen. Table columns fold under the name (`hidden md:table-cell` and a
  line `md:hidden` under the name), or the Numbers table scrolls with the name fixed.
- Roles: hide what a role must not see (money for a site engineer) in the columns, sorts and exports too.

**Tours** (see [LEARN_AND_TOURS.md](../engineering/LEARN_AND_TOURS.md))
- Keep every `data-guide` marker a tour points at; a new block gets one (`StateBar guide=…`).
- When the page changes enough, reword its steps in `lib/tours.ts` and raise the tour's `version`.

---

## 5. A page skeleton to copy

```tsx
import * as React from 'react'
import { useQuery } from '@tanstack/react-query'
import { CircleCheck, CircleDashed, Eye, TriangleAlert, Wrench } from 'lucide-react'
import {
  ActionButton, ActionChip, ClearButton, KpiStrip, Legend, NoMatch, NumbersTable, Pager, Pill, ReasonChip, SearchBox, ShowSwitch,
  SortSelect, StateBar, ToggleChip, type NumberColumn,
} from '@/components/page/page-kit'
import { DprHeader, DprSection } from '@/components/dpr-page'
import { usePagedUrl } from '@/lib/paging'
import { sortByColumn, useColumnSort, useShowMode } from '@/lib/numbers-view'
import { useUrlState } from '@/lib/url-state'
import { exportCsv } from '@/lib/export'

type Row = { id: string; name: string; state: 'red' | 'amber' | 'green' | 'grey'; /* … figures … */ }
const STATES = [
  { value: 'red', label: 'Late', icon: TriangleAlert, tone: 'bad' as const },
  { value: 'amber', label: 'Watch', icon: Eye, tone: 'attention' as const },
  { value: 'green', label: 'On time', icon: CircleCheck, tone: 'good' as const },
  { value: 'grey', label: 'Not started', icon: CircleDashed, tone: 'muted' as const },
]
const SORTS = [{ value: '', label: 'Worst first' }, { value: 'name', label: 'Name' }]
const NAME: NumberColumn<Row> = { key: 'name', label: 'Task', sortValue: (r) => r.name.toLowerCase(), cell: (r) => r.name }
const COLUMNS: NumberColumn<Row>[] = [/* one per figure: { key, label, sortValue, cell, tone } */]

export default function ExamplePage() {
  const q = useQuery({ queryKey: ['example'], queryFn: fetchExample })
  const [search, setSearch] = useUrlState<string>('q', '')
  const [state, setState] = useUrlState<string>('state', '')
  const [sort, setSort] = useUrlState<string>('sort', '')
  const [show, setShow] = useShowMode('example')
  const { col, dir, onSort, clear: clearCol } = useColumnSort()

  const rows = q.data?.rows ?? []
  const listed = React.useMemo(() => {
    const out = rows.filter((r) => (!state || r.state === state) && (!search || r.name.toLowerCase().includes(search.toLowerCase())))
    return (show === 'numbers' && sortByColumn(out, [NAME, ...COLUMNS], col, dir)) || out /* or the SORTS order */
  }, [rows, state, search, show, col, dir])
  const paged = usePagedUrl(listed)            // hooks before any early return
  const any = !!(search || state)
  const clear = () => { setSearch(''); setState('') }

  return (
    <div className="mx-auto flex w-full flex-col gap-4 pb-8 sm:px-2">
      <DprHeader title="Example" crumb="Module" />
      <KpiStrip stats={[/* 3 to 5 figures with tone, of / share, hint */]} />
      {/* <ActionChip icon={Wrench} to="/fix" action="Fix them"><b>3</b> tasks have no date</ActionChip> */}
      <DprSection icon={Wrench} title="Tasks" meta={any ? `${listed.length} of ${rows.length}` : rows.length}>
        <div className="mb-2">
          <StateBar
            items={STATES.map((s) => ({ ...s, count: rows.filter((r) => r.state === s.value).length }))}
            value={state}
            onChange={setState}
            right={
              <>
                <SearchBox value={search} onChange={setSearch} placeholder="Search tasks" size="sm" />
                <SortSelect value={sort} options={SORTS} onChange={(v) => { setSort(v); clearCol() }} size="sm" />
                <ClearButton show={any} onClick={clear} size="sm" />
                <ShowSwitch show={show} onShow={setShow} label="How to show the tasks" />
                <ActionButton kind="export-excel" size="sm" onClick={() => exportCsv('tasks.csv', [/* headers */], [/* listed rows */])} />
              </>
            }
          />
        </div>
        {listed.length === 0 ? (
          <NoMatch noun="task" onClear={clear} />
        ) : show === 'numbers' ? (
          <NumbersTable rows={paged.shown} rowKey={(r) => r.id} first={NAME} columns={COLUMNS} col={col} dir={dir} onSort={onSort} />
        ) : (
          <div className="overflow-hidden rounded-xl border bg-card">{/* the Bars table: colour edge, name, ReasonChip, bars, Pill */}</div>
        )}
        <Pager {...paged.pager} noun="tasks" className="mt-2" />
        <Legend className="mt-2" items={[{ tone: 'good', label: 'On time' }, { tone: 'attention', label: 'Watch' }, { tone: 'bad', label: 'Late' }]} />
      </DprSection>
    </div>
  )
}
```

---

## 6. Upgrading an existing page, step by step

1. **Read it and its data type** (`lib/<module>.ts`), its tour (`lib/tours.ts`), and who may see what (roles).
2. **List every sentence on the page.** For each: is it a state (→ colour, pill, icon), a figure (→ KPI or column),
   a to-do (→ `ActionChip`), a note (→ `NoteChip`), or an explanation (→ `title` or help)? Delete repeats.
3. **Top:** `KpiStrip` with tones and a change against before where a period is chosen.
4. **States:** a `StateBar` if rows have one; a `ToggleChip` for "needs a fix".
5. **Toolbar:** `SearchBox`, `FilterPill`s, `SortSelect`, `ClearButton`, `ShowSwitch` (if many figures), export.
6. **Rows:** white table; colour edge; name; `ReasonChip` with its fix; bars for "x against y"; a `Pill` for the
   verdict. Row click opens the thing's page. Phone: fold columns under the name.
7. **Pages:** `usePagedUrl` or `useServerPage`. Never a list that stops at a fixed limit without saying so.
8. **Tour:** keep the markers, reword steps, raise `version`.
9. **Check** (below), then commit with a tracker row.

---

## 7. Checklist before pushing

- [ ] No sentence that a colour, bar or figure already says; long words only on hover or in help.
- [ ] Colours from tones / tokens only; green, amber, red, blue, grey mean the same as everywhere.
- [ ] KPI strip of 3 to 5 figures; things to do as `ActionChip`s.
- [ ] Search ("/" and Esc), filters with counts, sort, Clear, pages, export of what is shown.
- [ ] All of it in the address; Back and a shared link keep the view.
- [ ] A row opens its page; header sort says so; blanks sort last.
- [ ] Loading skeleton, error with Try again, empty state, "No x matches".
- [ ] Roles: nothing shown to a role that must not see it (columns, sorts, exports).
- [ ] 1440 px and 390 px, light and dark; nothing wider than a phone.
- [ ] `npx tsc -b --noEmit && npx oxlint src/ && npx vite build` and `node scripts/words.mjs` pass.
- [ ] Tour markers kept; steps reworded and `version` raised when the page changed.

---

## 8. Don't

- Don't write a new search box, sort menu, colour bar, chip or pager on a page: use the part, or add to the kit
  (`components/page/list-kit.tsx`) and to this file.
- Don't use `components/ui/bulk-action-bar.tsx` (old, monospace): use `BulkBar`.
- Don't use "Load more": use pages.
- Don't put two address changes in two separate `setSearchParams` calls: `useUrlState` setters and `updateParams`
  are safe together; a raw `setSearchParams` is not.
