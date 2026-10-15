import * as React from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, ArrowRight, CheckCircle2, RotateCcw, Undo2 } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Skeleton } from '@/components/ui/skeleton'
import { useAuth } from '@/lib/AuthContext'
import { fetchTransfers, type MaterialTransfer } from '@/lib/materials'
import { CorrectionDialog } from './correction-dialog'

interface TransfersViewProps {
  projectId: string | null
  siteId: string | null
}

// Transfers leaving or entering the scope, one row per transfer (both halves
// together). Corrected as a whole: both sites go back at once.
export function TransfersView({ projectId, siteId }: TransfersViewProps) {
  const { me } = useAuth()
  const canCorrect = me?.role === 'ADMIN' || me?.role === 'PROJECT_MANAGER'
  const [correcting, setCorrecting] = React.useState<MaterialTransfer | null>(null)

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['materials', 'transfers', projectId],
    queryFn: () => fetchTransfers({ project_id: projectId ?? undefined, limit: 100 }),
  })

  // The endpoint scopes by project; a site scope narrows to transfers that
  // touch that site.
  const items = (data?.items ?? []).filter(
    (t) => !siteId || t.from_site_id === siteId || t.to_site_id === siteId
  )

  return (
    <div className="flex flex-col gap-3">
      <Card className="border-border/60 shadow-xs">
        <CardContent className="p-0">
          {isError ? (
            <div className="flex flex-col items-center gap-3 py-12 text-center text-xs">
              <AlertTriangle className="size-6 text-rose-500" />
              <p className="text-muted-foreground">Failed to load transfers.</p>
              <Button size="sm" variant="outline" onClick={() => refetch()} className="gap-1.5">
                <RotateCcw className="size-3.5" />
                Retry
              </Button>
            </div>
          ) : isLoading ? (
            <div className="p-3 space-y-2">
              {Array.from({ length: 4 }).map((_, i) => (
                <Skeleton key={i} className="h-8 w-full" />
              ))}
            </div>
          ) : items.length === 0 ? (
            <div className="flex flex-col items-center gap-1.5 py-12 text-center text-xs">
              <p className="text-muted-foreground">No transfers between sites in this scope.</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Material</TableHead>
                    <TableHead className="text-right">Quantity</TableHead>
                    <TableHead>From → To</TableHead>
                    <TableHead>Date</TableHead>
                    <TableHead>Notes</TableHead>
                    <TableHead className="text-right">Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {items.map((row) => (
                    <TableRow key={row.id} className="text-xs">
                      <TableCell className="font-semibold text-foreground">{row.material_name}</TableCell>
                      <TableCell className="text-right font-mono tabular-nums">
                        {row.quantity} {row.unit}
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        <span className="inline-flex items-center gap-1.5">
                          {row.from_site_name ?? row.from_site_id.slice(0, 8)}
                          <ArrowRight className="size-3" />
                          {row.to_site_name ?? row.to_site_id.slice(0, 8)}
                        </span>
                      </TableCell>
                      <TableCell className="text-muted-foreground">{row.occurred_date}</TableCell>
                      <TableCell className="text-muted-foreground max-w-[220px] truncate">
                        {row.notes ?? '—'}
                      </TableCell>
                      <TableCell className="text-right">
                        {row.is_reversed ? (
                          <Badge variant="outline" className="text-[10px] gap-1">
                            <CheckCircle2 className="size-3 text-emerald-600 dark:text-emerald-400" />
                            Corrected
                          </Badge>
                        ) : canCorrect ? (
                          <Button
                            size="sm"
                            variant="outline"
                            className="h-7 gap-1.5 text-xs"
                            onClick={() => setCorrecting(row)}
                          >
                            <Undo2 className="size-3.5" />
                            Correct
                          </Button>
                        ) : (
                          <Badge variant="outline" className="text-[10px]">
                            Recorded
                          </Badge>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {correcting && (
        <CorrectionDialog
          direction="OUT"
          movementId={correcting.outflow_id}
          transferId={correcting.id}
          originalSummary={`${correcting.material_name} · ${correcting.quantity} ${correcting.unit} · ${
            correcting.from_site_name ?? 'site'
          } → ${correcting.to_site_name ?? 'site'}`}
          open={!!correcting}
          onOpenChange={(open) => {
            if (!open) setCorrecting(null)
          }}
        />
      )}
    </div>
  )
}
