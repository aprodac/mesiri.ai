import * as React from 'react'
import { useQuery } from '@tanstack/react-query'
import { TriangleAlert } from 'lucide-react'
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from '@/components/ui/sheet'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { fetchLedger, REASON_WORDS, type LedgerEntry, type StockState } from '@/lib/materials'
import { fetchUsers } from '@/lib/api'
import { qty } from '@/lib/site-day'
import { cn } from '@/lib/utils'

// One material at one site, every movement with the stock after it
// (WEB-29: plain words, names instead of user ids, no code badges).

const shortDay = (iso: string) => new Date(`${iso}T00:00:00`).toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short' })

const PAGE_SIZE = 25

interface MaterialLedgerSheetProps {
  siteId: string | null
  materialId: string
  materialName: string
  open: boolean
  onOpenChange: (open: boolean) => void
  stockState?: StockState
}

export function MaterialLedgerSheet({
  siteId,
  materialId,
  materialName,
  open,
  onOpenChange,
  stockState,
}: MaterialLedgerSheetProps) {
  const [entries, setEntries] = React.useState<LedgerEntry[]>([])
  const [offset, setOffset] = React.useState(0)

  React.useEffect(() => {
    if (open) {
      setEntries([])
      setOffset(0)
    }
  }, [open, siteId, materialId])

  const { data, isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: ['materials', 'ledger', siteId, materialId, offset],
    queryFn: () => fetchLedger(siteId!, materialId, { limit: PAGE_SIZE, offset }),
    enabled: open && !!siteId && !!materialId,
  })

  React.useEffect(() => {
    if (!data) return
    setEntries((prev) => (offset === 0 ? data.items : [...prev, ...data.items]))
  }, [data, offset])

  const hasMore = data ? entries.length < data.total : false
  // Who recorded each movement; the list is admin-only, so others see none.
  const users = useQuery({ queryKey: ['users-list'], queryFn: fetchUsers, enabled: open, retry: false, staleTime: 5 * 60_000 })
  const userNames = React.useMemo(() => new Map((users.data ?? []).map((u) => [u.id, u.full_name])), [users.data])

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-full sm:max-w-lg overflow-y-auto">
        <SheetHeader>
          <SheetTitle>{materialName}</SheetTitle>
          <SheetDescription>Everything in and out, newest first. The right-hand number is the stock after each.</SheetDescription>
        </SheetHeader>

        <div className="flex flex-1 flex-col gap-4 px-4 pb-4 text-sm">
          {data && (
            <p className="text-sm">
              <span className={cn('text-2xl font-semibold tabular-nums', stockState === 'NEGATIVE_STOCK' && 'text-destructive', stockState === 'OUT_OF_STOCK' && 'text-draft')}>
                {qty(data.current_balance)}
              </span>{' '}
              <span className="text-muted-foreground">{data.unit} on site now</span>
              {stockState === 'NEGATIVE_STOCK' && <span className="block text-destructive">More used than received: a delivery or opening stock is probably missing.</span>}
            </p>
          )}

          {isLoading && entries.length === 0 && (
            <div className="flex flex-col gap-2">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-10 rounded-md" />
              ))}
            </div>
          )}

          {isError && (
            <div className="flex flex-col items-center gap-3 py-10 text-center">
              <TriangleAlert className="size-6 text-destructive" />
              <p className="text-muted-foreground">The history could not be loaded.</p>
              <Button size="sm" variant="outline" onClick={() => refetch()}>
                Try again
              </Button>
            </div>
          )}

          {entries.length > 0 && (
            <ul className="divide-y rounded-lg border">
              {entries.map((entry) => {
                const by = entry.created_by ? userNames.get(entry.created_by) : undefined
                return (
                  <li key={entry.id} className="flex items-center gap-3 px-3 py-2">
                    <div className="flex min-w-0 flex-1 flex-col">
                      <span className="truncate">
                        {REASON_WORDS[entry.movement_reason as keyof typeof REASON_WORDS] ?? entry.movement_reason}
                        {entry.reverses_movement_id && <span className="text-draft"> · correction</span>}
                      </span>
                      <span className="truncate text-xs text-muted-foreground">
                        {[shortDay(entry.occurred_date), entry.occurred_time && entry.occurred_time !== '00:00:00' ? entry.occurred_time.slice(0, 5) : null, by, entry.source === 'whatsapp' ? 'WhatsApp' : null, entry.notes]
                          .filter(Boolean)
                          .join(' · ')}
                      </span>
                    </div>
                    <span className={cn('w-16 text-right font-semibold tabular-nums', entry.direction === 'IN' ? 'text-success' : '')}>
                      {entry.direction === 'IN' ? '+' : '−'}
                      {qty(entry.quantity)}
                    </span>
                    <span className="w-16 text-right tabular-nums text-muted-foreground">{qty(entry.running_balance)}</span>
                  </li>
                )
              })}
            </ul>
          )}

          {!isLoading && !isError && entries.length === 0 && <p className="py-8 text-center text-muted-foreground">Nothing recorded for it here yet.</p>}

          {hasMore && (
            <Button size="sm" variant="outline" className="self-center" disabled={isFetching} onClick={() => setOffset((prev) => prev + PAGE_SIZE)}>
              {isFetching ? 'Loading…' : 'Show older'}
            </Button>
          )}
        </div>
      </SheetContent>
    </Sheet>
  )
}
