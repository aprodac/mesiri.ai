import * as React from 'react'
import { Link } from 'react-router-dom'
import { useInfiniteQuery } from '@tanstack/react-query'
import { History, MessageCircle, Monitor, Search } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { EmptyState, ModuleTitle, PageError, Segmented } from '@/components/page/page-kit'
import { useAuth } from '@/lib/AuthContext'
import { activityUrl, fetchActivity, type ActivityFilters, type ActivityItem } from '@/lib/admin'
import { usePageTitle } from '@/lib/page-title'
import { toLocalISODate } from '@/lib/utils'

// ADM-02: Settings › Activity log. Who changed what, when: every save, edit, delete and approval, on the web and
// on WhatsApp, newest first, by day. Read only, for the owner and admins. Written by one recorder at the API
// (mesiri/http/activity.py), so every module is in it without its own code.

const ADMIN_ROLES = ['ADMIN', 'OWNER', 'SUPER_ADMIN']
type Range = 'today' | 'week' | 'month' | 'all'
type Source = 'all' | 'web' | 'whatsapp'

function since(range: Range): string | undefined {
  const now = new Date()
  if (range === 'today') return toLocalISODate(now)
  if (range === 'week') return toLocalISODate(new Date(now.getFullYear(), now.getMonth(), now.getDate() - 6))
  if (range === 'month') return toLocalISODate(new Date(now.getFullYear(), now.getMonth(), now.getDate() - 29))
  return undefined
}

export default function ActivityLogPage() {
  usePageTitle('Activity log')
  const { me } = useAuth()
  const allowed = ADMIN_ROLES.includes(String(me?.role ?? '').toUpperCase())
  const [person, setPerson] = React.useState('all')
  const [range, setRange] = React.useState<Range>('week')
  const [source, setSource] = React.useState<Source>('all')
  const [typed, setTyped] = React.useState('')
  const [q, setQ] = React.useState('')
  React.useEffect(() => {
    const t = window.setTimeout(() => setQ(typed.trim()), 300)
    return () => window.clearTimeout(t)
  }, [typed])

  const filters: ActivityFilters = {
    user_id: person === 'all' ? undefined : person,
    source: source === 'all' ? undefined : source,
    date_from: since(range),
    q: q || undefined,
  }
  const query = useInfiniteQuery({
    queryKey: ['activity', filters],
    queryFn: ({ pageParam }) => fetchActivity(filters, pageParam),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next,
    enabled: allowed,
  })
  const items = React.useMemo(() => query.data?.pages.flatMap((p) => p.items) ?? [], [query.data])
  const people = query.data?.pages[0]?.people ?? []
  const days = React.useMemo(() => groupByDay(items), [items])

  return (
    <div className="mx-auto flex w-full flex-col gap-4 pb-8 sm:px-2">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <ModuleTitle icon={History} title="Activity log" />
      </header>
      {!allowed ? (
        <p className="text-sm text-muted-foreground">The activity log is for the owner and admins.</p>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <Segmented label="When" value={range} onChange={setRange} options={[
              { value: 'today', label: 'Today' }, { value: 'week', label: '7 days' },
              { value: 'month', label: '30 days' }, { value: 'all', label: 'All' }]} />
            <Segmented label="Where" value={source} onChange={setSource} options={[
              { value: 'all', label: 'All' }, { value: 'web', label: 'Web' }, { value: 'whatsapp', label: 'WhatsApp' }]} />
            <Select value={person} onValueChange={setPerson}>
              <SelectTrigger className="h-9 w-[180px]" aria-label="Person"><SelectValue placeholder="Everyone" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Everyone</SelectItem>
                {people.map((p) => <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>)}
              </SelectContent>
            </Select>
            <label className="relative min-w-[180px] flex-1 sm:max-w-xs">
              <span className="sr-only">Search</span>
              <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input value={typed} onChange={(e) => setTyped(e.target.value)} placeholder="RA-02, task, cement…" className="h-9 pl-8" />
            </label>
          </div>
          {query.isError ? (
            <PageError message="The activity log did not load." onRetry={() => query.refetch()} back={{ to: '/settings', label: 'Settings' }} />
          ) : !query.data ? (
            <Skeleton className="h-48 w-full" />
          ) : items.length === 0 ? (
            <EmptyState icon={History} title="Nothing in this view"
              about="Every save, edit, delete and approval shows here with who made it and when, from the web and from WhatsApp." />
          ) : (
            <div className="flex flex-col gap-4">
              {days.map(([day, rows]) => (
                <section key={day}>
                  <h2 className="mb-1 text-xs font-semibold text-muted-foreground">{dayLabel(day)}</h2>
                  <ul className="divide-y rounded-lg border">
                    {rows.map((item) => <Row key={item.id} item={item} />)}
                  </ul>
                </section>
              ))}
              {query.hasNextPage && (
                <Button variant="outline" className="self-center" disabled={query.isFetchingNextPage} onClick={() => query.fetchNextPage()}>
                  {query.isFetchingNextPage ? 'Loading…' : 'Show older'}
                </Button>
              )}
            </div>
          )}
        </>
      )}
    </div>
  )
}

function Row({ item }: { item: ActivityItem }) {
  const url = activityUrl(item)
  const time = new Date(item.at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
  const label = item.record_label
  return (
    <li className="flex items-start gap-3 px-3 py-2.5 text-sm">
      <span className="w-16 shrink-0 pt-0.5 text-xs text-muted-foreground tabular-nums">{time}</span>
      <span className="min-w-0 flex-1">
        <span>{item.action}</span>
        {label && (url ? <> <Link to={url} className="font-medium underline-offset-2 hover:underline">{label}</Link></> : <> <span className="font-medium">{label}</span></>)}
        {!label && url && <> · <Link to={url} className="text-muted-foreground underline-offset-2 hover:underline">open</Link></>}
        <span className="block text-xs text-muted-foreground">{item.actor_name ?? 'Someone'}</span>
      </span>
      <span className="flex shrink-0 items-center gap-1 text-xs text-muted-foreground" title={item.source === 'whatsapp' ? 'On WhatsApp' : 'On the web'}>
        {item.source === 'whatsapp' ? <MessageCircle className="size-3.5 text-emerald-600" /> : <Monitor className="size-3.5" />}
        <span className="hidden sm:inline">{item.source === 'whatsapp' ? 'WhatsApp' : 'Web'}</span>
      </span>
    </li>
  )
}

function groupByDay(items: ActivityItem[]): [string, ActivityItem[]][] {
  const out = new Map<string, ActivityItem[]>()
  for (const item of items) {
    const day = toLocalISODate(new Date(item.at))
    out.set(day, [...(out.get(day) ?? []), item])
  }
  return [...out.entries()]
}

function dayLabel(day: string): string {
  const today = toLocalISODate(new Date())
  const yesterday = toLocalISODate(new Date(Date.now() - 86_400_000))
  if (day === today) return 'Today'
  if (day === yesterday) return 'Yesterday'
  return new Date(`${day}T00:00:00`).toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short' })
}
