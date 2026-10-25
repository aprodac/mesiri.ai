import * as React from 'react'
import { Clock, Plus, Power, Trash2, History, X } from 'lucide-react'
import { useScope } from '@/lib/ScopeContext'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from '@/components/ui/table'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog'
import { useToast } from '@/components/ui/toast-notification'
import {
  fetchAutomationsApi,
  createAutomationApi,
  updateAutomationApi,
  deleteAutomationApi,
  fetchAutomationRunsApi,
  type AutomationItem,
  type AutomationRun,
  type AutomationAction,
  type AutomationAudience,
  type AutomationFrequency,
} from '@/lib/api'

const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

const ACTION_LABELS: Record<AutomationAction, string> = {
  SEND_DPR: 'Send the Daily Progress Report',
  COMPLIANCE_SUMMARY: "Tell who has/hasn't reported",
  REMINDER: 'Send a reminder message',
}

const AUDIENCE_LABELS: Record<AutomationAudience, string> = {
  SELF: 'Just me',
  USERS: 'Specific people',
  ROLE: 'Everyone in a role',
  NON_REPORTERS: "Whoever hasn't reported yet",
}

function describeSchedule(item: AutomationItem): string {
  const when =
    item.frequency === 'WEEKLY' && item.day_of_week !== null
      ? `Every ${WEEKDAYS[item.day_of_week] ?? '?'}`
      : item.frequency === 'WEEKDAYS'
        ? 'On weekdays'
        : 'Every day'
  return `${when} at ${item.time_of_day}`
}

interface FormState {
  action: AutomationAction
  audience: AutomationAudience
  audience_role: string
  audience_user_ids_text: string
  message: string
  frequency: AutomationFrequency
  day_of_week: number
  time_of_day: string
  timezone: string
  project_id: string
  site_id: string
}

const DEFAULT_FORM: FormState = {
  action: 'REMINDER',
  audience: 'SELF',
  audience_role: '',
  audience_user_ids_text: '',
  message: '',
  frequency: 'DAILY',
  day_of_week: 0,
  time_of_day: '17:00',
  timezone: 'Asia/Kolkata',
  project_id: '',
  site_id: '',
}

