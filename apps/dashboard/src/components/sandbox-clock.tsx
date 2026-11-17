import * as React from 'react'
import { Link } from 'react-router-dom'
import { CalendarClock, ChevronDown, ClipboardList, FastForward, History, Loader2, SkipForward, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { apiErrorMessage } from '@/lib/logo-upload'
import { catchUp, goBackTo, passDays, sandboxSession, takeDaysPassed, useSandboxClock, type ForYou } from '@/lib/sandbox'
import { findPage } from '@/lib/module-map'

// SS-74e (guided-demo-plan.md section 18): the sample company's days, in its banner. Next day and Skip ahead play the
// planned simulation (backend application/learn/sandbox_player.py): everyone else does their part; what is the
// person's to do waits for them under "For you", each with a link to the page it is done on.

const SKIPS = [2, 3, 7] as const

/** The words for what the cast did, by kind of entry (the plan's kinds, sample_plan.py KINDS). */
const DID: Record<string, string> = {
  conditions: 'site days written up', attendance: 'attendance', work: 'work recorded', use: 'material used',
  expense: 'expenses', issue: 'problems reported', request: 'material asked for', delivery: 'deliveries received',
  order: 'orders placed', boq_count: 'work put on the BOQ', issue_resolve: 'problems closed', work_order: 'work orders',
  measurement: 'measurements', supplier_bill: 'supplier bills booked', supplier_payment: 'suppliers paid',
  sub_bill: 'subcontract bills', sub_payment: 'subcontractor paid', advance: 'advances given', wage_pay: 'wages paid',
  client_receipt: 'client payments in', wage_approve: 'wage sheets approved', ra_bill: 'running bills sent',
  stage: 'project stage moved',
}

function dayName(iso: string): string {
  const d = new Date(`${iso}T12:00:00`)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short' })
}

function pageName(url: string): string {
  const [path, query = ''] = url.split('?')
  return findPage(path, query ? `?${query}` : '')?.page.title ?? path
}

/** The person's to-dos grouped by the page each is done on, in order of the first one. */
function byPage(items: ForYou[]): { page: string; items: ForYou[] }[] {
  const groups = new Map<string, ForYou[]>()
  for (const item of items) groups.set(item.page, [...(groups.get(item.page) ?? []), item])
  return [...groups].map(([page, list]) => ({ page, items: list }))
}

export function SandboxClock() {
  const session = sandboxSession()
  const clock = useSandboxClock()
  /** Days passing (1..7), or going back (-1). */
  const [busy, setBusy] = React.useState<number | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [away, setAway] = React.useState(takeDaysPassed)

  // Another tab moved the days on: this one opens the sample again on the current date (once).
  const date = clock.data?.date
  React.useEffect(() => {
    if (date && session?.today && date !== session.today && !clock.data?.old) void catchUp(date)
  }, [date, session?.today, clock.data?.old])

  if (!session || clock.isError) return null
  if (clock.data?.old) {
    return <p className="m-0 text-xs text-info/90">Made before days could pass: Start over to play them.</p>
  }
  const c = clock.data
  const done = !!c && c.day >= c.last_day
  const late = c ? c.for_you.filter((f) => f.day < c.day).length : 0

  const pass = async (days: number) => {
    setBusy(days)
    setError(null)
    try {
      await passDays(days)
    } catch (e) {
      setError(apiErrorMessage(e))
      setBusy(null)
    }
  }

  const back = async (day: number, date: string) => {
    const today = c && day === c.day
    if (!window.confirm(today
      ? `Try today again? Everything done since this morning (${dayName(date)}) is undone.`
      : `Go back to day ${day} (${dayName(date)})? Your sample company becomes exactly what it was that morning; the days after it are gone, and Next day plays them again.`)) return
    setBusy(-1)
    setError(null)
    try {
      await goBackTo(day)
    } catch (e) {
      setError(apiErrorMessage(e))
      setBusy(null)
    }
  }
  const saved = [...(c?.can_go_back_to ?? [])].reverse()

  return (
    <div className="flex flex-col gap-2" data-guide="sandbox.clock">
      <div className="flex flex-wrap items-center gap-2">
        <span className="inline-flex items-center gap-1.5 text-sm font-semibold">
          <CalendarClock className="size-4" aria-hidden />
          {c ? (
            <>
              Day {c.day} of {c.last_day} · {dayName(c.date)}
            </>
          ) : (
            'Day …'
          )}
        </span>
        {done ? (
          <span className="text-xs">Green Villa is handed over. Start over to play it again.</span>
        ) : (
          <>
            <Button size="sm" className="gap-1.5" disabled={!c || busy !== null} onClick={() => void pass(1)} data-guide="sandbox.next-day"
              aria-label="Move the sample company on to the next day">
              {busy === 1 ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : <SkipForward className="size-3.5" aria-hidden />}
              {busy === 1 ? 'A day passes…' : 'Next day'}
            </Button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button size="sm" variant="outline" className="gap-1.5 bg-background" disabled={!c || busy !== null}>
                  {busy && busy > 1 ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : <FastForward className="size-3.5" aria-hidden />}
                  {busy && busy > 1 ? `${busy} days pass…` : 'Skip ahead'}
                  <ChevronDown className="size-3.5" aria-hidden />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" className="w-64">
                <DropdownMenuLabel className="text-xs font-normal text-muted-foreground">
                  Everyone works through these days, you too; you land on the last with its work waiting for you.
                </DropdownMenuLabel>
                {SKIPS.map((n) => (
                  <DropdownMenuItem key={n} onSelect={() => void pass(n)}>
                    {n === 7 ? 'A week' : `${n} days`}
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
          </>
        )}
        {saved.length > 0 && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button size="sm" variant="outline" className="gap-1.5 bg-background" disabled={busy !== null} data-guide="sandbox.go-back">
                {busy === -1 ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : <History className="size-3.5" aria-hidden />}
                {busy === -1 ? 'Going back…' : 'Go back'}
                <ChevronDown className="size-3.5" aria-hidden />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="w-64">
              <DropdownMenuLabel className="text-xs font-normal text-muted-foreground">
                Back to the morning of a day you were on. Everything after it is undone.
              </DropdownMenuLabel>
              {saved.map((p) => (
                <DropdownMenuItem key={p.day} onSelect={() => void back(p.day, p.date)}>
                  {c && p.day === c.day ? 'Try today again' : `Day ${p.day} · ${dayName(p.date)}`}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        )}
        {c && c.for_you.length > 0 && <ForYouMenu items={c.for_you} late={late} />}
        {c && c.for_you.length === 0 && !done && <span className="text-xs text-info/90">Nothing waiting for you today.</span>}
      </div>
      {error && <p className="m-0 text-sm text-destructive">{error}</p>}
      {away && <Away away={away} onClose={() => setAway(null)} />}
    </div>
  )
}

function ForYouMenu({ items, late }: { items: ForYou[]; late: number }) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button size="sm" variant="outline" className="gap-1.5 bg-background" data-guide="sandbox.for-you">
          <ClipboardList className="size-3.5" aria-hidden />
          For you ({items.length}){late > 0 && <span className="text-destructive">· {late} late</span>}
          <ChevronDown className="size-3.5" aria-hidden />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="max-h-[70svh] w-[min(92vw,26rem)] overflow-y-auto">
        <DropdownMenuLabel className="text-xs font-normal text-muted-foreground">
          Your part of the day. Do each on its page; it is ticked off when it is saved. Left undone, what needs it waits.
        </DropdownMenuLabel>
        {byPage(items).map((group, i) => (
          <React.Fragment key={group.page}>
            {i > 0 && <DropdownMenuSeparator />}
            <DropdownMenuItem asChild>
              <Link to={group.page} className="flex flex-col items-start gap-0.5">
                <span className="text-sm font-medium">
                  {pageName(group.page)} <span className="font-normal text-muted-foreground">({group.items.length})</span>
                </span>
                {group.items.slice(0, 4).map((item) => (
                  <span key={item.id} className="text-xs text-muted-foreground">
                    {item.what}
                    {item.day < Math.max(...items.map((x) => x.day)) && <span className="text-destructive"> · from day {item.day}</span>}
                  </span>
                ))}
                {group.items.length > 4 && <span className="text-xs text-muted-foreground">and {group.items.length - 4} more</span>}
              </Link>
            </DropdownMenuItem>
          </React.Fragment>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

function Away({ away, onClose }: { away: NonNullable<ReturnType<typeof takeDaysPassed>>; onClose: () => void }) {
  const byWho = new Map<string, string[]>()
  for (const s of away.summary) byWho.set(s.who, [...(byWho.get(s.who) ?? []), `${DID[s.kind] ?? s.kind} ${s.count}`])
  const days = away.day - away.from
  return (
    <div className="rounded-lg border border-info/20 bg-background/70 p-2.5 text-sm text-foreground" role="status" data-guide="sandbox.away">
      <div className="flex items-start justify-between gap-2">
        <p className="m-0 font-medium">
          {days === 1 ? `Day ${away.day} at Green Villa Builders` : `Days ${away.from + 1} to ${away.day} passed`}
        </p>
        <button type="button" className="text-muted-foreground hover:text-foreground" aria-label="Close" onClick={onClose}>
          <X className="size-4" aria-hidden />
        </button>
      </div>
      {byWho.size === 0 ? (
        <p className="m-0 text-xs text-muted-foreground">A quiet day: nobody works on Sunday.</p>
      ) : (
        <ul className="m-0 mt-1 flex list-none flex-col gap-0.5 p-0 text-xs">
          {[...byWho].map(([who, did]) => (
            <li key={who}>
              <span className="font-medium">{who}:</span> <span className="text-muted-foreground">{did.join(', ')}</span>
            </li>
          ))}
        </ul>
      )}
      {away.waiting.length > 0 && (
        <p className="m-0 mt-1 text-xs text-draft">
          Waiting on something not done yet ({away.waiting.length}): {away.waiting.slice(0, 3).map((w) => `${w.who}: ${w.what}`).join('; ')}
          {away.waiting.length > 3 ? '…' : ''}
        </p>
      )}
      {away.failed.length > 0 && (
        <p className="m-0 mt-1 text-xs text-destructive">
          {away.failed.length} could not be saved: {away.failed.slice(0, 2).map((f) => f.what).join('; ')}
        </p>
      )}
    </div>
  )
}
