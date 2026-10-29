import * as React from 'react'
import { useQuery } from '@tanstack/react-query'
import { TriangleAlert } from 'lucide-react'
import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet'
import { SheetHero, SheetSection } from '@/components/detail-sheet'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { fetchLedger, REASON_WORDS, type LedgerEntry, type StockState } from '@/lib/materials'
import { fetchUsers } from '@/lib/api'
import { qty } from '@/lib/site-day'
import { cn } from '@/lib/utils'

// One material at one site, every movement with the stock after it
// (WEB-29: plain words, names instead of user ids, no code badges).
// WEB-36: the side-panel layout (detail-sheet.tsx): what is on site now in
// the head, then the book as In (green) / Out (red) / Stock columns.

const shortDay = (iso: string) => new Date(`${iso}T00:00:00`).toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short' })

const PAGE_SIZE = 25

interface MaterialLedgerSheetProps {
  siteId: string | null
  materialId: string
  materialName: string
  siteName?: string
  open: boolean
  onOpenChange: (open: boolean) => void
  stockState?: StockState
}

export function MaterialLedgerSheet({
  siteId,
  materialId,
  materialName,
  siteName,
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

  const negative = stockState === 'NEGATIVE_STOCK' || (data ? Number(data.current_balance) < 0 : false)

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-full gap-0 overflow-y-auto p-0 sm:max-w-lg">
        {data ? (
          <SheetHero
            tone={negative ? 'out' : stockState === 'OUT_OF_STOCK' ? 'warn' : 'neutral'}
            kicker="Stock book"
            lead={
              <span className={cn(negative && 'text-destructive')}>
                {qty(data.current_balance)} <span className="text-xl font-medium text-muted-foreground">{data.unit} on site</span>
              </span>
            }
            title={materialName}
          >
            {siteName && <span>{siteName}</span>}
            <span>
              {data.total} {data.total === 1 ? 'entry' : 'entries'}
            </span>
          </SheetHero>
        ) : (
          <div className="border-b px-5 pt-5 pb-4">
            <SheetTitle>{materialName}</SheetTitle>
          </div>
        )}

        {negative && (
          <p className="mx-5 mt-4 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
            More used than received: a delivery or opening stock is probably missing.
          </p>
        )}

        <SheetSection title="Newest first">
          {isLoading && entries.length === 0 && (
            <div className="flex flex-col gap-2">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-10 rounded-md" />
              ))}
            </div>
          )}

          {isError && (
            <div className="flex flex-col items-center gap-3 py-10 text-center text-sm">
              <TriangleAlert className="size-6 text-destructive" />
              <p className="text-muted-foreground">The history could not be loaded.</p>
              <Button size="sm" variant="outline" onClick={() => refetch()}>
                Try again
              </Button>
            </div>
          )}

          {entries.length > 0 && (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-xs text-muted-foreground">
                  <th className="py-1.5 pr-2 text-left font-medium">Entry</th>
                  <th className="w-16 py-1.5 text-right font-medium">In</th>
                  <th className="w-16 py-1.5 text-right font-medium">Out</th>
                  <th className="w-16 py-1.5 text-right font-medium">Stock</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {entries.map((entry) => {
                  const by = entry.created_by ? userNames.get(entry.created_by) : undefined
                  const isIn = entry.direction === 'IN'
                  return (
                    <tr key={entry.id} className="align-top">
                      <td className="py-2 pr-2">
                        <span className="block truncate font-medium">
                          {REASON_WORDS[entry.movement_reason as keyof typeof REASON_WORDS] ?? entry.movement_reason}
                          {entry.reverses_movement_id && <span className="font-normal text-draft"> · correction</span>}
                        </span>
                        <span className="block truncate text-xs text-muted-foreground">
                          {[shortDay(entry.occurred_date), entry.occurred_time && entry.occurred_time !== '00:00:00' ? entry.occurred_time.slice(0, 5) : null, by, entry.source === 'whatsapp' ? 'WhatsApp' : null, entry.notes]
                            .filter(Boolean)
                            .join(' · ')}
                        </span>
                      </td>
                      <td className="py-2 text-right font-semibold tabular-nums text-success">{isIn ? `+${qty(entry.quantity)}` : ''}</td>
                      <td className="py-2 text-right font-semibold tabular-nums text-destructive">{isIn ? '' : `−${qty(entry.quantity)}`}</td>
                      <td className={cn('py-2 text-right tabular-nums', Number(entry.running_balance) < 0 ? 'text-destructive' : 'text-muted-foreground')}>
                        {qty(entry.running_balance)}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}

          {!isLoading && !isError && entries.length === 0 && <p className="py-8 text-center text-sm text-muted-foreground">Nothing recorded for it here yet.</p>}

          {hasMore && (
            <Button size="sm" variant="outline" className="self-center" disabled={isFetching} onClick={() => setOffset((prev) => prev + PAGE_SIZE)}>
              {isFetching ? 'Loading…' : 'Show older'}
            </Button>
          )}
        </SheetSection>
      </SheetContent>
    </Sheet>
  )
}
