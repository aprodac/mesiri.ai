import * as React from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft,
  Check,
  CheckCheck,
  CircleCheck,
  CircleDashed,
  HardHat,
  History,
  Info,
  MessageSquareText,
  Package,
  Pencil,
  Trash2,
  TriangleAlert,
  Users,
} from 'lucide-react'
import {
  approveDailyReportApi,
  confirmFactApi,
  correctActivityApi,
  fetchDailyReportPdfApi,
  fetchFactSourcesApi,
  fetchSiteDayApi,
  rejectFactApi,
  setSiteDayConditionsApi,
  type DprVersion,
  type ReviewItem,
  type SiteDayConditions,
  type SiteDayDetail,
} from '@/lib/api'
import {
  CHIP,
  FROZEN,
  dateTime,
  errorDetail,
  hasUpdates as siteHasUpdates,
  longDate,
  missingText,
  plural,
  qty,
  severityChip,
  siteStatus,
} from '@/lib/site-day'
import { useReadOnly } from '@/lib/trial'
import { cn, formatClock } from '@/lib/utils'
import { useToast } from '@/components/ui/toast-notification'
import { DprSummaryCard } from '@/components/dpr-summary-card'
import { DprVersionsCard } from '@/components/dpr-versions-card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Callout, DprAside, DprSection, DprSteps, StatStrip, type StepState } from '@/components/dpr-page'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'

// Site DPR page (WEB-04): one site's working day. The engineer checks what
// was sent on WhatsApp (saved as drafts, WA-01), confirms or removes each
// item, sees where it came from, fixes the day's conditions, and approves the
// day -- which confirms every remaining draft and lets the project DPR go out
// (BE-16). Reads GET /dpr/site-days/{site_id}; the actions are the existing
// /dpr/facts confirm/reject, PATCH /progress/activities and .../approve.

const TEXTAREA =
  'flex min-h-[70px] w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-xs focus-visible:outline-hidden focus-visible:ring-1 focus-visible:ring-ring'
const SELECT = 'h-9 rounded-md border border-input bg-background px-2 text-sm'

const SECTIONS: {
  key: ReviewItem['section']
  icon: React.ComponentType<{ className?: string }>
  title: string
  empty: string
}[] = [
  { key: 'work', icon: HardHat, title: 'Work done', empty: 'No work reported.' },
  { key: 'labour', icon: Users, title: 'Labour', empty: 'No labour count yet.' },
  { key: 'materials', icon: Package, title: 'Materials', empty: 'No materials received or used.' },
  { key: 'issues', icon: TriangleAlert, title: 'Issues', empty: 'No issues reported.' },
]

const FACT_LABEL: Record<ReviewItem['fact_type'], string> = {
  activity: 'work item',
  labour_report: 'labour count',
  material_receipt: 'material received',
  material_usage: 'material used',
  site_issue: 'issue',
}

const WEATHER: { value: NonNullable<SiteDayConditions['weather']>; label: string }[] = [
  { value: 'sunny', label: 'Sunny' },
  { value: 'cloudy', label: 'Cloudy' },
  { value: 'rainy', label: 'Rainy' },
  { value: 'windy', label: 'Windy' },
  { value: 'extreme_heat', label: 'Extreme heat' },
]

const WORKING: { value: NonNullable<SiteDayConditions['site_working']>; label: string }[] = [
  { value: 'full', label: 'Full day' },
  { value: 'half', label: 'Half day' },
  { value: 'none', label: 'No work' },
]

function humanize(value: string | null | undefined): string {
  if (!value) return ''
  const text = value.replace(/_/g, ' ').toLowerCase()
  return text.charAt(0).toUpperCase() + text.slice(1)
}

// ─── One item ────────────────────────────────────────────────────────────────

