import * as React from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ArrowRight, Check, ChevronDown, Clock, Footprints, MessageSquareText, Play, RotateCcw, Volume2 } from 'lucide-react'
import { Spark } from '@/components/live/spark'
import { SandboxCard } from '@/components/learn/sandbox-card'
import { StarterKit } from '@/components/learn/starter-kit'
import { PageHeader, Section, Segmented } from '@/components/page/page-kit'
import { Button } from '@/components/ui/button'
import { WhatsAppPreview } from '@/components/whatsapp-preview'
import { useAuth } from '@/lib/AuthContext'
import { api } from '@/lib/api'
import { useScope } from '@/lib/ScopeContext'
import { urlWithScope } from '@/lib/scope-url'
import { MODULE_GROUPS, findPage, type ModulePage } from '@/lib/module-map'
import { useModuleEnabled } from '@/lib/modules'
import { usePageTitle } from '@/lib/page-title'
import { useStartMode } from '@/lib/start-mode'
import { startWalkthrough } from '@/lib/tour-events'
import { useTrial } from '@/lib/trial'
import { cn } from '@/lib/utils'
import {
  FULL_WORKFLOWS, MODULE_WALKS, OUTCOME_WALKS, PAGE_WALKS, ROLE_PATHS, VOICED, WORKFLOWS, learnKey, walkFor, type Walkthrough,
} from '@/lib/walkthroughs'

// Learn Mesiri (SS-41, learning-centre-plan.md section 3): one page to pick a walkthrough and run it, by role,
// workflow, module or page, and per page the WhatsApp messages to try. The walkthroughs and their engine:
// lib/walkthroughs.ts and components/walkthrough.tsx. Done or not comes from users.guide_seen (`/learn/<id>`).

type Tab = 'you' | 'workflows' | 'modules' | 'pages'
const TABS: { value: Tab; label: string }[] = [
  { value: 'you', label: 'For you' },
  { value: 'workflows', label: 'Workflows' },
  { value: 'modules', label: 'Modules' },
  { value: 'pages', label: 'Pages' },
]

const KIND_LABEL: Record<Walkthrough['kind'], string> = {
  role: 'Your path',
  outcome: 'What you get',
  workflow: 'Workflow',
  module: 'Module',
  page: 'Page',
}

function WalkCard({ walk, done }: { walk: Walkthrough; done: boolean }) {
  const practice = walk.steps.some((s) => s.try)
  return (
    <li className="flex flex-col gap-2 rounded-xl border bg-card p-4">
      <div className="flex items-start justify-between gap-2">
        <span className="text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">{KIND_LABEL[walk.kind]}</span>
        {done ? (
          <span className="inline-flex items-center gap-1 rounded-full bg-success-soft px-2 py-0.5 text-[11px] font-medium text-success">
            <Check className="size-3" aria-hidden /> Done
          </span>
        ) : (
          <span className="text-[11px] text-muted-foreground">Not started</span>
        )}
      </div>
      <h3 className="m-0 text-[15px] font-semibold">{walk.title}</h3>
      <p className="m-0 flex-1 text-sm text-muted-foreground">{walk.about}</p>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
        <span className="inline-flex items-center gap-1"><Clock className="size-3.5" aria-hidden /> {walk.minutes} min</span>
        <span className="inline-flex items-center gap-1"><Footprints className="size-3.5" aria-hidden /> {walk.steps.length} steps</span>
        {practice && <span className="inline-flex items-center gap-1"><MessageSquareText className="size-3.5" aria-hidden /> You try it</span>}
        {VOICED.has(walk.id) && <span className="inline-flex items-center gap-1"><Volume2 className="size-3.5" aria-hidden /> With voice</span>}
      </div>
      <Button size="sm" variant={done ? 'outline' : 'default'} className="mt-1 gap-1.5 self-start" onClick={() => startWalkthrough(walk.id)}>
        {done ? <RotateCcw className="size-3.5" aria-hidden /> : <Play className="size-3.5" aria-hidden />}
        {done ? 'Play again' : 'Start'}
      </Button>
    </li>
  )
}

function Cards({ walks, seen }: { walks: Walkthrough[]; seen: Record<string, number> }) {
  return (
    <ul className="grid list-none grid-cols-1 gap-3 p-0 sm:grid-cols-2 xl:grid-cols-3">
      {walks.map((w) => (
        <WalkCard key={w.id} walk={w} done={(seen[learnKey(w.id)] ?? 0) >= (w.version ?? 1)} />
      ))}
    </ul>
  )
}

