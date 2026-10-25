import * as React from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Mic, Monitor } from 'lucide-react'
import {
  fetchBranding,
  fetchFactSourcesApi,
  fetchSiteDayApi,
  fetchSiteDaysApi,
  type FactSources,
  type ReviewItem,
  type SiteDayDetail,
} from '@/lib/api'
import { useAuth } from '@/lib/AuthContext'
import { localIsoDate, longDate, siteDayPath } from '@/lib/site-day'
import { prefersReducedMotion } from '@/lib/timeline'
import { cn } from '@/lib/utils'
import { DUST_MS, inkDuration, SNAP_MS, THREAD_MS } from '@/lib/ink'
import { keyValue, readingLines, rowLines } from '@/lib/live-reading'
import { MesiriWordmark } from '@/components/brand/mesiri-logo'
import { WhatsAppIcon } from '@/components/brand/whatsapp-icon'
import { Label, WordsIn } from '@/components/onboarding/conversation'
import { CountTo, Ink } from '@/components/live/ink'
import { DustText } from '@/components/live/dust'
import { TellMesiri } from '@/components/tell-mesiri/tell-mesiri'

// The Live report (WEB-37): the day's report writing itself as the site's
// messages come in, and Mesiri seen reading each one. Left, a message
// arrives (WhatsApp or the web); under it Mesiri reads: the English of a
// voice note, the fields it took out (as the AI stored them), then a chip
// per fact. Each chip flies across into the report, where its line gathers
// out of dust and its number lands: the manpower total slams in, a
// quantity gets a highlighter sweep. Re-reads the day every few seconds.
// "Replay the day" snaps the report to dust and rebuilds it from its
// messages, in order. Read-only: it shows what Mesiri saved.

const POLL_MS = 3_000
const FLY_MS = 750
/** How long a landed number keeps its highlight. */
const LANDED_MS = 7_000
const SUB_LAG_MS = 350

type Section = 'labour' | 'work' | 'materials' | 'issues'
const SECTIONS: { key: Exclude<Section, 'labour'>; title: string }[] = [
  { key: 'work', title: 'Work done' },
  { key: 'materials', title: 'Materials' },
  { key: 'issues', title: 'Issues' },
]

type Message = FactSources['messages'][number]
type Reading = FactSources['readings'][number]
interface Source {
  message: Message | null
  reading: Reading | null
}

interface Chip {
  key: string
  label: string
  flown: boolean
}

interface Thinking {
  step: 'reading' | 'english' | 'fields' | 'chips' | 'done'
  english: string | null
  lines: string[]
  chips: Chip[]
}

interface FeedMessage {
  id: string
  type: string
  text: string
  at: string | null
  sender: string | null
  /** 'whatsapp', or 'dashboard' when told on the web (Tell Mesiri). */
  source: string
  /** Arrived while watching (animates), rather than already there. */
  fresh: boolean
  think: Thinking | null
}

const factKey = (item: ReviewItem) => `${item.fact_type}:${item.id}`
const sleep = (ms: number) => new Promise((resolve) => window.setTimeout(resolve, ms))

function clock(iso: string | null): string {
  return iso ? new Date(iso).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' }) : ''
}

function kindLabel(type: string): string {
  if (type.includes('voice') || type.includes('audio')) return 'Voice note'
  if (type.includes('image') || type.includes('photo')) return 'Photo'
  if (type.includes('document')) return 'Document'
  return 'Message'
}

function chipLabel(item: ReviewItem, headcount: number | undefined): string {
  if (item.section === 'labour') return headcount ? `${headcount} ${headcount === 1 ? 'worker' : 'workers'}` : item.title || 'Workers'
  const value = keyValue(item)
  return [rowLines(item).main, value].filter(Boolean).join(' · ')
}

