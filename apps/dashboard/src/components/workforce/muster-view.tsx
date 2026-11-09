import * as React from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight, Download, Plus, Users } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { useToast } from '@/components/ui/toast-notification'
import { EmptyState } from '@/components/page/page-kit'
import { errorWords, useSiteOptions } from '@/lib/equipment'
import { createLabourTeam, fetchLabourTeams, fetchMuster, n } from '@/lib/labour-pay'
import { useUrlState } from '@/lib/url-state'
import { cn } from '@/lib/utils'

// LW-02: the muster roll, a site's month as the grid every site keeps: people down, days across, P / ½ / A or how
// many came, from attendance (never typed again). LW-01: labour teams (a contractor's team is a vendor of kind
// labour; its workers point at it from the register).

const MARK: Record<string, string> = { P: 'bg-success-soft text-success', '½': 'bg-draft-soft text-draft', A: 'text-muted-foreground/50' }

function monthShift(month: string, by: number): string {
  const [y, m] = month.split('-').map(Number)
  const d = new Date(y, m - 1 + by, 1)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

export function MusterView({ siteId: scopedSite, leading }: { siteId: string | null; leading?: React.ReactNode }) {
  const sites = useSiteOptions()
  const now = new Date()
  const [month, setMonth] = useUrlState<string>('month', `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`)
  const [picked, setPicked] = useUrlState<string>('at', '')
  const siteId = scopedSite || picked || sites.data?.[0]?.id || ''
  const muster = useQuery({ queryKey: ['labour', 'muster', siteId, month], queryFn: () => fetchMuster(siteId, month), enabled: !!siteId })
  const m = muster.data
  const days = m ? Array.from({ length: m.days }, (_, i) => `${month}-${String(i + 1).padStart(2, '0')}`) : []

  const exportCsv = () => {
    if (!m) return
    const head = ['Name', 'Trade', 'Team', ...days.map((d) => d.slice(8)), 'Man-days', 'OT hours']
    const lines = m.rows.map((r) => [r.name, r.trade ?? '', r.team ?? '', ...days.map((d) => r.days[d]?.mark ?? ''), String(n(r.man_days)), String(n(r.overtime_hours))])
    const csv = [head, ...lines].map((l) => l.map((x) => `"${String(x).replace(/"/g, '""')}"`).join(',')).join('\n')
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }))
    const a = document.createElement('a')
    a.href = url
    a.download = `muster-roll-${month}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        {leading}
        {!scopedSite && (
          <select aria-label="Site" value={siteId} onChange={(e) => setPicked(e.target.value)} className="h-9 rounded-lg border bg-background px-2 text-sm">
            {(sites.data ?? []).map((s) => <option key={s.id} value={s.id}>{s.projectName} › {s.name}</option>)}
          </select>
        )}
        <div className="flex items-center rounded-lg border">
          <Button variant="ghost" size="icon" className="size-9" aria-label="Previous month" onClick={() => setMonth(monthShift(month, -1))}><ChevronLeft className="size-4" /></Button>
          <span className="min-w-24 text-center text-sm font-medium">{new Date(`${month}-01T00:00:00`).toLocaleDateString('en-IN', { month: 'short', year: 'numeric' })}</span>
          <Button variant="ghost" size="icon" className="size-9" aria-label="Next month" onClick={() => setMonth(monthShift(month, 1))}><ChevronRight className="size-4" /></Button>
        </div>
        <Button variant="outline" size="sm" className="ml-auto h-9 gap-1.5" disabled={!m?.rows.length} onClick={exportCsv}><Download className="size-4" /> Excel (CSV)</Button>
      </div>
      {!siteId ? (
        <EmptyState icon={Users} title="No sites yet" about="The muster roll is a site's month. Add a site first." />
      ) : !m ? (
        <Skeleton className="h-64 w-full rounded-xl" />
      ) : m.rows.length === 0 ? (
        <EmptyState icon={Users} title="No attendance this month" about="Each day the site reports who came; this grid fills itself." whatsapp="Ravi, Anil present; 3 helpers from Suresh team" />
      ) : (
        <div className="overflow-x-auto rounded-xl border">
          <table className="w-full border-collapse text-xs">
            <thead className="bg-muted/50 text-muted-foreground">
              <tr>
                <th className="sticky left-0 z-10 min-w-40 bg-muted/90 px-3 py-2 text-left font-semibold">Name</th>
                {days.map((d) => {
                  const wd = new Date(`${d}T00:00:00`).getDay()
                  return <th key={d} className={cn('w-7 px-0.5 py-2 text-center font-medium tabular-nums', wd === 0 && 'bg-muted')}>{Number(d.slice(8))}</th>
                })}
                <th className="px-2 py-2 text-right font-semibold">Days</th>
                <th className="px-2 py-2 text-right font-semibold">OT h</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {m.rows.map((r) => (
                <tr key={r.key}>
                  <td className="sticky left-0 z-10 bg-background px-3 py-1.5">
                    {r.worker_id ? <Link to={`/labour?view=workers&q=${encodeURIComponent(r.name)}`} className="font-medium hover:underline">{r.name}</Link> : <span className="font-medium">{r.name}</span>}
                    <span className="block text-[11px] text-muted-foreground">{[r.trade, r.team].filter(Boolean).join(' · ')}</span>
                  </td>
                  {days.map((d) => {
                    const c = r.days[d]
                    return (
                      <td key={d} className="px-0.5 py-1 text-center" title={c && n(c.ot) ? `${n(c.ot)} h overtime` : undefined}>
                        {c ? <span className={cn('inline-flex min-w-5 justify-center rounded px-0.5 font-semibold tabular-nums', MARK[c.mark] ?? 'bg-info-soft text-info', n(c.ot) > 0 && 'ring-1 ring-primary')}>{c.mark}</span> : ''}
                      </td>
                    )
                  })}
                  <td className="px-2 text-right font-semibold tabular-nums">{n(r.man_days)}</td>
                  <td className="px-2 text-right tabular-nums">{n(r.overtime_hours) || ''}</td>
                </tr>
              ))}
            </tbody>
            <tfoot className="border-t bg-muted/40">
              <tr>
                <td className="sticky left-0 bg-muted/90 px-3 py-2 font-semibold">Total</td>
                <td colSpan={days.length} />
                <td className="px-2 text-right font-semibold tabular-nums">{n(m.man_days)}</td>
                <td />
              </tr>
            </tfoot>
          </table>
        </div>
      )}
      <p className="text-xs text-muted-foreground">P present · ½ half day · A absent · a number is how many came in a headcount group · ringed: overtime</p>
    </div>
  )
}

export function TeamsView({ leading }: { leading?: React.ReactNode }) {
  const toast = useToast()
  const qc = useQueryClient()
  const teams = useQuery({ queryKey: ['labour', 'teams'], queryFn: fetchLabourTeams })
  const [adding, setAdding] = React.useState(false)
  const [name, setName] = React.useState('')
  const [phone, setPhone] = React.useState('')
  const add = useMutation({
    mutationFn: () => createLabourTeam({ name: name.trim(), phone: phone.trim() || undefined }),
    onSuccess: (t) => { toast.success(`${t.name} added`, 'Put its workers in the team from the register.'); setAdding(false); setName(''); setPhone(''); qc.invalidateQueries({ queryKey: ['labour', 'teams'] }) },
    onError: (e) => toast.error('Could not add the team', errorWords(e)),
  })
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        {leading}
        <Button size="sm" className="ml-auto h-9 gap-1.5" onClick={() => setAdding(true)}><Plus className="size-4" /> Add team</Button>
      </div>
      {teams.isLoading ? <Skeleton className="h-40 w-full rounded-xl" /> : (teams.data?.items ?? []).length === 0 ? (
        <EmptyState icon={Users} title="No labour teams yet" about="A labour contractor's team (Suresh's masons). Its days come from attendance, its wages are paid through the contractor, and advances to it come back off its wages."
          action={<Button size="sm" onClick={() => setAdding(true)}>Add team</Button>} />
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {teams.data!.items.map((t) => (
            <Link key={t.id} to={`/finance/vendors/${t.id}?tab=account`} className="flex flex-col gap-1 rounded-xl border px-4 py-3 transition-colors hover:border-foreground/25">
              <span className="font-semibold">{t.name}</span>
              <span className="text-xs text-muted-foreground">{t.phone ?? 'No phone'}</span>
              <span className="mt-1 text-sm tabular-nums">{t.workers} on the register · {n(t.man_days_30)} man-days in 30 days</span>
            </Link>
          ))}
        </div>
      )}
      <Dialog open={adding} onOpenChange={setAdding}>
        <DialogContent>
          <DialogHeader><DialogTitle>Add a labour team</DialogTitle></DialogHeader>
          <div className="grid gap-3 text-sm">
            <div className="grid gap-1.5"><Label htmlFor="tn">Contractor or team name</Label><Input id="tn" placeholder="Suresh team" value={name} onChange={(e) => setName(e.target.value)} /></div>
            <div className="grid gap-1.5"><Label htmlFor="tp">Contractor's WhatsApp number</Label><Input id="tp" inputMode="tel" placeholder="98765 43210" value={phone} onChange={(e) => setPhone(e.target.value)} /></div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setAdding(false)}>Cancel</Button>
            <Button disabled={!name.trim() || add.isPending} onClick={() => add.mutate()}>Add team</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
