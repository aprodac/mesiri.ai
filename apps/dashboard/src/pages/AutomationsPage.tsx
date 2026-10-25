import * as React from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { CalendarClock, MapPin, Plus, TriangleAlert } from 'lucide-react'
import { useScope } from '@/lib/ScopeContext'
import { useAuth } from '@/lib/AuthContext'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Callout, PageHeader } from '@/components/dpr-page'
import { useToast } from '@/components/ui/toast-notification'
import { useSiteNames } from '@/lib/site-names'
import { fetchProjects } from '@/lib/projects'
import { ROLE_LABELS, roleLabel, type Role } from '@/lib/permissions'
import { cn } from '@/lib/utils'
import {
  fetchAutomationsApi,
  createAutomationApi,
  updateAutomationApi,
  deleteAutomationApi,
  fetchAutomationRunsApi,
  fetchUsers,
  type AutomationItem,
  type AutomationAction,
  type AutomationAudience,
  type AutomationFrequency,
} from '@/lib/api'

// WEB-35: Automations redone. Each one reads as a sentence ("Every day at
// 5:00 pm, send the DPR to me · Block A") with On / Paused, when it last ran
// and plain buttons. The form picks people and roles from lists (it asked
// for comma-separated user ids and a typed role code), and the run history
// opens in a side panel with skip reasons in words.

const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

const ACTION_WORDS: Record<AutomationAction, string> = {
  SEND_DPR: 'send the DPR',
  COMPLIANCE_SUMMARY: "say who hasn't reported",
  REMINDER: 'send a reminder',
}

const ACTION_OPTIONS: { value: AutomationAction; label: string }[] = [
  { value: 'SEND_DPR', label: 'Send the DPR' },
  { value: 'COMPLIANCE_SUMMARY', label: "Say who hasn't reported" },
  { value: 'REMINDER', label: 'Send a reminder' },
]

const AUDIENCE_OPTIONS: { value: AutomationAudience; label: string; others: boolean }[] = [
  { value: 'SELF', label: 'Me', others: false },
  { value: 'USERS', label: 'Chosen people', others: true },
  { value: 'ROLE', label: 'Everyone in a role', others: true },
  { value: 'NON_REPORTERS', label: "Whoever hasn't reported", others: true },
]

// The backend lets only these roles target other people.
const TARGET_OTHERS: readonly string[] = ['ADMIN', 'PROJECT_MANAGER']

function clock(hhmm: string): string {
  const [h, m] = hhmm.split(':').map(Number)
  if (Number.isNaN(h)) return hhmm
  return `${h % 12 || 12}:${String(m || 0).padStart(2, '0')} ${h < 12 ? 'am' : 'pm'}`
}

function when(item: Pick<AutomationItem, 'frequency' | 'day_of_week' | 'time_of_day'>): string {
  const days =
    item.frequency === 'WEEKLY' && item.day_of_week !== null
      ? `Every ${WEEKDAYS[item.day_of_week] ?? 'week'}`
      : item.frequency === 'WEEKDAYS'
        ? 'Weekdays'
        : 'Every day'
  return `${days} at ${clock(item.time_of_day)}`
}

function audienceWords(item: AutomationItem): string {
  if (item.audience === 'SELF') return 'me'
  if (item.audience === 'ROLE') return `every ${roleLabel(item.audience_role).toLowerCase()}`
  if (item.audience === 'NON_REPORTERS') return "whoever hasn't reported"
  const n = item.audience_user_ids.length
  return n === 1 ? '1 person' : `${n} people`
}

// Why a run was skipped, in words; the code stays in the tooltip.
function skipWords(reason: string | null): string {
  if (!reason) return 'Not sent'
  if (reason.startsWith('outside_whatsapp_session_window')) return "They haven't messaged in 24 hours, so WhatsApp blocks it"
  if (reason.startsWith('template_')) return 'The WhatsApp message template is not ready'
  return 'Not sent'
}

