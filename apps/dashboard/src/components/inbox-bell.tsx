import * as React from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Bell, CheckCircle2, ChevronRight } from 'lucide-react'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { KIND_LABEL, KIND_ORDER, fetchWaiting, waitedFor, waitingUrl, type Waiting, type WaitingItem } from '@/lib/approvals'
import { cn } from '@/lib/utils'

// NXT-08: the bell in the top bar. Its count is everything waiting for this person (site reports to confirm,
// material requests to decide, subcontractor bills, RA bill drafts, my tasks due); the panel lists them, urgent
// first, grouped; each row opens the record where it is decided. Read only: the bell never acts.

export function InboxBell() {
  const [open, setOpen] = React.useState(false)
  const query = useQuery({ queryKey: ['approvals', 'waiting'], queryFn: fetchWaiting, refetchInterval: 60_000, staleTime: 30_000 })
  const total = query.data?.total ?? 0
  const urgent = query.data?.urgent ?? 0
  const label = total > 0 ? `${total} waiting for you${urgent ? `, ${urgent} urgent` : ''}` : 'Nothing waiting for you'

  return (
    <>
      <button
        type="button"
        onClick={() => { setOpen(true); query.refetch() }}
        className={cn('relative inline-flex size-8 items-center justify-center rounded-full hover:bg-muted',
          total > 0 ? 'text-foreground' : 'text-muted-foreground')}
        title={label}
        aria-label={label}
      >
        <Bell className="size-[18px]" />
        {total > 0 && (
          <span className={cn('absolute -top-0.5 -right-0.5 min-w-4 rounded-full px-1 text-center text-[10px] leading-4 font-semibold text-white ring-2 ring-background tabular-nums',
            urgent > 0 ? 'bg-rose-500' : 'bg-orange-500')}>
            {total > 99 ? '99+' : total}
          </span>
        )}
      </button>
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent side="right" className="w-full gap-0 overflow-y-auto p-0 sm:max-w-[420px]">
          <SheetHeader className="border-b p-4">
            <SheetTitle>Waiting for you</SheetTitle>
            <SheetDescription>
              {query.data ? (total > 0 ? `${total} to deal with${urgent ? ` · ${urgent} urgent` : ''}` : 'All clear') : 'Loading'}
            </SheetDescription>
          </SheetHeader>
          <Body query={query} onPick={() => setOpen(false)} />
        </SheetContent>
      </Sheet>
    </>
  )
}

function Body({ query, onPick }: { query: { data?: Waiting; isError: boolean; refetch: () => unknown }; onPick: () => void }) {
  if (query.isError) {
    return (
      <div className="p-4 text-sm">
        The list did not load.{' '}
        <button type="button" className="font-medium underline underline-offset-2" onClick={() => query.refetch()}>Try again</button>
      </div>
    )
  }
  if (!query.data) {
    return (
      <div className="flex flex-col gap-2 p-4">
        <Skeleton className="h-14 w-full" />
        <Skeleton className="h-14 w-full" />
        <Skeleton className="h-14 w-full" />
      </div>
    )
  }
  const data = query.data
  const groups = KIND_ORDER.map((kind) => ({ kind, items: data.items.filter((i) => i.kind === kind) })).filter((g) => g.items.length)
  return (
    <div className="flex flex-col">
      {data.unavailable.length > 0 && (
        <p className="border-b bg-amber-50 px-4 py-2 text-xs text-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
          Could not check {data.unavailable.map((k) => KIND_LABEL[k].toLowerCase()).join(', ')} just now.
        </p>
      )}
      {groups.length === 0 ? (
        <div className="flex flex-col items-center gap-2 px-6 py-12 text-center">
          <CheckCircle2 className="size-8 text-emerald-600" />
          <p className="text-sm font-medium">Nothing is waiting for you</p>
          <p className="text-xs text-muted-foreground">Reports to confirm, requests, bills and your tasks show here when they need you.</p>
        </div>
      ) : (
        groups.map((g) => (
          <section key={g.kind} className="border-b last:border-b-0">
            <h3 className="flex items-center justify-between px-4 pt-3 pb-1 text-xs font-semibold text-muted-foreground">
              {KIND_LABEL[g.kind]}
              <span className="tabular-nums">{data.counts[g.kind] ?? g.items.length}</span>
            </h3>
            <ul>
              {g.items.map((item) => <Row key={`${item.kind}-${item.id}`} item={item} today={data.today} onPick={onPick} />)}
            </ul>
          </section>
        ))
      )}
      {data.items.length < data.total && (
        <p className="px-4 py-3 text-xs text-muted-foreground">Showing the first {data.items.length} of {data.total}.</p>
      )}
    </div>
  )
}

function Row({ item, today, onPick }: { item: WaitingItem; today: string; onPick: () => void }) {
  const where = [item.project_name, item.site_name].filter(Boolean).join(' · ')
  const waited = waitedFor(item.since, today)
  return (
    <li>
      <Link to={waitingUrl(item)} onClick={onPick} className="flex items-start gap-3 px-4 py-2.5 hover:bg-muted/60 focus-visible:bg-muted/60 focus-visible:outline-none">
        <span aria-hidden className={cn('mt-1.5 size-2 shrink-0 rounded-full', item.urgent ? 'bg-rose-500' : 'bg-orange-400')} />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium">{item.title}</span>
          {item.detail && <span className="block truncate text-xs text-muted-foreground">{item.detail}</span>}
          <span className="block truncate text-xs text-muted-foreground">
            {where}{where && waited ? ' · ' : ''}{waited && (item.urgent ? <span className="text-rose-600 dark:text-rose-400">{waited}</span> : waited)}
          </span>
        </span>
        <ChevronRight className="mt-1 size-4 shrink-0 text-muted-foreground" />
      </Link>
    </li>
  )
}
