import * as React from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowRight, Building2, ChevronRight, ChevronsDownUp, ChevronsUpDown, FolderKanban, HandCoins, Minus, Plus, TrendingDown, TrendingUp, Truck, type LucideIcon } from 'lucide-react'
import { VoucherSheet } from '@/components/accounts/books'
import { Skeleton } from '@/components/ui/skeleton'
import { fetchProjectsBooks, fetchStatement, formatDay, rupees, type Period, type PlGroup, type PlLedger, type PlTotals, type ProfitLoss, type Scope } from '@/lib/accounts'
import { cn } from '@/lib/utils'

// UX-31 (asked 17 Nov 2026: "for an owner and for an accountant, different profit and loss?" -> the same numbers,
// a different first view): the owner's P&L. One card says the result in a sentence and where each ₹100 of income
// went; under it the statement reads top to bottom in plain words (money earned, site costs, office and running
// costs, other money in, profit), each line with its share of income and its change. The accounting name stays in
// small text beside the plain one. Same GET /accounts/pl as the other views.
// Digging in never needs another page (asked the same day: "drill down should be easy if they want to know more"):
// a line opens to its groups and accounts, an account to its entries in the period (GET /accounts/ledgers/{id}/
// statement), an entry to its voucher (VoucherSheet). "Open everything" opens every line; a part of the ₹100 bar opens
// its line; "Which project made it" lists the projects (GET /accounts/projects), each opening its own books.

const tiny = 0.005
const n = (v: string | number | null | undefined) => Number(v ?? 0)

type Kind = 'income' | 'direct' | 'indirect' | 'other'
const LOOK: Record<Kind, { icon: LucideIcon; tile: string; bar: string; fg: string }> = {
  income: { icon: TrendingUp, tile: 'bg-success-soft text-success', bar: 'bg-success', fg: 'text-success' },
  direct: { icon: Truck, tile: 'bg-draft-soft text-draft', bar: 'bg-draft', fg: 'text-draft' },
  indirect: { icon: Building2, tile: 'bg-ai-soft text-ai', bar: 'bg-ai', fg: 'text-ai' },
  other: { icon: HandCoins, tile: 'bg-info-soft text-info', bar: 'bg-info', fg: 'text-info' },
}

/** "▲ ₹2,45,300 · 14.9%", green when it is good news. */
function Change({ now, before, goodWhenUp, className }: { now: number; before: number | null; goodWhenUp: boolean; className?: string }) {
  if (before === null) return null
  const d = now - before
  if (Math.abs(d) < tiny) return <span className={cn('text-[11px] text-muted-foreground', className)}>no change</span>
  const pct = Math.abs(before) < tiny ? null : (d / Math.abs(before)) * 100
  const good = d > 0 === goodWhenUp
  return (
    <span className={cn('inline-flex items-center gap-0.5 rounded-full px-1.5 py-px text-[11px] font-medium tabular-nums', good ? 'bg-success-soft text-success' : 'bg-destructive/10 text-destructive', className)}>
      {d > 0 ? '▲' : '▼'} {rupees(Math.abs(d))}
      {pct !== null && ` · ${Math.abs(pct) >= 1000 ? '>999' : Math.abs(pct).toFixed(1)}%`}
    </span>
  )
}

// --- The result, in a sentence ---------------------------------------------------------------------------------

