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
  const text = reply.replace(/^🎤\s*_[^_]*_\s*/u, '').trim()
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
