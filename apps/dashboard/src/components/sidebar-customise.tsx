import * as React from 'react'
import { ArrowDown, ArrowUp, Check, CircleAlert, Eye, EyeOff, GripVertical, PanelLeft, Pin, Plus, RotateCcw, Search, X } from 'lucide-react'
import { Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Button } from '@/components/ui/button'
import type { NavSection } from '@/lib/module-map'
import { CUSTOMISE_EVENT as OPEN_EVENT, MAX_PINS, ROLE_NAMES, sectionTitle, usePinnable, useSidebarPrefs, type PinnablePage } from '@/lib/sidebar-prefs'
import { cn } from '@/lib/utils'
import { usePageUsage } from '@/lib/page-usage'

// UX-65: "Customise your sidebar". Two tabs: the pinned pages ("Your pages": add, drag or move, remove) and the
// sections (drag or move, show or hide). Every change shows in the sidebar behind the sheet at once and is saved on the
// person's account; "Back to the <role> sidebar" forgets their changes. Drag with a mouse; the arrows do the same from
// the keyboard or on a phone.


function move<T>(list: T[], from: number, to: number): T[] {
  if (to < 0 || to >= list.length || from === to) return list
  const next = [...list]
  const [item] = next.splice(from, 1)
  next.splice(to, 0, item)
  return next
}

export function SidebarCustomise() {
  const [open, setOpen] = React.useState(false)
  const [tab, setTab] = React.useState<'pages' | 'sections'>('pages')
  React.useEffect(() => {
    const onOpen = (e: Event) => {
      setTab(((e as CustomEvent).detail as 'pages' | 'sections') ?? 'pages')
      setOpen(true)
    }
    window.addEventListener(OPEN_EVENT, onOpen)
    return () => window.removeEventListener(OPEN_EVENT, onOpen)
  }, [])
  const sb = useSidebarPrefs()
  const { pages, byUrl, role } = usePinnable()
  const pinned = sb.prefs.pins.map((u) => byUrl.get(u)).filter((p): p is PinnablePage => !!p)
  const roleName = ROLE_NAMES[role] ?? 'your role'

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetContent side="right" className="w-full gap-0 p-0 sm:max-w-md" aria-describedby={undefined}>
        <SheetHeader className="border-b px-5 pt-5 pb-4">
          <div className="flex items-center gap-3">
            <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/15 text-primary-ink" aria-hidden>
              <PanelLeft className="size-[18px]" />
            </span>
            <div className="min-w-0">
              <SheetTitle className="text-base">Your sidebar</SheetTitle>
              <SheetDescription className="text-xs">Pin the pages you open most. Hide what you never use.</SheetDescription>
            </div>
          </div>
          <div className="mt-2 flex items-center gap-2 text-xs">
            <span className={cn('rounded-full px-2 py-0.5 font-medium', sb.custom ? 'bg-info-soft text-info' : 'bg-muted text-muted-foreground')}>
              {sb.custom ? 'Changed by you' : `The ${roleName} sidebar`}
            </span>
            <SaveState saving={sb.saving} failed={sb.failed} />
          </div>
        </SheetHeader>

        <Tabs value={tab} onValueChange={(v) => setTab(v as 'pages' | 'sections')} className="min-h-0 flex-1 gap-0">
          <div className="px-5 pt-3">
            <TabsList className="w-full">
              <TabsTrigger value="pages" className="flex-1">
                Pages <span className="ml-1 rounded-full bg-background/70 px-1.5 text-[11px] tabular-nums">{pinned.length}</span>
              </TabsTrigger>
              <TabsTrigger value="sections" className="flex-1">
                Sections
                {sb.prefs.hidden.length > 0 && <span className="ml-1 rounded-full bg-background/70 px-1.5 text-[11px] tabular-nums">{sb.prefs.hidden.length} hidden</span>}
              </TabsTrigger>
            </TabsList>
          </div>
          <TabsContent value="pages" className="min-h-0 flex-1 overflow-y-auto px-5 pt-3 pb-5">
            <PinnedList pinned={pinned} onChange={(urls) => sb.save({ ...sb.prefs, pins: urls })} />
            <AddPages pages={pages} pins={sb.prefs.pins} full={sb.full} onAdd={(url) => sb.save({ ...sb.prefs, pins: [...sb.prefs.pins, url] })} />
          </TabsContent>
          <TabsContent value="sections" className="min-h-0 flex-1 overflow-y-auto px-5 pt-3 pb-5">
            <SectionList
              order={sb.prefs.order}
              hidden={sb.prefs.hidden}
              pages={pages}
              onOrder={(order) => sb.save({ ...sb.prefs, order })}
              onToggle={(s) => sb.save({ ...sb.prefs, hidden: sb.prefs.hidden.includes(s) ? sb.prefs.hidden.filter((h) => h !== s) : [...sb.prefs.hidden, s] })}
            />
          </TabsContent>
        </Tabs>

        <SheetFooter className="flex-row items-center justify-between gap-2 border-t px-5 py-3">
          <Button variant="ghost" size="sm" className="gap-1.5 text-muted-foreground" disabled={!sb.custom || sb.saving} onClick={sb.reset}>
            <RotateCcw className="size-3.5" /> Back to the {roleName} sidebar
          </Button>
          <Button size="sm" onClick={() => setOpen(false)}>Done</Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  )
}

