import * as React from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Check } from 'lucide-react'
import { confirmReportTime, hideSetupCard, requestContinue, showSetupCard, type SetupProgress } from '@/lib/api'
import { apiErrorMessage } from '@/lib/logo-upload'
import { setupSteps, useSetupProgress } from '@/lib/setup'
import { useTrial } from '@/lib/trial'
import { inviteText } from '@/lib/invite'
import { Button } from '@/components/ui/button'
import { useToast } from '@/components/ui/toast-notification'
import { cn, formatClock } from '@/lib/utils'

interface Item {
  key: string
  done: boolean
  title: string
  detail: React.ReactNode
  action?: React.ReactNode
}

function items(p: SetupProgress, onTimeOk: () => void, savingTime: boolean, invite: (() => void) | null): Item[] {
  const sendTime = formatClock(p.first_project?.send_time) ?? '9:00 pm'
  const linkClass = 'font-medium text-foreground underline underline-offset-2'
  return [
    {
      key: 'site',
      done: p.has_site,
      title: 'Add your first site',
      detail: 'Each site gets its own daily report.',
      action: (
        <Link to="/projects" className={linkClass}>
          Projects & sites
        </Link>
      ),
    },
    {
      key: 'team',
      done: p.has_team,
      // The person who reports from site: in Mesiri's roles, a Site Engineer
      // (supervisors included; WEB-17 decided against a separate role).
      title: 'Add the person who reports from site',
      detail: 'Your site engineer or supervisor. On WhatsApp, share their contact with Mesiri, or add them on the Team page with just their number.',
      action: (
        <span className="flex items-center gap-3">
          {invite && (
            <button type="button" className={linkClass} onClick={invite}>
              Copy invite
            </button>
          )}
          <Link to="/team" className={linkClass}>
            Team
          </Link>
        </span>
      ),
    },
    {
      key: 'update',
      done: p.first_update_at !== null,
      title: 'Get the first update from site',
      detail: "You or your supervisor send today's work to Mesiri on WhatsApp: a text, a voice note or photos.",
      action: (
        <Link to="/welcome" className={linkClass}>
          Send it now
        </Link>
      ),
    },
    {
      key: 'time',
      done: p.report_time_set,
      title: p.report_time_set
        ? 'Report time chosen'
        : p.first_project?.auto_dpr
          ? `Your report goes out at ${sendTime}`
          : `Report time: ${sendTime}`,
      detail: p.report_time_set
        ? p.first_project?.auto_dpr
          ? `Reports go out at ${sendTime}.`
          : `Report time is ${sendTime}.`
        : 'Keep it, or pick a time that suits you.',
      action: p.first_project && (
        <span className="flex items-center gap-3">
          {!p.report_time_set && (
            <Button size="sm" variant="outline" className="h-7" disabled={savingTime} onClick={onTimeOk}>
              {sendTime} is fine
            </Button>
          )}
          <Link to={`/projects/${p.first_project.id}?tab=reporting`} className={linkClass}>
            Change
          </Link>
        </span>
      ),
    },
    {
      key: 'logo',
      done: p.has_logo,
      title: 'Put your logo on the report',
      detail: 'It goes at the top of every daily report.',
      action: (
        <Link to="/company?tab=letterhead" className={linkClass}>
          Add logo
        </Link>
      ),
    },
    {
      key: 'dpr',
      done: p.first_dpr_sent_at !== null,
      title: 'First daily report sent',
      // Only promise an automatic send when the project has one (WEB-15).
      detail: p.first_project?.auto_dpr
        ? `It goes out by itself at ${sendTime} once updates come in, or use Send now below.`
        : 'Use Send now below once updates come in. To send it by itself every day, turn on automatic DPR in the project.',
      action: p.first_project && !p.first_project.auto_dpr && (
        <Link to={`/projects/${p.first_project.id}?tab=reporting`} className={linkClass}>
          Turn on
        </Link>
      ),
    },
  ]
}

/**
 * The owner's getting-started checklist (SS-07), at the top of Today. Ticks
 * come from what actually happened (GET /company/setup-progress), so nobody
 * ticks anything by hand. Company admins only; gone once everything is done.
 */
