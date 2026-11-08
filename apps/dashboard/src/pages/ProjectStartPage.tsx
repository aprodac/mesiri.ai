import * as React from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowRight, Bell, CalendarDays, CalendarRange, Check, CheckCircle2, ChevronRight, FileSpreadsheet, Handshake, HardHat, MapPin,
  MessageCircle, Rocket, ScrollText, Store, TrendingUp, type LucideIcon,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useToast } from '@/components/ui/toast-notification'
import { PageError } from '@/components/dpr-page'
import { BoqImportDialog } from '@/components/schedule/boq-import-dialog'
import { ContractDialog } from '@/components/billing/contract-dialog'
import { useAuth } from '@/lib/AuthContext'
import { mayBill } from '@/lib/billing'
import { ProjectPickList, StageChip, usePlanningProject } from '@/components/schedule/project-picker'
import { apiErrorMessage } from '@/lib/logo-upload'
import { usePageTitle } from '@/lib/page-title'
import { fetchProjectStart, fetchSchedule, plural, shortDay, updateProjectStart, type ProjectStart, type Stage, type StartStep } from '@/lib/schedule'
import { useReadOnly } from '@/lib/trial'
import { cn } from '@/lib/utils'

// ST-05: Planning › Project start. The day a job is won, one page takes it to "work starts": the stage and the
// contract dates, the BOQ from the estimate Excel, the schedule, sites, the site team on WhatsApp, suppliers and
// opening stock, work orders. Each step says what is done and opens the place to do the rest; the next one is
// highlighted. Everything set here is used later by the DPR, purchasing, subcontracts and cost control.

const ICONS: Record<StartStep['key'], LucideIcon> = {
  dates: CalendarDays, contract: ScrollText, boq: FileSpreadsheet, schedule: CalendarRange, sites: MapPin, team: HardHat, suppliers: Store, work_orders: Handshake,
}

const WHY: Record<StartStep['key'], string> = {
  dates: 'The handover date is what the forecast is measured against.',
  contract: 'Retention, advance recovery, GST and TDS are worked out on every RA bill from these.',
  boq: 'Every work update, purchase and bill is checked against these lines.',
  schedule: 'Fills itself from site updates; delays reach you the same morning.',
  sites: 'Each site gets its own daily report.',
  team: 'Their WhatsApp messages are the data. No app to install.',
  suppliers: 'Orders, deliveries and bills match up from day one.',
  work_orders: 'Subcontract bills are checked against measured work.',
}

export default function ProjectStartPage() {
  usePageTitle('Project start')
  const projectId = usePlanningProject()
  if (!projectId) {
    return (
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-4 pb-8 sm:px-2">
        <Heading />
        <p className="text-sm text-muted-foreground">Pick the project you are starting.</p>
        <ProjectPickList to={(id) => `/planning/setup?project=${id}`} empty="No projects yet. Add one in Projects & Sites first." />
      </div>
    )
  }
  return <StartView key={projectId} projectId={projectId} />
}

function Heading({ children }: { children?: React.ReactNode }) {
  return (
    <header className="flex flex-wrap items-center justify-between gap-3">
      <div className="flex items-center gap-3">
        <span className="inline-flex size-10 items-center justify-center rounded-xl bg-violet-100 text-violet-800 dark:bg-violet-950 dark:text-violet-200"><Rocket className="size-5" /></span>
        <div>
          <div className="text-xs text-muted-foreground">Planning</div>
          <h1 className="text-2xl leading-tight font-semibold tracking-tight">Project start</h1>
        </div>
      </div>
      {children}
    </header>
  )
}