/** A page on the Pages tab: its tour, what to try on WhatsApp, and a way there. */
function PageRow({ page, walk, done }: { page: ModulePage; walk?: Walkthrough; done: boolean }) {
  const [open, setOpen] = React.useState(false)
  const { scope } = useScope()
  const examples = page.whatsapp ?? []
  return (
    <li className="flex flex-col gap-2 px-3 py-3">
      <div className="flex flex-wrap items-start gap-x-3 gap-y-2">
        <div className="min-w-0 flex-1 basis-56">
          <p className="m-0 flex items-center gap-1.5 text-sm font-medium">
            {page.title}
            {done && <Check className="size-3.5 text-success" aria-label="Tour done" />}
          </p>
          <p className="m-0 text-xs text-muted-foreground">{page.about}</p>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          {walk && (
            <Button size="sm" variant="outline" className="h-7 gap-1 px-2 text-xs" onClick={() => startWalkthrough(walk.id)}>
              <Play className="size-3" aria-hidden /> {done ? 'Tour again' : 'Tour'}
            </Button>
          )}
          {examples.length > 0 && (
            <Button size="sm" variant="outline" className="h-7 gap-1 px-2 text-xs" aria-expanded={open} onClick={() => setOpen(!open)}>
              Try it <ChevronDown className={cn('size-3 transition-transform', open && 'rotate-180')} aria-hidden />
            </Button>
          )}
          <Button size="sm" variant="ghost" className="h-7 gap-1 px-2 text-xs" asChild>
            <Link to={urlWithScope(page.url, scope)}>Open <ArrowRight className="size-3" aria-hidden /></Link>
          </Button>
        </div>
      </div>
      {open && <WhatsAppPreview examples={examples} className="max-w-md" />}
    </li>
  )
}

export default function LearnPage() {
  usePageTitle('Learn Mesiri')
  const { me } = useAuth()
  const guide = useStartMode()
  const trial = useTrial()
  const moduleOn = useModuleEnabled()
  const [params, setParams] = useSearchParams()
  const tab = (TABS.find((t) => t.value === params.get('view'))?.value ?? 'you') as Tab
  const role = me?.role
  const seen = guide.seen
  const mine = (walks: Walkthrough[]) => walks.filter((w) => walkFor(w, role))
  const isDone = (w: Walkthrough) => (seen[learnKey(w.id)] ?? 0) >= (w.version ?? 1)

  const groups = MODULE_GROUPS.filter((g) => moduleOn(g.module))
  const visiblePage = (p: ModulePage) =>
    p.status === 'built' && !p.shortcut && moduleOn(p.module) && (!p.roles || p.roles.includes((role ?? '').toUpperCase()))
  const pageVisible = (url: string | undefined) => {
    const hit = url ? findPage(url.split('?')[0]) : null
    return !!hit && moduleOn(hit.group.module) && visiblePage(hit.page)
  }
  const pageWalk = (p: ModulePage) =>
    PAGE_WALKS.find((w) => w.id !== 'app' && w.steps[0]?.page?.split('?')[0] === p.url.split('?')[0])
  const modules = mine(MODULE_WALKS).filter((w) => groups.some((g) => `module-${g.key}` === w.id))

  // The workflows tab: the full ones and any written whole; the parts (W2's first half) only appear inside them.
  const workflows = mine([...FULL_WORKFLOWS, ...WORKFLOWS.filter((w) => !w.part)])
  // For you: what this role gets out of Mesiri (asked 15 Nov: titled by the value, with how to get it), all of it as
  // one path, then the app and the page tours not done yet. A role without outcomes yet gets the workflows.
  const outcomes = mine(OUTCOME_WALKS)
  const forYou = [
    ...outcomes,
    ...mine(ROLE_PATHS),
    ...(outcomes.length ? [] : workflows),
    ...mine(PAGE_WALKS).filter((w) => !isDone(w) && (w.id === 'app' || pageVisible(w.steps[0]?.page))).slice(0, 6),
  ]

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-4 pb-8 sm:px-2">
      <PageHeader title="Learn Mesiri" subtitle="Pick a walkthrough. I show you each thing on the real page, and you try it yourself." />
      {['ADMIN', 'OWNER', 'SUPER_ADMIN'].includes(String(role ?? '').toUpperCase()) && <NarratorSamples />}
      {/* SS-67: the private sample company and the guided project in it. */}
      <SandboxCard />
      {/* SS-73: the paperwork to bring into it. */}
      <StarterKit />

      <div className="flex items-center gap-3 rounded-xl border bg-[#facc15]/10 px-4 py-3">
        <Spark mood="hello" size={44} quiet className="shrink-0" />
        <p className="m-0 text-sm">
          Practice is real: what you save is recorded. So each practice either has you tap Cancel on Mesiri's card, or ends by showing you how to take it back.
          {trial.readOnly && ' Your account is read-only right now, so the walkthroughs show the steps without the practice.'}
        </p>
      </div>

      <Segmented<Tab>
        label="Walkthroughs"
        value={tab}
        onChange={(v) => setParams((p) => {
          p.set('view', v)
          return p
        }, { replace: true })}
        options={TABS}
      />

      {tab === 'you' && (
        <Section title={outcomes.length ? 'What you get from Mesiri' : 'For you'} note="Start at the top, or with what matters most to you.">
          <Cards walks={forYou} seen={seen} />
        </Section>
      )}

      {tab === 'workflows' && (
        <Section title="Workflows" note="One job from start to finish, across pages.">
          <Cards walks={workflows} seen={seen} />
          <p className="m-0 text-sm text-muted-foreground">More workflows are on the way: a supplier bill to payment, subcontractors, billing the client, cost control, month end.</p>
        </Section>
      )}

      {tab === 'modules' && (
        <Section title="Modules" note="Every page of a module, one after another.">
          <Cards walks={modules} seen={seen} />
        </Section>
      )}

      {tab === 'pages' && (
        <div className="flex flex-col gap-5">
          {groups.map((g) => {
            const pages = g.pages.filter(visiblePage).filter((p) => pageWalk(p) || (p.whatsapp?.length ?? 0) > 0)
            if (pages.length === 0) return null
            return (
              <Section key={g.key} title={g.title} note={g.about}>
                <ul className="flex list-none flex-col divide-y rounded-lg border p-0">
                  {pages.map((p) => {
                    const walk = pageWalk(p)
                    return <PageRow key={p.url} page={p} walk={walk} done={!!walk && isDone(walk)} />
                  })}
                </ul>
              </Section>
            )
          })}
        </div>
      )}
    </div>
  )
}


