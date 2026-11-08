import * as React from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, ChevronLeft, ChevronRight, CircleCheck, CircleDashed, Circle, Images, MapPinned, MessageCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useToast } from '@/components/ui/toast-notification'
import { Callout, DprAside, PageError, PageHeader, Segmented, StatStrip, type Stat } from '@/components/dpr-page'
import { ProjectPickList, usePlanningProject } from '@/components/schedule/project-picker'
import { PlanCanvas } from '@/components/live-maps/plan-canvas'
import { CHIP_STATE, fetchLiveMaps, SOFT_STATE, STATE_WORD, stateFor, timeAgo, trackOnSite, type LiveFeedItem, type LiveMap, type LiveMaps, type LiveMarker, type LiveState } from '@/lib/live-maps'
import { apiErrorMessage } from '@/lib/logo-upload'
import { usePageTitle } from '@/lib/page-title'
import { fetchPlaceWork } from '@/lib/places'
import { CHIP } from '@/lib/site-day'
import { cn } from '@/lib/utils'

// DR-10 / DR-11: Planning › Live plans. The project's drawings, each room and footing coloured by the work site sent on
// WhatsApp: the floor's numbers, the plan, and beside it the work by trade and the newest updates, or one room's
// details. Built from the dashboard's own parts (docs/DESIGN.md): one page in flat sections, status tokens only.

const STATE_ICON: Record<LiveState, React.ComponentType<{ className?: string }>> = { done: CircleCheck, in_progress: CircleDashed, not_started: Circle }
const ICON_TONE: Record<LiveState, string> = { done: 'text-success', in_progress: 'text-info', not_started: 'text-muted-foreground' }

