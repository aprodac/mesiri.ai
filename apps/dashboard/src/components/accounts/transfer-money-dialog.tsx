import * as React from 'react'
import { ArrowLeftRight, DollarSign, Calendar, FileText } from 'lucide-react'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

interface MoneyAccount {
  id: string
  name: string
  current_balance: number
  currency: string
}

interface TransferMoneyDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  accounts: MoneyAccount[]
  onTransferCompleted?: (fromId: string, toId: string, amount: number) => void
}

import { transferMoneyApi } from '@/lib/api'
import { toLocalISODate } from '@/lib/utils'
import { DatePicker } from '@/components/ui/date-picker'

export function TransferMoneyDialog({
  open,
  onOpenChange,
  accounts,
  onTransferCompleted,
}: TransferMoneyDialogProps) {
  const [fromAccountId, setFromAccountId] = React.useState('')
  const [toAccountId, setToAccountId] = React.useState('')
  const [amount, setAmount] = React.useState('')
  const [description, setDescription] = React.useState('')
  const [transferDate, setTransferDate] = React.useState(() => toLocalISODate())
  const [submitting, setSubmitting] = React.useState(false)

  const activeAccounts = React.useMemo(() => {
    return accounts || []
  }, [accounts])

  const selectedFromAccount = React.useMemo(() => {
    return activeAccounts.find((a) => a.id === fromAccountId)
  }, [activeAccounts, fromAccountId])

  const availableDestinations = React.useMemo(() => {
    return activeAccounts.filter((a) => a.id !== fromAccountId)
  }, [activeAccounts, fromAccountId])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    const transferVal = parseFloat(amount)
    if (!fromAccountId || !toAccountId || !transferVal || transferVal <= 0) return

    if (selectedFromAccount && transferVal > selectedFromAccount.current_balance) {
      alert('Transfer amount exceeds available source account balance.')
      return
    }

    setSubmitting(true)
    const idempotencyKey = `xfer-web-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`

    try {
      await transferMoneyApi(
        {
          from_account_id: fromAccountId,
          to_account_id: toAccountId,
          amount: transferVal,
          description: description || undefined,
          occurred_date: transferDate,
        },
        idempotencyKey
      )
      onTransferCompleted?.(fromAccountId, toAccountId, transferVal)
      onOpenChange(false)
      setFromAccountId('')
      setToAccountId('')
      setAmount('')
      setDescription('')
    } catch (err: any) {
      const detail = err?.response?.data?.detail
      const msg = Array.isArray(detail) ? detail.join(', ') : detail || err.message || 'Transfer failed'
      alert(`Transfer failed: ${msg}`)
    } finally {
      setSubmitting(false)
    }
  }

  const formatCurrency = (val: number) => {
    return new Intl.NumberFormat('en-IN', {
      style: 'currency',
      currency: 'INR',
      maximumFractionDigits: 0,
    }).format(val)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[500px] gap-4">
        <form onSubmit={handleSubmit}>
          <DialogHeader className="pb-2 border-b">
            <div className="flex items-center gap-2 text-cyan-600 dark:text-cyan-400">
              <div className="p-1.5 rounded-md bg-cyan-500/10 border border-cyan-500/20">
                <ArrowLeftRight className="size-4" />
              </div>
              <DialogTitle className="text-base font-bold">Transfer Money</DialogTitle>
            </div>
            <DialogDescription className="text-xs">
              Between bank and site cash.
            </DialogDescription>
          </DialogHeader>

          <div className="grid gap-3 py-4 text-xs">
            {/* From Account & To Account */}
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="from_acc" className="text-xs font-semibold">
                  From Account (Source) *
                </Label>
                <Select value={fromAccountId} onValueChange={setFromAccountId}>
                  <SelectTrigger id="from_acc" className="h-9 text-xs">
                    <SelectValue placeholder="Select Source" />
                  </SelectTrigger>
                  <SelectContent>
                    {activeAccounts.map((acc) => (
                      <SelectItem key={acc.id} value={acc.id} className="text-xs">
                        {acc.name} ({formatCurrency(acc.current_balance)})
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {selectedFromAccount && (
                  <span className="text-[10px] text-muted-foreground block">
                    Available: <strong className="text-emerald-600 font-mono">{formatCurrency(selectedFromAccount.current_balance)}</strong>
                  </span>
                )}
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="to_acc" className="text-xs font-semibold">
                  To Account (Destination) *
                </Label>
                <Select value={toAccountId} onValueChange={setToAccountId} disabled={!fromAccountId}>
                  <SelectTrigger id="to_acc" className="h-9 text-xs">
                    <SelectValue placeholder="Select Destination" />
                  </SelectTrigger>
                  <SelectContent>
                    {availableDestinations.map((acc) => (
                      <SelectItem key={acc.id} value={acc.id} className="text-xs">
                        {acc.name} ({formatCurrency(acc.current_balance)})
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            {/* Transfer Amount & Date */}
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="transfer_amount" className="text-xs font-semibold flex items-center gap-1">
                  <DollarSign className="size-3.5 text-muted-foreground" />
                  Transfer Amount (₹) *
                </Label>
                <Input
                  id="transfer_amount"
                  type="number"
                  step="0.01"
                  placeholder="0.00"
                  value={amount}
                  onChange={(e) => setAmount(e.target.value)}
                  className="font-mono font-semibold text-sm h-9"
                  required
                />
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="transfer_date" className="text-xs font-semibold flex items-center gap-1">
                  <Calendar className="size-3.5 text-muted-foreground" />
                  Transfer Date
                </Label>
                <DatePicker id="transfer_date" value={transferDate} onChange={(v) => setTransferDate(v)} className="h-9 text-xs" />
              </div>
            </div>

            {/* Description / Remarks */}
            <div className="space-y-1.5">
              <Label htmlFor="desc" className="text-xs font-semibold flex items-center gap-1">
                <FileText className="size-3.5 text-muted-foreground" />
                Remarks / Reference #
              </Label>
              <Input
                id="desc"
                placeholder="e.g. Monthly site petty cash replenishment"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                className="h-9 text-xs"
              />
            </div>
          </div>

          <DialogFooter className="pt-2 border-t">
            <Button type="button" variant="outline" size="sm" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button
              type="submit"
              size="sm"
              disabled={submitting || !fromAccountId || !toAccountId || !amount}
              className="bg-cyan-600 hover:bg-cyan-700 text-white gap-1.5 font-semibold"
            >
              <ArrowLeftRight className="size-3.5" />
              {submitting ? 'Transferring...' : 'Execute Transfer'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
