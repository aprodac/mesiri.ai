import * as React from 'react'
import { Link } from 'react-router-dom'
import { useQueries, useQuery } from '@tanstack/react-query'
import type { LucideIcon } from 'lucide-react'
import {
  AlarmClock, CalendarX, ChevronDown, ChevronRight, CircleCheck, ClipboardCheck, FileText, HandCoins, PackageSearch, Truck, TrendingDown, Wallet,
} from 'lucide-react'
import { useAuth } from '@/lib/AuthContext'
import { useScope } from '@/lib/ScopeContext'
import { useModuleEnabled } from '@/lib/modules'
import { MONEY_ROLES } from '@/lib/module-map'
import { mayReadBooks, short } from '@/lib/accounts'
import { fetchToBill, mayBill } from '@/lib/billing'
import { maySeeBoq } from '@/lib/boq'
import { fetchPortfolio } from '@/lib/cost'
import { fetchPaySummary } from '@/lib/labour-pay'
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
// first, each opening the page that does it: work done not billed (raise the RA bill), clients to chase, projects
// heading over budget, late work, materials to order, suppliers and wages to pay, requests to decide, late
// deliveries. The tiles above answer "how are we doing"; this answers "what do I do". Every line reads an API the
// dashboard already has (the same queries as the tiles, so nothing is asked twice) and only when the role may read it
// and the module is on; a refused API leaves its lines out. A project picked in the top bar narrows it to that project.

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

