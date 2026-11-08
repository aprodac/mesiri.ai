import * as React from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  BadgeIndianRupee, CalendarCheck, Check, ClipboardCheck, Flag, Handshake, HardHat, KeyRound, ListTodo, ReceiptText, ShieldCheck, type LucideIcon,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useToast } from '@/components/ui/toast-notification'
import { PageError } from '@/components/dpr-page'
import { ProjectPickList, StageChip, usePlanningProject } from '@/components/schedule/project-picker'
import { billDay } from '@/lib/billing'
import { fetchHandover, setHandover, type HandoverStep } from '@/lib/closeout'
import { apiErrorMessage } from '@/lib/logo-upload'
import { usePageTitle } from '@/lib/page-title'
import { useReadOnly } from '@/lib/trial'
import { cn } from '@/lib/utils'

// END-03: Planning › Handover. The end of a project on one page, the mirror of Project start: work done, snags
// cleared, subcontractors settled, the final bill, the client paid, the handover day, the defect period, the
// retention back. Every step is read from what Mesiri already holds; each opens the place to do the rest. The money
// steps show only to the owner, admins and finance.

const ICONS: Record<HandoverStep['key'], LucideIcon> = {
  work: HardHat, snags: ListTodo, subcontracts: Handshake, final_bill: ReceiptText, paid: BadgeIndianRupee, handover: KeyRound,
  defects: ShieldCheck, retention: CalendarCheck,
}

export default function HandoverPage() {
  usePageTitle('Handover')
  const projectId = usePlanningProject()
  if (!projectId) {
    return (
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-4 pb-8 sm:px-2">
        <Heading />
        <p className="text-sm text-muted-foreground">Pick the project you are finishing.</p>
        <ProjectPickList to={(id) => `/planning/handover?project=${id}`} empty="No projects yet." />
      </div>
    )
  }
  return <HandoverView key={projectId} projectId={projectId} />
}

function Heading({ children }: { children?: React.ReactNode }) {
  return (
    <header className="flex flex-wrap items-center justify-between gap-3">
      <div className="flex items-center gap-3">
        <span className="inline-flex size-10 items-center justify-center rounded-xl bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200"><Flag className="size-5" /></span>
        <div>
          <div className="text-xs text-muted-foreground">Planning</div>
          <h1 className="text-2xl leading-tight font-semibold tracking-tight">Handover</h1>
        </div>
      </div>
      {children}
    </header>
  )
}

function HandoverView({ projectId }: { projectId: string }) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const readOnly = useReadOnly()
  const q = useQuery({ queryKey: ['handover', projectId], queryFn: () => fetchHandover(projectId) })
  const [day, setDay] = React.useState('')
  const save = useMutation({
    mutationFn: (body: { handed_over_on?: string; clear?: boolean }) => setHandover(projectId, body),
    onSuccess: (r) => {
      queryClient.setQueryData(['handover', projectId], r)
      for (const k of ['lifecycle', 'project-start', 'receivables']) queryClient.invalidateQueries({ queryKey: [k] })
      toast.success(r.handed_over_on ? `Handed over on ${billDay(r.handed_over_on)}` : 'Handover day removed')
    },
    onError: (e) => toast.error('Not saved', apiErrorMessage(e)),
  })

  if (q.isLoading) return <div className="mx-auto flex w-full max-w-4xl animate-pulse flex-col gap-4 sm:px-2"><div className="h-10 w-64 rounded bg-muted" /><div className="h-96 rounded-xl bg-muted/60" /></div>
  if (q.isError || !q.data) return <PageError message="The project did not load." onRetry={() => q.refetch()} back={{ to: '/planning/handover', label: 'All projects' }} />
  const d = q.data
  const canEdit = d.can_edit && !readOnly
  const pct = Math.round((d.done / d.total) * 100)

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-5 pb-12 sm:px-2">
      <Heading>
        <div className="flex items-center gap-2 text-sm">
          <Link to={`/projects/${projectId}`} className="font-medium hover:underline">{d.project.name}</Link>
          <StageChip stage={d.project.stage} label={d.project.stage_label} />
        </div>
      </Heading>
      <div className="flex items-center gap-3">
        <div className="h-2 flex-1 overflow-hidden rounded-full bg-muted"><div className="h-full rounded-full bg-success transition-all" style={{ width: `${pct}%` }} /></div>
        <span className="text-sm font-medium tabular-nums">{d.done} of {d.total} done</span>
      </div>
      {d.ready_to_close && (
        <div className="flex items-center gap-2 rounded-xl border border-success/25 bg-success-soft px-4 py-3 text-sm text-success">
          <ClipboardCheck className="size-5 shrink-0" />
          <span><strong>Nothing left.</strong> The project can be closed from Planning › Project start (stage: Closed).</span>
        </div>
      )}
      <ol className="flex flex-col gap-2">
        {d.steps.map((step, i) => {
          const Icon = ICONS[step.key]
          const next = d.next === step.key
          return (
            <li key={step.key} className={cn('flex flex-wrap items-start gap-3 rounded-xl border p-3', next && 'border-primary bg-primary/5', step.done && 'bg-muted/30')}>
              <span className={cn('flex size-9 shrink-0 items-center justify-center rounded-lg', step.done ? 'bg-success-soft text-success' : 'bg-muted')}>
                {step.done ? <Check className="size-4" /> : <Icon className="size-4" />}
              </span>
              <div className="min-w-0 flex-1">
                <p className="font-medium">{i + 1}. {step.title}{step.optional && <span className="ml-1 text-xs font-normal text-muted-foreground">(if any)</span>}{next && <span className="ml-2 text-xs font-semibold text-primary">Next</span>}</p>
                <p className="text-sm text-muted-foreground">{step.detail}</p>
                {step.key === 'handover' && canEdit && (
                  <form className="mt-2 flex flex-wrap items-center gap-2" onSubmit={(e) => { e.preventDefault(); save.mutate({ handed_over_on: day || undefined }) }}>
                    <Input type="date" className="h-8 w-44" value={day || d.handed_over_on || ''} max={d.today} onChange={(e) => setDay(e.target.value)} aria-label="Handover day" />
                    <Button size="sm" type="submit" disabled={save.isPending}>{d.handed_over_on ? 'Change' : 'Handed over'}</Button>
                    {d.handed_over_on && <Button size="sm" type="button" variant="ghost" disabled={save.isPending} onClick={() => save.mutate({ clear: true })}>Remove</Button>}
                    {!d.handed_over_on && <span className="text-xs text-muted-foreground">Leave empty for today. The stage moves to the defect period.</span>}
                  </form>
                )}
              </div>
              {step.link && !step.done && (
                <Button asChild size="sm" variant={next ? 'default' : 'outline'}>
                  <Link to={`${step.link}?project=${projectId}`}>Open</Link>
                </Button>
              )}
            </li>
          )
        })}
      </ol>
      {d.handed_over_on && (
        <p className="text-sm text-muted-foreground">
          Defect period: {billDay(d.handed_over_on)} to {d.defects_end ? billDay(d.defects_end) : '— (set the defect liability months in the contract)'}
          {d.defect_liability_months !== null && ` (${d.defect_liability_months} months)`}. Defects the client reports in it go on the <Link className="underline underline-offset-2" to={`/site/snags?project=${projectId}`}>snag list</Link>.
        </p>
      )}
    </div>
  )
}
