import * as React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Camera, HardHat, MessageCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useToast } from '@/components/ui/toast-notification'
import { trackFootings, type FootingState, type LiveMarker, type LivePlan } from '@/lib/live-plan'
import { apiErrorMessage } from '@/lib/logo-upload'
import { fetchPlaceWork } from '@/lib/places'
import { cn } from '@/lib/utils'

// DR-10: the footing plan as drawn, each footing coloured by what site reported there. Nothing to type: site's
// WhatsApp update ("B3 footing concreted") turns B3 green here.

const DOT: Record<FootingState, string> = {
  done: 'bg-emerald-500 text-white ring-emerald-700/40',
  in_progress: 'bg-amber-400 text-amber-950 ring-amber-700/40',
  not_started: 'bg-white/90 text-slate-700 ring-slate-400 dark:bg-slate-200',
}
const WORD: Record<FootingState, string> = { done: 'Done', in_progress: 'In progress', not_started: 'Not started' }

function day(iso: string | null): string {
  return iso ? new Date(`${iso}T00:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' }) : ''
}

function num(n: number, d = 0): string {
  return n.toLocaleString('en-IN', { maximumFractionDigits: d, minimumFractionDigits: d })
}

function Bar({ label, done, all, unit, digits = 1 }: { label: string; done: number; all: number; unit: string; digits?: number }) {
  const pct = all ? Math.round((done / all) * 100) : 0
  return (
    <div className="min-w-0 flex-1">
      <div className="flex justify-between gap-2 text-xs"><span className="text-muted-foreground">{label}</span><span className="tabular-nums">{num(done, digits)} of {num(all, digits)}{unit ? ` ${unit}` : ''}</span></div>
      <div className="mt-1 h-2 overflow-hidden rounded-full bg-muted"><div className="h-full rounded-full bg-emerald-500 transition-all" style={{ width: `${pct}%` }} /></div>
    </div>
  )
}

export function LiveFootingPlan({ live, refreshKey }: { live: LivePlan; refreshKey: unknown[] }) {
  const toast = useToast()
  const qc = useQueryClient()
  const [open, setOpen] = React.useState<LiveMarker | null>(null)
  const track = useMutation({
    mutationFn: () => trackFootings(live.document.id),
    onSuccess: (out) => {
      toast.success(`${out.tracked} footings are now places on site`, 'Site can say "B3 footing concreted" on WhatsApp.')
      qc.invalidateQueries({ queryKey: refreshKey })
      qc.invalidateQueries({ queryKey: ['places'] })
    },
    onError: (e) => toast.error('Footings not set up', apiErrorMessage(e)),
  })
  const s = live.summary
  const pageRatio = live.image_width && live.image_height ? live.image_width / live.image_height : 0.707
  // Zoom to the footings (with a margin), so the plan fills the box instead of the sheet's border and title block.
  const crop = React.useMemo(() => {
    const xs = live.markers.map((m) => m.x)
    const ys = live.markers.map((m) => m.y)
    if (xs.length < 2) return { x: 0, y: 0, w: 1, h: 1 }
    const pad = 0.08
    const x = Math.max(0, Math.min(...xs) - pad)
    const y = Math.max(0, Math.min(...ys) - pad)
    return { x, y, w: Math.min(1, Math.max(...xs) + pad) - x, h: Math.min(1, Math.max(...ys) + pad) - y }
  }, [live.markers])
  const ratio = (crop.w * pageRatio) / crop.h
  const example = live.markers.find((m) => m.grid)?.grid ?? 'B3'

  return (
    <section className="flex flex-col gap-3 rounded-xl border p-3 sm:p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="flex items-center gap-2 text-base font-semibold"><HardHat className="size-4" /> Live foundation plan</h2>
          <p className="text-xs text-muted-foreground">
            {[live.document.number, live.document.title, live.document.revision && `rev ${live.document.revision}`].filter(Boolean).join(' · ')} · page {live.page}
          </p>
        </div>
        <div className="flex gap-3 text-xs">
          {(['done', 'in_progress', 'not_started'] as FootingState[]).map((k) => (
            <span key={k} className="inline-flex items-center gap-1"><span className={cn('inline-block size-3 rounded-full ring-1', DOT[k])} />{WORD[k]} {s[k]}</span>
          ))}
        </div>
      </div>

      {!live.tracked ? (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg bg-primary/5 p-3 text-sm">
          <p className="max-w-xl">
            Mesiri found {s.footings} footings on this plan, each on its grid. Track them and site's WhatsApp updates colour them in:
            <span className="font-medium"> “{example} footing concreted”</span> turns {example} green.
          </p>
          {live.can_track ? (
            <Button size="sm" disabled={track.isPending} onClick={() => track.mutate()}>{track.isPending ? 'Setting up…' : 'Track footings on site'}</Button>
          ) : <span className="text-xs text-muted-foreground">The owner, an admin or the PM can turn this on.</span>}
        </div>
      ) : (
        <div className="flex flex-col gap-3 sm:flex-row">
          <Bar label="Footings done" done={s.done} all={s.footings} unit="" digits={0} />
          <Bar label="Concrete placed" done={s.concrete_done_cum} all={s.concrete_cum} unit="m³" />
          <Bar label="Steel tied" done={s.steel_done_kg / 1000} all={s.steel_kg / 1000} unit="t" />
        </div>
      )}

      <div className="grid gap-3 lg:grid-cols-[1fr_16rem]">
        <div className="relative w-full overflow-hidden rounded-lg border bg-white" style={{ aspectRatio: String(ratio) }}>
          {live.image_url ? (
            <img src={live.image_url} alt={`Footing plan, ${live.document.title}`} className="absolute max-w-none"
              style={{ width: `${100 / crop.w}%`, height: `${100 / crop.h}%`, left: `${(-crop.x / crop.w) * 100}%`, top: `${(-crop.y / crop.h) * 100}%` }} />
          ) : (
            <p className="absolute inset-x-0 bottom-2 text-center text-xs text-muted-foreground">The drawing's picture is not available; footings shown where they are.</p>
          )}
          {live.markers.map((m, i) => (
            <button key={`${m.grid}-${i}`} type="button" onClick={() => setOpen(m)}
              title={`${m.grid ?? ''} ${m.mark}${m.column ? ` · ${m.column}` : ''}: ${WORD[m.state]}${m.last_work ? `, ${m.last_work} ${day(m.last_date)}` : ''}`}
              className={cn('absolute flex -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full px-1 text-[9px] leading-none font-bold shadow ring-2 sm:text-[10px]',
                'h-5 min-w-5 sm:h-6 sm:min-w-6', DOT[m.state], open === m && 'scale-125 ring-primary', m.state === 'done' && 'animate-[pulse_1.2s_ease-out_1]')}
              style={{ left: `${((m.x - crop.x) / crop.w) * 100}%`, top: `${((m.y - crop.y) / crop.h) * 100}%` }}>
              {m.grid ?? m.mark}
            </button>
          ))}
        </div>
        <FootingPanel projectId={live.project_id} marker={open} tracked={live.tracked} />
      </div>
    </section>
  )
}

function FootingPanel({ projectId, marker, tracked }: { projectId: string; marker: LiveMarker | null; tracked: boolean }) {
  const work = useQuery({ queryKey: ['place-work', projectId, marker?.place_id], queryFn: () => fetchPlaceWork(projectId, marker!.place_id!), enabled: !!marker?.place_id })
  if (!marker) {
    return (
      <aside className="rounded-lg bg-muted/40 p-3 text-sm text-muted-foreground">
        <p className="flex items-center gap-1.5 font-medium text-foreground"><MessageCircle className="size-4" /> From site, on WhatsApp</p>
        <p className="mt-1">“B3 footing PCC done”, “D5 footing concreted”, “A1 steel tied” land on that footing.</p>
        <p className="mt-2">Tap a footing to see its updates and photos.</p>
      </aside>
    )
  }
  return (
    <aside className="flex flex-col gap-2 rounded-lg border p-3 text-sm">
      <p className="font-semibold">{marker.grid ?? '—'} · {marker.mark}{marker.size ? ` (${marker.size})` : ''}{marker.column ? ` · column ${marker.column}` : ''}</p>
      <p className={cn('text-xs font-medium', marker.state === 'done' ? 'text-success' : marker.state === 'in_progress' ? 'text-amber-600' : 'text-muted-foreground')}>{WORD[marker.state]}</p>
      {!tracked ? <p className="text-xs text-muted-foreground">Track the footings to record work here.</p>
        : !marker.place_id ? <p className="text-xs text-muted-foreground">No grid found for this footing.</p>
        : !work.data ? <p className="text-xs text-muted-foreground">Loading…</p>
        : work.data.work.length === 0 ? <p className="text-xs text-muted-foreground">Nothing reported yet. Site can send “{marker.grid} footing PCC done”.</p> : (
          <ul className="flex flex-col gap-2">
            {work.data.work.map((w) => (
              <li key={w.id} className="border-t pt-2">
                <div className="flex justify-between gap-2"><span className="font-medium">{w.work_type ?? 'Work'}{w.finished && <span className="ml-1 text-xs text-success">finished</span>}</span><span className="text-xs text-muted-foreground">{day(w.date)}</span></div>
                {w.reported_by && <p className="text-xs text-muted-foreground">{w.reported_by}</p>}
                {w.photos.length > 0 && (
                  <div className="mt-1 grid grid-cols-3 gap-1">
                    {w.photos.map((u) => <a key={u} href={u} target="_blank" rel="noreferrer"><img src={u} alt="" className="aspect-square w-full rounded object-cover" loading="lazy" /></a>)}
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      {marker.photos > 0 && <p className="flex items-center gap-1 text-xs text-muted-foreground"><Camera className="size-3" /> {marker.photos} photo{marker.photos > 1 ? 's' : ''}</p>}
    </aside>
  )
}