function PlOwnerHero({ pl, periodLabel, priorLabel, onFocus }: { pl: ProfitLoss; periodLabel: string; priorLabel?: string; onFocus?: (section: string) => void }) {
  const t = pl.totals
  const p = pl.prior_totals
  const income = n(t.income)
  const other = n(t.other_income)
  const direct = n(t.direct)
  const indirect = n(t.indirect)
  const np = n(t.net_profit)
  const loss = np < -tiny
  const before = p ? n(p.net_profit) : null
  const kept = income > tiny ? Math.round((np / income) * 100) : null

  // Where the money went: site costs, office costs and profit share the money that came in (income + other). In a
  // loss the costs are more than came in; the bar then shows the costs, and the loss is the part past the line.
  const cameIn = income + other
  const base = Math.max(cameIn, direct + indirect, 1)
  const parts = [
    { key: 'direct', label: 'Site costs', v: direct, cls: LOOK.direct.bar },
    { key: 'indirect', label: 'Office and running costs', v: indirect, cls: LOOK.indirect.bar },
    { key: 'profit', label: 'Profit', v: Math.max(0, np), cls: 'bg-success' },
  ].filter((x) => x.v > tiny)
  const per100 = (v: number) => (income > tiny ? Math.round((v / income) * 100) : null)
  const Icon = loss ? TrendingDown : TrendingUp

  return (
    <div data-guide="pl.stats" className={cn('grid gap-5 rounded-xl border bg-card p-4 shadow-xs sm:p-5 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]', loss ? 'border-destructive/30' : 'border-success/30')}>
      <div className="flex min-w-0 flex-col gap-1.5">
        <span className={cn('inline-flex w-fit items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold', loss ? 'bg-destructive/10 text-destructive' : 'bg-success-soft text-success')}>
          <Icon className="size-3.5" aria-hidden="true" />
          {loss ? 'Loss' : 'Profit'} · {periodLabel}
        </span>
        <p className={cn('text-3xl font-semibold tabular-nums tracking-tight sm:text-4xl', loss ? 'text-destructive' : 'text-success')}>
          {loss && '−'}
          {rupees(np)}
        </p>
        <p className="text-sm text-muted-foreground">
          {loss ? 'Costs were more than the money earned.' : kept !== null ? (
            <>
              Out of every <span className="font-medium text-foreground">₹100</span> earned, you kept <span className="font-semibold text-success">₹{kept}</span>.
            </>
          ) : (
            'No income in this period.'
          )}
        </p>
        {before !== null && (
          <p className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
            <Change now={np} before={before} goodWhenUp />
            <span>
              against {before < -tiny ? 'a loss of ' : ''}
              {rupees(before)} in {priorLabel ?? 'the period before'}
            </span>
          </p>
        )}
      </div>

      <div className="flex min-w-0 flex-col justify-center gap-2.5">
        <p className="text-xs font-medium text-muted-foreground">Where each ₹100 earned went</p>
        <div className="flex h-3.5 w-full gap-0.5 overflow-hidden rounded-full bg-muted">
          {parts.map((x) => (
            <button
              key={x.key}
              type="button"
              title={`${x.label}: ${rupees(x.v)}. Show what is in it`}
              aria-label={`${x.label}: show what is in it`}
              onClick={() => onFocus?.(x.key === 'profit' ? 'net' : x.key)}
              className={cn('h-full cursor-pointer transition-opacity first:rounded-l-full last:rounded-r-full hover:opacity-80', x.cls)}
              style={{ width: `${(x.v / base) * 100}%` }}
            />
          ))}
        </div>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
          {[
            { key: 'direct', label: 'Site costs', v: direct, dot: LOOK.direct.bar },
            { key: 'indirect', label: 'Office and running costs', v: indirect, dot: LOOK.indirect.bar },
            { key: 'net', label: loss ? 'Loss' : 'Profit', v: np, dot: loss ? 'bg-destructive' : 'bg-success' },
          ].map((x) => {
            const share = per100(Math.abs(x.v))
            return (
              <button
                key={x.key}
                type="button"
                onClick={() => onFocus?.(x.key)}
                className="group flex min-w-0 items-baseline gap-2 rounded-md text-left sm:flex-col sm:gap-0.5"
              >
                <span className="flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground">
                  <span className={cn('size-2 shrink-0 rounded-full', x.dot)} />
                  <span className="truncate">{x.label}</span>
                </span>
                <span className="ml-auto text-sm font-semibold tabular-nums sm:ml-0">
                  {share !== null ? `₹${share}` : '—'}
                  <span className="ml-1 text-xs font-normal text-muted-foreground group-hover:text-foreground group-hover:underline">{rupees(x.v)}</span>
                </span>
              </button>
            )
          })}
        </div>
      </div>
    </div>
  )
}

// --- The statement, top to bottom ------------------------------------------------------------------------------

interface Ctx {
  period: Period
  scope: Scope
  keep: string
  comparing: boolean
  /** Lines open at the moment: a section, a group ("section/group") or an account ("ledger:id"). */
  open: Set<string>
  toggle: (id: string) => void
  onEntry: (entryId: string) => void
}

