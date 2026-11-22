import * as React from 'react'
import { useSearchParams } from 'react-router-dom'
import { useAuth } from '@/lib/AuthContext'
import { useScope } from '@/lib/ScopeContext'
import { useSetupProgress } from '@/lib/setup'
import { cn } from '@/lib/utils'
import { TitleBlock } from '@/components/page/page-kit'
import { useLook } from '@/lib/look'
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
  const [look] = useLook()
  const classic = look === 'classic'
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
      <TitleBlock
        eyebrow={
          <>
            {longDate(localIsoDate(now))}
            {scopeLabel ? ` · ${scopeLabel}` : ''}
          </>
        }
        title={
          <>
            {greeting(now)}
            {first ? `, ${first}` : ''}
          </>
        }
      >
        {status && (
          <span
            className={cn(
              'mt-1 inline-flex w-fit items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold',
              classic
                ? status.tone === 'bad' ? 'bg-destructive/10 text-destructive' : status.tone === 'attention' ? 'bg-draft-soft text-draft' : 'bg-success-soft text-success'
                : status.tone === 'bad' ? 'bg-[#f6dcd4] text-[#9a3320]' : status.tone === 'attention' ? 'bg-primary text-primary-foreground' : 'bg-white/12 text-white',
            )}
          >
            <span aria-hidden className={cn('size-1.5 rounded-full', status.tone === 'bad' ? 'bg-destructive' : status.tone === 'attention' ? (classic ? 'bg-draft' : 'bg-primary-foreground') : classic ? 'bg-success' : 'bg-[#7fd6ae]')} />
            {status.text}
          </span>
        )}
      </TitleBlock>

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
