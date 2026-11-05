import * as React from 'react'
import { MessageCircleQuestion, Receipt } from 'lucide-react'
import type { LiveFeedItem } from '@/lib/api'
import { prefersReducedMotion } from '@/lib/timeline'
import { cn } from '@/lib/utils'
import { Count } from './meet'

// The company Live's moments for four kinds of message (WEB-57), shown on the
// stage under the character while it handles one:
// - a bill (an expense): the photo comes up, a scan reads it, the fields Mesiri
//   took out arrive one by one (the amount counting up), then its reply;
// - Mesiri asks back: its question, big, waiting for the person's answer (the
//   answer, when it comes, is shown as answering it);
// - a language change: "Hello" in each language, landing on the one chosen;
// - a question: the answer as a card, its number counting up.
// Flat: no glow. Reduced motion shows each one still.

type Step = 'arrive' | 'read' | 'understood' | 'done'
const still = () => prefersReducedMotion()
const at = (name: string, s: number, ms = 500) => (still() ? undefined : { animation: `${name} ${ms}ms cubic-bezier(.2,.9,.3,1) ${s}s both` })

const rupees = (v: string | null) => {
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}

/** A bill: the photo, read, its fields taken out one by one, then the reply. */
export function BillMoment({ item, step, presenting }: { item: LiveFeedItem; step: Step; presenting: boolean }) {
  const e = item.expense
  const amount = rupees(e?.amount ?? null)
  const fields: [string, React.ReactNode][] = e
    ? ([
        ['Amount', amount != null ? <Count key="amount" to={Math.round(amount)} ms={900} format={(n) => `₹${n.toLocaleString('en-IN')}`} /> : e.amount],
        ['Vendor', e.vendor],
        ['Category', e.category],
        ['Date', e.date ? new Date(e.date).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' }) : null],
        ['GST', e.tax ? `₹${Number(e.tax).toLocaleString('en-IN')}` : null],
        ['For', e.what],
      ].filter(([, v]) => v != null && v !== '') as [string, React.ReactNode][])
    : []
  const reading = step === 'read'
  const out = step === 'understood' || step === 'done'
  return (
    <div className="grid w-full items-start gap-4 text-left sm:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
      {/* The bill: its photo, or a receipt drawn from what was said. */}
      <div className="relative overflow-hidden border border-foreground/25 bg-muted">
        {item.media_url ? (
          <img
            src={item.media_url}
            alt="The bill"
            className={cn('block w-full object-cover', presenting ? 'max-h-80' : 'max-h-60')}
            style={still() ? undefined : { animation: 'live-develop 1.4s ease-out both' }}
          />
        ) : (
          <div className="grid gap-2 bg-background px-4 py-4 font-mono text-[12px]" style={at('meet-pop', 0)}>
            <span className="flex items-center gap-2 text-sm font-semibold">
              <Receipt className="size-4" /> {e?.vendor ?? 'Bill'}
            </span>
            {[70, 90, 55, 80].map((w, i) => (
              <span key={i} className="block h-1.5 bg-foreground/15" style={{ width: `${w}%` }} />
            ))}
            <span className="mt-1 border-t border-dashed border-foreground/40 pt-2 text-right text-sm font-bold">
              {amount != null ? `₹${amount.toLocaleString('en-IN')}` : '—'}
            </span>
          </div>
        )}
        {reading && !still() && (
          <span className="absolute inset-x-0 h-[3px] bg-primary" style={{ animation: 'live-scan 1.1s ease-in-out infinite' }} />
        )}
        {reading && (
          <span className="absolute left-2 top-2 bg-foreground px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.08em] text-background">
            Reading the bill…
          </span>
        )}
      </div>
      {/* What Mesiri took out of it. */}
      <dl className="m-0 grid gap-1.5">
        {out && fields.length === 0 && <p className="m-0 text-sm text-muted-foreground">Reading what it says…</p>}
        {out &&
          fields.map(([k, v], i) => (
            <div key={k} className="flex items-baseline justify-between gap-3 border-b border-foreground/10 pb-1.5" style={step === 'understood' ? at('meet-deal', 0.15 + i * 0.3) : undefined}>
              <dt className="font-mono text-[11px] uppercase tracking-[0.06em] text-muted-foreground">{k}</dt>
              <dd className={cn('m-0 text-right font-semibold', k === 'Amount' ? (presenting ? 'text-[34px]' : 'text-[26px]') + ' tracking-[-0.02em] text-primary' : 'text-[15px]')}>
                {v}
              </dd>
            </div>
          ))}
      </dl>
    </div>
  )
}

const GREETINGS = ['Hello', 'ഹലോ', 'नमस्ते', 'Hello ji', 'Namaskaram']
const LANGUAGES: Record<string, { name: string; line: string }> = {
  english: { name: 'English', line: 'Hello! Send me today’s update.' },
  malayalam: { name: 'മലയാളം', line: 'നമസ്കാരം! ഇന്നത്തെ അപ്ഡേറ്റ് അയക്കൂ.' },
  manglish: { name: 'Manglish', line: 'Namaskaram! Innathe update ayakku.' },
  hindi: { name: 'हिन्दी', line: 'नमस्ते! आज का अपडेट भेजिए।' },
  hinglish: { name: 'Hinglish', line: 'Namaste! Aaj ka update bhejo.' },
  auto: { name: 'Your language', line: 'I’ll reply in whatever language you write in.' },
}

/** A language change: "Hello" in every language, landing on the one chosen. */
export function LanguageMoment({ language, presenting }: { language: string | null; presenting: boolean }) {
  const chosen = LANGUAGES[language ?? ''] ?? LANGUAGES.auto
  const [i, setI] = React.useState(still() ? GREETINGS.length : 0)
  React.useEffect(() => {
    if (still()) return
    const t = window.setInterval(() => setI((n) => (n >= GREETINGS.length ? n : n + 1)), 260)
    return () => window.clearInterval(t)
  }, [])
  const landed = i >= GREETINGS.length
  return (
    <div className="grid justify-items-center gap-2" aria-live="polite">
      <p className={cn('m-0 font-bold tracking-[-0.03em]', presenting ? 'text-[56px]' : 'text-[42px]', landed && 'text-primary')}>
        <span key={i} className="inline-block" style={at('meet-flip', 0, 220)}>
          {landed ? chosen.name : GREETINGS[i]}
        </span>
      </p>
      {landed && (
        <p className={cn('m-0 rounded-[12px] rounded-tl-none border border-foreground/15 px-4 py-2', presenting ? 'text-xl' : 'text-base')} style={at('meet-pop', 0.1)}>
          {chosen.line}
        </p>
      )}
    </div>
  )
}

/** Mesiri asked something back: the question, big, and the person it waits for. */
export function AskedMoment({ question, who, presenting }: { question: string; who: string | null; presenting: boolean }) {
  return (
    <div className="grid w-full justify-items-center gap-3">
      <div
        className={cn('relative max-w-[34rem] border-2 border-foreground bg-background px-5 py-4 text-left font-medium', presenting ? 'text-[28px]' : 'text-[22px]')}
        style={at('meet-pop', 0)}
      >
        <MessageCircleQuestion className="absolute -left-3 -top-3 size-7 bg-background text-primary" aria-hidden="true" />
        {question}
      </div>
      <p className="m-0 flex items-center gap-2 text-sm text-muted-foreground" style={at('meet-rise', 0.5)}>
        Waiting for {who ? `${who}’s` : 'their'} answer
        <span className="flex gap-1" aria-hidden="true">
          {[0, 1, 2].map((d) => (
            <span key={d} className="size-1.5 rounded-full bg-muted-foreground" style={still() ? undefined : { animation: `spark-wave 1s ease-in-out ${d * 0.2}s infinite` }} />
          ))}
        </span>
      </p>
    </div>
  )
}

/** A question answered: the reply as a card, its first number counting up. */
export function AnswerMoment({ reply, presenting }: { reply: string; presenting: boolean }) {
  const text = cleanReply(reply)
  const match = text.match(/(\d[\d,]*(?:\.\d+)?)/)
  const n = match ? Number(match[1].replace(/,/g, '')) : null
  const before = match ? text.slice(0, match.index) : text
  const after = match ? text.slice((match.index ?? 0) + match[1].length) : ''
  return (
    <div className={cn('max-w-[36rem] border-2 border-foreground bg-background px-5 py-4 text-left', presenting ? 'text-[24px]' : 'text-[19px]')} style={at('meet-pop', 0)}>
      <span className="mb-1 block font-mono text-[11px] uppercase tracking-[0.08em] text-muted-foreground">Mesiri answered</span>
      <span className="leading-snug">
        {before.length > 220 ? `${before.slice(0, 219)}…` : before}
        {n != null && Number.isFinite(n) && (
          <b className={cn('mx-0.5 text-primary tracking-[-0.02em]', presenting ? 'text-[44px]' : 'text-[34px]')}>
            <Count to={n} ms={900} format={(v) => (match![1].includes(',') || v >= 1000 ? v.toLocaleString('en-IN') : String(v))} />
          </b>
        )}
        {after.length > 160 ? `${after.slice(0, 159)}…` : after}
      </span>
    </div>
  )
}

/** The message where Mesiri asked what this message answers: the last question it asked this sender, within half
 * an hour, when this is the sender's first message after it. */
export function answering(items: LiveFeedItem[], m: LiveFeedItem): LiveFeedItem | null {
  if (!m.sender_name || !m.received_at) return null
  const t = new Date(m.received_at).getTime()
  let best: LiveFeedItem | null = null
  for (const x of items) {
    if (x.id === m.id || x.sender_name !== m.sender_name || !x.received_at || x.state !== 'asked' || !x.asked) continue
    const tx = new Date(x.received_at).getTime()
    if (tx < t && t - tx <= 30 * 60_000 && (!best || tx > new Date(best.received_at!).getTime())) best = x
  }
  if (!best) return null
  // Only the first message after the question answers it.
  const between = items.some(
    (x) => x.sender_name === m.sender_name && x.received_at && x.id !== m.id && new Date(x.received_at) > new Date(best!.received_at!) && new Date(x.received_at).getTime() < t,
  )
  return between ? null : best
}

/** For every message: the question it answers (by message id), and the questions answered. */
export function answers(items: LiveFeedItem[]): { of: Map<string, string>; answered: Set<string> } {
  const of = new Map<string, string>()
  const answered = new Set<string>()
  for (const m of items) {
    const q = answering(items, m)
    if (q?.asked) {
      of.set(m.id, q.asked)
      answered.add(q.id)
    }
  }
  return { of, answered }
}

/** Mesiri's reply as a person reads it on Live: without the "🎤 _what was heard_" line WhatsApp shows first (Live shows
 * the words already) and without a note the code keeps for the model that a reply once carried by mistake. */
export function cleanReply(reply: string | null | undefined): string {
  return (reply ?? '')
    .replace(/^🎤\s*_[^_]*_\s*/u, '')
    .replace(/\(said by an older version of Mesiri[^)]*\)\s*/gi, '')
    .trim()
}

