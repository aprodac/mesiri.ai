import * as React from 'react'
import { useQuery } from '@tanstack/react-query'
import { ChevronRight, MessageSquare, PackageMinus, PackagePlus, Search, TriangleAlert } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Callout } from '@/components/dpr-page'
import {
  fetchInflows,
  fetchOutflows,
  formatMoney,
  INFLOW_REASONS,
  OUTFLOW_REASONS,
  REASON_WORDS,
  type MaterialReceipt,
  type MaterialUsage,
} from '@/lib/materials'
import { useSiteNames } from '@/lib/site-names'
import { CHIP, longDate, qty } from '@/lib/site-day'
import { useUrlState } from '@/lib/url-state'
import { cn } from '@/lib/utils'
import { MovementDetailsSheet } from './movement-details-sheet'

// WEB-29: deliveries (IN) and use (OUT) as one list by day -- "40 bags
// Cement · Tower 1 · Ultratech dealer" -- instead of two near-identical
// tables with checkboxes, site ids and reason codes. Corrections happen one
// at a time in the details sheet; the bulk "reverse" (it posted a fixed
// note for every row) is gone.

const DEFAULT_REASON = { IN: 'RECEIVED', OUT: 'CONSUMED' } as const

export function MovementsView({ direction, projectId, siteId }: { direction: 'IN' | 'OUT'; projectId: string | null; siteId: string | null }) {
  const siteNames = useSiteNames()
  const [search, setSearch] = useUrlState<string>('q', '')
  const [reason, setReason] = useUrlState<string>('reason', 'ALL')
  const [openId, setOpenId] = React.useState<string | null>(null)

  const filters = {
    project_id: projectId ?? undefined,
    site_id: siteId ?? undefined,
    material_name: search.trim() || undefined,
    movement_reason: reason === 'ALL' ? undefined : reason,
    limit: 100,
  }
  const query = useQuery<{ items: (MaterialReceipt | MaterialUsage)[]; total: number }>({
    queryKey: ['materials', direction === 'IN' ? 'inflows' : 'outflows', filters],
    queryFn: () => (direction === 'IN' ? fetchInflows(filters) : fetchOutflows(filters)),
  })
  const items = React.useMemo(() => query.data?.items ?? [], [query.data])
  const days = React.useMemo(() => {
    const byDay = new Map<string, (MaterialReceipt | MaterialUsage)[]>()
    for (const m of items) byDay.set(m.occurred_date, [...(byDay.get(m.occurred_date) ?? []), m])
    return [...byDay.entries()].sort(([a], [b]) => b.localeCompare(a))
  }, [items])
  const reasons = direction === 'IN' ? INFLOW_REASONS : OUTFLOW_REASONS
  const Icon = direction === 'IN' ? PackagePlus : PackageMinus

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative w-full sm:w-64">
          <Search className="absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
          <Input placeholder="Search material…" aria-label="Search material" value={search} onChange={(e) => setSearch(e.target.value)} className="h-9 pl-8" />
        </div>
        <Select value={reason} onValueChange={setReason}>
          <SelectTrigger className="h-9 w-[190px]" aria-label="Kind">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="ALL">{direction === 'IN' ? 'Everything received' : 'Everything that left'}</SelectItem>
            {reasons.map((r) => (
              <SelectItem key={r.value} value={r.value}>
                {REASON_WORDS[r.value]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {query.data && (
          <span className="ml-auto text-sm text-muted-foreground">
            {query.data.total > items.length ? `Newest ${items.length} of ${query.data.total}` : `${query.data.total} recorded`}
          </span>
        )}
      </div>

      {query.isError ? (
        <Callout
          tone="draft"
          icon={TriangleAlert}
          action={
            <Button variant="outline" size="sm" className="bg-background" onClick={() => query.refetch()}>
              Try again
            </Button>
          }
        >
          {direction === 'IN' ? 'Deliveries' : 'Material use'} could not be loaded.
        </Callout>
      ) : query.isLoading ? (
        <div className="flex flex-col gap-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-12 rounded-lg" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed py-12 text-center">
          <Icon className="size-6 text-muted-foreground" aria-hidden="true" />
          <p className="text-sm font-medium">
            {search || reason !== 'ALL' ? 'Nothing matches' : direction === 'IN' ? 'No deliveries recorded yet' : 'No material use recorded yet'}
          </p>
        </div>
      ) : (
        days.map(([day, list]) => (
          <section key={day} className="flex flex-col gap-1.5">
            <h3 className="text-sm font-semibold">{longDate(day)}</h3>
            <ul className="divide-y rounded-lg border">
              {list.map((m) => {
                const site = m.site_id ? siteNames.get(m.site_id) : undefined
                const detail = 'supplier' in m ? m.supplier : 'work_item' in m ? m.work_item : null
                const correction = Boolean(m.reverses_movement_id)
                const cost = 'total_cost' in m && m.total_cost ? formatMoney(m.total_cost) : null
                return (
                  <li key={m.id}>
                    <button type="button" onClick={() => setOpenId(m.id)} className="flex w-full items-center gap-3 px-3 py-2 text-left hover:bg-muted/40">
                      <div className="flex min-w-0 flex-1 flex-col">
                        <span className={cn('truncate', correction && 'text-muted-foreground line-through decoration-muted-foreground/40')}>
                          <strong className="font-semibold tabular-nums">
                            {qty(m.quantity)} {m.unit}
                          </strong>{' '}
                          {m.material_name}
                        </span>
                        <span className="truncate text-xs text-muted-foreground">
                          {[!siteId && site?.name, !projectId && site?.project, detail].filter(Boolean).join(' · ') || '—'}
                        </span>
                      </div>
                      {m.movement_reason !== DEFAULT_REASON[direction] && (
                        <span className={cn(CHIP, 'hidden bg-muted text-muted-foreground sm:inline-flex')}>{REASON_WORDS[m.movement_reason]}</span>
                      )}
                      {correction && <span className={cn(CHIP, 'bg-draft-soft text-draft')}>Correction</span>}
                      {m.source === 'whatsapp' && <MessageSquare className="size-3.5 shrink-0 text-muted-foreground" aria-label="From WhatsApp" />}
                      {cost && <span className="hidden w-24 text-right text-sm tabular-nums sm:inline">{cost}</span>}
                      <ChevronRight className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                    </button>
                  </li>
                )
              })}
            </ul>
          </section>
        ))
      )}

      <MovementDetailsSheet direction={direction} id={openId} open={openId !== null} onOpenChange={(open) => !open && setOpenId(null)} />
    </div>
  )
}
