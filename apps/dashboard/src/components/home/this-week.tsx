import * as React from 'react'
import { Link } from 'react-router-dom'
import { useQueries, useQuery } from '@tanstack/react-query'
import type { LucideIcon } from 'lucide-react'
import {
  AlarmClock, BookAlert, CalendarCheck, CalendarX, ChevronDown, ChevronRight, CircleCheck, FileText, HandCoins, PackageSearch, ReceiptText, Truck, TrendingDown, Wallet,
} from 'lucide-react'
import { useAuth } from '@/lib/AuthContext'
import { useScope } from '@/lib/ScopeContext'
import { useModuleEnabled } from '@/lib/modules'
import { MONEY_ROLES } from '@/lib/module-map'
import { fetchHome, fetchMonths, mayReadBooks, short } from '@/lib/accounts'
import { KIND_LOOK, KIND_ORDER, daysWaited, fetchWaiting, waitingUrl, type WaitingKind } from '@/lib/approvals'
import { fetchToBill, mayBill } from '@/lib/billing'
import { maySeeBoq } from '@/lib/boq'
import { fetchPortfolio } from '@/lib/cost'
import { fetchMaterialPlan } from '@/lib/material-plan'
import { fetchOrders } from '@/lib/orders'
import { fetchProjects } from '@/lib/projects'
import { fetchReceivables } from '@/lib/receivables'
import { fetchRequests } from '@/lib/requests'
import { fetchSchedule } from '@/lib/schedule'
import { fetchPayables } from '@/lib/vendors'
import { localIsoDate, plural } from '@/lib/site-day'
import { appNow } from '@/lib/clock'
import { cn } from '@/lib/utils'

// UX-61 (asked 18 Nov 2026: "an owner's this-week list"): the owner's to-do across the modules, one line each, worst
// first, each opening the page that does it. UX-65 (asked 18 Nov: "the home dashboard of each role"): every role gets
// its own list, made the same way from what its tiles and pages already read:
// - everyone: what waits on them to decide (the Approvals inbox, GET /approvals/waiting, one line per kind; their
//   tasks have their own card below);
// - owner: work done not billed, clients to chase, projects heading over budget, late work, materials to order,
//   suppliers to pay, late deliveries;
// - project manager: late work, materials to order, work lines in the red this week, late deliveries;
// - site engineer: deliveries late or due today, their requests past the date needed;
// - finance: suppliers to pay, delivered but not billed, clients to chase, the books' own checks (accounts home).
// The tiles above answer "how are we doing"; this answers "what do I do". A line asks its API only when the role may
// read it and the module is on; a refused API leaves its lines out. A project picked in the top bar narrows it.

type Tone = 'bad' | 'attention' | 'info'
interface Item {
  key: string
  tone: Tone
  icon: LucideIcon
  verb: string
  what: string
  project?: string
  amount?: string
  to: string
}

