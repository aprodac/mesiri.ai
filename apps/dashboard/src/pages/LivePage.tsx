import * as React from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, Mic, Monitor } from 'lucide-react'
import {
  fetchBranding,
  fetchFactSourcesApi,
  fetchSiteDayApi,
  fetchSiteDaysApi,
  fetchSiteQuestionsApi,
  type FactSources,
  type ReviewItem,
  type SiteDayDetail,
  type SiteQuestion,
} from '@/lib/api'
import { useAuth } from '@/lib/AuthContext'
import { localIsoDate, longDate, siteDayPath } from '@/lib/site-day'
import { prefersReducedMotion } from '@/lib/timeline'
import { cn, formatClock } from '@/lib/utils'
import { DUST_MS, inkDuration, SNAP_MS, THREAD_MS } from '@/lib/ink'
import { keyValue, readingLines, rowLines } from '@/lib/live-reading'
import { MesiriWordmark } from '@/components/brand/mesiri-logo'
import { WhatsAppIcon } from '@/components/brand/whatsapp-icon'
import { Label, WordsIn } from '@/components/onboarding/conversation'
import { CountTo, Ink } from '@/components/live/ink'
import { DustText } from '@/components/live/dust'
import { TellMesiri } from '@/components/tell-mesiri/tell-mesiri'
import { LIVE_MODULES, ModuleRail, moduleOf, useCinematicGo, type LiveModule, type ModuleSection } from '@/components/live/modules'
import { useModuleEnabled } from '@/lib/modules'
import { AnswerSheet, answerTitle, questionChip, type AnswerTarget } from '@/components/live/answer'
import { Finale } from '@/components/live/finale'

// The Live report (WEB-37): the day's report writing itself as the site's
// messages come in, and Mesiri seen reading each one. Left, a message
// arrives (WhatsApp or the web); under it Mesiri reads: the English of a
// voice note, the fields it took out (as the AI stored them), then a chip
// per fact. Each chip flies across into the report, where its line gathers
// out of dust and its number lands: the manpower total slams in, a
// quantity gets a highlighter sweep. Re-reads the day every few seconds.
// "Replay the day" snaps the report to dust and rebuilds it from its
// messages, in order. Then each fact travels on along a second thread to
// the module that keeps it (Labour, Site log, Materials, Issues, on the
// right); a line, the manpower block or a module opens that module with a
// cinematic cut. A question asked on WhatsApp ("stock at Tower A?") is read
// the same way, then the sheet turns over to the answer, from the same
// records, with Mesiri's reply under the question. Above the sheet: what the
// report is still waiting for, ticking off as lines land, and the time left
// before it sends. A line Mesiri flagged (more used than in stock, a likely
// repeat) shudders and says so. When the report goes out, it folds into its
// PDF and drops into WhatsApp (the finale). Read-only: it shows what Mesiri
// saved and said.

const POLL_MS = 3_000
const FLY_MS = 750
/** How long a landed number keeps its highlight. */
const LANDED_MS = 7_000
const SUB_LAG_MS = 350
/** How long an answer stays turned over before the report comes back. */
const ANSWER_MS = 12_000
const FLIP_MS = 1_100

type Section = ModuleSection
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
  /** Mesiri flagged it. */
  warn?: boolean
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
  /** A question's answer, as Mesiri sent it; shown once given. */
  reply?: string | null
  replied?: boolean
}

const factKey = (item: ReviewItem) => `${item.fact_type}:${item.id}`
const questionKey = (q: SiteQuestion) => `question:${q.id}`

/** The viewer's day for `date` (YYYY-MM-DD), as the questions endpoint takes it. */
function dayWindow(date: string): [Date, Date] {
  const [y, m, d] = date.split('-').map(Number)
  return [new Date(y, m - 1, d), new Date(y, m - 1, d + 1)]
}
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

