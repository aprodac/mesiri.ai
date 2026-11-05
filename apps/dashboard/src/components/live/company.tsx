import * as React from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle,
  ArrowLeftRight,
  Boxes,
  Camera,
  CheckCheck,
  CheckCircle2,
  FileText,
  Flag,
  Hammer,
  Hand,
  HardHat,
  HelpCircle,
  IndianRupee,
  Languages,
  type LucideIcon,
  MessageCircle,
  Mic,
  Monitor,
  Play,
  PackageMinus,
  PencilLine,
  Truck,
  Undo2,
  X,
  XCircle,
} from 'lucide-react'
import {
  fetchBranding,
  fetchLiveFeedApi,
  fetchSiteDayApi,
  fetchSetupProgress,
  fetchSiteDaysApi,
  type LiveFeedItem,
  type LiveKind,
  type SiteDayItem,
} from '@/lib/api'
import { noticeOf } from '@/lib/live-reading'
import { longDate } from '@/lib/site-day'
import { prefersReducedMotion } from '@/lib/timeline'
import { cn } from '@/lib/utils'
import { MesiriWordmark } from '@/components/brand/mesiri-logo'
import { WhatsAppIcon } from '@/components/brand/whatsapp-icon'
import { Label } from '@/components/onboarding/conversation'
import { QrCode } from '@/components/onboarding/qr-code'
import { TellMesiri } from '@/components/tell-mesiri/tell-mesiri'
import { CountTo } from './ink'
import { useCinematicGo } from './modules'
import { MEET_SAMPLES, MeetMesiri, type SceneKey } from './meet'
import { AnswerMoment, AskedMoment, BillMoment, LanguageMoment, answers as answersOf } from './moments'
import { Spark, type SparkMood } from './spark'

// The company Live (WEB-53): every message the company sends Mesiri, on one
// screen, as it happens, with Mesiri as a character (the Spark) seen
// handling each one. Left, the messages come in (any site, any kind:
// attendance, a delivery, a question, a photo, a "hi"). In the middle the
// Spark takes each in turn: it perks up, listens to a voice note or looks
// at a photo, says in English what it understood, then what it did (saved
// to Materials, waiting for ✅ Save, asked something back, answered). A
// light flies from the Spark to the site's card, which rings, and the
// company's numbers along the bottom count up. A site's card opens that
// site's own Live report (the day's report writing itself). Presenter mode
// is the demo: full screen, larger, and a QR code that opens a WhatsApp
// chat with Mesiri, so a phone in the room can send a message and everyone
// watches it land. Replay the day plays every message again, faster, for a
// demo when nobody is sending. A voice note shows its waveform; a message in
// another language turns into its English letter by letter; under the
// steps, what Mesiri did ("Found the material → Checked the stock"). When a
// line Mesiri flags appears with the message (more used than in stock, a
// likely repeat), the page dims and the site shakes red: Mesiri caught a
// mistake. A transfer flies from one site's card to the other; a site just
// added pops in. "Meet Mesiri" (meet.tsx) is the show of what Mesiri does,
// full on the button, short on a person's first message ever and at the start
// of a replay. Read-only, like the site Live.

const FEED_POLL_MS = 3_000
const SITES_POLL_MS = 10_000
/** How long each step of the Spark's handling shows. */
const STEP_MS = 1_300
/** At most this many new messages are played in turn; older ones just appear. */
const QUEUE_MAX = 6
/** Replay runs at this fraction of the live timing. */
const REPLAY_SPEED = 0.45
/** Sites whose flagged lines are read as the page opens (to tell a mistake caught later). */
const FLAG_SITES_MAX = 12

interface KindLook {
  icon: LucideIcon
  /** The module it goes to, as the Spark says it. */
  goes: string | null
  tone: 'work' | 'materials' | 'issues' | 'money' | 'info' | 'plain'
}

const KINDS: Record<LiveKind, KindLook> = {
  attendance: { icon: HardHat, goes: 'Labour', tone: 'work' },
  work: { icon: Hammer, goes: 'Site log', tone: 'work' },
  correction: { icon: PencilLine, goes: 'Site log', tone: 'work' },
  delivery: { icon: Truck, goes: 'Materials', tone: 'materials' },
  usage: { icon: PackageMinus, goes: 'Materials', tone: 'materials' },
  transfer: { icon: ArrowLeftRight, goes: 'Materials', tone: 'materials' },
  catalogue: { icon: Boxes, goes: 'Materials', tone: 'materials' },
  expense: { icon: IndianRupee, goes: 'Expenses', tone: 'money' },
  issue: { icon: AlertTriangle, goes: 'Issues', tone: 'issues' },
  issue_closed: { icon: CheckCircle2, goes: 'Issues', tone: 'issues' },
  undo: { icon: Undo2, goes: null, tone: 'plain' },
  setup: { icon: Flag, goes: 'Projects', tone: 'info' },
  language: { icon: Languages, goes: null, tone: 'info' },
  report: { icon: FileText, goes: 'Reports', tone: 'info' },
  question: { icon: HelpCircle, goes: null, tone: 'info' },
  saved: { icon: CheckCheck, goes: null, tone: 'work' },
  cancelled: { icon: XCircle, goes: null, tone: 'plain' },
  photo: { icon: Camera, goes: null, tone: 'plain' },
  chat: { icon: MessageCircle, goes: null, tone: 'plain' },
}

const TONES: Record<KindLook['tone'], string> = {
  work: 'text-[var(--success)] bg-[var(--success-soft)]',
  materials: 'text-[var(--info)] bg-[var(--info-soft)]',
  issues: 'text-[var(--destructive)] bg-[color-mix(in_srgb,var(--destructive)_12%,transparent)]',
  money: 'text-[var(--draft)] bg-[var(--draft-soft)]',
  info: 'text-[var(--ai)] bg-[var(--ai-soft)]',
  plain: 'text-muted-foreground bg-muted',
}

