import * as React from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
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
import { MesiriWordmark } from '@/components/brand/mesiri-logo'
import { Label, WordsIn } from '@/components/onboarding/conversation'
import { Mic, Monitor } from 'lucide-react'
import { CountTo, Ink } from '@/components/live/ink'
import { WhatsAppIcon } from '@/components/brand/whatsapp-icon'
import { TellMesiri } from '@/components/tell-mesiri/tell-mesiri'
import { inkDuration, THREAD_MS } from '@/lib/ink'

// The Live report (WEB-37): the day's report writing itself as the site's
// messages come in. Left, the messages as they arrive on WhatsApp (or from
// Tell Mesiri); right, the report sheet, each new line written in letter by
// letter, a thread drawn from the message to where it lands, counts going
// up. Re-reads the day every few seconds. "Replay the day" rebuilds the
// whole report from its messages, in order: the demo. Read-only: it shows
// what Mesiri saved, the same data as the site's day page.

const POLL_MS = 3_000
type Section = 'labour' | 'work' | 'materials' | 'issues'
const SECTIONS: { key: Exclude<Section, 'labour'>; title: string }[] = [
  { key: 'work', title: 'Work done' },
  { key: 'materials', title: 'Materials' },
  { key: 'issues', title: 'Issues' },
]

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

function rowText(item: ReviewItem): { main: string; sub: string | null } {
  const main = item.title || item.detail || 'Update'
  const qty = (item.quantities ?? [])
    .map((q) => [q.quantity, q.unit, q.work_type].filter(Boolean).join(' '))
    .join(', ')
  const sub = [item.title ? item.detail : null, qty || null, item.severity ? `${item.severity} priority` : null]
    .filter(Boolean)
    .join(' · ')
  return { main, sub: sub || null }
}

/** The thread from a message on the left to the line it fills on the right. */
function Thread({ from, to }: { from: DOMRect; to: DOMRect }) {
  const x1 = from.right
  const y1 = from.top + Math.min(28, from.height / 2)
  const x2 = to.left - 6
  const y2 = to.top + 12
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
        style={{ animation: 'live-draw 700ms cubic-bezier(.6,0,.2,1) both' }}
      />
      <circle cx={x2} cy={y2} r={4} className="fill-primary animate-in fade-in zoom-in-50 delay-500 fill-mode-both duration-300" />
    </svg>
  )
}

