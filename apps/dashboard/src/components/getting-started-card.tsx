import * as React from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check } from 'lucide-react'
import { confirmReportTime, fetchSetupProgress, requestContinue, type SetupProgress } from '@/lib/api'
import { apiErrorMessage } from '@/lib/logo-upload'
import { useAuth } from '@/lib/AuthContext'
import { useTrial } from '@/lib/trial'
import { Button } from '@/components/ui/button'
import { cn, formatClock } from '@/lib/utils'

const HIDE_KEY = 'mesiri_getting_started_hidden'

// "Hide for now" is a per-browser convenience; the card goes for good once
// everything is done. Storage can be unavailable (private window), so never
// let it break the page.
function readHidden(orgId: string): boolean {
  try {
    return localStorage.getItem(`${HIDE_KEY}:${orgId}`) === '1'
  } catch {
    return false
  }
}

function writeHidden(orgId: string): void {
  try {
    localStorage.setItem(`${HIDE_KEY}:${orgId}`, '1')
  } catch {
    // nothing to do: the card just shows again next time
  }
}

interface Item {
  key: string
  done: boolean
  title: string
  detail: React.ReactNode
  action?: React.ReactNode
}

function items(p: SetupProgress, onTimeOk: () => void, savingTime: boolean): Item[] {
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
      title: 'Add your site supervisor',
      detail: 'On WhatsApp, share their contact with Mesiri, or add them on the Team page.',
      action: (
        <Link to="/team" className={linkClass}>
          Team
        </Link>
      ),
    },
    {
      key: 'update',
      done: p.first_update_at !== null,
      title: 'Get the first update from site',
      detail: "Your supervisor sends today's work to Mesiri on WhatsApp: a text, a voice note or photos.",
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
          Letterhead
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
  const { me } = useAuth()
  const queryClient = useQueryClient()
  const orgId = me?.org_id || me?.organization_id || ''
  const isCompanyAdmin = (me?.role ?? '').toUpperCase() === 'ADMIN' && !me?.is_platform_admin && !!orgId
  const [hidden, setHidden] = React.useState(() => (orgId ? readHidden(orgId) : false))

  const progress = useQuery({
    queryKey: ['setup-progress'],
    queryFn: fetchSetupProgress,
    enabled: isCompanyAdmin && !hidden,
    refetchInterval: 60_000,
  })
  const trial = useTrial()
  const continueAsk = useMutation({ mutationFn: requestContinue })
  const timeOk = useMutation({
    mutationFn: confirmReportTime,
    onSuccess: (data) => queryClient.setQueryData(['setup-progress'], data),
  })

  // Once the trial has ended the banner (trial-banner.tsx) takes over.
  if (!isCompanyAdmin || hidden || trial.readOnly || !progress.data) return null
  const list = items(progress.data, () => timeOk.mutate(), timeOk.isPending)
  const doneCount = list.filter((i) => i.done).length
  if (doneCount === list.length) return null
  const daysLeft = progress.data.effective_status === 'trial' ? progress.data.trial_days_left : null
  const continueAsked = trial.continueRequested || continueAsk.isSuccess

  return (
    // Compact (WEB-25 density): progress on the title line, done steps
    // folded into it; only the steps still to do get a row.
    <section aria-label="Getting started" className="flex flex-col gap-2 rounded-xl border px-4 py-3">
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
          onClick={() => {
            writeHidden(orgId)
            setHidden(true)
          }}
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
