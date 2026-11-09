import * as React from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, ChevronLeft, ChevronRight, ClipboardPen, Copy, Download, MapPin, Save } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useToast } from '@/components/ui/toast-notification'
import { DayBar, Legend } from '@/components/equipment/parts'
import { useScope } from '@/lib/ScopeContext'
import { useAuth } from '@/lib/AuthContext'
import { usePageTitle } from '@/lib/page-title'
import { useUrlState } from '@/lib/url-state'
import { useReadOnly } from '@/lib/trial'
import { exportCsv } from '@/lib/export'
import { cn } from '@/lib/utils'
import { dayWords, errorWords, fetchLogs, hrs, iso, saveLogs, type LogLineInput } from '@/lib/equipment'
import { ModuleTitle } from '@/components/page/page-kit'

// NXT-11: Equipment > Daily log. One date, every machine at the sites in view on one screen, typed in place: the
// fewest taps for whoever fills it in the evening. Machines already logged (on WhatsApp or here) show their figures;
// the ones not logged yet are empty rows. "Copy yesterday" fills the empty rows from yesterday; one Save saves every
// row that changed.

type Row = {
  id: string
  name: string
  type: string | null
  kind: 'machine' | 'vehicle' | null
  siteId: string
  siteName: string
  projectName: string
  logged: boolean
  worked: string; idle: string; breakdown: string; reason: string; fuel: string; cost: string; operator: string; trips: string
}
type Field = 'worked' | 'idle' | 'breakdown' | 'reason' | 'fuel' | 'cost' | 'operator' | 'trips'

const num = (v: string) => v.replace(/[^0-9.]/g, '')
const add = (date: string, days: number) => iso(new Date(new Date(`${date}T00:00:00`).getTime() + days * 86_400_000))