/** An account's entries in the period, newest first, each opening its voucher; the full statement one tap further. */
function Entries({ ledger, ctx, cost, indent }: { ledger: PlLedger; ctx: Ctx; cost: boolean; indent: string }) {
  const q = useQuery({ queryKey: ['accounts', 'statement', ledger.ledger_id, ctx.period, ctx.scope], queryFn: () => fetchStatement(ledger.ledger_id, ctx.period, ctx.scope) })
  const SHOW = 8
  if (q.isLoading) return <div className={cn('border-t border-border/50 py-2 pr-4', indent)}><Skeleton className="h-16 w-full rounded-md" /></div>
  if (q.isError || !q.data) return <p className={cn('border-t border-border/50 py-2 pr-4 text-xs text-muted-foreground', indent)}>The entries could not be loaded.</p>
  const lines = [...q.data.lines].reverse()
  const amount = (debit: string, credit: string) => (cost ? n(debit) - n(credit) : n(credit) - n(debit))
  return (
    <div className={cn('border-t border-border/50 bg-muted/25 py-1.5 pr-4', indent)}>
      {lines.length === 0 && <p className="py-1.5 text-xs text-muted-foreground">No entries in this period.</p>}
      <ul className="divide-y divide-border/50">
        {lines.slice(0, SHOW).map((l) => {
          const v = amount(l.debit, l.credit)
          return (
            <li key={l.line_id}>
              <button type="button" onClick={() => ctx.onEntry(l.entry_id)} className="flex w-full items-start gap-3 py-1.5 text-left text-xs hover:text-foreground">
                <span className="w-14 shrink-0 tabular-nums text-muted-foreground">{formatDay(l.date).replace(/ \d{4}$/, '')}</span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-foreground">{l.narration || l.against || l.ref}</span>
                  <span className="block truncate text-muted-foreground">{[l.ref, l.project, l.site].filter(Boolean).join(' · ')}</span>
                </span>
                <span className={cn('shrink-0 tabular-nums', v < 0 && 'text-destructive')}>{v < 0 ? `(${rupees(v)})` : rupees(v)}</span>
              </button>
            </li>
          )
        })}
      </ul>
      <Link to={`/accounts/ledgers/${ledger.ledger_id}${ctx.keep}`} className="mt-1 inline-flex items-center gap-1 py-1 text-xs font-medium text-primary-ink hover:underline">
        {lines.length > SHOW ? `All ${lines.length} entries` : 'The full statement'} <ArrowRight className="size-3" />
      </Link>
    </div>
  )
}

function Ledgers({ group, ctx, goodWhenUp, indent, entriesIndent }: { group: PlGroup; ctx: Ctx; goodWhenUp: boolean; indent: string; entriesIndent: string }) {
  const total = Math.abs(n(group.amount)) || 1
  return (
    <>
      {group.ledgers.map((l) => {
        const id = `ledger:${l.ledger_id}`
        const isOpen = ctx.open.has(id)
        const v = n(l.amount)
        return (
          <React.Fragment key={l.ledger_id}>
            <button type="button" onClick={() => ctx.toggle(id)} aria-expanded={isOpen} className={cn('flex w-full items-center gap-3 border-t border-border/50 py-2 pr-4 text-left text-sm hover:bg-muted/40', indent)}>
              <ChevronRight className={cn('-ml-5 size-3.5 shrink-0 text-muted-foreground transition-transform', isOpen && 'rotate-90')} />
              <span className="min-w-0 flex-1">
                <span className="block truncate">
                  {l.name}
                  {l.is_overheads && <span className="ml-2 rounded bg-muted px-1.5 py-px text-[10px] text-muted-foreground">head-office share</span>}
                </span>
                <span className="mt-1 block h-1 w-full max-w-40 overflow-hidden rounded-full bg-muted">
                  <span className="block h-full rounded-full bg-foreground/30" style={{ width: `${Math.min(100, (Math.abs(v) / total) * 100)}%` }} />
                </span>
              </span>
              {ctx.comparing && <Change now={v} before={n(l.prior)} goodWhenUp={goodWhenUp} className="hidden sm:inline-flex" />}
              <span className="w-28 shrink-0 text-right tabular-nums sm:w-32">{rupees(v)}</span>
            </button>
            {isOpen && <Entries ledger={l} ctx={ctx} cost={!goodWhenUp} indent={entriesIndent} />}
          </React.Fragment>
        )
      })}
    </>
  )
}