/** What Mesiri noticed about a line (its review flags), in plain words; null when nothing. */
function noticeOf(item: ReviewItem, report: SiteDayDetail['report'] | undefined): string | null {
  if (item.flags?.includes('beyond_stock')) {
    const name = (item.title ?? '').toLowerCase()
    const line = report?.materials.find((m) => (m.material_name ?? '').toLowerCase() === name)
    const left = line?.closing != null ? ` The stock would be ${Number(line.closing)} ${line.unit ?? ''}.` : ''
    return `More used than was in stock.${left} Check it before confirming.`
  }
  if (item.flags?.includes('possible_duplicate')) return 'This looks like a repeat of an earlier message. Check it before confirming.'
  return null
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
/** A thread between two places; `travel` sends a dot along it (the relay to a module). */
function Thread({ from, to, travel = false, className = 'lg:block' }: { from: DOMRect; to: DOMRect; travel?: boolean; className?: string }) {
  const x1 = from.right
  const y1 = from.top + Math.min(travel ? 18 : from.height / 2, from.height / 2)
  const x2 = to.left - 6
  const y2 = to.top + Math.min(travel ? 22 : 14, to.height / 2)
  const dx = Math.max(40, (x2 - x1) / 2)
  const d = `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`
  return (
    <svg className={cn('pointer-events-none absolute inset-0 hidden h-full w-full overflow-visible', className)} aria-hidden="true">
      <path
        d={d}
        pathLength={1}
        strokeDasharray={1}
        fill="none"
        strokeWidth={1.5}
        className={travel ? 'stroke-foreground/40' : 'stroke-primary'}
        style={{ animation: `live-draw ${THREAD_MS}ms cubic-bezier(.6,0,.2,1) both` }}
      />
      {travel && (
        <circle r={5} className="fill-primary">
          <animateMotion dur={`${THREAD_MS}ms`} begin="0s" fill="freeze" path={d} keyPoints="0;1" keyTimes="0;1" calcMode="spline" keySplines=".6 0 .2 1" />
        </circle>
      )}
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
      {think.lines.length > 0 && think.step !== 'done' && (
        <ul className="m-0 grid list-none gap-0.5 p-0 font-mono text-[12px] text-foreground/70">
          {think.lines.map((line, i) => (
            <li
              key={i}
              className={cn('animate-in fade-in slide-in-from-left-1 duration-300 motion-reduce:animate-none', line.startsWith('⚠') && 'font-semibold text-red-700')}
            >
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
                chip.flown
                  ? chip.warn
                    ? 'border border-red-700/50 bg-transparent text-red-700'
                    : 'border border-foreground/25 bg-transparent text-foreground/45'
                  : chip.warn
                    ? 'bg-red-700 text-white'
                    : 'bg-foreground text-background',
              )}
              style={{ animationDelay: `${i * 140}ms` }}
            >
              {chip.flown && (chip.warn ? '! ' : '✓ ')}
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
  opensIn,
  onOpen,
  notice,
  noticing,
}: {
  item: ReviewItem
  writing: boolean
  snapping: boolean
  landed: boolean
  innerRef?: (el: HTMLElement | null) => void
  valueRef?: (el: HTMLElement | null) => void
  /** The module this line is kept in, when it can be opened. */
  opensIn?: string
  onOpen?: (el: HTMLElement) => void
  /** What Mesiri noticed about this line, and whether it's being said now. */
  notice?: string | null
  noticing?: boolean
}) {
  const { main, sub } = rowLines(item)
  const value = keyValue(item)
  const mode = snapping ? 'scatter' : writing ? 'gather' : 'still'
  const open = (el: HTMLElement) => onOpen?.(el)
  return (
    <li
      ref={innerRef}
      role={onOpen ? 'link' : undefined}
      tabIndex={onOpen ? 0 : undefined}
      aria-label={onOpen ? `${main}, open in ${opensIn}` : undefined}
      onClick={onOpen ? (e) => open(e.currentTarget) : undefined}
      onKeyDown={onOpen ? (e) => e.key === 'Enter' && open(e.currentTarget) : undefined}
      className={cn(
        'group relative grid grid-cols-[minmax(0,1fr)_auto] items-start gap-x-4 border-b border-black/10 py-3 last:border-b-0',
        onOpen && 'cursor-pointer outline-none hover:bg-black/[0.025] focus-visible:bg-black/[0.04]',
      )}
      style={
        prefersReducedMotion()
          ? undefined
          : noticing
            ? { animation: 'live-shake 600ms ease-in-out both' }
            : writing
              ? { animation: 'live-glow 3s ease-out both' }
              : undefined
      }
    >
      {onOpen && opensIn && (
        <span className="pointer-events-none absolute -bottom-2.5 right-0 z-10 bg-[#1a1d21] px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-[0.08em] text-white opacity-0 transition-opacity duration-200 group-hover:opacity-100 group-focus-visible:opacity-100">
          Open in {opensIn} →
        </span>
      )}
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
            <Landed active={landed} className={cn('text-[18px] font-semibold tabular-nums', notice && 'text-red-700')}>
              {value}
            </Landed>
          </span>
        )}
        {item.review === 'draft' && (
          <span className="font-mono text-[10px] uppercase tracking-[0.08em] text-primary">Draft</span>
        )}
      </span>
      {notice && (!writing || noticing) && !snapping && (
        // Mesiri caught something: said in red, under the line.
        <span className="col-span-2 mt-2 flex items-start gap-2 border-l-2 border-red-700 bg-red-50 px-2.5 py-1.5 text-[13px] text-red-800 animate-in fade-in slide-in-from-top-1 duration-300 motion-reduce:animate-none">
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
          <span>
            <b className="font-semibold">Mesiri noticed:</b> <Ink text={notice} writing={!!noticing} />
          </span>
        </span>
      )}
    </li>
  )
}

/** "HH:MM[:SS]" today, as a time; null when unset. */
function todayAt(hhmm: string | null | undefined): Date | null {
  if (!hhmm) return null
  const [h, m] = hhmm.split(':').map(Number)
  if (Number.isNaN(h) || Number.isNaN(m)) return null
  const at = new Date()
  at.setHours(h, m, 0, 0)
  return at
}

function left(ms: number): string {
  const mins = Math.max(0, Math.round(ms / 60_000))
  if (mins < 60) return `${mins} min`
  return `${Math.floor(mins / 60)}h ${String(mins % 60).padStart(2, '0')}m`
}

/** Above the sheet: what the report still waits for, ticking off as lines
 * land, and the time left before it sends. */
function DayProgress({
  needs,
  project,
  today,
  frozen,
}: {
  needs: { label: string; done: boolean; needed: boolean }[]
  project: SiteDayDetail['project']
  today: boolean
  frozen: boolean
}) {
  const [now, setNow] = React.useState(() => Date.now())
  React.useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 15_000)
    return () => window.clearInterval(timer)
  }, [])
  const deadline = today && !project?.sent ? todayAt(project?.dpr_send_deadline) : null
  const remaining = deadline ? deadline.getTime() - now : null
  const close = remaining !== null && remaining > 0 && remaining < 30 * 60_000
  const missing = needs.filter((n) => n.needed && !n.done)

  return (
    <div className="mx-auto mb-4 flex max-w-[720px] flex-wrap items-center justify-between gap-x-6 gap-y-2">
      <ul className="m-0 flex list-none flex-wrap items-center gap-x-4 gap-y-1 p-0 text-[12.5px]" aria-label="What the report needs">
        <li className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-muted-foreground">
          {frozen || project?.sent ? 'Complete' : missing.length ? 'Waiting for' : 'Has everything it needs'}
        </li>
        {needs.map((n) => (
          <li
            key={n.label}
            className={cn(
              'flex items-center gap-1.5 transition-colors duration-500',
              n.done ? 'text-foreground' : n.needed ? 'text-foreground/70' : 'text-foreground/40',
            )}
          >
            <span
              key={String(n.done)}
              className={cn(
                'grid size-4 place-items-center rounded-full border text-[10px] leading-none',
                n.done ? 'border-foreground bg-foreground text-background animate-in zoom-in-50 duration-300 motion-reduce:animate-none' : 'border-current',
              )}
              aria-hidden="true"
            >
              {n.done ? '✓' : ''}
            </span>
            <span className={cn(n.done && 'line-through decoration-foreground/40')}>{n.label}</span>
            <span className="sr-only">{n.done ? 'in' : n.needed ? 'still needed' : 'optional'}</span>
          </li>
        ))}
      </ul>
      {project && today && (
        <span
          className={cn('font-mono text-[11px] uppercase tracking-[0.06em]', close ? 'text-primary' : 'text-muted-foreground')}
          style={close && !prefersReducedMotion() ? { animation: 'pulse 2s ease-in-out infinite' } : undefined}
        >
          {project.sent
            ? 'Sent today'
            : deadline && remaining !== null && remaining > 0
              ? `${project.auto_generate_dpr ? 'Sends' : 'Due'} at ${formatClock(project.dpr_send_deadline)} · in ${left(remaining)}`
              : deadline
                ? `${project.auto_generate_dpr ? 'Sending' : 'Was due'} at ${formatClock(project.dpr_send_deadline)}`
                : null}
        </span>
      )}
    </div>
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
  const questions = useQuery({
    queryKey: ['live-site-questions', siteId, date],
    queryFn: () => fetchSiteQuestionsApi(siteId, ...dayWindow(date)),
    enabled: !!siteId,
    refetchInterval: POLL_MS,
    retry: false,
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
  // The relay on to a module: the thread from the report line to its module, and the modules just reached.
  const [relay, setRelay] = React.useState<{ from: string; to: Section } | null>(null)
  const [pulsing, setPulsing] = React.useState<Set<Section>>(new Set())
  const [moduleLast, setModuleLast] = React.useState<Partial<Record<Section, string>>>({})
  const moduleEnabled = useModuleEnabled()
  const cinematic = useCinematicGo()
  // The sheet turned over to a question's answer, and "sent as PDF" for a report asked for.
  const [answer, setAnswer] = React.useState<SiteQuestion | null>(null)
  const [stamped, setStamped] = React.useState(false)
  const qKnown = React.useRef<Set<string> | null>(null)
  const qQueue = React.useRef<SiteQuestion[]>([])
  const release = React.useRef<(() => void) | null>(null)
  // The line Mesiri is pointing a mistake out on, and the finale (the report going out).
  const [noticing, setNoticing] = React.useState<string | null>(null)
  const [finale, setFinale] = React.useState<DOMRect | null>(null)
  const finaleDue = React.useRef(false)
  const wasSent = React.useRef<boolean | null>(null)

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
  const nodeEls = React.useRef(new Map<Section, HTMLElement>())
  const setNodeEl = React.useCallback((section: Section, el: HTMLElement | null) => {
    if (el) nodeEls.current.set(section, el)
    else nodeEls.current.delete(section)
  }, [])
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

  const questionFeed = (q: SiteQuestion, fresh: boolean): FeedMessage => ({
    id: q.id,
    type: q.type,
    text: (q.text || '').trim() || kindLabel(q.type),
    at: q.received_at,
    sender: q.sender_name,
    source: q.source || 'whatsapp',
    fresh,
    think: fresh ? null : q.translated_text ? { step: 'done', english: q.translated_text, lines: [], chips: [] } : null,
    reply: q.reply,
    replied: !fresh,
  })

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

  const pulse = (section: Section) => {
    setPulsing((all) => new Set(all).add(section))
    window.setTimeout(() => {
      setPulsing((all) => {
        const next = new Set(all)
        next.delete(section)
        return next
      })
    }, 2400)
  }

  /** One message and the facts taken from it: read, understood, landed, passed on to its module. */
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
          for (const item of group) {
            if (item.flags?.includes('beyond_stock')) lines.push('⚠ more used than in stock')
            else if (item.flags?.includes('possible_duplicate')) lines.push('⚠ looks like a repeat')
          }
          for (const line of lines.slice(0, 9)) {
            think(msg.id, (t) => ({ ...t, lines: [...t.lines, line] }))
            await sleep(line.startsWith('⚠') ? 600 : 230)
          }
          if (!live()) return
        }
        think(msg.id, (t) => ({
          ...t,
          step: 'chips',
          chips: group.map((item) => ({ key: factKey(item), label: chipLabel(item, headcount), flown: false, warn: item.flags?.length > 0 })),
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
        if (!still && noticeOf(item, latest.current?.report)) {
          // Mesiri points it out before moving on.
          const { sub } = rowLines(item)
          await sleep(DUST_MS + (sub ? SUB_LAG_MS : 0))
          setNoticing(key)
          await sleep(2600)
        }
        if (msg) think(msg.id, (t) => ({ ...t, chips: t.chips.map((c) => (c.key === key ? { ...c, flown: true } : c)) }))
        if (!still) {
          const { sub } = rowLines(item)
          await sleep(isLabour ? 1600 : DUST_MS + (sub ? SUB_LAG_MS : 0) + 700)
          setThread(null)
          if (!live()) return
          // On to the module that keeps it.
          setRelay({ from: isLabour ? 'labour-total' : key, to: item.section })
          await sleep(THREAD_MS)
        }
        setModuleLast((all) => ({ ...all, [item.section]: chipLabel(item, headcount) }))
        pulse(item.section)
        if (!still) {
          await sleep(450)
          setRelay(null)
        }
        setWriting(null)
        if (!still) await sleep(350)
      }
      if (msg) think(msg.id, (t) => ({ ...t, step: 'done' }))
    },
    [sourceOf],
  )

  /** The report went out: the sheet folds into its PDF and drops into WhatsApp. */
  const startFinale = React.useCallback(() => {
    finaleDue.current = false
    setThread(null)
    setRelay(null)
    release.current?.()
    setAnswer(null)
    const sheet = targetEls.current.get('sheet')
    setFinale(sheet?.getBoundingClientRect() ?? new DOMRect(window.innerWidth / 2 - 300, 120, 600, 700))
  }, [])

  /** A question: read like any message, then the sheet turns over to the answer. */
  const playQuestion = React.useCallback(async (q: SiteQuestion, gen: number) => {
    const still = prefersReducedMotion()
    const live = () => alive.current && gen === generation.current
    const key = questionKey(q)
    const siteName = site?.site_name ?? 'site'
    if (!feedIds.current.has(q.id)) {
      feedIds.current.add(q.id)
      setFeed((all) => [...all, questionFeed(q, true)])
    }
    if (!still) {
      await sleep(Math.min(2600, 900 + (q.text ?? '').length * 10))
      think(q.id, (t) => ({ ...t, step: 'reading' }))
      await sleep(1100)
      if (!live()) return
      const english = q.translated_text?.trim() || null
      if (english) {
        think(q.id, (t) => ({ ...t, step: 'english', english }))
        await sleep(inkDuration(`“${english}”`) + 400)
        if (!live()) return
      }
      think(q.id, (t) => ({ ...t, step: 'fields' }))
      for (const line of [`→ a question: ${q.kind === 'report' ? 'send the report' : q.kind}`, `about: ${q.whole_project ? site?.project_name ?? 'the project' : siteName}`]) {
        think(q.id, (t) => ({ ...t, lines: [...t.lines, line] }))
        await sleep(260)
      }
    }
    think(q.id, (t) => ({ ...t, step: 'chips', chips: [{ key, label: questionChip(q, siteName), flown: false }] }))
    if (!still) await sleep(800)
    if (!live()) return
    const chip = chipEls.current.get(key)
    const sheet = targetEls.current.get('sheet')
    if (!still && chip && sheet) {
      const to = sheet.getBoundingClientRect()
      setFlyer({ id: Date.now(), label: questionChip(q, siteName), from: chip.getBoundingClientRect(), to: new DOMRect(to.left + 24, to.top, to.width, 60) })
      setThread({ chip: key, target: 'sheet' })
      await sleep(FLY_MS)
      setFlyer(null)
    }
    think(q.id, (t) => ({ ...t, chips: t.chips.map((c) => ({ ...c, flown: true })) }))
    if (q.kind === 'report') {
      // The report itself was asked for: it is stamped and goes out as a PDF.
      setStamped(true)
      await sleep(still ? 0 : 2600)
    } else {
      setAnswer(q)
      if (!still) await sleep(FLIP_MS)
    }
    setThread(null)
    // Mesiri's reply, under the question.
    setFeed((all) => all.map((m) => (m.id === q.id ? { ...m, replied: true } : m)))
    think(q.id, (t) => ({ ...t, step: 'done' }))
    if (q.kind !== 'report') {
      // The answer stays up a while, or until "Back to the report".
      await new Promise<void>((resolve) => {
        const timer = window.setTimeout(resolve, still ? 4000 : ANSWER_MS)
        release.current = () => {
          window.clearTimeout(timer)
          resolve()
        }
      })
      release.current = null
      if (gen !== generation.current) return
      setAnswer(null)
      if (!still) await sleep(FLIP_MS)
    } else {
      setStamped(false)
    }
  }, [site?.site_name, site?.project_name])

  // Plays the queue a message at a time: every fact a message gave lands together.
  const play = React.useCallback(async () => {
    if (running.current) return
    running.current = true
    const gen = generation.current
    while ((queue.current.length || qQueue.current.length) && alive.current && gen === generation.current) {
      await Promise.all(queue.current.map(sourceOf))
      if (gen !== generation.current) break
      // Whichever came in first, a question or a message with facts.
      const nextQuestion = qQueue.current[0]
      const factAt = queue.current.length ? (sources.current.get(factKey(queue.current[0]))?.message?.received_at ?? '9') : null
      if (nextQuestion && (factAt === null || (nextQuestion.received_at ?? '') <= factAt)) {
        qQueue.current = qQueue.current.slice(1)
        await playQuestion(nextQuestion, gen)
        if (!prefersReducedMotion()) await sleep(600)
        continue
      }
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
    if (gen === generation.current) {
      running.current = false
      if (finaleDue.current && alive.current) startFinale()
    }
  }, [sourceOf, playMessage, playQuestion, startFinale])

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
        for (const id of seen.keys()) feedIds.current.add(id)
        setFeed((all) =>
          [...all.filter((m) => !seen.has(m.id)), ...seen.values()].sort((a, b) => (a.at ?? '').localeCompare(b.at ?? '')),
        )
      })
      return
    }
    const fresh = data.items.filter((item) => !known.current!.has(factKey(item)))
    if (fresh.length === 0) return
    fresh.forEach((item) => known.current!.add(factKey(item)))
    queue.current.push(...fresh)
    void play()
  }, [detail.data, play, sourceOf])

  // Questions: the first read goes in the feed as already answered; new ones play.
  React.useEffect(() => {
    const data = questions.data
    if (!data) return
    if (qKnown.current === null) {
      qKnown.current = new Set(data.map((q) => q.id))
      for (const q of data) feedIds.current.add(q.id)
      setFeed((all) => [...all, ...data.map((q) => questionFeed(q, false))].sort((a, b) => (a.at ?? '').localeCompare(b.at ?? '')))
      return
    }
    const fresh = data.filter((q) => !qKnown.current!.has(q.id))
    if (fresh.length === 0) return
    fresh.forEach((q) => qKnown.current!.add(q.id))
    qQueue.current.push(...fresh)
    void play()
    // questionFeed is pure; play is the only dependency that changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [questions.data, play])

  // The report going out while watching ends the story: the finale, once what's playing has landed.
  React.useEffect(() => {
    const data = detail.data
    if (!data) return
    const sent = !!data.project?.sent
    if (wasSent.current === null) {
      wasSent.current = sent
      return
    }
    if (sent && !wasSent.current) {
      finaleDue.current = true
      if (!running.current) startFinale()
    }
    wasSent.current = sent
  }, [detail.data, startFinale])

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
    setRelay(null)
    setModuleLast({})
    qKnown.current = null
    qQueue.current = []
    release.current?.()
    setAnswer(null)
    setStamped(false)
    setNoticing(null)
    setFinale(null)
    finaleDue.current = false
    wasSent.current = null
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
    setRelay(null)
    qQueue.current = []
    release.current?.()
    setAnswer(null)
    setStamped(false)
    setNoticing(null)
    setFinale(null)
    if (!prefersReducedMotion() && written.size > 0) {
      setSnapping(true)
      await sleep(SNAP_MS + 500)
    }
    setSnapping(false)
    setWritten(new Set())
    setLanded(new Set())
    setModuleLast({})
    feedIds.current = new Set()
    setFeed([])
    setLabour({ ...data.report.labour, headcount: 0, trades: [] })
    const withTimes = await Promise.all(data.items.map(async (item) => ({ item, src: await sourceOf(item) })))
    withTimes.sort((a, b) => (a.src.message?.received_at ?? '9').localeCompare(b.src.message?.received_at ?? '9'))
    queue.current = withTimes.map((x) => x.item)
    qQueue.current = [...(questions.data ?? [])]
    // A day that went out ends the way it did: in WhatsApp.
    finaleDue.current = !!data.project?.sent
    await sleep(500)
    void play()
  }

  // The message being read stays in view; the report beside it is pinned.
  React.useEffect(() => {
    const el = stage.current?.querySelector('[data-reading]')
    if (el && !prefersReducedMotion()) el.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [feed])

  // The thread is measured after the frame that placed both ends.
  React.useLayoutEffect(() => {
    if (thread || relay) redraw()
  }, [thread, relay])
  React.useEffect(() => {
    // The report is pinned while the messages scroll, so threads follow both.
    const onResize = () => redraw()
    window.addEventListener('resize', onResize)
    window.addEventListener('scroll', onResize, { passive: true })
    return () => {
      window.removeEventListener('resize', onResize)
      window.removeEventListener('scroll', onResize)
    }
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
  const relayFrom = relay ? targetEls.current.get(relay.from) : undefined
  const relayTo = relay ? nodeEls.current.get(relay.to) : undefined
  const counts = Object.fromEntries(
    LIVE_MODULES.map((m) => [m.section, m.section === 'labour' ? (labour?.headcount ?? 0) : shown(m.section).length]),
  ) as Record<Section, number>
  const canOpen = (m: LiveModule) => moduleEnabled(m.module)
  const scopeQuery = () => {
    const scope = new URLSearchParams()
    if (site?.project_id) scope.set('project', site.project_id)
    if (siteId) scope.set('site', siteId)
    return scope.toString()
  }
  const answerTarget: AnswerTarget | null = (() => {
    if (!answer) return null
    if (answer.kind === 'project') return site?.project_id ? { name: 'Project', path: `/projects/${site.project_id}` } : null
    const section = ({ stock: 'materials', manpower: 'labour', work: 'work' } as const)[answer.kind as 'stock' | 'manpower' | 'work']
    if (!section) return null
    const m = moduleOf(section)
    return canOpen(m) ? { name: m.name, path: `${m.path}?${scopeQuery()}` } : null
  })()
  const open = (m: LiveModule, el: HTMLElement, line?: string) => {
    cinematic.go({
      from: el.getBoundingClientRect(),
      to: `${m.path}?${scopeQuery()}`,
      title: m.name,
      kicker: [site?.site_name, longDate(date)].filter(Boolean).join(' · '),
      line,
    })
  }

  return (
    <div className="min-h-svh bg-background px-4 pb-16 sm:px-8 lg:px-12">
      <div className="mx-auto max-w-[1440px]">
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
              disabled={!detail.data || (items.length === 0 && !questions.data?.length)}
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
          <div
            ref={stage}
            className="relative grid gap-10 pt-8 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:gap-16 xl:grid-cols-[minmax(0,5fr)_minmax(0,7fr)_220px] xl:gap-12"
          >
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
                    data-reading={m.think && m.think.step !== 'done' ? '' : undefined}
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
                    {m.replied && m.reply && (
                      // A question's answer, as Mesiri sent it back.
                      <div className="mt-2 grid gap-1 border-l-2 border-foreground pl-3 animate-in fade-in slide-in-from-left-1 duration-500 motion-reduce:animate-none">
                        <Label className="flex items-center gap-2">
                          {m.source === 'dashboard' ? <Monitor className="size-3.5" aria-hidden="true" /> : <WhatsAppIcon className="size-3.5 text-[#25D366]" />}
                          Mesiri replied
                        </Label>
                        <Ink
                          text={m.reply.length > 220 ? `${m.reply.slice(0, 217)}…` : m.reply}
                          writing={m.fresh}
                          className="whitespace-pre-line text-[14px] leading-relaxed text-foreground/80"
                        />
                        {!m.fresh && !running.current && (
                          <button
                            type="button"
                            onClick={() => setAnswer(questions.data?.find((q) => q.id === m.id) ?? null)}
                            className="justify-self-start border-b border-foreground font-mono text-[10.5px] uppercase tracking-[0.06em]"
                          >
                            See the answer
                          </button>
                        )}
                      </div>
                    )}
                  </li>
                ))}
              </ol>
            </section>

            {/* The report */}
            <section aria-label="Daily progress report" className="min-w-0 lg:sticky lg:top-6 lg:self-start">
              <DayProgress
                needs={[
                  { label: 'Manpower', done: (labour?.headcount ?? 0) > 0, needed: true },
                  { label: 'Work done', done: shown('work').length > 0, needed: true },
                  { label: 'Materials', done: shown('materials').length > 0, needed: false },
                  { label: 'Photos', done: (detail.data?.report.evidence_count ?? 0) > 0, needed: false },
                ]}
                project={detail.data?.project ?? null}
                today={date === today}
                frozen={frozen}
              />
              <div
                ref={(el) => {
                  if (el) targetEls.current.set('sheet', el)
                }}
                className="mx-auto max-w-[720px] [perspective:2400px]"
              >
                {/* The sheet turns over to a question's answer and back. */}
                <div
                  className="grid transition-transform ease-[cubic-bezier(.7,0,.2,1)] motion-reduce:transition-none"
                  style={{ transformStyle: 'preserve-3d', transform: answer ? 'rotateY(180deg)' : 'none', transitionDuration: `${FLIP_MS}ms` }}
                >
              <div className="relative [grid-area:1/1] [backface-visibility:hidden] border border-black/15 bg-white px-6 pt-6 pb-5 text-[#1a1d21] shadow-[0_20px_50px_-30px_rgba(0,0,0,0.35)] sm:px-9 sm:pt-8" aria-hidden={answer ? true : undefined} inert={!!answer}>
                {stamped && (
                  // The report was asked for: it goes out as a PDF.
                  <div className="pointer-events-none absolute inset-0 z-10 grid place-items-center bg-white/40" aria-live="polite">
                    <span
                      className="rotate-[-8deg] border-4 border-primary bg-white px-5 py-2 font-brand text-[28px] tracking-[0.1em] text-primary shadow-lg"
                      style={prefersReducedMotion() ? undefined : { animation: 'live-slam 800ms cubic-bezier(.2,.9,.3,1.2) both' }}
                    >
                      SENT AS PDF
                    </span>
                  </div>
                )}
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
                  {...(canOpen(moduleOf('labour'))
                    ? {
                        role: 'link',
                        tabIndex: 0,
                        'aria-label': 'Manpower, open in Labour',
                        onClick: (e: React.MouseEvent<HTMLElement>) =>
                          open(moduleOf('labour'), e.currentTarget, labour?.headcount ? `${labour.headcount} ${labour.headcount === 1 ? 'worker' : 'workers'} on site` : undefined),
                        onKeyDown: (e: React.KeyboardEvent<HTMLElement>) => {
                          if (e.key === 'Enter') open(moduleOf('labour'), e.currentTarget)
                        },
                      }
                    : {})}
                  className={cn(
                    'mt-6 transition-[opacity,filter,transform] duration-1000',
                    canOpen(moduleOf('labour')) && 'cursor-pointer outline-none hover:bg-black/[0.025] focus-visible:bg-black/[0.04]',
                    snapping && 'translate-x-3 opacity-0 blur-[3px]',
                  )}
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
                                notice={noticeOf(item, detail.data?.report)}
                                noticing={noticing === k}
                                opensIn={moduleOf(key).name}
                                onOpen={
                                  canOpen(moduleOf(key))
                                    ? (el) => open(moduleOf(key), el, [rowLines(item).main, keyValue(item)].filter(Boolean).join(' · '))
                                    : undefined
                                }
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
                    {frozen ? 'CONFIRMED' : detail.data?.project?.sent ? 'SENT' : 'LIVE DRAFT'}
                  </span>
                </div>
              </div>
              <div
                className="[grid-area:1/1] [backface-visibility:hidden] [transform:rotateY(180deg)] border border-black/15 bg-white px-6 pt-6 pb-5 text-[#1a1d21] shadow-[0_20px_50px_-30px_rgba(0,0,0,0.35)] sm:px-9 sm:pt-8"
                aria-hidden={answer ? undefined : true}
                inert={!answer}
              >
                {answer && (
                  <AnswerSheet
                    key={answer.id}
                    question={answer}
                    title={answerTitle(answer, site?.site_name ?? 'site', site?.project_name ?? 'the project')}
                    projectId={site?.project_id}
                    siteId={siteId}
                    labour={labour}
                    workRows={shown('work')}
                    stockOn={moduleEnabled('materials')}
                    target={answerTarget}
                    onOpen={(el) =>
                      answerTarget &&
                      cinematic.go({
                        from: el.getBoundingClientRect(),
                        to: answerTarget.path,
                        title: answerTarget.name,
                        kicker: [site?.site_name, longDate(date)].filter(Boolean).join(' · '),
                        line: answerTitle(answer, site?.site_name ?? 'site', site?.project_name ?? 'the project'),
                      })
                    }
                    onBack={() => (release.current ? release.current() : setAnswer(null))}
                  />
                )}
              </div>
                </div>
              </div>
            </section>

            {/* Where it goes: the modules that keep each fact */}
            <ModuleRail
              counts={counts}
              last={moduleLast}
              pulsing={pulsing}
              enabled={canOpen}
              nodeRef={setNodeEl}
              onOpen={open}
              className={cn(
                'min-w-0 lg:col-span-2 xl:col-span-1 xl:sticky xl:top-6 xl:self-start',
                'transition-[opacity,filter] duration-1000',
                snapping && 'opacity-40 blur-[2px]',
              )}
            />

            {thread && box && fromEl && toEl && (
              <Thread from={rel(fromEl.getBoundingClientRect())} to={rel(toEl.getBoundingClientRect())} />
            )}
            {relay && box && relayFrom && relayTo && (
              <Thread travel className="xl:block" from={rel(relayFrom.getBoundingClientRect())} to={rel(relayTo.getBoundingClientRect())} />
            )}
          </div>
        )}
      </div>
      {flyer && <Flyer key={flyer.id} label={flyer.label} from={flyer.from} to={flyer.to} />}
      {cinematic.overlay}
      {finale && (
        <Finale
          from={finale}
          projectId={site?.project_id}
          company={company}
          code={detail.data?.day?.code ?? null}
          site={site?.site_name ?? ''}
          onDone={() => setFinale(null)}
        />
      )}
    </div>
  )
}