const isVoice = (m: LiveFeedItem) => /voice|audio/.test(m.type)
/** An expense with a bill photo or what Mesiri read from it: its own moment (moments.tsx). */
const isBill = (m: LiveFeedItem) => (m.kind === 'expense' || m.saved_kind === 'expense') && !!(m.expense || (m.media_url && /image|photo/.test(m.type)))
const isPhoto = (m: LiveFeedItem) => /image|photo/.test(m.type)
const clock = (iso: string | null) =>
  iso ? new Date(iso).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' }) : ''
const initials = (name: string | null) =>
  (name ?? '?')
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase())
    .join('') || '?'
const short = (s: string | null | undefined, n = 140) => (s && s.length > n ? `${s.slice(0, n - 1)}…` : s ?? '')

/** The viewer's day for `date` (YYYY-MM-DD). */
function dayWindow(date: string): [Date, Date] {
  const [y, m, d] = date.split('-').map(Number)
  return [new Date(y, m - 1, d), new Date(y, m - 1, d + 1)]
}

/** The steps the Spark goes through with one message, and what it says at each. */
type Step = 'arrive' | 'read' | 'understood' | 'done'
interface Current {
  item: LiveFeedItem
  step: Step
  /** What Mesiri noticed (a line it flagged with this message), at "done". */
  alarm: string | null
}

function sparkMood(m: LiveFeedItem, step: Step, alarm: string | null): SparkMood {
  if (step === 'done' && alarm) return 'worry'
  if (step === 'arrive') return 'alert'
  if (step === 'read') return isVoice(m) ? 'listen' : isPhoto(m) ? 'look' : 'think'
  if (step === 'understood') return 'think'
  if (m.state === 'failed') return 'worry'
  if (m.kind === 'report') return 'send'
  if (m.state === 'saved') return 'happy'
  if (m.state === 'asked') return 'think'
  return 'idle'
}

function sparkSays(m: LiveFeedItem, step: Step, alarm: string | null): string {
  if (step === 'done' && alarm) return `Wait: ${alarm}`
  const who = m.sender_name?.split(/\s+/)[0] ?? 'Someone'
  const where = m.site_name ?? m.project_name
  if (step === 'arrive') return `${who} sent a ${isVoice(m) ? 'voice note' : isPhoto(m) ? 'photo' : 'message'}${where ? ` from ${where}` : ''}`
  if (step === 'read') return isVoice(m) ? 'Listening…' : isPhoto(m) ? 'Looking at the photo…' : 'Reading…'
  if (step === 'understood' && isBill(m)) return `A bill${m.expense?.vendor ? ` from ${m.expense.vendor}` : ''}`
  if (step === 'understood') return m.translated_text || m.text || (isPhoto(m) ? 'A photo from site' : '…')
  if (isBill(m) && m.reply) return short(m.reply, 160)
  const goes = KINDS[m.saved_kind ?? m.kind].goes
  const what = m.summaries.join(' · ')
  switch (m.state) {
    case 'saved':
      return `Saved${goes ? ` to ${goes}` : ''}${what ? `: ${what}` : ''}`
    case 'draft':
      return `Ready, waiting for ✅ Save${what ? `: ${what}` : ''}`
    case 'asked':
      return `I asked: ${m.asked}`
    case 'failed':
      return 'That could not be saved. I told them why.'
    case 'answered':
      return short(m.reply, 160) || 'Answered'
    default:
      return short(m.reply, 160) || 'Got it'
  }
}

/** Letters written in one by one. */
function Typed({ text, ms = 18 }: { text: string; ms?: number }) {
  const [n, setN] = React.useState(prefersReducedMotion() ? text.length : 0)
  React.useEffect(() => {
    if (prefersReducedMotion()) {
      setN(text.length)
      return
    }
    setN(0)
    const t = window.setInterval(() => setN((k) => (k >= text.length ? k : k + 1)), ms)
    return () => window.clearInterval(t)
  }, [text, ms])
  return (
    <span>
      {text.slice(0, n)}
      {n < text.length && <span className="ml-px inline-block h-[1em] w-[2px] translate-y-[2px] animate-pulse bg-current" />}
    </span>
  )
}

/** A voice note playing: bars that rise and fall. */
function Waveform({ big }: { big: boolean }) {
  const bars = [0.5, 0.9, 0.6, 1, 0.7, 0.4, 0.85, 0.55, 0.95, 0.6, 0.35, 0.75, 0.5, 0.9, 0.45]
  return (
    <span className={cn('flex items-center justify-center gap-[3px]', big ? 'h-14' : 'h-10')} aria-hidden="true">
      {bars.map((h, i) => (
        <span
          key={i}
          className="w-[4px] rounded-full bg-foreground"
          style={{
            height: `${h * 100}%`,
            transformOrigin: 'center',
            animation: prefersReducedMotion() ? undefined : `live-bar 900ms ease-in-out ${i * 70}ms infinite alternate`,
          }}
        />
      ))}
    </span>
  )
}

/** The words as sent, then turning into their English letter by letter. */
function Flip({ from, to }: { from: string; to: string }) {
  const [n, setN] = React.useState(prefersReducedMotion() ? to.length : 0)
  React.useEffect(() => {
    if (prefersReducedMotion()) return
    let timer = 0
    const start = window.setTimeout(() => {
      timer = window.setInterval(() => setN((k) => (k >= to.length ? k : k + 1)), Math.max(12, 900 / Math.max(1, to.length)))
    }, 900)
    return () => {
      window.clearTimeout(start)
      window.clearInterval(timer)
    }
  }, [to])
  const done = n >= to.length
  return (
    <span>
      <span>{to.slice(0, n)}</span>
      {!done && <span className="text-muted-foreground">{from.slice(Math.round((n / to.length) * from.length))}</span>}
    </span>
  )
}

