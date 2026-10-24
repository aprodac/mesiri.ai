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
import { Button } from '@/components/ui/button'
import { useAuth } from '@/lib/AuthContext'
import { Callout } from '@/components/dpr-page'
import { fetchInflow, fetchOutflow, formatMoney, REASON_WORDS, type MaterialReceipt, type MaterialUsage } from '@/lib/materials'
import { fetchUsers } from '@/lib/api'
import { useSiteNames } from '@/lib/site-names'
import { longDate, qty } from '@/lib/site-day'
import { cn } from '@/lib/utils'
import { MaterialLedgerSheet } from './material-ledger-sheet'
import { CorrectionDialog } from './correction-dialog'

// One movement in plain words (WEB-29): what, where, when, who -- names, not ids.

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
  const siteNames = useSiteNames()
  const site = movement?.site_id ? siteNames.get(movement.site_id) : undefined
  const users = useQuery({ queryKey: ['users-list'], queryFn: fetchUsers, enabled: open, retry: false, staleTime: 5 * 60_000 })
  const recorder = movement?.created_by ? users.data?.find((u) => u.id === movement.created_by)?.full_name : undefined
  const canOpenLedger = !!movement?.material_id && !!movement?.site_id

  const copyId = () => {
    if (id) navigator.clipboard.writeText(id)
  }

  return (
    <>
      <Sheet open={open} onOpenChange={onOpenChange}>
        <SheetContent className="w-full sm:max-w-md overflow-y-auto">
          <SheetHeader>
            <SheetTitle>{direction === 'IN' ? 'Received' : 'Left the site'}</SheetTitle>
            <SheetDescription>One entry in the stock book.</SheetDescription>
          </SheetHeader>

          <div className="flex-1 px-4 pb-4 text-sm">
            {isLoading && (
              <div className="flex items-center justify-center py-10 gap-2 text-muted-foreground">
                <Loader2 className="size-4 animate-spin" />
                Loading…
              </div>
            )}

            {isError && (
              <div className="flex flex-col items-center gap-3 py-10 text-center">
                <AlertTriangle className="size-6 text-destructive" />
                <p className="text-muted-foreground">This entry could not be loaded.</p>
                <Button size="sm" variant="outline" onClick={() => refetch()}>
                  Try again
                </Button>
              </div>
            )}

            {movement && (
              <div className="flex flex-col gap-4">
                <p className={cn('text-lg', movement.reverses_movement_id && 'text-muted-foreground')}>
                  <strong className="font-semibold tabular-nums">
                    {direction === 'IN' ? '+' : '−'}
                    {qty(movement.quantity)} {movement.unit}
                  </strong>{' '}
                  {movement.material_name}
                </p>
                <dl className="grid grid-cols-[96px_1fr] gap-x-3 gap-y-1.5 text-sm">
                  <dt className="text-muted-foreground">What</dt>
                  <dd>{REASON_WORDS[movement.movement_reason] ?? movement.movement_reason}</dd>
                  <dt className="text-muted-foreground">Site</dt>
                  <dd>{site ? `${site.name} · ${site.project}` : '—'}</dd>
                  <dt className="text-muted-foreground">Day</dt>
                  <dd>
                    {longDate(movement.occurred_date)}
                    {movement.occurred_time && movement.occurred_time !== '00:00:00' ? `, ${movement.occurred_time.slice(0, 5)}` : ''}
                  </dd>
                  {direction === 'IN' ? (
                    <>
                      <dt className="text-muted-foreground">Supplier</dt>
                      <dd>{(movement as MaterialReceipt).supplier || <span className="text-muted-foreground">Not named</span>}</dd>
                      <dt className="text-muted-foreground">Cost</dt>
                      <dd className={cn(!(movement as MaterialReceipt).total_cost && 'text-muted-foreground')}>
                        {formatMoney((movement as MaterialReceipt).total_cost)}
                      </dd>
                    </>
                  ) : (
                    <>
                      <dt className="text-muted-foreground">For</dt>
                      <dd>{(movement as MaterialUsage).work_item || <span className="text-muted-foreground">Not said</span>}</dd>
                    </>
                  )}
                  <dt className="text-muted-foreground">Recorded</dt>
                  <dd>
                    {[recorder, movement.source === 'whatsapp' ? 'on WhatsApp' : 'on the dashboard', new Date(movement.created_at).toLocaleString([], { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' })]
                      .filter(Boolean)
                      .join(' · ')}
                  </dd>
                  {movement.notes && (
                    <>
                      <dt className="text-muted-foreground">Note</dt>
                      <dd className="whitespace-pre-line">{movement.notes}</dd>
                    </>
                  )}
                </dl>

                {movement.reverses_movement_id && (
                  <Callout tone="draft" icon={Undo2}>
                    This is a correction: it cancels an earlier entry.
                  </Callout>
                )}
              </div>
            )}
          </div>

          {movement && (
            <SheetFooter className="flex-row flex-wrap gap-2 border-t pt-3">
              {canOpenLedger && (
                <Button size="sm" variant="outline" className="gap-1.5" onClick={() => setLedgerOpen(true)}>
                  <History className="size-3.5" /> Stock history
                </Button>
              )}
              {/* Hidden once a correction exists, rather than shown disabled:
                  a second correction does not undo twice, it posts a second
                  offsetting movement and doubles the adjustment. The backend
                  409s either way -- this stops the user reaching for it. */}
              {movement.already_reversed ? (
                <span className="inline-flex items-center gap-1.5 text-sm text-muted-foreground">
                  <CheckCircle2 className="size-3.5 text-success" /> Already corrected
                </span>
              ) : (
                canCorrect && (
                  <Button size="sm" variant="outline" className="gap-1.5" onClick={() => setCorrectionOpen(true)}>
                    <Undo2 className="size-3.5" /> Correct
                  </Button>
                )
              )}
              <Button size="sm" variant="ghost" className="ml-auto gap-1.5 text-muted-foreground" onClick={copyId} title="For support">
                <Copy className="size-3.5" /> Copy reference
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
          originalSummary={`${movement.material_name} · ${qty(movement.quantity)} ${movement.unit} · ${REASON_WORDS[movement.movement_reason] ?? movement.movement_reason}`}
          open={correctionOpen}
          onOpenChange={setCorrectionOpen}
        />
      )}
    </>
  )
}
