import * as React from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, Plus, ShieldAlert, Trash2 } from 'lucide-react'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Combobox } from '@/components/ui/combobox'
import { DatePicker } from '@/components/ui/date-picker'
import { fetchProjects, fetchSites } from '@/lib/projects'
import { fetchWorkersApi, recordAttendanceApi, type RecordAttendanceLineInput } from '@/lib/api'
import { newIdempotencyKey } from '@/lib/materials'
import { appNow } from '@/lib/clock'
import type { AppScope } from '@/lib/scope-types'
import { cn } from '@/lib/utils'

// Record attendance on the dashboard (WA-121): the same POST /labour/attendance
// the WhatsApp assistant uses, so "6 masons, 4 helpers" typed here and the same
// sent on WhatsApp become the identical report. One pipeline, one record.

function todayIso(): string {
  return appNow().toISOString().slice(0, 10)
}

// The trades the assistant sees most, as one-tap chips; any other trade is just
// typed. These mirror the WhatsApp wording, lower-cased the same way the backend
// normalises (`normalize_trade`).
const QUICK_TRADES = ['mason', 'helper', 'carpenter', 'bar bender', 'electrician', 'plumber', 'painter']

interface LineDraft {
  key: string
  workerId: string
  workerName: string
  trade: string
  headcount: string
  contractor: string
  dailyWage: string
}

function emptyLine(): LineDraft {
  return { key: crypto.randomUUID(), workerId: '', workerName: '', trade: '', headcount: '1', contractor: '', dailyWage: '' }
}

interface RecordAttendanceDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  scope: AppScope
}