const TONE: Record<Tone, { edge: string; icon: string; amount: string }> = {
  bad: { edge: 'before:bg-destructive', icon: 'bg-destructive/10 text-destructive', amount: 'text-destructive' },
  attention: { edge: 'before:bg-draft', icon: 'bg-draft-soft text-draft', amount: 'text-draft' },
  info: { edge: 'before:bg-info', icon: 'bg-info-soft text-info', amount: 'text-info' },
}
const RANK: Record<Tone, number> = { bad: 0, attention: 1, info: 2 }
const SHOWN = 6
const n = (v: string | number | null | undefined) => Number(v ?? 0) || 0
const dayLabel = (iso: string) => new Date(`${iso}T00:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })

type Who = 'owner' | 'pm' | 'engineer' | 'finance'
const WHO: Record<string, Who> = { OWNER: 'owner', ADMIN: 'owner', SUPER_ADMIN: 'owner', PROJECT_MANAGER: 'pm', SITE_ENGINEER: 'engineer', FINANCE: 'finance' }

/** One line per kind waiting on this person: the verb, and the icon of the Approvals page (one look everywhere). */
/** The books' own checks (accounts home `attention`), in a line each; a new check shows the API's own words. */
const BOOK_CHECKS: Record<string, { verb: string; what: string }> = {
  opening_difference: { verb: 'Fix the opening balances', what: "they don't match each other yet" },
  balance_adjustments: { verb: 'Classify balance adjustments', what: 'money moved with no ledger yet' },
  no_client: { verb: 'Set the client on a project', what: 'bills or money with no client' },
  after_close: { verb: 'Check changes to closed months', what: 'entries made after the close' },
}

const WAITING_VERB: Partial<Record<WaitingKind, (count: number) => string>> = {
  site_report: (c) => `Confirm ${plural(c, 'site report')}`,
  material_request: (c) => `Decide ${plural(c, 'material request')}`,
  subcontract_bill: (c) => `Check ${plural(c, 'subcontractor bill')}`,
  ra_bill: (c) => `Send ${plural(c, 'RA bill')} in draft`,
  wage_sheet: (c) => `Approve or pay ${plural(c, 'wage week')}`,
  labour_split: (c) => `Put ${plural(c, 'labour entry', 'labour entries')} on the BOQ`,
  stock_count: (c) => `Approve ${plural(c, 'stock count')}`,
}

/** UX-75: `onCount` tells Home's header how many things wait and how many are urgent, once they are known. */
export function ThisWeek({ onCount }: { onCount?: (count: { total: number; urgent: number }) => void } = {}) {
  const { me } = useAuth()
  const { scope } = useScope()
  const on = useModuleEnabled()
  const role = (me?.role || '').toUpperCase()
  const who: Who | undefined = WHO[role]
  const owner = who === 'owner'
  const pm = who === 'pm'
  const engineer = who === 'engineer'
  const finance = who === 'finance'
  const projectId = scope.mode === 'portfolio' ? undefined : scope.projectId
  const siteId = scope.mode === 'site' ? scope.siteId : undefined
  const today = React.useMemo(() => localIsoDate(appNow()), [])
  const [all, setAll] = React.useState(false)

  const money = (MONEY_ROLES as readonly string[]).includes(role) && on('finance')
  const wants = {
    waiting: !!who,
    toBill: owner && mayBill(role),
    receivables: (owner || finance) && mayReadBooks(role) && on('finance'),
    payables: (owner || finance) && money,
    home: finance && mayReadBooks(role) && on('finance') && on('accounts'),
    portfolio: (owner || pm) && maySeeBoq(role) && on('cost'),
    plans: (owner || pm) && maySeeBoq(role) && on('materials'),
    schedule: owner || pm,
    requests: engineer && on('materials'),
    orders: (owner || pm || engineer) && on('materials'),
  }
  // The same keys as the role's tiles (components/home/role-home.tsx) and the bell: one request each.
  const opts = { retry: false, staleTime: 60_000 } as const
  const waiting = useQuery({ queryKey: ['approvals', 'waiting'], queryFn: fetchWaiting, enabled: wants.waiting, ...opts })
  const toBill = useQuery({ queryKey: ['billing', 'to-bill'], queryFn: fetchToBill, enabled: wants.toBill, ...opts })
  const receivables = useQuery({ queryKey: ['home', 'receivables'], queryFn: fetchReceivables, enabled: wants.receivables, ...opts })
  const payables = useQuery({ queryKey: ['home', 'payables', projectId], queryFn: () => fetchPayables({ project_id: projectId }), enabled: wants.payables, ...opts })
  const home = useQuery({ queryKey: ['home', 'accounts', projectId], queryFn: () => fetchHome(projectId), enabled: wants.home, ...opts })
  const months = useQuery({ queryKey: ['home', 'months'], queryFn: fetchMonths, enabled: wants.home, ...opts })
  const portfolio = useQuery({ queryKey: ['home', 'portfolio'], queryFn: fetchPortfolio, enabled: wants.portfolio, ...opts })
  const requests = useQuery({ queryKey: ['home', 'requests', projectId, siteId], queryFn: () => fetchRequests({ project_id: projectId, site_id: siteId }), enabled: wants.requests, ...opts })
  const orders = useQuery({ queryKey: ['home', 'orders', projectId, siteId], queryFn: () => fetchOrders({ project_id: projectId, site_id: siteId }), enabled: wants.orders, ...opts })
  const projects = useQuery({ queryKey: ['scope-projects'], queryFn: fetchProjects, enabled: wants.schedule, staleTime: 60_000 })
  const ids = (projects.data ?? []).filter((p) => !projectId || p.id === projectId).slice(0, 12)
  const schedules = useQueries({
    queries: ids.map((p) => ({ queryKey: ['schedule', p.id], queryFn: () => fetchSchedule(p.id), enabled: wants.schedule, ...opts })),
  })
  const plans = useQueries({
    queries: ids.map((p) => ({ queryKey: ['material-plan', p.id, 4], queryFn: () => fetchMaterialPlan(p.id, 4), enabled: wants.plans, ...opts })),
  })

  if (!who) return null
  const mine = (id: string | null | undefined) => !projectId || id === projectId
  const items: Item[] = []

  // Waiting on me to decide, one line per kind (the Approvals inbox; tasks have their own card).
  const waitingItems = (waiting.data?.items ?? []).filter((w) => w.kind !== 'task' && mine(w.project_id) && (!siteId || !w.site_id || w.site_id === siteId))
  for (const kind of KIND_ORDER) {
    const verb = WAITING_VERB[kind]
    const rows = waitingItems.filter((w) => w.kind === kind)
    if (!verb || !rows.length) continue
    const urgent = rows.filter((w) => w.urgent).length
    const oldest = Math.max(...rows.map((w) => daysWaited(w.since, waiting.data?.today || today)))
    const projectNames = new Set(rows.map((w) => w.project_name).filter(Boolean))
    const amount = rows.reduce((t, w) => t + n(w.amount), 0)
    items.push({
      key: `wait-${kind}`,
      tone: urgent ? 'bad' : oldest >= 3 ? 'attention' : 'info',
      icon: KIND_LOOK[kind].icon,
      verb: verb(rows.length),
      what: [urgent ? `${urgent} urgent` : '', oldest > 0 ? `oldest ${plural(oldest, 'day')}` : 'came in today'].filter(Boolean).join(' · '),
      project: projectNames.size === 1 ? [...projectNames][0]! : undefined,
      amount: amount > 0 ? short(amount) : undefined,
      to: rows.length === 1 ? waitingUrl(rows[0]) : `/site/approvals?kind=${kind}`,
    })
  }
  // Money to raise: work done on no bill yet.
  for (const p of toBill.data?.projects ?? []) {
    if (!mine(p.project_id)) continue
    items.push({ key: `bill-${p.project_id}`, tone: n(p.amount) >= 500000 ? 'bad' : 'attention', icon: FileText, verb: 'Raise the RA bill', what: p.stages ? `${plural(p.lines, 'payment stage')} reached` : `${plural(p.lines, 'line')} of work done`, project: p.project, amount: short(p.amount), to: `/billing/ra-bills?project=${p.project_id}` })
  }
  // Money to chase: each client's oldest unpaid bill.
  for (const c of receivables.data?.clients ?? []) {
    const bills = c.open_bills.filter((b) => mine(b.project_id))
    if (!bills.length) continue
    const left = bills.reduce((t, b) => t + n(b.left), 0)
    const days = Math.max(...bills.map((b) => b.days))
    items.push({ key: `chase-${c.client_id}`, tone: days > 60 ? 'bad' : days > 30 ? 'attention' : 'info', icon: HandCoins, verb: `Chase ${c.client}`, what: `${plural(bills.length, 'bill')} · oldest ${days} days`, project: bills.length === 1 ? (bills[0].project ?? undefined) : undefined, amount: short(left), to: '/accounts/receivables' })
  }
  // Projects heading over their budget (the owner), work lines in the red this week (the project manager).
  for (const p of portfolio.data?.projects ?? []) {
    if (!mine(p.project_id)) continue
    if (owner) {
      if (n(p.forecast_difference) >= 0 || !p.budget) continue
      const over = -n(p.forecast_difference)
      if (over / n(p.budget) < 0.02) continue
      items.push({ key: `over-${p.project_id}`, tone: over / n(p.budget) >= 0.1 ? 'bad' : 'attention', icon: TrendingDown, verb: 'Check the costs', what: `heading ${Math.round((over / n(p.budget)) * 100)}% over budget`, project: p.name, amount: short(over), to: `/accounts/projects/${p.project_id}` })
    } else if (p.week?.red_lines) {
      items.push({ key: `red-${p.project_id}`, tone: 'bad', icon: TrendingDown, verb: `${plural(p.week.red_lines, 'work line')} in the red`, what: 'labour above what the work earned this week', project: p.name, to: `/cost/green-red?project=${p.project_id}` })
    }
  }
  // Late work.
  schedules.forEach((q, i) => {
    const late = (q.data?.activities ?? []).filter((a) => a.state === 'late').sort((a, b) => b.days_late - a.days_late)
    if (!late.length) return
    const worst = late[0]
    items.push({ key: `late-${ids[i].id}`, tone: late.some((a) => a.critical) || worst.days_late >= 7 ? 'bad' : 'attention', icon: CalendarX, verb: late.length > 1 ? `${late.length} activities late` : `${worst.name} late`, what: `${late.length > 1 ? `worst: ${worst.name}, ` : ''}${plural(worst.days_late, 'day')}`, project: ids[i].name, to: `/planning/schedule?project=${ids[i].id}` })
  })
  // Materials to order now or this week.
  plans.forEach((q, i) => {
    const due = (q.data?.materials ?? []).filter((m) => m.order_by && (m.order_now || m.order_by <= addDays(today, 7)))
    if (!due.length) return
    const now = due.filter((m) => m.order_now)
    items.push({ key: `order-${ids[i].id}`, tone: now.length ? 'bad' : 'attention', icon: PackageSearch, verb: `Order ${due.length === 1 ? due[0].material : plural(due.length, 'material')}`, what: now.length ? 'short before a new order can arrive' : `by ${dayLabel(due.map((m) => m.order_by!).sort()[0])}`, project: ids[i].name, to: `/planning/materials?project=${ids[i].id}` })
  })
  // Suppliers to pay, and what they delivered but have not billed (finance gets their bills in).
  const owe = payables.data?.totals
  if (owe && n(owe.overdue) > 0) items.push({ key: 'pay-suppliers', tone: 'bad', icon: Wallet, verb: 'Pay overdue suppliers', what: 'past their due day', amount: short(owe.overdue), to: '/finance/vendors' })
  if (finance && owe && n(owe.unbilled) > 0) items.push({ key: 'unbilled', tone: 'attention', icon: ReceiptText, verb: "Get the suppliers' bills", what: 'delivered, not billed yet', amount: short(owe.unbilled), to: '/finance/vendors' })
  // The books' own checks (finance): an opening difference, money in suspense, changes to closed months.
  for (const a of home.data?.attention ?? []) {
    const own = BOOK_CHECKS[a.key]
    items.push({ key: `books-${a.key}`, tone: 'attention', icon: BookAlert, verb: own?.verb ?? 'Check the books', what: own?.what ?? a.words, amount: a.amount ? short(a.amount) : undefined, to: a.to })
  }
  // The last month that ended and is still open (finance closes it once the bills are in).
  const lastOpen = months.data?.months.filter((m) => m.status === 'open' && m.ends_on < today).at(-1)
  if (lastOpen) {
    const name = new Date(`${lastOpen.starts_on}T00:00:00`).toLocaleDateString('en-IN', { month: 'long' })
    items.push({ key: 'close-month', tone: 'info', icon: CalendarCheck, verb: `Close ${name}`, what: 'once its bills are in', to: '/accounts/periods' })
  }
  // Deliveries: late (everyone who watches them), due today (the site engineer receives them).
  const open = (orders.data?.items ?? []).filter((o) => o.status === 'open' || o.status === 'part')
  const lateOrders = open.filter((o) => o.expected_date && o.expected_date < today).length
  if (lateOrders > 0) items.push({ key: 'deliveries', tone: 'bad', icon: Truck, verb: `${plural(lateOrders, 'delivery', 'deliveries')} late`, what: 'call the supplier', to: '/procurement/pending?show=late' })
  const dueToday = open.filter((o) => o.expected_date === today).length
  if (engineer && dueToday > 0) items.push({ key: 'deliveries-today', tone: 'info', icon: Truck, verb: `${plural(dueToday, 'delivery', 'deliveries')} due today`, what: 'check and record what comes', to: '/procurement/pending' })
  // The site engineer's own requests the office has not met in time.
  const lateRequests = requests.data?.counts.late ?? 0
  if (engineer && lateRequests > 0) items.push({ key: 'requests-late', tone: 'attention', icon: AlarmClock, verb: `${plural(lateRequests, 'request')} past the date needed`, what: 'ask the office', to: '/materials/requests' })

  items.sort((a, b) => RANK[a.tone] - RANK[b.tone])
  const loading = [waiting, toBill, receivables, payables, home, portfolio, projects, orders].some((q) => q.isLoading)
  const shown = all ? items : items.slice(0, SHOWN)
  const urgent = items.filter((i) => i.tone === 'bad').length

  return (
    <section className="flex flex-col overflow-hidden rounded-xl border bg-card shadow-xs" data-guide="home.week" aria-label="Needs you">
      {onCount && <ReportCount total={items.length} urgent={urgent} loading={loading} onCount={onCount} />}
      <header className="flex flex-wrap items-center gap-2 border-b px-4 py-2.5">
        {/* UX-75: Home leads with this list ("what needs my attention"), so it is named for what it answers. */}
        <h2 className="text-[15px] font-semibold">Needs you</h2>
        <span className="text-xs text-muted-foreground">this week, worst first</span>
        {items.length > 0 && <span className="rounded-full bg-muted px-2 py-0.5 text-xs font-semibold tabular-nums">{items.length}</span>}
        {urgent > 0 && <span className="rounded-full bg-destructive/10 px-2 py-0.5 text-xs font-semibold text-destructive">{urgent} urgent</span>}
        {projectId && scope.mode !== 'portfolio' && <span className="text-xs text-muted-foreground">{scope.projectName}</span>}
      </header>
      {loading && !items.length ? (
        <div className="flex flex-col gap-2 p-4">
          {[0, 1, 2].map((i) => <div key={i} className="h-9 animate-pulse rounded-lg bg-muted" />)}
        </div>
      ) : items.length === 0 ? (
        <p className="flex items-center gap-2 px-4 py-4 text-sm text-success">
          <CircleCheck className="size-4" aria-hidden /> Nothing waiting on you this week
        </p>
      ) : (
        <ul className="flex flex-col">
          {shown.map((it) => {
            const look = TONE[it.tone]
            return (
              <li key={it.key} className="border-b last:border-b-0">
                <Link
                  to={it.to}
                  className={cn("group relative flex items-center gap-3 px-4 py-2.5 pl-5 transition-colors before:absolute before:inset-y-1.5 before:left-0 before:w-1 before:rounded-r before:content-[''] hover:bg-muted/40", look.edge)}
                >
                  <span className={cn('flex size-8 shrink-0 items-center justify-center rounded-lg', look.icon)} aria-hidden>
                    <it.icon className="size-4" />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-semibold">{it.verb}</span>
                    <span className="flex min-w-0 flex-wrap items-center gap-x-1.5 text-xs text-muted-foreground">
                      {it.project && <span className="truncate rounded bg-muted px-1.5 py-px font-medium text-foreground">{it.project}</span>}
                      <span className="truncate">{it.what}</span>
                    </span>
                  </span>
                  {it.amount && <span className={cn('shrink-0 text-sm font-semibold tabular-nums', look.amount)}>{it.amount}</span>}
                  <ChevronRight className="size-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5" aria-hidden />
                </Link>
              </li>
            )
          })}
        </ul>
      )}
      {items.length > SHOWN && (
        <button type="button" onClick={() => setAll((a) => !a)} className="flex items-center justify-center gap-1 border-t px-4 py-2 text-xs font-medium text-muted-foreground hover:bg-muted/40 hover:text-foreground">
          {all ? 'Show fewer' : `Show all ${items.length}`} <ChevronDown className={cn('size-3.5 transition-transform', all && 'rotate-180')} aria-hidden />
        </button>
      )}
    </section>
  )
}

/** Tells Home's header the counts once they are known (a child, so the list's early return never skips a hook). */
function ReportCount({ total, urgent, loading, onCount }: { total: number; urgent: number; loading: boolean; onCount: (c: { total: number; urgent: number }) => void }) {
  React.useEffect(() => {
    if (!loading) onCount({ total, urgent })
  }, [loading, total, urgent, onCount])
  return null
}

function addDays(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00`)
  d.setDate(d.getDate() + days)
  return localIsoDate(d)
}
