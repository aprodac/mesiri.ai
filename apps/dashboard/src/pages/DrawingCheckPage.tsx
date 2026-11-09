import * as React from 'react'
import { useMutation } from '@tanstack/react-query'
import { AlertTriangle, Building2, FileSearch, Info, Layers, Ruler, Upload } from 'lucide-react'
import { Callout, StatStrip, type Stat } from '@/components/dpr-page'
import { useToast } from '@/components/ui/toast-notification'
import { useAuth } from '@/lib/AuthContext'
import { maySeeBoq } from '@/lib/boq'
import { readDrawing, type DrawingCheck, type DrawingReadWithDrafts as DrawingRead, type DrawingSheet, type StructureTakeoff } from '@/lib/drawings'
import { DraftBoq, DraftSchedule } from '@/components/drawings/drafts'
import { apiErrorMessage } from '@/lib/logo-upload'
import { usePageTitle } from '@/lib/page-title'
import { cn } from '@/lib/utils'
import { ModuleTitle } from '@/components/page/page-kit'

// DR-04: Planning › Drawing check. Drop the architect's PDF: Mesiri reads its own text (title blocks, levels, room
// sizes, fixtures) in a second and lists what to ask the architect before the drawing reaches site, such as an area
// label that does not match the room's size. Nothing is saved and nothing is sent to anyone. DR-05/06: a draft
// schedule from the floors and draft BOQ quantities from the rooms, edited here and added to a project on request.

/** What the production server accepts today (nginx); the reader itself takes up to 50 MB. */
const MAX_MB = 8

const SEVERITY: Record<DrawingCheck['severity'], { label: string; tone: string; icon: typeof AlertTriangle }> = {
  high: { label: 'Check', tone: 'border-destructive/30 bg-destructive/5 text-destructive', icon: AlertTriangle },
  medium: { label: 'Ask', tone: 'border-draft/30 bg-draft-soft text-draft', icon: AlertTriangle },
  low: { label: 'Note', tone: 'border-border bg-muted/50 text-foreground', icon: Info },
  info: { label: 'Info', tone: 'border-border bg-muted/30 text-muted-foreground', icon: Info },
}

const KIND: Record<string, string> = {
  plan: 'Plan', elevation: 'Elevation', section: 'Section', schedule: 'Schedule', detail: 'Detail', site_plan: 'Site plan',
}

const FIXTURE_NAMES: Record<string, string> = { toilet: 'Toilets', urinal: 'Urinals', wash: 'Wash basins', lift: 'Lifts', stair: 'Stairs' }

function num(n: number, d = 0): string {
  return n.toLocaleString('en-IN', { maximumFractionDigits: d })
}

function level(v: number): string {
  return v === 0 ? '±0' : `${v > 0 ? '+' : '−'}${num(Math.abs(v), 1)}`
}

export default function DrawingCheckPage() {
  usePageTitle('Drawing check')
  const { me } = useAuth()
  const toast = useToast()
  const input = React.useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = React.useState(false)
  const read = useMutation({
    mutationFn: readDrawing,
    onError: (e) => toast.error('Could not read the drawing', apiErrorMessage(e)),
  })
  const pick = (file: File | undefined) => {
    if (!file) return
    if (file.type && file.type !== 'application/pdf' && !file.name.toLowerCase().endsWith('.pdf')) {
      toast.error('Not a PDF', 'Send the drawing as a PDF exported from CAD.')
      return
    }
    if (file.size > MAX_MB * 1024 * 1024) {
      toast.error('Too big for now', `Up to ${MAX_MB} MB. Split the set, or export it at a lower resolution.`)
      return
    }
    read.mutate(file)
  }

  if (!maySeeBoq(me?.role)) {
    return <p className="mx-auto max-w-3xl p-4 text-sm text-muted-foreground">The drawing check is for the people who plan projects: owner, admins, finance and project managers.</p>
  }
  const r = read.data

  return (
    <div className="mx-auto flex w-full min-w-0 flex-col gap-4 pb-8 sm:px-2">
      <header className="flex items-center gap-3">
        <ModuleTitle icon={FileSearch} title="Drawing check" />
      </header>

      <button
        type="button"
        onClick={() => input.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => { e.preventDefault(); setDragging(false); pick(e.dataTransfer.files?.[0]) }}
        className={cn('flex flex-col items-center gap-2 rounded-xl border-2 border-dashed p-6 text-sm transition', dragging ? 'border-primary bg-primary/5' : 'hover:bg-muted/40')}
      >
        <Upload className="size-6 text-muted-foreground" />
        <span className="font-medium">{read.isPending ? 'Reading…' : r ? 'Check another drawing set' : 'Drop the drawing PDF here, or tap to choose'}</span>
        <span className="text-xs text-muted-foreground">PDF from CAD (not a scan), up to {MAX_MB} MB</span>
      </button>
      <input ref={input} type="file" accept="application/pdf,.pdf" className="hidden" onChange={(e) => { pick(e.target.files?.[0]); e.target.value = '' }} />

      {r && <Result r={r} />}
    </div>
  )
}