function Row({
  item,
  writing,
  innerRef,
}: {
  item: ReviewItem
  writing: boolean
  innerRef?: (el: HTMLElement | null) => void
}) {
  const { main, sub } = rowText(item)
  return (
    <li
      ref={innerRef}
      className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-4 border-b border-black/10 py-2.5 last:border-b-0"
      style={writing && !prefersReducedMotion() ? { animation: 'live-glow 2.6s ease-out both' } : undefined}
    >
      <span className="min-w-0">
        <Ink text={main} writing={writing} delay={THREAD_MS} className="block text-[14.5px] font-medium" />
        {sub && (
          <Ink
            text={sub}
            writing={writing}
            delay={THREAD_MS + inkDuration(main)}
            className="block text-[12.5px] text-black/55"
          />
        )}
      </span>
      {item.review === 'draft' && (
        <span className="self-start pt-0.5 font-mono text-[10px] uppercase tracking-[0.08em] text-primary">Draft</span>
      )}
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

  // What the sheet shows: facts written so far, the one being written, and
  // the labour figures as of the last labour line written.
  const [written, setWritten] = React.useState<Set<string>>(new Set())
  const [writing, setWriting] = React.useState<string | null>(null)
  const [labour, setLabour] = React.useState<SiteDayDetail['report']['labour'] | null>(null)
  const [feed, setFeed] = React.useState<FeedMessage[]>([])
  const [thread, setThread] = React.useState<{ message: string; target: string } | null>(null)
  const [, redraw] = React.useReducer((n: number) => n + 1, 0)
  // WEB-37: tell Mesiri right here; what's saved writes itself in like any message.
  const [telling, setTelling] = React.useState(params.get('tell') === '1')

  const known = React.useRef<Set<string> | null>(null)
  const queue = React.useRef<ReviewItem[]>([])
  const running = React.useRef(false)
  const alive = React.useRef(true)
  const generation = React.useRef(0)
  const sources = React.useRef(new Map<string, FactSources['messages'][number] | null>())
  const feedIds = React.useRef(new Set<string>())
  const latest = React.useRef<SiteDayDetail | undefined>(undefined)
  latest.current = detail.data

  const stage = React.useRef<HTMLDivElement>(null)
  const messageEls = React.useRef(new Map<string, HTMLElement>())
  const targetEls = React.useRef(new Map<string, HTMLElement>())

  React.useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])

  const sourceOf = React.useCallback(async (item: ReviewItem) => {
    const key = factKey(item)
    if (!sources.current.has(key)) {
      try {
        const res = await fetchFactSourcesApi(item.fact_type, item.id)
        sources.current.set(key, res.messages[0] ?? null)
      } catch {
        sources.current.set(key, null)
      }
    }
    return sources.current.get(key) ?? null
  }, [])

  const toFeed = (msg: FactSources['messages'][number], fresh: boolean): FeedMessage => ({
    id: msg.id,
    type: msg.type,
    text: (msg.text || '').trim() || kindLabel(msg.type),
    at: msg.received_at,
    sender: msg.sender_name,
    source: msg.source || 'whatsapp',
    fresh,
  })

  // Plays the queue: message in, thread across, line written, next.
  const play = React.useCallback(async () => {
    if (running.current) return
    running.current = true
    const gen = generation.current
    const still = prefersReducedMotion()
    while (queue.current.length && alive.current && gen === generation.current) {
      const item = queue.current.shift()!
      const key = factKey(item)
      const msg = await sourceOf(item)
      if (gen !== generation.current) break
      const messageId = msg?.id ?? `none:${key}`
      // One message can fill several lines (workers, work, an issue): it
      // arrives once, and its later lines draw from it.
      const added = !!msg && !feedIds.current.has(msg.id)
      if (msg && added) {
        feedIds.current.add(msg.id)
        setFeed((all) => [...all, toFeed(msg, true)])
      }
      // Time to read the message (its words arrive one by one) before it is used.
      if (!still) await sleep(added ? Math.min(3500, 1500 + (msg?.text ?? "").length * 12) : 500)
      const target = item.section === 'labour' ? 'labour' : key
      setWritten((all) => new Set(all).add(key))
      if (item.section === 'labour') setLabour(latest.current?.report.labour ?? null)
      setWriting(key)
      if (!still) {
        await sleep(60)
        setThread({ message: messageId, target })
        const { main, sub } = rowText(item)
        await sleep(THREAD_MS + inkDuration(main) + (sub ? inkDuration(sub) : 0) + 700)
        setThread(null)
      }
      setWriting(null)
      if (!still) await sleep(500)
    }
    // A replay started meanwhile owns the flag now.
    if (gen === generation.current) running.current = false
  }, [sourceOf])

  // New facts from the day's re-read join the queue; the first read is
  // taken as already written (with its messages in the feed, unanimated).
  React.useEffect(() => {
    const data = detail.data
    if (!data) return
    if (known.current === null) {
      known.current = new Set(data.items.map(factKey))
      setWritten(new Set(known.current))
      setLabour(data.report.labour)
      void Promise.all(data.items.map(sourceOf)).then((msgs) => {
        const seen = new Map<string, FeedMessage>()
        for (const m of msgs) if (m && !seen.has(m.id)) seen.set(m.id, toFeed(m, false))
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
    setWriting(null)
  }, [siteId, date])

  /** The demo: an empty report, then every line written again from its message, in order. */
  const replay = async () => {
    const data = latest.current
    if (!data) return
    generation.current++
    running.current = false
    queue.current = []
    setWritten(new Set())
    setWriting(null)
    setThread(null)
    feedIds.current = new Set()
    setFeed([])
    setLabour({ ...data.report.labour, headcount: 0, trades: [] })
    const withTimes = await Promise.all(data.items.map(async (item) => ({ item, msg: await sourceOf(item) })))
    withTimes.sort((a, b) => (a.msg?.received_at ?? '9').localeCompare(b.msg?.received_at ?? '9'))
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
  const fromEl = thread ? messageEls.current.get(thread.message) : undefined
  const toEl = thread ? targetEls.current.get(thread.target) : undefined
  const rel = (r: DOMRect) => new DOMRect(r.x - (box?.x ?? 0), r.y - (box?.y ?? 0), r.width, r.height)

  const items = detail.data?.items ?? []
  const shown = (section: Section) => items.filter((i) => i.section === section && written.has(factKey(i)))
  const company = branding.data?.letterhead_name || branding.data?.company_name || me?.org_name || me?.organization_name || 'Your company'
  const frozen = ['approved', 'published'].includes(detail.data?.day?.status ?? '')
  const lastRead = detail.dataUpdatedAt ? new Date(detail.dataUpdatedAt).toLocaleTimeString('en-GB') : null

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
            {/* From site */}
            <section aria-label="From site" className="min-w-0">
              {telling && (
                <div className="mb-8 border border-foreground px-4 py-4 animate-in fade-in slide-in-from-top-2 duration-300 motion-reduce:animate-none">
                  <Label className="block pb-3">Tell Mesiri · speak or type, and watch it land in the report</Label>
                  <TellMesiri compact />
                </div>
              )}
              <Label>From site · {site?.site_name ?? ''}</Label>
              <ol className="mt-4 grid gap-5" aria-live="polite">
                {feed.length === 0 && (
                  <li className="text-sm text-muted-foreground">Waiting for the first message from site…</li>
                )}
                {feed.slice(-6).map((m) => (
                  <li
                    key={m.id}
                    ref={(el) => {
                      if (el) messageEls.current.set(m.id, el)
                      else messageEls.current.delete(m.id)
                    }}
                    className={cn(
                      'grid gap-1.5 border-l-2 pl-4 transition-colors duration-700',
                      thread?.message === m.id ? 'border-primary' : 'border-foreground/15',
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
                  className="mt-6"
                  style={writing && writing.startsWith('labour') && !prefersReducedMotion() ? { animation: 'live-glow 2.6s ease-out both' } : undefined}
                >
                  <div className="flex items-baseline justify-between border-b border-black/80 pb-1.5">
                    <span className="font-mono text-[11px] uppercase tracking-[0.08em] text-black/60">Manpower</span>
                    <span className="text-[13px]">
                      Total <CountTo value={labour?.headcount ?? 0} className="text-[22px] font-semibold" />
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
                          {rows.map((item) => (
                            <Row
                              key={factKey(item)}
                              item={item}
                              writing={writing === factKey(item)}
                              innerRef={(el) => {
                                if (el) targetEls.current.set(factKey(item), el)
                                else targetEls.current.delete(factKey(item))
                              }}
                            />
                          ))}
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
    </div>
  )
}
