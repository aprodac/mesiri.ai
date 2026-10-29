import * as React from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Loader2, AlertTriangle, Copy, History, Undo2, CheckCircle2, FileText, MessageSquare, ArrowRight } from 'lucide-react'
import { Sheet, SheetContent, SheetFooter, SheetTitle } from '@/components/ui/sheet'
import { Button } from '@/components/ui/button'
import { useAuth } from '@/lib/AuthContext'
import { Callout } from '@/components/dpr-page'
import { ByLine, Fact, Facts, SheetHero, SheetSection } from '@/components/detail-sheet'
import { fetchInflow, fetchLedger, fetchOutflow, formatMoney, REASON_WORDS, type MaterialReceipt, type MaterialUsage } from '@/lib/materials'
import { fetchUsers } from '@/lib/api'
import { useSiteNames } from '@/lib/site-names'
import { longDate, qty } from '@/lib/site-day'
import { cn } from '@/lib/utils'
import { MaterialLedgerSheet } from './material-ledger-sheet'
import { InvoiceDetailsSheet } from './invoice-details-sheet'
import { CorrectionDialog } from './correction-dialog'

// One movement in plain words (WEB-29): what, where, when, who -- names, not ids.
// WEB-36: laid out like every side panel (detail-sheet.tsx): a tinted head
// with the quantity in green (in) or red (out), then what it did to the
// site's stock (before → after, and now), the details, and who sent it --
// with a link to their WhatsApp chat and, for a delivery from an invoice,
// to the invoice.

