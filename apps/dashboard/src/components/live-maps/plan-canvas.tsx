import * as React from 'react'
import { Maximize2, Minus, Plus } from 'lucide-react'
import { STATE_WORD, stateFor, type LiveMap, type LiveMarker, type LiveState } from '@/lib/live-maps'
import { cn } from '@/lib/utils'

// DR-10 / DR-11: one drawing page as a live map. Zoom with the wheel or a pinch, drag to move; markers keep their size.
// "Blueprint" shows the drawing as light lines on navy (the PNG inverted and tinted, nothing redrawn).

const PILL: Record<LiveState, string> = {
  done: 'bg-emerald-400 text-emerald-950 border-emerald-200 shadow-[0_0_18px_rgba(52,211,153,.75)]',
  in_progress: 'bg-amber-300 text-amber-950 border-amber-100 shadow-[0_0_18px_rgba(252,211,77,.7)]',
  not_started: 'bg-slate-900/70 text-slate-100 border-slate-300/50 backdrop-blur-sm',
}
const PILL_PAPER: Record<LiveState, string> = {
  done: 'bg-emerald-500 text-white border-emerald-700 shadow-md',
  in_progress: 'bg-amber-400 text-amber-950 border-amber-600 shadow-md',
  not_started: 'bg-white/95 text-slate-700 border-slate-400 shadow',
}

interface View { s: number; x: number; y: number }

function Ring({ value, className }: { value: number; className?: string }) {
  const r = 6, c = 2 * Math.PI * r
  return (
    <svg viewBox="0 0 16 16" className={cn('size-3.5 -rotate-90', className)} aria-hidden>
      <circle cx="8" cy="8" r={r} fill="none" stroke="currentColor" strokeOpacity=".25" strokeWidth="3" />
      <circle cx="8" cy="8" r={r} fill="none" stroke="currentColor" strokeWidth="3" strokeDasharray={`${c * value} ${c}`} strokeLinecap="round" />
    </svg>
  )
}

