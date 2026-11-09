import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { CircleCheck } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { fetchSchedule } from '@/lib/schedule'
import { fetchAttention } from '@/lib/attention'
import { Section } from '@/components/page/page-kit'
import { cn } from '@/lib/utils'

// GM-03 on main's project hub (UX-12): the answer before the links -- the handover forecast against its date, and
// why the project is red or amber today: its top three Attention alerts (GM-04), each with the page that acts on it.
// Both are the modules' own reads; nothing here is worked out twice.

const day = (iso: string | null | undefined) => (iso ? new Date(iso + 'T00:00:00').toLocaleDateString('en-IN', { day: 'numeric', month: 'short' }) : '')

export function ProjectWhy({ projectId }: { projectId: string }) {
  const opts = { retry: false, staleTime: 60_000 } as const
  const schedule = useQuery({ queryKey: ['hub', 'schedule', projectId], queryFn: () => fetchSchedule(projectId), ...opts })
  const attention = useQuery({ queryKey: ['hub', 'attention', projectId], queryFn: () => fetchAttention(projectId), ...opts })
  if (attention.isError && schedule.isError) return null
  const alerts = attention.data?.items ?? []
  const worst = alerts.some((a) => a.severity === 'bad') ? 'bad' : alerts.length ? 'warn' : 'ok'
  const s = schedule.data?.summary
  const handover = s?.forecast_finish
    ? s.slip_days ? `Handover forecast ${day(s.forecast_finish)}, ${s.slip_days} days after ${s.contract_finish ? 'the contract date' : 'the plan'} (${day(s.contract_finish ?? s.planned_finish)})`
      : `Handover on plan, ${day(s.forecast_finish)}`
    : null

  return (
    <Section title={worst === 'ok' ? 'How it is going' : `Why it is ${worst === 'bad' ? 'red' : 'amber'}`}
      note={handover ?? undefined}
      action={alerts.length > 3 ? <Link to={`/site/attention?project=${projectId}`} className="text-sm font-medium text-primary-ink hover:underline">All {alerts.length} in Attention</Link> : undefined}>
      <div className={cn('grid grid-cols-[5px_minmax(0,1fr)] overflow-hidden rounded-xl border bg-card')}>
        <span className={worst === 'bad' ? 'bg-red-600' : worst === 'warn' ? 'bg-amber-500' : 'bg-emerald-600'} aria-hidden />
        <div className="flex flex-col gap-3 p-4">
          {attention.isLoading && <div className="h-10 animate-pulse rounded bg-muted/50" />}
          {!attention.isLoading && alerts.length === 0 && (
            <p className="flex items-center gap-2 text-sm"><CircleCheck className="size-4 text-success" />Nothing has crossed a line on this project.</p>
          )}
          {alerts.slice(0, 3).map((a, i) => (
            <div key={a.key} className="grid grid-cols-[18px_minmax(0,1fr)] items-start gap-x-3 gap-y-2 sm:grid-cols-[18px_minmax(0,1fr)_auto]">
              <span className="pt-0.5 font-mono text-xs text-muted-foreground">{i + 1}</span>
              <div className="min-w-0">
                <div className="font-semibold">{a.title}{a.site_name ? <span className="font-normal text-muted-foreground"> · {a.site_name}</span> : null}</div>
                <div className="text-sm text-muted-foreground">{a.detail}</div>
              </div>
              <Button asChild size="sm" variant="outline" className="col-start-2 justify-self-start sm:col-start-auto"><Link to={a.action.link}>{a.action.label}</Link></Button>
            </div>
          ))}
        </div>
      </div>
    </Section>
  )
}