interface FormState {
  action: AutomationAction
  audience: AutomationAudience
  audience_role: string
  audience_user_ids: string[]
  message: string
  frequency: AutomationFrequency
  day_of_week: number
  time_of_day: string
}

const DEFAULT_FORM: FormState = {
  action: 'REMINDER',
  audience: 'SELF',
  audience_role: 'SITE_ENGINEER',
  audience_user_ids: [],
  message: '',
  frequency: 'DAILY',
  day_of_week: 0,
  time_of_day: '17:00',
}

const errorText = (err: unknown) => {
  const e = err as { response?: { data?: { detail?: unknown } }; message?: string }
  const d = e?.response?.data?.detail
  if (typeof d === 'string') return d
  if (Array.isArray(d) && d[0]?.msg) return String(d[0].msg).replace(/^Value error, /, '')
  return e?.message ?? 'Something went wrong'
}

export default function AutomationsPage({ embedded = false }: { embedded?: boolean } = {}) {
  const { scope } = useScope()
  const { me } = useAuth()
  const toast = useToast()
  const qc = useQueryClient()
  const siteNames = useSiteNames()
  const canTargetOthers = TARGET_OTHERS.includes((me?.role ?? '').toUpperCase())

  const { data, isLoading, isError, refetch } = useQuery({ queryKey: ['automations'], queryFn: fetchAutomationsApi })
  // On first, then by time of day.
  const items = React.useMemo(
    () => [...(data ?? [])].sort((a, b) => Number(b.enabled) - Number(a.enabled) || a.time_of_day.localeCompare(b.time_of_day)),
    [data],
  )
  const { data: projects = [] } = useQuery({ queryKey: ['filter-projects'], queryFn: fetchProjects })
  const projectName = React.useMemo(() => new Map(projects.map((p) => [p.id, p.name])), [projects])

  const [createOpen, setCreateOpen] = React.useState(false)
  const [runsFor, setRunsFor] = React.useState<AutomationItem | null>(null)
  const [busy, setBusy] = React.useState<string | null>(null)

  const where = (item: AutomationItem) =>
    item.site_id
      ? siteNames.get(item.site_id)?.name ?? 'A site'
      : item.project_id
        ? projectName.get(item.project_id) ?? 'A project'
        : 'All projects'

  const toggle = async (item: AutomationItem) => {
    setBusy(item.id)
    try {
      await updateAutomationApi(item.id, { enabled: !item.enabled })
      toast.success(item.enabled ? 'Paused' : 'Turned on', when(item))
      await qc.invalidateQueries({ queryKey: ['automations'] })
    } catch (err) {
      toast.error('Could not change it', errorText(err))
    } finally {
      setBusy(null)
    }
  }

  const remove = async (item: AutomationItem) => {
    if (!window.confirm(`Delete "${when(item)}, ${ACTION_WORDS[item.action]}"? This can't be undone.`)) return
    setBusy(item.id)
    try {
      await deleteAutomationApi(item.id)
      toast.success('Deleted', when(item))
      await qc.invalidateQueries({ queryKey: ['automations'] })
    } catch (err) {
      toast.error('Could not delete it', errorText(err))
    } finally {
      setBusy(null)
    }
  }

  const newButton = (
    <Button size="sm" className="gap-1.5 font-semibold" onClick={() => setCreateOpen(true)}>
      <Plus className="size-4" /> New automation
    </Button>
  )

  return (
    <div className="flex w-full flex-col gap-4 pb-8">
      {embedded ? (
        <div className="flex flex-wrap items-start justify-between gap-3">
          <p className="max-w-2xl text-sm text-muted-foreground">
            Messages Mesiri sends on WhatsApp on a schedule. You can also set one up by telling Mesiri on WhatsApp, e.g. "every day at 5
            pm send me the DPR".
          </p>
          {newButton}
        </div>
      ) : (
        <PageHeader title="Automations" subtitle="Messages Mesiri sends on WhatsApp on a schedule" actions={newButton} />
      )}

      {isError ? (
        <Callout
          tone="draft"
          icon={TriangleAlert}
          action={
            <Button variant="outline" size="sm" className="bg-background" onClick={() => refetch()}>
              Try again
            </Button>
          }
        >
          Automations could not be loaded.
        </Callout>
      ) : isLoading ? (
        <div className="flex flex-col gap-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-16 rounded-lg" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed px-6 py-12 text-center">
          <CalendarClock className="size-6 text-muted-foreground" aria-hidden="true" />
          <p className="text-sm font-medium">No automations yet</p>
          <p className="max-w-sm text-sm text-muted-foreground">For example: every day at 6 pm, send the DPR to the client's project manager.</p>
          <Button size="sm" className="mt-2 gap-1.5" onClick={() => setCreateOpen(true)}>
            <Plus className="size-4" /> New automation
          </Button>
        </div>
      ) : (
        <ul className="divide-y rounded-lg border">
          {items.map((item) => (
            <li key={item.id} className={cn('flex flex-col gap-3 px-4 py-3 sm:flex-row sm:items-center', !item.enabled && 'bg-muted/30')}>
              <div className="min-w-0 flex-1">
                <p className={cn('text-sm', !item.enabled && 'text-muted-foreground')}>
                  <span className="font-semibold">{when(item)}</span>, {ACTION_WORDS[item.action]} to {audienceWords(item)}
                </p>
                {item.action === 'REMINDER' && item.message && <p className="mt-0.5 truncate text-sm text-muted-foreground">"{item.message}"</p>}
                <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                  <span className={cn('inline-flex items-center gap-1 font-medium', item.enabled ? 'text-emerald-700 dark:text-emerald-400' : '')}>
                    <span className={cn('size-1.5 rounded-full', item.enabled ? 'bg-emerald-500' : 'bg-muted-foreground')} aria-hidden="true" />
                    {item.enabled ? 'On' : 'Paused'}
                  </span>
                  <span className="inline-flex items-center gap-1">
                    <MapPin className="size-3" aria-hidden="true" /> {where(item)}
                  </span>
                  <span>{item.last_run_on ? `Last ran ${new Date(item.last_run_on).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })}` : 'Not run yet'}</span>
                </p>
              </div>
              <div className="flex shrink-0 gap-1.5">
                <Button variant="outline" size="sm" onClick={() => setRunsFor(item)}>
                  History
                </Button>
                <Button variant="outline" size="sm" disabled={busy === item.id} onClick={() => toggle(item)}>
                  {item.enabled ? 'Pause' : 'Turn on'}
                </Button>
                <Button variant="ghost" size="sm" className="text-destructive hover:text-destructive" disabled={busy === item.id} onClick={() => remove(item)}>
                  Delete
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}

      <p className="text-xs text-muted-foreground">
        WhatsApp only lets Mesiri message people who wrote to it in the last 24 hours; anyone else is skipped and shows in History.
      </p>

      {/* Keyed so each opening starts from a blank form. */}
      <CreateDialog
        key={createOpen ? 'open' : 'closed'}
        open={createOpen}
        onOpenChange={setCreateOpen}
        canTargetOthers={canTargetOthers}
        scopeText={scope.mode === 'portfolio' ? 'All projects' : scope.mode === 'project' ? scope.projectName : `${scope.projectName} / ${scope.siteName}`}
        projectId={scope.mode !== 'portfolio' ? scope.projectId : null}
        siteId={scope.mode === 'site' ? scope.siteId : null}
        onCreated={() => qc.invalidateQueries({ queryKey: ['automations'] })}
      />
      <RunsSheet item={runsFor} onClose={() => setRunsFor(null)} />
    </div>
  )
}

function CreateDialog({
  open,
  onOpenChange,
  canTargetOthers,
  scopeText,
  projectId,
  siteId,
  onCreated,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  canTargetOthers: boolean
  scopeText: string
  projectId: string | null
  siteId: string | null
  onCreated: () => void
}) {
  const toast = useToast()
  const [form, setForm] = React.useState<FormState>(DEFAULT_FORM)
  const [saving, setSaving] = React.useState(false)
  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setForm((f) => ({ ...f, [k]: v }))

  // People to pick from (the list API answers admins; others won't see the option).
  const { data: users, isError: usersFailed } = useQuery({
    queryKey: ['users'],
    queryFn: fetchUsers,
    enabled: open && canTargetOthers,
  })
  const people = (users ?? []).filter((u) => u.status === 'active')
  const audiences = AUDIENCE_OPTIONS.filter((a) => !a.others || (canTargetOthers && !(a.value === 'USERS' && usersFailed)))

  const needsSite = form.action === 'SEND_DPR' && !siteId
  const problem =
    needsSite
      ? 'A DPR is for one site. Pick a site at the top of the page first.'
      : form.action === 'REMINDER' && !form.message.trim()
        ? 'Write the reminder.'
        : form.audience === 'USERS' && form.audience_user_ids.length === 0
          ? 'Pick at least one person.'
          : null

  const create = async () => {
    setSaving(true)
    try {
      await createAutomationApi({
        project_id: projectId,
        site_id: siteId,
        action: form.action,
        audience: form.audience,
        audience_user_ids: form.audience === 'USERS' ? form.audience_user_ids : undefined,
        audience_role: form.audience === 'ROLE' ? form.audience_role : undefined,
        message: form.action === 'REMINDER' ? form.message.trim() : undefined,
        frequency: form.frequency,
        day_of_week: form.frequency === 'WEEKLY' ? form.day_of_week : undefined,
        time_of_day: form.time_of_day,
        timezone: 'Asia/Kolkata',
      })
      toast.success('Automation added', when({ ...form, day_of_week: form.day_of_week }))
      onCreated()
      onOpenChange(false)
    } catch (err) {
      toast.error('Could not add it', errorText(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>New automation</DialogTitle>
          <DialogDescription>For {scopeText}. Times are India time.</DialogDescription>
        </DialogHeader>
        <div className="grid gap-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="grid gap-1.5">
              <Label>What</Label>
              <Select value={form.action} onValueChange={(v) => set('action', v as AutomationAction)}>
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {ACTION_OPTIONS.map((o) => (
                    <SelectItem key={o.value} value={o.value}>
                      {o.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="grid gap-1.5">
              <Label>To</Label>
              <Select value={form.audience} onValueChange={(v) => set('audience', v as AutomationAudience)}>
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {audiences.map((o) => (
                    <SelectItem key={o.value} value={o.value}>
                      {o.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          {form.audience === 'ROLE' && (
            <div className="grid gap-1.5">
              <Label>Role</Label>
              <Select value={form.audience_role} onValueChange={(v) => set('audience_role', v)}>
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {(Object.keys(ROLE_LABELS) as Role[]).map((r) => (
                    <SelectItem key={r} value={r}>
                      {ROLE_LABELS[r]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

          {form.audience === 'USERS' && (
            <div className="grid gap-1.5">
              <Label>People</Label>
              <ul className="max-h-44 divide-y overflow-y-auto rounded-md border">
                {people.map((u) => {
                  const on = form.audience_user_ids.includes(u.id)
                  return (
                    <li key={u.id}>
                      <label className="flex cursor-pointer items-center gap-2.5 px-3 py-2 text-sm hover:bg-muted/40">
                        <input
                          type="checkbox"
                          className="size-4 accent-primary"
                          checked={on}
                          onChange={() =>
                            set('audience_user_ids', on ? form.audience_user_ids.filter((x) => x !== u.id) : [...form.audience_user_ids, u.id])
                          }
                        />
                        <span className="min-w-0 flex-1 truncate">{u.full_name}</span>
                        <span className="text-xs text-muted-foreground">{u.whatsapp_number ? roleLabel(u.role) : 'No WhatsApp number'}</span>
                      </label>
                    </li>
                  )
                })}
              </ul>
            </div>
          )}

          {form.action === 'REMINDER' && (
            <div className="grid gap-1.5">
              <Label htmlFor="auto-message">Reminder</Label>
              <Input id="auto-message" placeholder="Please send today's update" value={form.message} onChange={(e) => set('message', e.target.value)} />
            </div>
          )}

          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            <div className="grid gap-1.5">
              <Label>How often</Label>
              <Select value={form.frequency} onValueChange={(v) => set('frequency', v as AutomationFrequency)}>
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="DAILY">Every day</SelectItem>
                  <SelectItem value="WEEKDAYS">Weekdays</SelectItem>
                  <SelectItem value="WEEKLY">Once a week</SelectItem>
                </SelectContent>
              </Select>
            </div>
            {form.frequency === 'WEEKLY' && (
              <div className="grid gap-1.5">
                <Label>Day</Label>
                <Select value={String(form.day_of_week)} onValueChange={(v) => set('day_of_week', Number(v))}>
                  <SelectTrigger className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {WEEKDAYS.map((d, i) => (
                      <SelectItem key={d} value={String(i)}>
                        {d}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}
            <div className="grid gap-1.5">
              <Label htmlFor="auto-time">Time</Label>
              <Input id="auto-time" type="time" value={form.time_of_day} onChange={(e) => set('time_of_day', e.target.value)} />
            </div>
          </div>

          {needsSite && <p className="text-sm text-draft">{problem}</p>}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={create} disabled={saving || problem !== null} title={problem ?? undefined}>
            {saving ? 'Adding…' : 'Add automation'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function RunsSheet({ item, onClose }: { item: AutomationItem | null; onClose: () => void }) {
  const { data: runs, isLoading, isError } = useQuery({
    queryKey: ['automation-runs', item?.id],
    queryFn: () => fetchAutomationRunsApi(item!.id),
    enabled: !!item,
  })
  return (
    <Sheet open={!!item} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-md">
        <SheetHeader>
          <SheetTitle>History</SheetTitle>
          <SheetDescription>{item ? `${when(item)}, ${ACTION_WORDS[item.action]}` : ''}</SheetDescription>
        </SheetHeader>
        <div className="px-4 pb-6">
          {isLoading ? (
            <Skeleton className="h-24" />
          ) : isError ? (
            <p className="text-sm text-muted-foreground">The history could not be loaded.</p>
          ) : !runs?.length ? (
            <p className="text-sm text-muted-foreground">It hasn't run yet.</p>
          ) : (
            <ul className="divide-y rounded-lg border">
              {runs.map((r) => {
                const sent = r.status === 'sent'
                return (
                  <li key={r.id} className="flex items-start gap-3 px-3 py-2 text-sm">
                    <span className="w-16 shrink-0 tabular-nums text-muted-foreground">
                      {new Date(r.occurred_on).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate">{r.recipient_name || 'Someone'}</span>
                      {!sent && (
                        <span className="block text-xs text-muted-foreground" title={r.skip_reason ?? undefined}>
                          {skipWords(r.skip_reason)}
                        </span>
                      )}
                    </span>
                    <span className={cn('shrink-0 text-xs font-medium', sent ? 'text-emerald-700 dark:text-emerald-400' : 'text-draft')}>
                      {sent ? 'Sent' : r.status === 'skipped' ? 'Skipped' : r.status === 'pending' ? 'Waiting' : 'Not sent'}
                    </span>
                  </li>
                )
              })}
            </ul>
          )}
        </div>
      </SheetContent>
    </Sheet>
  )
}