function ItemRow({
  item,
  frozen,
  busy,
  onConfirm,
  onRemove,
  onEdit,
  onSources,
}: {
  item: ReviewItem
  frozen: boolean
  busy: boolean
  onConfirm: (item: ReviewItem) => void
  onRemove: (item: ReviewItem) => void
  onEdit: (item: ReviewItem) => void
  onSources: (item: ReviewItem) => void
}) {
  const draft = item.review === 'draft'
  const title = humanize(item.title) || FACT_LABEL[item.fact_type]
  // The AI often repeats the title as the description; say it once.
  const detail = item.detail && item.detail.trim().toLowerCase() !== (item.title ?? '').trim().toLowerCase() ? item.detail : null
  const quantities = (item.quantities ?? []).map((q) => `${qty(q.quantity)} ${q.unit}`).join(', ')
  const severity = severityChip(item.severity)
  return (
    <li className={cn('group flex gap-3 py-3.5', draft && '-mx-3 rounded-lg bg-draft-soft/40 px-3')}>
      <span className="mt-0.5 shrink-0" title={draft ? 'Draft: not confirmed yet' : 'Confirmed'}>
        {draft ? (
          <CircleDashed className="size-5 text-draft" />
        ) : (
          <CircleCheck className="size-5 text-success" />
        )}
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-1 sm:flex-row sm:items-start sm:justify-between sm:gap-4">
        <div className="flex min-w-0 flex-col gap-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium">{title}</span>
            {draft && <span className={cn(CHIP, 'bg-draft-soft text-draft')}>Draft</span>}
            {severity && <span className={cn(CHIP, severity.className)}>{severity.label}</span>}
            {item.flags.includes('possible_duplicate') && (
              <span className={cn(CHIP, 'bg-draft-soft text-draft')}>Possible repeat</span>
            )}
            {item.flags.includes('beyond_stock') && (
              <span className={cn(CHIP, 'bg-destructive/10 text-destructive')}>More than in stock</span>
            )}
          </div>
          {detail && <p className="text-sm text-muted-foreground">{detail}</p>}
          {(item.evidence_count ?? 0) > 0 && (
            <p className="text-xs text-muted-foreground">{plural(item.evidence_count ?? 0, 'photo')}</p>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-1 sm:gap-3">
          {quantities && <span className="mr-auto text-sm font-semibold tabular-nums sm:mr-2">{quantities}</span>}
          <Button variant="ghost" size="icon" className="size-8 text-muted-foreground" title="Where this came from" aria-label="Where this came from" onClick={() => onSources(item)}>
            <MessageSquareText />
          </Button>
          {!frozen && item.fact_type === 'activity' && (
            <Button variant="ghost" size="icon" className="size-8 text-muted-foreground" title="Edit" aria-label="Edit" disabled={busy} onClick={() => onEdit(item)}>
              <Pencil />
            </Button>
          )}
          {!frozen && (
            <Button
              variant="ghost"
              size="icon"
              className="size-8 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
              title="Remove"
              aria-label="Remove"
              disabled={busy}
              onClick={() => onRemove(item)}
            >
              <Trash2 />
            </Button>
          )}
          {!frozen && draft && (
            <Button size="sm" className="ml-1" disabled={busy} onClick={() => onConfirm(item)}>
              <Check /> Confirm
            </Button>
          )}
        </div>
      </div>
    </li>
  )
}

function Section({
  icon,
  title,
  empty,
  items,
  summary,
  children,
}: {
  icon: React.ComponentType<{ className?: string }>
  title: string
  empty: string
  items: ReviewItem[]
  summary?: React.ReactNode
  children: (item: ReviewItem) => React.ReactNode
}) {
  const drafts = items.filter((i) => i.review === 'draft').length
  return (
    <DprSection
      icon={icon}
      title={title}
      meta={items.length > 0 ? items.length : undefined}
      action={drafts > 0 ? <span className={cn(CHIP, 'bg-draft-soft text-draft')}>{plural(drafts, 'draft')} to confirm</span> : undefined}
    >
      {summary}
      {items.length === 0 ? (
        <p className="text-sm text-muted-foreground">{empty}</p>
      ) : (
        <ul className="flex flex-col divide-y">{items.map(children)}</ul>
      )}
    </DprSection>
  )
}

// ─── Sources side panel ──────────────────────────────────────────────────────

function SourcesSheet({ item, onClose }: { item: ReviewItem | null; onClose: () => void }) {
  const query = useQuery({
    queryKey: ['fact-sources', item?.fact_type, item?.id],
    queryFn: () => fetchFactSourcesApi(item!.fact_type, item!.id),
    enabled: item !== null,
  })
  const data = query.data
  return (
    <Sheet open={item !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-md">
        <SheetHeader>
          <SheetTitle>Where this came from</SheetTitle>
          <SheetDescription>{item ? humanize(item.title) || FACT_LABEL[item.fact_type] : ''}</SheetDescription>
        </SheetHeader>
        <div className="flex flex-col gap-6 px-4 pb-6">
          {query.isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
          {query.isError && <p className="text-sm text-destructive">Could not load the sources.</p>}
          {data && (
            <>
              <section className="flex flex-col gap-3">
                <h3 className="text-sm font-semibold">WhatsApp</h3>
                {data.messages.length === 0 ? (
                  <p className="text-sm text-muted-foreground">Not sent on WhatsApp (entered on the dashboard).</p>
                ) : (
                  data.messages.map((m) => (
                    <div key={m.id} className="rounded-xl border bg-muted/40 p-3 text-sm">
                      <p className="text-xs text-muted-foreground">
                        {m.sender_name ?? m.sender_number ?? 'Unknown sender'} · {dateTime(m.received_at)}
                      </p>
                      {m.text && <p className="mt-1 whitespace-pre-wrap">{m.text}</p>}
                      {!m.text && <p className="mt-1 text-muted-foreground">{humanize(m.type)} message</p>}
                      {m.media_url && (
                        <a className="mt-2 inline-block text-xs font-semibold text-primary hover:underline" href={m.media_url} target="_blank" rel="noreferrer">
                          Open attachment
                        </a>
                      )}
                    </div>
                  ))
                )}
              </section>
              {data.readings.length > 0 && (
                <section className="flex flex-col gap-3">
                  <h3 className="text-sm font-semibold">What the AI read</h3>
                  {data.readings.map((r, i) => (
                    <div key={i} className="rounded-xl bg-ai-soft p-3 text-sm">
                      <p className="text-xs font-semibold text-ai">
                        {r.confidence ? `${humanize(r.confidence)} confidence` : 'Confidence not recorded'}
                      </p>
                      <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
                        {Object.entries(r.extracted)
                          .filter(([, v]) => v !== null && v !== '' && typeof v !== 'object')
                          .map(([k, v]) => (
                            <React.Fragment key={k}>
                              <dt className="text-muted-foreground">{humanize(k)}</dt>
                              <dd>{String(v)}</dd>
                            </React.Fragment>
                          ))}
                      </dl>
                    </div>
                  ))}
                </section>
              )}
              {data.photos.length > 0 && (
                <section className="flex flex-col gap-3">
                  <h3 className="text-sm font-semibold">Photos</h3>
                  <div className="grid grid-cols-2 gap-2">
                    {data.photos.map((p, i) =>
                      p.url ? (
                        <a key={i} href={p.url} target="_blank" rel="noreferrer" className="flex flex-col gap-1">
                          <img src={p.url} alt={p.caption ?? 'Site photo'} className="aspect-square w-full rounded-lg object-cover" />
                          {p.caption && <span className="text-xs text-muted-foreground line-clamp-2">{p.caption}</span>}
                        </a>
                      ) : (
                        <div key={i} className="flex aspect-square items-center justify-center rounded-lg bg-muted text-xs text-muted-foreground">
                          Photo unavailable
                        </div>
                      ),
                    )}
                  </div>
                </section>
              )}
              {data.history.length > 0 && (
                <section className="flex flex-col gap-2">
                  <h3 className="text-sm font-semibold">History</h3>
                  <ul className="flex flex-col gap-1 text-sm">
                    {data.history.map((h, i) => (
                      <li key={i}>
                        {humanize(h.state)}
                        <span className="text-muted-foreground">
                          {h.by ? ` by ${h.by}` : ''} · {dateTime(h.at)}
                          {h.note ? ` · ${h.note}` : ''}
                        </span>
                      </li>
                    ))}
                  </ul>
                </section>
              )}
            </>
          )}
        </div>
      </SheetContent>
    </Sheet>
  )
}

// ─── Dialogs ─────────────────────────────────────────────────────────────────

function RemoveDialog({
  item,
  busy,
  onCancel,
  onRemove,
}: {
  item: ReviewItem | null
  busy: boolean
  onCancel: () => void
  onRemove: (item: ReviewItem, reason: string) => void
}) {
  const [reason, setReason] = React.useState('')
  React.useEffect(() => setReason(''), [item])
  const materials = item?.fact_type === 'material_receipt' || item?.fact_type === 'material_usage'
  return (
    <Dialog open={item !== null} onOpenChange={(open) => !open && onCancel()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Remove this {item ? FACT_LABEL[item.fact_type] : 'item'}?</DialogTitle>
          <DialogDescription>
            It comes off today's report. If it was only partly wrong, send the correct update on WhatsApp
            {materials ? ' or correct it on the Materials page' : ''} after removing it.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-1.5">
          <Label htmlFor="removeReason">Why is it wrong?</Label>
          <textarea
            id="removeReason"
            className={TEXTAREA}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="e.g. Sent twice, wrong site"
          />
        </div>
        <DialogFooter>
          {materials && (
            <Button asChild variant="link" className="mr-auto px-0">
              <Link to="/materials">Materials page</Link>
            </Button>
          )}
          <Button variant="outline" onClick={onCancel}>
            Keep it
          </Button>
          <Button
            variant="destructive"
            disabled={busy || !reason.trim()}
            onClick={() => item && onRemove(item, reason.trim())}
          >
            Remove
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function EditActivityDialog({
  item,
  busy,
  onCancel,
  onSave,
}: {
  item: ReviewItem | null
  busy: boolean
  onCancel: () => void
  onSave: (item: ReviewItem, changes: { work_type: string; narrative: string }) => void
}) {
  const [workType, setWorkType] = React.useState('')
  const [narrative, setNarrative] = React.useState('')
  React.useEffect(() => {
    setWorkType(item?.title ?? '')
    setNarrative(item?.detail ?? '')
  }, [item])
  return (
    <Dialog open={item !== null} onOpenChange={(open) => !open && onCancel()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Edit work item</DialogTitle>
          <DialogDescription>Fix what the AI read. Quantities are corrected by sending them again on WhatsApp.</DialogDescription>
        </DialogHeader>
        <div className="grid gap-3">
          <div className="grid gap-1.5">
            <Label htmlFor="workType">Work</Label>
            <Input id="workType" value={workType} onChange={(e) => setWorkType(e.target.value)} />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="narrative">Description</Label>
            <textarea id="narrative" className={TEXTAREA} value={narrative} onChange={(e) => setNarrative(e.target.value)} />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onCancel}>
            Cancel
          </Button>
          <Button
            disabled={busy || !workType.trim()}
            onClick={() => item && onSave(item, { work_type: workType.trim(), narrative: narrative.trim() })}
          >
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function ApproveDialog({
  detail,
  open,
  busy,
  onCancel,
  onApprove,
}: {
  detail: SiteDayDetail
  open: boolean
  busy: boolean
  onCancel: () => void
  onApprove: () => void
}) {
  const project = detail.project
  const deadline = project?.dpr_send_deadline ? formatClock(project.dpr_send_deadline) : null
  const sending =
    project && project.site_count > 1
      ? `The ${project.project_name} DPR goes out once every site is confirmed${deadline ? `, or at ${deadline}` : ''}.`
      : `The DPR goes out to the owner and recipients${deadline ? ` (by ${deadline})` : ''}.`
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onCancel()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Approve and send?</DialogTitle>
          <DialogDescription>
            {detail.drafts > 0
              ? `This confirms the ${plural(detail.drafts, 'draft')} still waiting. `
              : 'Everything on the day is already confirmed. '}
            {sending}
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={onCancel}>
            Not yet
          </Button>
          <Button disabled={busy} onClick={onApprove}>
            Approve and send
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ─── Conditions and versions ─────────────────────────────────────────────────

function ConditionsCard({
  detail,
  frozen,
  onSave,
}: {
  detail: SiteDayDetail
  frozen: boolean
  onSave: (changes: SiteDayConditions) => Promise<boolean>
}) {
  const current = detail.report.conditions
  const [form, setForm] = React.useState({
    weather: current.weather ?? '',
    site_working: current.site_working ?? '',
    hours_lost: current.hours_lost_source === 'entered' ? (current.hours_lost ?? '') : '',
    tomorrow_plan: current.tomorrow_plan ?? '',
  })
  const [saving, setSaving] = React.useState(false)
  const set = (key: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
    setForm((f) => ({ ...f, [key]: e.target.value }))

  const save = async () => {
    setSaving(true)
    await onSave({
      weather: (form.weather || null) as SiteDayConditions['weather'],
      site_working: (form.site_working || null) as SiteDayConditions['site_working'],
      hours_lost: form.hours_lost === '' ? null : Number(form.hours_lost),
      tomorrow_plan: form.tomorrow_plan.trim() || null,
    })
    setSaving(false)
  }

  return (
    <div className="grid gap-3">
        <h2 className="text-sm font-semibold">Day conditions</h2>
        <div className="grid grid-cols-2 gap-3">
          <label className="grid gap-1.5 text-sm">
            <span className="text-muted-foreground">Weather</span>
            <select className={SELECT} value={form.weather} onChange={set('weather')} disabled={frozen}>
              <option value="">Not set</option>
              {WEATHER.map((w) => (
                <option key={w.value} value={w.value}>
                  {w.label}
                </option>
              ))}
            </select>
          </label>
          <label className="grid gap-1.5 text-sm">
            <span className="text-muted-foreground">Site working</span>
            <select className={SELECT} value={form.site_working} onChange={set('site_working')} disabled={frozen}>
              <option value="">Not set</option>
              {WORKING.map((w) => (
                <option key={w.value} value={w.value}>
                  {w.label}
                </option>
              ))}
            </select>
          </label>
        </div>
        <label className="grid gap-1.5 text-sm">
          <span className="text-muted-foreground">Hours lost</span>
          <Input
            type="number"
            min={0}
            step={0.5}
            value={form.hours_lost}
            onChange={set('hours_lost')}
            disabled={frozen}
            placeholder={current.hours_lost_source === 'issues' ? `${current.hours_lost} (from issue delays)` : '0'}
          />
        </label>
        <label className="grid gap-1.5 text-sm">
          <span className="text-muted-foreground">Tomorrow's plan</span>
          <textarea className={TEXTAREA} value={form.tomorrow_plan} onChange={set('tomorrow_plan')} disabled={frozen} />
        </label>
        {!frozen && (
          <Button variant="outline" className="justify-self-start" disabled={saving} onClick={save}>
            Save conditions
          </Button>
        )}
    </div>
  )
}

// ─── Page ────────────────────────────────────────────────────────────────────

export default function SiteDayPage() {
  const { siteId = '', date = '' } = useParams()
  const toast = useToast()
  const queryClient = useQueryClient()
  const readOnly = useReadOnly()
  const [busy, setBusy] = React.useState(false)
  const [sourcesFor, setSourcesFor] = React.useState<ReviewItem | null>(null)
  const [removing, setRemoving] = React.useState<ReviewItem | null>(null)
  const [editing, setEditing] = React.useState<ReviewItem | null>(null)
  const [approving, setApproving] = React.useState(false)

  const query = useQuery({
    queryKey: ['site-day', siteId, date],
    queryFn: () => fetchSiteDayApi(siteId, date),
    enabled: Boolean(siteId && date),
  })
  const detail = query.data

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['site-day', siteId, date] })
    queryClient.invalidateQueries({ queryKey: ['site-days'] })
  }

  const run = async (action: () => Promise<unknown>, done: [string, string], failed: string) => {
    setBusy(true)
    try {
      await action()
      toast.success(...done)
      refresh()
      return true
    } catch (err) {
      toast.error(failed, errorDetail(err) ?? 'Please try again.')
      return false
    } finally {
      setBusy(false)
    }
  }

  if (query.isLoading) {
    return <div className="p-6 text-sm text-muted-foreground">Loading the site's day…</div>
  }
  if (query.isError || !detail) {
    return (
      <div className="flex flex-col gap-3 p-6">
        <p className="text-sm text-destructive">This site's day could not be loaded.</p>
        <Link to={`/today?date=${date}`} className="text-sm font-semibold text-primary hover:underline">
          Back to Today
        </Link>
      </div>
    )
  }

  const day = detail.day
  const reportId = day?.daily_report_id ?? null
  const frozen = readOnly || (day ? FROZEN.includes(day.status) : false)
  const status = day ? siteStatus(day) : null
  const missing = day ? missingText(day) : null
  const current = detail.versions.find((v) => v.is_current)
  const bySection = (key: ReviewItem['section']) => detail.items.filter((i) => i.section === key)
  const labour = detail.report.labour

  const openPdf = async (version: DprVersion) => {
    if (!reportId) return
    try {
      const blob = await fetchDailyReportPdfApi(reportId, version.is_current ? undefined : version.id)
      window.open(URL.createObjectURL(blob), '_blank', 'noopener')
    } catch (err) {
      toast.error('Could not open the PDF', errorDetail(err) ?? 'Please try again.')
    }
  }

  const rowProps = {
    frozen,
    busy,
    onConfirm: (item: ReviewItem) =>
      run(() => confirmFactApi(item.fact_type, item.id), ['Confirmed', `The ${FACT_LABEL[item.fact_type]} is confirmed.`], 'Could not confirm'),
    onRemove: setRemoving,
    onEdit: setEditing,
    onSources: setSourcesFor,
  }

  const confirmed = day ? FROZEN.includes(day.status) : false
  const sent = day?.status === 'published' || Boolean(detail.project?.sent)
  const hasUpdates = detail.items.length > 0 || (day ? siteHasUpdates(day) : false)
  const steps: { label: string; hint?: string; state: StepState }[] = [
    {
      label: 'Updates from site',
      hint: hasUpdates ? plural(detail.items.length, 'item') : 'Nothing yet',
      state: hasUpdates ? 'done' : 'current',
    },
    {
      label: 'Engineer confirms',
      hint: confirmed
        ? current?.approved_by
          ? `By ${current.approved_by}`
          : 'Confirmed'
        : detail.drafts > 0
          ? `${plural(detail.drafts, 'draft')} waiting`
          : 'Waiting',
      state: confirmed ? 'done' : hasUpdates ? 'current' : 'todo',
    },
    {
      label: 'Sent to owner',
      hint: sent ? 'In the project DPR' : detail.project?.dpr_send_deadline ? `By ${formatClock(detail.project.dpr_send_deadline)}` : undefined,
      state: sent ? 'done' : confirmed ? 'current' : 'todo',
    },
  ]
  const issues = bySection('issues')

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 p-4 sm:p-8">
      <header className="flex flex-col gap-5">
        <Link to={`/today?date=${date}`} className="inline-flex w-fit items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
          <ArrowLeft className="size-4" /> Today
        </Link>
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div className="flex min-w-0 flex-col gap-1">
            <p className="text-sm text-muted-foreground">
              Site DPR{day?.project_name ? ` · ${day.project_name}` : ''}
            </p>
            <div className="flex flex-wrap items-center gap-3">
              <h1 className="text-3xl font-semibold tracking-tight">{day?.site_name ?? 'Site'}</h1>
              {status && <span className={cn(CHIP, status.className)}>{status.label}</span>}
            </div>
            <p className="text-sm text-muted-foreground">{longDate(date)}</p>
          </div>
          {!frozen && reportId && (
            <Button className="h-11 px-5 font-semibold" disabled={busy} onClick={() => setApproving(true)}>
              <CheckCheck /> Approve and send
            </Button>
          )}
        </div>
        <DprSteps steps={steps} />
      </header>

      {detail.drafts > 0 && !frozen && (
        <Callout tone="draft" icon={CircleDashed}>
          <strong className="font-semibold">{plural(detail.drafts, 'item')} from WhatsApp still to confirm.</strong> Confirm them one by one, or
          approve the day to confirm them all.
        </Callout>
      )}
      {confirmed && current?.approved_at && (
        <Callout tone="success" icon={CircleCheck}>
          Approved{current.approved_by ? ` by ${current.approved_by}` : ''} · {dateTime(current.approved_at)}. Changes sent later show as late
          entries on the next report.
        </Callout>
      )}
      {missing && !frozen && (
        <Callout tone="muted" icon={Info}>
          {missing}
          {!reportId && ". The report is built at the project's cutoff time; items can be checked now."}
        </Callout>
      )}

      <StatStrip
        stats={[
          { label: 'Workers', value: labour.headcount || '—' },
          { label: 'Work items', value: bySection('work').length || '—' },
          { label: 'Photos', value: detail.report.evidence_count || '—' },
          {
            label: 'Open issues',
            value: Math.max(day?.open_issues ?? 0, issues.length) || '—',
            tone: issues.some((i) => ['CRITICAL', 'HIGH'].includes((i.severity ?? '').toUpperCase()))
              ? 'bad'
              : (day?.open_issues ?? 0) > 0
                ? 'warn'
                : 'default',
          },
        ]}
      />

      <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="flex min-w-0 flex-col">
          {detail.summary && (
            <div className="pb-6">
              <DprSummaryCard summary={detail.summary} />
            </div>
          )}
          {SECTIONS.map((section) => (
            <Section
              key={section.key}
              icon={section.icon}
              title={section.title}
              empty={section.empty}
              items={bySection(section.key)}
              summary={
                section.key === 'labour' && labour.headcount > 0 ? (
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="mr-1 text-sm">
                      <strong className="text-lg font-semibold tabular-nums">{labour.headcount}</strong>{' '}
                      <span className="text-muted-foreground">workers today</span>
                    </span>
                    {labour.trades.map((t) => (
                      <span key={t.trade} className="rounded-md border px-2 py-0.5 text-sm">
                        {humanize(t.trade)} <strong className="font-semibold tabular-nums">{t.headcount}</strong>
                      </span>
                    ))}
                  </div>
                ) : section.key === 'materials' && detail.report.materials.length > 0 ? (
                  <div className="overflow-x-auto rounded-lg border">
                    <table className="w-full text-sm">
                      <thead className="bg-muted/50 text-xs text-muted-foreground">
                        <tr>
                          <th className="px-3 py-2 text-left font-medium">Material</th>
                          <th className="px-3 py-2 text-right font-medium">Opening</th>
                          <th className="px-3 py-2 text-right font-medium">Received</th>
                          <th className="px-3 py-2 text-right font-medium">Used</th>
                          <th className="px-3 py-2 text-right font-medium">Closing</th>
                        </tr>
                      </thead>
                      <tbody className="tabular-nums">
                        {detail.report.materials.map((m) => (
                          <tr key={`${m.material_name}-${m.unit}`} className={cn('border-t', m.beyond_stock && 'text-destructive')}>
                            <td className="px-3 py-2">
                              {m.material_name} <span className="text-muted-foreground">({m.unit})</span>
                            </td>
                            <td className="px-3 py-2 text-right">{qty(m.opening)}</td>
                            <td className="px-3 py-2 text-right">{qty(m.received)}</td>
                            <td className="px-3 py-2 text-right">{qty(m.used)}</td>
                            <td className="px-3 py-2 text-right font-semibold">{qty(m.closing)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : undefined
              }
            >
              {(item) => <ItemRow key={`${item.fact_type}-${item.id}`} item={item} {...rowProps} />}
            </Section>
          ))}

          {detail.report.late_entries.length > 0 && (
            <DprSection icon={History} title="Late entries for earlier days">
              <ul className="flex flex-col gap-1 text-sm">
                {detail.report.late_entries.map((e, i) => (
                  <li key={i}>
                    <span className="text-muted-foreground">{longDate(e.report_date)}:</span> {e.summary}
                  </li>
                ))}
              </ul>
            </DprSection>
          )}
        </div>

        <DprAside>
          <ConditionsCard
            key={`${siteId}-${date}-${current?.id ?? 'none'}`}
            detail={detail}
            frozen={frozen}
            onSave={(changes) =>
              run(() => setSiteDayConditionsApi(siteId, date, changes), ['Saved', "The day's conditions are saved."], 'Could not save')
            }
          />
          <DprVersionsCard reportId={reportId} versions={detail.versions} onPdf={openPdf} />
        </DprAside>
      </div>

      <SourcesSheet item={sourcesFor} onClose={() => setSourcesFor(null)} />
      <RemoveDialog
        item={removing}
        busy={busy}
        onCancel={() => setRemoving(null)}
        onRemove={async (item, reason) => {
          if (
            await run(
              () => rejectFactApi(item.fact_type, item.id, reason),
              ['Removed', `The ${FACT_LABEL[item.fact_type]} is off today's report.`],
              'Could not remove',
            )
          )
            setRemoving(null)
        }}
      />
      <EditActivityDialog
        item={editing}
        busy={busy}
        onCancel={() => setEditing(null)}
        onSave={async (item, changes) => {
          if (
            await run(
              () => correctActivityApi(item.id, { ...changes, reason: 'Edited on the site DPR page' }),
              ['Saved', 'The work item is updated.'],
              'Could not save',
            )
          )
            setEditing(null)
        }}
      />
      {reportId && (
        <ApproveDialog
          detail={detail}
          open={approving}
          busy={busy}
          onCancel={() => setApproving(false)}
          onApprove={async () => {
            if (
              await run(
                () => approveDailyReportApi(reportId),
                ['Approved', `${day?.site_name ?? 'The site'}'s day is confirmed.`],
                'Could not approve',
              )
            )
              setApproving(false)
          }}
        />
      )}
    </div>
  )
}
