import * as React from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Camera, CheckCircle2, ChevronLeft, ChevronRight, Circle, CircleDot, FileUp, Image as ImageIcon, MapPinned, MessageCircle, Moon, Sun, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { useToast } from '@/components/ui/toast-notification'
import { PageError } from '@/components/dpr-page'
import { ProjectPickList, usePlanningProject } from '@/components/schedule/project-picker'
import { PlanCanvas } from '@/components/live-maps/plan-canvas'
import { fetchLiveMaps, STATE_WORD, stateFor, timeAgo, trackOnSite, type LiveMap, type LiveMaps, type LiveMarker, type LiveState } from '@/lib/live-maps'
import { apiErrorMessage } from '@/lib/logo-upload'
import { usePageTitle } from '@/lib/page-title'
import { fetchPlaceWork } from '@/lib/places'
import { cn } from '@/lib/utils'

// DR-10 / DR-11: Planning › Live plans. The project's drawings as live maps of the building: every footing and room
// coloured by the work site sent on WhatsApp, per trade, with the photos; the floor's progress, a room's passport,
// and the newest updates. Nothing typed here: "first floor pantry plastering done" on WhatsApp turns Pantry green.

const DOT: Record<LiveState, string> = { done: 'bg-emerald-400', in_progress: 'bg-amber-300', not_started: 'bg-slate-400/60' }

