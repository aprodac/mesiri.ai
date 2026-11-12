import * as React from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle,
  ArrowRight,
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
  Sparkles,
  Truck,
  Undo2,
  Volume2,
  VolumeX,
  X,
  XCircle,
} from 'lucide-react'
import {
  fetchBranding,
  fetchEffectsApi,
  fetchJoining,
  fetchLiveBoardApi,
  fetchLiveFeedApi,
  fetchLiveStampApi,
  fetchSiteDayApi,
  fetchSetupProgress,
  fetchSiteDaysApi,
  type LiveBoardKey,
  type EffectCard,
  type EntryEffects,
  type LiveFeedItem,
  type LiveKind,
  type LiveRecord,
  type ProjectDayItem,
} from '@/lib/api'
import { noticeOf } from '@/lib/live-reading'
import { longDate } from '@/lib/site-day'
import { prefersReducedMotion } from '@/lib/timeline'
import { cn } from '@/lib/utils'
import { MesiriWordmark } from '@/components/brand/mesiri-logo'
import { WhatsAppIcon } from '@/components/brand/whatsapp-icon'
import { Label } from '@/components/onboarding/conversation'
import { TellMesiri } from '@/components/tell-mesiri/tell-mesiri'
import { CountTo } from './ink'
import { LIVE_MODULES, useCinematicGo } from './modules'
import { OwnerBoard, questionsOf } from './board'
import { useModuleEnabled, type ModuleKey } from '@/lib/modules'
import { MEET_SAMPLES, MeetMesiri, type SceneKey } from './meet'
import { Finale } from './finale'
import { Joining, joiningLine } from './joining'
import { ProjectSheet, ReportStrip, SHEET_MS } from './report'
import { AnswerMoment, AskedMoment, BillMoment, ChatMoment, EntryCard, LanguageMoment, answers as answersOf, cleanReply, languageLine, outcomes } from './moments'
import { useVoice } from '@/lib/voice'
import { Spark, type SparkMood } from './spark'
import { RIPPLE_CARD_MS, RIPPLE_END_MS, Ripple } from './ripple'

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

/** WEB-69: how often Live asks whether anything changed (a tiny count); the feed is read only when it did. */
const STAMP_POLL_MS = 1_000
/** A backstop read of the feed, in case a change slipped past the stamp. */
const FEED_POLL_MS = 15_000
const SITES_POLL_MS = 10_000
/** WEB-83: the owner's board is read again when a message lands, and this often besides (the web changes it too). */
const BOARD_POLL_MS = 60_000
/** WEB-71: who is joining; a few seconds, so an Approve tap shows while the room watches. */
const JOINING_POLL_MS = 3_000
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
  intro: { icon: Sparkles, goes: null, tone: 'info' },
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

/** Where Mesiri's work goes (WEB-59): the module pages, the company Live's right column. The first four are the site
 * Live's own (LIVE_MODULES); a message flies to the one that keeps what it said, and each opens its page. */
type DestKey = 'labour' | 'work' | 'materials' | 'issues' | 'expenses' | 'reports' | 'projects'
interface Dest {
  key: DestKey
  name: string
  keeps: string
  path: string
  icon: LucideIcon
  module?: ModuleKey
}
const DESTS: Dest[] = [
  ...LIVE_MODULES.map((m) => ({ key: m.section as DestKey, name: m.name, keeps: m.keeps, path: m.path, icon: m.icon, module: m.module })),
  { key: 'expenses', name: 'Expenses', keeps: 'Money spent, with the bills', path: '/finance/expenses', icon: IndianRupee, module: 'finance' },
  { key: 'reports', name: 'Daily reports', keeps: 'Each site’s report, sent at the day’s end', path: '/reports', icon: FileText, module: 'dpr' },
  { key: 'projects', name: 'Projects & sites', keeps: 'Sites, people, report time', path: '/projects', icon: Flag },
]
const KIND_DEST: Partial<Record<LiveKind, DestKey>> = {
  attendance: 'labour',
  work: 'work',
  correction: 'work',
  delivery: 'materials',
  usage: 'materials',
  transfer: 'materials',
  catalogue: 'materials',
  issue: 'issues',
  issue_closed: 'issues',
  expense: 'expenses',
  report: 'reports',
  setup: 'projects',
}
/** What a question looked up, from what Mesiri did ("Checked the stock" → Materials). */
const LOOKUP_DEST: [RegExp, DestKey][] = [
  [/stock|material|came in|used/i, 'materials'],
  [/attendance|workers/i, 'labour'],
  [/work/i, 'work'],
  [/issue/i, 'issues'],
  [/expense|account|vendor/i, 'expenses'],
  [/report|day’s updates|who reported/i, 'reports'],
  [/project|site/i, 'projects'],
]
/** WEB-82: the module a ripple card's page belongs to (it rings as the card plays). */
const PATH_DEST: [RegExp, DestKey][] = [
  [/^\/(materials|procurement)/, 'materials'],
  [/^\/labour/, 'labour'],
  [/^\/reports/, 'reports'],
  [/^\/(finance|cost)/, 'expenses'],
]
/** A move in a ripple: on to the next card, back one, to the closing count, to a card, or out. */
type RippleMove = 'next' | 'back' | 'end' | 'close' | number

/** The module a message's work went to, if any. */
function destOf(m: LiveFeedItem): Dest | null {
  const key =
    KIND_DEST[m.kind === 'saved' && m.saved_kind ? m.saved_kind : m.kind] ??
    (m.kind === 'question' ? LOOKUP_DEST.find(([re]) => m.did.some((d) => re.test(d)))?.[1] : undefined)
  return DESTS.find((d) => d.key === key) ?? null
}