/** A dot that flies from one element to another. */
interface Flight {
  key: number
  from: DOMRect
  to: DOMRect
  delay?: number
}
function Flyer({ flight, onDone }: { flight: Flight; onDone: () => void }) {
  const ref = React.useRef<HTMLSpanElement>(null)
  React.useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const fx = flight.from.left + flight.from.width / 2
    const fy = flight.from.top + flight.from.height / 2
    const tx = flight.to.left + flight.to.width / 2
    const ty = flight.to.top + Math.min(24, flight.to.height / 2)
    const anim = el.animate(
      [
        { transform: `translate(${fx}px, ${fy}px) scale(1.4)`, opacity: 1 },
        { transform: `translate(${(fx + tx) / 2}px, ${Math.min(fy, ty) - 80}px) scale(1)`, opacity: 1, offset: 0.5 },
        { transform: `translate(${tx}px, ${ty}px) scale(0.6)`, opacity: 0.2 },
      ],
      { duration: 900, delay: flight.delay ?? 0, easing: 'cubic-bezier(.5,0,.3,1)', fill: 'backwards' },
    )
    anim.onfinish = onDone
    return () => anim.cancel()
  }, [flight, onDone])
  return (
    <span
      ref={ref}
      aria-hidden="true"
      className="pointer-events-none fixed left-0 top-0 z-50 -ml-2 -mt-2 size-4 rounded-full border-2 border-foreground bg-primary"
    />
  )
}