export function RecordAttendanceDialog({ open, onOpenChange, scope }: RecordAttendanceDialogProps) {
  const queryClient = useQueryClient()

  const scopedProjectId = scope.mode === 'project' || scope.mode === 'site' ? scope.projectId : ''
  const scopedSiteId = scope.mode === 'site' ? scope.siteId : ''

  const [projectId, setProjectId] = React.useState(scopedProjectId)
  const [siteId, setSiteId] = React.useState(scopedSiteId)
  const [occurredDate, setOccurredDate] = React.useState(todayIso())
  const [lines, setLines] = React.useState<LineDraft[]>([emptyLine()])
  const [notes, setNotes] = React.useState('')
  const [error, setError] = React.useState('')
  const [success, setSuccess] = React.useState(false)
  // One key per dialog session, so N clicks are one report. Regenerated on open.
  const [idempotencyKey, setIdempotencyKey] = React.useState(newIdempotencyKey)

  React.useEffect(() => {
    if (open) {
      setProjectId(scopedProjectId)
      setSiteId(scopedSiteId)
      setOccurredDate(todayIso())
      setLines([emptyLine()])
      setNotes('')
      setError('')
      setSuccess(false)
      setIdempotencyKey(newIdempotencyKey())
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  const { data: projects = [] } = useQuery({
    queryKey: ['scope-projects'],
    queryFn: fetchProjects,
    enabled: open && !scopedProjectId,
    staleTime: 60_000,
  })

  const { data: sites = [] } = useQuery({
    queryKey: ['scope-sites', projectId],
    queryFn: () => fetchSites(projectId),
    enabled: open && !!projectId && !scopedSiteId,
    staleTime: 60_000,
  })

  // The register, for the optional per-line worker picker. Attendance never
  // writes the register, so a line without a worker is just a trade headcount.
  const { data: workers } = useQuery({
    queryKey: ['labour', 'workers', 'active'],
    queryFn: () => fetchWorkersApi({ status: 'active', limit: 500 }),
    enabled: open,
    staleTime: 60_000,
  })
  const workerById = React.useMemo(() => new Map((workers?.items ?? []).map((w) => [w.id, w])), [workers])
  const workerOptions = React.useMemo(
    () => (workers?.items ?? []).map((w) => ({ value: w.id, label: w.trade ? `${w.name} · ${w.trade}` : w.name })),
    [workers],
  )

  const setLine = (key: string, patch: Partial<LineDraft>) =>
    setLines((prev) => prev.map((l) => (l.key === key ? { ...l, ...patch } : l)))
  const addLine = () => setLines((prev) => [...prev, emptyLine()])
  const removeLine = (key: string) => setLines((prev) => (prev.length > 1 ? prev.filter((l) => l.key !== key) : prev))

  // Picking a worker fills the trade and wage from the register and pins the
  // line to that one person (headcount 1); clearing it returns a trade line.
  const pickWorker = (key: string, workerId: string) => {
    const w = workerById.get(workerId)
    if (!w) {
      setLine(key, { workerId: '', workerName: '' })
      return
    }
    setLine(key, {
      workerId,
      workerName: w.name,
      trade: w.trade ?? '',
      headcount: '1',
      contractor: w.contractor ?? '',
      dailyWage: w.default_daily_wage != null ? String(w.default_daily_wage) : '',
    })
  }

  const mutation = useMutation({
    mutationFn: () => {
      const payloadLines: RecordAttendanceLineInput[] = lines.map((l) => ({
        worker_id: l.workerId || undefined,
        worker_name: l.workerId ? l.workerName : undefined,
        trade: l.trade.trim() || undefined,
        headcount: Math.max(1, Math.floor(Number(l.headcount) || 1)),
        contractor: l.contractor.trim() || undefined,
        daily_wage: l.dailyWage.trim() ? Number(l.dailyWage) : undefined,
      }))
      return recordAttendanceApi(
        {
          project_id: projectId,
          site_id: siteId,
          occurred_date: occurredDate,
          lines: payloadLines,
          notes: notes.trim() || undefined,
        },
        idempotencyKey,
      )
    },
    onSuccess: () => {
      // Every labour read (ledger, chart, statements, Today) re-fetches.
      queryClient.invalidateQueries({ queryKey: ['labour'] })
      queryClient.invalidateQueries({ queryKey: ['today'] })
      setSuccess(true)
      setTimeout(() => onOpenChange(false), 900)
    },
    onError: (err: any) => {
      const detail = err.response?.data?.detail
      if (Array.isArray(detail)) {
        // 422 from the handler: a list of plain-English reasons.
        setError(detail.map((d: any) => (typeof d === 'string' ? d : d?.msg)).filter(Boolean).join(' '))
      } else {
        setError(typeof detail === 'string' ? detail : 'Could not record attendance.')
      }
    },
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    if (!projectId) {
      setError('Project is required.')
      return
    }
    if (!siteId) {
      setError('Site is required — attendance is recorded per site.')
      return
    }
    const bad = lines.find((l) => !l.workerId && !l.trade.trim())
    if (bad) {
      setError('Each line needs a trade (or a worker from the register).')
      return
    }
    const badCount = lines.find((l) => {
      const n = Number(l.headcount)
      return !l.headcount || Number.isNaN(n) || n < 1
    })
    if (badCount) {
      setError('Workers on each line must be 1 or more.')
      return
    }
    mutation.mutate()
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[560px] max-h-[88vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Record attendance</DialogTitle>
          <DialogDescription>Who worked at the site on this day. Saved the same as a WhatsApp attendance.</DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4 py-1 text-xs">
          {error && (
            <div className="bg-destructive/10 border border-destructive text-destructive p-2.5 rounded flex items-center gap-2">
              <ShieldAlert className="size-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}
          {success && (
            <div className="bg-emerald-500/10 border border-emerald-500/30 text-emerald-700 dark:text-emerald-400 p-2.5 rounded flex items-center gap-2">
              <CheckCircle2 className="size-4 shrink-0" />
              <span>Attendance recorded.</span>
            </div>
          )}

          <div className="grid gap-3 sm:grid-cols-3">
            <div className="grid gap-1.5">
              <Label>Project</Label>
              {scopedProjectId ? (
                <Input value={scope.mode !== 'portfolio' ? scope.projectName : ''} disabled />
              ) : (
                <Select value={projectId} onValueChange={(v) => { setProjectId(v); setSiteId('') }}>
                  <SelectTrigger className="h-9"><SelectValue placeholder="Choose project" /></SelectTrigger>
                  <SelectContent>
                    {projects.map((p) => (
                      <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </div>
            <div className="grid gap-1.5">
              <Label>Site</Label>
              {scopedSiteId ? (
                <Input value={scope.mode === 'site' ? scope.siteName : ''} disabled />
              ) : (
                <Select value={siteId} onValueChange={setSiteId} disabled={!projectId}>
                  <SelectTrigger className="h-9"><SelectValue placeholder="Choose site" /></SelectTrigger>
                  <SelectContent>
                    {sites.map((s) => (
                      <SelectItem key={s.id} value={s.id}>{s.name}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="attendanceDate">Day</Label>
              <DatePicker id="attendanceDate" value={occurredDate} onChange={(v) => setOccurredDate(v)} required />
            </div>
          </div>

          <div className="grid gap-2">
            <div className="flex items-center justify-between">
              <Label>Who worked</Label>
              <span className="text-[11px] text-muted-foreground">{lines.length} line{lines.length === 1 ? '' : 's'}</span>
            </div>

            <div className="flex flex-col gap-2">
              {lines.map((l, i) => {
                const pinned = !!l.workerId
                return (
                  <div key={l.key} className="rounded-lg border bg-muted/30 p-2.5">
                    <div className="flex items-start gap-2">
                      <div className="grid flex-1 gap-2 sm:grid-cols-[1fr_auto]">
                        <div className="grid gap-1.5">
                          <Label className="text-[11px] text-muted-foreground">Trade or worker</Label>
                          {workerOptions.length > 0 && (
                            <Combobox
                              options={workerOptions}
                              value={l.workerId}
                              onValueChange={(v) => pickWorker(l.key, v)}
                              placeholder="Pick a worker (optional)"
                              searchPlaceholder="Search the register…"
                              emptyText="No workers found."
                            />
                          )}
                          <Input
                            value={l.trade}
                            onChange={(e) => setLine(l.key, { trade: e.target.value })}
                            placeholder="e.g. mason, helper"
                            disabled={pinned}
                          />
                        </div>
                        <div className="grid gap-1.5">
                          <Label className="text-[11px] text-muted-foreground">Workers</Label>
                          <Input
                            type="number"
                            min="1"
                            step="1"
                            inputMode="numeric"
                            className="w-24 tabular-nums"
                            value={l.headcount}
                            onChange={(e) => setLine(l.key, { headcount: e.target.value })}
                            disabled={pinned}
                          />
                        </div>
                      </div>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        className="size-8 shrink-0 text-muted-foreground hover:text-destructive"
                        onClick={() => removeLine(l.key)}
                        disabled={lines.length === 1}
                        aria-label="Remove line"
                      >
                        <Trash2 className="size-4" />
                      </Button>
                    </div>

                    {i === 0 && !pinned && (
                      <div className="mt-2 flex flex-wrap gap-1">
                        {QUICK_TRADES.map((t) => (
                          <button
                            key={t}
                            type="button"
                            onClick={() => setLine(l.key, { trade: t })}
                            className={cn(
                              'rounded-full border px-2 py-0.5 text-[11px] capitalize transition-colors hover:bg-muted',
                              l.trade === t && 'border-primary bg-primary/10 text-primary-ink',
                            )}
                          >
                            {t}
                          </button>
                        ))}
                      </div>
                    )}

                    <div className="mt-2 grid gap-2 sm:grid-cols-2">
                      <div className="grid gap-1.5">
                        <Label className="text-[11px] text-muted-foreground">Contractor <span className="font-normal">(optional)</span></Label>
                        <Input value={l.contractor} onChange={(e) => setLine(l.key, { contractor: e.target.value })} placeholder="e.g. Suresh team" />
                      </div>
                      <div className="grid gap-1.5">
                        <Label className="text-[11px] text-muted-foreground">Wage / day <span className="font-normal">(optional)</span></Label>
                        <Input type="number" min="0" step="any" inputMode="decimal" value={l.dailyWage} onChange={(e) => setLine(l.key, { dailyWage: e.target.value })} placeholder="₹" />
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>

            <Button type="button" variant="outline" size="sm" className="gap-1.5 self-start" onClick={addLine}>
              <Plus className="size-3.5" /> Add a trade
            </Button>
          </div>

          <div className="grid gap-1.5">
            <Label htmlFor="attendanceNotes">Notes <span className="font-normal text-muted-foreground">(optional)</span></Label>
            <textarea
              id="attendanceNotes"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              className="flex min-h-[52px] w-full rounded-md border border-input bg-transparent px-3 py-2 text-xs shadow-xs focus-visible:outline-hidden focus-visible:ring-1 focus-visible:ring-ring"
              placeholder="Anything about the day"
            />
          </div>

          <DialogFooter className="pt-1">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={mutation.isPending}>
              Cancel
            </Button>
            <Button type="submit" disabled={mutation.isPending || success}>
              {mutation.isPending ? 'Saving…' : 'Record attendance'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
