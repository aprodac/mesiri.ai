import * as React from 'react'
import { useQuery } from '@tanstack/react-query'
import { useAuth } from '@/lib/AuthContext'
import { useScope } from '@/lib/ScopeContext'
import { useModuleEnabled } from '@/lib/modules'
import { MONEY_ROLES } from '@/lib/module-map'
import { fetchHome, fetchMonths, mayReadBooks, short } from '@/lib/accounts'
import { fetchReceivables } from '@/lib/receivables'
import { fetchPayables } from '@/lib/vendors'
import { fetchRequests } from '@/lib/requests'
import { fetchOrders } from '@/lib/orders'
import { fetchPortfolio } from '@/lib/cost'
import { fetchMachines } from '@/lib/equipment'
import { fetchPaySummary } from '@/lib/labour-pay'
import { Section, Tile, TileGrid } from '@/components/page/page-kit'
import { localIsoDate, plural } from '@/lib/site-day'

// A home for each role (UX-11, docs/plans/ui-story-plan.md section 4b). Today opens with the role's own
// questions, each a tile that opens the page that answers it in full; the site-by-site day stays below. Every
// tile reads an API the dashboard already has, asks only when the role may read it and the module is on, and
// disappears if its API refuses, so a tile never shows a number the role cannot open.

type Role = 'ADMIN' | 'PROJECT_MANAGER' | 'SITE_ENGINEER' | 'FINANCE'

const TITLES: Record<Role, { title: string; note: string }> = {
  ADMIN: { title: 'Your company today', note: 'Money, what needs you, which project is slipping' },
  PROJECT_MANAGER: { title: 'Your projects today', note: 'What is waiting on you and what runs short' },
  SITE_ENGINEER: { title: 'Your site today', note: 'What is coming and what is still open' },
  FINANCE: { title: 'Your books today', note: 'What is due, what came in, what is not booked' },
}

const n = (v: string | number | null | undefined) => Number(v ?? 0) || 0
const monthName = (iso: string) => new Date(`${iso}T00:00:00`).toLocaleDateString('en-IN', { month: 'long', year: 'numeric' })