const isVoice = (m: LiveFeedItem) => /voice|audio/.test(m.type)
/** WEB-63: what Mesiri says out loud when it is done with a message; null to stay quiet. Short: a moment's line. */
function spokenLine(m: LiveFeedItem, alarm: string | null): string | null {
  const first = m.sender_name?.split(/\s+/)[0]
  const lines = m.summaries.slice(0, 3).join(', ')
  if (alarm) return `Wait. ${alarm}`
  if (m.kind === 'intro') return null // the show speaks for itself
  if (isBill(m)) {
    const amount = Number(m.expense?.amount)
    const what = [m.expense?.vendor ? `A bill from ${m.expense.vendor}` : 'A bill', Number.isFinite(amount) ? `${amount.toLocaleString('en-IN')} rupees` : null]
    return `${what.filter(Boolean).join(': ')}.${m.state === 'draft' ? ' Tap save.' : ''}`
  }
  if (m.kind === 'language') return languageLine(m.language)
  if (m.state === 'asked' && m.asked) return cleanReply(m.asked)
  if (m.state === 'failed') return 'That could not be saved.'
  const card = cardAs(m)
  if (card === 'draft') return `${first ? `${first}, ` : ''}${lines}. Ready. Tap save.`
  if (card === 'saved') return `Saved. ${lines}.`
  if (card === 'cancelled') return 'Cancelled. Nothing was saved.'
  if (card === 'undone') return `Taken back. ${m.summaries[0] ?? ''}`
  if (m.kind === 'question' || m.kind === 'chat') return short(cleanReply(m.reply), 220) || null
  return null
}

/** WEB-65: what Mesiri is doing with a message it is still working on. */
function workingLine(m: LiveFeedItem): string {
  const who = m.sender_name?.split(/\s+/)[0] ?? 'Someone'
  const where = m.site_name ? ` from ${m.site_name}` : ''
  if (isVoice(m)) return `Listening to ${who}’s voice note${where}…`
  if (isPhoto(m)) return `Reading ${who}’s photo${where}…`
  if (m.type === 'interactive') return `${who} tapped a button…`
  return `Reading ${who}’s message${where}…`
}

/** WEB-62: the card a message's entries are on, and what became of them; null when it has no card. */
function cardAs(m: LiveFeedItem): 'draft' | 'saved' | 'cancelled' | 'undone' | null {
  if (isBill(m)) return null
  if (m.kind === 'cancelled' && m.summaries.length) return 'cancelled'
  if (m.kind === 'undo') return m.summaries.length ? 'undone' : null
  if (!m.summaries.length) return null
  if (m.state === 'draft') return 'draft'
  if (m.state === 'saved') return 'saved'
  return null
}
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
  // The bill's own line (the reply can be a bare "Tap Save to record these.").
  if (isBill(m) && m.summaries[0]) return m.state === 'saved' ? `Saved: ${m.summaries[0]}` : `${m.summaries[0]}. Waiting for ✅ Save.`
  if (isBill(m) && m.reply) return short(cleanReply(m.reply), 160)
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
      return short(cleanReply(m.reply), 160) || 'Answered'
    default:
      return short(cleanReply(m.reply), 160) || 'Got it'
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
  // onDone is a fresh function each render: a ref, so a re-render never restarts the flight.
  const done = React.useRef(onDone)
  done.current = onDone
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
    anim.onfinish = () => done.current()
    return () => anim.cancel()
  }, [flight])
  return (
    <span
      ref={ref}
      aria-hidden="true"
      className="pointer-events-none fixed left-0 top-0 z-50 -ml-2 -mt-2 size-4 rounded-full border-2 border-foreground bg-primary"
    />
  )
}

