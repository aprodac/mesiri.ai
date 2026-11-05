import * as React from 'react'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
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
import { createVendorApi, updateVendorApi, type VendorItem } from '@/lib/api'

interface CreateVendorDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  vendorToEdit?: VendorItem | null
  onSuccess: () => void
}

export function CreateVendorDialog({
  open,
  onOpenChange,
  vendorToEdit,
  onSuccess,
}: CreateVendorDialogProps) {
  const [name, setName] = React.useState('')
  const [status, setStatus] = React.useState<'active' | 'inactive'>('active')
  // PRC-04: contact details; GSTIN is checked by the API (15 characters).
  const [phone, setPhone] = React.useState('')
  const [gstin, setGstin] = React.useState('')
  const [address, setAddress] = React.useState('')
  const [submitting, setSubmitting] = React.useState(false)
  const [error, setError] = React.useState('')

  React.useEffect(() => {
    if (vendorToEdit) {
      setName(vendorToEdit.name || '')
      setStatus(vendorToEdit.status || 'active')
      setPhone(vendorToEdit.phone || '')
      setGstin(vendorToEdit.gstin || '')
      setAddress(vendorToEdit.address || '')
    } else {
      setName('')
      setStatus('active')
      setPhone('')
      setGstin('')
      setAddress('')
    }
    setError('')
  }, [vendorToEdit, open])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim()) {
      setError('Vendor name is required')
      return
    }

    setSubmitting(true)
    setError('')

    try {
      if (vendorToEdit) {
        await updateVendorApi(vendorToEdit.id, {
          name: name.trim(),
          status,
          phone: phone.trim() || null,
          gstin: gstin.trim() || null,
          address: address.trim() || null,
        })
      } else {
        await createVendorApi({
          name: name.trim(),
          phone: phone.trim() || null,
          gstin: gstin.trim() || null,
          address: address.trim() || null,
        })
      }
      onSuccess()
      onOpenChange(false)
    } catch (err: any) {
      const msg = err?.response?.data?.detail || err.message || 'Failed to save vendor'
      setError(msg)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="text-base font-bold">
            {vendorToEdit ? 'Edit Vendor / Payee' : 'Register New Vendor / Payee'}
          </DialogTitle>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="flex flex-col gap-4 py-2 text-xs">
          {error && (
            <div className="p-2.5 rounded-md bg-rose-500/10 border border-rose-500/20 text-rose-600 text-xs">
              {error}
            </div>
          )}

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="vendor-name" className="text-xs font-semibold">
              Vendor / Payee Name <span className="text-rose-500">*</span>
            </Label>
            <Input
              id="vendor-name"
              placeholder="e.g. Indian Oil Bunk #4, UltraTech Rental Services..."
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="h-9 text-xs"
              required
            />
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="vendor-phone" className="text-xs font-semibold">
                Phone
              </Label>
              <Input id="vendor-phone" inputMode="tel" placeholder="98470 12345" value={phone} onChange={(e) => setPhone(e.target.value)} className="h-9 text-xs" />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="vendor-gstin" className="text-xs font-semibold">
                GSTIN
              </Label>
              <Input
                id="vendor-gstin"
                placeholder="32ABCDE1234F1Z5"
                value={gstin}
                onChange={(e) => setGstin(e.target.value.toUpperCase())}
                maxLength={20}
                className="h-9 text-xs uppercase"
              />
            </div>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="vendor-address" className="text-xs font-semibold">
              Address
            </Label>
            <Input id="vendor-address" placeholder="Edappally, Kochi" value={address} onChange={(e) => setAddress(e.target.value)} className="h-9 text-xs" />
          </div>

          {vendorToEdit && (
            <div className="flex flex-col gap-1.5">
              <Label className="text-xs font-semibold">Status</Label>
              <Select value={status} onValueChange={(val: any) => setStatus(val)}>
                <SelectTrigger className="h-9 text-xs">
                  <SelectValue placeholder="Select status" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="active" className="text-xs">
                    Active
                  </SelectItem>
                  <SelectItem value="inactive" className="text-xs">
                    Inactive
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>
          )}

          <DialogFooter className="pt-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => onOpenChange(false)}
              disabled={submitting}
              className="h-8 text-xs"
            >
              Cancel
            </Button>
            <Button type="submit" size="sm" disabled={submitting} className="h-8 text-xs font-semibold">
              {submitting ? 'Saving...' : vendorToEdit ? 'Update Vendor' : 'Register Vendor'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
