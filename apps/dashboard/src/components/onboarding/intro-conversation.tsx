import * as React from 'react'
import { Button } from '@/components/ui/button'
import { MesiriWordmark } from '@/components/brand/mesiri-logo'
import { progress, useTimeline } from '@/lib/timeline'
import { Conversation, Exchange, ExchangeHeads, Fact, Label, Reveal, Rule, Waveform, Words } from './conversation'

// The signup intro (SS-18): an example site's evening, played once. A
// Malayalam voice note comes in on the left, Mesiri's reading and then the
// finished daily report go out on the right, and the page closes on the
// promise. The company and site are an example, labelled as one.

const VOICE_NOTE = 'ഇന്ന് 6 മേസൺമാരും 4 ഹെൽപ്പർമാരും. ഒന്നാം നിലയിലെ സ്ലാബ് ഷട്ടറിംഗ് കഴിഞ്ഞു. സിമന്റ് തീർന്നു.'
const TRANSLATION = "Six masons and four helpers today. First-floor slab shuttering is done. We're out of cement."
const END_MS = 14_000

const REPORT_ROWS: [string, React.ReactNode][] = [
  ['Manpower', <>Mason 6 · Helper 4 · <b className="font-semibold">Total 10</b></>],
  ['Work done', 'Slab shuttering, first floor: completed'],
  ['Issues', 'Cement stock exhausted; delivery needed before casting'],
  ['Reported by', 'Arun, site engineer · voice note'],
]

export function IntroConversation({ onStart, headerAction }: { onStart: () => void; headerAction?: React.ReactNode }) {
  const [run, setRun] = React.useState(0)
  const now = useTimeline(END_MS, run)
  const seen = (at: number) => now >= at
  const workers = Math.round(10 * progress(now, 5850, 900))
  const today = new Date().toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'short' })

  return (
    <Conversation now={now}>
      <header className="flex flex-wrap items-baseline justify-between gap-4 pt-7 pb-4">
        <MesiriWordmark className="text-lg" />
        <div className="flex items-baseline gap-5">
          <Label className="hidden normal-case tracking-normal sm:inline">{today} · Example site</Label>
          {headerAction}
        </div>
      </header>
      <Rule at={150} strong />
      <ExchangeHeads at={400} />
      <Rule at={550} />

      <Exchange
        time={<Reveal at={1000}><Label>18:41</Label></Reveal>}
        site={
          <div className="grid max-w-[440px] gap-3.5">
            <Reveal at={1000}><Label>Voice note · 0:12 · Malayalam</Label></Reveal>
            <Reveal at={1100}><Waveform played={progress(now, 1300, 2600)} /></Reveal>
            <p lang="ml" className="m-0 font-[Noto_Sans_Malayalam,var(--font-sans)] text-[19px] leading-relaxed">
              <Words text={VOICE_NOTE} at={3900} />
            </p>
            <Reveal at={4900}>
              <p className="m-0 max-w-[46ch] text-sm text-muted-foreground">{TRANSLATION}</p>
            </Reveal>
          </div>
        }
        mesiri={
          <div>
            <Reveal at={5600} className="mb-3"><Label>18:41 · Understood</Label></Reveal>
            <Rule at={5600} strong />
            <Fact at={5800} big value={workers} title="Workers" detail="6 masons, 4 helpers" />
            <Fact at={6300} value="1st floor" title="Slab shuttering" detail="Completed today" />
            <Fact at={6750} value="1 issue" title="Cement stock out" detail="Logged · needed before casting" />
          </div>
        }
      />
      <Rule at={7300} />

      <Exchange
        time={<Reveal at={7700}><Label>18:42</Label></Reveal>}
        site={<Reveal at={7700}><p className="m-0 text-[22px] font-medium tracking-[-0.01em]">Send today's report.</p></Reveal>}
        mesiri={
          <div>
            <Reveal at={8400} className="mb-3"><Label>18:42 · Daily progress report</Label></Reveal>
            <div
              className={
                'grid gap-3.5 border px-6 pt-5 pb-4 transition-colors duration-500 motion-reduce:transition-none max-sm:px-4 ' +
                (seen(8600) ? 'border-foreground' : 'border-transparent')
              }
            >
              <Reveal at={8800}>
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <div className="flex items-center gap-2.5 font-semibold">
                    <span className="grid size-[30px] place-items-center bg-foreground font-brand text-[11px] text-background">AB</span>
                    Arun Builders
                  </div>
                  <div className="text-right text-xs leading-snug text-muted-foreground">
                    <b className="block text-[13px] font-semibold text-foreground">DPR-0001</b>
                    Green Villa, Kakkanad
                  </div>
                </div>
              </Reveal>
              <div
                aria-hidden="true"
                className={
                  'h-[3px] origin-left bg-primary transition-transform duration-1000 ease-[cubic-bezier(.6,0,.2,1)] motion-reduce:transition-none ' +
                  (seen(9100) ? '' : 'scale-x-0')
                }
              />
              <div className="grid">
                {REPORT_ROWS.map(([label, value], i) => (
                  <Reveal key={label} at={9600 + i * 250}>
                    <div className="grid grid-cols-[112px_minmax(0,1fr)] gap-4 border-b py-2 text-[13.5px] max-sm:grid-cols-1 max-sm:gap-0.5">
                      <Label className="pt-0.5">{label}</Label>
                      <span>{value}</span>
                    </div>
                  </Reveal>
                ))}
              </div>
              <Reveal at={10_700}>
                <div className="flex flex-wrap justify-between gap-3">
                  <Label className="normal-case tracking-normal">Sent on WhatsApp · 18:42</Label>
                  <Label className="normal-case tracking-normal">PDF · 1 page</Label>
                </div>
              </Reveal>
            </div>
          </div>
        }
      />
      <Rule at={11_200} strong />

      <div className="grid grid-cols-1 gap-y-6 pt-11 @2xl:grid-cols-[72px_minmax(0,1fr)]">
        <h1 className="m-0 max-w-[18ch] text-[clamp(34px,6vw,72px)] leading-[0.98] font-semibold tracking-[-0.035em] text-balance @2xl:col-start-2">
          <Words text="One voice note in." at={11_600} step={110} />{' '}
          <Words text="A finished daily report out." at={12_000} step={110} className="text-muted-foreground" />
        </h1>
        <Reveal at={13_000} className="@2xl:col-start-2">
          <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
            <Button size="lg" className="rounded-none px-6" onClick={onStart}>
              Start free trial
            </Button>
            <span className="text-sm text-muted-foreground">No forms. No typing. Any language.</span>
            <button
              type="button"
              className="border-b border-foreground font-mono text-xs uppercase tracking-[0.06em]"
              onClick={() => setRun((r) => r + 1)}
            >
              Replay
            </button>
          </div>
        </Reveal>
      </div>
    </Conversation>
  )
}
