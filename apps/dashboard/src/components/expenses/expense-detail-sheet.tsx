import * as React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FileText, ImagePlus, Receipt, TriangleAlert } from 'lucide-react'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { CHIP } from '@/lib/site-day'
import { cn } from '@/lib/utils'
import { BILL_ACCEPT, billFile } from '@/lib/bill-upload'
import { apiErrorMessage } from '@/lib/logo-upload'
import { addExpenseBillApi, fetchExpenseAttachmentsApi } from '@/lib/api'
import { ExpensePayments } from './expense-payments'

// WEB-65 (Ilan, 5 Nov: "make sure sent expense bill and all is there saved for an expense if image is there"): one
// expense, with every bill on it (WhatsApp photos, a delivery's invoice, ones added here) and "Add bill" for a photo
// or a PDF. The old panel showed one photo and filled empty fields with made-up names ("Main Bank Account",
// "Finance Custodian", "General Operations"); only what the expense really has is shown.

export interface ExpenseDetailData {
  id: string
  number?: string | null
  amount: number
  category_name?: string
  category_id?: string
  vendor_name?: string | null
  project_name?: string | null
  site_name?: string | null
  date: string
  payment_label: string
  payment_class: string
  source: 'whatsapp' | 'web'
  reversed: boolean
  description?: string | null
  /** PRC-18: "Petty cash · Villa box", "Owed to Ravi", "Unpaid". */
  paid_line?: string
  recorded_by?: string | null
  /** PRC-35: paid from its owner's pocket: "Repay Ravi". */
  owed_to?: string | null
}

interface ExpenseDetailSheetProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  expense: ExpenseDetailData | null
  readOnly?: boolean
  onOpenVendor?: () => void
  onOpenCategory?: (categoryId: string) => void
  /** PRC-35: the owner, an admin or finance may pay it. */
  canPay?: boolean
  /** Open the payment form at once ("Mark paid" from the list's menu). */
  payNow?: boolean
}

const rupees = (n: number) => `₹${Math.round(n).toLocaleString('en-IN')}`
const isPdf = (url: string) => /\.pdf(\?|$)/i.test(url.split('#')[0])
const day = (iso: string) =>
  new Date(`${iso}T00:00:00`).toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' })

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-2">
      <span className="text-muted-foreground">{label}</span>
      <span className="min-w-0 text-right font-medium">{children}</span>
    </div>
  )
}

