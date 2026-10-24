import * as React from 'react'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeftRight, ArrowRight, TriangleAlert, Undo2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Callout } from '@/components/dpr-page'
import { useAuth } from '@/lib/AuthContext'
import { fetchTransfers, type MaterialTransfer } from '@/lib/materials'
import { useSiteNames } from '@/lib/site-names'
import { CHIP, longDate, qty } from '@/lib/site-day'
import { cn } from '@/lib/utils'
import { CorrectionDialog } from './correction-dialog'

interface TransfersViewProps {
  projectId: string | null
  siteId: string | null
}

// Transfers leaving or entering the scope, one row per transfer (both halves
// together), by day (WEB-29). Corrected as a whole: both sites go back at once.
export function TransfersView({ projectId, siteId }: TransfersViewProps) {
  const { me } = useAuth()
  const siteNames = useSiteNames()
  const canCorrect = me?.role === 'ADMIN' || me?.role === 'PROJECT_MANAGER'
  const [correcting, setCorrecting] = React.useState<MaterialTransfer | null>(null)

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['materials', 'transfers', projectId],
    queryFn: () => fetchTransfers({ project_id: projectId ?? undefined, limit: 100 }),
  })

  // The endpoint scopes by project; a site scope narrows to transfers that
  // touch that site.
  const days = React.useMemo(() => {
    const byDay = new Map<string, MaterialTransfer[]>()
    for (const t of data?.items ?? []) {
      if (siteId && t.from_site_id !== siteId && t.to_site_id !== siteId) continue
      byDay.set(t.occurred_date, [...(byDay.get(t.occurred_date) ?? []), t])
    }
    return [...byDay.entries()].sort(([a], [b]) => b.localeCompare(a))
  }, [data, siteId])
  const site = (id: string, name: string | null | undefined) => name ?? siteNames.get(id)?.name ?? 'A site'

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
        Transfers could not be loaded.
      </Callout>
    )
  }
  if (isLoading) {
    return (
      <div className="flex flex-col gap-2">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-12 rounded-lg" />
        ))}
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-3">
      {days.length === 0 ? (
        <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed py-12 text-center">
          <ArrowLeftRight className="size-6 text-muted-foreground" aria-hidden="true" />
          <p className="text-sm font-medium">No material moved between sites yet</p>
          <p className="text-sm text-muted-foreground">Use Move to send stock from one site to another.</p>
        </div>
      ) : (
        days.map(([day, list]) => (
          <section key={day} className="flex flex-col gap-1.5">
            <h3 className="text-sm font-semibold">{longDate(day)}</h3>
            <ul className="divide-y rounded-lg border">
              {list.map((t) => (
                <li key={t.id} className="flex items-center gap-3 px-3 py-2">
                  <div className="flex min-w-0 flex-1 flex-col">
                    <span className={cn('truncate', t.is_reversed && 'text-muted-foreground line-through decoration-muted-foreground/40')}>
                      <strong className="font-semibold tabular-nums">
                        {qty(t.quantity)} {t.unit}
                      </strong>{' '}
                      {t.material_name}
                    </span>
                    <span className="inline-flex min-w-0 items-center gap-1 text-xs text-muted-foreground">
                      <span className="truncate">{site(t.from_site_id, t.from_site_name)}</span>
                      <ArrowRight className="size-3 shrink-0" aria-hidden="true" />
                      <span className="truncate">{site(t.to_site_id, t.to_site_name)}</span>
                      {t.notes && <span className="truncate">· {t.notes}</span>}
                    </span>
                  </div>
                  {t.is_reversed ? (
                    <span className={cn(CHIP, 'bg-muted text-muted-foreground')}>Corrected</span>
                  ) : (
                    canCorrect && (
                      <Button size="sm" variant="ghost" className="gap-1.5" onClick={() => setCorrecting(t)}>
                        <Undo2 className="size-3.5" /> Correct
                      </Button>
                    )
                  )}
                </li>
              ))}
            </ul>
          </section>
        ))
      )}

      {correcting && (
        <CorrectionDialog
          direction="OUT"
          movementId={correcting.outflow_id}
          transferId={correcting.id}
          originalSummary={`${correcting.material_name} · ${qty(correcting.quantity)} ${correcting.unit} · ${site(
            correcting.from_site_id,
            correcting.from_site_name,
          )} → ${site(correcting.to_site_id, correcting.to_site_name)}`}
          open={!!correcting}
          onOpenChange={(open) => {
            if (!open) setCorrecting(null)
          }}
        />
      )}
    </div>
  )
}