function day(iso: string | null): string {
  return iso ? new Date(`${iso.slice(0, 10)}T00:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' }) : ''
}

function Ring({ value, size = 40, stroke = 5, className, children }: { value: number; size?: number; stroke?: number; className?: string; children?: React.ReactNode }) {
  const r = (size - stroke) / 2, c = 2 * Math.PI * r
  return (
    <div className={cn('relative grid shrink-0 place-items-center', className)} style={{ width: size, height: size }}>
      <svg width={size} height={size} className="absolute inset-0 -rotate-90" aria-hidden>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="currentColor" strokeOpacity=".15" strokeWidth={stroke} />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="currentColor" strokeWidth={stroke} strokeLinecap="round"
          strokeDasharray={`${c * value} ${c}`} className="transition-all duration-700" />
      </svg>
      {children}
    </div>
  )
}

export default function LivePlansPage() {
  usePageTitle('Live plans')
  const projectId = usePlanningProject()
  if (!projectId) {
    return (
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-4 pb-8 sm:px-2">
        <Heading />
        <p className="text-sm text-muted-foreground">Pick a project to see its drawings come alive with site's updates.</p>
        <ProjectPickList to={(id) => `/planning/live?project=${id}`} empty="No projects yet. Add one in Projects & Sites." />
      </div>
    )
  }
  return <Live key={projectId} projectId={projectId} />
}

function Heading({ right }: { right?: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <header className="flex min-w-0 items-center gap-3">
        <span className="inline-flex size-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-sky-500 to-indigo-600 text-white shadow-lg shadow-sky-500/30">
          <MapPinned className="size-5" />
        </span>
        <div className="min-w-0">
          <div className="text-xs text-muted-foreground">Planning</div>
          <h1 className="text-2xl leading-tight font-semibold tracking-tight">Live plans</h1>
        </div>
      </header>
      {right}
    </div>
  )
}

function Live({ projectId }: { projectId: string }) {
  const query = useQuery<LiveMaps>({ queryKey: ['live-maps', projectId], queryFn: () => fetchLiveMaps(projectId), staleTime: 0, refetchInterval: 15_000 })
  const [mapId, setMapId] = React.useState<string | null>(null)
  const [trade, setTrade] = React.useState<string | null>(null)
  const [selected, setSelected] = React.useState<string | null>(null)
  const [blueprint, setBlueprint] = React.useState(true)
  const [photos, setPhotos] = React.useState(false)
  const [lightbox, setLightbox] = React.useState<{ urls: string[]; i: number } | null>(null)

  if (query.isError) return <PageError message="The live plans did not load." onRetry={() => query.refetch()} back={{ to: '/planning/live', label: 'All projects' }} />
  const data = query.data
  const map = data?.maps.find((m) => m.id === mapId) ?? data?.maps[0]
  const marker = map?.markers.find((m) => m.key === selected) ?? null

  const toggles = (
    <div className="flex items-center gap-2">
      <span className="hidden items-center gap-1.5 rounded-full bg-emerald-500/10 px-3 py-1 text-xs font-medium text-emerald-700 sm:inline-flex dark:text-emerald-300">
        <span className="relative flex size-2"><span className="absolute inline-flex size-full animate-ping rounded-full bg-emerald-400 opacity-75" /><span className="relative inline-flex size-2 rounded-full bg-emerald-500" /></span>
        Live
      </span>
      <Button variant="outline" size="sm" className="gap-1.5" onClick={() => setPhotos((p) => !p)} aria-pressed={photos}>
        <ImageIcon className="size-3.5" /> {photos ? 'Hide photos' : 'Photos'}
      </Button>
      <Button variant="outline" size="sm" className="gap-1.5" onClick={() => setBlueprint((b) => !b)}>
        {blueprint ? <Sun className="size-3.5" /> : <Moon className="size-3.5" />} {blueprint ? 'Paper' : 'Blueprint'}
      </Button>
    </div>
  )

  if (!data) return <div className="mx-auto flex w-full max-w-7xl flex-col gap-4 pb-8 sm:px-2"><Heading /><Skeleton className="h-[70vh] w-full rounded-2xl" /></div>
  if (!map) return <div className="mx-auto flex w-full max-w-7xl flex-col gap-4 pb-8 sm:px-2"><Heading /><Empty projectId={projectId} /></div>

  return (
    <div className="mx-auto flex w-full max-w-7xl min-w-0 flex-col gap-4 pb-8 sm:px-2">
      <Heading right={toggles} />
      {data.untracked.length > 0 && <TrackBanner projectId={projectId} data={data} />}

      <FloorTabs maps={data.maps} current={map.id} onPick={(id) => { setMapId(id); setSelected(null); setTrade(null) }} />

      <div className="grid min-w-0 gap-4 lg:grid-cols-[1fr_22rem]">
        <div className="flex min-w-0 flex-col gap-3">
          <TradeChips map={map} trade={trade} onPick={setTrade} />
          <div className="relative">
            <PlanCanvas map={map} trade={trade} blueprint={blueprint} photos={photos} selected={selected}
              onSelect={(m) => setSelected(m?.key ?? null)} className="h-[62vh] min-h-[420px] w-full border shadow-inner" />
            <div className="pointer-events-none absolute top-3 left-3 flex flex-wrap gap-2 text-xs">
              <span className={cn('rounded-full px-3 py-1 font-medium shadow backdrop-blur', blueprint ? 'bg-slate-950/70 text-white' : 'bg-white/90 text-slate-800')}>
                {[map.document.number ?? map.document.title, map.name, map.document.revision && `rev ${map.document.revision}`].filter(Boolean).join(' · ')}
              </span>
            </div>
            <Legend blueprint={blueprint} />
          </div>
        </div>
        <aside className="flex min-w-0 flex-col gap-4">
          {marker ? (
            <Passport projectId={projectId} map={map} marker={marker} trade={trade} onClose={() => setSelected(null)} onPhoto={(urls, i) => setLightbox({ urls, i })} />
          ) : (
            <>
              <FloorProgress map={map} trade={trade} onTrade={setTrade} />
              <Feed data={data} onOpen={(item) => { if (item.map_id) { setMapId(item.map_id); setSelected(item.place_id) } }} onPhoto={(url) => setLightbox({ urls: [url], i: 0 })} />
            </>
          )}
        </aside>
      </div>
      {lightbox && <Lightbox {...lightbox} onClose={() => setLightbox(null)} onMove={(i) => setLightbox({ ...lightbox, i })} />}
    </div>
  )
}

function FloorTabs({ maps, current, onPick }: { maps: LiveMap[]; current: string; onPick: (id: string) => void }) {
  return (
    <nav className="-mx-1 flex gap-2 overflow-x-auto px-1 pb-1" aria-label="Floors">
      {maps.map((m) => {
        const share = m.summary.count ? m.summary.done / m.summary.count : 0
        const on = m.id === current
        return (
          <button key={m.id} type="button" onClick={() => onPick(m.id)}
            className={cn('flex shrink-0 items-center gap-3 rounded-2xl border px-3 py-2 text-left transition-all',
              on ? 'border-sky-500 bg-sky-500/10 shadow-md shadow-sky-500/10' : 'bg-card hover:border-sky-300')}>
            <Ring value={share} size={38} stroke={4} className={on ? 'text-sky-600' : 'text-emerald-500'}>
              <span className="text-[10px] font-bold tabular-nums">{Math.round(share * 100)}%</span>
            </Ring>
            <span>
              <span className="block text-sm font-semibold">{m.name}</span>
              <span className="block text-xs text-muted-foreground">{m.summary.done} of {m.summary.count} {m.kind === 'foundation' ? 'footings' : 'rooms'} done</span>
            </span>
          </button>
        )
      })}
    </nav>
  )
}

function TradeChips({ map, trade, onPick }: { map: LiveMap; trade: string | null; onPick: (k: string | null) => void }) {
  if (!map.kinds.length) return null
  return (
    <div className="flex flex-wrap items-center gap-2">
      <button type="button" onClick={() => onPick(null)} className={cn('rounded-full border px-3 py-1 text-xs font-medium', !trade ? 'border-foreground bg-foreground text-background' : 'hover:bg-muted')}>All work</button>
      {map.kinds.map((k) => (
        <button key={k.key} type="button" onClick={() => onPick(trade === k.key ? null : k.key)}
          className={cn('flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-medium transition', trade === k.key ? 'border-sky-600 bg-sky-600 text-white' : 'hover:bg-muted')}>
          {k.name}
          <span className={cn('rounded-full px-1.5 tabular-nums', trade === k.key ? 'bg-white/20' : 'bg-muted')}>{k.done}/{k.total}</span>
        </button>
      ))}
    </div>
  )
}

function Legend({ blueprint }: { blueprint: boolean }) {
  return (
    <div className={cn('pointer-events-none absolute bottom-3 left-3 flex gap-3 rounded-full px-3 py-1.5 text-[11px] shadow backdrop-blur', blueprint ? 'bg-slate-950/70 text-white' : 'bg-white/90 text-slate-700')}>
      {(['done', 'in_progress', 'not_started'] as LiveState[]).map((s) => <span key={s} className="flex items-center gap-1.5"><span className={cn('size-2.5 rounded-full', DOT[s])} />{STATE_WORD[s]}</span>)}
      <span className="flex items-center gap-1.5"><span className="relative flex size-2.5"><span className="absolute size-full animate-ping rounded-full bg-emerald-300" /><span className="relative size-2.5 rounded-full bg-emerald-400" /></span>Last 48 h</span>
    </div>
  )
}

function FloorProgress({ map, trade, onTrade }: { map: LiveMap; trade: string | null; onTrade: (k: string | null) => void }) {
  const s = map.summary
  const what = map.kind === 'foundation' ? 'footings' : 'rooms'
  return (
    <section className="rounded-2xl border bg-card p-4">
      <div className="flex items-center gap-4">
        <Ring value={s.count ? s.done / s.count : 0} size={84} stroke={8} className="text-emerald-500">
          <span className="text-center"><span className="block text-lg leading-none font-bold tabular-nums">{s.done}/{s.count}</span><span className="text-[10px] text-muted-foreground">{what}</span></span>
        </Ring>
        <div className="min-w-0">
          <h2 className="text-lg font-semibold">{map.name}</h2>
          <p className="text-sm text-muted-foreground">{s.in_progress} under way · {s.not_started} not started{s.photos ? ` · ${s.photos} photos` : ''}</p>
        </div>
      </div>
      {map.kind === 'foundation' && s.concrete_cum ? (
        <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
          <Stat label="Concrete placed" value={`${s.concrete_done_cum?.toFixed(1)} / ${s.concrete_cum.toFixed(1)} m³`} share={(s.concrete_done_cum ?? 0) / s.concrete_cum} />
          <Stat label="Steel tied" value={`${((s.steel_done_kg ?? 0) / 1000).toFixed(2)} / ${((s.steel_kg ?? 0) / 1000).toFixed(2)} t`} share={(s.steel_done_kg ?? 0) / (s.steel_kg || 1)} />
        </div>
      ) : null}
      {map.kinds.length > 0 && (
        <div className="mt-4 flex flex-col gap-2.5">
          {map.kinds.map((k) => (
            <button key={k.key} type="button" onClick={() => onTrade(trade === k.key ? null : k.key)} className={cn('rounded-lg p-1 text-left transition hover:bg-muted/60', trade === k.key && 'bg-sky-500/10')}>
              <div className="flex justify-between text-xs"><span className="font-medium">{k.name}</span><span className="text-muted-foreground tabular-nums">{k.done} done{k.started ? ` · ${k.started} under way` : ''} / {k.total}</span></div>
              <div className="mt-1 flex h-2 overflow-hidden rounded-full bg-muted">
                <div className="bg-emerald-500 transition-all duration-700" style={{ width: `${(k.done / (k.total || 1)) * 100}%` }} />
                <div className="bg-amber-400 transition-all duration-700" style={{ width: `${(k.started / (k.total || 1)) * 100}%` }} />
              </div>
            </button>
          ))}
        </div>
      )}
      {!map.kinds.length && <p className="mt-3 text-sm text-muted-foreground">Nothing reported here yet. When site sends “{map.markers[0]?.label ?? 'B3'} {map.kind === 'foundation' ? 'footing concreted' : 'plastering done'}”, it shows on the plan.</p>}
    </section>
  )
}

function Stat({ label, value, share }: { label: string; value: string; share: number }) {
  return (
    <div className="rounded-xl bg-muted/50 p-2.5">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="font-semibold tabular-nums">{value}</div>
      <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-muted"><div className="h-full bg-emerald-500" style={{ width: `${Math.min(100, share * 100)}%` }} /></div>
    </div>
  )
}

function Feed({ data, onOpen, onPhoto }: { data: LiveMaps; onOpen: (item: LiveMaps['feed'][number]) => void; onPhoto: (url: string) => void }) {
  const [now, setNow] = React.useState(() => Date.now())
  React.useEffect(() => { const t = setInterval(() => setNow(Date.now()), 30_000); return () => clearInterval(t) }, [])
  return (
    <section className="rounded-2xl border bg-card p-4">
      <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold"><MessageCircle className="size-4 text-emerald-600" /> From site, live</h2>
      {data.feed.length === 0 ? <p className="text-sm text-muted-foreground">Nothing yet. Site's WhatsApp updates appear here as they come.</p> : (
        <ol className="relative flex flex-col gap-3 border-l border-dashed pl-4">
          {data.feed.map((f) => (
            <li key={f.id} className="relative">
              <span className={cn('absolute top-1.5 -left-[21px] size-2.5 rounded-full ring-4 ring-card', f.finished ? 'bg-emerald-500' : 'bg-amber-400')} />
              <button type="button" onClick={() => onOpen(f)} className="w-full text-left">
                <p className="text-sm"><span className="font-semibold">{f.place?.split(' / ').pop()}</span> · {f.work ?? 'work'}{f.finished && <span className="text-emerald-600"> ✓</span>}</p>
                <p className="text-xs text-muted-foreground">{f.who ?? 'Someone'} · {f.via} · {timeAgo(f.at, now)}</p>
              </button>
              {f.photo && <button type="button" onClick={() => onPhoto(f.photo!)} className="mt-1.5"><img src={f.photo} alt="" className="h-16 w-24 rounded-lg object-cover" loading="lazy" /></button>}
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}

function Passport({ projectId, map, marker, trade, onClose, onPhoto }: { projectId: string; map: LiveMap; marker: LiveMarker; trade: string | null; onClose: () => void; onPhoto: (urls: string[], i: number) => void }) {
  const work = useQuery({ queryKey: ['place-work', projectId, marker.place_id], queryFn: () => fetchPlaceWork(projectId, marker.place_id!), enabled: !!marker.place_id })
  const st = stateFor(marker, trade)
  const allPhotos = (work.data?.work ?? []).flatMap((w) => w.photos)
  const icon = { done: CheckCircle2, in_progress: CircleDot, not_started: Circle }
  return (
    <section className="flex flex-col gap-4 rounded-2xl border bg-card p-4 shadow-lg">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-xs tracking-wide text-muted-foreground uppercase">{map.name}</p>
          <h2 className="text-xl font-bold">{marker.label}</h2>
          {marker.sub && <p className="text-sm text-muted-foreground">{marker.sub}{marker.area_sqft ? ` · ${Math.round(marker.area_sqft)} sq ft` : ''}</p>}
        </div>
        <Button size="icon" variant="ghost" aria-label="Close" onClick={onClose}><X className="size-4" /></Button>
      </div>
      <span className={cn('w-fit rounded-full px-3 py-1 text-xs font-semibold', st === 'done' ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200' : st === 'in_progress' ? 'bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200' : 'bg-muted text-muted-foreground')}>{STATE_WORD[st]}</span>
      {map.kinds.length > 0 && (
        <div className="flex flex-col gap-1.5">
          <p className="text-xs font-semibold text-muted-foreground">Work here</p>
          {map.kinds.map((k) => {
            const s = marker.cells[k.key] ?? 'not_started'
            const Icon = icon[s]
            return <div key={k.key} className="flex items-center gap-2 text-sm"><Icon className={cn('size-4', s === 'done' ? 'text-emerald-500' : s === 'in_progress' ? 'text-amber-500' : 'text-muted-foreground')} />{k.name}<span className="ml-auto text-xs text-muted-foreground">{STATE_WORD[s]}</span></div>
          })}
        </div>
      )}
      {map.kind === 'foundation' && marker.concrete_cum ? <p className="text-sm">This footing: {marker.concrete_cum.toFixed(2)} m³ concrete, {Math.round(marker.steel_kg ?? 0)} kg steel</p> : null}
      <div>
        <p className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-muted-foreground"><Camera className="size-3.5" /> Photo timeline</p>
        {!marker.place_id ? <p className="text-sm text-muted-foreground">Track the drawing to record work here.</p>
          : !work.data ? <Skeleton className="h-24 w-full" />
          : allPhotos.length === 0 ? <p className="text-sm text-muted-foreground">No photos yet. A photo sent with “{marker.label} …” on WhatsApp lands here.</p> : (
            <div className="grid grid-cols-3 gap-1.5">
              {allPhotos.slice(0, 9).map((u, i) => (
                <button key={u} type="button" onClick={() => onPhoto(allPhotos, i)} className="group relative aspect-square overflow-hidden rounded-lg">
                  <img src={u} alt="" className="size-full object-cover transition group-hover:scale-105" loading="lazy" />
                </button>
              ))}
            </div>
          )}
      </div>
      {work.data && work.data.work.length > 0 && (
        <div className="flex flex-col gap-2">
          <p className="text-xs font-semibold text-muted-foreground">Updates</p>
          {work.data.work.map((w) => (
            <div key={w.id} className="flex items-start justify-between gap-2 border-t pt-2 text-sm">
              <div><p className="font-medium">{w.work_type ?? 'Work'}{w.finished && <span className="ml-1 text-xs text-emerald-600">finished</span>}</p><p className="text-xs text-muted-foreground">{w.reported_by ?? ''}</p></div>
              <span className="shrink-0 text-xs text-muted-foreground">{day(w.date)}</span>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}

function Lightbox({ urls, i, onClose, onMove }: { urls: string[]; i: number; onClose: () => void; onMove: (i: number) => void }) {
  React.useEffect(() => {
    const key = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); if (e.key === 'ArrowRight' && i < urls.length - 1) onMove(i + 1); if (e.key === 'ArrowLeft' && i > 0) onMove(i - 1) }
    window.addEventListener('keydown', key)
    return () => window.removeEventListener('keydown', key)
  }, [i, urls.length, onClose, onMove])
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/85 p-4 backdrop-blur" role="dialog" aria-label="Photo" onClick={onClose}>
      <img src={urls[i]} alt="" className="max-h-[85vh] max-w-full rounded-xl shadow-2xl" onClick={(e) => e.stopPropagation()} />
      {i > 0 && <button type="button" aria-label="Previous photo" className="absolute left-4 rounded-full bg-white/15 p-3 text-white" onClick={(e) => { e.stopPropagation(); onMove(i - 1) }}><ChevronLeft /></button>}
      {i < urls.length - 1 && <button type="button" aria-label="Next photo" className="absolute right-4 rounded-full bg-white/15 p-3 text-white" onClick={(e) => { e.stopPropagation(); onMove(i + 1) }}><ChevronRight /></button>}
      <span className="absolute bottom-4 text-sm text-white/70">{i + 1} / {urls.length}</span>
    </div>
  )
}

function TrackBanner({ projectId, data }: { projectId: string; data: LiveMaps }) {
  const toast = useToast()
  const qc = useQueryClient()
  const track = useMutation({
    mutationFn: async () => { for (const d of data.untracked) await trackOnSite(d.id) },
    onSuccess: () => { toast.success('Footings and rooms are now places on site', 'Site\'s WhatsApp updates will colour them.'); qc.invalidateQueries({ queryKey: ['live-maps', projectId] }); qc.invalidateQueries({ queryKey: ['places'] }) },
    onError: (e) => toast.error('Not set up', apiErrorMessage(e)),
  })
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-sky-200 bg-gradient-to-r from-sky-50 to-indigo-50 p-4 dark:border-sky-900 dark:from-sky-950/40 dark:to-indigo-950/40">
      <p className="max-w-2xl text-sm">
        <span className="font-semibold">{data.untracked.map((d) => d.number ?? d.title).join(', ')}</span>: Mesiri found the footings and rooms on {data.untracked.length > 1 ? 'these drawings' : 'this drawing'}.
        Track them, and site's WhatsApp messages (“kitchen plastering done”, “B3 footing concreted”) colour them here.
      </p>
      {data.can_track ? <Button disabled={track.isPending} onClick={() => track.mutate()}>{track.isPending ? 'Setting up…' : 'Track on site'}</Button>
        : <span className="text-xs text-muted-foreground">The owner, an admin or the PM can turn this on.</span>}
    </div>
  )
}

function Empty({ projectId }: { projectId: string }) {
  return (
    <div className="relative overflow-hidden rounded-2xl border bg-[#0a1a33] p-8 text-white sm:p-12">
      <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(rgba(125,211,252,.08)_1px,transparent_1px),linear-gradient(90deg,rgba(125,211,252,.08)_1px,transparent_1px)] bg-[size:28px_28px]" />
      <div className="relative max-w-xl">
        <h2 className="text-2xl font-semibold">Your drawings, alive</h2>
        <p className="mt-2 text-slate-300">Upload the architect's floor plans or the structural set in Documents. Every room and footing becomes a place on site, and site's WhatsApp updates colour them in, with the photos.</p>
        <Button asChild className="mt-6 gap-2"><Link to={`/planning/documents?project=${projectId}`}><FileUp className="size-4" /> Upload drawings</Link></Button>
      </div>
    </div>
  )
}
