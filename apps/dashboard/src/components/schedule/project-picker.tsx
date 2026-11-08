import { Link, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ChevronRight, FolderKanban } from 'lucide-react'
import { Skeleton } from '@/components/ui/skeleton'
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

const LINE_TONE = { bad: 'text-red-700 dark:text-red-300', warn: 'text-amber-700 dark:text-amber-300', good: 'text-success', muted: 'text-muted-foreground' }

export function ProjectPickList({ to, empty }: { to: (id: string) => string; empty: string }) {
  const projects = useQuery({ queryKey: ['lifecycle'], queryFn: fetchLifecycle })
  if (projects.isLoading) return <Skeleton className="h-40 rounded-xl" />
  if (!projects.data?.length) return <p className="text-sm text-muted-foreground">{empty}</p>
  return (
    <ul className="divide-y overflow-hidden rounded-xl border">
      {projects.data.map((p) => {
        const line = scheduleLine(p)
        return (
          <li key={p.id}>
            <Link to={to(p.id)} className="flex items-center gap-3 px-4 py-3 hover:bg-muted/50">
              <span className="flex size-9 items-center justify-center rounded-lg bg-muted"><FolderKanban className="size-4" /></span>
              <span className="min-w-0 flex-1">
                <span className="flex flex-wrap items-center gap-2"><span className="font-medium">{p.name}</span><StageChip stage={p.stage} label={p.stage_label} /></span>
                <span className={cn('block text-xs', LINE_TONE[line.tone])}>{line.text}{p.progress !== null ? ` · ${p.progress}% done` : ''}</span>
              </span>
              <ChevronRight className="size-4 text-muted-foreground" />
            </Link>
          </li>
        )
      })}
    </ul>
  )
}