function SaveState({ saving, failed }: { saving: boolean; failed: boolean }) {
  if (saving) return <span className="text-muted-foreground">Saving…</span>
  if (failed)
    return (
      <span className="inline-flex items-center gap-1 text-destructive">
        <CircleAlert className="size-3.5" aria-hidden /> Not saved, try again
      </span>
    )
  return (
    <span className="inline-flex items-center gap-1 text-muted-foreground">
      <Check className="size-3.5 text-success" aria-hidden /> Saved to your account
    </span>
  )
}

/** Drag a row to another place (mouse), or use its arrows (keyboard, touch). */
function useDragOrder<T>(items: T[], onChange: (next: T[]) => void) {
  const [drag, setDrag] = React.useState<{ from: number; over: number } | null>(null)
  const rowProps = (i: number) => ({
    draggable: true,
    onDragStart: (e: React.DragEvent) => {
      e.dataTransfer.effectAllowed = 'move'
      e.dataTransfer.setData('text/plain', String(i))
      setDrag({ from: i, over: i })
    },
    onDragOver: (e: React.DragEvent) => {
      if (!drag) return
      e.preventDefault()
      if (drag.over !== i) setDrag({ ...drag, over: i })
    },
    onDrop: (e: React.DragEvent) => {
      e.preventDefault()
      if (drag) onChange(move(items, drag.from, drag.over))
      setDrag(null)
    },
    onDragEnd: () => setDrag(null),
  })
  const look = (i: number) =>
    cn(
      drag?.from === i && 'opacity-40',
      drag && drag.over === i && drag.from !== i && (drag.from < i ? 'shadow-[inset_0_-2px_0_0_var(--color-primary)]' : 'shadow-[inset_0_2px_0_0_var(--color-primary)]'),
    )
  return { rowProps, look, step: (i: number, by: number) => onChange(move(items, i, i + by)) }
}

function ArrowButtons({ i, n, name, step }: { i: number; n: number; name: string; step: (i: number, by: number) => void }) {
  return (
    <span className="flex shrink-0 items-center">
      <button type="button" className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-30" disabled={i === 0} onClick={() => step(i, -1)} aria-label={`Move ${name} up`} title="Move up">
        <ArrowUp className="size-3.5" />
      </button>
      <button type="button" className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-30" disabled={i === n - 1} onClick={() => step(i, 1)} aria-label={`Move ${name} down`} title="Move down">
        <ArrowDown className="size-3.5" />
      </button>
    </span>
  )
}

