import * as React from 'react'
import { Wallet, DollarSign, Calendar, FileText, Tag, User } from 'lucide-react'
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

export interface PettyCashBox {
  id: string
  name: string
  current_balance: number
  custodian_name: string
  project_name: string
  project_id?: string
  site_id?: string
}

interface RecordVoucherDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  cashBoxes: PettyCashBox[]
  // No arguments -- the caller re-fetches real data after a successful
  // record rather than being handed a client-fabricated voucher object
  // (the backend resolves the real category/vendor/expense id, none of
  // which this dialog can predict).
  onVoucherCreated?: () => void
}

import { recordVoucherApi } from '@/lib/api'
import { toLocalISODate } from '@/lib/utils'

export function RecordVoucherDialog({
  open,
  onOpenChange,
  cashBoxes,
  onVoucherCreated,
}: RecordVoucherDialogProps) {
  const [cashBoxId, setCashBoxId] = React.useState('')
  const [amount, setAmount] = React.useState('')
  const [category, setCategory] = React.useState('Fuel & Logistics')
  const [vendorName, setVendorName] = React.useState('')
  const [description, setDescription] = React.useState('')
  const [voucherDate, setVoucherDate] = React.useState(() => toLocalISODate())
  const [submitting, setSubmitting] = React.useState(false)

  const selectedBox = React.useMemo(() => {
    return cashBoxes.find((b) => b.id === cashBoxId)
  }, [cashBoxes, cashBoxId])

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
    if (!cashBoxId || !val || val <= 0) return

    if (selectedBox && val > selectedBox.current_balance) {
      alert('Voucher amount exceeds available site cash box balance.')
      return
    }
    if (!selectedBox?.project_id) {
      alert('This cash box has no project assigned, so a voucher cannot be recorded against it.')
      return
    }

    setSubmitting(true)

    try {
      await recordVoucherApi({
        cash_box_id: cashBoxId,
        project_id: selectedBox.project_id,
        site_id: selectedBox.site_id,
        amount: val,
        category,
        vendor_name: vendorName || undefined,
        description: description || 'Petty cash expenditure',
        date: voucherDate,
      })
      onVoucherCreated?.()
      onOpenChange(false)
      setCashBoxId('')
      setAmount('')
      setVendorName('')
    } catch (err: any) {
      const detail = err?.response?.data?.detail
      const msg = Array.isArray(detail) ? detail.join(', ') : detail || err.message || 'Record voucher failed'
      alert(`Record voucher failed: ${msg}`)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[500px] gap-4">
        <form onSubmit={handleSubmit}>
          <DialogHeader className="pb-2 border-b">
            <div className="flex items-center gap-2 text-amber-600 dark:text-amber-400">
              <div className="p-1.5 rounded-md bg-amber-500/10 border border-amber-500/20">
                <Wallet className="size-4" />
              </div>
              <DialogTitle className="text-base font-bold">Record Petty Cash Expense Voucher</DialogTitle>
            </div>
            <DialogDescription className="text-xs">
              Cash spent on site, from its cash box.
            </DialogDescription>
          </DialogHeader>

          <div className="grid gap-3 py-4 text-xs">
            {/* Target Cash Box & Amount */}
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="target_box" className="text-xs font-semibold">
                  Site Cash Float Box *
                </Label>
                <Select value={cashBoxId} onValueChange={setCashBoxId}>
                  <SelectTrigger id="target_box" className="h-9 text-xs">
                    <SelectValue placeholder="Select Cash Box" />
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
                    Available Float: <strong className="text-amber-600 font-mono">{formatCurrency(selectedBox.current_balance)}</strong>
                  </span>
                )}
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="vch_amount" className="text-xs font-semibold flex items-center gap-1">
                  <DollarSign className="size-3.5 text-muted-foreground" />
                  Voucher Amount (₹) *
                </Label>
                <Input
                  id="vch_amount"
                  type="number"
                  step="0.01"
                  placeholder="0.00"
                  value={amount}
                  onChange={(e) => setAmount(e.target.value)}
                  className="font-mono font-semibold text-sm h-9"
                  required
                />
              </div>
            </div>

            {/* Category & Vendor Name */}
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="vch_cat" className="text-xs font-semibold flex items-center gap-1">
                  <Tag className="size-3.5 text-muted-foreground" />
                  Expense Category
                </Label>
                <Select value={category} onValueChange={setCategory}>
                  <SelectTrigger id="vch_cat" className="h-9 text-xs">
                    <SelectValue placeholder="Select Category" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="Fuel & Logistics">Fuel & Logistics</SelectItem>
                    <SelectItem value="Site Refreshments & Tea">Site Refreshments & Tea</SelectItem>
                    <SelectItem value="Hardware & Small Tools">Hardware & Small Tools</SelectItem>
                    <SelectItem value="Emergency Repairs">Emergency Repairs</SelectItem>
                    <SelectItem value="Daily Travel / Conveyance">Daily Travel / Conveyance</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="vch_vendor" className="text-xs font-semibold flex items-center gap-1">
                  <User className="size-3.5 text-muted-foreground" />
                  Vendor / Payee Name
                </Label>
                <Input
                  id="vch_vendor"
                  placeholder="e.g. Local Hardware / Fuel Bunk"
                  value={vendorName}
                  onChange={(e) => setVendorName(e.target.value)}
                  className="h-9 text-xs"
                />
              </div>
            </div>

            {/* Date & Description */}
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="vch_date" className="text-xs font-semibold flex items-center gap-1">
                  <Calendar className="size-3.5 text-muted-foreground" />
                  Voucher Date
                </Label>
                <Input
                  id="vch_date"
                  type="date"
                  value={voucherDate}
                  onChange={(e) => setVoucherDate(e.target.value)}
                  className="h-9 text-xs"
                />
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="vch_desc" className="text-xs font-semibold flex items-center gap-1">
                  <FileText className="size-3.5 text-muted-foreground" />
                  Remarks / Description
                </Label>
                <Input
                  id="vch_desc"
                  placeholder="e.g. Diesel for JCB Excavator #2"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  className="h-9 text-xs"
                />
              </div>
            </div>
          </div>

          <DialogFooter className="pt-2 border-t">
            <Button type="button" variant="outline" size="sm" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button
              type="submit"
              size="sm"
              disabled={submitting || !cashBoxId || !amount}
              className="bg-amber-600 hover:bg-amber-700 text-white gap-1.5 font-semibold"
            >
              <Wallet className="size-3.5" />
              {submitting ? 'Recording...' : 'Record Cash Voucher'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