export function RoleHome() {
  const { me } = useAuth()
  const { scope } = useScope()
  const isModuleEnabled = useModuleEnabled()
  const rawRole = (me?.role || '').toUpperCase()
  const role: Role = (['ADMIN', 'PROJECT_MANAGER', 'SITE_ENGINEER', 'FINANCE'] as const).find((r) => r === rawRole) ?? 'ADMIN'
  const projectId = scope.mode === 'portfolio' ? undefined : scope.projectId
  const siteId = scope.mode === 'site' ? scope.siteId : undefined
  const today = React.useMemo(() => localIsoDate(new Date()), [])

  const books = mayReadBooks(rawRole) && isModuleEnabled('finance')
  const accountsOn = books && isModuleEnabled('accounts')
  const money = (MONEY_ROLES as readonly string[]).includes(rawRole) && isModuleEnabled('finance')
  const materials = isModuleEnabled('materials')
  const cost = (MONEY_ROLES as readonly string[]).includes(rawRole) && isModuleEnabled('cost')
  const equipment = isModuleEnabled('equipment')

  const wants = {
    home: accountsOn && (role === 'ADMIN' || role === 'FINANCE'),
    receivables: books && (role === 'ADMIN' || role === 'FINANCE'),
    payables: money && (role === 'ADMIN' || role === 'FINANCE'),
    months: accountsOn && role === 'FINANCE',
    requests: materials && role !== 'FINANCE',
    orders: materials && role !== 'FINANCE',
    portfolio: cost && (role === 'ADMIN' || role === 'PROJECT_MANAGER'),
    machines: equipment && (role === 'PROJECT_MANAGER' || role === 'SITE_ENGINEER'),
    // LW-08: wages approved and not paid, sheets waiting, advances still to take back (the roles that see wages).
    wages: isModuleEnabled('labour') && (MONEY_ROLES as readonly string[]).includes(rawRole),
  }
  const opts = { retry: false, staleTime: 60_000 } as const
  const home = useQuery({ queryKey: ['home', 'accounts', projectId], queryFn: () => fetchHome(projectId), enabled: wants.home, ...opts })
  const receivables = useQuery({ queryKey: ['home', 'receivables'], queryFn: fetchReceivables, enabled: wants.receivables, ...opts })
  const payables = useQuery({ queryKey: ['home', 'payables', projectId], queryFn: () => fetchPayables({ project_id: projectId }), enabled: wants.payables, ...opts })
  const months = useQuery({ queryKey: ['home', 'months'], queryFn: fetchMonths, enabled: wants.months, ...opts })
  const requests = useQuery({ queryKey: ['home', 'requests', projectId, siteId], queryFn: () => fetchRequests({ project_id: projectId, site_id: siteId }), enabled: wants.requests, ...opts })
  const orders = useQuery({ queryKey: ['home', 'orders', projectId, siteId], queryFn: () => fetchOrders({ project_id: projectId, site_id: siteId }), enabled: wants.orders, ...opts })
  const portfolio = useQuery({ queryKey: ['home', 'portfolio'], queryFn: fetchPortfolio, enabled: wants.portfolio, ...opts })
  const wagesQ = useQuery({ queryKey: ['home', 'wages'], queryFn: fetchPaySummary, enabled: wants.wages, ...opts })
  const machines = useQuery({ queryKey: ['home', 'machines', projectId, siteId], queryFn: () => fetchMachines({ project_id: projectId, site_id: siteId }), enabled: wants.machines, ...opts })

  const tiles: React.ReactNode[] = []
  const show = (q: { isError: boolean }, want: boolean) => want && !q.isError

  // --- the questions, in the order each role asks them -------------------------------------------------
  const cashTile = show(home, wants.home) && (home.data?.cash_bank || home.isLoading) && (
    <Tile key="cash" label="Cash and bank" to="/accounts/cash-bank" loading={home.isLoading} value={home.data?.cash_bank ? short(home.data.cash_bank.total) : undefined}
      hint={home.data?.cash_bank ? `${plural(home.data.cash_bank.accounts.length, 'account')} today` : undefined} />
  )
  const owedToUs = receivables.data
  const old = owedToUs ? n(owedToUs.buckets['61_90']) + n(owedToUs.buckets['90_plus']) : 0
  const receivableTile = show(receivables, wants.receivables) && (
    <Tile key="receivable" label="Clients owe you" to="/accounts/receivables" loading={receivables.isLoading} tone={old > 0 ? 'attention' : 'default'}
      value={owedToUs ? short(owedToUs.outstanding) : undefined}
      hint={owedToUs ? (old > 0 ? `${short(old)} over 60 days` : `${plural(owedToUs.clients.length, 'client')}`) : undefined} />
  )
  const owe = payables.data?.totals
  const payableTile = show(payables, wants.payables) && (
    <Tile key="payable" label={role === 'FINANCE' ? 'Payments due' : 'You owe suppliers'} to="/finance/vendors" loading={payables.isLoading}
      tone={owe && n(owe.overdue) > 0 ? 'bad' : 'default'} value={owe ? short(owe.payable) : undefined}
      hint={owe ? (n(owe.overdue) > 0 ? `${short(owe.overdue)} overdue` : 'Nothing overdue') : undefined} />
  )
  const unbilledTile = show(payables, wants.payables) && role === 'FINANCE' && owe && n(owe.unbilled) > 0 && (
    <Tile key="unbilled" label="Delivered, not billed" to="/finance/vendors" tone="attention" value={short(owe.unbilled)} hint="Deliveries waiting for the supplier's bill" />
  )
  const month = home.data?.this_month
  const profitTile = show(home, wants.home) && role === 'ADMIN' && (
    <Tile key="profit" label="Profit this month" to="/accounts/pl" loading={home.isLoading} tone={month && n(month.net_profit) < 0 ? 'bad' : 'default'}
      value={month ? short(month.net_profit) : undefined}
      hint={month ? `${short(month.income)} billed · ${short(n(month.direct) + n(month.indirect))} cost` : undefined} />
  )
  const gst = home.data?.gst_this_month
  const gstTile = show(home, wants.home) && role === 'FINANCE' && gst && (
    <Tile key="gst" label="GST this month" to="/accounts/gst" value={short(gst.payable)} hint={`${short(gst.output)} output · ${short(gst.input)} input`} />
  )
  const tdsTile = show(home, wants.home) && role === 'FINANCE' && home.data?.tds_to_deposit !== undefined && (
    <Tile key="tds" label="TDS to deposit" to="/accounts/tds" tone={n(home.data.tds_to_deposit) > 0 ? 'attention' : 'default'} value={short(home.data.tds_to_deposit)} hint="Due by the 7th" />
  )
  const lastOpen = months.data?.months.filter((m) => m.status === 'open' && m.ends_on < today).at(-1)
  const closeTile = show(months, wants.months) && months.data && (
    <Tile key="close" label="Month close" to="/accounts/periods" tone={lastOpen ? 'attention' : 'good'}
      value={lastOpen ? `${monthName(lastOpen.starts_on)} open` : 'Up to date'} hint={lastOpen ? 'Close it once the bills are in' : 'Every past month is closed'} />
  )
  const projectsRed = portfolio.data?.projects.filter((p) => p.colour === 'red') ?? []
  const redLines = portfolio.data?.projects.reduce((sum, p) => sum + (p.week?.red_lines ?? 0), 0) ?? 0
  const costTile = show(portfolio, wants.portfolio) && (portfolio.isLoading || (portfolio.data?.projects.length ?? 0) > 0) && (
    role === 'ADMIN' ? (
      <Tile key="cost" label="Projects over budget" to="/cost" loading={portfolio.isLoading} tone={projectsRed.length ? 'bad' : 'good'}
        value={portfolio.data ? `${projectsRed.length} of ${portfolio.data.projects.length}` : undefined}
        hint={projectsRed[0] ? `Worst: ${projectsRed[0].name}` : 'All on or under budget'} />
    ) : (
      <Tile key="red" label="Work items over budget this week" to="/cost/green-red" loading={portfolio.isLoading} tone={redLines ? 'bad' : 'good'}
        value={portfolio.data ? String(redLines) : undefined} hint={redLines ? 'Labour above what the work earned' : 'All green or amber'} />
    )
  )
  const waiting = requests.data?.counts.waiting ?? 0
  const late = requests.data?.counts.late ?? 0
  const requestTile = show(requests, wants.requests) && (
    <Tile key="requests" label={role === 'SITE_ENGINEER' ? 'Your requests' : 'Requests to decide'} to="/materials/requests" loading={requests.isLoading}
      tone={role !== 'SITE_ENGINEER' && waiting ? 'attention' : late ? 'bad' : 'default'}
      value={requests.data ? (role === 'SITE_ENGINEER' ? `${waiting} waiting` : String(waiting)) : undefined}
      hint={requests.data ? (late ? `${late} past the date needed` : `${requests.data.counts.ordered ?? 0} ordered`) : undefined} />
  )
  const openOrders = orders.data?.items.filter((o) => o.status === 'open' || o.status === 'part') ?? []
  const dueToday = openOrders.filter((o) => o.expected_date === today).length
  const lateOrders = openOrders.filter((o) => o.expected_date && o.expected_date < today).length
  const deliveryTile = show(orders, wants.orders) && (
    <Tile key="deliveries" label="Deliveries" to="/procurement/orders" loading={orders.isLoading} tone={lateOrders ? 'bad' : dueToday ? 'info' : 'default'}
      value={orders.data ? `${dueToday} due today` : undefined}
      hint={orders.data ? (lateOrders ? `${plural(lateOrders, 'order')} late` : `${plural(openOrders.length, 'order')} still coming`) : undefined} />
  )
  const machineCounts = machines.data?.counts
  const machineTile = show(machines, wants.machines) && (machines.isLoading || (machines.data?.items.length ?? 0) > 0) && (
    <Tile key="machines" label="Machines today" to="/equipment/log" loading={machines.isLoading}
      tone={machineCounts && (machineCounts.breakdown || machineCounts.not_logged) ? 'attention' : 'default'}
      value={machineCounts ? `${machineCounts.working} working` : undefined}
      hint={machineCounts ? [machineCounts.breakdown ? `${machineCounts.breakdown} broken down` : '', machineCounts.not_logged ? `${machineCounts.not_logged} not logged` : ''].filter(Boolean).join(' · ') || 'All logged' : undefined} />
  )
  const w = wagesQ.data
  const wagesTile = show(wagesQ, wants.wages) && (wagesQ.isLoading || (w && (n(w.due) > 0 || w.drafts > 0 || n(w.advances_outstanding) > 0))) && (
    <Tile key="wages" label="Wages" to="/labour/wages" loading={wagesQ.isLoading} tone={w && n(w.due) > 0 ? 'attention' : w && w.drafts ? 'info' : 'default'}
      value={w ? (n(w.due) > 0 ? `${short(w.due)} to pay` : w.drafts ? `${w.drafts} week${w.drafts > 1 ? 's' : ''} to approve` : 'Up to date') : undefined}
      hint={w ? (n(w.advances_outstanding) > 0 ? `${short(w.advances_outstanding)} advance to take back` : 'No advance outstanding') : undefined} />
  )
  const order: Record<Role, (React.ReactNode | false | null | undefined | 0)[]> = {
    // Sites reported and open issues are the strip right under these tiles, so they are not repeated here.
    ADMIN: [cashTile, profitTile, receivableTile, payableTile, wagesTile, costTile, requestTile],
    PROJECT_MANAGER: [requestTile, deliveryTile, wagesTile, costTile, machineTile],
    SITE_ENGINEER: [requestTile, deliveryTile, machineTile],
    FINANCE: [cashTile, payableTile, wagesTile, receivableTile, unbilledTile, gstTile, tdsTile, closeTile],
  }
  for (const tile of order[role]) if (tile) tiles.push(tile)
  if (tiles.length === 0) return null

  return (
    <Section title={TITLES[role].title} note={TITLES[role].note}>
      <TileGrid>{tiles}</TileGrid>
    </Section>
  )
}