function SectionBlock({
  kind,
  sign,
  label,
  formal,
  hint,
  groups,
  v,
  before,
  income,
  goodWhenUp,
  ctx,
}: {
  kind: Kind
  sign: '+' | '−'
  label: string
  formal: string
  hint: string
  groups: PlGroup[]
  v: number
  before: number | null
  income: number
  goodWhenUp: boolean
  ctx: Ctx
}) {
  const look = LOOK[kind]
  const Icon = look.icon
  const share = income > tiny ? (v / income) * 100 : null
  const single = groups.length === 1
  const headOpen = ctx.open.has(kind)
  const SignIcon = sign === '+' ? Plus : Minus
  return (
    <div id={`pl-${kind}`} className="scroll-mt-24 border-t first:border-t-0">
      <button
        type="button"
        onClick={() => groups.length > 0 && ctx.toggle(kind)}
        aria-expanded={groups.length > 0 ? headOpen : undefined}
        className={cn('flex w-full items-center gap-3 px-4 py-3 text-left', groups.length > 0 && 'hover:bg-muted/40', headOpen && 'bg-muted/30')}
      >
        {kind === 'income' ? <span className="w-3.5 shrink-0" /> : <SignIcon className="size-3.5 shrink-0 text-muted-foreground" aria-label={sign === '+' ? 'plus' : 'less'} />}
        <span className={cn('flex size-8 shrink-0 items-center justify-center rounded-lg', look.tile)}>
          <Icon className="size-4" aria-hidden="true" />
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-baseline gap-x-2">
            <span className="font-semibold">{label}</span>
            <span className="text-[11px] text-muted-foreground">{formal}</span>
            {groups.length > 0 && <ChevronRight className={cn('size-3.5 self-center text-muted-foreground transition-transform', headOpen && 'rotate-90')} />}
          </span>
          <span className="block text-xs text-muted-foreground">{hint}</span>
          {share !== null && kind !== 'income' && (
            <span className="mt-1.5 flex items-center gap-2">
              <span className="h-1.5 w-full max-w-48 overflow-hidden rounded-full bg-muted">
                <span className={cn('block h-full rounded-full', look.bar)} style={{ width: `${Math.min(100, Math.abs(share))}%` }} />
              </span>
              <span className="shrink-0 text-[11px] text-muted-foreground tabular-nums">₹{Math.round(share)} of every ₹100</span>
            </span>
          )}
        </span>
        <span className="flex shrink-0 flex-col items-end gap-1">
          <span className={cn('text-base font-semibold tabular-nums', look.fg)}>{rupees(v)}</span>
          <Change now={v} before={before} goodWhenUp={goodWhenUp} />
        </span>
      </button>
      {headOpen && single && <Ledgers group={groups[0]} ctx={ctx} goodWhenUp={goodWhenUp} indent="pl-[4.75rem]" entriesIndent="pl-[4.75rem]" />}
      {headOpen &&
        !single &&
        groups.map((g) => {
          const id = `${kind}/${g.group_id ?? g.name}`
          const isOpen = ctx.open.has(id)
          return (
            <React.Fragment key={id}>
              <button type="button" onClick={() => ctx.toggle(id)} aria-expanded={isOpen} className="flex w-full items-center gap-3 border-t border-border/50 py-2 pl-[4.75rem] pr-4 text-left text-sm hover:bg-muted/40">
                <ChevronRight className={cn('-ml-5 size-3.5 shrink-0 text-muted-foreground transition-transform', isOpen && 'rotate-90')} />
                <span className="min-w-0 flex-1 truncate font-medium">
                  {g.name} <span className="text-[11px] font-normal text-muted-foreground">{g.ledgers.length}</span>
                </span>
                {before !== null && <Change now={n(g.amount)} before={n(g.prior)} goodWhenUp={goodWhenUp} className="hidden sm:inline-flex" />}
                <span className="w-28 shrink-0 text-right font-medium tabular-nums sm:w-32">{rupees(n(g.amount))}</span>
              </button>
              {isOpen && <Ledgers group={g} ctx={ctx} goodWhenUp={goodWhenUp} indent="pl-[6rem]" entriesIndent="pl-[6rem]" />}
            </React.Fragment>
          )
        })}
    </div>
  )
}

