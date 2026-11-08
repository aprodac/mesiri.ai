import * as React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useToast } from '@/components/ui/toast-notification'
import { fetchAccountsApi } from '@/lib/api'
import { formatRupees } from '@/lib/boq'
import { apiErrorMessage } from '@/lib/logo-upload'
import { fetchProjects } from '@/lib/projects'
import { recordClientReceipt, type OpenBill, type ReceiptKind } from '@/lib/receivables'
import { cn } from '@/lib/utils'

// NXT-03: money a client paid. Against a bill (the bill's amount left is offered), on account (settles their oldest
// bills first), or a mobilisation advance (never put on a bill: each bill recovers it). The API checks the rest.

interface Account { id: string; name: string; account_type: string; status?: string }

function todayIso(): string {
  const d = new Date()
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10)
}

const KINDS: { key: ReceiptKind; label: string; about: string }[] = [
  { key: 'bill', label: 'For a bill', about: 'Pays one RA bill.' },
  { key: 'on_account', label: 'On account', about: 'Settles their oldest open bills first.' },
  { key: 'advance', label: 'Advance', about: 'Mobilisation advance; each bill recovers it.' },
]

export function ReceiveMoneyDialog({ open, onOpenChange, bills, preselect }: {
  open: boolean
  onOpenChange: (open: boolean) => void
  bills: OpenBill[]
  preselect?: OpenBill | null
}) {
  const toast = useToast()
  const qc = useQueryClient()
  const accounts = useQuery({ queryKey: ['finance', 'accounts', 'payable'], queryFn: () => fetchAccountsApi(), enabled: open, staleTime: 30_000 })
  const projects = useQuery({ queryKey: ['scope-projects'], queryFn: fetchProjects, enabled: open })
  const active = ((accounts.data ?? []) as Account[]).filter((a) => a.status !== 'inactive' && !a.name.startsWith('TDS payable'))
  const [kind, setKind] = React.useState<ReceiptKind>('bill')
  const [billId, setBillId] = React.useState('')
  const [projectId, setProjectId] = React.useState('')
  const [amount, setAmount] = React.useState('')
  const [date, setDate] = React.useState(todayIso())
  const [account, setAccount] = React.useState('')
  const [reference, setReference] = React.useState('')

  React.useEffect(() => {
    if (!open) return
    const first = preselect ?? bills[0]
    setKind(bills.length ? 'bill' : 'on_account')
    setBillId(first?.id ?? '')
    setProjectId(first?.project_id ?? '')
    setAmount(first ? first.left : '')
    setDate(todayIso())
    setReference('')
  }, [open, preselect, bills])
  React.useEffect(() => {
    if (!account && active.length) setAccount(String((active.find((a) => a.account_type === 'bank') ?? active[0]).id))
  }, [active, account])

  const bill = bills.find((b) => b.id === billId)
  const save = useMutation({
    mutationFn: () =>
      recordClientReceipt({
        kind,
        ...(kind === 'bill' ? { ra_bill_id: billId } : { project_id: projectId }),
        amount,
        received_on: date,
        account_id: account,
        reference: reference.trim() || undefined,
      }),
    onSuccess: () => {
      toast.success('Money received recorded')
      qc.invalidateQueries({ queryKey: ['billing'] })
      onOpenChange(false)
    },
    onError: (err: unknown) => toast.error('Could not record it', apiErrorMessage(err)),
  })
  const tooMuch = kind === 'bill' && bill && Number(amount) > Number(bill.left)
  const ready = Number(amount) > 0 && !!account && (kind === 'bill' ? !!billId && !tooMuch : !!projectId)

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Money received from a client</DialogTitle>
          <DialogDescription>Record what came in and into which account.</DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <div className="grid grid-cols-3 gap-2" role="radiogroup" aria-label="What it is for">
            {KINDS.map((k) => (
              <button
                key={k.key}
                type="button"
                role="radio"
                aria-checked={kind === k.key}
                disabled={k.key === 'bill' && bills.length === 0}
                onClick={() => setKind(k.key)}
                className={cn('rounded-lg border p-2 text-left text-sm disabled:opacity-50', kind === k.key ? 'border-primary ring-1 ring-primary' : 'hover:bg-muted/60')}
              >
                <span className="block font-medium">{k.label}</span>
                <span className="block text-xs text-muted-foreground">{k.about}</span>
              </button>
            ))}
          </div>
          {kind === 'bill' ? (
            <div className="flex flex-col gap-1">
              <Label>Bill</Label>
              <Select
                value={billId}
                onValueChange={(v) => {
                  setBillId(v)
                  const b = bills.find((x) => x.id === v)
                  if (b) setAmount(b.left)
                }}
              >
                <SelectTrigger aria-label="Bill">
                  <SelectValue placeholder="Pick the bill" />
                </SelectTrigger>
                <SelectContent>
                  {bills.map((b) => (
                    <SelectItem key={b.id} value={b.id}>
                      {b.ref} · {b.project} · {formatRupees(b.left)} left
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          ) : (
            <div className="flex flex-col gap-1">
              <Label>Project</Label>
              <Select value={projectId} onValueChange={setProjectId}>
                <SelectTrigger aria-label="Project">
                  <SelectValue placeholder="Pick the project" />
                </SelectTrigger>
                <SelectContent>
                  {(projects.data ?? []).map((p) => (
                    <SelectItem key={p.id} value={p.id}>
                      {p.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
          <div className="grid grid-cols-2 gap-2">
            <div className="flex flex-col gap-1">
              <Label htmlFor="rcv-amount">Amount (₹)</Label>
              <Input id="rcv-amount" type="number" inputMode="decimal" min="0" value={amount} onChange={(e) => setAmount(e.target.value)} className="tabular-nums" />
            </div>
            <div className="flex flex-col gap-1">
              <Label htmlFor="rcv-date">Received on</Label>
              <Input id="rcv-date" type="date" value={date} max={todayIso()} onChange={(e) => setDate(e.target.value)} />
            </div>
          </div>
          {tooMuch && bill && (
            <p className="text-xs text-destructive">
              {bill.ref} has {formatRupees(bill.left)} left. Record that against it and the rest on account.
            </p>
          )}
          <div className="grid grid-cols-2 gap-2">
            <div className="flex flex-col gap-1">
              <Label>Into account</Label>
              <Select value={account} onValueChange={setAccount}>
                <SelectTrigger aria-label="Into account">
                  <SelectValue placeholder="Pick the account" />
                </SelectTrigger>
                <SelectContent>
                  {active.map((a) => (
                    <SelectItem key={a.id} value={String(a.id)}>
                      {a.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex flex-col gap-1">
              <Label htmlFor="rcv-ref">UTR / cheque no.</Label>
              <Input id="rcv-ref" value={reference} onChange={(e) => setReference(e.target.value)} placeholder="Optional" />
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={() => save.mutate()} disabled={!ready || save.isPending}>
            {save.isPending ? 'Saving…' : `Record ${Number(amount) > 0 ? formatRupees(amount) : ''}`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