function StartView({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient()
  const toast = useToast()
  const readOnly = useReadOnly()
  const start = useQuery({ queryKey: ['project-start', projectId], queryFn: () => fetchProjectStart(projectId) })
  const schedule = useQuery({ queryKey: ['schedule', projectId], queryFn: () => fetchSchedule(projectId) })
  const [importing, setImporting] = React.useState(false)
  const update = useMutation({
    mutationFn: (body: { stage?: Stage; start_date?: string; planned_finish?: string }) => updateProjectStart(projectId, body),
    onSuccess: (r) => {
      queryClient.setQueryData(['project-start', projectId], r)
      for (const k of ['lifecycle', 'schedule']) queryClient.invalidateQueries({ queryKey: [k] })
      toast.success('Saved')
    },
    onError: (e) => toast.error('Not saved', apiErrorMessage(e)),
  })

  if (start.isLoading) return <div className="mx-auto flex w-full max-w-6xl animate-pulse flex-col gap-4 sm:px-2"><div className="h-10 w-64 rounded bg-muted" /><div className="h-24 rounded-xl bg-muted/60" /><div className="h-96 rounded-xl bg-muted/60" /></div>
  if (start.isError || !start.data) return <PageError message="The project did not load." onRetry={() => start.refetch()} back={{ to: '/planning/setup', label: 'All projects' }} />

  const d = start.data
  const canEdit = d.can_edit && !readOnly
  const pct = Math.round((d.done / d.total) * 100)
  const sched = schedule.data

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-5 pb-12 sm:px-2">
      <Heading>
        <div className="flex items-center gap-2 text-sm">
          <Link to={`/projects/${projectId}`} className="font-medium hover:underline">{d.project.name}</Link>
          <StageChip stage={d.project.stage} label={d.project.stage_label} />
        </div>
      </Heading>

      <StageTrack data={d} canEdit={canEdit} onPick={(stage) => update.mutate({ stage })} />

      <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,1fr)_340px]">
        <section className="flex flex-col gap-3">
          <div className="flex items-center gap-3">
            <div className="h-2 flex-1 overflow-hidden rounded-full bg-muted"><div className="h-full rounded-full bg-success transition-all" style={{ width: `${pct}%` }} /></div>
            <span className="text-sm font-medium tabular-nums">{d.done} of {d.total} done</span>
          </div>
          {d.ready && (
            <div className="flex items-center gap-2 rounded-xl border border-success/25 bg-success-soft px-4 py-3 text-sm text-success">
              <CheckCircle2 className="size-5 shrink-0" />
              <span><strong>Ready for site.</strong> From now on the site's WhatsApp updates fill the schedule, the daily report and the cost.</span>
            </div>
          )}
          <ol className="flex flex-col gap-2">
            {d.steps.map((step, i) => (
              <StepCard key={step.key} n={i + 1} step={step} next={d.next === step.key} projectId={projectId} data={d} canEdit={canEdit}
                saving={update.isPending} onDates={(body) => update.mutate(body)} onImport={() => setImporting(true)} />
            ))}
          </ol>
        </section>

        <aside className="flex flex-col gap-4 lg:sticky lg:top-4">
          {sched && sched.summary.scheduled > 0 && (
            <Link to={`/planning/schedule?project=${projectId}`} className="flex flex-col gap-2 rounded-xl border p-4 hover:bg-muted/40">
              <span className="flex items-center justify-between text-sm font-semibold"><span className="flex items-center gap-2"><CalendarRange className="size-4" /> Schedule today</span><ChevronRight className="size-4 text-muted-foreground" /></span>
              <span className="grid grid-cols-3 gap-2 text-center">
                <Mini label="Done" value={sched.summary.progress !== null ? `${sched.summary.progress}%` : '—'} />
                <Mini label="Late" value={String(sched.summary.counts.late ?? 0)} bad={!!sched.summary.counts.late} />
                <Mini label="Finish" value={shortDay(sched.summary.forecast_finish, sched.today)} bad={sched.summary.slip_days > 0} />
              </span>
            </Link>
          )}
          <div className="flex flex-col gap-3 rounded-xl border bg-muted/30 p-4 text-sm">
            <h2 className="font-semibold">What you get once this is set up</h2>
            <Benefit icon={FileSpreadsheet} title="Start in minutes, not days" text="The estimate Excel you already have becomes the BOQ, the budget and the schedule. Nothing typed twice." />
            <Benefit icon={MessageCircle} title="The schedule updates itself" text="Engineers keep sending WhatsApp updates as today. The bars fill in." />
            <Benefit icon={Bell} title="Delays reach you the same day" text="What is late, what it pushes and the new handover date, on WhatsApp each morning." />
            <Benefit icon={TrendingUp} title="One thread from start to finish" text="The same BOQ lines carry into purchases, work orders, cost and client bills." />
          </div>
        </aside>
      </div>

      <BoqImportDialog projectId={projectId} projectName={d.project.name} open={importing} onOpenChange={setImporting} />
    </div>
  )
}

