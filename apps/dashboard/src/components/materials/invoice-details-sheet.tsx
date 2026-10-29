import * as React from 'react'
import { useQuery } from '@tanstack/react-query'
import { Loader2, AlertTriangle, FileText, ExternalLink, Receipt } from 'lucide-react'
import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet'
import { Fact, Facts, SheetHero, SheetSection } from '@/components/detail-sheet'
import { Button } from '@/components/ui/button'
import { Callout } from '@/components/dpr-page'
import { useSiteNames } from '@/lib/site-names'
import { longDate, qty } from '@/lib/site-day'
import {
  fetchInvoice,
  fetchInvoiceAttachment,
  formatMoney,
  type MaterialInvoice,
} from '@/lib/materials'

interface InvoiceDetailsSheetProps {
  invoiceId: string | null
  open: boolean
  onOpenChange: (open: boolean) => void
}

/**
 * One supplier document: who supplied it, every material on it, what it cost,
 * the Finance expense it created, and the original image or PDF.
 *
 * The document is the point. When a delivery is disputed weeks later, the
 * answer is the piece of paper the supplier sent, not our retyping of it.
 *
 * WEB-35: restyled like the other Materials panels -- supplier and number
 * first, plain labels, a light table with a total row, no internal id.
 * WEB-36: the side-panel layout (detail-sheet.tsx), total in the head.
 */
