import * as React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CalendarClock, Check, FileText, Send, X } from 'lucide-react'
import { Segmented } from '@/components/dpr-page'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { useToast } from '@/components/ui/toast-notification'
import { fetchUsers } from '@/lib/api'
import { useAuth } from '@/lib/AuthContext'
import { downloadBlob } from '@/lib/export'
import { apiErrorMessage } from '@/lib/logo-upload'
import {
  addSchedule,
  downloadSentPdf,
  fetchSchedules,
  fetchSent,
  fetchSentCopy,
  maySendToOthers,
  sendReport,
  shortDay,
  stopSchedule,
  WEEKDAYS,
  type BriefQuery,
  type ReportScope,
  type SendResult,
} from '@/lib/period-report'
import { cn } from '@/lib/utils'

// PRC-20 / RPT-01: send the report on WhatsApp now, or every week / on the 1st. Each person gets it as their own
// access shows (the API builds it per person). Nothing says "sent" until WhatsApp took it: the list below shows,
// per person, waiting / delivered / not sent and why (most often: they have not messaged Mesiri in 24 hours and the
// WhatsApp template is not approved yet).

type When = 'now' | 'weekly' | 'monthly'

function keyOf(target: ReportScope) {
  return target.scope === 'project' ? ['reports', 'project', target.project_id] : ['reports', 'portfolio']
}