function StageTrack({ data, canEdit, onPick }: { data: ProjectStart; canEdit: boolean; onPick: (s: Stage) => void }) {
  const at = data.stages.findIndex((s) => s.key === data.project.stage)
  return (
    <nav aria-label="Project stage" className="overflow-x-auto rounded-xl border p-1.5">
      <ol className="flex min-w-max items-center gap-1">
        {data.stages.map((s, i) => {
          const done = i < at
          const now = i === at
          return (
            <li key={s.key} className="flex items-center gap-1">
              <button type="button" disabled={!canEdit || now} onClick={() => onPick(s.key)} aria-current={now ? 'step' : undefined}
                title={canEdit && !now ? `Move the project to ${s.label}` : undefined}
                className={cn('flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm transition',
                  now ? 'bg-foreground font-semibold text-background' : done ? 'text-foreground hover:bg-muted' : 'text-muted-foreground hover:bg-muted',
                  !canEdit && 'cursor-default')}>
                <span className={cn('flex size-5 items-center justify-center rounded-full text-[11px] font-bold', now ? 'bg-background text-foreground' : done ? 'bg-success text-white' : 'bg-muted')}>
                  {done ? <Check className="size-3" /> : i + 1}
                </span>
                {s.label}
              </button>
              {i < data.stages.length - 1 && <ChevronRight className="size-4 text-muted-foreground/50" />}
            </li>
          )
        })}
      </ol>
    </nav>
  )
}