// SS-64: hear the narrator voices on offer, each reading the same line, to choose the walkthroughs' voice. The choice
// is set on the server (MESIRI_SARVAM__GUIDE_TTS_MODEL / __GUIDE_TTS_SPEAKER), so it is the same for everyone.
const NARRATORS: { which: string; name: string; about: string }[] = [
  { which: 'shubh', name: 'Shubh', about: 'The voice now (Sarvam bulbul v3)' },
  { which: 'shubh_en_narration', name: 'Shubh, narration', about: 'Made for storytelling (bulbul v4)' },
  { which: 'kalpit_en_edtech', name: 'Kalpit, teaching', about: 'Made for lessons (bulbul v4)' },
  { which: 'sarang_en_narration', name: 'Sarang, narration', about: 'Made for storytelling (bulbul v4)' },
]

function NarratorSamples() {
  const [open, setOpen] = React.useState(false)
  const [playing, setPlaying] = React.useState<string | null>(null)
  const [failed, setFailed] = React.useState<string | null>(null)
  const audio = React.useRef<HTMLAudioElement | null>(null)
  React.useEffect(() => () => audio.current?.pause(), [])
  const play = async (which: string) => {
    audio.current?.pause()
    if (playing === which) {
      setPlaying(null)
      return
    }
    setFailed(null)
    setPlaying(which)
    try {
      const res = await api.get<Blob>('/dpr/live/voice/sample', { params: { which }, responseType: 'blob' })
      const a = (audio.current ??= new Audio())
      a.src = URL.createObjectURL(res.data)
      a.onended = () => setPlaying(null)
      await a.play()
    } catch {
      setFailed(which)
      setPlaying(null)
    }
  }
  return (
    <section className="rounded-xl border bg-card p-3 text-sm">
      <button type="button" className="flex w-full items-center justify-between gap-2 text-left font-medium" aria-expanded={open} onClick={() => setOpen(!open)}>
        <span className="inline-flex items-center gap-2"><Volume2 className="size-4" aria-hidden /> Choose the narrator</span>
        <ChevronDown className={cn('size-4 transition-transform', open && 'rotate-180')} aria-hidden />
      </button>
      {open && (
        <div className="mt-3 flex flex-col gap-2">
          <p className="m-0 text-xs text-muted-foreground">The same line in each voice. Tell the Mesiri team which you like; it is set once, for everyone.</p>
          <ul className="grid gap-2 sm:grid-cols-2">
            {NARRATORS.map((n) => (
              <li key={n.which} className="flex items-center justify-between gap-2 rounded-lg border px-3 py-2">
                <span className="min-w-0">
                  <span className="block font-medium">{n.name}</span>
                  <span className="block text-xs text-muted-foreground">{failed === n.which ? 'Not available right now' : n.about}</span>
                </span>
                <Button size="sm" variant="outline" className="h-7 shrink-0 gap-1 px-2 text-xs" onClick={() => void play(n.which)}>
                  {playing === n.which ? 'Stop' : <><Play className="size-3" aria-hidden /> Listen</>}
                </Button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}