function PinnedList({ pinned, onChange }: { pinned: PinnablePage[]; onChange: (urls: string[]) => void }) {
  const urls = pinned.map((p) => p.url)
  const { rowProps, look, step } = useDragOrder(urls, onChange)
  return (
    <section aria-label="Your pages">
      <h3 className="mb-1.5 flex items-center justify-between text-[11px] font-semibold tracking-wider text-muted-foreground uppercase">
        Your pages
        <span className="font-medium tracking-normal normal-case tabular-nums">{pinned.length} of {MAX_PINS}</span>
      </h3>
      {pinned.length === 0 ? (
        <p className="flex items-center gap-2 rounded-lg border border-dashed px-3 py-4 text-sm text-muted-foreground">
          <Pin className="size-4 shrink-0" aria-hidden /> Nothing pinned yet. Add the pages you open every day.
        </p>
      ) : (
        <ul className="flex flex-col overflow-hidden rounded-lg border">
          {pinned.map((p, i) => (
            <li key={p.url} {...rowProps(i)} className={cn('group flex items-center gap-2 border-b bg-card px-2 py-1.5 last:border-b-0', look(i))} data-pin={p.url}>
              <GripVertical className="size-4 shrink-0 cursor-grab text-muted-foreground/60 active:cursor-grabbing" aria-hidden />
              <span className="flex size-7 shrink-0 items-center justify-center rounded-md bg-muted text-foreground/80" aria-hidden>
                <p.icon className="size-3.5" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium">{p.title}</span>
                <span className="block truncate text-[11px] text-muted-foreground">{where(p)}</span>
              </span>
              <ArrowButtons i={i} n={pinned.length} name={p.title} step={step} />
              <button type="button" className="rounded p-1 text-muted-foreground hover:bg-destructive/10 hover:text-destructive" onClick={() => onChange(urls.filter((u) => u !== p.url))} aria-label={`Unpin ${p.title}`} title="Unpin">
                <X className="size-3.5" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

/** Where a page lives in the sidebar, without saying a name twice ("Buy · Procurement", "Site"). */
function where(p: PinnablePage): string {
  const section = sectionTitle(p.section)
  return p.group.key === 'site' || p.group.flat || p.group.title === section ? section : `${section} · ${p.group.title}`
}

const SECTION_ORDER_FOR_LIST: NavSection[] = ['tasks', 'site', 'plan', 'buy', 'money']

function AddPages({ pages, pins, full, onAdd }: { pages: PinnablePage[]; pins: string[]; full: boolean; onAdd: (url: string) => void }) {
  const [q, setQ] = React.useState('')
  const words = q.trim().toLowerCase().split(/\s+/).filter(Boolean)
  const match = (p: PinnablePage) => {
    const hay = `${p.title} ${p.group.title} ${p.page.about}`.toLowerCase()
    return words.every((w) => hay.includes(w))
  }
  // UX-70: the pages this person opens most, not yet pinned, come first.
  const usage = usePageUsage()
  const most = words.length ? [] : usage.map((u) => pages.find((p) => p.url === u.url)).filter((p): p is PinnablePage => !!p && !pins.includes(p.url)).slice(0, 5)
  const groups: { s: NavSection | 'most'; rows: PinnablePage[] }[] = [
    ...(most.length ? [{ s: 'most' as const, rows: most }] : []),
    ...SECTION_ORDER_FOR_LIST.map((s) => ({ s, rows: pages.filter((p) => p.section === s && match(p)) })),
  ].filter((g) => g.rows.length > 0)
  return (
    <section aria-label="Add a page" className="mt-5">
      <h3 className="mb-1.5 text-[11px] font-semibold tracking-wider text-muted-foreground uppercase">Add a page</h3>
      <label className="flex h-9 items-center gap-2 rounded-lg border bg-background px-2.5 focus-within:ring-2 focus-within:ring-ring/40">
        <Search className="size-4 shrink-0 text-muted-foreground" aria-hidden />
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Find a page: stock, wages, RA bill…" className="min-w-0 flex-1 bg-transparent text-sm outline-none" aria-label="Find a page to pin" />
        {q && (
          <button type="button" onClick={() => setQ('')} className="rounded p-0.5 text-muted-foreground hover:text-foreground" aria-label="Clear">
            <X className="size-3.5" />
          </button>
        )}
      </label>
      {full && <p className="mt-2 rounded-lg bg-draft-soft px-3 py-2 text-xs text-draft">{MAX_PINS} pinned: unpin one to add another.</p>}
      {groups.length === 0 && <p className="mt-3 text-sm text-muted-foreground">No page matches “{q}”.</p>}
      {groups.map(({ s, rows }) => (
        <div key={s} className={cn('mt-3', s === 'most' && 'rounded-lg bg-primary/10 p-2')}>
          <div className="mb-1 text-xs font-semibold text-foreground/70">{s === 'most' ? 'You open most' : sectionTitle(s)}</div>
          <ul className="flex flex-col gap-0.5">
            {rows.map((p) => {
              const on = pins.includes(p.url)
              return (
                <li key={p.url}>
                  <button
                    type="button"
                    disabled={on || full}
                    onClick={() => onAdd(p.url)}
                    className={cn('group flex w-full items-center gap-2.5 rounded-lg px-2 py-1.5 text-left transition-colors', on ? 'cursor-default' : 'hover:bg-muted disabled:opacity-50')}
                    aria-label={on ? `${p.title}, pinned` : `Pin ${p.title}`}
                  >
                    <p.icon className="size-4 shrink-0 text-muted-foreground" aria-hidden />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm">{p.title}</span>
                      <span className="block truncate text-[11px] text-muted-foreground">{p.group.flat || p.group.key === 'site' ? sectionTitle(p.section) : p.group.title}</span>
                    </span>
                    {on ? (
                      <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-success-soft px-2 py-0.5 text-[11px] font-medium text-success">
                        <Check className="size-3" aria-hidden /> Pinned
                      </span>
                    ) : (
                      <span className="inline-flex shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium text-muted-foreground group-hover:border-primary group-hover:bg-primary group-hover:text-primary-foreground">
                        <Plus className="size-3" aria-hidden /> Pin
                      </span>
                    )}
                  </button>
                </li>
              )
            })}
          </ul>
        </div>
      ))}
    </section>
  )
}

function SectionList({ order, hidden, pages, onOrder, onToggle }: {
  order: NavSection[]
  hidden: NavSection[]
  pages: PinnablePage[]
  onOrder: (next: NavSection[]) => void
  onToggle: (s: NavSection) => void
}) {
  const { rowProps, look, step } = useDragOrder(order, onOrder)
  // What each section holds, as its modules' names, so "Buy" says "Procurement, Subcontract".
  const holds = (s: NavSection) => {
    const names = new Set(pages.filter((p) => p.section === s).map((p) => (p.group.key === 'site' || p.group.flat ? p.title : p.group.title)))
    return [...names]
  }
  const shown = order.filter((s) => holds(s).length > 0)
  return (
    <section aria-label="Sections">
      <p className="mb-2 text-xs text-muted-foreground">Drag to reorder. Hidden sections stay in search (Ctrl K).</p>
      <ul className="flex flex-col overflow-hidden rounded-lg border">
        {shown.map((s, i) => {
          const off = hidden.includes(s)
          const names = holds(s)
          return (
            <li key={s} {...rowProps(order.indexOf(s))} className={cn('flex items-center gap-2 border-b bg-card px-2 py-2 last:border-b-0', look(order.indexOf(s)), off && 'bg-muted/40')} data-section={s}>
              <GripVertical className="size-4 shrink-0 cursor-grab text-muted-foreground/60 active:cursor-grabbing" aria-hidden />
              <span className="min-w-0 flex-1">
                <span className={cn('block text-sm font-semibold', off && 'text-muted-foreground line-through decoration-muted-foreground/50')}>{sectionTitle(s)}</span>
                <span className="block truncate text-[11px] text-muted-foreground">{names.slice(0, 4).join(', ')}{names.length > 4 ? ` +${names.length - 4}` : ''}</span>
              </span>
              <ArrowButtons i={i} n={shown.length} name={sectionTitle(s)} step={(_, by) => step(order.indexOf(s), by === -1 ? order.indexOf(shown[i - 1]) - order.indexOf(s) : order.indexOf(shown[i + 1]) - order.indexOf(s))} />
              <button
                type="button"
                role="switch"
                aria-checked={!off}
                aria-label={`Show ${sectionTitle(s)}`}
                onClick={() => onToggle(s)}
                className={cn('inline-flex h-7 shrink-0 items-center gap-1 rounded-full border px-2 text-[11px] font-medium transition-colors', off ? 'text-muted-foreground hover:bg-muted' : 'border-success/30 bg-success-soft text-success hover:bg-success-soft/70')}
              >
                {off ? <EyeOff className="size-3.5" aria-hidden /> : <Eye className="size-3.5" aria-hidden />}
                {off ? 'Hidden' : 'Shown'}
              </button>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
