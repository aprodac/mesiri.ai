import * as React from 'react'
import { AlertTriangle, Boxes, Check, FileText, Hammer, HardHat, Mic, type LucideIcon, X } from 'lucide-react'
import { prefersReducedMotion } from '@/lib/timeline'
import { cn } from '@/lib/utils'
import { QrCode } from '@/components/onboarding/qr-code'
import { WhatsAppIcon } from '@/components/brand/whatsapp-icon'
import { Spark } from './spark'

// "Meet Mesiri" (WEB-56): what Mesiri does, shown on the company Live itself,
// told with the product overview's own examples (Mesiri_Overview, 5 Nov 2026).
// Nine scenes, each animated in CSS (the `meet-*` keyframes in index.css):
// hello and the four numbers; one voice note becoming a five-line card that is
// saved and sent to its modules; one update in four languages; the site words
// it knows; questions answered; what it catches (a correction, an attendance
// sheet, a new size); the day's updates becoming the 9 PM report, sent as a
// PDF; what the owner asks for as an image (stock, cost by category); and the
// close, with the QR code. It plays on Live's own stage: the character narrates
// each scene, and each scene's sample messages arrive in Live's message stream
// (marked Sample), so it stays the live screen, not a separate slideshow.
// Sample data, said so on screen. Flat: no glow. A person's first message plays
// the short show (hello, the card, the report, the close).

const SCENE_MS = { title: 5_500, card: 11_500, languages: 7_000, words: 6_500, ask: 7_500, catches: 8_500, report: 11_000, owner: 10_000, close: 7_000 }
export type SceneKey = keyof typeof SCENE_MS
const FULL: SceneKey[] = ['title', 'card', 'languages', 'words', 'ask', 'catches', 'report', 'owner', 'close']
const SHORT: SceneKey[] = ['title', 'card', 'report', 'close']

const still = () => prefersReducedMotion()
/** An animation that starts `at` seconds into the scene. */
const at = (name: string, s: number, ms = 600, ease = 'cubic-bezier(.2,.9,.3,1)') =>
  still() ? undefined : { animation: `${name} ${ms}ms ${ease} ${s}s both` }

function Typed({ text, ms = 28, delay = 0 }: { text: string; ms?: number; delay?: number }) {
  const [n, setN] = React.useState(still() ? text.length : 0)
  React.useEffect(() => {
    if (still()) return
    let timer = 0
    const start = window.setTimeout(() => {
      timer = window.setInterval(() => setN((k) => (k >= text.length ? k : k + 1)), ms)
    }, delay * 1000)
    return () => {
      window.clearTimeout(start)
      window.clearInterval(timer)
    }
  }, [text, ms, delay])
  return (
    <>
      {text.slice(0, n)}
      {n > 0 && n < text.length && <span className="ml-px inline-block h-[0.9em] w-[2px] translate-y-[2px] bg-current" />}
    </>
  )
}

/** A number counting up from 0, starting `delay` seconds in. */
export function Count({ to, delay = 0, ms = 900, format = (n: number) => String(n) }: { to: number; delay?: number; ms?: number; format?: (n: number) => string }) {
  const [n, setN] = React.useState(still() ? to : 0)
  React.useEffect(() => {
    if (still()) return
    let raf = 0
    const start = window.setTimeout(() => {
      const t0 = performance.now()
      const step = (t: number) => {
        const p = Math.min(1, (t - t0) / ms)
        setN(Math.round(to * (1 - Math.pow(1 - p, 3))))
        if (p < 1) raf = requestAnimationFrame(step)
      }
      raf = requestAnimationFrame(step)
    }, delay * 1000)
    return () => {
      window.clearTimeout(start)
      cancelAnimationFrame(raf)
    }
  }, [to, delay, ms])
  return <>{format(n)}</>
}

function Bars({ n = 28, className }: { n?: number; className?: string }) {
  return (
    <span className={cn('flex h-7 items-center gap-[2px]', className)} aria-hidden="true">
      {Array.from({ length: n }, (_, i) => (
        <span
          key={i}
          className="w-[3px] rounded-full bg-current"
          style={{
            height: `${30 + ((i * 37) % 70)}%`,
            animation: still() ? undefined : `live-bar 700ms ease-in-out ${(i % 7) * 90}ms 4 alternate`,
          }}
        />
      ))}
    </span>
  )
}

const Kicker = ({ children }: { children: React.ReactNode }) => (
  <p className="m-0 flex items-center gap-2 font-mono text-[12px] uppercase tracking-[0.1em] text-muted-foreground" style={at('meet-rise', 0)}>
    <span className="inline-block h-2.5 w-5 bg-primary" /> {children}
  </p>
)
const Big = ({ children, s = 0.2, className }: { children: React.ReactNode; s?: number; className?: string }) => (
  <h2 className={cn('m-0 text-[32px] font-bold leading-[1.04] tracking-[-0.035em] sm:text-[46px]', className)} style={at('meet-rise', s, 700)}>
    {children}
  </h2>
)
/** A message sent to Mesiri (right, green) or Mesiri's reply (left, white). */
const Bubble = ({ me, children, s, className }: { me?: boolean; children: React.ReactNode; s: number; className?: string }) => (
  <div
    className={cn(
      'max-w-[92%] rounded-[12px] px-3.5 py-2.5 text-[16px] leading-snug sm:text-[18px]',
      me ? 'justify-self-end rounded-tr-none bg-[#d9fdd3] text-[#111]' : 'justify-self-start rounded-tl-none border border-foreground/15 bg-background',
      className,
    )}
    style={at('meet-pop', s, 450)}
  >
    {children}
  </div>
)

