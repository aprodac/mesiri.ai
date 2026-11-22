import * as React from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { ClipboardPen, Plus, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { api } from '@/lib/api'
import { apiErrorMessage } from '@/lib/logo-upload'

// UX-104 (Ilan, 22 Nov 2026: "dont necessarily make it of tell mesiri, some form also works"): a site's day on a
// form, for anyone at a desk: who came (a trade and how many), the work done, and anything stuck. Each part goes to
// the same API a WhatsApp message's Save uses (POST /labour/attendance, /progress/activities, /progress/issues), so
// the day reads the same on Today, the site day and the evening report. Each part carries its own Idempotency-Key,
// kept while the form is open, so pressing Save again after a failure never records a part twice.

export interface SiteChoice {
  site_id: string
  site_name: string
  project_id: string
  project_name?: string
}

type Crew = { trade: string; count: string }

const ISSUE_TYPES: [string, string][] = [
  ['MATERIAL_SHORTAGE', 'Material ran out'], ['LABOUR_SHORTAGE', 'Short of people'], ['WEATHER', 'Weather'],
  ['DRAWING_PENDING', 'Waiting for a drawing'], ['EQUIPMENT_BREAKDOWN', 'Machine broke down'],
  ['INSPECTION_WAITING', 'Waiting for an inspection'], ['ACCESS', 'No access'], ['SAFETY', 'Safety'], ['QUALITY', 'Quality'],
  ['OTHER', 'Something else'],
]

const FIELD = 'h-9 w-full rounded-md border border-input bg-background px-2.5 text-sm shadow-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring'

function key(part: string): string {
  return `siteday_${part}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`
}

/** The button that opens the form (Today's header): `data-guide="today.record-day"`. */
export function RecordDayButton({ sites, date, disabled }: { sites: SiteChoice[]; date: string; disabled?: boolean }) {
  const [open, setOpen] = React.useState(false)
  if (sites.length === 0) return null
  return (
    <>
      <Button variant="outline" size="sm" className="gap-1.5 bg-background" onClick={() => setOpen(true)} disabled={disabled} data-guide="today.record-day">
        <ClipboardPen className="size-4" aria-hidden /> Record a site's day
      </Button>
      {open && <SiteDayForm sites={sites} date={date} onClose={() => setOpen(false)} />}
    </>
  )
}

export function SiteDayForm({ sites, date, onClose }: { sites: SiteChoice[]; date: string; onClose: () => void }) {
  const queryClient = useQueryClient()
  const [siteId, setSiteId] = React.useState(sites.length === 1 ? sites[0].site_id : '')
  const [crew, setCrew] = React.useState<Crew[]>([{ trade: '', count: '' }])
  const [work, setWork] = React.useState('')
  const [quantity, setQuantity] = React.useState('')
  const [unit, setUnit] = React.useState('')
  const [issue, setIssue] = React.useState('')
  const [issueType, setIssueType] = React.useState('OTHER')
  const [saving, setSaving] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  // One key per part for the life of the form, and the parts already saved (a retry sends only the rest).
  const keys = React.useRef({ attendance: key('att'), work: key('work'), issue: key('issue') })
  const [saved, setSaved] = React.useState<Set<string>>(new Set())

  const site = sites.find((s) => s.site_id === siteId)
  const people = crew.filter((c) => c.trade.trim() && Number(c.count) > 0)
  const hasWork = work.trim().length > 0
  const hasIssue = issue.trim().length > 0
  const ready = !!site && (people.length > 0 || hasWork || hasIssue) && (!quantity || (Number(quantity) > 0 && unit.trim()))

  const save = async () => {
    if (!site || !ready) return
    setSaving(true)
    setError(null)
    const done = new Set(saved)
    const where = { project_id: site.project_id, site_id: site.site_id }
    try {
      if (people.length && !done.has('attendance')) {
        await api.post('/labour/attendance', {
          ...where, occurred_date: date, recorded_via: 'dashboard',
          lines: people.map((c) => ({ trade: c.trade.trim(), headcount: Math.round(Number(c.count)) })),
        }, { headers: { 'Idempotency-Key': keys.current.attendance } })
        done.add('attendance')
      }
      if (hasWork && !done.has('work')) {
        await api.post('/progress/activities', {
          ...where, activity_date: date, source: 'dashboard', work_type: work.trim(), narrative: work.trim(),
          quantities: quantity ? [{ quantity: Number(quantity), unit: unit.trim(), work_type: work.trim() }] : [],
        }, { headers: { 'Idempotency-Key': keys.current.work } })
        done.add('work')
      }
      if (hasIssue && !done.has('issue')) {
        await api.post('/progress/issues', { ...where, issue_type: issueType, severity: 'MEDIUM', narrative: issue.trim() },
          { headers: { 'Idempotency-Key': keys.current.issue } })
        done.add('issue')
      }
      void queryClient.invalidateQueries()
      onClose()
    } catch (err) {
      setSaved(done)
      const kept = [...done].map((d) => ({ attendance: 'who came', work: 'the work', issue: 'the problem' })[d]).join(' and ')
      setError(`${apiErrorMessage(err)}${kept ? ` (${kept} saved; Save sends the rest)` : ''}`)
    } finally {
      setSaving(false)
    }
  }

  const setCrewAt = (i: number, patch: Partial<Crew>) => setCrew((all) => all.map((c, j) => (j === i ? { ...c, ...patch } : c)))

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-lg" data-guide="site-day.form">
        <DialogHeader>
          <DialogTitle>Record a site's day</DialogTitle>
          <DialogDescription>Who came, what got done, and anything stuck. Fill what you have; the rest can wait.</DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="siteday-site">Site</Label>
            <select id="siteday-site" className={FIELD} value={siteId} onChange={(e) => setSiteId(e.target.value)}>
              {sites.length > 1 && <option value="">Pick the site</option>}
              {sites.map((s) => (
                <option key={s.site_id} value={s.site_id}>{s.project_name ? `${s.project_name} · ${s.site_name}` : s.site_name}</option>
              ))}
            </select>
          </div>

          <fieldset className="flex flex-col gap-1.5">
            <legend className="mb-1.5 text-sm font-medium">Who came</legend>
            {crew.map((c, i) => (
              <div key={i} className="flex items-center gap-2">
                <Input aria-label="Trade" placeholder="Mason" value={c.trade} onChange={(e) => setCrewAt(i, { trade: e.target.value })} />
                <Input aria-label="How many" type="number" inputMode="numeric" min={1} placeholder="6" className="w-20" value={c.count} onChange={(e) => setCrewAt(i, { count: e.target.value })} />
                <Button type="button" variant="ghost" size="icon" className="size-9 shrink-0 text-muted-foreground" aria-label="Remove this line" disabled={crew.length === 1} onClick={() => setCrew((all) => all.filter((_, j) => j !== i))}>
                  <Trash2 className="size-4" />
                </Button>
              </div>
            ))}
            <Button type="button" variant="ghost" size="sm" className="gap-1 self-start px-2" onClick={() => setCrew((all) => [...all, { trade: '', count: '' }])}>
              <Plus className="size-4" aria-hidden /> Another trade
            </Button>
          </fieldset>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="siteday-work">Work done</Label>
            <Input id="siteday-work" placeholder="First-floor slab shuttering" value={work} onChange={(e) => setWork(e.target.value)} />
            <div className="flex gap-2">
              <Input aria-label="How much" type="number" inputMode="decimal" min={0} placeholder="How much (optional)" value={quantity} onChange={(e) => setQuantity(e.target.value)} />
              <Input aria-label="Unit" placeholder="sqm" className="w-28" value={unit} onChange={(e) => setUnit(e.target.value)} />
            </div>
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="siteday-issue">Anything stuck?</Label>
            <Input id="siteday-issue" placeholder="Cement ran out" value={issue} onChange={(e) => setIssue(e.target.value)} />
            {hasIssue && (
              <select aria-label="What kind of problem" className={FIELD} value={issueType} onChange={(e) => setIssueType(e.target.value)}>
                {ISSUE_TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            )}
          </div>
          {error && <p className="m-0 text-sm text-destructive" role="alert">{error}</p>}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={saving}>Cancel</Button>
          <Button onClick={save} disabled={!ready || saving} data-guide="site-day.save">{saving ? 'Saving…' : 'Save'}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