export default function EquipmentLogPage() {
  usePageTitle('Machine daily log')
  const { scope } = useScope()
  const { me } = useAuth()
  const seesMoney = ['ADMIN', 'OWNER', 'SUPER_ADMIN', 'FINANCE', 'PROJECT_MANAGER'].includes((me?.role || '').toUpperCase())
  const readOnly = useReadOnly()
  const toast = useToast()
  const qc = useQueryClient()
  const today = iso(new Date())
  const [date, setDate] = useUrlState<string>('date', today)
  const projectId = scope.mode === 'project' || scope.mode === 'site' ? scope.projectId : null
  const siteId = scope.mode === 'site' ? scope.siteId : null

  const day = useQuery({ queryKey: ['equipment', 'logs', date, projectId, siteId], queryFn: () => fetchLogs({ date, project_id: projectId, site_id: siteId }) })
  const yesterday = useQuery({ queryKey: ['equipment', 'logs', add(date, -1), projectId, siteId], queryFn: () => fetchLogs({ date: add(date, -1), project_id: projectId, site_id: siteId }) })

  const base = React.useMemo<Row[]>(() => {
    const d = day.data
    if (!d) return []
    const logged: Row[] = d.items.map((l) => ({
      id: l.equipment_id, name: l.machine ?? '', type: l.type, kind: l.kind, siteId: l.site_id ?? '', siteName: l.site_name ?? '', projectName: l.project_name ?? '', logged: true,
      worked: l.worked_hours ?? '', idle: l.idle_hours ?? '', breakdown: l.breakdown_hours ?? '', reason: l.breakdown_reason ?? '', fuel: l.fuel_litres ?? '',
      cost: l.fuel_cost ? String(Number(l.fuel_cost)) : '', operator: l.operator_name ?? '', trips: l.trips ? String(l.trips) : '',
    }))
    const missing: Row[] = d.missing.map((m) => ({
      id: m.id, name: m.name, type: m.type, kind: m.kind, siteId: m.site_id, siteName: m.site_name ?? '', projectName: m.project_name ?? '', logged: false,
      worked: '', idle: '', breakdown: '', reason: '', fuel: '', cost: '', operator: m.operator_name ?? '', trips: '',
    }))
    return [...logged, ...missing].sort((a, b) => a.projectName.localeCompare(b.projectName) || a.siteName.localeCompare(b.siteName) || a.name.localeCompare(b.name))
  }, [day.data])

  const [edits, setEdits] = React.useState<Record<string, Partial<Row>>>({})
  React.useEffect(() => setEdits({}), [date, projectId, siteId])
  const rows = base.map((r) => ({ ...r, ...edits[r.id] }))
  const changed = rows.filter((r) => edits[r.id] && (['worked', 'idle', 'breakdown', 'reason', 'fuel', 'cost', 'operator', 'trips'] as Field[]).some((f) => (edits[r.id]![f] ?? r[f]) !== (base.find((b) => b.id === r.id)![f])))
  const set = (id: string, patch: Partial<Row>) => setEdits((e) => ({ ...e, [id]: { ...e[id], ...patch } }))
  const tooLong = (r: Row) => Number(r.worked || 0) + Number(r.idle || 0) + Number(r.breakdown || 0) > 24

  const copyYesterday = () => {
    const prev = new Map((yesterday.data?.items ?? []).map((l) => [l.equipment_id, l]))
    let n = 0
    for (const r of rows) {
      const y = prev.get(r.id)
      if (r.logged || !y || r.worked || r.idle || r.breakdown) continue
      set(r.id, { worked: y.worked_hours ?? '', idle: y.idle_hours ?? '', breakdown: '', fuel: '', operator: y.operator_name ?? r.operator })
      n++
    }
    if (n) toast.success(`${n} filled from ${dayWords(add(date, -1), today).toLowerCase()}`, 'Check the hours, add diesel, then Save.')
    else toast.error('Nothing to copy', 'No machine still empty here was logged the day before.')
  }

  const save = useMutation({
    mutationFn: () => {
      const lines: LogLineInput[] = changed.filter((r) => r.worked || r.idle || r.breakdown || r.fuel).map((r) => ({
        equipment_id: r.id, site_id: r.siteId, worked_hours: r.worked || null, idle_hours: r.idle || null, breakdown_hours: r.breakdown || null,
        breakdown_reason: Number(r.breakdown) > 0 ? r.reason.trim() || null : null, fuel_litres: r.fuel || null,
        ...(seesMoney ? { fuel_cost: r.cost || null } : {}), operator_name: r.operator.trim() || null,
        ...(r.kind === 'vehicle' ? { trips: r.trips ? Number(r.trips) : null } : {}),
      }))
      return saveLogs({ occurred_date: date, lines })
    },
    onSuccess: (r) => {
      setEdits({})
      qc.invalidateQueries({ queryKey: ['equipment'] })
      qc.invalidateQueries({ queryKey: ['finance', 'costs'] })
      toast.success(`${r.items.length} machine${r.items.length === 1 ? '' : 's'} saved for ${dayWords(date, today).toLowerCase()}`,
        r.issues.length ? `${r.issues.map((i) => i.machine).join(', ')}: breakdown on Issues.` : undefined)
    },
    onError: (e) => toast.error('Not saved', errorWords(e)),
  })

  const t = rows.reduce((n, r) => ({ worked: n.worked + Number(r.worked || 0), idle: n.idle + Number(r.idle || 0), breakdown: n.breakdown + Number(r.breakdown || 0), fuel: n.fuel + Number(r.fuel || 0) }), { worked: 0, idle: 0, breakdown: 0, fuel: 0 })
  const sites = [...new Map(rows.map((r) => [r.siteId, r])).values()]
  const empty = rows.filter((r) => !r.logged && !r.worked && !r.idle && !r.breakdown && !r.fuel).length
  const canSave = changed.length > 0 && !changed.some(tooLong) && !readOnly
  const exportDay = () => exportCsv(`machine-log-${date}.csv`, ['Date', 'Project', 'Site', 'Machine', 'Worked (h)', 'Idle (h)', 'Breakdown (h)', 'Reason', 'Diesel (L)', 'Operator'],
    rows.filter((r) => r.logged).map((r) => [date, r.projectName, r.siteName, r.name, r.worked, r.idle, r.breakdown, r.reason, r.fuel, r.operator]))

  return (
    <div className="mx-auto flex w-full flex-col gap-4 pb-28 sm:px-2 md:pb-8">
      <Link to="/equipment" className="inline-flex w-fit items-center gap-1 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="size-4" />Machines</Link>
      <header className="flex flex-wrap items-center justify-between gap-3">
        <ModuleTitle icon={ClipboardPen} title="Daily log" />
        <div className="flex items-center gap-1.5">
          <Button variant="outline" size="icon" aria-label="Day before" onClick={() => setDate(add(date, -1))}><ChevronLeft className="size-4" /></Button>
          <label className="flex h-9 items-center gap-2 rounded-lg border bg-background px-3 text-sm font-semibold">
            {dayWords(date, today)}
            <input type="date" value={date} max={today} onChange={(e) => e.target.value && setDate(e.target.value)} className="w-[8.5rem] bg-transparent text-sm font-normal outline-none" aria-label="Date" />
          </label>
          <Button variant="outline" size="icon" aria-label="Day after" disabled={date >= today} onClick={() => setDate(add(date, 1))}><ChevronRight className="size-4" /></Button>
        </div>
      </header>

      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border bg-card px-4 py-3">
        <div className="flex flex-wrap gap-x-6 gap-y-1 text-sm tabular-nums">
          <span><strong className="text-lg">{hrs(String(t.worked))}</strong> <span className="text-muted-foreground">worked</span></span>
          <span className="text-amber-700 dark:text-amber-300"><strong className="text-lg">{hrs(String(t.idle))}</strong> idle</span>
          <span className="text-red-700 dark:text-red-300"><strong className="text-lg">{hrs(String(t.breakdown))}</strong> breakdown</span>
          <span><strong className="text-lg">{t.fuel} L</strong> <span className="text-muted-foreground">diesel</span></span>
          <span className="text-muted-foreground">{rows.length - empty} of {rows.length} machines logged</span>
        </div>
        <div className="flex gap-2">
          {!readOnly && empty > 0 && <Button variant="outline" size="sm" className="gap-1.5" onClick={copyYesterday} disabled={!yesterday.data?.items.length}><Copy className="size-4" />Copy yesterday</Button>}
          <Button variant="outline" size="sm" className="gap-1.5" disabled={!rows.some((r) => r.logged)} onClick={exportDay}><Download className="size-4" />Export</Button>
        </div>
      </div>

      {day.isLoading && <div className="h-40 animate-pulse rounded-xl bg-muted/40" />}
      {day.isError && <p className="text-sm text-destructive">The log did not load. Refresh to try again.</p>}
      {day.data && rows.length === 0 && (
        <div className="flex flex-col items-center gap-2 rounded-xl border px-4 py-12 text-center text-sm text-muted-foreground">
          <ClipboardPen className="size-8 opacity-40" />
          No machine is on a site here. Add machines on the <Link to="/equipment" className="font-medium text-primary underline">Machines</Link> page, at their site.
        </div>
      )}

      {sites.map((s) => (
        <section key={s.siteId} aria-label={s.siteName} className="overflow-hidden rounded-xl border">
          <h2 className="flex items-center gap-2 border-b bg-muted/30 px-4 py-2 text-sm font-semibold"><MapPin className="size-4 text-muted-foreground" />{s.projectName} › {s.siteName}</h2>
          <div className="hidden grid-cols-[minmax(140px,1.4fr)_repeat(3,72px)_minmax(120px,1fr)_72px_minmax(100px,0.8fr)] gap-2 border-b px-4 py-1.5 text-[11px] font-medium text-muted-foreground uppercase md:grid">
            <span>Machine</span><span className="text-right">Worked</span><span className="text-right">Idle</span><span className="text-right">Broken</span><span>What broke</span><span className="text-right">Diesel L</span><span>Operator</span>
          </div>
          {rows.filter((r) => r.siteId === s.siteId).map((r) => {
            const dirty = !!edits[r.id]
            return (
              <div key={r.id} className={cn('grid grid-cols-3 gap-2 border-b px-4 py-2.5 last:border-b-0 md:grid-cols-[minmax(140px,1.4fr)_repeat(3,72px)_minmax(120px,1fr)_72px_minmax(100px,0.8fr)] md:items-center', dirty && 'bg-amber-50/60 dark:bg-amber-950/20', tooLong(r) && 'bg-red-50 dark:bg-red-950/30')}>
                <div className="col-span-3 flex min-w-0 items-center justify-between gap-2 md:col-span-1">
                  <span className="flex min-w-0 flex-col">
                    <Link to={`/equipment/${r.id}`} className="truncate font-semibold hover:underline">{r.name}</Link>
                    <span className="truncate text-xs text-muted-foreground">{r.type ?? ''}{!r.logged && !dirty ? ' · not logged' : ''}</span>
                  </span>
                  {!readOnly && !r.worked && !r.idle && !r.breakdown && <button type="button" className="shrink-0 rounded-full border px-2 py-0.5 text-xs hover:bg-muted" onClick={() => set(r.id, { worked: '8' })}>Full day</button>}
                </div>
                {(['worked', 'idle', 'breakdown'] as const).map((f) => (
                  <label key={f} className="flex flex-col gap-0.5">
                    <span className="text-[10px] text-muted-foreground uppercase md:sr-only">{f === 'breakdown' ? 'Broken' : f}</span>
                    <input inputMode="decimal" value={r[f]} disabled={readOnly} onChange={(e) => set(r.id, { [f]: num(e.target.value) })} placeholder="0" aria-label={`${r.name} ${f} hours`}
                      className={cn('h-9 w-full rounded-md border bg-background px-2 text-right font-semibold tabular-nums outline-none focus:ring-2 focus:ring-ring', f === 'breakdown' && Number(r.breakdown) > 0 && 'border-red-300 text-red-700 dark:text-red-300')} />
                  </label>
                ))}
                <input value={r.reason} disabled={readOnly || !(Number(r.breakdown) > 0)} onChange={(e) => set(r.id, { reason: e.target.value })} placeholder={Number(r.breakdown) > 0 ? 'What broke' : '—'} aria-label={`${r.name} what broke`}
                  className="col-span-3 h-9 rounded-md border bg-background px-2 text-sm outline-none focus:ring-2 focus:ring-ring disabled:opacity-50 md:col-span-1" />
                <label className="flex flex-col gap-0.5">
                  <span className="text-[10px] text-muted-foreground uppercase md:sr-only">Diesel L</span>
                  <input inputMode="decimal" value={r.fuel} disabled={readOnly} onChange={(e) => set(r.id, { fuel: num(e.target.value) })} placeholder="0" aria-label={`${r.name} diesel litres`}
                    className="h-9 w-full rounded-md border bg-background px-2 text-right tabular-nums outline-none focus:ring-2 focus:ring-ring" />
                </label>
                <input value={r.operator} disabled={readOnly} onChange={(e) => set(r.id, { operator: e.target.value })} placeholder="Operator" aria-label={`${r.name} operator`}
                  className="col-span-2 h-9 rounded-md border bg-background px-2 text-sm outline-none focus:ring-2 focus:ring-ring md:col-span-1" />
                <DayBar worked={r.worked} idle={r.idle} breakdown={r.breakdown} className="col-span-3 md:hidden" />
              </div>
            )
          })}
        </section>
      ))}
      {rows.length > 0 && <Legend className="px-1" />}

      {!readOnly && (
        <div className={cn('fixed inset-x-0 bottom-0 z-30 border-t bg-background/95 px-4 py-3 backdrop-blur transition md:static md:border-0 md:bg-transparent md:p-0', !changed.length && 'translate-y-full md:translate-y-0')}>
          <div className="flex items-center justify-end gap-3">
            {changed.length > 0 && <span className="text-sm text-muted-foreground">{changed.length} changed</span>}
            {changed.length > 0 && <Button variant="ghost" onClick={() => setEdits({})}>Undo changes</Button>}
            <Button className="gap-2 font-semibold" disabled={!canSave || save.isPending} onClick={() => save.mutate()}><Save className="size-4" />{save.isPending ? 'Saving…' : 'Save'}</Button>
          </div>
        </div>
      )}
    </div>
  )
}
