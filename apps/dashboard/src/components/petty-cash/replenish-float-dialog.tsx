import * as React from 'react'
import { ArrowLeftRight, DollarSign, Calendar, FileText, Landmark, Wallet } from 'lucide-react'
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

export interface BankAccountItem {
  id: string
  name: string
  current_balance: number
}

interface ReplenishFloatDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  cashBoxes: any[]
  bankAccounts?: BankAccountItem[]
  onReplenishCompleted?: (boxId: string, amount: number) => void
}

// WEB-51: no default banks. The old default was two made-up accounts ("HDFC Corporate Main Account", ₹34.5 L) shown
// whenever the caller passed none; the money can only come from the company's real accounts.
const NO_BANKS: BankAccountItem[] = []

import { replenishFloatApi } from '@/lib/api'
import { toLocalISODate } from '@/lib/utils'

export function ReplenishFloatDialog({
  open,
  onOpenChange,
  cashBoxes,
  bankAccounts = NO_BANKS,
  onReplenishCompleted,
}: ReplenishFloatDialogProps) {
  const [sourceBankId, setSourceBankId] = React.useState('')
  React.useEffect(() => {
    if (!sourceBankId && bankAccounts.length > 0) setSourceBankId(bankAccounts[0].id)
  }, [bankAccounts, sourceBankId])
  const [targetBoxId, setTargetBoxId] = React.useState('')
  const [amount, setAmount] = React.useState('')
  const [description, setDescription] = React.useState('')
  const [transferDate, setTransferDate] = React.useState(() => toLocalISODate())
  const [submitting, setSubmitting] = React.useState(false)

  const selectedBank = React.useMemo(() => {
    return bankAccounts.find((b) => b.id === sourceBankId)
  }, [bankAccounts, sourceBankId])

  const selectedBox = React.useMemo(() => {
    return cashBoxes.find((b) => b.id === targetBoxId)
  }, [cashBoxes, targetBoxId])

  const formatCurrency = (val: number) => {
    return new Intl.NumberFormat('en-IN', {
      style: 'currency',
      currency: 'INR',
      maximumFractionDigits: 0,
    }).format(val)
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    const val = parseFloat(amount)
    if (!sourceBankId || !targetBoxId || !val || val <= 0) return

    if (selectedBank && val > selectedBank.current_balance) {
      alert('Replenishment amount exceeds available bank balance.')
      return
    }

    setSubmitting(true)

    try {
      await replenishFloatApi({
        cash_box_id: targetBoxId,
        source_account_id: sourceBankId,
        amount: val,
        notes: description || undefined,
      })
      onReplenishCompleted?.(targetBoxId, val)
      onOpenChange(false)
      setTargetBoxId('')
      setAmount('')
      setDescription('')
    } catch (err: any) {
      const detail = err?.response?.data?.detail
      const msg = Array.isArray(detail) ? detail.join(', ') : detail || err.message || 'Replenishment failed'
      alert(`Float replenishment failed: ${msg}`)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[500px] gap-4">
        <form onSubmit={handleSubmit}>
          <DialogHeader className="pb-2 border-b">
            <div className="flex items-center gap-2 text-emerald-600 dark:text-emerald-400">
              <div className="p-1.5 rounded-md bg-emerald-500/10 border border-emerald-500/20">
                <ArrowLeftRight className="size-4" />
              </div>
              <DialogTitle className="text-base font-bold">Replenish Site Petty Cash Float</DialogTitle>
            </div>
            <DialogDescription className="text-xs">
              Top up a site cash box from corporate bank float (triggers instant WhatsApp notification to custodian).
            </DialogDescription>
          </DialogHeader>

          <div className="grid gap-3 py-4 text-xs">
            {/* Source Bank & Target Cash Box */}
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="source_bank" className="text-xs font-semibold flex items-center gap-1">
                  <Landmark className="size-3.5 text-muted-foreground" />
                  Source Bank Account *
                </Label>
                <Select value={sourceBankId} onValueChange={setSourceBankId}>
                  <SelectTrigger id="source_bank" className="h-9 text-xs">
                    <SelectValue placeholder="Select Source Bank" />
                  </SelectTrigger>
                  <SelectContent>
                    {bankAccounts.map((b) => (
                      <SelectItem key={b.id} value={b.id} className="text-xs">
                        {b.name} ({formatCurrency(b.current_balance)})
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="target_box_replenish" className="text-xs font-semibold flex items-center gap-1">
                  <Wallet className="size-3.5 text-muted-foreground" />
                  Target Site Float Box *
                </Label>
                <Select value={targetBoxId} onValueChange={setTargetBoxId}>
                  <SelectTrigger id="target_box_replenish" className="h-9 text-xs">
                    <SelectValue placeholder="Select Site Box" />
                  </SelectTrigger>
                  <SelectContent>
                    {cashBoxes.map((box) => (
                      <SelectItem key={box.id} value={box.id} className="text-xs">
                        {box.name} ({formatCurrency(box.current_balance)})
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {selectedBox && (
                  <span className="text-[10px] text-muted-foreground block">
                    Custodian: <strong>{selectedBox.custodian_name}</strong>
                  </span>
                )}
              </div>
            </div>

            {/* Replenish Amount & Date */}
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="replenish_amount" className="text-xs font-semibold flex items-center gap-1">
                  <DollarSign className="size-3.5 text-muted-foreground" />
                  Top-Up Amount (₹) *
                </Label>
                <Input
                  id="replenish_amount"
                  type="number"
                  step="0.01"
                  placeholder="50,000"
                  value={amount}
                  onChange={(e) => setAmount(e.target.value)}
                  className="font-mono font-semibold text-sm h-9"
                  required
                />
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="replenish_date" className="text-xs font-semibold flex items-center gap-1">
                  <Calendar className="size-3.5 text-muted-foreground" />
                  Transfer Date
                </Label>
                <Input
                  id="replenish_date"
                  type="date"
                  value={transferDate}
                  onChange={(e) => setTransferDate(e.target.value)}
                  className="h-9 text-xs"
                />
              </div>
            </div>

            {/* Remarks */}
            <div className="space-y-1.5">
              <Label htmlFor="replenish_desc" className="text-xs font-semibold flex items-center gap-1">
                <FileText className="size-3.5 text-muted-foreground" />
                Remarks / Reference #
              </Label>
              <Input
                id="replenish_desc"
                placeholder="e.g. Monthly petty cash replenishment for Site Alpha"
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
              disabled={submitting || !sourceBankId || !targetBoxId || !amount}
              className="bg-emerald-600 hover:bg-emerald-700 text-white gap-1.5 font-semibold"
            >
              <ArrowLeftRight className="size-3.5" />
              {submitting ? 'Replenishing...' : 'Execute Replenishment'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