function ResultLine({ label, formal, v, before, income, strong }: { label: string; formal: string; v: number; before: number | null; income: number; strong?: boolean }) {
  const loss = v < -tiny
  const share = income > tiny ? Math.round((v / income) * 100) : null
  return (
    <div id={strong ? 'pl-net' : undefined} className={cn('flex scroll-mt-24 items-center gap-3 border-t px-4', strong ? 'border-t-2 py-4' : 'bg-muted/50 py-3', strong && (loss ? 'border-t-destructive/40 bg-destructive/[0.05]' : 'border-t-success/40 bg-success-soft/50'))}>
      <span className="w-3.5 shrink-0 text-center font-semibold text-muted-foreground">=</span>
      <span className="min-w-0 flex-1">
        <span className="flex flex-wrap items-baseline gap-x-2">
          <span className={cn('font-semibold', strong && 'text-base')}>{loss ? label.replace('profit', 'loss').replace('Profit', 'Loss') : label}</span>
          <span className="text-[11px] text-muted-foreground">{loss ? formal.replace('profit', 'loss') : formal}</span>
        </span>
        {share !== null && <span className="block text-xs text-muted-foreground">{share < 0 ? `Lost ₹${-share} on every ₹100 earned` : `₹${share} of every ₹100 earned`}</span>}
      </span>
      <span className="flex shrink-0 flex-col items-end gap-1">
        <span className={cn('font-semibold tabular-nums', strong ? 'text-xl' : 'text-base', loss ? 'text-destructive' : strong && 'text-success')}>
          {loss && '−'}
          {rupees(v)}
        </span>
        <Change now={v} before={before} goodWhenUp />
      </span>
    </div>
  )
}