export function GettingStartedCard() {
  const queryClient = useQueryClient()
  const progress = useSetupProgress()
  const { isCompanyAdmin } = progress
  // The sidebar's "Finish setup" (SS-19) asks for the card even when hidden.
  const [params, setParams] = useSearchParams()
  const asked = params.get('setup') === '1'
  const section = React.useRef<HTMLElement>(null)
  const trial = useTrial()
  const save = (data: SetupProgress) => queryClient.setQueryData(['setup-progress'], data)
  // "Hide for now" holds for the whole company for a week (SS-19).
  const hide = useMutation({
    mutationFn: hideSetupCard,
    onSuccess: (data) => {
      save(data)
      // Drop ?setup=1, or the card would ask to be shown again at once.
      if (asked) {
        setParams(
          (prev) => {
            const next = new URLSearchParams(prev)
            next.delete('setup')
            return next
          },
          { replace: true },
        )
      }
    },
  })
  const show = useMutation({ mutationFn: showSetupCard, onSuccess: save })
  const hiddenUntil = progress.data?.hidden_until
  const showCard = show.mutate
  // Once per visit from the link: hiding again while the address still says
  // ?setup=1 must not bring the card straight back.
  const handled = React.useRef(false)
  React.useEffect(() => {
    if (!asked) {
      handled.current = false
      return
    }
    if (handled.current || hiddenUntil === undefined) return
    handled.current = true
    if (hiddenUntil) showCard()
    section.current?.scrollIntoView({ block: 'start' })
  }, [asked, hiddenUntil, showCard])
  const toast = useToast()
  const continueAsk = useMutation({ mutationFn: requestContinue })
  const timeOk = useMutation({
    mutationFn: confirmReportTime,
    onSuccess: save,
  })

  // Once the trial has ended the banner (trial-banner.tsx) takes over: the
  // dashboard is read-only, so none of these could be done anyway.
  const hidden = !!hiddenUntil && !(asked && !hide.isSuccess)
  if (!isCompanyAdmin || hidden || trial.readOnly || !progress.data) return null
  const number = progress.data.whatsapp_number
  const site = progress.data.first_project?.name
  // A message the owner forwards to their supervisor (SS-18): Mesiri's
  // number and what to send, so nobody has to explain it.
  const invite = number
    ? async () => {
        const text = inviteText({ number, site })
        try {
          await navigator.clipboard.writeText(text)
          toast.success('Invite copied', 'Paste it to your supervisor on WhatsApp.')
        } catch {
          toast.error('Could not copy', text)
        }
      }
    : null
  const list = items(progress.data, () => timeOk.mutate(), timeOk.isPending, invite)
  const doneCount = setupSteps(progress.data).filter(Boolean).length
  if (doneCount === list.length) return null
  const daysLeft = progress.data.effective_status === 'trial' ? progress.data.trial_days_left : null
  const continueAsked = trial.continueRequested || continueAsk.isSuccess

  return (
    // Compact (WEB-25 density): progress on the title line, done steps
    // folded into it; only the steps still to do get a row.
    <section ref={section} aria-label="Getting started" className="scroll-mt-16 flex flex-col gap-2 rounded-xl border px-4 py-3">
      <header className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-3 gap-y-1">
          <h2 className="text-sm font-semibold">Getting started</h2>
          <div className="h-1.5 w-24 overflow-hidden rounded-full bg-muted" aria-hidden>
            <div className="h-full bg-primary transition-all" style={{ width: `${(doneCount / list.length) * 100}%` }} />
          </div>
          <p className="text-xs text-muted-foreground">
            {doneCount} of {list.length} done
            {daysLeft !== null && ` · ${daysLeft} ${daysLeft === 1 ? 'day' : 'days'} left in your free trial`}
            {daysLeft !== null &&
              (continueAsked ? (
                ' · our team will call you'
              ) : (
                <>
                  {' · '}
                  <button
                    type="button"
                    className="font-medium text-foreground underline underline-offset-2 disabled:opacity-60"
                    disabled={continueAsk.isPending}
                    onClick={() => continueAsk.mutate()}
                  >
                    Continue with Mesiri
                  </button>
                </>
              ))}
          </p>
        </div>
        <button
          type="button"
          className="text-xs text-muted-foreground underline underline-offset-2"
          disabled={hide.isPending}
          onClick={() => hide.mutate()}
        >
          Hide for now
        </button>
      </header>
      <ul className="flex flex-col divide-y">
        {list.filter((item) => !item.done).map((item) => (
          <li key={item.key} className="flex items-start gap-3 py-2">
            <span
              className={cn(
                'mt-0.5 size-5 shrink-0 rounded-full border flex items-center justify-center',
                item.done ? 'bg-primary border-primary text-primary-foreground' : 'border-muted-foreground/40',
              )}
              aria-label={item.done ? 'Done' : 'Not done yet'}
            >
              {item.done && <Check className="size-3.5" strokeWidth={3} />}
            </span>
            <div className="flex-1 min-w-0 flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-4">
              <div className="flex-1 min-w-0">
                <p className={cn('text-sm font-medium', item.done && 'text-muted-foreground line-through')}>
                  {item.title}
                </p>
                {!item.done && <p className="text-xs text-muted-foreground">{item.detail}</p>}
              </div>
              {!item.done && item.action && <div className="text-sm shrink-0">{item.action}</div>}
            </div>
          </li>
        ))}
      </ul>
      {timeOk.isError && <p className="text-sm text-destructive">{apiErrorMessage(timeOk.error)}</p>}
      {continueAsk.isError && <p className="text-sm text-destructive">{apiErrorMessage(continueAsk.error)}</p>}
    </section>
  )
}