export function CompanyLive({ date, isToday }: { date: string; isToday: boolean }) {
  const [since, until] = React.useMemo(() => dayWindow(date), [date])
  const feed = useQuery({
    queryKey: ['live-feed', date],
    queryFn: () => fetchLiveFeedApi(since, until),
    refetchInterval: isToday ? FEED_POLL_MS : false,
    retry: false,
  })
  const days = useQuery({
    queryKey: ['live-site-days', date, null],
    queryFn: () => fetchSiteDaysApi(date),
    refetchInterval: isToday ? SITES_POLL_MS : false,
  })
  const branding = useQuery({ queryKey: ['company-branding'], queryFn: fetchBranding, retry: false, staleTime: 10 * 60_000 })
  const setup = useQuery({ queryKey: ['setup-progress'], queryFn: fetchSetupProgress, retry: false, staleTime: 10 * 60_000 })
  const cinematic = useCinematicGo()

  const items = React.useMemo(() => feed.data ?? [], [feed.data])
  /** Which message answers which question Mesiri asked back. */
  const qa = React.useMemo(() => answersOf(items), [items])
  const sites = React.useMemo(
    () => [...(days.data?.items ?? [])].sort((a, b) => (b.last_update_at ?? '').localeCompare(a.last_update_at ?? '')),
    [days.data],
  )

  // Which messages are on screen, and the one Mesiri is handling.
  const queryClient = useQueryClient()
  const [shown, setShown] = React.useState<Set<string>>(new Set())
  const [current, setCurrent] = React.useState<Current | null>(null)
  const [beat, setBeat] = React.useState(0)
  const [ringing, setRinging] = React.useState<Map<string, 'land' | 'alarm'>>(new Map())
  const [flights, setFlights] = React.useState<Flight[]>([])
  const [replaying, setReplaying] = React.useState(false)
  /** "Meet Mesiri" on screen: to whom (null: everyone), and the short show or the full one. */
  const [hello, setHello] = React.useState<{ to: string | null; short: boolean } | null>(null)
  /** The show is on: a message that comes meanwhile waits for it. */
  const greeting = React.useRef(false)
  const helloDone = React.useRef<(() => void) | null>(null)
  /** The show's sample messages, in the stream while it plays (marked Sample). */
  const [samples, setSamples] = React.useState<LiveFeedItem[]>([])
  /** Plays the show and resolves when it ends (or is closed). */
  const showMeet = React.useCallback((to: string | null, short: boolean) => {
    greeting.current = true
    setHello({ to, short })
    return new Promise<void>((resolve) => {
      helloDone.current = () => {
        helloDone.current = null
        greeting.current = false
        setHello(null)
        setSamples([])
        resolve()
      }
    })
  }, [])
  const queue = React.useRef<LiveFeedItem[]>([])
  const playing = React.useRef(false)
  const seeded = React.useRef(false)
  /** Replay plays faster. */
  const speed = React.useRef(1)
  const sparkRef = React.useRef<HTMLDivElement>(null)
  const siteRefs = React.useRef(new Map<string, HTMLElement>())
  /** Each site's lines Mesiri has flagged, as last read: a new one is a mistake just caught. */
  const flagged = React.useRef(new Map<string, Set<string>>())

  const readFlags = React.useCallback(
    async (siteId: string): Promise<{ keys: Set<string>; notices: Map<string, string> } | null> => {
      try {
        const day = await queryClient.fetchQuery({
          queryKey: ['live-site-day', siteId, date],
          queryFn: () => fetchSiteDayApi(siteId, date),
          staleTime: 0,
        })
        const notices = new Map<string, string>()
        for (const item of day.items ?? []) {
          const notice = noticeOf(item, day.report_with_drafts ?? day.report)
          if (notice) notices.set(`${item.fact_type}:${item.id}`, `${item.title ? `${item.title}: ` : ''}${notice}`)
        }
        return { keys: new Set(notices.keys()), notices }
      } catch {
        return null
      }
    },
    [queryClient, date],
  )

  const ring = React.useCallback((site: string, how: 'land' | 'alarm', after: number) => {
    window.setTimeout(() => setRinging((r) => new Map(r).set(site, how)), after)
    window.setTimeout(
      () =>
        setRinging((r) => {
          const next = new Map(r)
          next.delete(site)
          return next
        }),
      after + (how === 'alarm' ? 3_200 : 1_600),
    )
  }, [])

  const play = React.useCallback(async () => {
    if (playing.current) return
    playing.current = true
    const wait = (ms: number) => new Promise((r) => window.setTimeout(r, prefersReducedMotion() ? 0 : ms * speed.current))
    while (queue.current.length) {
      while (greeting.current) await new Promise((r) => window.setTimeout(r, 300))
      const item = queue.current.shift()!
      const live = speed.current === 1
      // Someone's first message ever: Mesiri says hello before it reads it.
      if (live && item.first_message) {
        await showMeet(item.sender_name?.split(/\s+/)[0] ?? null, true)
      }
      setShown((s) => new Set(s).add(item.id))
      setBeat((b) => b + 1)
      // Read the site's flags while Mesiri reads the message, so the answer is there by "done".
      const flags = live && item.site_id && flagged.current.has(item.site_id) ? readFlags(item.site_id) : null
      const flips = !!(item.translated_text && item.text && item.translated_text !== item.text) || isBill(item)
      for (const step of ['arrive', 'read', 'understood'] as Step[]) {
        setCurrent({ item, step, alarm: null })
        await wait(step === 'understood' ? STEP_MS + (flips ? 2_200 : 600) : step === 'read' && isVoice(item) ? STEP_MS + 900 : STEP_MS)
      }
      // A line of this site newly flagged: Mesiri caught a mistake.
      let alarm: string | null = null
      if (flags && item.site_id) {
        const read = await flags
        if (read) {
          const before = flagged.current.get(item.site_id) ?? new Set()
          const fresh = [...read.keys].find((k) => !before.has(k))
          alarm = fresh ? read.notices.get(fresh) ?? null : null
          flagged.current.set(item.site_id, read.keys)
        }
      }
      setCurrent({ item, step: 'done', alarm })
      const from = sparkRef.current?.getBoundingClientRect()
      const fly = (a: DOMRect | undefined, b: DOMRect | undefined, delay = 0) => {
        if (a && b && !prefersReducedMotion()) setFlights((f) => [...f, { key: Math.random(), from: a, to: b, delay }])
      }
      const transfer = item.transfer
      if (transfer && siteRefs.current.has(transfer.from_site_id) && siteRefs.current.has(transfer.to_site_id)) {
        // Materials move from one site to the other: three lights along the arc between them.
        const a = siteRefs.current.get(transfer.from_site_id)?.getBoundingClientRect()
        const b = siteRefs.current.get(transfer.to_site_id)?.getBoundingClientRect()
        for (const delay of [0, 160, 320]) fly(a, b, delay)
        ring(transfer.from_site_id, 'land', 0)
        ring(transfer.to_site_id, 'land', 900)
      } else if (item.site_id) {
        fly(from, siteRefs.current.get(item.site_id)?.getBoundingClientRect())
        ring(item.site_id, alarm ? 'alarm' : 'land', 850)
      }
      // The sites' numbers (and a site just added) catch up as it lands.
      if (live) void queryClient.invalidateQueries({ queryKey: ['live-site-days', date, null] })
      await wait(alarm ? STEP_MS + 3_400 : isBill(item) || item.kind === 'language' || item.state === 'asked' ? STEP_MS + 2_400 : STEP_MS + 1_200)
    }
    setCurrent(null)
    playing.current = false
    speed.current = 1
    setReplaying(false)
  }, [readFlags, ring, queryClient, date, showMeet])

  // The first read just shows the day; later reads play what is new.
  React.useEffect(() => {
    if (!feed.data) return
    if (!seeded.current) {
      seeded.current = true
      setShown(new Set(feed.data.map((m) => m.id)))
      return
    }
    if (replaying) return
    const known = new Set([...shown, ...queue.current.map((m) => m.id), current?.item.id])
    const fresh = feed.data.filter((m) => !known.has(m.id))
    if (!fresh.length) return
    const late = fresh.slice(0, Math.max(0, fresh.length - QUEUE_MAX))
    if (late.length) setShown((s) => new Set([...s, ...late.map((m) => m.id)]))
    queue.current.push(...fresh.slice(-QUEUE_MAX))
    void play()
  }, [feed.data, shown, current, play, replaying])

  // Each site's flagged lines as the page opens, so a mistake caught later shows as new.
  const flagSites = React.useMemo(() => (days.data?.items ?? []).slice(0, FLAG_SITES_MAX).map((s) => s.site_id).join(','), [days.data])
  React.useEffect(() => {
    if (!isToday || !flagSites) return
    for (const siteId of flagSites.split(',')) {
      if (flagged.current.has(siteId)) continue
      flagged.current.set(siteId, new Set())
      void readFlags(siteId).then((read) => {
        if (read) flagged.current.set(siteId, read.keys)
      })
    }
  }, [flagSites, isToday, readFlags])

  // A site that appears after the page opened (Mesiri just added it) pops in.
  const knownSites = React.useRef<Set<string> | null>(null)
  const [newSites, setNewSites] = React.useState<Set<string>>(new Set())
  React.useEffect(() => {
    const ids = (days.data?.items ?? []).map((s) => s.site_id)
    if (!days.data) return
    if (knownSites.current === null) {
      knownSites.current = new Set(ids)
      return
    }
    const added = ids.filter((id) => !knownSites.current!.has(id))
    if (!added.length) return
    for (const id of added) knownSites.current.add(id)
    setNewSites((s) => new Set([...s, ...added]))
    window.setTimeout(() => setNewSites((s) => new Set([...s].filter((id) => !added.includes(id)))), 8_000)
  }, [days.data])

  /** Replay the day: every message again, in order, faster. */
  const replay = async () => {
    if (!items.length || replaying) return
    setReplaying(true)
    setShown(new Set())
    // A replay opens with Mesiri's hello, at its own pace.
    if (!playing.current && !greeting.current) await showMeet(null, true)
    queue.current = [...items]
    speed.current = REPLAY_SPEED
    void play()
  }

  /** Mesiri says hello on demand ("Meet Mesiri"), when nothing else is playing. */
  const meet = async () => {
    if (playing.current || greeting.current) return
    await showMeet(null, false)
  }

  // Presenter mode: full screen, larger, the QR code to message Mesiri.
  const [presenting, setPresenting] = React.useState(false)
  const [telling, setTelling] = React.useState(false)
  const present = async (on: boolean) => {
    setPresenting(on)
    try {
      if (on && !document.fullscreenElement) await document.documentElement.requestFullscreen?.()
      if (!on && document.fullscreenElement) await document.exitFullscreen?.()
    } catch {
      // Full screen refused (an iframe, a browser setting): presenter mode still works in the window.
    }
  }
  React.useEffect(() => {
    const left = () => {
      if (!document.fullscreenElement) setPresenting(false)
    }
    document.addEventListener('fullscreenchange', left)
    return () => document.removeEventListener('fullscreenchange', left)
  }, [])

  const number = setup.data?.whatsapp_number ?? null
  const qrLink = number ? `https://wa.me/${number.replace(/\D/g, '')}?text=${encodeURIComponent('Hi Mesiri')}` : null

  const stream = [...samples].reverse().concat(items.filter((m) => shown.has(m.id)).reverse())
  const sampleSite = sites[0]?.site_name ?? 'Villa 3'
  const onScene = React.useCallback(
    (scene: SceneKey) => {
      const now = new Date().toISOString()
      const add = (MEET_SAMPLES[scene] ?? []).map(
        (x, n): LiveFeedItem => ({
          id: `sample-${scene}-${n}-${now}`,
          type: x.voice ? 'voice' : 'text',
          text: x.text.replace('{site}', sampleSite),
          translated_text: null,
          reply: x.reply.replace('{site}', sampleSite),
          received_at: now,
          project_id: null,
          site_id: null,
          site_name: sampleSite,
          project_name: null,
          sender_name: x.sender,
          source: 'sample',
          media_url: null,
          kind: x.kind,
          label: x.label,
          state: x.state,
          summaries: [],
          asked: null,
          saved_kind: null,
          did: [],
          transfer: null,
          first_message: false,
          expense: null,
          language: null,
        }),
      )
      if (add.length) setSamples((all) => [...all, ...add])
    },
    [sampleSite],
  )
  const totals = {
    workers: sites.reduce((n, s) => n + (s.workers || 0), 0),
    messages: items.filter((m) => shown.has(m.id)).length,
    saved: items.filter((m) => shown.has(m.id) && m.state === 'saved').length,
    issues: sites.reduce((n, s) => n + (s.open_issues || 0), 0),
    reported: sites.filter((s) => s.last_update_at).length,
  }
  const company = branding.data?.company_name
  // The moment for what Mesiri is handling now (moments.tsx), if its kind has one.
  const moment: 'bill' | 'language' | 'asked' | 'answer' | null = (() => {
    if (!current || (current.alarm && current.step === 'done')) return null
    const m = current.item
    if (isBill(m)) return 'bill'
    if (m.kind === 'language' && (current.step === 'understood' || current.step === 'done')) return 'language'
    if (current.step === 'done' && m.state === 'asked' && m.asked) return 'asked'
    if (current.step === 'done' && m.kind === 'question' && m.reply) return 'answer'
    return null
  })()
  const answers = current ? qa.of.get(current.item.id) ?? null : null

  const openSite = (s: SiteDayItem, el: HTMLElement) =>
    cinematic.go({
      from: el.getBoundingClientRect(),
      to: `/live?project=${s.project_id}&site=${s.site_id}${isToday ? '' : `&date=${date}`}`,
      title: s.site_name,
      kicker: [s.project_name, longDate(date)].filter(Boolean).join(' · '),
    })

  return (
    <div className={cn('min-h-svh bg-background px-4 pb-6 sm:px-8 sm:pb-24 lg:px-12', presenting && 'text-[1.12rem]')}>
      <div className="mx-auto max-w-[1600px]">
        <header className="flex flex-wrap items-center justify-between gap-x-6 gap-y-3 pt-6 pb-4">
          <div className="flex items-baseline gap-4">
            <MesiriWordmark className={presenting ? 'text-2xl' : 'text-lg'} />
            <Label className="flex items-center gap-2">
              <span className="relative flex size-2" aria-hidden="true">
                <span className="absolute inline-flex size-full animate-ping rounded-full bg-primary opacity-60 motion-reduce:animate-none" />
                <span className="relative inline-flex size-2 rounded-full bg-primary" />
              </span>
              Live{company ? ` · ${company}` : ''} · {longDate(date)}
            </Label>
          </div>
          <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
            {!presenting && (
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
            )}
            <button
              type="button"
              onClick={() => void meet()}
              disabled={!!hello || !!current}
              className="flex items-center gap-2 border border-foreground px-4 py-2 text-sm font-medium hover:bg-foreground hover:text-background disabled:opacity-40"
            >
              <Hand className="size-4" /> Meet Mesiri
            </button>
            <button
              type="button"
              onClick={() => void replay()}
              disabled={!items.length || replaying}
              className="flex items-center gap-2 border border-foreground px-4 py-2 text-sm font-medium hover:bg-foreground hover:text-background disabled:opacity-40"
            >
              <Play className="size-4" /> {replaying ? 'Replaying…' : 'Replay the day'}
            </button>
            <button
              type="button"
              onClick={() => void present(!presenting)}
              className="flex items-center gap-2 bg-primary px-4 py-2 text-sm font-medium text-primary-foreground"
            >
              {presenting ? <X className="size-4" /> : <Monitor className="size-4" />}
              {presenting ? 'Leave presenter mode' : 'Presenter mode'}
            </button>
            {!presenting && (
              <Link to="/today" className="border-b border-foreground font-mono text-[11px] uppercase tracking-[0.06em]">
                Exit
              </Link>
            )}
          </div>
        </header>
        <div className="h-px bg-foreground" />

        {telling && !presenting && (
          <div className="mt-6 border border-foreground px-4 py-4 animate-in fade-in slide-in-from-top-2 duration-300 motion-reduce:animate-none">
            <Label className="block pb-3">Tell Mesiri · speak or type, and watch the Spark take it</Label>
            <TellMesiri compact />
          </div>
        )}

        {feed.isError ? (
          <p className="py-10 text-sm text-muted-foreground">Could not read the company's messages. Trying again…</p>
        ) : (
          <div
            className={cn(
              'mt-8 grid gap-10 transition-[grid-template-columns] duration-700',
              hello
                ? 'lg:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)] xl:grid-cols-[minmax(320px,0.75fr)_minmax(0,2fr)_minmax(220px,0.55fr)]'
                : 'lg:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)] xl:grid-cols-[minmax(300px,0.9fr)_minmax(0,1.2fr)_minmax(280px,0.9fr)]',
            )}
          >
            {/* The messages, newest first */}
            <section aria-label="Messages" className="order-2 min-w-0 lg:order-1">
              <Label>Messages · {totals.messages} today</Label>
              {feed.isLoading ? (
                <p className="mt-4 text-sm text-muted-foreground">Loading…</p>
              ) : stream.length === 0 ? (
                <p className="mt-4 text-sm text-muted-foreground">
                  Nothing yet today. Send Mesiri a message on WhatsApp and watch it arrive here.
                </p>
              ) : (
                <ol className="m-0 mt-4 grid list-none gap-3 p-0" aria-live="polite">
                  {stream.slice(0, 40).map((m) => (
                    <MessageCard key={m.id} m={m} active={current?.item.id === m.id} answers={qa.of.get(m.id) ?? null} answered={qa.answered.has(m.id)} />
                  ))}
                </ol>
              )}
            </section>

            {/* The Spark, handling one message at a time */}
            <section
              aria-label="Mesiri"
              className={cn('order-1 min-w-0 lg:order-2', current?.alarm && 'relative z-40', hello && 'lg:col-span-2 lg:order-1 xl:col-span-1 xl:order-2')}
            >
              {hello ? (
                <div className="sticky top-6 border-2 border-foreground bg-background px-4 py-5 sm:px-7 sm:py-6">
                  <MeetMesiri
                    to={hello.to}
                    short={hello.short}
                    site={sites[0]?.site_name ?? null}
                    number={number}
                    presenting={presenting}
                    onScene={onScene}
                    onDone={() => helloDone.current?.()}
                  />
                </div>
              ) : (
              <div className="sticky top-6 grid bg-background justify-items-center gap-4 border border-foreground/15 px-4 py-5 text-center sm:gap-5 sm:px-6 sm:py-8">
                <div ref={sparkRef}>
                  <Spark
                    mood={current ? sparkMood(current.item, current.step, current.alarm) : 'idle'}
                    beat={beat}
                    size={moment ? (presenting ? 140 : 110) : presenting ? 220 : 170}
                  />
                </div>
                <div className={cn('min-h-[5.5rem] sm:min-h-[7.5rem]', moment === 'bill' ? 'w-full max-w-[44rem]' : 'max-w-[34rem]')} aria-live="polite">
                  {current ? (
                    <>
                      <Label className={cn('block', current.alarm && current.step === 'done' && 'text-[var(--destructive)]')}>
                        {current.alarm && current.step === 'done' ? 'Mesiri noticed' : STEP_LABEL[current.step]}
                      </Label>
                      {answers && current.step !== 'done' && (
                        <p className="m-0 mt-2 inline-block border border-foreground/30 px-2 py-0.5 text-[13px] text-muted-foreground" style={prefersReducedMotion() ? undefined : { animation: 'live-in 400ms ease-out' }}>
                          ↳ Answer to Mesiri: “{short(answers, 70)}”
                        </p>
                      )}
                      {current.step === 'read' && isVoice(current.item) && (
                        <div className="mt-3">
                          <Waveform big={presenting} />
                        </div>
                      )}
                      {moment === 'bill' && (
                        <div className="mt-3">
                          <BillMoment item={current.item} step={current.step} presenting={presenting} />
                        </div>
                      )}
                      {moment === 'language' && (
                        <div className="mt-3">
                          <LanguageMoment language={current.item.language} presenting={presenting} />
                        </div>
                      )}
                      {moment === 'asked' && (
                        <div className="mt-3">
                          <AskedMoment question={current.item.asked ?? ''} who={current.item.sender_name?.split(/\s+/)[0] ?? null} presenting={presenting} />
                        </div>
                      )}
                      {moment === 'answer' && (
                        <div className="mt-3 grid justify-items-center">
                          <AnswerMoment reply={current.item.reply ?? ''} presenting={presenting} />
                        </div>
                      )}
                      {(moment !== 'asked' && moment !== 'answer' && moment !== 'language') || current.step !== 'done' ? (
                      <p
                        key={`${current.item.id}-${current.step}`}
                        className={cn(
                          'm-0 mt-2 font-medium tracking-[-0.01em]',
                          presenting ? 'text-[30px] leading-[1.25]' : 'text-[22px] leading-[1.3]',
                          current.step === 'done' && (current.item.state === 'failed' || current.alarm) && 'text-[var(--destructive)]',
                        )}
                      >
                        {current.step === 'understood' && current.item.text && current.item.translated_text && current.item.translated_text !== current.item.text ? (
                          <Flip from={current.item.text} to={current.item.translated_text} />
                        ) : (
                          <Typed text={sparkSays(current.item, current.step, current.alarm)} />
                        )}
                      </p>
                      ) : null}
                    </>
                  ) : (
                    <>
                      <Label className="block">Mesiri · listening</Label>
                      <p className={cn('m-0 mt-2 text-muted-foreground', presenting ? 'text-[26px]' : 'text-lg')}>
                        Waiting for the next message from site…
                      </p>
                    </>
                  )}
                </div>
                <Steps step={current?.step ?? null} />
                <Did current={current} />
                {presenting && qrLink && (
                  <div className="mt-2 flex items-center gap-5 border-t border-foreground/15 pt-6 text-left">
                    <QrCode value={qrLink} label={`QR code to message Mesiri at ${number}`} className="size-36 shrink-0" />
                    <div>
                      <p className="m-0 flex items-center gap-2 text-xl font-semibold">
                        <WhatsAppIcon className="size-5" /> Send Mesiri a message
                      </p>
                      <p className="m-0 mt-1 text-base text-muted-foreground">
                        Scan, send anything about site, and watch it land here. {number}
                      </p>
                      <p className="m-0 mt-1 text-sm text-muted-foreground">Only numbers on this company's team are filed.</p>
                    </div>
                  </div>
                )}
              </div>
              )}
            </section>

            {/* The sites */}
            <section aria-label="Sites" className="order-3 min-w-0 lg:col-span-2 xl:col-span-1">
              <Label>Sites · {totals.reported} of {sites.length} heard from</Label>
              <ul className="m-0 mt-4 grid list-none grid-cols-1 gap-3 p-0 sm:grid-cols-2 xl:grid-cols-1">
                {sites.map((s) => (
                  <li key={s.site_id}>
                    <button
                      type="button"
                      ref={(el) => {
                        if (el) siteRefs.current.set(s.site_id, el)
                        else siteRefs.current.delete(s.site_id)
                      }}
                      onClick={(e) => openSite(s, e.currentTarget)}
                      className={cn(
                        'relative grid w-full gap-2 border bg-background px-4 py-3 text-left transition-colors hover:border-foreground',
                        ringing.get(s.site_id) === 'alarm' ? 'z-40 border-[var(--destructive)]' : newSites.has(s.site_id) ? 'border-primary' : 'border-foreground/20',
                      )}
                      style={
                        prefersReducedMotion()
                          ? undefined
                          : ringing.get(s.site_id) === 'alarm'
                            ? { animation: 'live-shake 600ms ease-out 2' }
                            : ringing.has(s.site_id)
                              ? { animation: 'live-land 1.4s ease-out' }
                              : newSites.has(s.site_id)
                                ? { animation: 'live-pop 900ms cubic-bezier(.3,1.5,.5,1) both' }
                                : undefined
                      }
                    >
                      {newSites.has(s.site_id) && (
                        <span className="absolute -top-2.5 right-3 bg-primary px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.06em] text-primary-foreground">
                          New site
                        </span>
                      )}
                      <span className="flex items-baseline justify-between gap-3">
                        <span className="truncate text-[15px] font-semibold">{s.site_name}</span>
                        <span className="shrink-0 font-mono text-[11px] text-muted-foreground">
                          {s.last_update_at ? clock(s.last_update_at) : 'not yet'}
                        </span>
                      </span>
                      <span className="truncate text-xs text-muted-foreground">{s.project_name}</span>
                      <span className="flex flex-wrap gap-x-4 gap-y-1 font-mono text-[12px]">
                        <Stat n={s.workers} what={s.workers === 1 ? 'worker' : 'workers'} />
                        <Stat n={s.work_items + s.progress_updates} what="work" />
                        <Stat n={s.materials} what="materials" />
                        {s.open_issues > 0 && <Stat n={s.open_issues} what={s.open_issues === 1 ? 'issue' : 'issues'} warn />}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          </div>
        )}
      </div>

      {/* The company's day, counting up */}
      <footer
        className={cn(
          '-mx-4 mt-10 border-t border-foreground bg-background/95 backdrop-blur transition-transform duration-500 sm:fixed sm:inset-x-0 sm:bottom-0 sm:z-40 sm:mx-0 sm:mt-0',
          hello && 'sm:translate-y-full',
        )}
      >
        <div className="mx-auto flex max-w-[1600px] flex-wrap items-baseline justify-between gap-x-8 gap-y-1 px-4 py-3 sm:px-8 lg:px-12">
          <Total n={totals.workers} what={totals.workers === 1 ? 'worker on site' : 'workers on site'} big={presenting} />
          <Total n={totals.messages} what={totals.messages === 1 ? 'message' : 'messages'} big={presenting} />
          <Total n={totals.saved} what={totals.saved === 1 ? 'entry saved' : 'entries saved'} big={presenting} />
          <Total n={totals.issues} what={totals.issues === 1 ? 'open issue' : 'open issues'} big={presenting} />
          <Total n={totals.reported} what={`of ${sites.length} sites heard from`} big={presenting} />
        </div>
      </footer>

      {current?.alarm && current.step === 'done' && (
        <div
          aria-hidden="true"
          className="fixed inset-0 z-30 bg-foreground/35 animate-in fade-in duration-300 motion-reduce:animate-none"
        />
      )}
      {flights.map((f) => (
        <Flyer key={f.key} flight={f} onDone={() => setFlights((all) => all.filter((x) => x.key !== f.key))} />
      ))}
      {cinematic.overlay}
    </div>
  )
}

const STEP_LABEL: Record<Step, string> = {
  arrive: 'New message',
  read: 'Mesiri',
  understood: 'Understood',
  done: 'Done',
}

/** Heard → understood → done, lighting up as the Spark goes. */
function Steps({ step }: { step: Step | null }) {
  const order: Step[] = ['arrive', 'read', 'understood', 'done']
  const at = step ? order.indexOf(step) : -1
  return (
    <ol className="m-0 flex list-none items-center gap-2 p-0 font-mono text-[11px] uppercase tracking-[0.06em]" aria-hidden="true">
      {['Heard', 'Reading', 'Understood', 'Done'].map((w, i) => (
        <li key={w} className="flex items-center gap-2">
          {i > 0 && <span className={cn('h-px w-6 transition-colors duration-500', i <= at ? 'bg-primary' : 'bg-foreground/20')} />}
          <span className={cn('transition-colors duration-500', i <= at ? 'text-primary' : 'text-muted-foreground')}>{w}</span>
        </li>
      ))}
    </ol>
  )
}

/** What Mesiri did along the way, lighting up one by one. */
function Did({ current }: { current: Current | null }) {
  const did = current && current.step !== 'arrive' ? current.item.did : []
  const at = current?.step === 'read' ? 1 : current?.step === 'understood' ? Math.ceil(did.length / 2) + 1 : did.length
  if (!did.length) return <div className="h-5" aria-hidden="true" />
  return (
    <p className="m-0 flex min-h-5 flex-wrap items-center justify-center gap-x-2 gap-y-1 text-[13px]" aria-live="polite">
      {did.map((d, i) => (
        <span
          key={d}
          className={cn('transition-[color,opacity] duration-500', i < at ? 'text-foreground opacity-100' : 'text-muted-foreground opacity-40')}
        >
          {i > 0 && <span className="mr-2 text-muted-foreground">→</span>}
          {d}
        </span>
      ))}
    </p>
  )
}

function Stat({ n, what, warn }: { n: number; what: string; warn?: boolean }) {
  return (
    <span className={cn(warn ? 'text-[var(--destructive)]' : n ? 'text-foreground' : 'text-muted-foreground')}>
      <CountTo value={n} /> {what}
    </span>
  )
}

function Total({ n, what, big }: { n: number; what: string; big: boolean }) {
  return (
    <span className="flex items-baseline gap-2">
      <span className={cn('font-semibold tabular-nums tracking-[-0.02em]', big ? 'text-4xl' : 'text-2xl')}>
        <CountTo value={n} />
      </span>
      <span className="text-sm text-muted-foreground">{what}</span>
    </span>
  )
}

const STATE_CHIP: Record<LiveFeedItem['state'], { text: string; className: string } | null> = {
  saved: { text: '✅ Saved', className: 'text-[var(--success)]' },
  draft: { text: 'Waiting for Save', className: 'text-[var(--draft)]' },
  asked: { text: 'Mesiri asked back', className: 'text-[var(--ai)]' },
  answered: { text: 'Answered', className: 'text-[var(--ai)]' },
  failed: { text: 'Not saved', className: 'text-[var(--destructive)]' },
  heard: null,
}

function MessageCard({ m, active, answers, answered }: { m: LiveFeedItem; active: boolean; answers: string | null; answered: boolean }) {
  const look = KINDS[m.saved_kind && m.kind === 'saved' ? m.saved_kind : m.kind]
  const Icon = look.icon
  const chip = m.state === 'asked' ? (answered ? { text: 'Answered ✓', className: 'text-[var(--success)]' } : { text: 'Waiting for answer', className: 'text-[var(--draft)]' }) : STATE_CHIP[m.state]
  const english = m.translated_text && m.translated_text !== m.text ? m.translated_text : null
  return (
    <li
      className={cn(
        'grid gap-2 border px-4 py-3 transition-[border-color,background-color] duration-500',
        active ? 'border-primary bg-[color-mix(in_srgb,var(--primary)_6%,transparent)]' : 'border-foreground/15',
        m.source === 'sample' && 'border-dashed border-foreground/40',
      )}
      style={prefersReducedMotion() ? undefined : { animation: 'live-in 500ms ease-out' }}
    >
      <div className="flex items-center gap-3">
        <span className="grid size-8 shrink-0 place-items-center rounded-full bg-foreground text-[12px] font-semibold text-background">
          {initials(m.sender_name)}
        </span>
        <div className="min-w-0 flex-1">
          <p className="m-0 truncate text-sm font-semibold">{m.sender_name ?? 'Unknown number'}</p>
          <p className="m-0 truncate text-xs text-muted-foreground">
            {[m.site_name ?? m.project_name, clock(m.received_at)].filter(Boolean).join(' · ')}
          </p>
        </div>
        <span className={cn('flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-1 text-[12px] font-medium', TONES[look.tone])}>
          <Icon className="size-3.5" aria-hidden="true" /> {m.kind === 'saved' ? 'Saved' : m.label}
        </span>
      </div>
      {m.media_url && (
        <img
          src={m.media_url}
          alt="Photo from site"
          className="max-h-48 w-full object-cover"
          style={active && !prefersReducedMotion() ? { animation: 'live-develop 1.6s ease-out both' } : undefined}
        />
      )}
      {(m.text || isVoice(m)) && (
        <p className="m-0 text-[15px] leading-snug">
          {isVoice(m) && <Mic className="mr-1.5 inline size-4 align-[-2px] text-primary" aria-label="Voice note" />}
          {short(m.text, 220)}
        </p>
      )}
      {answers && <p className="m-0 text-[12px] text-muted-foreground">↳ Answer to Mesiri: “{short(answers, 80)}”</p>}
      {english && <p className="m-0 text-sm italic text-muted-foreground">“{short(english, 220)}”</p>}
      {m.state === 'asked' && m.asked && <p className="m-0 text-[13px] font-medium">Mesiri asked: {short(m.asked, 140)}</p>}
      {m.reply && m.reply !== m.asked && (
        <div className="flex items-start gap-2 border-l-2 border-foreground/20 pl-3">
          <Spark mood="idle" quiet size={22} className="mt-0.5 shrink-0" label="Mesiri's reply" />
          <p className="m-0 text-sm leading-snug text-muted-foreground">{short(m.reply, 200)}</p>
        </div>
      )}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
          {m.source === 'sample' ? 'Sample · Meet Mesiri' : m.source === 'dashboard' ? 'Mesiri web' : <><WhatsAppIcon className="size-3" /> WhatsApp</>}
        </span>
        {chip && <span className={cn('text-[12px] font-medium', chip.className)}>{chip.text}</span>}
      </div>
    </li>
  )
}