/** A number or tag that has just landed: it slams in and a highlighter sweeps under it. */
function Landed({ active, children, className }: { active: boolean; children: React.ReactNode; className?: string }) {
  return (
    <span
      className={cn('inline-block rounded-[2px] px-1 transition-[background-color] duration-[1500ms]', className)}
      style={
        active && !prefersReducedMotion()
          ? {
              animation: 'live-slam 700ms cubic-bezier(.2,.9,.3,1.2) both, live-marker 600ms 350ms ease-out both',
              backgroundImage: 'linear-gradient(transparent 52%, color-mix(in srgb, var(--primary) 32%, transparent) 52%)',
              backgroundRepeat: 'no-repeat',
            }
          : undefined
      }
    >
      {children}
    </span>
  )
}

/** The thread from a chip on the left to where its fact lands on the right. */
function Thread({ from, to }: { from: DOMRect; to: DOMRect }) {
  const x1 = from.right
  const y1 = from.top + from.height / 2
  const x2 = to.left - 6
  const y2 = to.top + Math.min(14, to.height / 2)
  const dx = Math.max(40, (x2 - x1) / 2)
  return (
    <svg className="pointer-events-none absolute inset-0 hidden h-full w-full overflow-visible lg:block" aria-hidden="true">
      <path
        d={`M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`}
        pathLength={1}
        strokeDasharray={1}
        fill="none"
        strokeWidth={1.5}
        className="stroke-primary"
        style={{ animation: `live-draw ${THREAD_MS}ms cubic-bezier(.6,0,.2,1) both` }}
      />
    </svg>
  )
}

/** A copy of a chip flying from the message to the report. */
function Flyer({ label, from, to }: { label: string; from: DOMRect; to: DOMRect }) {
  const [go, setGo] = React.useState(false)
  React.useLayoutEffect(() => {
    const frame = requestAnimationFrame(() => setGo(true))
    return () => cancelAnimationFrame(frame)
  }, [])
  const dx = to.left - from.left
  const dy = to.top + to.height / 2 - (from.top + from.height / 2)
  return (
    <span
      aria-hidden="true"
      className="pointer-events-none fixed z-50 whitespace-nowrap bg-primary px-2.5 py-1 text-[12.5px] font-semibold text-primary-foreground shadow-lg"
      style={{
        left: from.left,
        top: from.top,
        transform: go ? `translate(${dx}px, ${dy}px) scale(0.92)` : 'none',
        opacity: go ? 0.15 : 1,
        transition: `transform ${FLY_MS}ms cubic-bezier(.6,0,.2,1), opacity ${FLY_MS}ms ease-in`,
      }}
    >
      {label}
    </span>
  )
}

