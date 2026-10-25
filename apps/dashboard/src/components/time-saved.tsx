import { useQuery } from '@tanstack/react-query'
import { Clock } from 'lucide-react'
import { fetchDprHistoryApi } from '@/lib/api'
import { localIsoDate } from '@/lib/site-day'

// What Mesiri saved the owner this week (onboarding follow-up): the daily
// reports that went out in the last 7 days, each counted at the time it
// takes to write one by hand. Only the count is measured; the minutes are an
// assumption, stated on the page, and kept in this one constant.

/** Minutes to write and send one daily report by hand (assumed, not measured). */
export const MINUTES_PER_REPORT = 25

function duration(minutes: number): string {
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  if (h === 0) return `${m} min`
  return m === 0 ? `${h} h` : `${h} h ${m} min`
}

export function TimeSaved() {
  const from = localIsoDate(new Date(Date.now() - 6 * 24 * 60 * 60 * 1000))
  const sent = useQuery({
    queryKey: ['time-saved', from],
    // Only the total matters: one row is the smallest page the API serves.
    queryFn: () => fetchDprHistoryApi({ level: 'project', status: 'published', date_from: from, limit: 1 }),
    staleTime: 5 * 60_000,
  })
  const reports = sent.data?.total ?? 0
  if (reports === 0) return null

  return (
    <p
      className="flex items-center gap-2 text-sm text-muted-foreground"
      title={`Counted at ${MINUTES_PER_REPORT} minutes to write and send a daily report by hand.`}
    >
      <Clock className="size-4 shrink-0" aria-hidden="true" />
      <span>
        This week Mesiri sent <b className="font-semibold text-foreground tabular-nums">{reports}</b> daily{' '}
        {reports === 1 ? 'report' : 'reports'} for you: about{' '}
        <b className="font-semibold text-foreground tabular-nums">{duration(reports * MINUTES_PER_REPORT)}</b> of writing
        saved.
      </span>
    </p>
  )
}