function day(iso: string | null): string {
  return iso ? new Date(`${iso.slice(0, 10)}T00:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' }) : ''
}

export default function LivePlansPage() {
  usePageTitle('Live plans')
  const projectId = usePlanningProject()
  if (!projectId) {
    return (
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-4 pb-4 sm:px-2">
        <PageHeader title="Live plans" subtitle="The drawings, coloured by the work site reports on WhatsApp." />
        <ProjectPickList to={(id) => `/planning/live?project=${id}`} empty="No projects yet. Add one in Projects & Sites." />
      </div>
    )
  }
  return <Live key={projectId} projectId={projectId} />
}

function LiveLine() {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="relative flex size-2"><span className="absolute inline-flex size-full animate-ping rounded-full bg-success opacity-40" /><span className="relative inline-flex size-2 rounded-full bg-success" /></span>
      Live from site's WhatsApp updates
    </span>
  )
}

function Live({ projectId }: { projectId: string }) {
  const query = useQuery<LiveMaps>({ queryKey: ['live-maps', projectId], queryFn: () => fetchLiveMaps(projectId), staleTime: 0, refetchInterval: 15_000 })
  const [mapId, setMapId] = React.useState<string | null>(null)
  const [trade, setTrade] = React.useState<string>('all')
  const [selected, setSelected] = React.useState<string | null>(null)
  const [photos, setPhotos] = React.useState(false)
  const [lightbox, setLightbox] = React.useState<{ urls: string[]; i: number } | null>(null)

  if (query.isError) return <PageError message="The live plans did not load." onRetry={() => query.refetch()} back={{ to: '/planning/live', label: 'All projects' }} />
  const data = query.data
  const map = data?.maps.find((m) => m.id === mapId) ?? data?.maps[0]
  const marker = map?.markers.find((m) => m.key === selected) ?? null
  const tradeKey = trade === 'all' ? null : trade

  const header = (
    <PageHeader title="Live plans" subtitle={<LiveLine />}
      actions={map && (
        <Button variant={photos ? 'secondary' : 'outline'} size="sm" className="gap-1.5" aria-pressed={photos} onClick={() => setPhotos((p) => !p)}>
          <Images className="size-3.5" /> Photos on the plan
        </Button>
      )} />
  )

  if (!data) {
    return (
      <div className="mx-auto flex w-full max-w-6xl animate-pulse flex-col gap-4 pb-4 sm:px-2" aria-busy="true" aria-label="Loading">
        {header}
        <div className="h-8 w-80 rounded-lg bg-muted" />
        <div className="h-16 rounded-xl bg-muted/60" />
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_300px]"><div className="h-[60vh] rounded-xl bg-muted/60" /><div className="h-80 rounded-xl bg-muted/60" /></div>
      </div>
    )
  }
  if (!map) {
    return (
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-4 pb-4 sm:px-2">
        {header}
        <Callout tone="muted" icon={MapPinned} action={<Button asChild size="sm" variant="outline"><Link to={`/planning/documents?project=${projectId}`}>Open Documents</Link></Button>}>
          No drawings with rooms or footings yet. Upload the architect's floor plans or the structural set in Documents: each room and footing shows here, coloured by the work site reports.
        </Callout>
      </div>
    )
  }

  const pick = (id: string) => { setMapId(id); setSelected(null); setTrade('all') }
  const s = map.summary
  const what = map.kind === 'foundation' ? 'Footings' : 'Rooms'
  const stats: Stat[] = map.kind === 'foundation' && s.concrete_cum
    ? [
        { label: 'Footings done', value: `${s.done} of ${s.count}`, tone: s.done === s.count ? 'good' : undefined },
        { label: 'Under way', value: s.in_progress || '—', tone: s.in_progress ? 'info' : undefined },
        { label: 'Concrete placed', value: `${(s.concrete_done_cum ?? 0).toFixed(1)} of ${s.concrete_cum.toFixed(1)} m³` },
        { label: 'Steel in place', value: `${((s.steel_done_kg ?? 0) / 1000).toFixed(2)} of ${((s.steel_kg ?? 0) / 1000).toFixed(2)} t` },
      ]
    : [
        { label: `${what} done`, value: `${s.done} of ${s.count}`, tone: s.count && s.done === s.count ? 'good' : undefined, hint: 'every trade finished' },
        { label: 'Under way', value: s.in_progress || '—', tone: s.in_progress ? 'info' : undefined },
        { label: 'Not started', value: s.not_started || '—' },
        { label: 'Photos', value: s.photos || '—' },
      ]

  return (
    <div className="mx-auto flex w-full max-w-6xl min-w-0 flex-col gap-4 pb-4 sm:px-2">
      {header}
      {data.untracked.length > 0 && <TrackCallout projectId={projectId} data={data} />}

      <div className="flex flex-wrap items-center justify-between gap-2">
        <Segmented label="Drawing" value={map.id} onChange={pick}
          options={data.maps.map((m) => ({ value: m.id, label: `${m.name} · ${m.summary.done}/${m.summary.count}` }))} />
        {map.kinds.length > 0 && (
          <Segmented label="Trade" value={map.kinds.some((k) => k.key === trade) ? trade : 'all'} onChange={setTrade}
            options={[{ value: 'all', label: 'All work' }, ...map.kinds.map((k) => ({ value: k.key, label: k.name }))]} />
        )}
      </div>
      <StatStrip stats={stats} phoneCols={2} />

      <div className="grid min-w-0 gap-4 lg:grid-cols-[minmax(0,1fr)_300px]">
        <div className="flex min-w-0 flex-col gap-2">
          <PlanCanvas map={map} trade={tradeKey} photos={photos} selected={selected} onSelect={(m) => setSelected(m?.key ?? null)} className="h-[62vh] min-h-[420px] w-full" />
          <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 text-xs text-muted-foreground">
            <span className="flex flex-wrap items-center gap-3">
              {(['done', 'in_progress', 'not_started'] as LiveState[]).map((st) => (
                <span key={st} className="inline-flex items-center gap-1.5"><span className={cn('size-2.5 rounded-sm border', CHIP_STATE[st])} />{STATE_WORD[st]}</span>
              ))}
              <span className="inline-flex items-center gap-1.5"><span className="size-2 rounded-full bg-primary" />Updated in the last 2 days</span>
            </span>
            <span className="truncate">{[map.document.number ?? map.document.title, map.document.revision && `rev ${map.document.revision}`, `page ${map.page}`].filter(Boolean).join(' · ')}</span>
          </div>
        </div>
        <DprAside>
          {marker ? (
            <Details projectId={projectId} map={map} marker={marker} trade={tradeKey} onBack={() => setSelected(null)} onPhoto={(urls, i) => setLightbox({ urls, i })} />
          ) : (
            <>
              <ByTrade map={map} trade={trade} onTrade={setTrade} />
              <Feed items={data.feed} onOpen={(f) => { if (f.map_id) { setMapId(f.map_id); setSelected(f.place_id) } }} onPhoto={(url) => setLightbox({ urls: [url], i: 0 })} />
            </>
          )}
        </DprAside>
      </div>
      {lightbox && <Lightbox {...lightbox} onClose={() => setLightbox(null)} onMove={(i) => setLightbox({ ...lightbox, i })} />}
    </div>
  )
}

function ByTrade({ map, trade, onTrade }: { map: LiveMap; trade: string; onTrade: (k: string) => void }) {
  const what = map.kind === 'foundation' ? 'footings' : 'rooms'
  return (
    <section className="flex flex-col gap-3">
      <h2 className="text-sm font-semibold">By trade</h2>
      {map.kinds.length === 0 ? (
        <p className="text-sm text-muted-foreground">Nothing reported yet. When site sends “{map.markers[0]?.label ?? 'B3'} {map.kind === 'foundation' ? 'footing concreted' : 'plastering done'}” on WhatsApp, it shows here and on the plan.</p>
      ) : map.kinds.map((k) => (
        <button key={k.key} type="button" onClick={() => onTrade(trade === k.key ? 'all' : k.key)} aria-pressed={trade === k.key}
          className={cn('-mx-2 flex flex-col gap-1.5 rounded-md px-2 py-1 text-left hover:bg-muted/60', trade === k.key && 'bg-muted')}>
          <span className="flex items-baseline justify-between gap-2 text-sm">
            <span className="font-medium">{k.name}</span>
            <span className="text-xs text-muted-foreground tabular-nums">{k.done} of {k.total} {what}</span>
          </span>
          <span className="flex h-1.5 overflow-hidden rounded-full bg-muted" aria-hidden>
            <span className="bg-success transition-all duration-500" style={{ width: `${(k.done / (k.total || 1)) * 100}%` }} />
            <span className="bg-info/60 transition-all duration-500" style={{ width: `${(k.started / (k.total || 1)) * 100}%` }} />
          </span>
        </button>
      ))}
    </section>
  )
}

function Feed({ items, onOpen, onPhoto }: { items: LiveFeedItem[]; onOpen: (f: LiveFeedItem) => void; onPhoto: (url: string) => void }) {
  const [now, setNow] = React.useState(() => Date.now())
  React.useEffect(() => { const t = setInterval(() => setNow(Date.now()), 30_000); return () => clearInterval(t) }, [])
  return (
    <section className="flex flex-col gap-1">
      <h2 className="mb-1 flex items-center gap-1.5 text-sm font-semibold"><MessageCircle className="size-3.5 text-muted-foreground" /> From site</h2>
      {items.length === 0 ? <p className="text-sm text-muted-foreground">Site's WhatsApp updates show here as they come.</p> : (
        <ul className="-mx-2 flex flex-col">
          {items.slice(0, 8).map((f) => {
            const Icon = f.finished ? CircleCheck : CircleDashed
            return (
              <li key={f.id} className="flex items-start gap-2 rounded-md px-2 py-1.5 hover:bg-muted/60">
                <Icon className={cn('mt-0.5 size-4 shrink-0', f.finished ? 'text-success' : 'text-info')} />
                <button type="button" className="min-w-0 flex-1 text-left" onClick={() => onOpen(f)}>
                  <p className="truncate text-sm"><span className="font-medium">{f.place?.split(' / ').pop()}</span><span className="text-muted-foreground"> · {f.work ?? 'Work'}{f.finished ? ' done' : ''}</span></p>
                  <p className="truncate text-xs text-muted-foreground">{f.who ?? 'Someone'} · {f.via} · {timeAgo(f.at, now)}</p>
                </button>
                {f.photo && <button type="button" className="shrink-0" onClick={() => onPhoto(f.photo!)} aria-label="Open the photo"><img src={f.photo} alt="" className="size-9 rounded-md object-cover" loading="lazy" /></button>}
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}

function Details({ projectId, map, marker, trade, onBack, onPhoto }: { projectId: string; map: LiveMap; marker: LiveMarker; trade: string | null; onBack: () => void; onPhoto: (urls: string[], i: number) => void }) {
  const work = useQuery({ queryKey: ['place-work', projectId, marker.place_id], queryFn: () => fetchPlaceWork(projectId, marker.place_id!), enabled: !!marker.place_id })
  const st = stateFor(marker, trade)
  const allPhotos = (work.data?.work ?? []).flatMap((w) => w.photos)
  return (
    <>
      <section className="flex flex-col gap-2">
        <button type="button" onClick={onBack} className="inline-flex w-fit items-center gap-1 text-xs text-muted-foreground hover:text-foreground"><ArrowLeft className="size-3.5" /> {map.name}</button>
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-lg font-semibold">{marker.label}</h2>
          <span className={cn(CHIP, SOFT_STATE[st])}>{STATE_WORD[st]}</span>
        </div>
        {marker.sub && <p className="text-sm text-muted-foreground">{marker.sub}{marker.area_sqft ? ` · ${Math.round(marker.area_sqft).toLocaleString('en-IN')} sq ft` : ''}</p>}
        {map.kind === 'foundation' && marker.concrete_cum ? <p className="text-sm">{marker.concrete_cum.toFixed(2)} m³ concrete · {Math.round(marker.steel_kg ?? 0)} kg steel</p> : null}
      </section>
      {map.kinds.length > 0 && (
        <section className="flex flex-col gap-1.5">
          <h3 className="text-sm font-semibold">Work here</h3>
          {map.kinds.map((k) => {
            const s = marker.cells[k.key] ?? 'not_started'
            const Icon = STATE_ICON[s]
            return (
              <div key={k.key} className="flex items-center gap-2 text-sm">
                <Icon className={cn('size-4', ICON_TONE[s])} />{k.name}
                <span className="ml-auto text-xs text-muted-foreground">{STATE_WORD[s]}</span>
              </div>
            )
          })}
        </section>
      )}
      <section className="flex flex-col gap-2">
        <h3 className="text-sm font-semibold">Photos {allPhotos.length > 0 && <span className="font-normal text-muted-foreground">{allPhotos.length}</span>}</h3>
        {!marker.place_id ? <p className="text-sm text-muted-foreground">Not tracked yet: track the drawing to record work here.</p>
          : !work.data ? <div className="h-20 animate-pulse rounded-md bg-muted" />
          : allPhotos.length === 0 ? <p className="text-sm text-muted-foreground">None yet. A photo sent with “{marker.label} …” on WhatsApp shows here.</p> : (
            <div className="grid grid-cols-3 gap-1.5">
              {allPhotos.slice(0, 9).map((u, i) => (
                <button key={u} type="button" onClick={() => onPhoto(allPhotos, i)} className="aspect-square overflow-hidden rounded-md bg-muted" aria-label={`Photo ${i + 1}`}>
                  <img src={u} alt="" className="size-full object-cover" loading="lazy" />
                </button>
              ))}
            </div>
          )}
      </section>
      {work.data && work.data.work.length > 0 && (
        <section className="flex flex-col">
          <h3 className="mb-1 text-sm font-semibold">Updates</h3>
          {work.data.work.map((w) => (
            <div key={w.id} className="flex items-start gap-2 border-t py-2 text-sm first:border-t-0">
              {w.finished ? <CircleCheck className="mt-0.5 size-4 shrink-0 text-success" /> : <CircleDashed className="mt-0.5 size-4 shrink-0 text-info" />}
              <div className="min-w-0 flex-1"><p className="font-medium">{w.work_type ?? 'Work'}{w.finished ? ' done' : ''}</p>{w.reported_by && <p className="text-xs text-muted-foreground">{w.reported_by}</p>}</div>
              <span className="shrink-0 text-xs text-muted-foreground">{day(w.date)}</span>
            </div>
          ))}
        </section>
      )}
    </>
  )
}

function Lightbox({ urls, i, onClose, onMove }: { urls: string[]; i: number; onClose: () => void; onMove: (i: number) => void }) {
  React.useEffect(() => {
    const key = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); if (e.key === 'ArrowRight' && i < urls.length - 1) onMove(i + 1); if (e.key === 'ArrowLeft' && i > 0) onMove(i - 1) }
    window.addEventListener('keydown', key)
    return () => window.removeEventListener('keydown', key)
  }, [i, urls.length, onClose, onMove])
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/80 p-4" role="dialog" aria-label="Photo" onClick={onClose}>
      <img src={urls[i]} alt="" className="max-h-[85vh] max-w-full rounded-lg shadow-2xl" onClick={(e) => e.stopPropagation()} />
      {i > 0 && <button type="button" aria-label="Previous photo" className="absolute left-4 rounded-full bg-background/90 p-2 shadow" onClick={(e) => { e.stopPropagation(); onMove(i - 1) }}><ChevronLeft className="size-5" /></button>}
      {i < urls.length - 1 && <button type="button" aria-label="Next photo" className="absolute right-4 rounded-full bg-background/90 p-2 shadow" onClick={(e) => { e.stopPropagation(); onMove(i + 1) }}><ChevronRight className="size-5" /></button>}
      <span className="absolute bottom-4 rounded-full bg-background/90 px-2.5 py-0.5 text-xs tabular-nums">{i + 1} of {urls.length}</span>
    </div>
  )
}

function TrackCallout({ projectId, data }: { projectId: string; data: LiveMaps }) {
  const toast = useToast()
  const qc = useQueryClient()
  const track = useMutation({
    mutationFn: async () => { for (const d of data.untracked) await trackOnSite(d.id) },
    onSuccess: () => { toast.success('Rooms and footings are now places on site', 'Site\'s WhatsApp updates will colour them.'); qc.invalidateQueries({ queryKey: ['live-maps', projectId] }); qc.invalidateQueries({ queryKey: ['places'] }) },
    onError: (e) => toast.error('Not set up', apiErrorMessage(e)),
  })
  const names = data.untracked.map((d) => d.number ?? d.title).join(', ')
  return (
    <Callout tone="draft" icon={MapPinned}
      action={data.can_track ? <Button size="sm" disabled={track.isPending} onClick={() => track.mutate()}>{track.isPending ? 'Setting up…' : 'Track on site'}</Button> : undefined}>
      <span className="font-medium">{names}</span> {data.untracked.length > 1 ? 'are' : 'is'} not tracked on site yet. Track {data.untracked.length > 1 ? 'them' : 'it'} and site's messages (“kitchen plastering done”, “B3 footing concreted”) colour the rooms and footings here.
      {!data.can_track && ' The owner, an admin or the project manager can do this.'}
    </Callout>
  )
}
