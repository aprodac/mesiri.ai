import * as React from 'react'
import { Maximize2, Minus, Plus } from 'lucide-react'
import { CHIP_STATE, STATE_WORD, stateFor, type LiveMap, type LiveMarker } from '@/lib/live-maps'
import { cn } from '@/lib/utils'

// DR-10 / DR-11: one drawing page as a live map, shown like a drawing viewer: the sheet on a neutral surround, a
// status chip where each room or footing is. Colours are the status tokens (docs/DESIGN.md §3): green done, blue in
// progress, grey not started. Wheel or pinch to zoom, drag to move; chips keep their size.

interface View { s: number; x: number; y: number }

export function PlanCanvas({ map, trade, photos, selected, onSelect, className }: {
  map: LiveMap
  trade: string | null
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
    const pad = 60
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
  const clear = (e: React.MouseEvent) => { if (!moved.current && e.target === e.currentTarget) onSelect(null) }

  const share = (m: LiveMarker) => {
    const kinds = Object.values(m.cells)
    return kinds.length > 1 ? `${kinds.filter((s) => s === 'done').length}/${kinds.length}` : null
  }

  return (
    <div ref={box} className={cn('relative cursor-grab touch-none overflow-hidden rounded-xl border bg-muted/60 select-none active:cursor-grabbing', className)}
      onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={up} onClick={clear}>
      <div className="absolute top-0 left-0 origin-top-left bg-white shadow-sm ring-1 ring-border will-change-transform"
        style={{ width: cw, height: ch, transform: `translate(${view.x}px, ${view.y}px) scale(${view.s})` }} onClick={clear}>
        {map.image_url ? (
          <img src={map.image_url} alt={`${map.name}: ${map.document.title}`} draggable={false} className="pointer-events-none absolute inset-0 size-full" />
        ) : (
          <p className="absolute inset-x-0 top-1/2 text-center text-sm text-muted-foreground">The drawing's picture is not available. The {map.kind === 'foundation' ? 'footings' : 'rooms'} are shown where they are.</p>
        )}
      </div>
      {/* Chips in screen pixels over the sheet (never scaled with it), so their words stay sharp at any zoom. */}
      <div className="pointer-events-none absolute inset-0">
        {map.markers.map((m) => {
            const st = stateFor(m, trade)
            const sel = selected === m.key
            const round = map.kind === 'foundation'
            const frac = trade ? null : share(m)
            return (
              <div key={m.key} className="group pointer-events-auto absolute" style={{ left: view.x + m.x * cw * view.s, top: view.y + m.y * ch * view.s, transform: 'translate(-50%, -50%)', zIndex: sel ? 30 : 10 }}>
                {photos && m.thumbs[0] && (
                  <div className="absolute bottom-full left-1/2 mb-1 -translate-x-1/2">
                    <img src={m.thumbs[0]} alt="" className="size-9 max-w-none rounded-md border-2 border-background object-cover shadow-sm" />
                    {m.photos > 1 && <span className="absolute -right-1.5 -bottom-1 rounded-full border bg-background px-1 text-[10px] font-medium tabular-nums">{m.photos}</span>}
                  </div>
                )}
                <button type="button" aria-label={`${m.label}: ${STATE_WORD[st]}`} aria-pressed={sel}
                  onClick={(e) => { e.stopPropagation(); if (!moved.current) onSelect(sel ? null : m) }}
                  className={cn('relative flex items-center gap-1 border font-medium whitespace-nowrap shadow-sm transition-colors duration-300 hover:brightness-95',
                    round ? 'size-6 justify-center rounded-full text-[10px]' : 'rounded-md px-1.5 py-0.5 text-[11px]',
                    CHIP_STATE[st], sel && 'ring-2 ring-ring ring-offset-1 ring-offset-background')}>
                  {m.label}
                  {frac && <span className="tabular-nums opacity-75">{frac}</span>}
                  {m.fresh && <span className="absolute -top-1 -right-1 size-2 rounded-full border border-background bg-primary" title="Updated in the last 2 days" />}
                </button>
                <div className="pointer-events-none absolute top-full left-1/2 z-40 mt-1.5 hidden w-48 -translate-x-1/2 rounded-lg border bg-popover p-2.5 text-xs text-popover-foreground shadow-md group-hover:block">
                  <p className="font-semibold">{m.label}</p>
                  {m.sub && <p className="text-muted-foreground">{m.sub}</p>}
                  <p className="mt-1">{STATE_WORD[st]}{m.last_work ? ` · ${m.last_work}` : ''}</p>
                  {m.updates > 0 && <p className="text-muted-foreground">{m.updates} update{m.updates > 1 ? 's' : ''}{m.photos ? `, ${m.photos} photo${m.photos > 1 ? 's' : ''}` : ''}</p>}
                </div>
              </div>
            )
          })}
            </div>
      <div className="absolute right-2.5 bottom-2.5 flex flex-col divide-y overflow-hidden rounded-lg border bg-background shadow-sm">
        <button type="button" className="p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground" title="Zoom in" aria-label="Zoom in" onClick={() => zoomAt(size.w / 2, size.h / 2, 1.4)}><Plus className="size-4" /></button>
        <button type="button" className="p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground" title="Zoom out" aria-label="Zoom out" onClick={() => zoomAt(size.w / 2, size.h / 2, 1 / 1.4)}><Minus className="size-4" /></button>
        <button type="button" className="p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground" title="Fit the plan" aria-label="Fit the plan" onClick={fit}><Maximize2 className="size-4" /></button>
      </div>
    </div>
  )
}
