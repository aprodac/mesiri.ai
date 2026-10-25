import * as React from 'react'
import { Link, Navigate } from 'react-router-dom'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  confirmFactApi,
  fetchSetupProgress,
  fetchSiteDayApi,
  fetchSiteDayDocumentApi,
  fetchSiteDaysApi,
  type SiteDayDetail,
  type SiteDayItem,
} from '@/lib/api'
import { apiErrorMessage } from '@/lib/logo-upload'
import { hasUpdates, localIsoDate, siteDayPath } from '@/lib/site-day'
import { progress, useScenes } from '@/lib/timeline'
import { formatClock } from '@/lib/utils'
import { MesiriWordmark } from '@/components/brand/mesiri-logo'
import { DprDocument } from '@/components/dpr-document'
import { Exchange, ExchangeHeads, Fact, Label, Reveal, Rule, Words } from '@/components/onboarding/conversation'
import { SceneStage, SceneSteps } from '@/components/onboarding/scenes'
import { QrCode } from '@/components/onboarding/qr-code'
import { Button } from '@/components/ui/button'
import { useToast } from '@/components/ui/toast-notification'

// The welcome screen (SS-18): where web signup lands. The owner sends their
// first update to Mesiri on WhatsApp; this page waits for it and, the moment
// it arrives, shows what Mesiri understood and the daily report it makes, in
// the same layout as the signup intro. It is a real update on their real
// site (signup linked their number and made the site), so nothing here is a
// demo and nothing needs cleaning up. Skippable at every point.

/** Polling while waiting; stops after WAIT_MS and points at Today instead. */
const WAITING_POLL_MS = 3_000
const ARRIVED_POLL_MS = 15_000
const WAIT_MS = 10 * 60_000
const STEPS = [
  { key: 'send', label: 'Send' },
  { key: 'understood', label: 'Understood' },
  { key: 'report', label: 'Report' },
]
/** How long each scene runs once the update is in; the report stays. */
const DURATIONS = [2_600, 5_200, 1_500]

const EXAMPLE = '“Today 6 masons, 4 helpers. First-floor slab shuttering done. Cement ran out.”'

function pickSite(items: SiteDayItem[] | undefined, projectId: string | undefined): SiteDayItem | undefined {
  return items?.find((s) => s.project_id === projectId) ?? items?.[0]
}

function clock(iso: string | null): string {
  if (!iso) return ''
  return new Date(iso).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
}

interface Understood {
  key: string
  value: React.ReactNode
  big?: boolean
  title: string
  detail?: string
}

/** What Mesiri took from the day, most telling first: people, work, issues, materials. */
function understood(detail: SiteDayDetail): Understood[] {
  const out: Understood[] = []
  const labour = detail.report.labour
  if (labour.headcount > 0) {
    out.push({
      key: 'labour',
      value: labour.headcount,
      big: true,
      title: labour.headcount === 1 ? 'Worker' : 'Workers',
      // As the report says it: "Mason 6 · Helper 4".
      detail: labour.trades.map((t) => `${t.trade} ${t.headcount}`).join(' · ') || undefined,
    })
  }
  const groups: [string, string, string][] = [
    ['work', 'work item', 'work items'],
    ['issues', 'issue', 'issues'],
    ['materials', 'material', 'materials'],
  ]
  for (const [section, one, many] of groups) {
    const items = detail.items.filter((i) => i.section === section)
    if (items.length === 0) continue
    const first = items[0]
    out.push({
      key: section,
      value: `${items.length} ${items.length === 1 ? one : many}`,
      title: first.title ?? first.detail ?? '',
      detail: items.length > 1 ? `and ${items.length - 1} more` : first.title ? (first.detail ?? undefined) : undefined,
    })
  }
  return out
}

function Invite({ number, siteName }: { number: string | null; siteName: string }) {
  const toast = useToast()
  if (!number) {
    return (
      <div className="grid max-w-[440px] gap-3">
        <Label>Send to Mesiri on WhatsApp</Label>
        <p className="m-0 text-[22px] font-medium tracking-[-0.01em]">Open the WhatsApp chat your sign-in code came from.</p>
        <p className="m-0 text-sm text-muted-foreground">
          Send today's work for {siteName} there: a text, a voice note or photos. Any language.
        </p>
      </div>
    )
  }
  const digits = number.replace(/\D/g, '')
  const link = `https://wa.me/${digits}?text=${encodeURIComponent(`Today's update for ${siteName}: `)}`
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(number)
      toast.success('Number copied', number)
    } catch {
      toast.error('Could not copy', `Mesiri's number is ${number}.`)
    }
  }
  return (
    <div className="grid max-w-[440px] gap-4">
      <Label>Send to Mesiri on WhatsApp</Label>
      <div className="flex items-start gap-5">
        <QrCode value={link} label={`QR code to message Mesiri at ${number}`} className="hidden size-28 shrink-0 sm:block" />
        <div className="grid min-w-0 gap-1">
          <span className="text-[28px] leading-tight font-semibold tracking-[-0.02em] tabular-nums select-all">{number}</span>
          <span className="text-sm text-muted-foreground">
            <span className="hidden sm:inline">Scan with your phone, or open WhatsApp. </span>
            Send from the number you signed up with. A voice note is fine, in any language.
          </span>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
        <Button asChild className="rounded-none">
          <a href={link} target="_blank" rel="noreferrer">
            Open WhatsApp
          </a>
        </Button>
        <button type="button" className="border-b border-foreground font-mono text-xs uppercase tracking-[0.06em]" onClick={copy}>
          Copy number
        </button>
      </div>
    </div>
  )
}