export function SendReportDialog({
  target,
  query,
  what,
  open,
  onOpenChange,
}: {
  target: ReportScope
  query: BriefQuery
  /** "Villa Kakkanad, Week 45" */
  what: string
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const { me } = useAuth()
  const toast = useToast()
  const qc = useQueryClient()
  const others = maySendToOthers(me?.role)
  const users = useQuery({ queryKey: ['users'], queryFn: fetchUsers, enabled: open && others })
  const [when, setWhen] = React.useState<When>('now')
  const [day, setDay] = React.useState(0)
  const [time, setTime] = React.useState('08:00')
  const [note, setNote] = React.useState('')
  const [picked, setPicked] = React.useState<string[]>(() => (me?.user_id ? [me.user_id] : []))
  const [result, setResult] = React.useState<SendResult | null>(null)

  const people = (users.data ?? []).filter((u) => u.status === 'active').sort((a, b) => a.full_name.localeCompare(b.full_name))
  const toggle = (id: string) => setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]))
  const recipients = others ? picked : []

  const go = useMutation({
    mutationFn: async () => {
      if (when === 'now') return { kind: 'sent' as const, result: await sendReport(target, query, { recipient_user_ids: recipients, note: note || undefined }) }
      await addSchedule(target, {
        frequency: when === 'weekly' ? 'WEEKLY' : 'MONTHLY',
        day_of_week: when === 'weekly' ? day : undefined,
        time_of_day: time,
        recipient_user_ids: recipients,
        note: note || undefined,
      })
      return { kind: 'scheduled' as const }
    },
    onSuccess: (out) => {
      qc.invalidateQueries({ queryKey: keyOf(target) })
      if (out.kind === 'sent') setResult(out.result)
      else {
        toast.success(when === 'weekly' ? `Every ${WEEKDAYS[day]} at ${time}` : `On the 1st of each month at ${time}`, 'The report will go by itself.')
        onOpenChange(false)
      }
    },
    onError: (err) => toast.error(when === 'now' ? 'The report was not sent' : 'The schedule was not saved', apiErrorMessage(err)),
  })

  const close = (v: boolean) => {
    onOpenChange(v)
    if (!v) setResult(null)
  }

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{result ? 'Report on its way' : 'Send this report'}</DialogTitle>
          <DialogDescription>{what}</DialogDescription>
        </DialogHeader>
        {result ? (
          <div className="flex flex-col gap-3">
            <ul className="divide-y rounded-lg border">
              {result.people.map((p) => (
                <li key={p.user_id} className="flex items-start gap-2 px-3 py-2 text-sm">
                  {p.status === 'queued' ? <Check className="mt-0.5 size-4 text-success" /> : <X className="mt-0.5 size-4 text-destructive" />}
                  <div className="min-w-0">
                    <p className="font-medium">{p.name}</p>
                    <p className="text-xs text-muted-foreground">
                      {p.status === 'queued' ? (p.sees_money === false ? 'Going on WhatsApp, without money (their role)' : 'Going on WhatsApp') : `Not sent: ${p.reason}`}
                    </p>
                  </div>
                </li>
              ))}
            </ul>
            <p className="text-xs text-muted-foreground">It reaches people who messaged Mesiri in the last 24 hours within a minute. The others get it once the WhatsApp template is approved; the list on the page says which.</p>
            <DialogFooter><Button onClick={() => close(false)}>Done</Button></DialogFooter>
          </div>
        ) : (
          <form className="flex flex-col gap-4" onSubmit={(e) => { e.preventDefault(); go.mutate() }}>
            <div className="flex flex-col gap-2">
              <span className="text-sm font-medium">When</span>
              <Segmented label="When" value={when} onChange={setWhen} options={[
                { value: 'now', label: 'Now, once' },
                { value: 'weekly', label: 'Every week' },
                { value: 'monthly', label: 'On the 1st' },
              ]} />
              {when !== 'now' && (
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  {when === 'weekly' && (
                    <>
                      <label htmlFor="report-day" className="sr-only">Day</label>
                      <select id="report-day" className="h-8 rounded-md border bg-background px-2" value={day} onChange={(e) => setDay(Number(e.target.value))}>
                        {WEEKDAYS.map((d, i) => <option key={d} value={i}>{d}</option>)}
                      </select>
                    </>
                  )}
                  <label htmlFor="report-time" className="sr-only">Time</label>
                  <input id="report-time" type="time" className="h-8 rounded-md border bg-background px-2" value={time} onChange={(e) => setTime(e.target.value)} required />
                  <span className="text-xs text-muted-foreground">{when === 'weekly' ? 'the week just finished, Monday to Sunday' : 'last month'}</span>
                </div>
              )}
            </div>
            <div className="flex flex-col gap-2">
              <span className="text-sm font-medium">To</span>
              {!others ? (
                <p className="text-sm text-muted-foreground">You. Owners, admins and project managers can send it to others.</p>
              ) : users.isLoading ? (
                <p className="text-sm text-muted-foreground">Loading the team…</p>
              ) : (
                <ul className="flex max-h-48 flex-wrap gap-1.5 overflow-y-auto">
                  {people.map((u) => {
                    const on = picked.includes(u.id)
                    const noWa = !u.whatsapp_number
                    return (
                      <li key={u.id}>
                        <button
                          type="button"
                          disabled={noWa}
                          aria-pressed={on}
                          onClick={() => toggle(u.id)}
                          title={noWa ? 'No WhatsApp number: add it in Team' : undefined}
                          className={cn('rounded-full border px-2.5 py-1 text-sm', on ? 'border-foreground bg-foreground text-background' : 'hover:bg-muted/60', noWa && 'cursor-not-allowed opacity-50')}
                        >
                          {u.full_name}
                          <span className={cn('ml-1 text-xs', on ? 'opacity-80' : 'text-muted-foreground')}>{u.role.replace('_', ' ').toLowerCase()}</span>
                        </button>
                      </li>
                    )
                  })}
                </ul>
              )}
              {others && <p className="text-xs text-muted-foreground">Each person gets what their role shows: rupees only for those who see spending.</p>}
            </div>
            <div className="flex flex-col gap-1.5">
              <label htmlFor="report-note" className="text-sm font-medium">Note <span className="font-normal text-muted-foreground">(optional, printed on page 1)</span></label>
              <textarea id="report-note" maxLength={300} rows={2} className="rounded-md border bg-background px-3 py-2 text-sm" placeholder="Rain stopped work on Thursday." value={note} onChange={(e) => setNote(e.target.value)} />
            </div>
            <DialogFooter className="items-center gap-2 sm:justify-between">
              <p className="text-xs text-muted-foreground">On WhatsApp: a short summary and the PDF.</p>
              <Button type="submit" disabled={go.isPending || (others && picked.length === 0)}>
                {when === 'now' ? <Send className="size-4" /> : <CalendarClock className="size-4" />}
                {go.isPending ? 'Working…' : when === 'now' ? 'Send now' : 'Save schedule'}
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  )
}

const DELIVERY_TONE: Record<string, string> = {
  sent: 'text-success',
  pending: 'text-muted-foreground',
  skipped: 'text-destructive',
}

