import { useQuery } from '@tanstack/react-query'
import { ProjectWhy } from '@/components/home/project-why'
import { useAuth } from '@/lib/AuthContext'
import { useModuleEnabled } from '@/lib/modules'
import { MONEY_ROLES } from '@/lib/module-map'
import { mayReadProjectBooks, short } from '@/lib/accounts'
import { fetchPortfolio } from '@/lib/cost'
import { fetchRequests } from '@/lib/requests'
import { fetchOrders } from '@/lib/orders'
import { Section, Tile, TileGrid } from '@/components/page/page-kit'
import { plural } from '@/lib/site-day'

// The project hub (UX-12, docs/plans/ui-story-plan.md section 4c): one project across every module, in the
// order of its story (plan, site, buy, money). Each tile opens its module already scoped to the project
// (?project= is read by ScopeContext on every page), so the project page is where a project's threads meet.

export function ProjectHub({ projectId }: { projectId: string }) {
  const { me } = useAuth()
  const role = (me?.role || '').toUpperCase()
  const isModuleEnabled = useModuleEnabled()
  const money = (MONEY_ROLES as readonly string[]).includes(role)
  const materials = isModuleEnabled('materials')
  const cost = money && isModuleEnabled('cost')
  const q = `project=${projectId}`
  const opts = { retry: false, staleTime: 60_000 } as const

  const portfolio = useQuery({ queryKey: ['home', 'portfolio'], queryFn: fetchPortfolio, enabled: cost, ...opts })
  const requests = useQuery({ queryKey: ['home', 'requests', projectId, undefined], queryFn: () => fetchRequests({ project_id: projectId }), enabled: materials, ...opts })
  const orders = useQuery({ queryKey: ['home', 'orders', projectId, undefined], queryFn: () => fetchOrders({ project_id: projectId }), enabled: materials, ...opts })

  const row = portfolio.data?.projects.find((p) => p.project_id === projectId)
  const openOrders = orders.data?.items.filter((o) => o.status === 'open' || o.status === 'part').length ?? 0
  const waiting = requests.data?.counts.waiting ?? 0

  return (
    <>
    <ProjectWhy projectId={projectId} />
    <Section title="This project across Mesiri" note="Each opens already filtered to this project">
      <TileGrid className="xl:grid-cols-4">
        <Tile label="Plan" to={`/planning/schedule?${q}`} value="Schedule" hint="What is late and what it pushes" />
        <Tile label="Plan" to={`/projects/${projectId}/boq`} value="BOQ & budget" hint="Quantities, client and budget rates" />
        <Tile label="Plan" to={`/planning/documents?${q}`} value="Documents" hint="Latest revisions, permits, contract" />
        <Tile label="Site" to={`/today?${q}`} value="Today's updates" hint="What each site sent today" />
        {materials && <Tile label="Site" to={`/materials?view=stock&${q}`} value="Stock" hint="What is there and how long it lasts" />}
        {isModuleEnabled('labour') && <Tile label="Site" to={`/labour?${q}`} value="Labour" hint="Attendance, muster roll, teams" />}
        {isModuleEnabled('equipment') && <Tile label="Site" to={`/equipment?${q}`} value="Machines" hint="Hours, idle, diesel, hire" />}
        {materials && (
          <Tile label="Buy · Requests" to={`/materials/requests?${q}`} loading={requests.isLoading} tone={waiting ? 'attention' : 'default'}
            value={requests.data ? `${waiting} waiting` : undefined} hint="What the sites asked for" />
        )}
        {materials && (
          <Tile label="Buy · Orders" to={`/procurement/orders?${q}`} loading={orders.isLoading}
            value={orders.data ? `${openOrders} open` : undefined} hint={orders.data ? plural(orders.data.items.length, 'order') + ' in all' : undefined} />
        )}
        {money && <Tile label="Buy" to={`/subcontract/work-orders?${q}`} value="Work orders" hint="Who does which work at what rate" />}
        {isModuleEnabled('labour') && money && <Tile label="Money" to={`/labour/wages?${q}`} value="Wages" hint="This week's pay, advances taken back" />}
        {cost && (
          <Tile label="Money · Budget vs actual" to={`/cost/budget?${q}`} loading={portfolio.isLoading}
            tone={row?.colour === 'red' ? 'bad' : row?.colour === 'green' ? 'good' : row?.colour === 'amber' ? 'attention' : 'default'}
            value={row ? short(row.spent) : 'Not set up'} hint={row?.budget ? `spent of ${short(row.budget)} budget` : 'No budget yet: add the BOQ'} />
        )}
        {money && role !== 'PROJECT_MANAGER' && <Tile label="Money" to={`/billing/ra-bills?${q}`} value="Client bills" hint="Bill the work measured since the last bill" />}
        {mayReadProjectBooks(role) && isModuleEnabled('finance') && (
          <Tile label="Money" to={`/accounts/projects/${projectId}`} value="Profit and loss" hint="Billed against every cost booked" />
        )}
      </TileGrid>
    </Section>
    </>
  )
}