export function ThisWeek() {
  const { me } = useAuth()
  const { scope } = useScope()
  const on = useModuleEnabled()
  const role = (me?.role || '').toUpperCase()
  const owner = ['OWNER', 'ADMIN', 'SUPER_ADMIN'].includes(role)
  const projectId = scope.mode === 'portfolio' ? undefined : scope.projectId
  const siteId = scope.mode === 'site' ? scope.siteId : undefined
  const today = React.useMemo(() => localIsoDate(appNow()), [])
  const [all, setAll] = React.useState(false)

  const money = (MONEY_ROLES as readonly string[]).includes(role) && on('finance')
  const wants = {
    toBill: owner && mayBill(role),
    receivables: owner && mayReadBooks(role) && on('finance'),
    payables: owner && money,
    portfolio: owner && maySeeBoq(role) && on('cost'),
    plans: owner && maySeeBoq(role) && on('materials'),
    schedule: owner,
    wages: owner && on('labour') && money,
    requests: owner && on('materials'),
    orders: owner && on('materials'),
  }
  // The same keys as the role's tiles (components/home/role-home.tsx): one request each.
  const opts = { retry: false, staleTime: 60_000 } as const
  const toBill = useQuery({ queryKey: ['billing', 'to-bill'], queryFn: fetchToBill, enabled: wants.toBill, ...opts })
  const receivables = useQuery({ queryKey: ['home', 'receivables'], queryFn: fetchReceivables, enabled: wants.receivables, ...opts })
  const payables = useQuery({ queryKey: ['home', 'payables', projectId], queryFn: () => fetchPayables({ project_id: projectId }), enabled: wants.payables, ...opts })
  const portfolio = useQuery({ queryKey: ['home', 'portfolio'], queryFn: fetchPortfolio, enabled: wants.portfolio, ...opts })
  const wages = useQuery({ queryKey: ['home', 'wages', projectId], queryFn: () => fetchPaySummary(projectId), enabled: wants.wages, ...opts })
  const requests = useQuery({ queryKey: ['home', 'requests', projectId, siteId], queryFn: () => fetchRequests({ project_id: projectId, site_id: siteId }), enabled: wants.requests, ...opts })
  const orders = useQuery({ queryKey: ['home', 'orders', projectId, siteId], queryFn: () => fetchOrders({ project_id: projectId, site_id: siteId }), enabled: wants.orders, ...opts })
  const projects = useQuery({ queryKey: ['scope-projects'], queryFn: fetchProjects, enabled: owner, staleTime: 60_000 })
  const ids = (projects.data ?? []).filter((p) => !projectId || p.id === projectId).slice(0, 12)
  const schedules = useQueries({
    queries: ids.map((p) => ({ queryKey: ['schedule', p.id], queryFn: () => fetchSchedule(p.id), enabled: wants.schedule, ...opts })),
  })
  const plans = useQueries({
    queries: ids.map((p) => ({ queryKey: ['material-plan', p.id, 4], queryFn: () => fetchMaterialPlan(p.id, 4), enabled: wants.plans, ...opts })),
  })

  if (!owner) return null
  const mine = (id: string | null | undefined) => !projectId || id === projectId
  const items: Item[] = []

  // Money to raise: work done on no bill yet.
  for (const p of toBill.data?.projects ?? []) {
    if (!mine(p.project_id)) continue
    items.push({ key: `bill-${p.project_id}`, tone: n(p.amount) >= 500000 ? 'bad' : 'attention', icon: FileText, verb: 'Raise the RA bill', what: `${plural(p.lines, 'line')} of work done`, project: p.project, amount: short(p.amount), to: `/billing/ra-bills?project=${p.project_id}` })
  }
  // Money to chase: each client's oldest unpaid bill.
  for (const c of receivables.data?.clients ?? []) {
    const bills = c.open_bills.filter((b) => mine(b.project_id))
    if (!bills.length) continue
    const left = bills.reduce((t, b) => t + n(b.left), 0)
    const days = Math.max(...bills.map((b) => b.days))
    items.push({ key: `chase-${c.client_id}`, tone: days > 60 ? 'bad' : days > 30 ? 'attention' : 'info', icon: HandCoins, verb: `Chase ${c.client}`, what: `${plural(bills.length, 'bill')} · oldest ${days} days`, project: bills.length === 1 ? (bills[0].project ?? undefined) : undefined, amount: short(left), to: '/accounts/receivables' })
  }
  // Projects heading over their budget.
  for (const p of portfolio.data?.projects ?? []) {
    if (!mine(p.project_id) || n(p.forecast_difference) >= 0 || !p.budget) continue
    const over = -n(p.forecast_difference)
    if (over / n(p.budget) < 0.02) continue
    items.push({ key: `over-${p.project_id}`, tone: over / n(p.budget) >= 0.1 ? 'bad' : 'attention', icon: TrendingDown, verb: 'Check the costs', what: `heading ${Math.round((over / n(p.budget)) * 100)}% over budget`, project: p.name, amount: short(over), to: `/accounts/projects/${p.project_id}` })
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
  // Suppliers to pay.
  const owe = payables.data?.totals
  if (owe && n(owe.overdue) > 0) items.push({ key: 'pay-suppliers', tone: 'bad', icon: Wallet, verb: 'Pay overdue suppliers', what: 'past their due day', amount: short(owe.overdue), to: '/finance/vendors' })
  // Wages.
  const w = wages.data
  if (w && n(w.due) > 0) items.push({ key: 'wages-pay', tone: 'attention', icon: Wallet, verb: 'Pay wages', what: plural(w.due_rows, 'person', 'people'), amount: short(w.due), to: '/labour/wages' })
  if (w && w.drafts > 0) items.push({ key: 'wages-approve', tone: 'attention', icon: ClipboardCheck, verb: `Approve ${plural(w.drafts, 'wage week')}`, what: 'before they can be paid', to: '/labour/wages' })
  // Requests and deliveries.
  const waiting = requests.data?.counts.waiting ?? 0
  if (waiting > 0) items.push({ key: 'requests', tone: (requests.data?.counts.late ?? 0) > 0 ? 'bad' : 'attention', icon: AlarmClock, verb: `Decide ${plural(waiting, 'material request')}`, what: (requests.data?.counts.late ?? 0) > 0 ? `${requests.data?.counts.late} past the date needed` : 'site is waiting', to: '/materials/requests' })
  const lateOrders = (orders.data?.items ?? []).filter((o) => (o.status === 'open' || o.status === 'part') && o.expected_date && o.expected_date < today).length
  if (lateOrders > 0) items.push({ key: 'deliveries', tone: 'bad', icon: Truck, verb: `${plural(lateOrders, 'delivery', 'deliveries')} late`, what: 'call the supplier', to: '/procurement/pending?show=late' })

  items.sort((a, b) => RANK[a.tone] - RANK[b.tone])
  const loading = [toBill, receivables, portfolio, projects].some((q) => q.isLoading)
  const shown = all ? items : items.slice(0, SHOWN)
  const urgent = items.filter((i) => i.tone === 'bad').length

  return (
    <section className="flex flex-col overflow-hidden rounded-xl border bg-card shadow-xs" data-guide="today.week" aria-label="This week">
      <header className="flex flex-wrap items-center gap-2 border-b px-4 py-2.5">
        <h2 className="text-[15px] font-semibold">This week</h2>
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
        <ul className="grid lg:grid-cols-2">
          {shown.map((it) => {
            const look = TONE[it.tone]
            return (
              <li key={it.key} className="border-b last:border-b-0 lg:odd:border-r lg:[&:nth-last-child(2):nth-child(odd)]:border-b-0">
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

function addDays(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00`)
  d.setDate(d.getDate() + days)
  return localIsoDate(d)
}
