import * as React from 'react'
import { DUST_MS, SNAP_MS } from '@/lib/ink'
import { prefersReducedMotion } from '@/lib/timeline'
import { cn } from '@/lib/utils'

// The Live report's dust (WEB-37): a line that gathers out of drifting dust
// into its letters, or crumbles into dust and blows away (the replay's
// "snap"). A canvas over the line draws the text in the line's own font,
// samples its letter pixels, and moves one particle per sample, left to
// right. The real text sits underneath, hidden while the dust works, so
// layout and accessibility never change. Reduced motion: the text, plainly.

export type DustMode = 'still' | 'gather' | 'scatter'

interface Grain {
  x: number
  y: number
  /** Where it drifts from (gather) or to (scatter), relative to x, y. */
  dx: number
  dy: number
  /** 0..1 across the line, so the effect sweeps left to right. */
  order: number
}

const STEP = 2 // sample every 2 css px
const SPREAD = 0.55 // part of the duration the sweep takes
const SIZE = 1.8

function ease(t: number): number {
  return 1 - Math.pow(1 - t, 3)
}

export function DustText({
  text,
  mode,
  delay = 0,
  className,
  onDone,
}: {
  text: string
  mode: DustMode
  delay?: number
  className?: string
  onDone?: () => void
}) {
  const host = React.useRef<HTMLSpanElement>(null)
  const canvas = React.useRef<HTMLCanvasElement>(null)
  // 'shown': real text visible; 'dust': canvas working, text hidden; 'gone': scattered away.
  const [state, setState] = React.useState<'shown' | 'dust' | 'gone'>(mode === 'gather' ? 'dust' : 'shown')
  const done = React.useRef(onDone)
  done.current = onDone

  React.useEffect(() => {
    if (mode === 'still') {
      setState('shown')
      return
    }
    const el = host.current
    const cv = canvas.current
    if (!el || !cv || prefersReducedMotion()) {
      setState(mode === 'gather' ? 'shown' : 'gone')
      done.current?.()
      return
    }
    setState(mode === 'gather' ? 'dust' : 'shown')

    const style = getComputedStyle(el)
    const rect = el.getBoundingClientRect()
    const font = `${style.fontStyle} ${style.fontWeight} ${style.fontSize} ${style.fontFamily}`
    const ctx = cv.getContext('2d')
    const measure = document.createElement('canvas').getContext('2d')
    if (!ctx || !measure) {
      setState(mode === 'gather' ? 'shown' : 'gone')
      done.current?.()
      return
    }
    measure.font = font
    const width = Math.ceil(Math.min(rect.width, measure.measureText(text).width + 2))
    const lineHeight = parseFloat(style.lineHeight) || parseFloat(style.fontSize) * 1.4
    const height = Math.ceil(Math.max(rect.height, lineHeight))
    const fontSize = parseFloat(style.fontSize)

    // The letters, drawn once off screen, become the grains' homes.
    const off = document.createElement('canvas')
    off.width = width
    off.height = height
    const o = off.getContext('2d')!
    o.font = font
    o.textBaseline = 'middle'
    o.fillStyle = '#000'
    o.fillText(text, 0, Math.min(height, lineHeight) / 2 + fontSize * 0.04)
    const pixels = o.getImageData(0, 0, width, height).data
    const grains: Grain[] = []
    for (let y = 0; y < height; y += STEP) {
      for (let x = 0; x < width; x += STEP) {
        if (pixels[(y * width + x) * 4 + 3] > 110) {
          const angle = (Math.random() - 0.65) * 1.4 // mostly right and up, like the snap
          // Scattered dust travels further than gathering dust comes from.
          const dist = (mode === 'scatter' ? 70 : 40) + Math.random() * (mode === 'scatter' ? 240 : 130)
          grains.push({
            x,
            y,
            dx: Math.cos(angle) * dist,
            dy: Math.sin(angle) * dist - 10,
            order: x / Math.max(1, width),
          })
        }
      }
    }

    // The canvas covers the line plus room for the drift.
    const pad = mode === 'scatter' ? 300 : 180
    const dpr = window.devicePixelRatio || 1
    cv.style.left = `${-8}px`
    cv.style.top = `${-pad / 2}px`
    cv.style.width = `${width + pad}px`
    cv.style.height = `${height + pad}px`
    cv.width = Math.ceil((width + pad) * dpr)
    cv.height = Math.ceil((height + pad) * dpr)
    ctx.setTransform(dpr, 0, 0, dpr, 8 * dpr, (pad / 2) * dpr)
    ctx.fillStyle = style.color

    const start = performance.now() + delay
    let frame = 0
    const draw = (now: number) => {
      const t = (now - start) / (mode === 'scatter' ? SNAP_MS : DUST_MS)
      ctx.clearRect(-8, -pad / 2, width + pad, height + pad)
      if (t < 0) {
        frame = requestAnimationFrame(draw)
        return
      }
      for (const g of grains) {
        // Each grain starts a little after the one to its left.
        const local = Math.min(1, Math.max(0, (t - g.order * SPREAD) / (1 - SPREAD)))
        const k = mode === 'gather' ? 1 - ease(local) : ease(local)
        const alpha = mode === 'gather' ? Math.min(1, local * 1.6) : 1 - local
        if (alpha <= 0.01) continue
        ctx.globalAlpha = alpha
        const wobble = Math.sin((g.x + g.y) * 0.3 + t * 6) * 2 * k
        ctx.fillRect(g.x + g.dx * k + wobble, g.y + g.dy * k, SIZE, SIZE)
      }
      ctx.globalAlpha = 1
      if (mode === 'scatter' && t > 0.02) setState((s) => (s === 'shown' ? 'dust' : s))
      if (t < 1) {
        frame = requestAnimationFrame(draw)
      } else {
        ctx.clearRect(-8, -pad / 2, width + pad, height + pad)
        setState(mode === 'gather' ? 'shown' : 'gone')
        done.current?.()
      }
    }
    frame = requestAnimationFrame(draw)
    return () => cancelAnimationFrame(frame)
  }, [text, mode, delay])

  return (
    <span ref={host} className={cn('relative', className)}>
      <span
        className={cn('transition-opacity duration-300', state === 'shown' ? 'opacity-100' : 'opacity-0')}
      >
        {text}
      </span>
      <canvas ref={canvas} aria-hidden="true" className="pointer-events-none absolute" />
    </span>
  )
}
