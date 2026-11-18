import * as React from 'react'
import { Link } from 'react-router-dom'
import { CalendarDays, MessageSquarePlus } from 'lucide-react'
import { useAuth } from '@/lib/AuthContext'
import { useScope } from '@/lib/ScopeContext'
import { useReadOnly } from '@/lib/trial'
import { appNow } from '@/lib/clock'
import { localIsoDate, longDate } from '@/lib/site-day'
import { openTellMesiri } from '@/lib/tell-mesiri-events'
import { RoleHome } from '@/components/home/role-home'
import { ThisWeek } from '@/components/home/this-week'
import { ProjectsNow } from '@/components/home/projects-now'
import { MyTasksCard } from '@/components/tasks/my-tasks-card'
import { TimeSaved } from '@/components/time-saved'
import { GettingStartedCard } from '@/components/getting-started-card'
import { SupplierPapersWaiting, SuppliersWaiting } from '@/components/vendors/vendor-parts'
import { BillsWaitingLine } from '@/components/subcontracts/parts'

// UX-68 (asked 18 Nov 2026: "is Today supposed to be the home page?" -> no, a Home of its own). Home answers "what do
// I do, and how are we doing", whatever the day: the greeting, the role's own figures first (finance's cash, the
// owner's money, the project manager's requests and deliveries), This week, the projects one line each (owner and
// project manager), tasks, and what waits on suppliers and bills. Today stays the site's day (sites, the daily report,
// issues, other days). Everyone lands here, except site engineers, who land on Today (App.tsx Landing).

function greeting(now: Date): string {
  const h = now.getHours()
  return h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : 'Good evening'
}

export default function HomePage() {
  const { me } = useAuth()
  const { scope } = useScope()
  const readOnly = useReadOnly()
  const [now] = React.useState(() => appNow())
  const first = (me?.name || me?.full_name || '').trim().split(/\s+/)[0]
  const scopeLabel = scope.mode === 'site' ? scope.siteName : scope.mode === 'project' ? scope.projectName : null
  return (
    <div className="mx-auto flex w-full flex-col gap-5 pb-8 sm:px-2">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold tracking-tight">
            {greeting(now)}
            {first ? `, ${first}` : ''}
          </h1>
          <p className="mt-0.5 text-sm text-muted-foreground">
            {longDate(localIsoDate(now))}
            {scopeLabel ? ` · ${scopeLabel}` : ''}
          </p>
        </div>
        <div className="flex items-center gap-1.5">
          {!readOnly && (
            <button
              type="button"
              onClick={() => openTellMesiri()}
              className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-primary px-3 text-sm font-semibold text-primary-foreground shadow-xs transition-colors hover:bg-primary/90"
            >
              <MessageSquarePlus className="size-4" /> <span className="hidden sm:inline">Tell Mesiri</span>
            </button>
          )}
          <Link to="/today" className="inline-flex h-8 items-center gap-1.5 rounded-lg border bg-card px-2.5 text-sm hover:bg-muted" data-guide="home.today">
            <CalendarDays className="size-4 text-primary-ink" /> Today on site
          </Link>
        </div>
      </header>

      <GettingStartedCard />
      <div data-guide="home.figures">
        <RoleHome />
      </div>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_340px] xl:grid-cols-[minmax(0,1fr)_380px]">
        <div className="flex min-w-0 flex-col gap-5">
          <ThisWeek />
          <ProjectsNow />
        </div>
        <aside className="flex min-w-0 flex-col gap-5">
          <MyTasksCard />
          <SuppliersWaiting />
          <SupplierPapersWaiting />
          <BillsWaitingLine />
          <TimeSaved />
        </aside>
      </div>
    </div>
  )
}