function Waiting({ gaveUp }: { gaveUp: boolean }) {
  return (
    <div className="grid gap-3">
      <Label className="flex items-center gap-2">
        {!gaveUp && (
          <span className="relative flex size-2" aria-hidden="true">
            <span className="absolute inline-flex size-full animate-ping rounded-full bg-primary opacity-60 motion-reduce:animate-none" />
            <span className="relative inline-flex size-2 rounded-full bg-primary" />
          </span>
        )}
        {gaveUp ? 'Not here yet' : 'Listening'}
      </Label>
      <Rule strong />
      <p className="m-0 text-[22px] font-medium tracking-[-0.01em]" role="status">
        {gaveUp ? 'It will show on Today when it arrives.' : 'Waiting for your first update…'}
      </p>
      <p className="m-0 text-sm text-muted-foreground">
        Try something like {EXAMPLE} The moment it arrives, you see what Mesiri understood and the report it makes.
      </p>
      {gaveUp && (
        <Button asChild variant="outline" className="justify-self-start rounded-none">
          <Link to="/today">Go to Today</Link>
        </Button>
      )}
    </div>
  )
}

export default function WelcomePage() {
  const queryClient = useQueryClient()
  const toast = useToast()
  const [today] = React.useState(() => localIsoDate(new Date()))
  const [gaveUp, setGaveUp] = React.useState(false)
  React.useEffect(() => {
    const timer = window.setTimeout(() => setGaveUp(true), WAIT_MS)
    return () => window.clearTimeout(timer)
  }, [])

  const setup = useQuery({ queryKey: ['setup-progress'], queryFn: fetchSetupProgress, retry: false })
  const [arrived, setArrived] = React.useState(false)
  const days = useQuery({
    queryKey: ['welcome-site-days', today],
    queryFn: () => fetchSiteDaysApi(today),
    enabled: setup.isSuccess,
    refetchInterval: arrived ? ARRIVED_POLL_MS : gaveUp ? false : WAITING_POLL_MS,
  })
  const site = pickSite(days.data?.items, setup.data?.first_project?.id)
  const hasUpdate = !!site && hasUpdates(site)
  React.useEffect(() => {
    if (hasUpdate) setArrived(true)
  }, [hasUpdate])

  const detail = useQuery({
    queryKey: ['welcome-site-day', site?.site_id, today, site?.last_update_at],
    queryFn: () => fetchSiteDayApi(site!.site_id, today),
    enabled: hasUpdate,
    placeholderData: keepPreviousData,
  })

  const shown = !!detail.data
  // Send → Understood → Report, one scene at a time. Before the first update
  // the page rests on Send; once it is in, the scenes play through and stop
  // on the report. Any step can be chosen by hand.
  const scenes = useScenes(DURATIONS, (i) => (shown && i < STEPS.length - 1 ? i + 1 : null))
  const { go } = scenes
  React.useEffect(() => {
    if (shown) go(0)
  }, [shown, go])

  const confirm = useMutation({
    mutationFn: async (data: SiteDayDetail) => {
      for (const item of data.items.filter((i) => i.review === 'draft')) {
        await confirmFactApi(item.fact_type, item.id)
      }
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['welcome-site-day'] })
      void queryClient.invalidateQueries({ queryKey: ['setup-progress'] })
      toast.success('Confirmed', 'It goes in your daily report.')
    },
    onError: (err) => toast.error('Could not confirm', apiErrorMessage(err)),
  })

  // The checklist and this page are for the company's admin (setup-progress
  // refuses anyone else); everyone else goes straight to Today.
  if (setup.isError) return <Navigate to="/today" replace />

  const siteName = site?.site_name ?? setup.data?.first_project?.name ?? 'your site'
  const facts = detail.data ? understood(detail.data) : []
  const drafts = detail.data?.items.filter((i) => i.review === 'draft').length ?? 0
  const project = setup.data?.first_project
  const sendTime = formatClock(project?.send_time) ?? '9:00 pm'
  const now = scenes.now
  const steps = STEPS.map((step, i) => ({ ...step, disabled: i > 0 && !shown }))

  const message = site && (
    <div className="grid max-w-[440px] gap-3">
      <Label>{site.last_update_by ?? 'Update'}</Label>
      <p className="m-0 text-[19px] leading-relaxed">
        {scenes.index === 0 ? (
          <Words text={site.latest_update ?? 'Update received.'} at={100} step={45} />
        ) : (
          <span className="text-muted-foreground">{site.latest_update ?? 'Update received.'}</span>
        )}
      </p>
    </div>
  )

  const sendScene = site && (
    <Exchange
      time={<Label>{shown ? clock(site.last_update_at) : 'Now'}</Label>}
      site={shown ? message : <Invite number={setup.data?.whatsapp_number ?? null} siteName={siteName} />}
      mesiri={
        shown ? (
          <Reveal at={1200}>
            <Label className="flex items-center gap-2">
              <span className="size-1.5 rounded-full bg-foreground" aria-hidden="true" />
              Received · reading it
            </Label>
          </Reveal>
        ) : (
          <Waiting gaveUp={gaveUp} />
        )
      }
    />
  )

  const understoodScene = site && (
    <Exchange
      time={<Label>{clock(site.last_update_at)}</Label>}
      site={message}
      mesiri={
        <div>
          <Reveal at={0} className="mb-3">
            <Label>Understood</Label>
          </Reveal>
          <Rule at={100} strong />
          {facts.length === 0 ? (
            <Reveal at={300}>
              <p className="m-0 py-3 text-sm text-muted-foreground">
                Mesiri replied on WhatsApp. Have a look there, then add more about the day.
              </p>
            </Reveal>
          ) : (
            facts.map((f, i) => (
              <Fact
                key={f.key}
                at={300 + i * 450}
                big={f.big}
                value={f.big && typeof f.value === 'number' ? Math.round(f.value * progress(now, 350, 900)) : f.value}
                title={f.title}
                detail={f.detail}
              />
            ))
          )}
        </div>
      }
    />
  )

  const allConfirmed = confirm.isSuccess || drafts === 0
  const reportScene = site && (
    <Exchange
      time={<Label>Report</Label>}
      site={
        <Reveal at={600}>
          <div className="grid max-w-[440px] gap-4">
            <p className="m-0 text-[22px] font-medium tracking-[-0.01em]">
              {allConfirmed ? 'All confirmed.' : 'Does it look right?'}
            </p>
            <p className="m-0 text-sm text-muted-foreground">
              {allConfirmed
                ? `It goes in today's report. Send more updates any time before ${sendTime}.`
                : 'Confirm what Mesiri understood, or change anything first. Your site team’s updates will land here the same way.'}
            </p>
            <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
              {!allConfirmed ? (
                <Button className="rounded-none" disabled={confirm.isPending} onClick={() => detail.data && confirm.mutate(detail.data)}>
                  {confirm.isPending ? 'Confirming…' : 'Looks right'}
                </Button>
              ) : (
                <Button asChild className="rounded-none">
                  <Link to="/today">Go to Today</Link>
                </Button>
              )}
              <Link
                to={siteDayPath(site.site_id, today)}
                className="border-b border-foreground font-mono text-xs uppercase tracking-[0.06em]"
              >
                Change something
              </Link>
            </div>
          </div>
        </Reveal>
      }
      mesiri={
        <Reveal at={0}>
          <DprDocument
            queryKey={['welcome-document', site.site_id, today, site.last_update_at]}
            fetchHtml={() => fetchSiteDayDocumentApi(site.site_id, today)}
            live
            title={`${siteName} daily report`}
          />
        </Reveal>
      }
    />
  )

  return (
    <div className="min-h-svh bg-background px-4 pb-16 sm:px-8 lg:px-12">
      <div className="mx-auto max-w-[1120px] @container">
        <header className="flex flex-wrap items-baseline justify-between gap-4 pt-7 pb-4">
          <MesiriWordmark className="text-lg" />
          <Link to="/today" className="text-sm text-muted-foreground underline underline-offset-2">
            Skip, go to Today
          </Link>
        </header>
        <Rule strong />

        <div className="py-8">
          <h1 className="m-0 max-w-[18ch] text-[clamp(30px,4.5vw,52px)] leading-[1.02] font-semibold tracking-[-0.03em] text-balance">
            {shown ? 'Your first daily report.' : 'Send your first update.'}
          </h1>
          <p className="mt-3 mb-0 max-w-[56ch] text-muted-foreground">
            {shown
              ? `Made from what you sent for ${siteName}. Check it, then it goes out at ${sendTime}${project?.auto_dpr ? ' by itself' : ' when you send it'}.`
              : `Tell Mesiri what happened at ${siteName} today, the way you'd tell a colleague. Mesiri turns it into your daily report.`}
          </p>
        </div>

        <Rule strong />
        <SceneSteps steps={steps} index={scenes.index} progress={shown ? scenes.progress : 0} onSelect={scenes.select} />
        <ExchangeHeads />
        <Rule />

        {days.isLoading || setup.isLoading ? (
          <p className="py-7 text-sm text-muted-foreground">Loading…</p>
        ) : !site ? (
          <div className="grid gap-3 py-7">
            <p className="m-0">Add a site first, then send its update.</p>
            <Button asChild variant="outline" className="justify-self-start rounded-none">
              <Link to="/projects">Projects & sites</Link>
            </Button>
          </div>
        ) : (
          <SceneStage stacked={false} index={scenes.index} now={now} scenes={[sendScene, understoodScene, reportScene]} />
        )}
      </div>
    </div>
  )
}