export function CompanyLive({
  date,
  isToday,
  sitePanel,
  onCloseSite,
}: {
  date: string
  isToday: boolean
  /** A site's own Live report, shown in a panel over the company Live (?site=…). */
  sitePanel: React.ReactNode
  onCloseSite: () => void
}) {
  const [, setParams] = useSearchParams()
  const moduleEnabled = useModuleEnabled()
  /** WEB-63: Mesiri's voice: on in presenter mode, Mute turns it off. */
  const voice = useVoice()
  const say = voice.say
  const [since, until] = React.useMemo(() => dayWindow(date), [date])
  const feed = useQuery({
    queryKey: ['live-feed', date],
    queryFn: () => fetchLiveFeedApi(since, until),
    refetchInterval: isToday ? FEED_POLL_MS : false,
    retry: false,
  })
  // A message came in, or Mesiri finished one: read the feed now, not on the next round.
  const stamp = useQuery({
    queryKey: ['live-stamp', date],
    queryFn: () => fetchLiveStampApi(since, until),
    refetchInterval: isToday ? STAMP_POLL_MS : false,
    retry: false,
  })
  const lastStamp = React.useRef<string | undefined>(undefined)
  React.useEffect(() => {
    if (!stamp.data || stamp.data === lastStamp.current) return
    const first = lastStamp.current === undefined
    lastStamp.current = stamp.data
    if (!first) void feed.refetch()
  }, [stamp.data, feed])
  const days = useQuery({
    queryKey: ['live-site-days', date, null],
    queryFn: () => fetchSiteDaysApi(date),
    refetchInterval: isToday ? SITES_POLL_MS : false,
  })
  const branding = useQuery({ queryKey: ['company-branding'], queryFn: fetchBranding, retry: false, staleTime: 10 * 60_000 })
  const setup = useQuery({ queryKey: ['setup-progress'], queryFn: fetchSetupProgress, retry: false, staleTime: 10 * 60_000 })
  // WEB-71: the join code the QR code sends, and who is joining (admins only: anyone else keeps "Hi Mesiri").
  const joining = useQuery({
    queryKey: ['live-joining'],
    queryFn: fetchJoining,
    refetchInterval: isToday ? JOINING_POLL_MS : false,
    retry: false,
  })
  // WEB-83: the owner's board: six answers from the modules' own reads, as of now (whatever day is shown).
  const board = useQuery({
    queryKey: ['live-board'],
    queryFn: fetchLiveBoardApi,
    refetchInterval: isToday ? BOARD_POLL_MS : false,
    retry: false,
  })
  const boardData = React.useRef(board.data)
  boardData.current = board.data
  const boardRefs = React.useRef(new Map<LiveBoardKey, HTMLElement>())
  const cinematic = useCinematicGo()

  const items = React.useMemo(() => feed.data ?? [], [feed.data])
  /** Which message answers which question Mesiri asked back. */
  const qa = React.useMemo(() => answersOf(items), [items])
  /** What each waiting card became (Save or Cancel tapped later). */
  const became = React.useMemo(() => outcomes(items), [items])
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
  /** WEB-82: the ripple on the stage: what the entry just saved changed, one card at a time. */
  const [ripple, setRipple] = React.useState<{ item: LiveFeedItem; effects: EntryEffects; at: number; held: boolean } | null>(null)
  /** The presenter's hand on it: hold it on a card, or move it (Space, ← →, S, Esc, a click). */
  const rippleCtl = React.useRef<{ held: boolean; move: ((to: RippleMove | 'hold') => void) | null }>({ held: false, move: null })
  const queue = React.useRef<LiveFeedItem[]>([])
  const playing = React.useRef(false)
  const seeded = React.useRef(false)
  /** What was already there when Live opened: counted, not shown, never played (until Replay the day). */
  const before = React.useRef(new Set<string>())
  /** Replay plays faster. */
  const speed = React.useRef(1)
  const sparkRef = React.useRef<HTMLDivElement>(null)
  const destRefs = React.useRef(new Map<DestKey, HTMLElement>())
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

  /** WEB-82: play what one saved record changed: each card in turn, then the closing count. */
  const playRipple = React.useCallback(
    async (item: LiveFeedItem, record: LiveRecord, pace: number) => {
      let effects: EntryEffects
      try {
        effects = await queryClient.fetchQuery({
          queryKey: ['live-effects', record.kind, record.id],
          queryFn: () => fetchEffectsApi(record.kind, record.id),
          staleTime: 0,
        })
      } catch {
        return // no ripple to show (taken back, or not this viewer's site): the message has played
      }
      const n = effects.cards.length
      if (!n) return
      rippleCtl.current.held = false
      let at = 0
      for (;;) {
        setRipple({ item, effects, at, held: rippleCtl.current.held })
        const card = effects.cards[at]
        const dest = card?.opens ? PATH_DEST.find(([re]) => re.test(card.opens!))?.[1] : undefined
        if (dest) ring(dest, card.tag === 'caught' ? 'alarm' : 'land', 300)
        // WEB-83: the card lands on the owner's question it answers (the board's questions are in the plan's order, 1 to 6).
        const asks = card ? boardData.current?.questions[card.question - 1]?.key : undefined
        if (asks) ring(`q:${asks}`, card.tag === 'caught' ? 'alarm' : 'land', 300)
        const here = at
        const move = await new Promise<RippleMove>((resolve) => {
          let timer: number | undefined
          const arm = () => {
            if (!rippleCtl.current.held) timer = window.setTimeout(() => resolve('next'), (here >= n ? RIPPLE_END_MS : RIPPLE_CARD_MS) * pace)
          }
          rippleCtl.current.move = (to) => {
            window.clearTimeout(timer)
            if (to === 'hold') {
              rippleCtl.current.held = !rippleCtl.current.held
              setRipple((r) => (r ? { ...r, held: rippleCtl.current.held } : r))
              arm()
              return
            }
            resolve(to)
          }
          arm()
        })
        if (move === 'close' || (at >= n && move === 'next')) break
        at = move === 'next' ? at + 1 : move === 'back' ? Math.max(0, at - 1) : move === 'end' ? n : Math.min(n, Math.max(0, move))
        if (at === n && speed.current === 1) say(`One message. ${n} ${n === 1 ? 'thing' : 'things'} you now know.`)
      }
      rippleCtl.current = { held: false, move: null }
      setRipple(null)
    },
    [queryClient, ring, say],
  )

  const play = React.useCallback(async () => {
    if (playing.current) return
    playing.current = true
    const wait = (ms: number) => new Promise((r) => window.setTimeout(r, prefersReducedMotion() ? 0 : ms * speed.current))
    while (queue.current.length) {
      while (greeting.current) await new Promise((r) => window.setTimeout(r, 300))
      const item = queue.current.shift()!
      const live = speed.current === 1
      // WEB-60: they asked what Mesiri can do: the message comes in, then Mesiri's whole introduction plays for them,
      // then its own answer, as a conversation.
      if (live && item.kind === 'intro') {
        setShown((s) => new Set(s).add(item.id))
        setBeat((b) => b + 1)
        setCurrent({ item, step: 'arrive', alarm: null })
        await wait(STEP_MS)
        setCurrent(null)
        await showMeet(item.sender_name?.split(/\s+/)[0] ?? null, false)
        setCurrent({ item, step: 'done', alarm: null })
        await wait(STEP_MS + 3_000)
        continue
      }
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
      if (live) say(spokenLine(item, alarm))
      const from = sparkRef.current?.getBoundingClientRect()
      const fly = (a: DOMRect | undefined, b: DOMRect | undefined, delay = 0) => {
        if (a && b && !prefersReducedMotion()) setFlights((f) => [...f, { key: Math.random(), from: a, to: b, delay }])
      }
      // Its work flies on to the module that keeps it (a transfer: three, one after another, as the stock moves).
      const dest = destOf(item)
      // WEB-83: a saved entry lands on the owner's questions it answers (the first is where it flies), and the
      // answers are read again; anything else still goes to the module that keeps it.
      const asks = item.state === 'saved' ? questionsOf(item, boardData.current) : []
      const to = (asks.length ? boardRefs.current.get(asks[0]) : dest ? destRefs.current.get(dest.key) : undefined)?.getBoundingClientRect()
      if (asks.length || dest) for (const delay of item.transfer ? [0, 160, 320] : [0]) fly(from, to, delay)
      if (dest) ring(dest.key, alarm ? 'alarm' : 'land', 850)
      asks.forEach((key, i) => ring(`q:${key}`, alarm && i === 0 ? 'alarm' : 'land', 850 + i * 260))
      if (asks.length && live) window.setTimeout(() => void queryClient.invalidateQueries({ queryKey: ['live-board'] }), 900)
      // The sites' numbers (and a site just added) catch up as it lands.
      if (live) void queryClient.invalidateQueries({ queryKey: ['live-site-days', date, null] })
      await wait(alarm ? STEP_MS + 3_400 : item.kind === 'cancelled' || item.kind === 'undo' ? STEP_MS + 3_800 : isBill(item) || item.kind === 'language' || item.state === 'asked' || item.kind === 'chat' || cardAs(item) ? STEP_MS + 2_600 : STEP_MS + 1_200)
      // WEB-82: saved is not the value; what it changed is. Each record it saved plays its ripple.
      for (const record of (item.source === 'sample' ? [] : item.records ?? []).slice(0, 3)) await playRipple(item, record, speed.current)
    }
    setCurrent(null)
    playing.current = false
    speed.current = 1
    setReplaying(false)
  }, [readFlags, ring, queryClient, date, showMeet, say, playRipple])

  // The first read just shows the day; later reads play what is new.
  React.useEffect(() => {
    if (!feed.data) return
    if (!seeded.current) {
      // WEB-64: Live starts empty: what came before it opened is known, not shown (Replay the day shows it).
      seeded.current = true
      before.current = new Set(feed.data.map((m) => m.id))
      return
    }
    if (replaying) return
    const known = new Set([...before.current, ...shown, ...queue.current.map((m) => m.id), current?.item.id])
    // WEB-65: only what Mesiri is done with: played before, a photo was only a photo (its expense came 27 s later).
    const fresh = feed.data.filter((m) => !known.has(m.id) && m.handled !== false)
    if (!fresh.length) return
    const late = fresh.slice(0, Math.max(0, fresh.length - QUEUE_MAX))
    if (late.length) setShown((s) => new Set([...s, ...late.map((m) => m.id)]))
    queue.current.push(...fresh.slice(-QUEUE_MAX))
    void play()
  }, [feed.data, shown, current, play, replaying])

  // Each site's flagged lines as the page opens, so a mistake caught later shows as new.
  // WEB-61: a project's report going out (its "sent" turning on in the polled site-days): its sheet builds on the
  // stage from the day's sites, then folds into the PDF and drops into WhatsApp (the site Live's Finale).
  const [sending, setSending] = React.useState<{ project: ProjectDayItem; from: DOMRect | null } | null>(null)
  const sheetRef = React.useRef<HTMLDivElement>(null)
  const sentBefore = React.useRef<Map<string, boolean> | null>(null)
  const sendQueue = React.useRef<ProjectDayItem[]>([])
  const nextSend = React.useCallback(() => {
    if (greeting.current || playing.current) return
    const project = sendQueue.current.shift()
    if (!project) return
    greeting.current = true // messages that come meanwhile wait for it
    setSending({ project, from: null })
    say(`${project.project_name}: the day’s messages become the report.`)
    window.setTimeout(
      () => {
        say(`Today’s report for ${project.project_name} is out.`)
        setSending((s) => (s ? { ...s, from: sheetRef.current?.getBoundingClientRect() ?? new DOMRect(window.innerWidth / 2 - 300, 120, 600, 600) } : s))
      },
      prefersReducedMotion() ? 600 : SHEET_MS,
    )
  }, [say])
  const sentDone = React.useCallback(() => {
    setSending(null)
    greeting.current = false
    if (sendQueue.current.length) window.setTimeout(nextSend, 400)
    else if (queue.current.length) void play()
  }, [nextSend, play])
  React.useEffect(() => {
    const projects = days.data?.projects ?? []
    if (!days.data || !isToday) return
    if (sentBefore.current === null) {
      sentBefore.current = new Map(projects.map((p) => [p.project_id, p.sent]))
      return
    }
    for (const p of projects) {
      if (p.sent && sentBefore.current.get(p.project_id) === false) sendQueue.current.push(p)
      sentBefore.current.set(p.project_id, p.sent)
    }
    if (sendQueue.current.length && !sending) nextSend()
  }, [days.data, isToday, nextSend, sending])
  // A report due while a message plays goes out once it is done.
  React.useEffect(() => {
    if (!current && !hello && !sending && sendQueue.current.length) nextSend()
  }, [current, hello, sending, nextSend])

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
    voice.setOn(on) // presenter mode talks; leaving it is quiet again
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
    const mute = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null
      if (e.key.toLowerCase() === 'm' && !e.metaKey && !e.ctrlKey && !(t && /input|textarea|select/i.test(t.tagName))) voice.setOn(!voice.on)
    }
    window.addEventListener('keydown', mute)
    document.addEventListener('fullscreenchange', left)
    return () => {
      document.removeEventListener('fullscreenchange', left)
      window.removeEventListener('keydown', mute)
    }
  }, [voice])

  // WEB-82: the presenter's keys while a ripple plays.
  const rippling = !!ripple
  React.useEffect(() => {
    if (!rippling) return
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null
      if (e.metaKey || e.ctrlKey || e.altKey || (t && /input|textarea|select/i.test(t.tagName))) return
      const to: RippleMove | 'hold' | null =
        e.key === ' ' ? 'hold' : e.key === 'ArrowRight' ? 'next' : e.key === 'ArrowLeft' ? 'back' : e.key.toLowerCase() === 's' ? 'end' : e.key === 'Escape' ? 'close' : null
      if (to === null) return
      e.preventDefault()
      rippleCtl.current.move?.(to)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [rippling])

  const number = setup.data?.whatsapp_number ?? null
  // WEB-71: in a meeting the QR code is how people join this company: it sends the join code, and the admin lets
  // them in on WhatsApp. Without the code (not an admin) it stays "Hi Mesiri".
  const qrText = joining.data?.join_text ?? 'Hi Mesiri'
  const qrLink = number ? `https://wa.me/${number.replace(/\D/g, '')}?text=${encodeURIComponent(qrText)}` : null

  // Who just moved on a step: their card animates, and Mesiri says it (presenter mode talks).
  const joinSteps = React.useRef<Map<string, string> | null>(null)
  const [joinFresh, setJoinFresh] = React.useState<Map<string, 'new' | 'step' | 'in'>>(new Map())
  React.useEffect(() => {
    const people = joining.data?.people
    if (!people) return
    if (joinSteps.current === null) {
      joinSteps.current = new Map(people.map((p) => [p.key, p.step]))
      return
    }
    const changed = new Map<string, 'new' | 'step' | 'in'>()
    for (const p of people) {
      const before = joinSteps.current.get(p.key) as typeof p.step | undefined
      if (before === p.step) continue
      changed.set(p.key, before === undefined && p.step !== 'joined' ? 'new' : p.step === 'joined' ? 'in' : 'step')
      joinSteps.current.set(p.key, p.step)
      const line = joiningLine(p, before)
      if (line) say(line)
    }
    if (!changed.size) return
    setJoinFresh((m) => new Map([...m, ...changed]))
    const keys = [...changed.keys()]
    window.setTimeout(() => setJoinFresh((m) => new Map([...m].filter(([k]) => !keys.includes(k)))), 4_000)
  }, [joining.data, say])

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
          handled: true,
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
    // The whole day's, whatever the stream shows.
    messages: items.length,
    saved: items.filter((m) => m.state === 'saved').length,
    issues: sites.reduce((n, s) => n + (s.open_issues || 0), 0),
    reported: sites.filter((s) => s.last_update_at).length,
  }
  const company = branding.data?.company_name
  // WEB-65: messages Mesiri is still working on (just in, no reply yet): shown as being worked on, played once done.
  const working = isToday
    ? items.filter((m) => m.handled === false && !before.current.has(m.id) && !shown.has(m.id) && current?.item.id !== m.id)
    : []
  // The moment for what Mesiri is handling now (moments.tsx), if its kind has one.
  const moment: 'bill' | 'language' | 'asked' | 'answer' | 'chat' | 'card' | null = (() => {
    if (!current || (current.alarm && current.step === 'done')) return null
    const m = current.item
    if (isBill(m)) return 'bill'
    if (m.kind === 'language' && (current.step === 'understood' || current.step === 'done')) return 'language'
    if (current.step === 'done' && m.state === 'asked' && m.asked) return 'asked'
    if (current.step === 'done' && cardAs(m)) return 'card'
    if (current.step === 'done' && m.kind === 'question' && cleanReply(m.reply)) return 'answer'
    if (current.step === 'done' && (m.kind === 'chat' || m.kind === 'photo' || m.kind === 'intro') && m.text && cleanReply(m.reply)) return 'chat'
    return null
  })()
  const answers = current ? qa.of.get(current.item.id) ?? null : null

  /** A site's own report writing itself, in the panel (?site=…, so the address can be shared). */
  const openSite = (siteId: string | null, projectId: string | null) => {
    if (!siteId) return
    setParams((prev) => {
      const next = new URLSearchParams(prev)
      next.set('site', siteId)
      if (projectId) next.set('project', projectId)
      return next
    })
  }
  /** A module's page, with a cinematic cut: the whole company, or one message's project and site. */
  const openDest = (d: Dest, el: HTMLElement, m?: LiveFeedItem) => {
    const scope = new URLSearchParams()
    if (m?.project_id) scope.set('project', m.project_id)
    if (m?.site_id) scope.set('site', m.site_id)
    cinematic.go({
      from: el.getBoundingClientRect(),
      to: `${d.path}${scope.size ? `?${scope}` : ''}`,
      title: d.name,
      kicker: [m?.site_name ?? 'All sites', longDate(date)].filter(Boolean).join(' · '),
      line: m ? m.summaries[0] ?? m.text ?? undefined : undefined,
    })
  }
  /** WEB-82: the page a ripple card's number lives on, for the entry's project and site. */
  const openCard = (card: EffectCard, el: HTMLElement, m: LiveFeedItem) => {
    if (!card.opens) return
    const scope = new URLSearchParams()
    if (m.project_id) scope.set('project', m.project_id)
    if (m.site_id) scope.set('site', m.site_id)
    cinematic.go({
      from: el.getBoundingClientRect(),
      to: `${card.opens}${scope.size ? `?${scope}` : ''}`,
      title: card.title,
      kicker: [m.site_name ?? 'All sites', longDate(date)].filter(Boolean).join(' · '),
      line: card.sentence,
    })
  }
  const destOn = (d: Dest) => !d.module || moduleEnabled(d.module)
  // What each module got today: entries saved there, and the last one.
  const destCounts = new Map<DestKey, { n: number; last: string | null }>()
  for (const m of items) {
    if (!shown.has(m.id) && !before.current.has(m.id)) continue
    const d = destOf(m)
    if (!d) continue
    const was = destCounts.get(d.key) ?? { n: 0, last: null }
    destCounts.set(d.key, {
      n: was.n + (m.state === 'saved' || m.state === 'answered' ? 1 : 0),
      last: m.summaries[0] ?? (m.kind === 'question' ? cleanReply(m.reply) : m.text) ?? was.last,
    })
  }
  const newSiteNames = sites.filter((s) => newSites.has(s.site_id)).map((s) => s.site_name)
  // The day's totals sit fixed at the bottom and grow (presenter mode's bigger numbers, wrapping
  // on a narrower screen): the page keeps that much room under its content, and the sticky stage
  // stops above it, so nothing hides behind the bar.
  const footRef = React.useRef<HTMLElement>(null)
  const pageRef = React.useRef<HTMLDivElement>(null)
  const [footH, setFootH] = React.useState(72)
  React.useLayoutEffect(() => {
    const el = footRef.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(() => setFootH(Math.ceil(el.getBoundingClientRect().height)))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  // The show starts at the top of its card: scrolled down a long message list, it would open off screen.
  React.useEffect(() => {
    if (hello) pageRef.current?.scrollIntoView({ behavior: prefersReducedMotion() ? 'auto' : 'smooth', block: 'start' })
  }, [hello])
  React.useEffect(() => {
    if (!sitePanel) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onCloseSite()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [sitePanel, onCloseSite])

  return (
    <div
      ref={pageRef}
      className={cn('min-h-svh bg-background px-4 pb-6 sm:px-8 sm:pb-[calc(var(--live-foot)+2rem)] lg:px-12', presenting && 'text-[1.12rem]')}
      style={{ '--live-foot': `${footH}px` } as React.CSSProperties}
    >
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
              onClick={() => voice.setOn(!voice.on)}
              aria-pressed={voice.on}
              title={voice.unavailable ? 'Mesiri’s voice is not available right now' : voice.on ? 'Mute Mesiri (M)' : 'Let Mesiri talk (M)'}
              className={cn(
                'flex items-center gap-2 border px-3 py-2 text-sm font-medium',
                voice.on ? 'border-foreground bg-foreground text-background' : 'border-foreground hover:bg-foreground hover:text-background',
                voice.unavailable && voice.on && 'border-[var(--destructive)] bg-background text-[var(--destructive)]',
              )}
            >
              {voice.on ? <Volume2 className="size-4" /> : <VolumeX className="size-4" />}
              {voice.on ? (voice.unavailable ? 'No voice' : 'Mute') : 'Sound'}
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
        <ReportStrip
          projects={days.data?.projects ?? []}
          sites={sites}
          isToday={isToday}
          onSite={(s) => openSite(s.site_id, s.project_id)}
        />

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
              <Label>{shown.size || samples.length ? `Messages · ${totals.messages} today` : 'Messages · from now'}</Label>
              {feed.isLoading ? (
                <p className="mt-4 text-sm text-muted-foreground">Loading…</p>
              ) : stream.length === 0 && !working.length ? (
                <p className="mt-4 text-sm leading-relaxed text-muted-foreground">
                  Listening. New messages show here as they arrive: send Mesiri one on WhatsApp.
                  {items.length > 0 && (
                    <>
                      {' '}
                      {items.length} earlier today:{' '}
                      <button type="button" onClick={() => void replay()} className="border-b border-current font-medium text-foreground">
                        Replay the day
                      </button>{' '}
                      to see them.
                    </>
                  )}
                </p>
              ) : (
                <ol className="m-0 mt-4 grid list-none gap-3 p-0" aria-live="polite">
                  {working.map((m) => (
                    <li
                      key={`w-${m.id}`}
                      className="grid gap-1 border border-dashed border-primary px-4 py-3"
                      style={prefersReducedMotion() ? undefined : { animation: 'live-in 400ms ease-out' }}
                    >
                      <span className="flex items-center justify-between gap-2 text-sm">
                        <b>{m.sender_name ?? 'Someone'}</b>
                        <span className="font-mono text-[11px] text-muted-foreground">{clock(m.received_at)}</span>
                      </span>
                      <span className="flex items-center gap-2 text-sm text-muted-foreground">
                        {workingLine(m)}
                        <span className="flex gap-1" aria-hidden="true">
                          {[0, 1, 2].map((d) => (
                            <span key={d} className="size-1.5 rounded-full bg-primary" style={prefersReducedMotion() ? undefined : { animation: `spark-wave 1s ease-in-out ${d * 0.2}s infinite` }} />
                          ))}
                        </span>
                      </span>
                    </li>
                  ))}
                  {stream.slice(0, 40).map((m) => (
                    <MessageCard key={m.id} m={m} active={current?.item.id === m.id} answers={qa.of.get(m.id) ?? null}
                      answered={qa.answered.has(m.id)}
                      became={became.get(m.id) ?? null}
                      onSite={() => openSite(m.site_id, m.project_id)}
                      onDest={(d, el) => openDest(d, el, m)}
                    />
                  ))}
                </ol>
              )}
            </section>

            {/* The Spark, handling one message at a time */}
            <section
              aria-label="Mesiri"
              className={cn('order-1 min-w-0 lg:order-2', current?.alarm && 'relative z-40', hello && 'lg:col-span-2 lg:order-1 xl:col-span-1 xl:order-2')}
            >
              {sending ? (
                <div className="sticky top-6 grid max-h-[calc(100svh-var(--live-foot)-3rem)] justify-items-center gap-4 overflow-y-auto border border-foreground/15 bg-background px-4 py-6 text-center sm:px-6">
                  <Spark mood="send" size={presenting ? 120 : 90} />
                  <div>
                    <Label className="block">The day’s report</Label>
                    <p className={cn('m-0 mt-1 font-medium', presenting ? 'text-[26px]' : 'text-[20px]')}>
                      <Typed text={`${sending.project.project_name}: the day’s messages become the report.`} />
                    </p>
                  </div>
                  <div className={cn('w-full', sending.from && 'invisible')}>
                    <ProjectSheet ref={sheetRef} project={sending.project} sites={sites} company={company ?? null} date={date} />
                  </div>
                </div>
              ) : hello ? (
                <div className="border-2 border-foreground bg-background px-4 py-5 sm:px-7 sm:py-6">
                  <MeetMesiri
                    to={hello.to}
                    short={hello.short}
                    site={sites[0]?.site_name ?? null}
                    number={number}
                    qrText={qrText}
                    presenting={presenting}
                    onScene={onScene}
                    onSay={say}
                    onDone={() => helloDone.current?.()}
                  />
                </div>
              ) : (
              <div className="sticky top-6 grid max-h-[calc(100svh-var(--live-foot)-3rem)] justify-items-center gap-4 overflow-y-auto border border-foreground/15 bg-background px-4 py-5 text-center sm:gap-5 sm:px-6 sm:py-8">
                <div ref={sparkRef}>
                  <Spark
                    mood={current ? sparkMood(current.item, current.step, current.alarm) : working.length ? (isVoice(working[0]) ? 'listen' : isPhoto(working[0]) ? 'look' : 'think') : 'idle'}
                    beat={beat}
                    size={ripple ? (presenting ? 96 : 72) : moment ? (presenting ? 140 : 110) : presenting ? 220 : 170}
                  />
                </div>
                <div className={cn('min-h-[5.5rem] sm:min-h-[7.5rem]', ripple ? 'grid w-full justify-items-center' : moment === 'bill' ? 'w-full max-w-[44rem]' : 'max-w-[34rem]')} aria-live="polite">
                  {ripple ? (
                    <Ripple
                      effects={ripple.effects}
                      at={ripple.at}
                      held={ripple.held}
                      presenting={presenting}
                      onPick={(i) => rippleCtl.current.move?.(i)}
                      onOpen={(card, el) => openCard(card, el, ripple.item)}
                    />
                  ) : current ? (
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
                      {moment === 'card' && cardAs(current.item) && (
                        <div className="mt-3 grid justify-items-center">
                          <EntryCard
                            key={current.item.id}
                            lines={current.item.summaries}
                            site={current.item.site_name}
                            who={current.item.sender_name?.split(/\s+/)[0] ?? null}
                            as={cardAs(current.item)!}
                            presenting={presenting}
                          />
                        </div>
                      )}
                      {moment === 'chat' && (
                        <div className="mt-3 grid justify-items-center">
                          <ChatMoment
                            said={current.item.text ?? ''}
                            english={current.item.translated_text && current.item.translated_text !== current.item.text ? current.item.translated_text : null}
                            reply={cleanReply(current.item.reply)}
                            presenting={presenting}
                          />
                        </div>
                      )}
                      {moment === 'answer' && (
                        <div className="mt-3 grid justify-items-center">
                          <AnswerMoment reply={current.item.reply ?? ''} presenting={presenting} />
                        </div>
                      )}
                      {(moment !== 'asked' && moment !== 'answer' && moment !== 'language' && moment !== 'chat' && moment !== 'card') || current.step !== 'done' ? (
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
                    working.length ? (
                      <>
                        <Label className="block">Mesiri · on it</Label>
                        <p className={cn('m-0 mt-2 font-medium', presenting ? 'text-[26px]' : 'text-[20px]')}>
                          <Typed key={working[0].id} text={workingLine(working[0])} />
                        </p>
                      </>
                    ) : (
                    <>
                      <Label className="block">Mesiri · listening</Label>
                      <p className={cn('m-0 mt-2 text-muted-foreground', presenting ? 'text-[26px]' : 'text-lg')}>
                        Waiting for the next message from site…
                      </p>
                    </>
                    )
                  )}
                </div>
                {!ripple && <Steps step={current?.step ?? null} />}
                {!ripple && <Did current={current} />}
                {!ripple && current?.step === 'done' && destOf(current.item) && current.item.source !== 'sample' && (
                  <button
                    type="button"
                    onClick={(e) => openDest(destOf(current.item)!, e.currentTarget, current.item)}
                    className="flex items-center gap-1.5 border-b border-foreground text-sm font-medium hover:text-primary-ink"
                    style={prefersReducedMotion() ? undefined : { animation: 'live-in 400ms ease-out' }}
                  >
                    Open in {destOf(current.item)!.name} <ArrowRight className="size-3.5" />
                  </button>
                )}
                {isToday && (presenting || (joining.data?.people.length ?? 0) > 0) && (
                  <Joining
                    people={joining.data?.people ?? []}
                    fresh={joinFresh}
                    qrLink={qrLink}
                    number={number}
                    code={joining.data?.code ?? null}
                    company={branding.data?.company_name ?? 'the team'}
                    presenting={presenting}
                  />
                )}
              </div>
              )}
            </section>

            {/* WEB-83: the owner's board: what the day's entries mean, each answer opening its page. */}
            <section aria-label="The owner’s board" className="order-3 min-w-0 lg:col-span-2 xl:col-span-1">
              <OwnerBoard
                board={board.data}
                failed={board.isError}
                items={items.filter((m) => shown.has(m.id) || before.current.has(m.id))}
                ringing={ringing}
                presenting={presenting}
                nodeRef={(key, el) => {
                  if (el) boardRefs.current.set(key, el)
                  else boardRefs.current.delete(key)
                }}
                onOpen={(q, path, el, line) =>
                  cinematic.go({ from: el.getBoundingClientRect(), to: path, title: q.question, kicker: `All sites · ${longDate(date)}`, line })
                }
              />
              {/* Where it is kept: the modules that hold Mesiri's work, each opening its page. */}
              <nav aria-label="Where it is kept" className="mt-5">
                <Label>Where it is kept</Label>
                <ul className="m-0 mt-2 flex list-none flex-wrap gap-1.5 p-0">
                  {DESTS.filter(destOn).map((d) => {
                    const Icon = d.icon
                    const got = destCounts.get(d.key)
                    const how = ringing.get(d.key)
                    const fresh = d.key === 'projects' && newSiteNames.length > 0
                    return (
                      <li key={d.key}>
                        <button
                          type="button"
                          ref={(el) => {
                            if (el) destRefs.current.set(d.key, el)
                            else destRefs.current.delete(d.key)
                          }}
                          title={fresh ? `New: ${newSiteNames.join(', ')}` : got?.last ? short(got.last, 80) : d.keeps}
                          onClick={(e) => openDest(d, e.currentTarget)}
                          className={cn(
                            'flex items-center gap-1.5 border px-2 py-1 text-[12.5px] font-medium transition-colors duration-300 hover:bg-foreground hover:text-background',
                            how === 'alarm' ? 'border-[var(--destructive)]' : fresh ? 'border-primary' : 'border-foreground/20',
                          )}
                          style={
                            prefersReducedMotion()
                              ? undefined
                              : how
                                ? { animation: 'live-land 1.4s ease-out' }
                                : fresh
                                  ? { animation: 'live-pop 900ms cubic-bezier(.3,1.5,.5,1) both' }
                                  : undefined
                          }
                        >
                          <Icon className="size-3.5" aria-hidden="true" />
                          {fresh ? `New site: ${newSiteNames.join(', ')}` : d.name}
                          <span className="font-mono text-[11.5px] tabular-nums opacity-70">
                            <CountTo value={got?.n ?? 0} />
                          </span>
                        </button>
                      </li>
                    )
                  })}
                </ul>
              </nav>
              <label className="mt-5 grid gap-1.5">
                <Label>A site’s day</Label>
                <select
                  aria-label="Open a site’s day"
                  value=""
                  onChange={(e) => {
                    const s = sites.find((x) => x.site_id === e.target.value)
                    if (s) openSite(s.site_id, s.project_id)
                  }}
                  className="h-9 w-full min-w-0 border border-foreground/30 bg-background px-2 text-sm"
                >
                  <option value="">Open a site… ({totals.reported} of {sites.length} heard from)</option>
                  {sites.map((s) => (
                    <option key={s.site_id} value={s.site_id}>
                      {s.site_name} · {s.project_name}
                      {s.last_update_at ? ` · ${clock(s.last_update_at)}` : ' · not yet'}
                    </option>
                  ))}
                </select>
              </label>
            </section>
          </div>
        )}
      </div>

      {/* The company's day, counting up */}
      <footer
        ref={footRef}
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

      {sending?.from && (
        <Finale
          from={sending.from}
          projectId={sending.project.project_id}
          company={company ?? ''}
          code={null}
          site={sending.project.project_name}
          onDone={sentDone}
        />
      )}
      {sitePanel && (
        <div className="fixed inset-0 z-[55]" role="dialog" aria-modal="true" aria-label="A site’s day">
          <button type="button" aria-label="Close" onClick={onCloseSite} className="absolute inset-0 cursor-default bg-foreground/30 animate-in fade-in duration-300" />
          <div className="absolute inset-y-0 right-0 w-full max-w-[1240px] overflow-y-auto border-l-2 border-foreground bg-background animate-in slide-in-from-right duration-500 motion-reduce:animate-none">
            {sitePanel}
          </div>
        </div>
      )}
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
          <span className={cn('transition-colors duration-500', i <= at ? 'text-primary-ink' : 'text-muted-foreground')}>{w}</span>
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

function MessageCard({
  m,
  active,
  answers,
  answered,
  became,
  onSite,
  onDest,
}: {
  m: LiveFeedItem
  active: boolean
  answers: string | null
  answered: boolean
  /** Opens the message's site's day in the panel. */
  onSite: () => void
  /** A waiting card's fate: Save or Cancel tapped later. */
  became: 'saved' | 'cancelled' | null
  /** Opens the module that keeps what it said. */
  onDest: (d: Dest, el: HTMLElement) => void
}) {
  const dest = destOf(m)
  const look = KINDS[m.saved_kind && m.kind === 'saved' ? m.saved_kind : m.kind]
  const Icon = look.icon
  const chip = became === 'saved' ? { text: 'Saved ✓', className: 'text-[var(--success)]' } : became === 'cancelled' ? { text: 'Cancelled', className: 'text-muted-foreground' } : m.state === 'asked' ? (answered ? { text: 'Answered ✓', className: 'text-[var(--success)]' } : { text: 'Waiting for answer', className: 'text-[var(--draft)]' }) : STATE_CHIP[m.state]
  const english = m.translated_text && m.translated_text !== m.text ? m.translated_text : null
  return (
    <li
      className={cn(
        'grid min-w-0 gap-2 border px-4 py-3 [overflow-wrap:anywhere] transition-[border-color,background-color] duration-500',
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
            {m.site_id && m.source !== 'sample' ? (
              <button type="button" onClick={onSite} className="border-b border-dotted border-current hover:text-foreground">
                {m.site_name}
              </button>
            ) : (
              m.site_name ?? m.project_name
            )}
            {m.received_at ? ` · ${clock(m.received_at)}` : ''}
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
          {isVoice(m) && <Mic className="mr-1.5 inline size-4 align-[-2px] text-primary-ink" aria-label="Voice note" />}
          {short(m.text, 220)}
        </p>
      )}
      {answers && <p className="m-0 text-[12px] text-muted-foreground">↳ Answer to Mesiri: “{short(answers, 80)}”</p>}
      {english && <p className="m-0 text-sm italic text-muted-foreground">“{short(english, 220)}”</p>}
      {m.state === 'asked' && m.asked && <p className="m-0 text-[13px] font-medium">Mesiri asked: {short(m.asked, 140)}</p>}
      {cleanReply(m.reply) && m.reply !== m.asked && (
        <div className="flex items-start gap-2 border-l-2 border-foreground/20 pl-3">
          <Spark mood="idle" quiet size={22} className="mt-0.5 shrink-0" label="Mesiri's reply" />
          <p className="m-0 text-sm leading-snug text-muted-foreground">{short(cleanReply(m.reply), 200)}</p>
        </div>
      )}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
          {m.source === 'sample' ? 'Sample · Meet Mesiri' : m.source === 'dashboard' ? 'Mesiri web' : <><WhatsAppIcon className="size-3" /> WhatsApp</>}
        </span>
        <span className="flex items-center gap-3">
          {dest && m.source !== 'sample' && (m.state === 'saved' || m.state === 'draft' || m.state === 'answered') && (
            <button
              type="button"
              onClick={(e) => onDest(dest, e.currentTarget)}
              className="flex items-center gap-1 border-b border-foreground text-[12px] font-medium hover:text-primary-ink"
            >
              {dest.name} <ArrowRight className="size-3" />
            </button>
          )}
          {chip && <span className={cn('text-[12px] font-medium', chip.className)}>{chip.text}</span>}
        </span>
      </div>
    </li>
  )
}