function ThinkingPanel({
  think,
  chipRef,
}: {
  think: Thinking
  chipRef: (key: string, el: HTMLElement | null) => void
}) {
  const reading = think.step === 'reading'
  return (
    <div className="mt-3 grid gap-2 border-l-2 border-primary/50 pl-3 animate-in fade-in duration-500 motion-reduce:animate-none">
      <Label className="flex items-center gap-2 text-primary">
        <span className={cn('size-1.5 rounded-full bg-primary', reading && 'animate-ping')} aria-hidden="true" />
        Mesiri · {reading ? 'reading' : think.step === 'done' ? 'understood' : 'understanding'}
        {reading && <span className="animate-pulse">…</span>}
      </Label>
      {think.english && think.step !== 'reading' && (
        <div className="grid gap-0.5">
          <Label>In English</Label>
          <Ink text={`“${think.english}”`} writing={think.step === 'english'} className="text-[15px] leading-relaxed text-foreground/85" />
        </div>
      )}
      {think.lines.length > 0 && (
        <ul className="m-0 grid list-none gap-0.5 p-0 font-mono text-[12px] text-foreground/70">
          {think.lines.map((line, i) => (
            <li key={i} className="animate-in fade-in slide-in-from-left-1 duration-300 motion-reduce:animate-none">
              {line}
            </li>
          ))}
        </ul>
      )}
      {think.chips.length > 0 && (
        <div className="flex flex-wrap gap-2 pt-1">
          {think.chips.map((chip, i) => (
            <span
              key={chip.key}
              ref={(el) => chipRef(chip.key, el)}
              className={cn(
                'px-2.5 py-1 text-[12.5px] font-semibold transition-all duration-500 animate-in zoom-in-75 fade-in fill-mode-both motion-reduce:animate-none',
                chip.flown ? 'border border-foreground/25 bg-transparent text-foreground/45' : 'bg-foreground text-background',
              )}
              style={{ animationDelay: `${i * 140}ms` }}
            >
              {chip.flown && '✓ '}
              {chip.label}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

function Row({
  item,
  writing,
  snapping,
  landed,
  innerRef,
  valueRef,
}: {
  item: ReviewItem
  writing: boolean
  snapping: boolean
  landed: boolean
  innerRef?: (el: HTMLElement | null) => void
  valueRef?: (el: HTMLElement | null) => void
}) {
  const { main, sub } = rowLines(item)
  const value = keyValue(item)
  const mode = snapping ? 'scatter' : writing ? 'gather' : 'still'
  return (
    <li
      ref={innerRef}
      className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-x-4 border-b border-black/10 py-3 last:border-b-0"
      style={writing && !prefersReducedMotion() ? { animation: 'live-glow 3s ease-out both' } : undefined}
    >
      <span className="min-w-0">
        <DustText text={main} mode={mode} delay={writing ? THREAD_MS : 0} className="block text-[15px] font-semibold" />
        {sub && (
          <DustText
            text={sub}
            mode={mode}
            delay={writing ? THREAD_MS + SUB_LAG_MS : 80}
            className="block text-[12.5px] text-black/55"
          />
        )}
      </span>
      <span
        className={cn(
          'flex flex-col items-end gap-1 transition-opacity duration-700',
          snapping && 'opacity-0',
          writing && !landed && 'opacity-0',
        )}
      >
        {value && (
          <span ref={valueRef}>
            <Landed active={landed} className="text-[18px] font-semibold tabular-nums">
              {value}
            </Landed>
          </span>
        )}
        {item.review === 'draft' && (
          <span className="font-mono text-[10px] uppercase tracking-[0.08em] text-primary">Draft</span>
        )}
      </span>
    </li>
  )
}

export default function LivePage() {
  const { me } = useAuth()
  const [params, setParams] = useSearchParams()
  const [today] = React.useState(() => localIsoDate(new Date()))
  const date = params.get('date') || today

  const days = useQuery({ queryKey: ['live-site-days', date], queryFn: () => fetchSiteDaysApi(date) })
  const sites = days.data?.items ?? []
  const siteId = params.get('site') || sites[0]?.site_id || ''
  const site = sites.find((s) => s.site_id === siteId)

  const detail = useQuery({
    queryKey: ['live-site-day', siteId, date],
    queryFn: () => fetchSiteDayApi(siteId, date),
    enabled: !!siteId,
    refetchInterval: POLL_MS,
  })
  const branding = useQuery({ queryKey: ['company-branding'], queryFn: fetchBranding, retry: false, staleTime: 10 * 60_000 })

  // What the sheet shows: facts written so far, the one being written, the
  // ones just landed (highlighted), and labour as of the last labour line.
  const [written, setWritten] = React.useState<Set<string>>(new Set())
  const [writing, setWriting] = React.useState<string | null>(null)
  const [landed, setLanded] = React.useState<Set<string>>(new Set())
  const [labour, setLabour] = React.useState<SiteDayDetail['report']['labour'] | null>(null)
  const [feed, setFeed] = React.useState<FeedMessage[]>([])
  const [thread, setThread] = React.useState<{ chip: string; target: string } | null>(null)
  const [flyer, setFlyer] = React.useState<{ id: number; label: string; from: DOMRect; to: DOMRect } | null>(null)
  const [, redraw] = React.useReducer((n: number) => n + 1, 0)
  // Tell Mesiri right here; what's saved writes itself in like any message.
  const [telling, setTelling] = React.useState(params.get('tell') === '1')
  const [snapping, setSnapping] = React.useState(false)

  const known = React.useRef<Set<string> | null>(null)
  const queue = React.useRef<ReviewItem[]>([])
  const running = React.useRef(false)
  const alive = React.useRef(true)
  const generation = React.useRef(0)
  const sources = React.useRef(new Map<string, Source>())
  const feedIds = React.useRef(new Set<string>())
  const latest = React.useRef<SiteDayDetail | undefined>(undefined)
  latest.current = detail.data

  const stage = React.useRef<HTMLDivElement>(null)
  const chipEls = React.useRef(new Map<string, HTMLElement>())
  const targetEls = React.useRef(new Map<string, HTMLElement>())
  const setChipEl = React.useCallback((key: string, el: HTMLElement | null) => {
    if (el) chipEls.current.set(key, el)
    else chipEls.current.delete(key)
  }, [])

  React.useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])

  const sourceOf = React.useCallback(async (item: ReviewItem): Promise<Source> => {
    const key = factKey(item)
    if (!sources.current.has(key)) {
      try {
        const res = await fetchFactSourcesApi(item.fact_type, item.id)
        sources.current.set(key, { message: res.messages[0] ?? null, reading: res.readings[0] ?? null })
      } catch {
        sources.current.set(key, { message: null, reading: null })
      }
    }
    return sources.current.get(key)!
  }, [])

  const toFeed = (msg: Message, fresh: boolean): FeedMessage => ({
    id: msg.id,
    type: msg.type,
    text: (msg.text || '').trim() || kindLabel(msg.type),
    at: msg.received_at,
    sender: msg.sender_name,
    source: msg.source || 'whatsapp',
    fresh,
    think: null,
  })

  const think = (messageId: string, change: (t: Thinking) => Thinking) =>
    setFeed((all) =>
      all.map((m) =>
        m.id === messageId ? { ...m, think: change(m.think ?? { step: 'reading', english: null, lines: [], chips: [] }) } : m,
      ),
    )

  const land = (key: string) => {
    setLanded((all) => new Set(all).add(key))
    window.setTimeout(() => {
      setLanded((all) => {
        const next = new Set(all)
        next.delete(key)
        return next
      })
    }, LANDED_MS)
  }

  /** One message and the facts taken from it: read, understood, landed. */
  const playMessage = React.useCallback(
    async (group: ReviewItem[], gen: number) => {
      const still = prefersReducedMotion()
      const source = await sourceOf(group[0])
      const msg = source.message
      const live = () => alive.current && gen === generation.current
      const headcount = latest.current?.report.labour.headcount

      if (msg) {
        if (!feedIds.current.has(msg.id)) {
          feedIds.current.add(msg.id)
          setFeed((all) => [...all, toFeed(msg, true)])
        }
        if (!still) {
          // The message's words arrive, then Mesiri reads.
          await sleep(Math.min(2600, 900 + (msg.text ?? '').length * 10))
          think(msg.id, (t) => ({ ...t, step: 'reading' }))
          await sleep(1100)
          if (!live()) return
          const english = msg.translated_text?.trim() || null
          if (english) {
            think(msg.id, (t) => ({ ...t, step: 'english', english }))
            await sleep(inkDuration(`“${english}”`) + 400)
            if (!live()) return
          }
          think(msg.id, (t) => ({ ...t, step: 'fields' }))
          const lines: string[] = []
          for (const item of group) {
            const reading = (await sourceOf(item)).reading
            for (const line of readingLines(reading?.extracted)) if (!lines.includes(line)) lines.push(line)
          }
          for (const line of lines.slice(0, 8)) {
            think(msg.id, (t) => ({ ...t, lines: [...t.lines, line] }))
            await sleep(230)
          }
          if (!live()) return
        }
        think(msg.id, (t) => ({
          ...t,
          step: 'chips',
          chips: group.map((item) => ({ key: factKey(item), label: chipLabel(item, headcount), flown: false })),
        }))
        if (!still) await sleep(700 + group.length * 140)
      }

      for (const item of group) {
        if (!live()) return
        const key = factKey(item)
        const isLabour = item.section === 'labour'
        setWritten((all) => new Set(all).add(key))
        setWriting(key)
        if (!still) {
          await sleep(80)
          const chip = chipEls.current.get(key)
          const target = targetEls.current.get(isLabour ? 'labour-total' : `${key}:value`) ?? targetEls.current.get(key)
          if (chip && target) {
            setFlyer({ id: Date.now(), label: chipLabel(item, headcount), from: chip.getBoundingClientRect(), to: target.getBoundingClientRect() })
            setThread({ chip: key, target: isLabour ? 'labour-total' : key })
            await sleep(FLY_MS)
            setFlyer(null)
          }
        }
        if (isLabour) setLabour(latest.current?.report.labour ?? null)
        land(key)
        if (msg) think(msg.id, (t) => ({ ...t, chips: t.chips.map((c) => (c.key === key ? { ...c, flown: true } : c)) }))
        if (!still) {
          const { sub } = rowLines(item)
          await sleep(isLabour ? 1600 : DUST_MS + (sub ? SUB_LAG_MS : 0) + 700)
          setThread(null)
        }
        setWriting(null)
        if (!still) await sleep(350)
      }
      if (msg) think(msg.id, (t) => ({ ...t, step: 'done' }))
    },
    [sourceOf],
  )

  // Plays the queue a message at a time: every fact a message gave lands together.
  const play = React.useCallback(async () => {
    if (running.current) return
    running.current = true
    const gen = generation.current
    while (queue.current.length && alive.current && gen === generation.current) {
      await Promise.all(queue.current.map(sourceOf))
      if (gen !== generation.current) break
      const first = queue.current[0]
      const id = sources.current.get(factKey(first))?.message?.id ?? `none:${factKey(first)}`
      const group = queue.current.filter(
        (item) => (sources.current.get(factKey(item))?.message?.id ?? `none:${factKey(item)}`) === id,
      )
      queue.current = queue.current.filter((item) => !group.includes(item))
      // Manpower first, as a report reads.
      group.sort((a, b) => Number(b.section === 'labour') - Number(a.section === 'labour'))
      await playMessage(group, gen)
      if (!prefersReducedMotion()) await sleep(600)
    }
    // A replay started meanwhile owns the flag now.
    if (gen === generation.current) running.current = false
  }, [sourceOf, playMessage])

  // New facts from the day's re-read join the queue; the first read is
  // taken as already written (with its messages in the feed, unanimated).
  React.useEffect(() => {
    const data = detail.data
    if (!data) return
    if (known.current === null) {
      known.current = new Set(data.items.map(factKey))
      setWritten(new Set(known.current))
      setLabour(data.report.labour)
      void Promise.all(data.items.map(sourceOf)).then((all) => {
        const seen = new Map<string, FeedMessage>()
        for (const { message } of all) {
          if (!message || seen.has(message.id)) continue
          const english = message.translated_text?.trim() || null
          seen.set(message.id, {
            ...toFeed(message, false),
            think: english ? { step: 'done', english, lines: [], chips: [] } : null,
          })
        }
        feedIds.current = new Set(seen.keys())
        setFeed([...seen.values()].sort((a, b) => (a.at ?? '').localeCompare(b.at ?? '')))
      })
      return
    }
    const fresh = data.items.filter((item) => !known.current!.has(factKey(item)))
    if (fresh.length === 0) return
    fresh.forEach((item) => known.current!.add(factKey(item)))
    queue.current.push(...fresh)
    void play()
  }, [detail.data, play, sourceOf])

  // A new site or day starts over.
  React.useEffect(() => {
    generation.current++
    known.current = null
    queue.current = []
    feedIds.current = new Set()
    setWritten(new Set())
    setFeed([])
    setLabour(null)
    setThread(null)
    setFlyer(null)
    setWriting(null)
    setLanded(new Set())
  }, [siteId, date])

  /** The demo: the report snaps to dust, then every line comes back from its message, in order. */
  const replay = async () => {
    const data = latest.current
    if (!data) return
    generation.current++
    running.current = false
    queue.current = []
    setThread(null)
    setFlyer(null)
    setWriting(null)
    if (!prefersReducedMotion() && written.size > 0) {
      setSnapping(true)
      await sleep(SNAP_MS + 500)
    }
    setSnapping(false)
    setWritten(new Set())
    setLanded(new Set())
    feedIds.current = new Set()
    setFeed([])
    setLabour({ ...data.report.labour, headcount: 0, trades: [] })
    const withTimes = await Promise.all(data.items.map(async (item) => ({ item, src: await sourceOf(item) })))
    withTimes.sort((a, b) => (a.src.message?.received_at ?? '9').localeCompare(b.src.message?.received_at ?? '9'))
    queue.current = withTimes.map((x) => x.item)
    await sleep(500)
    void play()
  }

  // The thread is measured after the frame that placed both ends.
  React.useLayoutEffect(() => {
    if (thread) redraw()
  }, [thread])
  React.useEffect(() => {
    const onResize = () => redraw()
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  const box = stage.current?.getBoundingClientRect()
  const fromEl = thread ? chipEls.current.get(thread.chip) : undefined
  const toEl = thread ? targetEls.current.get(thread.target) : undefined
  const rel = (r: DOMRect) => new DOMRect(r.x - (box?.x ?? 0), r.y - (box?.y ?? 0), r.width, r.height)

  const items = detail.data?.items ?? []
  const shown = (section: Section) => items.filter((i) => i.section === section && written.has(factKey(i)))
  const company = branding.data?.letterhead_name || branding.data?.company_name || me?.org_name || me?.organization_name || 'Your company'
  const frozen = ['approved', 'published'].includes(detail.data?.day?.status ?? '')
  const lastRead = detail.dataUpdatedAt ? new Date(detail.dataUpdatedAt).toLocaleTimeString('en-GB') : null
  const labourLanding = [...landed].some((k) => k.startsWith('labour'))

  return (
    <div className="min-h-svh bg-background px-4 pb-16 sm:px-8 lg:px-12">
      <div className="mx-auto max-w-[1280px]">
        <header className="flex flex-wrap items-center justify-between gap-x-6 gap-y-3 pt-6 pb-4">
          <div className="flex items-baseline gap-4">
            <MesiriWordmark className="text-lg" />
            <Label className="flex items-center gap-2">
              <span className="relative flex size-2" aria-hidden="true">
                <span className="absolute inline-flex size-full animate-ping rounded-full bg-primary opacity-60 motion-reduce:animate-none" />
                <span className="relative inline-flex size-2 rounded-full bg-primary" />
              </span>
              Live{lastRead ? ` · read ${lastRead}` : ''}
            </Label>
          </div>
          <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
            {sites.length > 1 && (
              <select
                aria-label="Site"
                value={siteId}
                onChange={(e) => setParams({ site: e.target.value, ...(params.get('date') ? { date } : {}) })}
                className="h-8 border border-foreground/30 bg-background px-2 text-sm"
              >
                {sites.map((s) => (
                  <option key={s.site_id} value={s.site_id}>
                    {s.site_name}
                  </option>
                ))}
              </select>
            )}
            <button
              type="button"
              onClick={() => setTelling((t) => !t)}
              aria-expanded={telling}
              className={cn(
                'flex items-center gap-2 border border-foreground px-4 py-2 text-sm font-medium',
                telling ? 'bg-foreground text-background' : 'hover:bg-foreground hover:text-background',
              )}
            >
              <Mic className="size-4" /> Tell Mesiri
            </button>
            <button
              type="button"
              onClick={() => void replay()}
              disabled={!detail.data || items.length === 0}
              className="bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-40"
            >
              Replay the day
            </button>
            {siteId && (
              <Link to={siteDayPath(siteId, date)} className="border-b border-foreground font-mono text-[11px] uppercase tracking-[0.06em]">
                Review
              </Link>
            )}
            <Link to="/today" className="border-b border-foreground font-mono text-[11px] uppercase tracking-[0.06em]">
              Exit
            </Link>
          </div>
        </header>
        <div className="h-px bg-foreground" />

        {days.isLoading ? (
          <p className="py-10 text-sm text-muted-foreground">Loading…</p>
        ) : !siteId ? (
          <p className="py-10">No site yet. Add one on Projects &amp; Sites, then its day shows here.</p>
        ) : (
          <div ref={stage} className="relative grid gap-10 pt-8 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:gap-16">
            {/* From site, and Mesiri reading it */}
            <section aria-label="From site" className="min-w-0">
              {telling && (
                <div className="mb-8 border border-foreground px-4 py-4 animate-in fade-in slide-in-from-top-2 duration-300 motion-reduce:animate-none">
                  <Label className="block pb-3">Tell Mesiri · speak or type, and watch it land in the report</Label>
                  <TellMesiri compact />
                </div>
              )}
              <Label>From site · {site?.site_name ?? ''}</Label>
              <ol
                className={cn('mt-4 grid gap-6 transition-[opacity,filter,transform] duration-1000', snapping && 'translate-x-3 opacity-0 blur-[3px]')}
                aria-live="polite"
              >
                {feed.length === 0 && <li className="text-sm text-muted-foreground">Waiting for the first message from site…</li>}
                {feed.slice(-5).map((m) => (
                  <li
                    key={m.id}
                    className={cn(
                      'grid gap-1.5 border-l-2 pl-4 transition-colors duration-700',
                      m.think && m.think.step !== 'done' ? 'border-primary' : 'border-foreground/15',
                      m.fresh && 'animate-in fade-in slide-in-from-left-2 duration-500 motion-reduce:animate-none',
                    )}
                  >
                    <Label className="flex items-center gap-2">
                      {m.source === 'dashboard' ? (
                        <Monitor className="size-3.5 text-foreground" aria-label="From the Mesiri dashboard" />
                      ) : (
                        <WhatsAppIcon className="size-3.5 text-[#25D366]" />
                      )}
                      <span>
                        {[clock(m.at), m.sender, kindLabel(m.type), m.source === 'dashboard' ? 'Mesiri web' : 'WhatsApp']
                          .filter(Boolean)
                          .join(' · ')}
                      </span>
                    </Label>
                    {m.fresh ? (
                      <WordsIn text={m.text} className="text-[16px] leading-relaxed" />
                    ) : (
                      <p className="m-0 text-[16px] leading-relaxed text-foreground/80">{m.text}</p>
                    )}
                    {m.think && (m.fresh || m.think.english) && <ThinkingPanel think={m.think} chipRef={setChipEl} />}
                  </li>
                ))}
              </ol>
            </section>

            {/* The report */}
            <section aria-label="Daily progress report" className="min-w-0">
              <div className="mx-auto max-w-[720px] border border-black/15 bg-white px-6 pt-6 pb-5 text-[#1a1d21] shadow-[0_20px_50px_-30px_rgba(0,0,0,0.35)] sm:px-9 sm:pt-8">
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <div className="flex items-center gap-3">
                    {branding.data?.logo_url ? (
                      <img src={branding.data.logo_url} alt="" className="h-10 w-auto max-w-[140px] object-contain" />
                    ) : (
                      <span className="grid size-10 place-items-center bg-[#1a1d21] font-brand text-[12px] text-white">
                        {company
                          .split(/\s+/)
                          .slice(0, 2)
                          .map((w) => w[0])
                          .join('')
                          .toUpperCase()}
                      </span>
                    )}
                    <span className="text-[16px] font-semibold">{company}</span>
                  </div>
                  <div className="text-right text-[12px] leading-snug text-black/55">
                    <b className="block text-[13px] font-semibold text-black">
                      Daily Progress Report{detail.data?.day?.code ? ` · ${detail.data.day.code}` : ''}
                    </b>
                    {site?.site_name}
                    {site?.project_name && site.project_name !== site.site_name ? `, ${site.project_name}` : ''}
                    <br />
                    {longDate(date)}
                  </div>
                </div>
                <div className="mt-4 h-[3px]" style={{ background: branding.data?.brand_color || 'var(--primary)' }} />

                {/* Manpower */}
                <div
                  ref={(el) => {
                    if (el) targetEls.current.set('labour', el)
                  }}
                  className={cn('mt-6 transition-[opacity,filter,transform] duration-1000', snapping && 'translate-x-3 opacity-0 blur-[3px]')}
                  style={labourLanding && !prefersReducedMotion() ? { animation: 'live-glow 3s ease-out both' } : undefined}
                >
                  <div className="flex items-baseline justify-between border-b border-black/80 pb-1.5">
                    <span className="font-mono text-[11px] uppercase tracking-[0.08em] text-black/60">Manpower</span>
                    <span className="flex items-baseline gap-1.5 text-[13px]">
                      Total
                      <span
                        ref={(el) => {
                          if (el) targetEls.current.set('labour-total', el)
                        }}
                        className="inline-block rounded-full"
                        style={labourLanding && !prefersReducedMotion() ? { animation: 'live-ring 900ms 300ms ease-out 2' } : undefined}
                      >
                        <Landed active={labourLanding} className="text-[26px] font-semibold leading-none">
                          <CountTo value={labour?.headcount ?? 0} />
                        </Landed>
                      </span>
                    </span>
                  </div>
                  {labour && labour.trades.length > 0 ? (
                    <ul className="m-0 flex list-none flex-wrap gap-x-6 gap-y-1 p-0 pt-2.5 text-[14px]">
                      {labour.trades.map((t) => (
                        <li key={t.trade} className="animate-in fade-in duration-500 motion-reduce:animate-none">
                          {t.trade} <CountTo value={t.headcount} className="font-semibold" />
                        </li>
                      ))}
                    </ul>
                  ) : labour && labour.headcount > 0 ? (
                    // A headcount without trades ("5 people came"): say it, don't say nobody.
                    <p className="m-0 pt-2.5 text-[14px] animate-in fade-in duration-500 motion-reduce:animate-none">
                      <CountTo value={labour.headcount} className="font-semibold" /> {labour.headcount === 1 ? 'worker' : 'workers'} on site
                    </p>
                  ) : (
                    <p className="m-0 pt-2.5 text-[13px] text-black/35">No one reported yet</p>
                  )}
                </div>

                {SECTIONS.map(({ key, title }) => {
                  const rows = shown(key)
                  return (
                    <div key={key} className="mt-6">
                      <div className="flex items-baseline justify-between border-b border-black/80 pb-1.5">
                        <span className="font-mono text-[11px] uppercase tracking-[0.08em] text-black/60">{title}</span>
                        <span className="font-mono text-[11px] tabular-nums text-black/45">
                          <CountTo value={rows.length} />
                        </span>
                      </div>
                      {rows.length === 0 ? (
                        <p className="m-0 pt-2.5 text-[13px] text-black/35">Nothing yet</p>
                      ) : (
                        <ul className="m-0 list-none p-0">
                          {rows.map((item) => {
                            const k = factKey(item)
                            return (
                              <Row
                                key={k}
                                item={item}
                                writing={writing === k}
                                snapping={snapping}
                                landed={landed.has(k)}
                                innerRef={(el) => {
                                  if (el) targetEls.current.set(k, el)
                                  else targetEls.current.delete(k)
                                }}
                                valueRef={(el) => {
                                  if (el) targetEls.current.set(`${k}:value`, el)
                                  else targetEls.current.delete(`${k}:value`)
                                }}
                              />
                            )
                          })}
                        </ul>
                      )}
                    </div>
                  )
                })}

                <div className="mt-8 flex items-end justify-between gap-4 border-t border-black/10 pt-3">
                  <span className="font-mono text-[11px] text-black/45">
                    {feed.length} {feed.length === 1 ? 'message' : 'messages'} from site · made by Mesiri
                  </span>
                  <span
                    className={cn(
                      'rotate-[-6deg] border-2 px-2 py-0.5 font-brand text-[11px] tracking-[0.08em]',
                      frozen ? 'border-emerald-700 text-emerald-700' : 'border-primary text-primary',
                    )}
                  >
                    {frozen ? 'CONFIRMED' : 'LIVE DRAFT'}
                  </span>
                </div>
              </div>
            </section>

            {thread && box && fromEl && toEl && (
              <Thread from={rel(fromEl.getBoundingClientRect())} to={rel(toEl.getBoundingClientRect())} />
            )}
          </div>
        )}
      </div>
      {flyer && <Flyer key={flyer.id} label={flyer.label} from={flyer.from} to={flyer.to} />}
    </div>
  )
}