/** An everyday message ("Hello സുഖമാണോ", "ok thanks"): the two of them talking, the reply typing in. */
export function ChatMoment({ said, english, reply, presenting }: { said: string; english: string | null; reply: string; presenting: boolean }) {
  const [n, setN] = React.useState(still() ? reply.length : 0)
  React.useEffect(() => {
    if (still()) return
    let timer = 0
    const start = window.setTimeout(() => {
      timer = window.setInterval(() => setN((k) => (k >= reply.length ? k : k + 2)), 18)
    }, 700)
    return () => {
      window.clearTimeout(start)
      window.clearInterval(timer)
    }
  }, [reply])
  const size = presenting ? 'text-[22px]' : 'text-[18px]'
  return (
    <div className="grid w-full max-w-[36rem] gap-3 text-left">
      <div className={cn('max-w-[85%] justify-self-end rounded-[12px] rounded-tr-none bg-[#d9fdd3] px-4 py-2.5 text-[#111]', size)} style={at('meet-pop', 0)}>
        {said}
        {english && <span className="mt-1 block text-[0.8em] italic text-[#111]/60">“{english}”</span>}
      </div>
      <div className={cn('max-w-[90%] justify-self-start rounded-[12px] rounded-tl-none border border-foreground/20 bg-background px-4 py-2.5', size)} style={at('meet-pop', 0.5)}>
        <span className="mb-0.5 block font-mono text-[10px] uppercase tracking-[0.08em] text-muted-foreground">Mesiri</span>
        {reply.slice(0, n)}
        {n < reply.length && (
          <span className="ml-1 inline-flex gap-0.5 align-middle" aria-hidden="true">
            {[0, 1, 2].map((d) => (
              <span key={d} className="size-1.5 rounded-full bg-muted-foreground" style={still() ? undefined : { animation: `spark-wave 900ms ease-in-out ${d * 0.15}s infinite` }} />
            ))}
          </span>
        )}
      </div>
    </div>
  )
}