function CopyRow({ p }: { p: { snapshot_id: string; name: string; delivery: string; word: string; reason: string | null } }) {
  const toast = useToast()
  const [changed, setChanged] = React.useState<{ label: string; sent: string; now: string }[] | null>(null)
  const check = async () => {
    try {
      setChanged((await fetchSentCopy(p.snapshot_id)).changed_since)
    } catch (err) {
      toast.error('Could not check the copy', apiErrorMessage(err))
    }
  }
  const pdf = async () => {
    try {
      downloadBlob(`sent-report-${p.name.replace(/\s+/g, '-')}.pdf`, await downloadSentPdf(p.snapshot_id))
    } catch (err) {
      toast.error('Could not open the PDF', apiErrorMessage(err))
    }
  }
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1 py-1.5 text-sm">
      <span className="min-w-28 font-medium">{p.name}</span>
      <span className={cn('text-xs', DELIVERY_TONE[p.delivery] ?? 'text-muted-foreground')}>{p.word}{p.reason ? `: ${p.reason}` : ''}</span>
      <span className="ml-auto flex gap-1">
        <Button size="sm" variant="ghost" onClick={check}>What changed?</Button>
        <Button size="sm" variant="ghost" onClick={pdf}><FileText className="size-3.5" /> PDF as sent</Button>
      </span>
      {changed !== null && (
        <p className="w-full text-xs text-muted-foreground">
          {changed.length === 0 ? 'Nothing has changed since it was sent.' : changed.map((c) => `${c.label}: ${c.sent} then, ${c.now} now`).join(' · ')}
        </p>
      )}
    </li>
  )
}

/** What went (newest first, per person: waiting / delivered / not sent and why) and what goes by itself. */
export function SentAndScheduled({ target }: { target: ReportScope }) {
  const toast = useToast()
  const qc = useQueryClient()
  const sent = useQuery({ queryKey: [...keyOf(target), 'sent'], queryFn: () => fetchSent(target), refetchInterval: 30_000 })
  const schedules = useQuery({ queryKey: [...keyOf(target), 'schedules'], queryFn: () => fetchSchedules(target) })
  const stop = useMutation({
    mutationFn: stopSchedule,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: [...keyOf(target), 'schedules'] })
      toast.success('Stopped', 'The report will not go by itself any more.')
    },
    onError: (err) => toast.error('Could not stop it', apiErrorMessage(err)),
  })
  const sends = sent.data ?? []
  const plans = schedules.data ?? []
  if (sends.length === 0 && plans.length === 0) return null
  return (
    <section className="flex flex-col gap-3 border-t pt-4">
      <h2 className="text-[15px] font-semibold">Sent and scheduled</h2>
      {plans.length > 0 && (
        <ul className="divide-y rounded-lg border">
          {plans.map((s) => (
            <li key={s.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-sm">
              <CalendarClock className="size-4 text-muted-foreground" />
              <span className="font-medium">
                {s.frequency === 'WEEKLY' ? `Every ${WEEKDAYS[s.day_of_week ?? 0]}` : 'On the 1st of each month'} at {s.time_of_day}
              </span>
              <span className="text-muted-foreground">to {s.recipients.map((r) => r.name).join(', ')}</span>
              {s.last_run_on && <span className="text-xs text-muted-foreground">last went {shortDay(s.last_run_on)}</span>}
              <Button size="sm" variant="ghost" className="ml-auto" onClick={() => stop.mutate(s.id)} disabled={stop.isPending}>Stop</Button>
            </li>
          ))}
        </ul>
      )}
      {sends.length > 0 && (
        <ul className="flex flex-col gap-2">
          {sends.map((s) => (
            <li key={s.send_id} className="rounded-lg border px-3 py-2">
              <p className="text-sm">
                <span className="font-medium">{s.period.kind === 'custom' ? s.period.range : `${s.period.label}, ${s.period.range}`}</span>
                <span className="text-muted-foreground"> · {s.trigger === 'schedule' ? 'by schedule' : `by ${s.sent_by ?? 'someone'}`} · {new Date(s.created_at).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' })}</span>
              </p>
              {s.note && <p className="text-xs italic text-muted-foreground">“{s.note}”</p>}
              <ul className="divide-y">{s.people.map((p) => <CopyRow key={p.snapshot_id} p={p} />)}</ul>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
