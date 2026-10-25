import * as React from 'react'
import { Link } from 'react-router-dom'
import { Check, X } from 'lucide-react'
import { useSetupProgress } from '@/lib/setup'
import { localIsoDate, projectDayPath } from '@/lib/site-day'
import { Button } from '@/components/ui/button'

// The first daily report going out is the moment Mesiri proves itself
// (SS-18 follow-up): a one-time note on Today with the way to the report
// and to the client. Shown for a few days after the first send; closing it
// is remembered in this browser only, a convenience like the scope picker.

const SHOW_FOR_MS = 3 * 24 * 60 * 60 * 1000
const SEEN_KEY = 'mesiri_first_report_seen'

function readSeen(companyKey: string): boolean {
  try {
    return localStorage.getItem(`${SEEN_KEY}:${companyKey}`) === '1'
  } catch {
    return false
  }
}

function writeSeen(companyKey: string): void {
  try {
    localStorage.setItem(`${SEEN_KEY}:${companyKey}`, '1')
  } catch {
    // shows again next time; nothing breaks
  }
}

export function FirstReportMoment() {
  const progress = useSetupProgress()
  const project = progress.data?.first_project
  const sentAt = progress.data?.first_dpr_sent_at
  // The first project stands for the company: every company has exactly one first.
  const companyKey = project?.id ?? ''
  const [closed, setClosed] = React.useState(false)

  if (!progress.isCompanyAdmin || !sentAt || !project || closed || readSeen(companyKey)) return null
  const sent = new Date(sentAt)
  if (Number.isNaN(sent.getTime()) || Date.now() - sent.getTime() > SHOW_FOR_MS) return null

  const close = () => {
    writeSeen(companyKey)
    setClosed(true)
  }
  const when = sent.toLocaleString([], { weekday: 'short', hour: 'numeric', minute: '2-digit' })

  return (
    <section
      aria-label="Your first daily report is out"
      className="relative flex flex-col gap-3 overflow-hidden rounded-xl border px-4 py-4 animate-in fade-in slide-in-from-top-1 duration-500 motion-reduce:animate-none sm:flex-row sm:items-center sm:gap-5"
    >
      <span
        aria-hidden="true"
        className="grid size-10 shrink-0 place-items-center rounded-full bg-primary text-primary-foreground animate-in zoom-in-50 duration-500 motion-reduce:animate-none"
      >
        <Check className="size-5" strokeWidth={3} />
      </span>
      <div className="min-w-0 flex-1">
        <h2 className="text-[17px] font-semibold tracking-[-0.01em]">Your first daily report is out.</h2>
        <p className="text-sm text-muted-foreground">
          {project.name} · sent {when}. From here on it goes out every evening, made from what your site sends.
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-2 pr-6 sm:pr-8">
        <Button asChild size="sm">
          <Link to={projectDayPath(project.id, localIsoDate(sent))}>See the report</Link>
        </Button>
        <Button asChild size="sm" variant="outline">
          <Link to={`/projects/${project.id}?tab=recipients`}>Send it to your client too</Link>
        </Button>
      </div>
      <button
        type="button"
        onClick={close}
        aria-label="Close"
        className="absolute top-2 right-2 grid size-7 place-items-center rounded-md text-muted-foreground hover:bg-muted"
      >
        <X className="size-4" />
      </button>
    </section>
  )
}