function Result({ r }: { r: DrawingRead }) {
  const plans = r.sheets.filter((s) => s.kind === 'plan')
  const asks = r.checks.filter((c) => c.severity === 'high' || c.severity === 'medium')
  const stats: Stat[] = [
    { label: 'Sheets', value: r.pages, icon: Layers },
    { label: 'Floors', value: r.floors.length || '—', icon: Building2 },
    { label: 'Levels', value: r.levels.length || '—', icon: Ruler },
    { label: 'To ask the architect', value: asks.length, tone: asks.length ? 'bad' : 'good', icon: AlertTriangle },
  ]
  return (
    <>
      <div>
        <p className="font-semibold">{r.project ?? r.file_name ?? 'Drawing set'}</p>
        <p className="text-sm text-muted-foreground">{[r.client && `Client ${r.client}`, r.architect, r.units && `dimensions in ${r.units}`].filter(Boolean).join(' · ')}</p>
      </div>
      <StatStrip stats={stats} />

      <section className="flex flex-col gap-2">
        <h2 className="text-base font-semibold">What to check</h2>
        {r.checks.length === 0 ? (
          <Callout tone="success" icon={Info}>Nothing found to ask about. Levels, sizes and areas agree.</Callout>
        ) : (
          <ul className="flex flex-col gap-2">
            {r.checks.map((c, i) => {
              const s = SEVERITY[c.severity]
              const Icon = s.icon
              return (
                <li key={i} className={cn('flex gap-3 rounded-lg border p-3 text-sm', s.tone)}>
                  <Icon className="mt-0.5 size-4 shrink-0" />
                  <div className="min-w-0">
                    <p className="font-medium text-foreground">{c.message}</p>
                    <p className="text-xs text-muted-foreground">{c.page ? `Page ${c.page}${c.sheet ? `, ${c.sheet}` : ''}. ` : ''}{c.why}</p>
                  </div>
                </li>
              )
            })}
          </ul>
        )}
      </section>

      <section className="flex flex-col gap-2">
        <h2 className="text-base font-semibold">Sheets</h2>
        <div className="overflow-x-auto rounded-lg border [contain:inline-size]">
          <table className="w-full min-w-[640px] text-sm">
            <thead className="bg-muted/50 text-xs text-muted-foreground">
              <tr>
                <th className="px-3 py-2 text-left font-medium">Page</th>
                <th className="px-3 py-2 text-left font-medium">Title</th>
                <th className="px-3 py-2 text-left font-medium">Kind</th>
                <th className="px-3 py-2 text-left font-medium">Scale</th>
                <th className="px-3 py-2 text-left font-medium">Date</th>
                <th className="px-3 py-2 text-left font-medium">Drawn / checked</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {r.sheets.map((s) => (
                <tr key={s.page} className={cn(!s.has_text && 'text-muted-foreground')}>
                  <td className="px-3 py-2 tabular-nums">{s.page}</td>
                  <td className="px-3 py-2 font-medium">{s.has_text ? s.title ?? '—' : 'Scanned page: not read'}</td>
                  <td className="px-3 py-2">{s.kind ? KIND[s.kind] : '—'}</td>
                  <td className="px-3 py-2">{s.scale ?? '—'}</td>
                  <td className="px-3 py-2">{s.date ?? '—'}</td>
                  <td className="px-3 py-2 text-muted-foreground">{[s.drawn_by, s.checked_by].filter(Boolean).join(' / ') || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <div className="grid gap-4 lg:grid-cols-[1fr_18rem]">
        <section className="flex flex-col gap-2">
          <h2 className="text-base font-semibold">Rooms by floor</h2>
          {plans.length === 0 && <p className="text-sm text-muted-foreground">No floor plans in this set.</p>}
          {plans.length > 0 && !plans.some((s) => s.rooms.length) && (
            <p className="text-sm text-muted-foreground">No room sizes on these plans{r.structure ? ' (a structural set: its footings and columns are below)' : ''}.</p>
          )}
          {plans.filter((s) => s.rooms.length || !r.structure).map((s) => <PlanRooms key={s.page} sheet={s} units={r.units} />)}
        </section>
        <aside className="flex flex-col gap-4">
          <section className="rounded-lg border p-3">
            <h2 className="mb-2 text-sm font-semibold">Levels ({r.units ?? 'cm'})</h2>
            {r.levels.length === 0 ? <p className="text-sm text-muted-foreground">No level marks found.</p> : (
              <ul className="text-sm tabular-nums">
                {r.levels.map((l) => (
                  <li key={l.value} className="flex justify-between gap-2 py-0.5"><span className="font-medium">{level(l.value)}</span><span className="text-xs text-muted-foreground">page {l.pages.join(', ')}</span></li>
                ))}
              </ul>
            )}
          </section>
          <section className="rounded-lg border p-3">
            <h2 className="mb-2 text-sm font-semibold">Fixtures on the plans</h2>
            <ul className="text-sm">
              {Object.entries(r.fixtures).filter(([, n]) => n > 0).map(([k, n]) => (
                <li key={k} className="flex justify-between py-0.5"><span>{FIXTURE_NAMES[k] ?? k}</span><span className="font-medium tabular-nums">{n}</span></li>
              ))}
            </ul>
            <p className="mt-2 text-xs text-muted-foreground">Counted from the labels on each plan; check against the BOQ.</p>
          </section>
        </aside>
      </div>
      {r.structure && <Structure st={r.structure} />}
      <DraftSchedule read={r} />
      <DraftBoq read={r} />
    </>
  )
}

/** DR-09: what a structural set's schedules add up to. Net quantities read from the drawing, never a design check. */
function Structure({ st }: { st: StructureTakeoff }) {
  const f = st.foundation
  const t = (kg: number) => (kg >= 1000 ? `${num(kg / 1000, 2)} t` : `${num(kg)} kg`)
  const n = st.notes
  const design = [n.concrete, n.steel, n.sbc_t_per_sqm && `SBC ${n.sbc_t_per_sqm} t/m²`, n.designed_for && `designed for ${n.designed_for}`].filter(Boolean)
  const stats: Stat[] = [
    { label: 'Footings', value: f.footings },
    { label: `Concrete ${f.concrete_grade}`, value: `${num(f.concrete_cum, 1)} m³` },
    { label: `PCC ${f.pcc_mix}`, value: `${num(f.pcc_cum, 1)} m³` },
    { label: 'Steel', value: t(f.steel_kg) },
    { label: 'Cement', value: `${num(f.cement_bags)} bags` },
  ]
  return (
    <section className="flex flex-col gap-3">
      <div>
        <h2 className="text-base font-semibold">Foundation from the structural drawings</h2>
        <p className="text-sm text-muted-foreground">
          Counted from the footing plan{st.plan_page ? ` (page ${st.plan_page})` : ''} and the footing and column schedules
          {design.length ? ` · ${design.join(' · ')}` : ''}.
        </p>
      </div>
      <StatStrip stats={stats} />
      <p className="text-sm">Steel by bar: {Object.entries(f.steel_by_dia).map(([d, kg]) => `${d} ${t(kg)}`).join(' · ')}</p>
      <div className="overflow-x-auto rounded-lg border [contain:inline-size]">
        <table className="w-full min-w-[680px] text-sm">
          <thead className="bg-muted/50 text-xs text-muted-foreground">
            <tr>
              <th className="px-3 py-2 text-left font-medium">Footing</th>
              <th className="px-3 py-2 text-right font-medium">Nos</th>
              <th className="px-3 py-2 text-left font-medium">Size (cm)</th>
              <th className="px-3 py-2 text-left font-medium">Columns</th>
              <th className="px-3 py-2 text-left font-medium">Bars (each)</th>
              <th className="px-3 py-2 text-right font-medium">Concrete m³</th>
              <th className="px-3 py-2 text-right font-medium">Steel kg</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {st.footings.map((x) => (
              <tr key={x.mark} className="align-top">
                <td className="px-3 py-2 font-medium">{x.mark}{x.combined && <span className="ml-1 text-xs text-muted-foreground">combined</span>}</td>
                <td className="px-3 py-2 text-right tabular-nums">{x.count}</td>
                <td className="px-3 py-2">{x.size ? `${x.size}, ${x.depth_cm} deep` : '—'}</td>
                <td className="px-3 py-2">{x.columns.join(', ')}</td>
                <td className="px-3 py-2 text-xs text-muted-foreground">{x.bars ?? x.basis}</td>
                <td className="px-3 py-2 text-right tabular-nums">{x.concrete_cum != null ? num(x.concrete_cum, 2) : '—'}</td>
                <td className="px-3 py-2 text-right tabular-nums">{x.steel_kg != null ? num(x.steel_kg) : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {st.columns.length > 0 && (
        <div className="overflow-x-auto rounded-lg border [contain:inline-size]">
          <table className="w-full min-w-[560px] text-sm">
            <thead className="bg-muted/50 text-xs text-muted-foreground">
              <tr>
                <th className="px-3 py-2 text-left font-medium">Column</th>
                <th className="px-3 py-2 text-right font-medium">On plan</th>
                <th className="px-3 py-2 text-left font-medium">Size (cm)</th>
                <th className="px-3 py-2 text-left font-medium">Bars</th>
                <th className="px-3 py-2 text-left font-medium">Ties</th>
                <th className="px-3 py-2 text-right font-medium">kg per m</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {st.columns.map((c) => (
                <tr key={c.mark}>
                  <td className="px-3 py-2 font-medium">{c.mark}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{c.count_on_plan}</td>
                  <td className="px-3 py-2">{c.size ?? '—'}</td>
                  <td className="px-3 py-2">{c.bars ?? '—'}</td>
                  <td className="px-3 py-2">{c.ties ?? '—'}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{num(c.kg_per_m, 1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="border-t px-3 py-2 text-xs text-muted-foreground">All columns on the plan: {num(st.columns_kg_per_m)} kg of steel per metre of height. A 3.2 m floor: about {t(st.columns_kg_per_m * 3.2)}.</p>
        </div>
      )}
      {st.slabs.length > 0 && (
        <p className="text-sm">
          <span className="font-medium">Slabs:</span>{' '}
          {st.slabs.map((x) => `${x.floor ?? `page ${x.page}`} ${x.mark} ${x.thickness_cm} cm, ${num(x.steel_kg_per_sqm, 1)} kg/m²`).join(' · ')}
        </p>
      )}
      <details className="text-xs text-muted-foreground">
        <summary className="cursor-pointer">How these are worked out</summary>
        <ul className="mt-1 list-disc pl-5">{st.assumptions.map((a) => <li key={a}>{a}</li>)}</ul>
        <p className="mt-1">Net quantities read from the drawing, not a design check. Add your usual wastage.</p>
      </details>
    </section>
  )
}

function PlanRooms({ sheet, units }: { sheet: DrawingSheet; units: string | null }) {
  return (
    <div className="rounded-lg border">
      <p className="border-b bg-muted/40 px-3 py-2 text-sm font-medium">{sheet.level ?? sheet.title} <span className="text-xs font-normal text-muted-foreground">page {sheet.page}</span></p>
      {sheet.rooms.length === 0 ? <p className="px-3 py-2 text-sm text-muted-foreground">No room sizes printed.</p> : (
        <ul className="divide-y text-sm">
          {sheet.rooms.map((room, i) => {
            const stated = room.area
            const actual = stated ? (stated.unit === 'sqft' ? room.computed.sqft : room.computed.sqm) : null
            const off = stated && actual ? Math.abs(stated.value - actual) / actual > 0.03 : false
            return (
              <li key={i} className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 px-3 py-1.5">
                <span className="font-medium">{room.label}</span>
                <span className="text-muted-foreground tabular-nums">
                  {room.size_text} {units ?? 'cm'} · {num(room.computed.sqm, 1)} m² · {num(room.computed.sqft)} sq ft
                  {stated && <span className={cn('ml-2', off ? 'font-semibold text-destructive' : 'text-success')}>labelled {stated.text}</span>}
                </span>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