function StepCard({
  n, step, next, projectId, data, canEdit, saving, onDates, onImport,
}: {
  n: number
  step: StartStep
  next: boolean
  projectId: string
  data: ProjectStart
  canEdit: boolean
  saving: boolean
  onDates: (b: { start_date?: string; planned_finish?: string }) => void
  onImport: () => void
}) {
  const Icon = ICONS[step.key]
  const { me } = useAuth()
  const [contractOpen, setContractOpen] = React.useState(false)
  const [startDate, setStartDate] = React.useState(data.project.start_date ?? '')
  const [finish, setFinish] = React.useState(data.project.planned_finish ?? '')
  React.useEffect(() => { setStartDate(data.project.start_date ?? ''); setFinish(data.project.planned_finish ?? '') }, [data.project.start_date, data.project.planned_finish])
  const months = startDate && finish ? Math.round((new Date(finish).getTime() - new Date(startDate).getTime()) / (30.44 * 86_400_000)) : null

  const actions: Record<StartStep['key'], React.ReactNode> = {
    dates: null,
    contract: mayBill(me?.role) ? (
      <>
        <Button size="sm" variant={step.done ? 'outline' : 'default'} onClick={() => setContractOpen(true)} className="gap-1.5"><ScrollText className="size-4" /> {step.done ? 'Contract terms' : 'Set the client and contract'}</Button>
        {step.done && <Button size="sm" variant="ghost" asChild><Link to={`/billing/ra-bills?project=${projectId}`}>RA bills <ArrowRight className="size-3.5" /></Link></Button>}
        <ContractDialog projectId={projectId} open={contractOpen} onOpenChange={setContractOpen} />
      </>
    ) : <span className="text-xs text-muted-foreground">Set by the owner, an admin or finance.</span>,
    boq: (
      <>
        {canEdit && <Button size="sm" variant={step.done ? 'outline' : 'default'} onClick={onImport} className="gap-1.5"><FileSpreadsheet className="size-4" /> {step.done ? 'Import more' : 'Upload the BOQ Excel'}</Button>}
        {step.done && <Button size="sm" variant="ghost" asChild><Link to={`/projects/${projectId}/boq`}>Open the BOQ <ArrowRight className="size-3.5" /></Link></Button>}
      </>
    ),
    schedule: <Button size="sm" variant={next ? 'default' : 'outline'} asChild><Link to={`/planning/schedule?project=${projectId}`} className="gap-1.5"><CalendarRange className="size-4" /> {step.done ? 'Open the schedule' : 'Plan the schedule'}</Link></Button>,
    sites: <Button size="sm" variant="outline" asChild><Link to={`/projects/${projectId}`}>{step.done ? 'Sites' : 'Add a site'} <ArrowRight className="size-3.5" /></Link></Button>,
    team: <Button size="sm" variant={next ? 'default' : 'outline'} asChild><Link to={`/projects/${projectId}`}>{step.done ? 'The team' : 'Add the site engineer'} <ArrowRight className="size-3.5" /></Link></Button>,
    suppliers: (
      <>
        <Button size="sm" variant="outline" asChild><Link to="/finance/vendors">Suppliers</Link></Button>
        <Button size="sm" variant="ghost" asChild><Link to="/materials?view=items">Items & opening stock <ArrowRight className="size-3.5" /></Link></Button>
      </>
    ),
    work_orders: <Button size="sm" variant="outline" asChild><Link to="/subcontract/work-orders">Work orders <ArrowRight className="size-3.5" /></Link></Button>,
  }

  return (
    <li className={cn('flex gap-3 rounded-xl border p-4 transition', next && 'border-primary/60 bg-primary/5 shadow-sm ring-1 ring-primary/30', step.done && !next && 'bg-card')}>
      <span className={cn('flex size-9 shrink-0 items-center justify-center rounded-lg', step.done ? 'bg-success-soft text-success' : next ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground')}>
        {step.done ? <Check className="size-5" strokeWidth={3} /> : <Icon className="size-4" />}
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-2">
        <div className="flex flex-wrap items-baseline gap-x-2">
          <span className="text-xs text-muted-foreground tabular-nums">{n}</span>
          <h3 className="font-semibold">{step.title}</h3>
          {step.optional && <span className="text-xs text-muted-foreground">optional</span>}
          {next && <span className="rounded-full bg-primary px-2 py-0.5 text-[11px] font-bold text-primary-foreground">Next</span>}
        </div>
        <p className="text-sm text-muted-foreground">{step.detail}</p>
        <p className="text-xs text-foreground/60">{WHY[step.key]}</p>
        {step.key === 'dates' ? (
          canEdit ? (
            <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); onDates({ start_date: startDate || undefined, planned_finish: finish || undefined }) }}>
              <div className="flex flex-col gap-1"><Label htmlFor="ps-start" className="text-xs">Work starts</Label><Input id="ps-start" type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} className="w-40" /></div>
              <div className="flex flex-col gap-1"><Label htmlFor="ps-finish" className="text-xs">Handover (contract)</Label><Input id="ps-finish" type="date" value={finish} min={startDate || undefined} onChange={(e) => setFinish(e.target.value)} className="w-40" /></div>
              <Button size="sm" type="submit" disabled={saving || (!startDate && !finish) || (startDate === (data.project.start_date ?? '') && finish === (data.project.planned_finish ?? ''))}>Save dates</Button>
              {months !== null && months >= 0 && <span className="pb-2 text-xs text-muted-foreground">{plural(months, 'month')}</span>}
            </form>
          ) : (
            <p className="text-sm">{shortDay(data.project.start_date)} → {shortDay(data.project.planned_finish)}</p>
          )
        ) : (
          <div className="flex flex-wrap items-center gap-2">{actions[step.key]}</div>
        )}
      </div>
    </li>
  )
}

function Mini({ label, value, bad }: { label: string; value: string; bad?: boolean }) {
  return (
    <span className="flex flex-col rounded-lg bg-muted/50 px-2 py-1.5">
      <span className={cn('text-base font-semibold tabular-nums', bad && 'text-red-700 dark:text-red-300')}>{value}</span>
      <span className="text-[11px] text-muted-foreground">{label}</span>
    </span>
  )
}

function Benefit({ icon: Icon, title, text }: { icon: LucideIcon; title: string; text: string }) {
  return (
    <div className="flex gap-2.5">
      <span className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-lg bg-background text-foreground/80 shadow-sm"><Icon className="size-3.5" /></span>
      <div><div className="font-medium">{title}</div><div className="text-muted-foreground">{text}</div></div>
    </div>
  )
}