export function PlanCanvas({ map, trade, blueprint, photos, selected, onSelect, className }: {
  map: LiveMap
  trade: string | null
  blueprint: boolean
  photos: boolean
  selected: string | null
  onSelect: (m: LiveMarker | null) => void
  className?: string
}) {
  const box = React.useRef<HTMLDivElement>(null)
  const [size, setSize] = React.useState({ w: 800, h: 560 })
  const [view, setView] = React.useState<View>({ s: 1, x: 0, y: 0 })
  const pointers = React.useRef(new Map<number, { x: number; y: number }>())
  const last = React.useRef<{ x: number; y: number; d: number } | null>(null)
  const moved = React.useRef(false)
  const ratio = map.image_width && map.image_height ? map.image_width / map.image_height : 1.414
  const cw = size.w
  const ch = cw / ratio

  React.useEffect(() => {
    const el = box.current
    if (!el) return
    const ro = new ResizeObserver(([e]) => setSize({ w: e.contentRect.width, h: e.contentRect.height }))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const fit = React.useCallback(() => {
    const xs = map.markers.map((m) => m.x * cw), ys = map.markers.map((m) => m.y * ch)
    if (!xs.length) return setView({ s: Math.min(1, size.h / ch), x: 0, y: 0 })
    const pad = 70
    const x0 = Math.min(...xs) - pad, x1 = Math.max(...xs) + pad, y0 = Math.min(...ys) - pad, y1 = Math.max(...ys) + pad
    const s = Math.max(0.4, Math.min(4, Math.min(size.w / (x1 - x0), size.h / (y1 - y0))))
    setView({ s, x: size.w / 2 - s * (x0 + x1) / 2, y: size.h / 2 - s * (y0 + y1) / 2 })
  }, [map.markers, cw, ch, size.w, size.h])
  // A new floor (or the first size) fits the plan; a refresh of the same floor keeps where the person is looking.
  const fitted = React.useRef<string | null>(null)
  React.useEffect(() => {
    const key = `${map.id}:${Math.round(size.w)}`
    if (fitted.current !== key && size.w > 100) { fitted.current = key; fit() }
  }, [map.id, size.w, fit])

  const zoomAt = (px: number, py: number, factor: number) => setView((v) => {
    const s = Math.max(0.3, Math.min(8, v.s * factor))
    return { s, x: px - (px - v.x) * s / v.s, y: py - (py - v.y) * s / v.s }
  })
  const local = (e: { clientX: number; clientY: number }) => {
    const r = box.current!.getBoundingClientRect()
    return { x: e.clientX - r.left, y: e.clientY - r.top }
  }

  React.useEffect(() => {
    const el = box.current
    if (!el) return
    const wheel = (e: WheelEvent) => { e.preventDefault(); const p = local(e); zoomAt(p.x, p.y, Math.exp(-e.deltaY * 0.0015)) }
    el.addEventListener('wheel', wheel, { passive: false })
    return () => el.removeEventListener('wheel', wheel)
  }, [])

  const down = (e: React.PointerEvent) => {
    (e.target as Element).setPointerCapture?.(e.pointerId)
    pointers.current.set(e.pointerId, local(e))
    moved.current = false
    last.current = null
  }
  const move = (e: React.PointerEvent) => {
    if (!pointers.current.has(e.pointerId)) return
    pointers.current.set(e.pointerId, local(e))
    const pts = [...pointers.current.values()]
    const cx = pts.reduce((a, p) => a + p.x, 0) / pts.length, cy = pts.reduce((a, p) => a + p.y, 0) / pts.length
    const d = pts.length > 1 ? Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y) : 0
    const prev = last.current
    if (prev) {
      if (Math.abs(cx - prev.x) + Math.abs(cy - prev.y) > 2) moved.current = true
      setView((v) => ({ ...v, x: v.x + cx - prev.x, y: v.y + cy - prev.y }))
      if (d && prev.d) zoomAt(cx, cy, d / prev.d)
    }
    last.current = { x: cx, y: cy, d }
  }
  const up = (e: React.PointerEvent) => { pointers.current.delete(e.pointerId); last.current = null }

  const doneShare = (m: LiveMarker) => {
    const kinds = Object.values(m.cells)
    return kinds.length ? kinds.filter((s) => s === 'done').length / kinds.length : 0
  }

  return (
    <div ref={box} className={cn('relative touch-none overflow-hidden rounded-2xl select-none', blueprint ? 'bg-[#0a1a33]' : 'bg-white', className)}
      onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={up}
      onClick={(e) => { if (!moved.current && e.target === e.currentTarget) onSelect(null) }}>
      {blueprint && <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(rgba(125,211,252,.06)_1px,transparent_1px),linear-gradient(90deg,rgba(125,211,252,.06)_1px,transparent_1px)] bg-[size:28px_28px]" />}
      <div className={cn('absolute top-0 left-0 origin-top-left will-change-transform', blueprint && 'bg-[#0a1a33]')} style={{ width: cw, height: ch, transform: `translate(${view.x}px, ${view.y}px) scale(${view.s})` }}
        onClick={(e) => { if (!moved.current && e.target === e.currentTarget) onSelect(null) }}>
        {map.image_url ? (
          <img src={map.image_url} alt={`${map.name}: ${map.document.title}`} draggable={false}
            className={cn('pointer-events-none absolute inset-0 size-full', blueprint && 'opacity-90 mix-blend-screen [filter:invert(1)_sepia(1)_saturate(3)_hue-rotate(165deg)_brightness(1.15)]')} />
        ) : <p className="absolute inset-x-0 top-1/2 text-center text-sm text-slate-400">The drawing's picture is not available: the {map.kind === 'foundation' ? 'footings' : 'rooms'} are shown where they are.</p>}
        {map.markers.map((m) => {
          const st = stateFor(m, trade)
          const sel = selected === m.key
          const round = map.kind === 'foundation'
          return (
            <div key={m.key} className="group absolute" style={{ left: m.x * cw, top: m.y * ch, transform: `translate(-50%, -50%) scale(${1 / view.s})`, zIndex: sel ? 30 : m.fresh ? 20 : 10 }}>
              {photos && m.thumbs[0] && (
                <div className="absolute bottom-full left-1/2 mb-1.5 -translate-x-1/2">
                  <img src={m.thumbs[0]} alt="" className="size-10 max-w-none rounded-full border-2 border-white object-cover shadow-lg" />
                  {m.photos > 1 && <span className="absolute -top-1 -right-1 rounded-full bg-sky-500 px-1.5 text-[10px] font-bold text-white">{m.photos}</span>}
                </div>
              )}
              {m.fresh && <span className="pointer-events-none absolute inset-0 animate-ping rounded-full bg-emerald-300/50" />}
              <button type="button" onClick={(e) => { e.stopPropagation(); if (!moved.current) onSelect(sel ? null : m) }}
                className={cn('relative flex items-center gap-1 border font-semibold whitespace-nowrap transition-all duration-500 hover:scale-110',
                  round ? 'size-7 justify-center rounded-full text-[10px]' : 'rounded-full px-2.5 py-1 text-[11px]',
                  (blueprint ? PILL : PILL_PAPER)[st], sel && 'scale-125 ring-4 ring-white/80')}>
                {!round && Object.keys(m.cells).length > 0 && !trade && <Ring value={doneShare(m)} />}
                {m.label}
                {!round && m.photos > 0 && !photos && <span className="ml-0.5 text-[9px] opacity-70">📷{m.photos}</span>}
              </button>
              <div className="pointer-events-none absolute top-full left-1/2 z-40 mt-2 hidden w-52 -translate-x-1/2 rounded-xl border border-white/10 bg-slate-950/95 p-2.5 text-left text-xs text-slate-100 shadow-2xl group-hover:block">
                <p className="text-sm font-semibold">{m.label}</p>
                {m.sub && <p className="text-slate-400">{m.sub}</p>}
                <p className="mt-1">{STATE_WORD[st]}{m.last_work ? ` · ${m.last_work}` : ''}</p>
                {m.updates > 0 && <p className="text-slate-400">{m.updates} update{m.updates > 1 ? 's' : ''}{m.photos ? ` · ${m.photos} photo${m.photos > 1 ? 's' : ''}` : ''}</p>}
              </div>
            </div>
          )
        })}
      </div>
      <div className="absolute right-3 bottom-3 flex flex-col overflow-hidden rounded-xl border border-white/15 bg-slate-950/70 text-white shadow-lg backdrop-blur">
        <button type="button" className="p-2 hover:bg-white/10" aria-label="Zoom in" onClick={() => zoomAt(size.w / 2, size.h / 2, 1.4)}><Plus className="size-4" /></button>
        <button type="button" className="p-2 hover:bg-white/10" aria-label="Zoom out" onClick={() => zoomAt(size.w / 2, size.h / 2, 1 / 1.4)}><Minus className="size-4" /></button>
        <button type="button" className="p-2 hover:bg-white/10" aria-label="Fit the plan" onClick={fit}><Maximize2 className="size-4" /></button>
      </div>
    </div>
  )
}