interface MovementDetailsSheetProps {
  direction: 'IN' | 'OUT'
  id: string | null
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function MovementDetailsSheet({ direction, id, open, onOpenChange }: MovementDetailsSheetProps) {
  const { me } = useAuth()
  const [ledgerOpen, setLedgerOpen] = React.useState(false)
  const [invoiceOpen, setInvoiceOpen] = React.useState(false)
  const [correctionOpen, setCorrectionOpen] = React.useState(false)
  const [copied, setCopied] = React.useState(false)

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
  const recorder = movement?.created_by ? users.data?.find((u) => u.id === movement.created_by) : undefined
  const canOpenLedger = !!movement?.material_id && !!movement?.site_id

  // The site's stock book for this material: where this entry left the
  // stock, and what is there now. Only looked up in the latest 100 entries.
  const ledger = useQuery({
    queryKey: ['materials', 'ledger', movement?.site_id, movement?.material_id, 'recent'],
    queryFn: () => fetchLedger(movement!.site_id!, movement!.material_id!, { limit: 100 }),
    enabled: open && canOpenLedger,
  })
  const entry = ledger.data?.items.find((e) => e.source_id === id)
  const after = entry ? Number(entry.running_balance) : null
  const before = after !== null && movement ? after + (direction === 'IN' ? -1 : 1) * Number(movement.quantity) : null

  const receipt = direction === 'IN' ? (movement as MaterialReceipt | undefined) : undefined
  const usage = direction === 'OUT' ? (movement as MaterialUsage | undefined) : undefined
  const reason = movement ? (REASON_WORDS[movement.movement_reason] ?? movement.movement_reason) : ''
  const when = movement
    ? `${longDate(movement.occurred_date)}${movement.occurred_time && movement.occurred_time !== '00:00:00' ? `, ${movement.occurred_time.slice(0, 5)}` : ''}`
    : ''
  const recordedAt = movement
    ? new Date(movement.created_at).toLocaleString([], { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' })
    : ''
  const chatNumber = movement?.source === 'whatsapp' && me?.role === 'ADMIN' ? recorder?.whatsapp_number?.replace(/\D/g, '') : undefined

  const copyId = () => {
    if (!id) return
    navigator.clipboard.writeText(id)
    setCopied(true)
    window.setTimeout(() => setCopied(false), 1500)
  }

  return (
    <>
      <Sheet open={open} onOpenChange={onOpenChange}>
        <SheetContent className="w-full gap-0 overflow-y-auto p-0 sm:max-w-md">
          {isLoading && (
            <>
              <SheetTitle className="sr-only">Loading</SheetTitle>
              <div className="flex items-center justify-center gap-2 py-16 text-muted-foreground">
                <Loader2 className="size-4 animate-spin" />
                Loading…
              </div>
            </>
          )}

          {isError && (
            <div className="flex flex-col items-center gap-3 px-5 py-16 text-center">
              <SheetTitle className="sr-only">Could not load</SheetTitle>
              <AlertTriangle className="size-6 text-destructive" />
              <p className="text-muted-foreground">This entry could not be loaded.</p>
              <Button size="sm" variant="outline" onClick={() => refetch()}>
                Try again
              </Button>
            </div>
          )}

          {movement && (
            <>
              <SheetHero
                tone={movement.reverses_movement_id ? 'warn' : direction === 'IN' ? 'in' : 'out'}
                kicker={movement.reverses_movement_id ? 'Correction' : reason}
                lead={
                  <span className={cn(direction === 'IN' ? 'text-success' : 'text-destructive', movement.reverses_movement_id && 'text-foreground')}>
                    {direction === 'IN' ? '+' : '−'}
                    {qty(movement.quantity)} <span className="text-xl font-medium text-muted-foreground">{movement.unit}</span>
                  </span>
                }
                title={movement.material_name}
              >
                <span>{site ? `${site.name} · ${site.project}` : 'Site not known'}</span>
                <span>{when}</span>
              </SheetHero>

              {movement.reverses_movement_id && (
                <div className="px-5 pt-4">
                  <Callout tone="draft" icon={Undo2}>
                    This cancels an earlier entry. It is not a real {direction === 'IN' ? 'delivery' : 'use'}.
                  </Callout>
                </div>
              )}

              {canOpenLedger && (
                <SheetSection title={`Stock at ${site?.name ?? 'the site'}`}>
                  {ledger.isLoading ? (
                    <div className="h-14 animate-pulse rounded-lg bg-muted" />
                  ) : ledger.data ? (
                    <div className="grid grid-cols-[1fr_auto_1fr_1fr] items-center gap-2 rounded-lg border px-3 py-2.5 text-center">
                      <StockFigure label="Before" value={before} unit={ledger.data.unit} />
                      <ArrowRight className="size-4 text-muted-foreground" aria-hidden="true" />
                      <StockFigure label="After this" value={after} unit={ledger.data.unit} strong />
                      <StockFigure label="Now" value={Number(ledger.data.current_balance)} unit={ledger.data.unit} divider />
                    </div>
                  ) : (
                    <p className="text-sm text-muted-foreground">The stock could not be loaded.</p>
                  )}
                </SheetSection>
              )}

              <SheetSection title="Details" className="border-t">
                <Facts>
                  <Fact label="What">{reason}</Fact>
                  {receipt && (
                    <>
                      <Fact label="Supplier" missing="Not named">
                        {receipt.supplier}
                      </Fact>
                      <Fact label="Cost" missing="Not recorded">
                        {receipt.total_cost && (
                          <>
                            <span className="font-medium tabular-nums">{formatMoney(receipt.total_cost)}</span>
                            {receipt.unit_cost && (
                              <span className="text-muted-foreground">
                                {' '}
                                · rate {formatMoney(receipt.unit_cost)}
                              </span>
                            )}
                          </>
                        )}
                      </Fact>
                      {receipt.invoice_id && (
                        <Fact label="Invoice">
                          <button type="button" className="inline-flex items-center gap-1 font-medium hover:underline" onClick={() => setInvoiceOpen(true)}>
                            <FileText className="size-3.5" /> Open the invoice
                          </button>
                        </Fact>
                      )}
                    </>
                  )}
                  {usage && (
                    <Fact label="For" missing="Not said">
                      {usage.work_item}
                    </Fact>
                  )}
                  {movement.notes && <Fact label="Note">{<span className="whitespace-pre-line">{movement.notes}</span>}</Fact>}
                </Facts>
              </SheetSection>

              <SheetSection title="Recorded by" className="border-t">
                <div className="flex items-center justify-between gap-3">
                  <ByLine name={recorder?.full_name} detail={`${movement.source === 'whatsapp' ? 'On WhatsApp' : 'On the dashboard'} · ${recordedAt}`} />
                  {chatNumber && (
                    <Button asChild size="sm" variant="outline" className="shrink-0 gap-1.5">
                      <Link to={`/whatsapp?with=${chatNumber}`}>
                        <MessageSquare className="size-3.5" /> Chat
                      </Link>
                    </Button>
                  )}
                </div>
              </SheetSection>
            </>
          )}

          {movement && (
            <SheetFooter className="flex-row flex-wrap items-center gap-2 border-t bg-background px-5 py-3">
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
              <Button size="icon" variant="ghost" className="ml-auto size-8 text-muted-foreground" onClick={copyId} title={copied ? 'Copied' : 'Copy reference (for support)'} aria-label="Copy reference">
                {copied ? <CheckCircle2 className="size-4 text-success" /> : <Copy className="size-4" />}
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
          siteName={site?.name}
          open={ledgerOpen}
          onOpenChange={setLedgerOpen}
        />
      )}

      {receipt?.invoice_id && <InvoiceDetailsSheet invoiceId={receipt.invoice_id} open={invoiceOpen} onOpenChange={setInvoiceOpen} />}

      {movement && id && (
        <CorrectionDialog
          direction={direction}
          movementId={id}
          transferId={movement.transfer_id}
          originalSummary={`${movement.material_name} · ${qty(movement.quantity)} ${movement.unit} · ${reason}`}
          open={correctionOpen}
          onOpenChange={setCorrectionOpen}
        />
      )}
    </>
  )
}

function StockFigure({ label, value, unit, strong, divider }: { label: string; value: number | null; unit: string; strong?: boolean; divider?: boolean }) {
  return (
    <div className={cn('flex flex-col', divider && 'border-l pl-2')}>
      <span className="text-[11px] text-muted-foreground">{label}</span>
      <span className={cn('tabular-nums', strong ? 'text-lg font-semibold' : 'text-lg', value !== null && value < 0 && 'text-destructive')}>
        {value === null ? '—' : qty(String(value))}
      </span>
      <span className="text-[11px] text-muted-foreground">{unit}</span>
    </div>
  )
}
