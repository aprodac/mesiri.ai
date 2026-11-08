import * as React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CircleCheck, Landmark, Undo2, Wallet } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { fetchAccountsApi } from '@/lib/api'
import { apiErrorMessage } from '@/lib/logo-upload'
import { fetchExpensePayments, payExpense, rupees, undoExpensePayment } from '@/lib/expenses'
import { cn } from '@/lib/utils'
import { applyAdvance } from '@/lib/vendors'

// PRC-35: an expense's payments, and paying what is left (or repaying who paid it from their pocket) from one of the
// company's accounts -- in full or in part, on a date -- with undo for a payment made by mistake. Only shown to the
// owner, admins and finance (the API refuses the rest).

const today = () => new Date().toISOString().slice(0, 10)

export function ExpensePayments({ expenseId, owedTo, canPay, startOpen }: { expenseId: string; owedTo?: string | null; canPay: boolean; startOpen?: boolean }) {
  const queryClient = useQueryClient()
  const data = useQuery({ queryKey: ['finance', 'expense-payments', expenseId], queryFn: () => fetchExpensePayments(expenseId) })
  const accounts = useQuery({ queryKey: ['finance', 'accounts', 'payable'], queryFn: () => fetchAccountsApi(), enabled: canPay, staleTime: 30_000 })
  const active = ((accounts.data ?? []) as any[]).filter((a) => a.status !== 'inactive' && !String(a.name).startsWith('TDS payable')) // eslint-disable-line @typescript-eslint/no-explicit-any
  const [paying, setPaying] = React.useState(!!startOpen)
  const [account, setAccount] = React.useState('')
  const [amount, setAmount] = React.useState('')
  const [date, setDate] = React.useState(today())
  const left = Number(data.data?.left ?? 0)
  React.useEffect(() => {
    if (!account && active.length === 1) setAccount(String(active[0].id))
  }, [active, account])
  const refresh = (next: unknown) => {
    queryClient.setQueryData(['finance', 'expense-payments', expenseId], next)
    queryClient.invalidateQueries({ queryKey: ['finance'] })
  }
  const pay = useMutation({
    mutationFn: () => payExpense(expenseId, { account_id: account, amount: amount || undefined, paid_date: date }),
    onSuccess: (next) => {
      refresh(next)
      setPaying(false)
      setAmount('')
    },
  })
  const undo = useMutation({ mutationFn: (paymentId: string) => undoExpensePayment(expenseId, paymentId), onSuccess: refresh })
  // CC-10: the supplier holds an advance of ours: use it on this bill first (no money moves), oldest advance first.
  const offer = data.data?.vendor_advance
  const useAdvance = useMutation({
    mutationFn: async () => {
      for (const a of offer?.advances ?? []) {
        await applyAdvance(offer!.vendor_id, a.id, [expenseId])
        const now = await fetchExpensePayments(expenseId)
        if (Number(now.left) <= 0) return now
      }
      return fetchExpensePayments(expenseId)
    },
    onSuccess: refresh,
  })
  const payments = data.data?.payments ?? []
  const verb = owedTo ? `Repay ${owedTo.split(' ')[0]}` : 'Mark paid'

  return (
    <section className="flex flex-col gap-2">
      <div className="flex items-center justify-between gap-2">
        <h3 className="flex items-center gap-2 font-semibold">
          <Wallet className="size-4 text-muted-foreground" aria-hidden="true" /> Payment
        </h3>
        {data.data && (
          <span className={cn('text-xs font-semibold tabular-nums', left > 0 ? 'text-draft' : 'text-success')}>
            {left > 0 ? `${rupees(left)} ${owedTo ? `owed to ${owedTo.split(' ')[0]}` : 'unpaid'}` : 'Paid in full'}
          </span>
        )}
      </div>
      {payments.length > 0 && (
        <ul className="divide-y rounded-lg border">
          {payments.map((p) => (
            <li key={p.id} className={cn('flex items-center gap-2 px-3 py-2 text-sm', p.status === 'reversed' && 'opacity-60')}>
              {p.account_type === 'bank' ? <Landmark className="size-4 shrink-0 text-sky-700" /> : <Wallet className="size-4 shrink-0 text-amber-700" />}
              <span className="min-w-0 flex-1">
                <span className={cn('block truncate font-medium', p.status === 'reversed' && 'line-through')}>{p.account_name}</span>
                <span className="block truncate text-xs text-muted-foreground">
                  {new Date(`${p.paid_date}T00:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })}
                  {p.recorded_by ? ` · ${p.recorded_by}` : ''}
                  {p.from_advance ? ' · from advance' : ''}
                  {p.status === 'reversed' ? ' · undone' : ''}
                </span>
              </span>
              <span className="font-semibold tabular-nums">{rupees(Number(p.amount))}</span>
              {canPay && p.status === 'confirmed' && (
                <Button size="icon" variant="ghost" className="size-8 text-muted-foreground" title="Undo this payment" aria-label="Undo this payment" disabled={undo.isPending} onClick={() => undo.mutate(p.id)}>
                  <Undo2 className="size-4" />
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
      {undo.isError && <p className="text-sm text-destructive">{apiErrorMessage(undo.error)}</p>}
      {canPay && left > 0 && offer && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-sky-200 bg-sky-50 px-3 py-2 text-sm dark:border-sky-900 dark:bg-sky-950/40">
          <span className="min-w-0 flex-1">{offer.vendor} holds {rupees(Number(offer.left))} of your advance.</span>
          <Button size="sm" variant="outline" className="bg-background" disabled={useAdvance.isPending} onClick={() => useAdvance.mutate()}>
            {useAdvance.isPending ? 'Using…' : `Use ${rupees(Math.min(Number(offer.left), left))} on this bill`}
          </Button>
          {useAdvance.isError && <p className="w-full text-destructive">{apiErrorMessage(useAdvance.error)}</p>}
        </div>
      )}
      {canPay && left > 0 && !paying && (
        <Button size="sm" className="gap-1.5 self-start font-semibold" onClick={() => setPaying(true)}>
          <CircleCheck className="size-4" /> {verb}
        </Button>
      )}
      {canPay && left > 0 && paying && (
        <form
          className="grid gap-2 rounded-lg border bg-muted/30 p-3"
          onSubmit={(e) => {
            e.preventDefault()
            if (account) pay.mutate()
          }}
        >
          {active.length === 0 ? (
            <p className="text-sm text-muted-foreground">Add a bank account or a site's petty cash in Finance › Money first.</p>
          ) : (
            <>
              <Select value={account} onValueChange={setAccount}>
                <SelectTrigger className="h-9 bg-background">
                  <SelectValue placeholder="Paid from which account" />
                </SelectTrigger>
                <SelectContent>
                  {active.map((a: any) => ( // eslint-disable-line @typescript-eslint/no-explicit-any
                    <SelectItem key={a.id} value={String(a.id)}>
                      {a.name} · {rupees(Number(a.current_balance) || 0)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <div className="grid grid-cols-2 gap-2">
                <Input type="number" min={0} step="any" inputMode="decimal" aria-label="Amount" placeholder={`${left} (all)`} value={amount} onChange={(e) => setAmount(e.target.value)} className="bg-background" />
                <Input type="date" aria-label="Paid on" value={date} max={today()} onChange={(e) => setDate(e.target.value)} className="bg-background dark:[color-scheme:dark]" />
              </div>
              {pay.isError && <p className="text-sm text-destructive">{apiErrorMessage(pay.error)}</p>}
              <div className="flex gap-2">
                <Button type="submit" size="sm" className="font-semibold" disabled={!account || pay.isPending}>
                  {pay.isPending ? 'Saving…' : amount && Number(amount) < left ? `Pay ${rupees(Number(amount))}` : `${verb} · ${rupees(left)}`}
                </Button>
                <Button type="button" size="sm" variant="outline" onClick={() => setPaying(false)}>
                  Cancel
                </Button>
              </div>
            </>
          )}
        </form>
      )}
    </section>
  )
}