export function ExpenseDetailSheet({ open, onOpenChange, expense, readOnly, onOpenVendor, onOpenCategory, canPay, payNow }: ExpenseDetailSheetProps) {
  const queryClient = useQueryClient()
  const input = React.useRef<HTMLInputElement>(null)
  const id = expense?.id
  const bills = useQuery({
    queryKey: ['finance', 'expense-bills', id],
    queryFn: () => fetchExpenseAttachmentsApi(id!),
    enabled: open && !!id,
  })
  const add = useMutation({
    mutationFn: async (file: File) => addExpenseBillApi(id!, await billFile(file)),
    onSuccess: (rows) => {
      queryClient.setQueryData(['finance', 'expense-bills', id], rows)
      queryClient.invalidateQueries({ queryKey: ['finance', 'expense-photos'] })
    },
  })
  React.useEffect(() => add.reset(), [id]) // eslint-disable-line react-hooks/exhaustive-deps
  if (!expense) return null
  const canAdd = !readOnly && !expense.reversed

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="flex w-full flex-col gap-0 overflow-hidden p-0 sm:max-w-md">
        <SheetHeader className="border-b p-4 text-left">
          <SheetTitle className="flex flex-wrap items-center gap-2 text-2xl font-semibold tabular-nums">
            {rupees(expense.amount)}
            {expense.reversed ? (
              <span className={cn(CHIP, 'bg-muted text-muted-foreground')}>Taken back</span>
            ) : (
              <span className={cn(CHIP, expense.payment_class)}>{expense.payment_label}</span>
            )}
          </SheetTitle>
          <SheetDescription>
            {[expense.vendor_name || expense.category_name, day(expense.date), expense.number].filter(Boolean).join(' · ')}
          </SheetDescription>
        </SheetHeader>

        <div className="flex flex-1 flex-col gap-5 overflow-y-auto p-4 text-sm">
          <section className="flex flex-col gap-2">
            <div className="flex items-center justify-between gap-2">
              <h3 className="flex items-center gap-2 font-semibold">
                <Receipt className="size-4 text-muted-foreground" aria-hidden="true" /> Bill
              </h3>
              {canAdd && (
                <>
                  <input
                    ref={input}
                    type="file"
                    accept={BILL_ACCEPT}
                    className="hidden"
                    onChange={(e) => {
                      const file = e.target.files?.[0]
                      e.target.value = ''
                      if (file) add.mutate(file)
                    }}
                  />
                  <Button size="sm" variant="outline" className="gap-1.5" disabled={add.isPending} onClick={() => input.current?.click()}>
                    <ImagePlus className="size-3.5" /> {add.isPending ? 'Adding…' : 'Add bill'}
                  </Button>
                </>
              )}
            </div>
            {add.isError && (
              <p className="flex items-center gap-1.5 text-destructive">
                <TriangleAlert className="size-3.5 shrink-0" /> {apiErrorMessage(add.error)}
              </p>
            )}
            {bills.isLoading ? (
              <Skeleton className="h-40 rounded-lg" />
            ) : bills.isError ? (
              <p className="text-muted-foreground">
                The bill could not be loaded.{' '}
                <button type="button" className="underline" onClick={() => bills.refetch()}>
                  Try again
                </button>
              </p>
            ) : (bills.data ?? []).length === 0 ? (
              <p className="rounded-lg border border-dashed p-4 text-center text-muted-foreground">
                No bill yet.{canAdd ? ' Add a photo or a PDF, or send the photo on WhatsApp.' : ''}
              </p>
            ) : (
              <ul className="grid grid-cols-2 gap-2">
                {bills.data!.map((b, i) => (
                  <li key={b.id}>
                    <a
                      href={b.url}
                      target="_blank"
                      rel="noreferrer"
                      className="flex h-40 items-center justify-center overflow-hidden rounded-lg border bg-muted/40 hover:border-foreground/30"
                      aria-label={`Open bill ${i + 1}`}
                    >
                      {isPdf(b.url) ? (
                        <span className="flex flex-col items-center gap-1 text-muted-foreground">
                          <FileText className="size-8" aria-hidden="true" /> PDF
                        </span>
                      ) : (
                        <img src={b.url} alt={`Bill ${i + 1}`} className="h-full w-full object-cover object-top" loading="lazy" />
                      )}
                    </a>
                  </li>
                ))}
              </ul>
            )}
          </section>

          {!expense.reversed && <ExpensePayments key={`${expense.id}:${payNow ? 1 : 0}`} expenseId={expense.id} owedTo={expense.owed_to} canPay={!!canPay && !readOnly} startOpen={payNow} />}

          <section className="divide-y border-t">
            <Row label="Category">
              {expense.category_id && onOpenCategory ? (
                <button type="button" className="underline-offset-2 hover:underline" onClick={() => onOpenCategory(expense.category_id!)}>
                  {expense.category_name}
                </button>
              ) : (
                expense.category_name || '—'
              )}
            </Row>
            <Row label="Vendor">
              {expense.vendor_name ? (
                onOpenVendor ? (
                  <button type="button" className="underline-offset-2 hover:underline" onClick={onOpenVendor}>
                    {expense.vendor_name}
                  </button>
                ) : (
                  expense.vendor_name
                )
              ) : (
                '—'
              )}
            </Row>
            <Row label="Where">{[expense.project_name, expense.site_name].filter(Boolean).join(' · ') || '—'}</Row>
            {expense.paid_line && <Row label="Paid">{expense.paid_line}</Row>}
            <Row label="From">
              {expense.source === 'whatsapp' ? 'WhatsApp' : 'Dashboard'}
              {expense.recorded_by && <span className="font-normal text-muted-foreground"> · {expense.recorded_by}</span>}
            </Row>
            {expense.description && <Row label="Note">{expense.description}</Row>}
          </section>
        </div>
      </SheetContent>
    </Sheet>
  )
}
