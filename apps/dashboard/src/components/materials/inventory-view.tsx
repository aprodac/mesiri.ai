import * as React from 'react'
import { useQuery } from '@tanstack/react-query'
import { Boxes, ChevronRight, MapPin, TriangleAlert } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Callout, StatStrip } from '@/components/dpr-page'
import { fetchInventory, type MaterialStock } from '@/lib/materials'
import { useSiteNames } from '@/lib/site-names'
import { qty } from '@/lib/site-day'
import { cn, timeAgo } from '@/lib/utils'
import { MaterialLedgerSheet } from './material-ledger-sheet'

// WEB-29: stock grouped by site -- what each site holds now -- instead of
// one flat table repeating every material per site. Site names come from
// the scope's cached lists, so "All projects" no longer shows site ids.
// The bulk "Deactivate materials" (it switched catalogue entries off for the
// whole company from here) is gone; the Catalogue does that.

interface InventoryViewProps {
  projectId: string | null
  siteId: string | null
}

export function InventoryView({ projectId, siteId }: InventoryViewProps) {
  const siteNames = useSiteNames()
  const [selected, setSelected] = React.useState<MaterialStock | null>(null)
  const filters = { project_id: projectId ?? undefined, site_id: siteId ?? undefined }
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['materials', 'inventory', filters],
    queryFn: () => fetchInventory(filters),
  })
  const rows = React.useMemo(() => data ?? [], [data])

  const groups = React.useMemo(() => {
    const bySite = new Map<string, MaterialStock[]>()
    for (const r of rows) bySite.set(r.site_id ?? '', [...(bySite.get(r.site_id ?? '') ?? []), r])
    return [...bySite.entries()]
      .map(([sid, list]) => ({
        sid,
        name: siteNames.get(sid)?.name ?? 'Site',
        project: siteNames.get(sid)?.project ?? '',
        list: list.sort((a, b) => a.material_name.localeCompare(b.material_name)),
      }))
      .sort((a, b) => (a.project + a.name).localeCompare(b.project + b.name))
  }, [rows, siteNames])

  const below = rows.filter((r) => r.stock_state === 'NEGATIVE_STOCK')
  const out = rows.filter((r) => r.stock_state === 'OUT_OF_STOCK')

  if (isError) {
    return (
      <Callout
        tone="draft"
        icon={TriangleAlert}
        action={
          <Button variant="outline" size="sm" className="bg-background" onClick={() => refetch()}>
            Try again
          </Button>
        }
      >
        The stock could not be loaded.
      </Callout>
    )
  }
  if (isLoading) {
    return (
      <div className="flex flex-col gap-2">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-24 rounded-lg" />
        ))}
      </div>
    )
  }
  if (rows.length === 0) {
    return (
      <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed py-12 text-center">
        <Boxes className="size-6 text-muted-foreground" aria-hidden="true" />
        <p className="text-sm font-medium">No stock yet</p>
        <p className="max-w-sm text-sm text-muted-foreground">Record a delivery, or send "received 50 bags cement" on WhatsApp.</p>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4">
      <StatStrip
        stats={[
          { label: 'Materials', value: new Set(rows.map((r) => r.material_id)).size },
          { label: 'Sites', value: groups.length },
          { label: 'Run out', value: out.length || '—', tone: out.length ? 'warn' : 'default' },
          { label: 'Over-used', value: below.length || '—', tone: below.length ? 'bad' : 'default' },
        ]}
      />
      {below.length > 0 && (
        <Callout tone="draft" icon={TriangleAlert}>
          <strong className="font-semibold">
            {below.length === 1 ? `${below[0].material_name} at ${siteNames.get(below[0].site_id)?.name ?? 'a site'}` : `${below.length} materials`} used more than
            received.
          </strong>
          <span className="hidden sm:inline"> A delivery or opening stock is probably missing.</span>
        </Callout>
      )}

      {groups.map((g) => (
        <section key={g.sid} className="flex flex-col gap-1.5">
          <h3 className="flex items-baseline gap-2 text-sm">
            <MapPin className="size-3.5 self-center text-muted-foreground" aria-hidden="true" />
            <span className="font-semibold">{g.name}</span>
            {!siteId && g.project && <span className="text-muted-foreground">{g.project}</span>}
          </h3>
          <ul className="divide-y rounded-lg border">
            {g.list.map((r) => {
              const bad = r.stock_state === 'NEGATIVE_STOCK'
              const empty = r.stock_state === 'OUT_OF_STOCK'
              return (
                <li key={r.material_id}>
                  <button
                    type="button"
                    onClick={() => setSelected(r)}
                    className="flex w-full items-center gap-3 px-3 py-2 text-left hover:bg-muted/40"
                  >
                    <span className="min-w-0 flex-1 truncate font-medium">{r.material_name}</span>
                    <span className="hidden text-xs text-muted-foreground tabular-nums sm:inline">
                      +{qty(r.total_received)} in · −{qty(r.total_used)} used
                      {r.last_movement_at ? ` · ${timeAgo(r.last_movement_at)}` : ''}
                    </span>
                    <span
                      className={cn(
                        'w-28 text-right tabular-nums',
                        bad ? 'font-semibold text-destructive' : empty ? 'font-semibold text-draft' : 'font-semibold',
                      )}
                    >
                      {qty(r.current_stock)} <span className="font-normal text-muted-foreground">{r.unit}</span>
                    </span>
                    <ChevronRight className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                  </button>
                </li>
              )
            })}
          </ul>
        </section>
      ))}

      {selected && (
        <MaterialLedgerSheet
          siteId={selected.site_id}
          materialId={selected.material_id}
          materialName={selected.material_name}
          siteName={siteNames.get(selected.site_id)?.name}
          stockState={selected.stock_state}
          open={selected !== null}
          onOpenChange={(open) => !open && setSelected(null)}
        />
      )}
    </div>
  )
}