/** What a waiting card became: the sender's next Save or Cancel tap, within four hours (WEB-62). */
export function outcomes(items: LiveFeedItem[]): Map<string, 'saved' | 'cancelled'> {
  const out = new Map<string, 'saved' | 'cancelled'>()
  const at = (m: LiveFeedItem) => (m.received_at ? new Date(m.received_at).getTime() : 0)
  for (const m of items) {
    if (m.state !== 'draft' || !m.sender_name) continue
    const tap = items
      .filter((x) => x.sender_name === m.sender_name && at(x) > at(m) && at(x) - at(m) <= 4 * 3600_000 && (x.kind === 'saved' || x.kind === 'cancelled'))
      .sort((a, b) => at(a) - at(b))[0]
    if (tap) out.set(m.id, tap.kind === 'saved' ? 'saved' : 'cancelled')
  }
  return out
}

/** The card the person sees on WhatsApp, and what became of it: waiting for ✅ Save, saved, cancelled, or taken back. */
export function EntryCard({
  lines,
  site,
  who,
  as,
  presenting,
}: {
  lines: string[]
  site: string | null
  who: string | null
  as: 'draft' | 'saved' | 'cancelled' | 'undone'
  presenting: boolean
}) {
  const shown = lines.length ? lines.slice(0, 6) : ['—']
  const gone = as === 'cancelled' || as === 'undone'
  const stamp = { draft: null, saved: 'Saved', cancelled: 'Cancelled', undone: 'Taken back' }[as]
  const stampTone = as === 'saved' ? 'border-[var(--success)] text-[var(--success)]' : 'border-muted-foreground text-muted-foreground'
  const end = 0.4 + shown.length * 0.3
  return (
    <div className="grid w-full max-w-[34rem] gap-2 text-left">
      <div
        className="relative overflow-hidden border-2 border-foreground bg-background"
        style={
          still()
            ? undefined
            : gone
              ? { animation: `meet-pop 400ms ease-out both, live-drop-away 900ms ease-in ${end + 1.4}s forwards` }
              : { animation: 'meet-pop 400ms ease-out both' }
        }
      >
        <div className={cn('h-2.5', as === 'saved' ? 'bg-[var(--success)]' : 'bg-[repeating-linear-gradient(-45deg,#1a1d21_0_10px,#f5b301_10px_20px)]')} />
        <div className="flex items-center justify-between px-4 pt-2.5">
          <span
            className={cn(
              'px-2 py-0.5 font-mono text-[11px] uppercase tracking-[0.08em]',
              as === 'saved' ? 'bg-[var(--success)] text-white' : gone ? 'bg-muted text-muted-foreground' : 'bg-foreground text-background',
            )}
          >
            {as === 'saved' ? '✅ Saved' : as === 'cancelled' ? 'Cancelled' : as === 'undone' ? 'Taken back' : 'Draft · not saved'}
          </span>
          {site && <span className="text-xs text-muted-foreground">{site}</span>}
        </div>
        <ol className="m-0 grid list-none p-0 py-1">
          {shown.map((l, i) => (
            <li
              key={i}
              className="relative flex items-center gap-3 border-b border-dashed border-foreground/15 px-4 py-2 last:border-0"
              style={at('meet-deal', 0.2 + i * 0.3)}
            >
              <span className="w-4 font-mono text-xs text-primary">{i + 1}</span>
              <span className={cn('min-w-0 flex-1 font-medium transition-colors duration-500', presenting ? 'text-[19px]' : 'text-[16px]', gone && 'text-muted-foreground')}>
                {l}
              </span>
              {gone && (
                <span
                  className="absolute left-10 right-4 top-1/2 h-[2px] origin-left bg-[var(--destructive)]"
                  style={at('meet-strike', end + i * 0.25, 350)}
                />
              )}
            </li>
          ))}
        </ol>
        {as === 'draft' && (
          <div className="grid grid-cols-3 gap-2 border-t border-foreground/15 px-4 py-2.5 text-center text-sm font-medium">
            <span className="border-2 border-foreground py-1.5" style={still() ? undefined : { animation: 'live-wait 1.4s ease-in-out infinite' }}>
              Save
            </span>
            <span className="border border-foreground/30 py-1.5 text-muted-foreground">✏️ Edit</span>
            <span className="border border-foreground/30 py-1.5 text-muted-foreground">Cancel</span>
          </div>
        )}
        {stamp && (
          <span className="pointer-events-none absolute left-1/2 top-[45%] -translate-x-1/2">
            <span
              className={cn(
                'block -rotate-6 whitespace-nowrap border-4 bg-background/85 px-3 py-0.5 font-black uppercase tracking-[0.06em]',
                shown.length > 1 ? 'text-[28px]' : 'text-[18px]',
                stampTone,
              )}
              style={at('meet-stamp', as === 'saved' ? end : end + shown.length * 0.25 + 0.2, 500)}
            >
              {stamp}
            </span>
          </span>
        )}
      </div>
      <p className="m-0 flex items-center gap-2 justify-self-center text-sm text-muted-foreground" style={at('meet-rise', end)}>
        {as === 'draft' ? (
          <>
            Waiting for {who ? `${who}’s` : 'their'} ✅ Save
            <span className="flex gap-1" aria-hidden="true">
              {[0, 1, 2].map((d) => (
                <span key={d} className="size-1.5 rounded-full bg-muted-foreground" style={still() ? undefined : { animation: `spark-wave 1s ease-in-out ${d * 0.2}s infinite` }} />
              ))}
            </span>
          </>
        ) : as === 'saved' ? (
          'One tap, and it’s in.'
        ) : as === 'cancelled' ? (
          'Cancelled. Nothing was saved.'
        ) : (
          'Taken back. The stock and the report follow.'
        )}
      </p>
    </div>
  )
}