// ── Scenes ────────────────────────────────────────────────────────────────────

function TitleScene({ to }: { to: string | null }) {
  const stats = [
    { n: 0, unit: '', what: 'apps to install' },
    { n: 1, unit: '', what: 'tap to save an update' },
    { n: 9, unit: 'PM', what: 'report in your inbox' },
    { n: 4, unit: '', what: 'languages: Malayalam, Manglish, Hinglish, English' },
  ]
  return (
    <div className="grid gap-8">
      <div>
        <Kicker>Meet Mesiri{to ? ` · for ${to}` : ''}</Kicker>
      </div>
      <Big s={1.3} className="sm:text-[68px]">
        Your site
        <br />
        reports itself.
      </Big>
      <ul className="m-0 grid list-none grid-cols-2 gap-x-6 gap-y-5 p-0 sm:grid-cols-4">
        {stats.map((st, i) => (
          <li key={st.what} className="border-t-2 border-foreground pt-3" style={at('meet-rise', 2.3 + i * 0.3)}>
            <span className="text-[44px] font-bold leading-none tracking-[-0.04em] text-primary sm:text-[54px]">
              <Count to={st.n} delay={2.4 + i * 0.3} ms={700} />
              {st.unit && <span className="ml-1 text-[24px]">{st.unit}</span>}
            </span>
            <span className="mt-2 block text-sm text-muted-foreground">{st.what}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

const CARD_LINES: { icon: LucideIcon; tone: string; title: string; sub: string; n?: number; unit?: string; goes: string }[] = [
  { icon: HardHat, tone: 'bg-[var(--info-soft)] text-[var(--info)]', title: 'Ravi contractor', sub: 'Mason', n: 12, unit: 'people', goes: 'Labour' },
  { icon: HardHat, tone: 'bg-[var(--info-soft)] text-[var(--info)]', title: 'Ravi contractor', sub: 'Helper', n: 5, unit: 'people', goes: 'Labour' },
  { icon: Boxes, tone: 'bg-[var(--draft-soft)] text-[var(--draft)]', title: 'Cement (OPC 53)', sub: 'Received · Malabar Traders', n: 150, unit: 'bags', goes: 'Materials' },
  { icon: Hammer, tone: 'bg-[var(--success-soft)] text-[var(--success)]', title: 'Slab shuttering, 2nd floor', sub: 'Started', goes: 'Site log' },
  { icon: AlertTriangle, tone: 'bg-[color-mix(in_srgb,var(--destructive)_12%,transparent)] text-[var(--destructive)]', title: 'Concrete mixer broke down', sub: '2 hours lost', goes: 'Issues' },
]

function CardScene({ site }: { site: string }) {
  const said = 'Innu Ravi contractor-nte 12 mason, 5 helper. Cement 150 chaakku vannu, Malabar Traders. Second floor slab shuttering start cheythu. Mixer breakdown aayi, 2 hour poyi.'
  return (
    <div className="grid gap-6">
      <div>
        <Kicker>One voice note</Kicker>
        <Big>Five updates. One tap.</Big>
      </div>
      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)]">
        <div className="grid gap-3">
          <Bubble me s={0.6}>
            <span className="flex items-center gap-3 text-[#0f5132]">
              <Mic className="size-5" /> <Bars /> <span className="font-mono text-xs">0:21</span>
            </span>
          </Bubble>
          <p className="m-0 border-l-4 border-primary pl-4 text-[17px] italic leading-relaxed sm:text-[19px]" style={at('meet-rise', 1.6)}>
            “<Typed text={said} ms={16} delay={1.8} />”
          </p>
        </div>
        <div className="relative">
          <div className="overflow-hidden border-2 border-foreground bg-background" style={at('meet-pop', 4.3, 500)}>
            <div className="relative h-3 bg-[repeating-linear-gradient(-45deg,#1a1d21_0_10px,#f5b301_10px_20px)]" />
            <div className="flex items-center justify-between px-4 pt-3">
              <span className="relative">
                <span className="bg-foreground px-2 py-0.5 font-mono text-[11px] uppercase tracking-[0.08em] text-background">Draft · not saved</span>
                <span
                  className="absolute inset-0 grid place-items-center bg-[var(--success)] font-mono text-[11px] uppercase tracking-[0.08em] text-white"
                  style={at('meet-fade', 8.3, 300)}
                >
                  ✅ Saved
                </span>
              </span>
              <span className="text-xs text-muted-foreground">Today · 9:05 AM</span>
            </div>
            <p className="m-0 px-4 pt-1 text-[22px] font-bold tracking-[-0.02em]">{site}</p>
            <ol className="m-0 grid list-none gap-0 p-0 px-4 py-2">
              {CARD_LINES.map((l, i) => {
                const Icon = l.icon
                return (
                  <li key={i} className="flex items-center gap-3 border-b border-dashed border-foreground/15 py-2.5 last:border-0" style={at('meet-deal', 4.8 + i * 0.4)}>
                    <span className="w-4 font-mono text-xs text-primary">{i + 1}</span>
                    <span className={cn('grid size-8 shrink-0 place-items-center rounded-md', l.tone)}>
                      <Icon className="size-4" />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[15px] font-semibold">{l.title}</span>
                      <span className="flex min-w-0 items-center gap-2 text-xs text-muted-foreground">
                        <span className="truncate">{l.sub}</span>
                        <span className="shrink-0 bg-foreground px-1.5 py-px text-[10px] font-medium text-background" style={at('meet-slide', 9 + i * 0.15)}>
                          → {l.goes}
                        </span>
                      </span>
                    </span>
                    {l.n != null && (
                      <span className="shrink-0 text-right">
                        <span className="text-[20px] font-bold tabular-nums">
                          <Count to={l.n} delay={4.9 + i * 0.4} ms={600} />
                        </span>
                        <span className="ml-1 text-xs text-muted-foreground">{l.unit}</span>
                      </span>
                    )}
                  </li>
                )
              })}
            </ol>
            <div className="flex items-center justify-between bg-[var(--draft-soft)] px-4 py-2 text-xs">
              <span>
                Check it, then tap <b>Save</b>
              </span>
              <span>5 lines</span>
            </div>
          </div>
          <div className="mt-3 grid grid-cols-3 gap-2 text-center text-sm font-medium" style={at('meet-rise', 6.8)}>
            <span className="border border-foreground py-2" style={at('meet-press', 7.6, 400)}>
              Save
            </span>
            <span className="border border-foreground/30 py-2 text-muted-foreground">✏️ Edit</span>
            <span className="border border-foreground/30 py-2 text-muted-foreground">Cancel</span>
          </div>
          <span className="pointer-events-none absolute left-1/2 top-[38%] -translate-x-1/2">
            <span
              className="block -rotate-12 border-4 border-[var(--success)] bg-background/80 px-5 py-1 text-[34px] font-black uppercase tracking-[0.06em] text-[var(--success)]"
              style={at('meet-stamp', 8.1, 500)}
            >
              Saved
            </span>
          </span>
        </div>
      </div>
    </div>
  )
}

function LanguagesScene() {
  const ways = [
    { tag: 'മലയാളം', text: 'ഇന്ന് രവി കോൺട്രാക്ടറുടെ 12 മേസൺ, 5 ഹെൽപ്പർ വന്നു.' },
    { tag: 'Malayalam voice note', text: 'voice' },
    { tag: 'Manglish', text: 'innu Ravi contractor-nte 12 mason, 5 helper vannu' },
    { tag: 'English', text: 'Today 12 masons and 5 helpers came, Ravi contractor’s team.' },
  ]
  return (
    <div className="grid gap-8">
      <div>
        <Kicker>Any language</Kicker>
        <Big>
          മലയാളത്തിൽ
          <br />
          പറഞ്ഞാൽ മതി.
        </Big>
      </div>
      <div className="relative">
        <ul className="m-0 grid list-none gap-3 p-0 sm:grid-cols-4">
          {ways.map((w, i) => (
            <li key={w.tag} style={still() ? undefined : { animation: `meet-pop 450ms cubic-bezier(.2,.9,.3,1) ${0.6 + i * 0.35}s both, meet-converge 700ms ease-in 3.6s forwards` }}>
              <div className="h-full rounded-[12px] bg-[#d9fdd3] px-3.5 py-3 text-[#111]">
                <span className="bg-[#111] px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-[0.06em] text-white">{w.tag}</span>
                <p className="m-0 mt-2 text-[16px] leading-snug">{w.text === 'voice' ? <Bars n={22} className="text-[#0f5132]" /> : w.text}</p>
              </div>
            </li>
          ))}
        </ul>
        <div className="absolute inset-0 grid place-items-center" style={at('meet-pop', 4.1, 600)}>
          <div className="border-2 border-foreground bg-background px-5 py-4 text-center">
            <p className="m-0 font-mono text-[11px] uppercase tracking-[0.08em] text-muted-foreground">All four become the same report line</p>
            <p className="m-0 mt-1 text-[22px] font-bold tracking-[-0.02em] sm:text-[30px]">Manpower · Ravi contractor · Mason 12 · Helper 5</p>
          </div>
        </div>
      </div>
    </div>
  )
}

function WordsScene() {
  const words = [
    ['ചാക്ക്', 'chaakku', 'bags'],
    ['ലോഡ്', 'lod', 'load'],
    ['കെട്ട്', 'kettu', 'bundle'],
    ['അടി', 'adi', 'feet'],
    ['എണ്ണം', 'ennam', 'numbers'],
    ['കമ്പി', 'kambi', 'steel'],
    ['മണൽ', 'manal', 'sand'],
  ]
  return (
    <div className="grid gap-8">
      <div>
        <Kicker>Site words</Kicker>
        <Big>It understands how sites talk.</Big>
      </div>
      <ul className="m-0 grid list-none grid-cols-2 gap-px bg-foreground p-px p-0 sm:grid-cols-4 lg:grid-cols-7">
        {words.map(([ml, roman, en], i) => (
          <li key={ml} className="relative grid min-h-36 content-start gap-1 bg-background px-4 py-4" style={at('meet-deal', 0.5 + i * 0.15)}>
            <span className="text-[30px] font-bold leading-tight">{ml}</span>
            <span className="text-sm text-muted-foreground">{roman}</span>
            <span className="mt-2 text-[22px] font-bold text-primary" style={at('meet-flip', 2 + i * 0.3, 500)}>
              = {en}
            </span>
          </li>
        ))}
      </ul>
      <p className="m-0 text-lg text-muted-foreground" style={at('meet-rise', 4.6)}>
        Say <b className="text-foreground">“മലയാളത്തിൽ പറയൂ”</b> once and every reply stays in Malayalam.
      </p>
    </div>
  )
}

function AskScene({ site }: { site: string }) {
  return (
    <div className="grid gap-8">
      <div>
        <Kicker>Ask anything</Kicker>
        <Big>Ask on WhatsApp. Get the number.</Big>
      </div>
      <div className="grid gap-8 lg:grid-cols-2">
        {[
          { q: 'സിമന്റ് എത്ര ചാക്ക് ബാക്കിയുണ്ട്?', a: `${site}-ൽ ഇപ്പോൾ`, n: 210, unit: 'ചാക്ക് Cement ഉണ്ട്.', fill: 0.62, s: 0.6 },
          { q: 'Block B-il kambi ethra und?', a: 'Block B-il ippol', n: 2100, unit: 'kg Steel und.', fill: 0.84, s: 3.4 },
        ].map((x) => (
          <div key={x.q} className="grid gap-3">
            <Bubble me s={x.s}>
              {x.q}
            </Bubble>
            <span className="flex gap-1 justify-self-start px-2" style={still() ? undefined : { animation: `meet-dots 1s linear ${x.s + 0.5}s both` }}>
              {[0, 1, 2].map((i) => (
                <span key={i} className="size-2 rounded-full bg-muted-foreground" />
              ))}
            </span>
            <Bubble s={x.s + 1.5} className="w-[92%]">
              {x.a}{' '}
              <b className="text-[26px] tracking-[-0.02em] text-primary">
                <Count to={x.n} delay={x.s + 1.6} format={(n) => n.toLocaleString('en-IN')} />
              </b>{' '}
              {x.unit}
              <span className="mt-2 block h-2 w-full bg-muted">
                <span className="block h-full bg-foreground" style={{ width: `${x.fill * 100}%`, ...(at('meet-grow', x.s + 1.7, 1100) ?? {}) }} />
              </span>
            </Bubble>
          </div>
        ))}
      </div>
    </div>
  )
}

function CatchesScene() {
  return (
    <div className="grid gap-8">
      <div>
        <Kicker>Nothing lost</Kicker>
        <Big>It catches what people miss.</Big>
      </div>
      <div className="grid gap-6 lg:grid-cols-3">
        <div className="grid content-start gap-3 border-t-2 border-foreground pt-4" style={at('meet-rise', 0.5)}>
          <p className="m-0 font-semibold">A correction, in their words</p>
          <Bubble me s={0.9}>
            cement 12 alla, 14 chaakku
          </Bubble>
          <Bubble s={2}>
            Cement{' '}
            <span className="relative inline-block">
              12
              <span className="absolute left-0 top-1/2 h-[2px] w-full origin-left bg-[var(--destructive)]" style={at('meet-strike', 2.6, 400)} />
            </span>{' '}
            <b className="text-primary" style={at('meet-pop', 3, 400)}>
              → 14
            </b>{' '}
            chaakku aakki.
          </Bubble>
        </div>
        <div className="grid content-start gap-3 border-t-2 border-foreground pt-4" style={at('meet-rise', 0.9)}>
          <p className="m-0 font-semibold">The attendance sheet, read</p>
          <div className="relative h-28 justify-self-end overflow-hidden rounded-[10px] border border-foreground/20 bg-muted px-4 py-3" style={{ width: '70%', ...(at('meet-pop', 1.3, 450) ?? {}) }}>
            {Array.from({ length: 6 }, (_, i) => (
              <span key={i} className="mb-2 block h-[3px] bg-foreground/35" style={{ width: `${55 + ((i * 23) % 40)}%` }} />
            ))}
            <span className="absolute inset-x-0 h-[3px] bg-primary" style={still() ? undefined : { animation: 'live-scan 1.2s ease-in-out 1.8s 2 both' }} />
          </div>
          <Bubble s={4.2}>
            <b>
              <Count to={21} delay={4.3} />
            </b>{' '}
            lines ready from the sheet.
          </Bubble>
        </div>
        <div className="grid content-start gap-3 border-t-2 border-foreground pt-4" style={at('meet-rise', 1.3)}>
          <p className="m-0 font-semibold">A new size, asked once</p>
          <Bubble me s={1.7}>
            M-sand 1 lod vannu
          </Bubble>
          <Bubble s={2.6}>1 load M-sand = how many bags?</Bubble>
          <div className="grid grid-cols-3 gap-2 text-center text-sm" style={at('meet-rise', 3.2)}>
            {[40, 50, 60].map((b) => (
              <span key={b} className={cn('border py-1.5', b === 60 ? 'border-foreground font-semibold' : 'border-foreground/25')} style={b === 60 ? at('meet-press', 4.2, 400) : undefined}>
                {b} bags
              </span>
            ))}
          </div>
          <Bubble s={5}>Got it: 1 load = 60 bags from now on.</Bubble>
        </div>
      </div>
    </div>
  )
}

function ReportScene({ site }: { site: string }) {
  const kpis: [number | string, string, boolean?][] = [
    [21, 'workers'],
    [3, 'work items'],
    [4, 'materials'],
    [6, 'photos'],
    [1, 'open issue', true],
    ['2h', 'hours lost', true],
  ]
  const fromDay = ['12 Mason', '5 Helper', 'Cement 150 bags', 'Slab shuttering', 'Mixer breakdown']
  const sections: [string, [string, string][]][] = [
    ['Work done', [['Slab shuttering, 2nd floor', 'In progress'], ['Column casting, grid C', 'Done']]],
    ['Manpower', [['Mason · Ravi contractor', '12'], ['Helper · Ravi contractor', '5'], ['Carpenter', '4']]],
    ['Materials', [['Cement (OPC 53) · in 150 · used 40', '210 bags'], ['TMT steel 12 mm', '3,400 kg']]],
  ]
  return (
    <div className="grid gap-8 lg:grid-cols-[minmax(0,0.75fr)_minmax(0,1.25fr)] lg:items-center">
      <div className="grid gap-5">
        <Kicker>Every evening</Kicker>
        <p className="m-0 font-bold leading-none tracking-[-0.05em]" style={at('meet-rise', 0.2)}>
          <span className="relative inline-block overflow-hidden text-[64px] sm:text-[88px]">
            <span className="block" style={still() ? { visibility: 'hidden' } : { animation: 'meet-out 400ms ease-in 1.2s both' }}>
              8:59
            </span>
            <span className="absolute inset-0" style={at('meet-in-up', 1.5, 400)}>
              9:00
            </span>
          </span>
          <span className="ml-2 text-[32px]">PM</span>
        </p>
        <p className="m-0 text-xl" style={at('meet-rise', 2)}>
          The day’s messages become the report. <b>Nobody typed it.</b>
        </p>
        <p className="m-0 text-base text-muted-foreground" style={at('meet-rise', 2.4)}>
          On your letterhead, with your logo and GSTIN. Needs attention first, then work, manpower, materials, photos and
          tomorrow’s plan.
        </p>
      </div>
      <div className="relative min-h-[460px]">
        {/* The morning's updates drop into the report. */}
        <p className="m-0 flex flex-wrap gap-1.5" aria-hidden="true">
          {fromDay.map((c, i) => (
            <span
              key={c}
              className="bg-[#d9fdd3] px-2 py-1 text-[12px] font-medium text-[#111]"
              style={still() ? { display: 'none' } : { animation: `meet-pop 400ms ease-out ${0.4 + i * 0.15}s both, meet-drop 600ms ease-in ${2.2 + i * 0.1}s forwards` }}
            >
              {c}
            </span>
          ))}
        </p>
        <div
          className="mt-3 border border-foreground/30 bg-background px-5 py-4 shadow-[8px_8px_0_0_var(--primary)]"
          style={still() ? undefined : { animation: 'meet-pop 600ms ease-out 2.6s both, meet-send 800ms ease-in 7.4s forwards' }}
        >
          <div className="flex items-start justify-between gap-3 border-b border-foreground pb-2">
            <span>
              <span className="block text-xs text-muted-foreground">Your Company Builders · Daily Progress Report</span>
              <span className="block text-[22px] font-bold tracking-[-0.02em]">{site}</span>
            </span>
            <FileText className="size-5 text-muted-foreground" />
          </div>
          <div className="grid grid-cols-3 gap-y-3 py-3 sm:grid-cols-6">
            {kpis.map(([n, w, red], i) => (
              <span key={w} style={at('meet-rise', 2.9 + i * 0.12)}>
                <span className={cn('block text-[26px] font-bold leading-none tabular-nums', red && 'text-[var(--destructive)]')}>
                  {typeof n === 'number' ? <Count to={n} delay={3 + i * 0.12} ms={700} /> : n}
                </span>
                <span className="text-[11px] text-muted-foreground">{w}</span>
              </span>
            ))}
          </div>
          <div className="border border-[var(--destructive)]/40 bg-[color-mix(in_srgb,var(--destructive)_6%,transparent)] px-3 py-2">
            <span className="font-mono text-[10px] uppercase tracking-[0.08em] text-[var(--destructive)]">Needs attention</span>
            {['Concrete mixer broke down · 2 hours lost', 'TMT steel 12 mm running low · about 3 days left', 'Transit mixer needed tomorrow by 8 AM'].map((l, i) => (
              <p key={l} className="m-0 mt-1 text-[13px] font-medium" style={at('meet-deal', 3.7 + i * 0.3)}>
                <span className="mr-2 text-[var(--destructive)]">{i + 1}</span>
                {l}
              </p>
            ))}
          </div>
          <div className="mt-2 grid gap-2 sm:grid-cols-3">
            {sections.map(([head, rows], i) => (
              <div key={head} style={at('meet-rise', 4.8 + i * 0.35)}>
                <span className="font-mono text-[10px] uppercase tracking-[0.08em] text-muted-foreground">{head}</span>
                {rows.map(([what, n]) => (
                  <p key={what} className="m-0 flex justify-between gap-2 border-b border-foreground/10 py-0.5 text-[12px]">
                    <span className="truncate">{what}</span>
                    <b className="shrink-0">{n}</b>
                  </p>
                ))}
              </div>
            ))}
          </div>
        </div>
        {/* …and it goes out on WhatsApp, as a PDF. */}
        <div className="absolute inset-x-0 top-1/3 grid justify-items-center gap-3" style={still() ? { display: 'none' } : { animation: 'meet-pop 500ms ease-out 8.1s both' }}>
          <div className="w-[300px] rounded-[12px] rounded-tl-none border border-foreground/15 bg-background p-3">
            <div className="flex items-center gap-3 bg-muted px-3 py-3">
              <span className="grid h-11 w-9 place-items-center bg-[var(--destructive)] text-[10px] font-bold text-white">PDF</span>
              <span className="min-w-0">
                <span className="block truncate text-sm font-semibold">DPR · {site} · today.pdf</span>
                <span className="text-xs text-muted-foreground">1 page · 240 KB</span>
              </span>
            </div>
            <p className="m-0 mt-2 text-right text-[11px] text-muted-foreground">
              9:00 PM <span className="text-[var(--info)]">✓✓</span>
            </p>
          </div>
          <p className="m-0 flex flex-wrap justify-center gap-2" style={at('meet-rise', 8.6)}>
            {['Owner', 'Project manager', 'Client'].map((w) => (
              <span key={w} className="flex items-center gap-1.5 border border-foreground bg-background px-3 py-1.5 text-sm font-medium">
                <WhatsAppIcon className="size-3.5" /> {w} <span className="text-[var(--info)]">✓✓</span>
              </span>
            ))}
          </p>
        </div>
      </div>
    </div>
  )
}

function OwnerScene({ site }: { site: string }) {
  const stock: [string, string, number, boolean?][] = [
    ['TMT steel 12 mm', '3,400 kg', 0.22, true],
    ['PVC conduit 20 mm', '60 nos', 0.15, true],
    ['Cement (OPC 53)', '210 bags', 0.62],
    ['M-sand', '120 bags', 0.48],
  ]
  const cost: [string, number][] = [
    ['Structural', 1248300],
    ['Labour', 640500],
    ['Masonry', 312850],
    ['Plumbing & CP', 174000],
    ['Electrical', 138000],
  ]
  const total = cost.reduce((n, [, v]) => n + v, 0)
  const rupees = (n: number) => `₹${n.toLocaleString('en-IN')}`
  const Sheet = ({ title, children, s }: { title: string; children: React.ReactNode; s: number }) => (
    <div className="border border-foreground/25 bg-background px-4 py-3 shadow-[6px_6px_0_0_var(--foreground)]" style={at('meet-pop', s, 550)}>
      <p className="m-0 flex justify-between border-b border-foreground pb-1.5 font-mono text-[10px] uppercase tracking-[0.08em]">
        <span>Mesiri · {title}</span>
        <span className="text-muted-foreground">{site}</span>
      </p>
      {children}
    </div>
  )
  return (
    <div className="grid gap-8">
      <div>
        <Kicker>Any time, for the owner</Kicker>
        <Big>Ask for it as an image. Forward it.</Big>
      </div>
      <div className="grid gap-8 lg:grid-cols-2">
        <div className="grid content-start gap-3">
          <Bubble me s={0.5}>
            {site} stock list image aayi ayakku
          </Bubble>
          <Sheet title="Stock" s={1.4}>
            {stock.map(([m, q, f, low], i) => (
              <div key={m} className="py-1.5" style={at('meet-deal', 1.8 + i * 0.2)}>
                <p className="m-0 flex justify-between text-[14px]">
                  <span>{m}</span>
                  <b className={cn(low && 'text-[var(--destructive)]')}>{q}</b>
                </p>
                <span className="mt-1 block h-1.5 bg-muted">
                  <span
                    className={cn('block h-full', low ? 'bg-[var(--destructive)]' : 'bg-foreground')}
                    style={{ width: `${f * 100}%`, ...(at('meet-grow', 2 + i * 0.2, 900) ?? {}) }}
                  />
                </span>
              </div>
            ))}
            <p className="m-0 mt-2 bg-[var(--destructive)] px-2 py-1 text-[11px] font-semibold uppercase tracking-[0.04em] text-white" style={at('meet-pop', 3.1, 400)}>
              TMT steel and PVC conduit running low
            </p>
          </Sheet>
        </div>
        <div className="grid content-start gap-3">
          <Bubble me s={3.6}>
            Project cost category wise venam, image
          </Bubble>
          <Sheet title="Cost by category · 1 Sep to today" s={4.5}>
            {cost.map(([c, v], i) => (
              <p key={c} className="m-0 grid grid-cols-[7.5rem_1fr_auto] items-center gap-3 py-1 text-[14px]" style={at('meet-deal', 4.9 + i * 0.18)}>
                <span>{c}</span>
                <span className="block h-2 bg-muted">
                  <span className="block h-full bg-primary" style={{ width: `${(v / cost[0][1]) * 100}%`, ...(at('meet-grow', 5 + i * 0.18, 900) ?? {}) }} />
                </span>
                <b className="tabular-nums">{rupees(v)}</b>
              </p>
            ))}
            <p className="m-0 mt-2 flex items-baseline justify-between border-t-2 border-foreground pt-2" style={at('meet-rise', 6)}>
              <span className="font-semibold">Total</span>
              <b className="text-[28px] tracking-[-0.02em] text-primary tabular-nums">
                <Count to={total} delay={6.1} ms={1200} format={rupees} />
              </b>
            </p>
          </Sheet>
        </div>
      </div>
    </div>
  )
}

function CloseScene({ number, link }: { number: string | null; link: string | null }) {
  return (
    <div className="grid gap-8 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,0.8fr)] lg:items-center">
      <div className="grid gap-6">
        <Big s={0.4} className="sm:text-[56px]">
          Just send a voice note.
          <br />
          <span className="text-primary">In any language.</span>
        </Big>
        <p className="m-0 text-xl text-muted-foreground" style={at('meet-rise', 1.6)}>
          No app to install, no forms to fill. Your team only does the first step.
        </p>
      </div>
      {link && (
        <div className="grid justify-items-start gap-3 border-2 border-foreground p-5" style={at('meet-pop', 2.2, 500)}>
          <QrCode value={link} label={`QR code to message Mesiri at ${number}`} className="size-40" />
          <p className="m-0 flex items-center gap-2 text-lg font-semibold">
            <WhatsAppIcon className="size-5" /> Try it now
          </p>
          <p className="m-0 text-sm text-muted-foreground">{number}</p>
        </div>
      )}
    </div>
  )
}

// ── The show ──────────────────────────────────────────────────────────────────

/** What Mesiri says over each scene, and how it looks saying it. */
const NARRATION: Record<SceneKey, { say: (to: string | null) => string; mood: 'hello' | 'listen' | 'think' | 'happy' | 'look' | 'send' }> = {
  title: { say: (to) => `Hi${to ? ` ${to}` : ''}, I’m Mesiri. Let me show you what I do.`, mood: 'hello' },
  card: { say: () => 'Your supervisor sends one voice note. I turn it into five updates.', mood: 'listen' },
  languages: { say: () => 'Malayalam, Manglish, Hinglish or English: it’s all the same to me.', mood: 'happy' },
  words: { say: () => 'Chaakku, lod, kambi: I know how sites talk.', mood: 'think' },
  ask: { say: () => 'Ask me anything about your site. I answer from your records.', mood: 'look' },
  catches: { say: () => 'I catch what people miss, and I ask only once.', mood: 'think' },
  report: { say: () => 'At 9 PM, the day’s messages become your report.', mood: 'send' },
  owner: { say: () => 'Owners ask for stock or cost as an image, and forward it.', mood: 'happy' },
  close: { say: () => 'Just send me a voice note. In any language.', mood: 'hello' },
}

/** A message the show adds to Live's stream as its scene starts (marked Sample there). */
export interface MeetSample {
  sender: string
  text: string
  kind: 'attendance' | 'delivery' | 'question' | 'correction' | 'report' | 'photo'
  label: string
  state: 'saved' | 'draft' | 'answered'
  reply: string
  voice?: boolean
}
export const MEET_SAMPLES: Partial<Record<SceneKey, MeetSample[]>> = {
  card: [
    {
      sender: 'Suresh · supervisor',
      text: 'Innu Ravi contractor-nte 12 mason, 5 helper. Cement 150 chaakku vannu, Malabar Traders. Second floor slab shuttering start cheythu. Mixer breakdown aayi, 2 hour poyi.',
      kind: 'attendance',
      label: 'Five updates',
      state: 'saved',
      reply: '5 updates for {site}. ✅ Saved.',
      voice: true,
    },
  ],
  ask: [
    { sender: 'Biju · engineer', text: 'സിമന്റ് എത്ര ചാക്ക് ബാക്കിയുണ്ട്?', kind: 'question', label: 'Question', state: 'answered', reply: '{site}-ൽ ഇപ്പോൾ 210 ചാക്ക് Cement ഉണ്ട്.' },
    { sender: 'Biju · engineer', text: 'Block B-il kambi ethra und?', kind: 'question', label: 'Question', state: 'answered', reply: 'Block B-il ippol 2,100 kg Steel und.' },
  ],
  catches: [
    { sender: 'Suresh · supervisor', text: 'cement 12 alla, 14 chaakku', kind: 'correction', label: 'Correction', state: 'saved', reply: 'Cement 12 → 14 chaakku aakki.' },
    { sender: 'Anil · supervisor', text: 'Attendance sheet (photo)', kind: 'photo', label: 'Photo', state: 'draft', reply: '21 lines ready from the sheet.' },
  ],
  report: [{ sender: 'Mesiri', text: 'Today’s report: 21 workers, 3 work items, 1 open issue.', kind: 'report', label: 'Report', state: 'saved', reply: 'Sent to Owner, PM and Client at 9:00 PM.' }],
  owner: [
    { sender: 'Owner', text: '{site} stock list image aayi ayakku', kind: 'question', label: 'Question', state: 'answered', reply: '{site} stock. TMT steel and PVC conduit are running low.' },
    { sender: 'Owner', text: 'Project cost category wise venam, image', kind: 'question', label: 'Question', state: 'answered', reply: '1 Sep to today: ₹25,13,650.' },
  ],
}

/** The show, played on Live's stage: the character narrates, the scene plays under it. */
export function MeetMesiri({
  to,
  site,
  number,
  short = false,
  presenting = false,
  onScene,
  onSay,
  onDone,
}: {
  to: string | null
  site: string | null
  number: string | null
  short?: boolean
  presenting?: boolean
  /** A scene starts (Live adds its sample messages to the stream). */
  onScene?: (scene: SceneKey) => void
  /** Mesiri's line for the scene, to be spoken (WEB-63). */
  onSay?: (line: string) => void
  onDone: () => void
}) {
  const scenes = short ? SHORT : FULL
  const [i, setI] = React.useState(0)
  const key = scenes[i]
  const place = site ?? 'Villa 3'
  const link = number ? `https://wa.me/${number.replace(/\D/g, '')}?text=${encodeURIComponent('Hi Mesiri')}` : null
  const narration = NARRATION[key]

  const next = React.useCallback(() => {
    if (i + 1 >= scenes.length) onDone()
    else setI(i + 1)
  }, [i, scenes.length, onDone])
  const back = React.useCallback(() => setI((n) => Math.max(0, n - 1)), [])

  React.useEffect(() => {
    onScene?.(key)
  }, [key, onScene])
  React.useEffect(() => {
    onSay?.(NARRATION[key].say(to))
  }, [key, to, onSay])
  React.useEffect(() => {
    const t = window.setTimeout(next, still() ? 4_000 : SCENE_MS[key])
    return () => window.clearTimeout(t)
  }, [key, next])
  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onDone()
      if (e.key === 'ArrowRight') next()
      if (e.key === 'ArrowLeft') back()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [next, back, onDone])

  return (
    <div aria-label="Meet Mesiri" className="grid w-full gap-5 text-left">
      <div className="flex items-center gap-3">
        <ol className="m-0 flex flex-1 list-none gap-1.5 p-0" aria-hidden="true">
          {scenes.map((sc, n) => (
            <li key={sc} className="h-1 flex-1 overflow-hidden bg-foreground/15">
              <span
                key={`${sc}-${n === i}`}
                className="block h-full bg-foreground"
                style={
                  n < i
                    ? { width: '100%' }
                    : n === i && !still()
                      ? { animation: `meet-grow ${SCENE_MS[sc]}ms linear both` }
                      : { width: n === i ? '100%' : '0%' }
                }
              />
            </li>
          ))}
        </ol>
        <button type="button" onClick={next} className="border border-foreground px-3 py-1 text-sm font-medium hover:bg-foreground hover:text-background">
          Next →
        </button>
        <button type="button" onClick={onDone} aria-label="Close" className="grid size-8 place-items-center border border-foreground hover:bg-foreground hover:text-background">
          <X className="size-4" />
        </button>
      </div>
      {/* Mesiri narrates. */}
      <div className="flex items-center gap-4 border-b border-foreground/15 pb-4">
        <Spark key={key} mood={narration.mood} size={presenting ? 96 : 72} className="shrink-0" />
        <div className="min-w-0">
          <p className="m-0 font-mono text-[11px] uppercase tracking-[0.08em] text-muted-foreground">
            Mesiri · {i + 1} of {scenes.length}
          </p>
          <p key={key} className={cn('m-0 mt-1 font-medium tracking-[-0.01em]', presenting ? 'text-[26px]' : 'text-[20px]')}>
            <Typed text={narration.say(to)} ms={22} />
          </p>
        </div>
      </div>
      <div key={key} className="min-h-[420px]">
        {key === 'title' && <TitleScene to={to} />}
        {key === 'card' && <CardScene site={place} />}
        {key === 'languages' && <LanguagesScene />}
        {key === 'words' && <WordsScene />}
        {key === 'ask' && <AskScene site={place} />}
        {key === 'catches' && <CatchesScene />}
        {key === 'report' && <ReportScene site={place} />}
        {key === 'owner' && <OwnerScene site={place} />}
        {key === 'close' && <CloseScene number={number} link={link} />}
      </div>
      <p className="m-0 flex items-center gap-1.5 font-mono text-[11px] uppercase tracking-[0.08em] text-muted-foreground">
        <Check className="size-3" /> Sample conversation · ← → to move · Esc to close
      </p>
    </div>
  )
}
