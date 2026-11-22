import * as React from 'react'
import { useQuery } from '@tanstack/react-query'
import { Plus, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { useToast } from '@/components/ui/toast-notification'
import { recordAttendanceApi, recordWorkApi } from '@/lib/api'
import { useAuth } from '@/lib/AuthContext'
import { fetchBoq, maySeeBoq } from '@/lib/boq'
import { errorDetail } from '@/lib/site-day'

/**
 * UX-101 (22 Nov 2026: "data entry through normal forms"): a site's day typed on the dashboard, beside what WhatsApp
 * sends: who came (attendance) and what was done (work). Each saves through the same route as WhatsApp's
 * (`POST /labour/attendance`, `POST /progress/activities`, source `dashboard`), so totals, wages, the BOQ and the DPR
 * read it the same way.
 */

/** Trades offered as you type (any other word is kept as typed). */
const TRADES = ['Mason', 'Helper', 'Carpenter', 'Bar bender', 'Electrician', 'Plumber', 'Painter', 'Tiler', 'Welder']

interface DayScope {
  projectId: string
  siteId: string
  siteName: string
  date: string
}

const key = () => (typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : `k_${Date.now()}_${Math.random()}`)

const FIELD = 'space-y-1'
const LABEL = 'text-sm font-medium'

interface Row {
  trade: string
  headcount: string
  wage: string
}

export function AttendanceDialog({ open, onOpenChange, scope, onSaved }: { open: boolean; onOpenChange: (open: boolean) => void; scope: DayScope; onSaved: () => void }) {
  const toast = useToast()
  const [rows, setRows] = React.useState<Row[]>([{ trade: '', headcount: '', wage: '' }])
  const [contractor, setContractor] = React.useState('')
  const [busy, setBusy] = React.useState(false)
  const idem = React.useRef(key())
  React.useEffect(() => {
    if (!open) return
    setRows([{ trade: '', headcount: '', wage: '' }])
    setContractor('')
    idem.current = key()
  }, [open])

  const lines = rows
    .filter((r) => r.trade.trim() && Number(r.headcount) >= 1)
    .map((r) => ({ trade: r.trade.trim(), headcount: Math.floor(Number(r.headcount)), daily_wage: r.wage.trim() ? r.wage.trim() : null, contractor: contractor.trim() || null }))
  const set = (i: number, patch: Partial<Row>) => setRows((all) => all.map((r, j) => (j === i ? { ...r, ...patch } : r)))

  const save = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!lines.length) return
    setBusy(true)
    try {
      await recordAttendanceApi({ project_id: scope.projectId, site_id: scope.siteId, occurred_date: scope.date, lines }, idem.current)
      const people = lines.reduce((n, l) => n + l.headcount, 0)
      toast.success('Attendance saved', `${people} ${people === 1 ? 'person' : 'people'} at ${scope.siteName}.`)
      onSaved()
      onOpenChange(false)
    } catch (err) {
      toast.error('Not saved', errorDetail(err) ?? 'Please try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg" data-guide="dayform.attendance">
        <form onSubmit={save}>
          <DialogHeader>
            <DialogTitle className="text-base font-semibold">Attendance · {scope.siteName}</DialogTitle>
            <DialogDescription>Who came today, by trade. Another crew on the same day is added to the ones already here.</DialogDescription>
          </DialogHeader>
          <div className="space-y-3 py-4">
            <datalist id="att-trades">{TRADES.map((t) => <option key={t} value={t} />)}</datalist>
            <div className="grid grid-cols-[minmax(0,1fr)_5rem_6.5rem_2rem] items-end gap-2 text-xs text-muted-foreground">
              <span>Trade</span>
              <span>How many</span>
              <span>Daily wage ₹</span>
              <span />
            </div>
            {rows.map((r, i) => (
              <div key={i} className="grid grid-cols-[minmax(0,1fr)_5rem_6.5rem_2rem] items-center gap-2">
                <Input id={i === 0 ? 'att-trade' : undefined} aria-label="Trade" list="att-trades" value={r.trade} onChange={(e) => set(i, { trade: e.target.value })} placeholder="e.g. Carpenter" className="h-9" />
                <Input id={i === 0 ? 'att-count' : undefined} aria-label="How many" type="number" min={1} inputMode="numeric" value={r.headcount} onChange={(e) => set(i, { headcount: e.target.value })} className="h-9" />
                <Input id={i === 0 ? 'att-wage' : undefined} aria-label="Daily wage" type="number" min={0} inputMode="decimal" value={r.wage} onChange={(e) => set(i, { wage: e.target.value })} placeholder="optional" className="h-9" />
                <Button type="button" variant="ghost" size="icon" className="size-8 text-muted-foreground" aria-label="Remove this line" disabled={rows.length === 1} onClick={() => setRows((all) => all.filter((_, j) => j !== i))}>
                  <Trash2 className="size-4" />
                </Button>
              </div>
            ))}
            <Button type="button" variant="ghost" size="sm" className="gap-1.5" onClick={() => setRows((all) => [...all, { trade: '', headcount: '', wage: '' }])}>
              <Plus className="size-4" /> Another trade
            </Button>
            <div className={FIELD}>
              <label className={LABEL} htmlFor="att-contractor">Labour contractor <span className="font-normal text-muted-foreground">(optional)</span></label>
              <Input id="att-contractor" value={contractor} onChange={(e) => setContractor(e.target.value)} placeholder="e.g. Rahim" className="h-9" />
            </div>
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
            <Button type="submit" disabled={busy || !lines.length} className="font-semibold">{busy ? 'Saving…' : 'Save attendance'}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

export function WorkDoneDialog({ open, onOpenChange, scope, onSaved }: { open: boolean; onOpenChange: (open: boolean) => void; scope: DayScope; onSaved: () => void }) {
  const toast = useToast()
  const { me } = useAuth()
  const [work, setWork] = React.useState('')
  const [quantity, setQuantity] = React.useState('')
  const [unit, setUnit] = React.useState('')
  const [place, setPlace] = React.useState('')
  const [finished, setFinished] = React.useState(false)
  const [busy, setBusy] = React.useState(false)
  const idem = React.useRef(key())
  React.useEffect(() => {
    if (!open) return
    setWork('')
    setQuantity('')
    setUnit('')
    setPlace('')
    setFinished(false)
    idem.current = key()
  }, [open])

  // The BOQ's work, offered as you type (and its unit), for the people who may see the BOQ.
  const boq = useQuery({ queryKey: ['boq', scope.projectId], queryFn: () => fetchBoq(scope.projectId), enabled: open && maySeeBoq(me?.role) })
  const lines = React.useMemo(() => (boq.data?.sections ?? []).flatMap((s) => s.lines), [boq.data])
  const pickWork = (value: string) => {
    setWork(value)
    const line = lines.find((l) => l.work.toLowerCase() === value.trim().toLowerCase())
    if (line && !unit) setUnit(line.unit)
  }

  const ready = work.trim() && (!quantity || (Number(quantity) > 0 && unit.trim()))
  const save = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!ready) return
    setBusy(true)
    try {
      await recordWorkApi(
        {
          project_id: scope.projectId,
          site_id: scope.siteId,
          activity_date: scope.date,
          work_type: work.trim(),
          narrative: work.trim(),
          quantities: quantity ? [{ quantity, unit: unit.trim() }] : [],
          place: place.trim() || null,
          finished,
        },
        idem.current,
      )
      toast.success('Work saved', `${work.trim()}${quantity ? `: ${quantity} ${unit.trim()}` : ''} at ${scope.siteName}.`)
      onSaved()
      onOpenChange(false)
    } catch (err) {
      toast.error('Not saved', errorDetail(err) ?? 'Please try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md" data-guide="dayform.work">
        <form onSubmit={save}>
          <DialogHeader>
            <DialogTitle className="text-base font-semibold">Work done · {scope.siteName}</DialogTitle>
            <DialogDescription>What was done today, and how much. It counts on its BOQ line and in the day's report.</DialogDescription>
          </DialogHeader>
          <div className="space-y-3.5 py-4">
            <div className={FIELD}>
              <label className={LABEL} htmlFor="work-what">What was done</label>
              <datalist id="work-lines">{lines.map((l) => <option key={l.id} value={l.work}>{l.boq_code ?? ''}</option>)}</datalist>
              <Input id="work-what" list="work-lines" value={work} onChange={(e) => pickWork(e.target.value)} placeholder="e.g. Slab shuttering" className="h-9" />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className={FIELD}>
                <label className={LABEL} htmlFor="work-qty">How much</label>
                <Input id="work-qty" type="number" min={0} step="any" inputMode="decimal" value={quantity} onChange={(e) => setQuantity(e.target.value)} placeholder="optional" className="h-9" />
              </div>
              <div className={FIELD}>
                <label className={LABEL} htmlFor="work-unit">Unit</label>
                <Input id="work-unit" value={unit} onChange={(e) => setUnit(e.target.value)} placeholder="sqm, cum, nos" className="h-9" />
              </div>
            </div>
            <div className={FIELD}>
              <label className={LABEL} htmlFor="work-place">Where <span className="font-normal text-muted-foreground">(optional)</span></label>
              <Input id="work-place" value={place} onChange={(e) => setPlace(e.target.value)} placeholder="e.g. First floor" className="h-9" />
            </div>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={finished} onChange={(e) => setFinished(e.target.checked)} className="size-4" />
              Finished there
            </label>
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
            <Button type="submit" disabled={busy || !ready} className="font-semibold">{busy ? 'Saving…' : 'Save work'}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
