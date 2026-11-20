import { Link, Navigate, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ChevronRight, FolderKanban } from 'lucide-react'
import { Skeleton } from '@/components/ui/skeleton'
import { NewProjectButton } from '@/components/new-project-button'
import { initialsOf } from '@/lib/initials'
import { useScope } from '@/lib/ScopeContext'
import { fetchLifecycle, plural, shortDay, type ProjectLifecycle } from '@/lib/schedule'
import { cn } from '@/lib/utils'

// ST-01: the project a planning page is about: ?project= in the address, else the project picked in the top bar.
export function usePlanningProject(): string | null {
  const [params] = useSearchParams()
  const { scope } = useScope()
  return params.get('project') ?? (scope.mode === 'project' || scope.mode === 'site' ? scope.projectId : null)
}

export const STAGE_TONE: Record<string, string> = {
  tender: 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200',
  won: 'bg-violet-100 text-violet-800 dark:bg-violet-950 dark:text-violet-200',
  running: 'bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-200',
  handover: 'bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200',
  defects: 'bg-orange-100 text-orange-800 dark:bg-orange-950 dark:text-orange-200',
  closed: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200',
}

export function StageChip({ stage, label, className }: { stage: string; label: string; className?: string }) {
  return <span className={cn('inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold', STAGE_TONE[stage] ?? STAGE_TONE.running, className)}>{label}</span>
}

/** One line about how a project's schedule stands: for the Projects list and the pickers. */
export function scheduleLine(p: ProjectLifecycle): { text: string; tone: 'bad' | 'warn' | 'good' | 'muted' } {
  if (!p.scheduled) return { text: p.activities ? `${plural(p.activities, 'section')}, no dates yet` : 'No schedule yet', tone: 'muted' }
  if (p.late) return { text: `${p.late} late${p.slip_days ? ` · finish +${p.slip_days}d` : ''}`, tone: 'bad' }
  if (p.behind) return { text: `${p.behind} behind${p.slip_days ? ` · finish +${p.slip_days}d` : ''}`, tone: 'warn' }
  return { text: `On time${p.planned_finish ? ` · handover ${shortDay(p.planned_finish)}` : ''}`, tone: 'good' }
}

// Colour marks only a problem (UX-19): late red, behind amber; on time and no schedule stay plain.
const LINE_TONE = { bad: 'text-red-700 dark:text-red-300', warn: 'text-amber-700 dark:text-amber-300', good: 'text-foreground/70', muted: 'text-muted-foreground' }

/** Each project keeps one colour for its tile, from its id, so it is recognised at a glance on every page. */
const TILE = ['#2563EB', '#7C3AED', '#0D9488', '#C2410C', '#BE185D', '#4D7C0F', '#0369A1', '#A16207']
function tileColour(id: string): string {
  let h = 0
  for (const c of id) h = (h * 31 + c.charCodeAt(0)) >>> 0
  return TILE[h % TILE.length]
}

/**
 * The "which project?" screen of every page that works on one project (Schedule, Project start, RA bills, Places …).
 * UX-35 (18 Nov, asked: "upgrade the UI/UX of such screens with project selection"): a card per project with its own
 * colour, client, stage, how much is done and how its schedule stands, a New project card for those who may make
 * one; with only one project there is nothing to choose, so it opens straight away.
 */
export function ProjectPickList({ to, empty, newProject = true }: { to: (id: string) => string; empty: string; newProject?: boolean }) {
  const projects = useQuery({ queryKey: ['lifecycle'], queryFn: fetchLifecycle })
  if (projects.isLoading) {
    return (
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {[0, 1, 2].map((i) => <Skeleton key={i} className="h-36 rounded-xl" />)}
      </div>
    )
  }
  const list = projects.data ?? []
  if (list.length === 1) return <Navigate to={to(list[0].id)} replace />
  if (list.length === 0) {
    return (
      <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed px-4 py-12 text-center">
        <span className="flex size-11 items-center justify-center rounded-xl bg-muted"><FolderKanban className="size-5 text-muted-foreground" aria-hidden /></span>
        <p className="m-0 max-w-sm text-sm text-muted-foreground">{empty}</p>
        {newProject && <NewProjectButton size="default" className="gap-1.5" />}
      </div>
    )
  }
  return (
    <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3" data-guide="project.pick">
      {list.map((p) => {
        const line = scheduleLine(p)
        const done = p.progress ?? 0
        return (
          <li key={p.id}>
            <Link
              to={to(p.id)}
              className="group flex h-full flex-col gap-4 rounded-xl border bg-card p-4 transition hover:-translate-y-px hover:border-foreground/25 hover:shadow-md focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
            >
              <span className="flex items-start gap-3">
                <span
                  className="flex size-10 shrink-0 items-center justify-center rounded-lg text-sm font-bold text-white"
                  style={{ backgroundColor: tileColour(p.id) }}
                  aria-hidden
                >
                  {initialsOf(p.name)}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-base font-semibold">{p.name}</span>
                  <span className="block truncate text-sm text-muted-foreground">{p.client ? `For ${p.client}` : 'No client set'}</span>
                </span>
                <StageChip stage={p.stage} label={p.stage_label} className="shrink-0" />
              </span>
              <span className="flex flex-col gap-1.5">
                {/* "Done" is measured on the BOQ: with none there is no measure, which is not "not started" (a running
                    site with no BOQ read "Not started", 20 Nov test). */}
                <span className="flex items-baseline justify-between gap-2 text-sm">
                  <span className="font-semibold tabular-nums">{p.progress !== null ? `${p.progress}% done` : p.activities ? 'Nothing measured yet' : 'No BOQ yet'}</span>
                  <span className={cn('truncate text-xs', LINE_TONE[line.tone])}>{line.text}</span>
                </span>
                <span className="block h-1.5 overflow-hidden rounded-full bg-muted" role="img" aria-label={`${done}% done`}>
                  <span className={cn('block h-full rounded-full', line.tone === 'bad' ? 'bg-red-500' : line.tone === 'warn' ? 'bg-amber-500' : 'bg-info')} style={{ width: `${Math.min(100, done)}%` }} />
                </span>
              </span>
              <span className="mt-auto flex items-center justify-between text-xs text-muted-foreground">
                <span className="tabular-nums">{p.planned_finish ? `Handover ${shortDay(p.planned_finish)}` : 'No handover date'}</span>
                <span className="inline-flex items-center gap-0.5 font-medium text-foreground/80 group-hover:text-foreground">
                  Open <ChevronRight className="size-3.5 transition-transform group-hover:translate-x-0.5" aria-hidden />
                </span>
              </span>
            </Link>
          </li>
        )
      })}
    </ul>
  )
}
