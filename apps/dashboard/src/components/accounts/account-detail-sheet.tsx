import * as React from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowDownLeft, ArrowUpRight, Download, Pencil } from 'lucide-react'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { CHIP } from '@/lib/site-day'
import { cn } from '@/lib/utils'
import { exportCsv } from '@/lib/export'
import { fetchAccountTransactionsApi } from '@/lib/api'

// WEB-66: one money account: its balance, its bank details (bank, IFSC, last 4 digits), who holds it, where it is,
// and its money in and out with a statement to download. The old panel showed a made-up "Created 2026-07-01", a
// fixed ₹50,000 low line, and opened every transaction as an expense.

export interface AccountSheetData {
  id: string
  name: string
  account_type: string
  current_balance: number
  currency: string
  holder?: string | null
  where?: string | null
  bank_name?: string | null
  ifsc_code?: string | null
  account_last4?: string | null
  status: string
}

interface AccountDetailSheetProps {
  account: AccountSheetData | null
  open: boolean
  onOpenChange: (open: boolean) => void
  onEdit?: () => void
}

const TYPE_LABEL: Record<string, string> = {
  bank: 'Bank account',
  cash: 'Petty cash',
  employee_advance: 'Cash advance',
  other: 'Other',
}
const TX_LABEL: Record<string, string> = {
  expense_payment: 'Expense paid',
  transfer: 'Transfer',
  fund_received: 'Money in',
  reversal: 'Reversed',
}
const rupees = (n: number) => `₹${Math.round(n).toLocaleString('en-IN')}`

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-2">
      <span className="text-muted-foreground">{label}</span>
      <span className="min-w-0 text-right font-medium">{children}</span>
    </div>
  )
}

export function AccountDetailSheet({ account, open, onOpenChange, onEdit }: AccountDetailSheetProps) {
  const navigate = useNavigate()
  const tx = useQuery({
    queryKey: ['finance', 'account-transactions', account?.id],
    queryFn: () => fetchAccountTransactionsApi(account!.id),
    enabled: open && !!account?.id,
  })
  if (!account) return null
  const rows: any[] = Array.isArray(tx.data) ? tx.data : []
  const isBank = account.account_type === 'bank'

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="flex w-full flex-col gap-0 overflow-hidden p-0 sm:max-w-md">
        <SheetHeader className="border-b p-4 text-left">
          <SheetTitle className="flex flex-wrap items-center gap-2 text-base font-semibold">
            {account.name}
            {account.status === 'inactive' && <span className={cn(CHIP, 'bg-muted text-muted-foreground')}>Closed</span>}
          </SheetTitle>
          <SheetDescription className={cn('text-2xl font-semibold tabular-nums text-foreground', account.current_balance < 0 && 'text-destructive')}>
            {rupees(account.current_balance)}
          </SheetDescription>
        </SheetHeader>

        <div className="flex flex-1 flex-col gap-5 overflow-y-auto p-4 text-sm">
          <section>
            <div className="flex items-center justify-between gap-2 pb-1">
              <h3 className="font-semibold">{TYPE_LABEL[account.account_type] ?? 'Account'}</h3>
              {onEdit && (
                <Button size="sm" variant="outline" className="gap-1.5" onClick={onEdit}>
                  <Pencil className="size-3.5" /> Edit
                </Button>
              )}
            </div>
            <div className="divide-y border-t">
              {isBank && <Row label="Bank">{account.bank_name || '—'}</Row>}
              {isBank && <Row label="IFSC">{account.ifsc_code || '—'}</Row>}
              {isBank && <Row label="Account number">{account.account_last4 ? `•••• ${account.account_last4}` : '—'}</Row>}
              <Row label={isBank ? 'Looked after by' : 'Held by'}>{account.holder || 'Nobody'}</Row>
              {account.where && <Row label="Where">{account.where}</Row>}
            </div>
          </section>

          <section className="flex flex-col gap-2">
            <div className="flex items-center justify-between gap-2">
              <h3 className="font-semibold">Money in and out</h3>
              {rows.length > 0 && (
                <Button
                  size="sm"
                  variant="ghost"
                  className="gap-1.5"
                  onClick={() =>
                    exportCsv(
                      `${account.name} statement.csv`,
                      ['Date', 'Kind', 'In', 'Out', 'Note'],
                      rows.map((t) => {
                        const inbound = String(t.to_account_id) === account.id
                        return [String(t.occurred_date ?? '').slice(0, 10), TX_LABEL[t.transaction_type] ?? t.transaction_type, inbound ? t.amount : '', inbound ? '' : t.amount, t.description ?? '']
                      }),
                    )
                  }
                >
                  <Download className="size-3.5" /> Statement
                </Button>
              )}
            </div>
            {tx.isLoading ? (
              <Skeleton className="h-24 rounded-lg" />
            ) : tx.isError ? (
              <p className="text-muted-foreground">
                The money in and out could not be loaded.{' '}
                <button type="button" className="underline" onClick={() => tx.refetch()}>
                  Try again
                </button>
              </p>
            ) : rows.length === 0 ? (
              <p className="rounded-lg border border-dashed p-4 text-center text-muted-foreground">Nothing in or out yet.</p>
            ) : (
              <ul className="divide-y rounded-lg border">
                {rows.map((t) => {
                  const inbound = String(t.to_account_id) === account.id
                  const expense = t.transaction_type === 'expense_payment' && t.source_id
                  const body = (
                    <>
                      <span className={cn('flex size-7 shrink-0 items-center justify-center rounded-full', inbound ? 'bg-success-soft text-success' : 'bg-muted text-muted-foreground')}>
                        {inbound ? <ArrowDownLeft className="size-3.5" /> : <ArrowUpRight className="size-3.5" />}
                      </span>
                      <span className="flex min-w-0 flex-1 flex-col">
                        <span className="truncate font-medium">{t.description || TX_LABEL[t.transaction_type] || t.transaction_type}</span>
                        <span className="text-xs text-muted-foreground">
                          {[TX_LABEL[t.transaction_type], t.occurred_date].filter(Boolean).join(' · ')}
                        </span>
                      </span>
                      <span className={cn('shrink-0 font-semibold tabular-nums', inbound && 'text-success')}>
                        {inbound ? '+' : '−'}
                        {rupees(Number(t.amount) || 0)}
                      </span>
                    </>
                  )
                  return (
                    <li key={t.id}>
                      {expense ? (
                        <button
                          type="button"
                          className="flex w-full items-center gap-2.5 px-3 py-2 text-left hover:bg-muted/30"
                          onClick={() => {
                            onOpenChange(false)
                            navigate(`/finance/expenses?id=${t.source_id}&period=all`)
                          }}
                        >
                          {body}
                        </button>
                      ) : (
                        <div className="flex items-center gap-2.5 px-3 py-2">{body}</div>
                      )}
                    </li>
                  )
                })}
              </ul>
            )}
          </section>
        </div>
      </SheetContent>
    </Sheet>
  )
}
