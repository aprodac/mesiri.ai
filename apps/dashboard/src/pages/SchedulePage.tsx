import * as React from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle, CalendarCheck2, CalendarRange, CheckCircle2, Clock, FileSpreadsheet, Flame, Gauge, ListOrdered, MessageCircle, Plus, Rocket,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet'
import { useToast } from '@/components/ui/toast-notification'
import { Callout, PageError, Segmented, StatStrip, type Stat } from '@/components/dpr-page'
import { ActivityPanel, StateChip } from '@/components/schedule/activity-panel'
import { BoqImportDialog } from '@/components/schedule/boq-import-dialog'
import { AddActivityDialog, ConfirmChangeDialog, QuickPlanDialog } from '@/components/schedule/dialogs'
import { Gantt, STATE_BAR, type Zoom } from '@/components/schedule/gantt'
import { ProjectPickList, StageChip, usePlanningProject } from '@/components/schedule/project-picker'
import { useIsMobile } from '@/hooks/use-mobile'
import { apiErrorMessage } from '@/lib/logo-upload'
import { usePageTitle } from '@/lib/page-title'
import {
  addDays, createActivity, dayNum, daysBetween, deleteActivity, fetchSchedule, plural, sequenceActivities, shortDay, updateActivity,
  type Activity, type ActivityUpdate, type Schedule, type ScheduleChange,
} from '@/lib/schedule'
import { useReadOnly } from '@/lib/trial'
import { cn } from '@/lib/utils'
import { ModuleTitle } from '@/components/page/page-kit'

// ST-04: Planning › Schedule. The project's Gantt: what should happen when, what site has actually done (measured
// from the WhatsApp work updates, never typed), what is late and what it pushes, and the forecast handover.
// Those who plan move bars by dragging or in the panel; every move is previewed before the ones after it move.

type Filter = 'all' | 'attention' | 'week' | 'critical' | 'undated'

export default function SchedulePage() {
  usePageTitle('Schedule')
  const projectId = usePlanningProject()
  if (!projectId) {
    return (
      <div className="mx-auto flex w-full flex-col gap-4 pb-8 sm:px-2">
        <Heading />
        <p className="text-sm text-muted-foreground">Pick a project to see its schedule.</p>
        <ProjectPickList to={(id) => `/planning/schedule?project=${id}`} empty="No projects yet. Add one in Projects & Sites." />
      </div>
    )
  }
  return <ScheduleView key={projectId} projectId={projectId} />
}

function Heading({ children, chip }: { children?: React.ReactNode; chip?: React.ReactNode }) {
  return (
    <header className="flex flex-wrap items-center justify-between gap-3">
      <ModuleTitle icon={CalendarRange} title="Schedule" chip={chip} />
      {children}
    </header>
  )
}

function inWeek(a: Activity, today: string): boolean {
  if (!a.start || !a.end) return false
  const t = dayNum(today)
  return dayNum(a.start) <= t + 6 && dayNum(a.end) >= t
}

