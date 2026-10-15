import * as React from 'react'
import { useQuery } from '@tanstack/react-query'
import { Loader2, AlertTriangle, Copy, History, Undo2, CheckCircle2 } from 'lucide-react'
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
  SheetFooter,
} from '@/components/ui/sheet'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useAuth } from '@/lib/AuthContext'
import { fetchInflow, fetchOutflow, type MaterialReceipt, type MaterialUsage } from '@/lib/materials'
import { MaterialLedgerSheet } from './material-ledger-sheet'
import { CorrectionDialog } from './correction-dialog'

interface MovementDetailsSheetProps {
  direction: 'IN' | 'OUT'
  id: string | null
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function MovementDetailsSheet({ direction, id, open, onOpenChange }: MovementDetailsSheetProps) {
  const { me } = useAuth()
  const [ledgerOpen, setLedgerOpen] = React.useState(false)
  const [correctionOpen, setCorrectionOpen] = React.useState(false)

  const {
    data: movement,
    isLoading,
    isError,
    refetch,
  } = useQuery<MaterialReceipt | MaterialUsage>({
    queryKey: ['materials', direction === 'IN' ? 'inflow' : 'outflow', id],
    queryFn: () => (direction === 'IN' ? fetchInflow(id!) : fetchOutflow(id!)),
    enabled: !!id && open,
  })

  const canCorrect = me?.role === 'ADMIN' || me?.role === 'PROJECT_MANAGER'
  const canOpenLedger = !!movement?.material_id && !!movement?.site_id

  const copyId = () => {
    if (id) navigator.clipboard.writeText(id)
  }

  return (
    <>
      <Sheet open={open} onOpenChange={onOpenChange}>
        <SheetContent className="w-full sm:max-w-md overflow-y-auto">
          <SheetHeader>
            <SheetTitle>{direction === 'IN' ? 'Material Inflow' : 'Material Outflow'}</SheetTitle>
            <SheetDescription>Movement details and audit trail.</SheetDescription>
          </SheetHeader>

          <div className="px-4 pb-4 flex-1 text-xs">
            {isLoading && (
              <div className="flex items-center justify-center py-10 gap-2 text-muted-foreground">
                <Loader2 className="size-4 animate-spin text-primary" />
                Loading movement...
              </div>
            )}

            {isError && (
              <div className="flex flex-col items-center gap-3 py-10 text-center">
                <AlertTriangle className="size-6 text-rose-500" />
                <p className="text-muted-foreground">Failed to load this movement.</p>
                <Button size="sm" variant="outline" onClick={() => refetch()}>
                  Retry
                </Button>
              </div>
            )}

            {movement && (
              <div className="space-y-4">
                <div className="space-y-1">
                  <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">
                    Material
                  </span>
                  <div className="text-sm font-bold text-foreground">{movement.material_name}</div>
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <Field label="Direction">
                    <Badge variant={direction === 'IN' ? 'default' : 'secondary'} className="text-[10px]">
                      {direction === 'IN' ? 'Inflow' : 'Outflow'}
                    </Badge>
                  </Field>
                  <Field label="Reason">
                    <Badge variant="outline" className="text-[10px]">
                      {movement.movement_reason}
                    </Badge>
                  </Field>
                  <Field label="Quantity">
                    <span className="font-mono tabular-nums font-semibold">
                      {movement.quantity} {movement.unit}
                    </span>
                  </Field>
                  <Field label="Source">
                    <Badge variant="outline" className="text-[10px]">
                      {movement.source}
                    </Badge>
                  </Field>
                  <Field label="Occurred At">
                    <span>
                      {movement.occurred_date}
                      {movement.occurred_time ? ` ${movement.occurred_time}` : ''}
                    </span>
                  </Field>
                  <Field label="Recorded By">
                    <span className="font-mono text-[10px] break-all">{movement.created_by ?? '—'}</span>
                  </Field>
                  {direction === 'IN' ? (
                    <Field label="Supplier">
                      <span>{(movement as MaterialReceipt).supplier ?? '—'}</span>
                    </Field>
                  ) : (
                    <Field label="Work Item">
                      <span>{(movement as MaterialUsage).work_item ?? '—'}</span>
                    </Field>
                  )}
                  <Field label="Created">
                    <span>{new Date(movement.created_at).toLocaleString()}</span>
                  </Field>
                </div>

                {movement.notes && (
                  <div className="space-y-1">
                    <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">
                      Notes
                    </span>
                    <p className="text-foreground leading-relaxed">{movement.notes}</p>
                  </div>
                )}

                {movement.reverses_movement_id && (
                  <div className="bg-amber-500/10 border border-amber-500/20 text-amber-700 dark:text-amber-400 p-2.5 rounded flex items-center gap-2">
                    <Undo2 className="size-3.5 shrink-0" />
                    <span>Corrects movement {movement.reverses_movement_id}</span>
                  </div>
                )}

                <div className="space-y-1 pt-2 border-t">
                  <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">
                    Movement ID
                  </span>
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-[10px] break-all text-muted-foreground">{movement.id}</span>
                  </div>
                </div>
              </div>
            )}
          </div>

          {movement && (
            <SheetFooter className="border-t pt-3 flex-row flex-wrap gap-2">
              {canOpenLedger && (
                <Button
                  size="sm"
                  variant="outline"
                  className="h-8 gap-1.5 text-xs"
                  onClick={() => setLedgerOpen(true)}
                >
                  <History className="size-3.5" />
                  Open Ledger
                </Button>
              )}
              {/* Hidden once a correction exists, rather than shown disabled:
                  a second correction does not undo twice, it posts a second
                  offsetting movement and doubles the adjustment. The backend
                  409s either way -- this stops the user reaching for it. */}
              {movement.already_reversed ? (
                <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-muted-foreground">
                  <CheckCircle2 className="size-3.5 text-emerald-600 dark:text-emerald-400" />
                  Already corrected
                </span>
              ) : (
                canCorrect && (
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-8 gap-1.5 text-xs"
                    onClick={() => setCorrectionOpen(true)}
                  >
                    <Undo2 className="size-3.5" />
                    Correct Movement
                  </Button>
                )
              )}
              <Button size="sm" variant="outline" className="h-8 gap-1.5 text-xs" onClick={copyId}>
                <Copy className="size-3.5" />
                Copy Movement ID
              </Button>
            </SheetFooter>
          )}
        </SheetContent>
      </Sheet>

      {movement && movement.material_id && movement.site_id && (
        <MaterialLedgerSheet
          siteId={movement.site_id}
          materialId={movement.material_id}
          materialName={movement.material_name}
          open={ledgerOpen}
          onOpenChange={setLedgerOpen}
        />
      )}

      {movement && id && (
        <CorrectionDialog
          direction={direction}
          movementId={id}
          transferId={movement.transfer_id}
          originalSummary={`${movement.material_name} · ${movement.quantity} ${movement.unit} · ${movement.movement_reason}`}
          open={correctionOpen}
          onOpenChange={setCorrectionOpen}
        />
      )}
    </>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold block">
        {label}
      </span>
      <div className="text-foreground font-medium">{children}</div>
    </div>
  )
}