/** Which project made it: each project's profit in the period, best first; each opens its own books. */
function ByProject({ period }: { period: Period }) {
  const q = useQuery({ queryKey: ['accounts', 'projects', period], queryFn: () => fetchProjectsBooks(period) })
  if (q.isLoading) return <Skeleton className="h-40 rounded-xl" />
  const rows = (q.data?.projects ?? []).filter((r) => Math.abs(n(r.billed)) > tiny || Math.abs(n(r.cost)) > tiny)
  if (q.isError || rows.length === 0) return null
  rows.sort((a, b) => n(b.profit) - n(a.profit))
  const top = Math.max(1, ...rows.map((r) => Math.abs(n(r.profit))))
  return (
    <div className="overflow-hidden rounded-xl border bg-card shadow-xs">
      <div className="flex items-center justify-between gap-2 border-b bg-muted/40 px-4 py-2.5">
        <span className="flex items-center gap-2 text-sm font-semibold">
          <FolderKanban className="size-4 text-muted-foreground" aria-hidden="true" /> Which project made it
        </span>
        <Link to="/accounts/projects" className="text-[11px] font-medium text-primary-ink hover:underline">
          All projects
        </Link>
      </div>
      <ul className="divide-y">
        {rows.map((r) => {
          const p = n(r.profit)
          return (
            <li key={r.project_id}>
              <Link to={`/accounts/projects/${r.project_id}`} className="flex items-center gap-3 px-4 py-2.5 hover:bg-muted/40">
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium">{r.name}</span>
                  <span className="block truncate text-xs text-muted-foreground">
                    Earned {rupees(r.billed)} · costs {rupees(n(r.cost) + n(r.overheads))}
                  </span>
                </span>
                <span className="hidden w-40 sm:block">
                  <span className="block h-1.5 overflow-hidden rounded-full bg-muted">
                    <span className={cn('block h-full rounded-full', p < 0 ? 'bg-destructive' : 'bg-success')} style={{ width: `${(Math.abs(p) / top) * 100}%` }} />
                  </span>
                </span>
                <span className="w-32 shrink-0 text-right">
                  <span className={cn('block text-sm font-semibold tabular-nums', p < 0 ? 'text-destructive' : 'text-success')}>
                    {p < 0 && '−'}
                    {rupees(p)}
                  </span>
                  {r.margin !== null && <span className="block text-[11px] text-muted-foreground">{p < 0 ? 'loss' : 'profit'} · {Number(r.margin).toFixed(0)}%</span>}
                </span>
                <ChevronRight className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
              </Link>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

/** The ids of every line, for "Open everything" (accounts' entries stay closed: they each ask the server). */
function allLines(pl: ProfitLoss): string[] {
  const kinds: [Kind, keyof ProfitLoss['sections']][] = [['income', 'income'], ['direct', 'direct'], ['indirect', 'indirect'], ['other', 'other_income']]
  return kinds.flatMap(([k, key]) => [k, ...pl.sections[key].map((g) => `${k}/${g.group_id ?? g.name}`)])
}

function usePlFocus() {
  const [open, setOpen] = React.useState<Set<string>>(new Set())
  const toggle = (id: string) =>
    setOpen((s) => {
      const next = new Set(s)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  /** From the ₹100 bar: open that line and bring it into view. */
  const focus = (key: string) => {
    if (key !== 'net') setOpen((s) => new Set(s).add(key))
    window.setTimeout(() => document.getElementById(`pl-${key}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 50)
  }
  return { open, setOpen, toggle, focus }
}

export function PlSimple({
  pl,
  period,
  scope,
  company,
  periodLabel,
  priorLabel,
  notice,
}: {
  pl: ProfitLoss
  period: Period
  scope: Scope
  /** The whole company (not one project or site): show which project made it. */
  company: boolean
  periodLabel: string
  priorLabel?: string
  /** A note between the result and the statement (a project's share of head-office costs). */
  notice?: React.ReactNode
}) {
  const [entry, setEntry] = React.useState<string | null>(null)
  const focus = usePlFocus()
  const t = pl.totals
  const p = pl.prior_totals
  const pr = (k: keyof PlTotals) => (p ? n(p[k]) : null)
  const income = n(t.income)
  const keep = typeof window !== 'undefined' && window.location.search ? window.location.search : ''
  const empty = !income && !n(t.direct) && !n(t.indirect) && !n(t.other_income)
  if (empty) {
    return (
      <div data-guide="pl.stats">
        <p data-guide="pl.statement" className="rounded-xl border border-dashed bg-card px-4 py-6 text-sm text-muted-foreground">
          No income or cost in the books for this period.
        </p>
      </div>
    )
  }
  const ctx: Ctx = { period, scope, keep, comparing: !!p, open: focus.open, toggle: focus.toggle, onEntry: setEntry }
  const s = pl.sections
  const showOther = s.other_income.length > 0 || Math.abs(n(t.other_income)) > tiny
  const showIndirect = s.indirect.length > 0 || Math.abs(n(t.indirect)) > tiny
  const anyOpen = focus.open.size > 0
  return (
    <div className="flex flex-col gap-4">
      <PlOwnerHero pl={pl} periodLabel={periodLabel} priorLabel={priorLabel} onFocus={focus.focus} />
      {notice}
      <div data-guide="pl.statement" className="overflow-hidden rounded-xl border bg-card shadow-xs">
        <div className="flex items-center justify-between gap-2 border-b bg-muted/40 px-4 py-2">
          <span className="text-sm font-semibold">How you got there</span>
          <button
            type="button"
            onClick={() => focus.setOpen(anyOpen ? new Set() : new Set(allLines(pl)))}
            className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium text-muted-foreground hover:bg-muted hover:text-foreground"
          >
            {anyOpen ? <ChevronsDownUp className="size-3.5" /> : <ChevronsUpDown className="size-3.5" />}
            {anyOpen ? 'Close all' : 'Open everything'}
          </button>
        </div>
        <SectionBlock kind="income" sign="+" label="Money earned" formal="Income" hint="RA bills sent, before GST" groups={s.income} v={income} before={pr('income')} income={income} goodWhenUp ctx={ctx} />
        <SectionBlock kind="direct" sign="−" label="Site costs" formal="Direct costs" hint="Bills and expenses on the projects, after the GST you claim back" groups={s.direct} v={n(t.direct)} before={pr('direct')} income={income} goodWhenUp={false} ctx={ctx} />
        <ResultLine label="Left after site costs" formal="Gross profit" v={n(t.gross_profit)} before={pr('gross_profit')} income={income} />
        {showIndirect && (
          <SectionBlock kind="indirect" sign="−" label="Office and running costs" formal="Indirect costs" hint="Costs of running the company, not of one job" groups={s.indirect} v={n(t.indirect)} before={pr('indirect')} income={income} goodWhenUp={false} ctx={ctx} />
        )}
        {showOther && (
          <SectionBlock kind="other" sign="+" label="Other money in" formal="Other income" hint="Money that did not come from project bills" groups={s.other_income} v={n(t.other_income)} before={pr('other_income')} income={income} goodWhenUp ctx={ctx} />
        )}
        <ResultLine label="Profit" formal="Net profit" v={n(t.net_profit)} before={pr('net_profit')} income={income} strong />
        <p className="border-t px-4 py-2 text-[11px] text-muted-foreground">Tap any line to see what is in it, an account for its entries, and an entry for the bill or voucher behind it.</p>
      </div>
      {company && <ByProject period={period} />}
      <VoucherSheet entryId={entry} onClose={() => setEntry(null)} onOpen={setEntry} />
    </div>
  )
}