function ScheduleView({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient()
  const toast = useToast()
  const isMobile = useIsMobile()
  const readOnly = useReadOnly()
  const [params, setParams] = useSearchParams()
  const query = useQuery({ queryKey: ['schedule', projectId], queryFn: () => fetchSchedule(projectId) })
  const [filter, setFilter] = React.useState<Filter>('all')
  const [zoom, setZoom] = React.useState<Zoom | null>(null)
  const [todayTick, setTodayTick] = React.useState(0)
  const selected = params.get('activity')
  const select = (id: string | null) => setParams((p) => { const n = new URLSearchParams(p); if (id) n.set('activity', id); else n.delete('activity'); return n }, { replace: true })
  const [pending, setPending] = React.useState<{ id: string; body: ActivityUpdate; label: string } | null>(null)
  const [quick, setQuick] = React.useState(false)
  const [adding, setAdding] = React.useState(false)
  const [importing, setImporting] = React.useState(false)

  const put = (s: Schedule) => queryClient.setQueryData(['schedule', projectId], s)
  const refreshOthers = () => { for (const k of ['lifecycle', 'project-start']) queryClient.invalidateQueries({ queryKey: [k] }) }

  const preview = useMutation({ mutationFn: (p: { id: string; body: ActivityUpdate }) => updateActivity(projectId, p.id, { ...p.body, preview: true }) })
  const save = useMutation({
    mutationFn: (p: { id: string; body: ActivityUpdate }) => updateActivity(projectId, p.id, p.body),
    onSuccess: (r: ScheduleChange) => {
      put(r.schedule)
      refreshOthers()
      setPending(null)
      toast.success('Schedule saved', r.moved.length ? `${plural(r.moved.length, 'activity')} after it moved too.` : undefined)
    },
    onError: (e) => toast.error('Not saved', apiErrorMessage(e)),
  })
  const sequence = useMutation({
    mutationFn: (b: { start: string; items: { id: string; days: number }[] }) => sequenceActivities(projectId, b),
    onSuccess: (r) => { put(r.schedule); refreshOthers(); setQuick(false); toast.success('Schedule planned', 'Drag any bar to fine-tune it.') },
    onError: (e) => toast.error('Not planned', apiErrorMessage(e)),
  })
  const add = useMutation({
    mutationFn: (b: Parameters<typeof createActivity>[1]) => createActivity(projectId, b),
    onSuccess: (r) => { put(r.schedule); refreshOthers(); setAdding(false); if (r.focus) select(r.focus); toast.success('Added to the schedule') },
    onError: (e) => toast.error('Not added', apiErrorMessage(e)),
  })
  const remove = useMutation({
    mutationFn: (id: string) => deleteActivity(projectId, id),
    onSuccess: () => { select(null); queryClient.invalidateQueries({ queryKey: ['schedule', projectId] }); refreshOthers(); toast.success('Removed') },
    onError: (e) => toast.error('Not removed', apiErrorMessage(e)),
  })

  const ask = (id: string, body: ActivityUpdate, label: string) => {
    // Marking finished or reopening moves nothing: save at once. Dates and links are previewed first.
    if (body.done !== undefined) {
      save.mutate({ id, body })
      return
    }
    setPending({ id, body, label })
    preview.reset()
    preview.mutate({ id, body })
  }

  if (query.isLoading) return <div className="mx-auto flex w-full animate-pulse flex-col gap-4 sm:px-2"><div className="h-10 w-64 rounded bg-muted" /><div className="h-16 rounded-xl bg-muted/60" /><div className="h-96 rounded-xl bg-muted/60" /></div>
  if (query.isError || !query.data) return <PageError message="The schedule did not load." onRetry={() => query.refetch()} back={{ to: '/planning/schedule', label: 'All projects' }} />

  const s = query.data
  const today = s.today
  // A long project opens on months (the whole job at a glance); a short one, or a close look, on days.
  const span = s.summary.first_start && s.summary.planned_finish ? daysBetween(s.summary.first_start, s.summary.planned_finish) : 0
  const view: Zoom = zoom ?? (span > 75 ? 'month' : 'week')
  const canEdit = s.can_edit && !readOnly
  const counts = s.summary.counts
  const attention = s.activities.filter((a) => a.state === 'late' || a.state === 'behind')
  const undated = s.activities.filter((a) => !a.start)
  const critical = s.activities.filter((a) => a.critical && a.state !== 'done')
  const list = s.activities.filter((a) => {
    if (filter === 'attention') return a.state === 'late' || a.state === 'behind'
    if (filter === 'week') return inWeek(a, today) || a.state === 'late'
    if (filter === 'critical') return a.critical && a.state !== 'done'
    if (filter === 'undated') return !a.start
    return true
  })
  const current = s.activities.find((a) => a.id === selected) ?? null
  const finishTarget = s.summary.contract_finish ?? s.summary.planned_finish
  const worst = [...attention].sort((a, b) => (b.slip_days || b.days_late) - (a.slip_days || a.days_late))[0]
  const pushedCount = s.activities.filter((a) => a.pushed_days > 0 && a.state !== 'done').length

  const stats: Stat[] = [
    { label: 'Work done', value: s.summary.progress !== null ? `${s.summary.progress}%` : '—', icon: Gauge, hint: 'measured from site updates' },
    { label: 'Late', value: counts.late ?? 0, tone: counts.late ? 'bad' : 'good', icon: AlertTriangle, hint: counts.behind ? `${counts.behind} more behind` : 'past their end day' },
    { label: 'On track', value: (counts.on_track ?? 0) + (counts.done ?? 0), tone: 'good', icon: CheckCircle2, hint: `${counts.done ?? 0} finished` },
    { label: 'Handover', value: shortDay(finishTarget, today), icon: CalendarCheck2, hint: s.summary.contract_finish ? 'contract date' : 'last planned day' },
    {
      label: 'Forecast finish',
      value: shortDay(s.summary.forecast_finish, today),
      tone: s.summary.slip_days > 0 ? 'bad' : s.summary.forecast_finish ? 'good' : 'default',
      icon: Clock,
      hint: s.summary.slip_days > 0 ? `${plural(s.summary.slip_days, 'day')} late at this pace` : 'on time at this pace',
    },
  ]

  const panel = current && (
    <ActivityPanel
      schedule={s}
      activity={current}
      projectId={projectId}
      canEdit={canEdit}
      busy={save.isPending || preview.isPending}
      onChange={(body, label) => ask(current.id, body, label)}
      onDelete={() => remove.mutate(current.id)}
      onClose={() => select(null)}
    />
  )

  return (
    <div className="mx-auto flex w-full max-w-[1500px] flex-col gap-4 pb-24 sm:px-2 md:pb-8">
      <Heading chip={<StageChip stage={s.project.stage} label={s.project.stage_label} />}>
        <div className="flex flex-wrap items-center gap-2">
          <Link to={`/planning/setup?project=${projectId}`} className="text-sm text-muted-foreground hover:text-foreground">{s.project.name}</Link>
          {canEdit && <Button variant="outline" className="gap-2" onClick={() => setImporting(true)}><FileSpreadsheet className="size-4" /><span className="hidden sm:inline">BOQ from Excel</span></Button>}
          {canEdit && s.activities.length > 0 && <Button variant="outline" className="gap-2" onClick={() => setQuick(true)}><ListOrdered className="size-4" /><span className="hidden sm:inline">Quick plan</span></Button>}
          {canEdit && <Button className="hidden gap-2 font-semibold md:inline-flex" onClick={() => setAdding(true)}><Plus className="size-4" strokeWidth={2.6} /> Activity</Button>}
        </div>
      </Heading>

      {s.activities.length === 0 ? (
        <EmptySchedule canEdit={canEdit} onImport={() => setImporting(true)} onAdd={() => setAdding(true)} />
      ) : (
        <>
          {worst ? (
            <Callout tone="draft" icon={AlertTriangle} action={<Button size="sm" variant="outline" onClick={() => { setFilter('attention'); select(worst.id) }}>See what is late</Button>}>
              <strong>{worst.name}</strong> is {worst.state === 'late' ? `${plural(worst.days_late, 'day')} late` : 'behind'}
              {worst.progress !== null ? ` at ${worst.progress}%` : ''}
              {pushedCount ? ` and pushes ${plural(pushedCount, 'activity')} after it` : ''}.
              {s.summary.slip_days > 0 && <> Forecast handover <strong>{shortDay(s.summary.forecast_finish, today)}</strong>, {plural(s.summary.slip_days, 'day')} late.</>}
              <span className="text-foreground/70"> The owner and PM get this on WhatsApp each morning.</span>
            </Callout>
          ) : undated.length === s.activities.length ? (
            <Callout tone="info" icon={Rocket} action={canEdit && <Button size="sm" onClick={() => setQuick(true)} className="gap-1.5"><ListOrdered className="size-4" /> Quick plan</Button>}>
              {plural(undated.length, 'section')} from the BOQ, none with dates yet. <strong>Quick plan</strong> puts them one after another in a minute; drag to fine-tune.
            </Callout>
          ) : (
            <Callout tone="success" icon={CheckCircle2}>Everything is on time. Site's WhatsApp updates keep this chart current; nobody needs to update it by hand.</Callout>
          )}

          <StatStrip stats={stats} />

          <div className="flex flex-wrap items-center justify-between gap-2">
            <Segmented<Filter>
              label="Show"
              value={filter}
              onChange={setFilter}
              options={[
                { value: 'all', label: 'All', count: s.activities.length },
                { value: 'attention', label: 'Late & behind', count: attention.length },
                { value: 'week', label: 'This week', count: s.activities.filter((a) => inWeek(a, today) || a.state === 'late').length },
                { value: 'critical', label: 'Critical', count: critical.length },
                ...(undated.length ? [{ value: 'undated' as Filter, label: 'No dates', count: undated.length }] : []),
              ]}
            />
            {!isMobile && (
              <div className="flex items-center gap-2">
                <Legend />
                <Segmented<Zoom> label="Zoom" value={view} onChange={setZoom} options={[{ value: 'week', label: 'Days' }, { value: 'month', label: 'Months' }]} />
                <Button size="sm" variant="outline" onClick={() => setTodayTick((n) => n + 1)}>Today</Button>
              </div>
            )}
          </div>

          {list.length === 0 ? (
            <p className="rounded-xl border px-4 py-10 text-center text-sm text-muted-foreground">Nothing here. {filter === 'attention' ? 'Nothing is late or behind.' : ''}</p>
          ) : isMobile ? (
            <MobileList schedule={s} activities={list} onSelect={select} />
          ) : (
            <div className="flex flex-col items-start gap-4 xl:flex-row">
              <div className="w-full min-w-0 flex-1">
                <Gantt
                  schedule={s}
                  activities={list}
                  zoom={view}
                  selectedId={selected}
                  onSelect={select}
                  canEdit={canEdit}
                  scrollToToday={todayTick}
                  onMove={(id, days) => {
                    const a = s.activities.find((x) => x.id === id)
                    if (!a?.start || !a.end) return
                    select(id)
                    ask(id, a.milestone ? { start: addDays(a.start, days), milestone: true } : { start: addDays(a.start, days), end: addDays(a.end, days) },
                      `Move ${a.name} ${days > 0 ? 'later' : 'earlier'} by ${plural(Math.abs(days), 'day')}`)
                  }}
                  onAddDates={(id) => select(id)}
                />
                <p className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                  <span className="inline-flex items-center gap-1"><MessageCircle className="size-3.5" /> Progress fills in from the site's WhatsApp work updates on each section's BOQ lines.</span>
                  {canEdit && <span>Drag a bar to move it; the ones after it follow.</span>}
                  {s.summary.conflicts > 0 && <span className="text-red-600">{plural(s.summary.conflicts, 'link')} broken by the dates (red dashed).</span>}
                </p>
              </div>
              {current && (
                <aside aria-label="Activity" className="w-full shrink-0 overflow-hidden rounded-xl border xl:sticky xl:top-4 xl:w-[400px]">{panel}</aside>
              )}
            </div>
          )}
        </>
      )}

      {isMobile && (
        <Sheet open={!!current} onOpenChange={(o) => !o && select(null)}>
          <SheetContent side="bottom" className="max-h-[92vh] gap-0 overflow-y-auto rounded-t-2xl p-0">
            <SheetTitle className="sr-only">{current?.name ?? 'Activity'}</SheetTitle>
            {current && (
              <ActivityPanel schedule={s} activity={current} projectId={projectId} canEdit={canEdit} busy={save.isPending || preview.isPending}
                onChange={(body, label) => ask(current.id, body, label)} onDelete={() => remove.mutate(current.id)} />
            )}
          </SheetContent>
        </Sheet>
      )}
      {canEdit && (
        <Button className="fixed right-4 bottom-5 z-30 h-12 gap-2 rounded-full px-5 font-semibold shadow-lg md:hidden" onClick={() => setAdding(true)}><Plus className="size-5" strokeWidth={2.6} /> Activity</Button>
      )}

      {pending && (
        <ConfirmChangeDialog
          label={pending.label}
          preview={preview.data ?? null}
          loading={preview.isPending}
          saving={save.isPending}
          error={preview.isError ? apiErrorMessage(preview.error) : ''}
          today={today}
          onCancel={() => setPending(null)}
          onConfirm={() => save.mutate({ id: pending.id, body: pending.body })}
        />
      )}
      <QuickPlanDialog
        open={quick}
        onOpenChange={setQuick}
        activities={s.activities}
        defaultStart={s.project.start_date ?? today}
        saving={sequence.isPending}
        onSubmit={(start, items) => sequence.mutate({ start, items })}
      />
      <AddActivityDialog open={adding} onOpenChange={setAdding} activities={s.activities} defaultStart={s.project.start_date && s.project.start_date > today ? s.project.start_date : today} saving={add.isPending} onSubmit={(b) => add.mutate(b)} />
      <BoqImportDialog projectId={projectId} projectName={s.project.name} open={importing} onOpenChange={setImporting} />
    </div>
  )
}

function Legend() {
  const items: [keyof typeof STATE_BAR, string][] = [['on_track', 'On track'], ['behind', 'Behind'], ['late', 'Late'], ['done', 'Done']]
  return (
    <span className="hidden items-center gap-2.5 text-[11px] text-muted-foreground 2xl:flex">
      {items.map(([k, label]) => <span key={k} className="inline-flex items-center gap-1"><span className={cn('size-2.5 rounded-sm', STATE_BAR[k].fill)} />{label}</span>)}
      <span className="inline-flex items-center gap-1"><Flame className="size-3 text-orange-600" />Critical</span>
      <span className="inline-flex items-center gap-1"><span className="h-2.5 w-4 rounded-sm border border-dashed border-red-500" />Overrun</span>
    </span>
  )
}

function EmptySchedule({ canEdit, onImport, onAdd }: { canEdit: boolean; onImport: () => void; onAdd: () => void }) {
  return (
    <div className="flex flex-col items-center gap-4 rounded-2xl border border-dashed px-6 py-14 text-center">
      <span className="inline-flex size-14 items-center justify-center rounded-2xl bg-teal-100 text-teal-800 dark:bg-teal-950 dark:text-teal-200"><CalendarRange className="size-7" /></span>
      <div className="flex max-w-lg flex-col gap-1.5">
        <h2 className="text-lg font-semibold">Your schedule starts from your BOQ</h2>
        <p className="text-sm text-muted-foreground">
          Upload the estimate Excel you already have: each section becomes a bar. Give them days with Quick plan, and from then
          on the site's WhatsApp work updates fill the bars in. You see a delay the day it happens, not at the monthly meeting.
        </p>
      </div>
      {canEdit ? (
        <div className="flex flex-wrap justify-center gap-2">
          <Button onClick={onImport} className="gap-2"><FileSpreadsheet className="size-4" /> Upload the BOQ Excel</Button>
          <Button variant="outline" onClick={onAdd} className="gap-2"><Plus className="size-4" /> Add an activity by hand</Button>
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">The project manager makes the schedule; it shows here once they do.</p>
      )}
    </div>
  )
}

function MobileList({ schedule: s, activities, onSelect }: { schedule: Schedule; activities: Activity[]; onSelect: (id: string) => void }) {
  return (
    <ul className="flex flex-col gap-2">
      {activities.map((a) => (
        <li key={a.id}>
          <button type="button" onClick={() => onSelect(a.id)} className="flex w-full flex-col gap-1.5 rounded-xl border p-3 text-left active:bg-muted/50">
            <span className="flex items-center justify-between gap-2">
              <span className="flex min-w-0 items-center gap-1.5 font-medium"><span className="truncate">{a.name}</span>{a.critical && a.state !== 'done' && <Flame className="size-3.5 shrink-0 text-orange-600" />}</span>
              <StateChip state={a.state} />
            </span>
            <span className="text-xs text-muted-foreground">
              {a.start ? `${shortDay(a.start, s.today)}${a.milestone ? ' · milestone' : ` → ${shortDay(a.end, s.today)}`}` : 'No dates yet'}
              {a.slip_days > 0 && !a.done ? <span className="text-red-600"> · forecast {shortDay(a.forecast_end, s.today)}</span> : null}
            </span>
            {!a.milestone && a.start && (
              <span className="relative h-2 overflow-hidden rounded-full bg-muted">
                <span className={cn('absolute inset-y-0 left-0 rounded-full', STATE_BAR[a.state].fill)} style={{ width: `${a.progress ?? 0}%` }} />
                {a.expected !== null && a.state !== 'done' && <span className="absolute inset-y-0 w-0.5 bg-foreground/60" style={{ left: `${a.expected}%` }} />}
              </span>
            )}
          </button>
        </li>
      ))}
    </ul>
  )
}
