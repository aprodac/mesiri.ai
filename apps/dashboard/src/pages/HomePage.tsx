import * as React from 'react'
import { useSearchParams } from 'react-router-dom'
import { useAuth } from '@/lib/AuthContext'
import { useScope } from '@/lib/ScopeContext'
import { useSetupProgress } from '@/lib/setup'
import { cn } from '@/lib/utils'
import { appNow } from '@/lib/clock'
import { localIsoDate, longDate } from '@/lib/site-day'
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
  const [now] = React.useState(() => appNow())
  const [params] = useSearchParams()
  const setup = useSetupProgress()
  const [count, setCount] = React.useState<{ total: number; urgent: number } | null>(null)
  const first = (me?.name || me?.full_name || '').trim().split(/\s+/)[0]
  const scopeLabel = scope.mode === 'site' ? scope.siteName : scope.mode === 'project' ? scope.projectName : null
  // UX-75: the checklist is the sidebar's "Set up" (UX-74) in full: shown here while no site has sent its first
  // update, or when asked for ("N more steps" opens /home?setup=1); otherwise the sidebar carries the next step.
  const showChecklist = params.get('setup') === '1' || (setup.isCompanyAdmin && setup.data?.first_update_at === null)
  const status = !count
    ? null
    : count.urgent > 0
      ? { tone: 'bad' as const, text: `${count.urgent} urgent ${count.urgent === 1 ? 'thing needs' : 'things need'} you${count.total > count.urgent ? `, ${count.total - count.urgent} more this week` : ''}` }
      : count.total > 0
        ? { tone: 'attention' as const, text: `${count.total} ${count.total === 1 ? 'thing needs' : 'things need'} you this week` }
        : { tone: 'good' as const, text: 'Nothing needs you right now' }
  return (
    <div className="mx-auto flex w-full flex-col gap-5 pb-8 sm:px-2">
      {/* UX-75 (asked 20 Nov 2026: "the home page is the one with the worst design"): what needs you first (exceptions
          first, the figures beside it, not a row of equal cards on top); the page's own Tell Mesiri and Today
          buttons went: the top bar's New and the sidebar's Today are one tap away on every page. */}
      <header className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold tracking-tight">
          {greeting(now)}
          {first ? `, ${first}` : ''}
        </h1>
        <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-muted-foreground">
          <span>
            {longDate(localIsoDate(now))}
            {scopeLabel ? ` · ${scopeLabel}` : ''}
          </span>
          {status && (
            <span
              className={cn(
                'inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold',
                status.tone === 'bad' ? 'bg-destructive/10 text-destructive' : status.tone === 'attention' ? 'bg-draft-soft text-draft' : 'bg-success-soft text-success',
              )}
            >
              <span aria-hidden className={cn('size-1.5 rounded-full', status.tone === 'bad' ? 'bg-destructive' : status.tone === 'attention' ? 'bg-draft' : 'bg-success')} />
              {status.text}
            </span>
          )}
        </p>
      </header>

      {showChecklist && <GettingStartedCard />}

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_340px] xl:grid-cols-[minmax(0,1fr)_380px]">
        <div className="flex min-w-0 flex-col gap-5">
          <ThisWeek onCount={setCount} />
          <ProjectsNow />
        </div>
        <aside className="flex min-w-0 flex-col gap-5">
          <div data-guide="home.figures">
            <RoleHome list />
          </div>
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