export function InvoiceDetailsSheet({ invoiceId, open, onOpenChange }: InvoiceDetailsSheetProps) {
  const siteNames = useSiteNames()
  const {
    data: invoice,
    isLoading,
    isError,
    refetch,
  } = useQuery<MaterialInvoice>({
    queryKey: ['materials', 'invoice', invoiceId],
    queryFn: () => fetchInvoice(invoiceId!),
    enabled: !!invoiceId && open,
  })

  // Fetched separately and lazily: the link is short-lived, so there is no
  // point minting one until the sheet is actually open and a document exists.
  const {
    data: attachment,
    isLoading: attachmentLoading,
    isError: attachmentError,
  } = useQuery({
    queryKey: ['materials', 'invoice-attachment', invoiceId],
    queryFn: () => fetchInvoiceAttachment(invoiceId!),
    enabled: !!invoiceId && open && !!invoice?.has_attachment,
    retry: false,
  })

  const linesTotal = React.useMemo(() => {
    if (!invoice) return null
    const sum = invoice.lines.reduce((acc, l) => acc + (Number(l.total_cost) || 0), 0)
    return sum > 0 ? sum : null
  }, [invoice])

  const site = invoice?.site_id ? siteNames.get(invoice.site_id) : undefined
  const supplier = invoice?.vendor_name ?? invoice?.supplier_name

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-full gap-0 overflow-y-auto p-0 sm:max-w-lg">
        {!invoice && <SheetTitle className="sr-only">Supplier invoice</SheetTitle>}
        <div className="flex-1 text-sm">
          {isLoading && (
            <div className="flex items-center justify-center gap-2 py-16 text-muted-foreground">
              <Loader2 className="size-4 animate-spin" />
              Loading…
            </div>
          )}

          {isError && (
            <div className="flex flex-col items-center gap-3 py-10 text-center">
              <AlertTriangle className="size-6 text-destructive" />
              <p className="text-muted-foreground">This invoice could not be loaded.</p>
              <Button size="sm" variant="outline" onClick={() => refetch()}>
                Try again
              </Button>
            </div>
          )}

          {invoice && (
            <div className="flex flex-col">
              <SheetHero
                kicker="Supplier invoice"
                lead={formatMoney(invoice.invoice_total)}
                title={supplier ?? 'Supplier not named'}
              >
                {invoice.invoice_number && <span>No. {invoice.invoice_number}</span>}
                {invoice.invoice_date && <span>{longDate(invoice.invoice_date)}</span>}
                {site && <span>{site.name}</span>}
              </SheetHero>

              <SheetSection title="Details">
                <Facts>
                  <Fact label="Site">{site ? `${site.name} · ${site.project}` : null}</Fact>
                  {invoice.vendor_name && invoice.supplier_name && invoice.vendor_name !== invoice.supplier_name && (
                    // The document's own words are kept even when a vendor
                    // record matched, so a later rename can't rewrite history.
                    <Fact label="On the paper">{invoice.supplier_name}</Fact>
                  )}
                  <Fact label="Recorded">{new Date(invoice.created_at).toLocaleString([], { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' })}</Fact>
                  {invoice.notes && (
                    <Fact label="Note">
                      <span className="whitespace-pre-line">{invoice.notes}</span>
                    </Fact>
                  )}
                </Facts>
              </SheetSection>

              <SheetSection title={`Materials · ${invoice.lines.length}`} className="border-t">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b text-left text-xs text-muted-foreground">
                      <th className="py-1.5 pr-2 font-medium">Material</th>
                      <th className="py-1.5 pr-2 text-right font-medium">Qty</th>
                      <th className="hidden py-1.5 pr-2 text-right font-medium sm:table-cell">Rate</th>
                      <th className="py-1.5 text-right font-medium">Amount</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y">
                    {invoice.lines.map((line) => (
                      <tr key={line.id}>
                        <td className="py-2 pr-2 font-medium">{line.material_name}</td>
                        <td className="py-2 pr-2 text-right tabular-nums text-emerald-700 dark:text-emerald-400">
                          +{qty(line.quantity)} <span className="text-muted-foreground">{line.unit}</span>
                        </td>
                        <td className="hidden py-2 pr-2 text-right tabular-nums text-muted-foreground sm:table-cell">{formatMoney(line.unit_cost)}</td>
                        <td className="py-2 text-right tabular-nums">{formatMoney(line.total_cost)}</td>
                      </tr>
                    ))}
                  </tbody>
                  {linesTotal !== null && (
                    <tfoot>
                      <tr className="border-t font-semibold">
                        <td className="py-2" colSpan={2}>
                          Lines add up to
                        </td>
                        <td className="hidden sm:table-cell" />
                        <td className="py-2 text-right tabular-nums">{formatMoney(String(linesTotal))}</td>
                      </tr>
                    </tfoot>
                  )}
                </table>
                {/* Tax and freight are deliberately not extracted, so the
                    printed total is normally higher than the lines add up to.
                    Stated plainly rather than flagged as a discrepancy — the
                    gap is expected on almost every real invoice. */}
                {linesTotal !== null && invoice.invoice_total && Math.abs(Number(invoice.invoice_total) - linesTotal) > 0.5 && (
                  <p className="text-xs text-muted-foreground">The invoice total is higher by tax and delivery, which aren't split out.</p>
                )}
              </SheetSection>

              {invoice.expense_id && (
                <div className="px-5 pb-2">
                  <Callout tone="success" icon={Receipt}>
                    <strong className="font-semibold">In Finance as an unpaid bill.</strong> Nobody needs to enter it again.
                  </Callout>
                </div>
              )}

              <SheetSection title="Original" className="border-t">
                {!invoice.has_attachment ? (
                  <p className="text-muted-foreground">No photo or PDF was attached.</p>
                ) : attachmentLoading ? (
                  <p className="text-muted-foreground">Getting the link…</p>
                ) : attachment ? (
                  <Button asChild size="sm" variant="outline" className="w-fit gap-1.5">
                    <a href={attachment.url} target="_blank" rel="noreferrer">
                      <FileText className="size-3.5" />
                      Open the original
                      <ExternalLink className="size-3" />
                    </a>
                  </Button>
                ) : (
                  // The reference is stored and correct; only the storage
                  // provider is unreachable. Say that, rather than implying the
                  // document was lost.
                  <p className="flex items-center gap-2 text-muted-foreground">
                    <FileText className="size-3.5" />
                    {attachmentError ? 'Attached, but it cannot be opened right now.' : 'Attached.'}
                  </p>
                )}
              </SheetSection>
            </div>
          )}
        </div>
      </SheetContent>
    </Sheet>
  )
}