export default function AutomationsPage({ embedded = false }: { embedded?: boolean } = {}) {
  const { scope } = useScope()
  const toast = useToast()

  const [items, setItems] = React.useState<AutomationItem[]>([])
  const [loading, setLoading] = React.useState(true)
  const [createOpen, setCreateOpen] = React.useState(false)
  const [form, setForm] = React.useState<FormState>(DEFAULT_FORM)
  const [saving, setSaving] = React.useState(false)

  const [runsFor, setRunsFor] = React.useState<AutomationItem | null>(null)
  const [runs, setRuns] = React.useState<AutomationRun[]>([])
  const [runsLoading, setRunsLoading] = React.useState(false)

  const load = React.useCallback(async () => {
    setLoading(true)
    try {
      const data = await fetchAutomationsApi()
      setItems(data)
    } catch (err) {
      console.warn('Failed to load automations:', err)
      setItems([])
    } finally {
      setLoading(false)
    }
  }, [])

  React.useEffect(() => {
    load()
  }, [load])

  React.useEffect(() => {
    if (!createOpen) return
    setForm({
      ...DEFAULT_FORM,
      project_id: scope.mode !== 'portfolio' ? scope.projectId : '',
      site_id: scope.mode === 'site' ? scope.siteId : '',
    })
  }, [createOpen, scope])

  const scopeLabel = React.useMemo(() => {
    if (scope.mode === 'portfolio') return 'Portfolio Scope (All Organization Automations)'
    if (scope.mode === 'project') return `Project Scope: ${scope.projectName}`
    return `Site Scope: ${scope.projectName} / ${scope.siteName}`
  }, [scope])

  const handleToggle = async (item: AutomationItem) => {
    try {
      await updateAutomationApi(item.id, { enabled: !item.enabled })
      toast.success(
        `Automation ${item.enabled ? 'paused' : 'resumed'}`,
        describeSchedule(item)
      )
      load()
    } catch (err: any) {
      toast.error('Failed to update automation', err?.response?.data?.detail || err.message)
    }
  }

  const handleDelete = async (item: AutomationItem) => {
    if (!window.confirm('Delete this automation? This cannot be undone.')) return
    try {
      await deleteAutomationApi(item.id)
      toast.success('Automation deleted', describeSchedule(item))
      load()
    } catch (err: any) {
      toast.error('Failed to delete automation', err?.response?.data?.detail || err.message)
    }
  }

  const openRuns = async (item: AutomationItem) => {
    setRunsFor(item)
    setRunsLoading(true)
    try {
      const data = await fetchAutomationRunsApi(item.id)
      setRuns(data)
    } catch (err) {
      console.warn('Failed to load automation runs:', err)
      setRuns([])
    } finally {
      setRunsLoading(false)
    }
  }

  const handleCreate = async () => {
    setSaving(true)
    try {
      const audience_user_ids = form.audience_user_ids_text
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean)
      await createAutomationApi({
        project_id: form.project_id || null,
        site_id: form.site_id || null,
        action: form.action,
        audience: form.audience,
        audience_user_ids: form.audience === 'USERS' && audience_user_ids.length ? audience_user_ids : undefined,
        audience_role: form.audience === 'ROLE' ? form.audience_role : undefined,
        message: form.action === 'REMINDER' ? form.message : undefined,
        frequency: form.frequency,
        day_of_week: form.frequency === 'WEEKLY' ? form.day_of_week : undefined,
        time_of_day: form.time_of_day,
        timezone: form.timezone,
      })
      toast.success('Automation created', describeSchedule({ ...form, day_of_week: form.day_of_week } as any))
      setCreateOpen(false)
      load()
    } catch (err: any) {
      toast.error('Failed to create automation', err?.response?.data?.detail || err.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="flex flex-col gap-4 w-full max-w-full relative pb-12">
      {/* Page Header (embedded in the WhatsApp page: just the action) */}
      {embedded ? (
        <div className="flex justify-end">
          <Button size="sm" className="gap-1.5 font-semibold" onClick={() => setCreateOpen(true)}>
            <Plus className="size-4" /> New automation
          </Button>
        </div>
      ) : (
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b pb-3.5">
        <div className="flex items-center gap-3">
          <div className="size-10 rounded-lg border border-violet-500/30 bg-violet-500/10 flex items-center justify-center text-violet-600 dark:text-violet-400 shrink-0 shadow-2xs">
            <Clock className="size-5" />
          </div>
          <div>
            <h1 className="text-xl font-bold tracking-tight text-foreground flex items-center gap-2">
              Scheduled Automations
              <Badge variant="outline" className="text-[10px] font-mono border-violet-500/30 text-violet-600 dark:text-violet-400">
                WhatsApp
              </Badge>
            </h1>
            <p className="text-xs text-muted-foreground font-medium">{scopeLabel}</p>
          </div>
        </div>

        <Button
          size="sm"
          className="h-9 px-3.5 text-xs font-semibold gap-1.5 shadow-2xs"
          onClick={() => setCreateOpen(true)}
        >
          <Plus className="size-4" />
          New Automation
        </Button>
      </div>
      )}

      <p className="max-w-2xl text-sm text-muted-foreground">
        Messages Mesiri sends on WhatsApp on a schedule, e.g. "every day at 5 pm send me the DPR" or "at 3 pm tell me who
        hasn't reported". WhatsApp only lets them reach people who messaged in the last 24 hours; anyone else shows as skipped in
        the run history.
      </p>

      {loading ? (
        <div className="py-20 text-center text-xs text-muted-foreground">Loading automations...</div>
      ) : items.length === 0 ? (
        <div className="py-20 border rounded-lg bg-card text-center flex flex-col items-center justify-center p-6 gap-2">
          <Clock className="size-10 text-muted-foreground/40" />
          <h3 className="text-sm font-semibold text-foreground">No Automations Yet</h3>
          <p className="text-xs text-muted-foreground max-w-sm">
            Create your first recurring schedule, or set one up by just telling the WhatsApp
            assistant what you want.
          </p>
          <Button size="sm" className="mt-2 text-xs font-semibold gap-1.5" onClick={() => setCreateOpen(true)}>
            <Plus className="size-3.5" />
            Create Automation
          </Button>
        </div>
      ) : (
        <div className="border rounded-lg overflow-hidden bg-card shadow-2xs">
          <Table>
            <TableHeader className="bg-muted/40">
              <TableRow className="hover:bg-transparent">
                <TableHead className="text-xs font-semibold h-10">Schedule</TableHead>
                <TableHead className="text-xs font-semibold h-10">Action</TableHead>
                <TableHead className="text-xs font-semibold h-10">Audience</TableHead>
                <TableHead className="text-xs font-semibold h-10 text-center">Status</TableHead>
                <TableHead className="text-xs font-semibold h-10 text-right w-[140px]">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((item) => (
                <TableRow key={item.id} className="hover:bg-muted/40 text-xs">
                  <TableCell className="font-semibold text-foreground">
                    {describeSchedule(item)}
                  </TableCell>
                  <TableCell>{ACTION_LABELS[item.action] ?? item.action}</TableCell>
                  <TableCell>
                    {AUDIENCE_LABELS[item.audience] ?? item.audience}
                    {item.audience === 'ROLE' && item.audience_role ? ` (${item.audience_role})` : ''}
                    {item.audience === 'USERS' && item.audience_user_ids.length
                      ? ` (${item.audience_user_ids.length})`
                      : ''}
                  </TableCell>
                  <TableCell className="text-center">
                    <Badge
                      className={
                        item.enabled
                          ? 'bg-emerald-500/10 text-emerald-600 border-emerald-500/20 text-[10px]'
                          : 'bg-muted text-muted-foreground text-[10px]'
                      }
                    >
                      {item.enabled ? 'ACTIVE' : 'PAUSED'}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex items-center justify-end gap-1">
                      <Button
                        size="sm"
                        variant="ghost"
                        className="size-7 p-0"
                        title="Run history"
                        onClick={() => openRuns(item)}
                      >
                        <History className="size-4 text-blue-500" />
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        className="size-7 p-0"
                        title={item.enabled ? 'Pause' : 'Resume'}
                        onClick={() => handleToggle(item)}
                      >
                        <Power className={item.enabled ? 'size-4 text-amber-500' : 'size-4 text-emerald-500'} />
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        className="size-7 p-0"
                        title="Delete"
                        onClick={() => handleDelete(item)}
                      >
                        <Trash2 className="size-4 text-red-500" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      {/* Create Dialog */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>New Automation</DialogTitle>
          </DialogHeader>
          <div className="grid gap-3 py-2">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label className="text-xs mb-1 block">What should happen</Label>
                <Select value={form.action} onValueChange={(v) => setForm((f) => ({ ...f, action: v as AutomationAction }))}>
                  <SelectTrigger className="h-8 text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="SEND_DPR" className="text-xs">Send the DPR</SelectItem>
                    <SelectItem value="COMPLIANCE_SUMMARY" className="text-xs">Who hasn't reported</SelectItem>
                    <SelectItem value="REMINDER" className="text-xs">Send a reminder</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label className="text-xs mb-1 block">Who to tell</Label>
                <Select value={form.audience} onValueChange={(v) => setForm((f) => ({ ...f, audience: v as AutomationAudience }))}>
                  <SelectTrigger className="h-8 text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="SELF" className="text-xs">Just me</SelectItem>
                    <SelectItem value="USERS" className="text-xs">Specific people</SelectItem>
                    <SelectItem value="ROLE" className="text-xs">A role (e.g. Site Engineer)</SelectItem>
                    <SelectItem value="NON_REPORTERS" className="text-xs">Whoever hasn't reported</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>

            {form.audience === 'USERS' && (
              <div>
                <Label className="text-xs mb-1 block">User IDs (comma-separated)</Label>
                <Input
                  className="h-8 text-xs"
                  placeholder="e.g. user-id-1, user-id-2"
                  value={form.audience_user_ids_text}
                  onChange={(e) => setForm((f) => ({ ...f, audience_user_ids_text: e.target.value }))}
                />
              </div>
            )}
            {form.audience === 'ROLE' && (
              <div>
                <Label className="text-xs mb-1 block">Role</Label>
                <Input
                  className="h-8 text-xs"
                  placeholder="e.g. SITE_ENGINEER"
                  value={form.audience_role}
                  onChange={(e) => setForm((f) => ({ ...f, audience_role: e.target.value }))}
                />
              </div>
            )}
            {form.action === 'REMINDER' && (
              <div>
                <Label className="text-xs mb-1 block">Message</Label>
                <Input
                  className="h-8 text-xs"
                  placeholder="e.g. Please submit today's DPR"
                  value={form.message}
                  onChange={(e) => setForm((f) => ({ ...f, message: e.target.value }))}
                />
              </div>
            )}

            <div className="grid grid-cols-3 gap-3">
              <div>
                <Label className="text-xs mb-1 block">Frequency</Label>
                <Select value={form.frequency} onValueChange={(v) => setForm((f) => ({ ...f, frequency: v as AutomationFrequency }))}>
                  <SelectTrigger className="h-8 text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="DAILY" className="text-xs">Every day</SelectItem>
                    <SelectItem value="WEEKDAYS" className="text-xs">Weekdays</SelectItem>
                    <SelectItem value="WEEKLY" className="text-xs">Weekly</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              {form.frequency === 'WEEKLY' && (
                <div>
                  <Label className="text-xs mb-1 block">Day</Label>
                  <Select
                    value={String(form.day_of_week)}
                    onValueChange={(v) => setForm((f) => ({ ...f, day_of_week: Number(v) }))}
                  >
                    <SelectTrigger className="h-8 text-xs">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {WEEKDAYS.map((d, i) => (
                        <SelectItem key={d} value={String(i)} className="text-xs">{d}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              )}
              <div>
                <Label className="text-xs mb-1 block">Time</Label>
                <Input
                  type="time"
                  className="h-8 text-xs"
                  value={form.time_of_day}
                  onChange={(e) => setForm((f) => ({ ...f, time_of_day: e.target.value }))}
                />
              </div>
            </div>

            {form.action === 'SEND_DPR' && !form.site_id && (
              <p className="text-[11px] text-amber-600">
                A DPR is site-scoped -- switch to a site scope before creating this automation, or it
                will be rejected.
              </p>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" size="sm" onClick={() => setCreateOpen(false)}>
              Cancel
            </Button>
            <Button size="sm" onClick={handleCreate} disabled={saving}>
              {saving ? 'Creating...' : 'Create Automation'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Run History Dialog */}
      <Dialog open={!!runsFor} onOpenChange={(open) => !open && setRunsFor(null)}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle className="flex items-center justify-between">
              <span>Run History</span>
              <Button size="sm" variant="ghost" className="size-7 p-0" onClick={() => setRunsFor(null)}>
                <X className="size-4" />
              </Button>
            </DialogTitle>
          </DialogHeader>
          {runsLoading ? (
            <div className="py-10 text-center text-xs text-muted-foreground">Loading run history...</div>
          ) : runs.length === 0 ? (
            <div className="py-10 text-center text-xs text-muted-foreground">
              No runs recorded yet -- this automation hasn't fired.
            </div>
          ) : (
            <div className="max-h-80 overflow-y-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="text-xs">Date</TableHead>
                    <TableHead className="text-xs">Recipient</TableHead>
                    <TableHead className="text-xs">Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {runs.map((run) => (
                    <TableRow key={run.id} className="text-xs">
                      <TableCell>{run.occurred_on}</TableCell>
                      <TableCell>{run.recipient_name || '—'}</TableCell>
                      <TableCell>
                        <Badge
                          className={
                            run.status === 'sent'
                              ? 'bg-emerald-500/10 text-emerald-600 border-emerald-500/20 text-[10px]'
                              : run.status === 'skipped'
                                ? 'bg-amber-500/10 text-amber-600 border-amber-500/20 text-[10px]'
                                : 'bg-muted text-muted-foreground text-[10px]'
                          }
                        >
                          {run.status.toUpperCase()}
                        </Badge>
                        {run.skip_reason && (
                          <div className="text-[10px] text-muted-foreground mt-0.5">{run.skip_reason}</div>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}
