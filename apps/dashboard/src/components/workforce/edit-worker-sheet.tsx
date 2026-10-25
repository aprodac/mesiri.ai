import * as React from 'react'
import { Save, UserX, UserCheck } from 'lucide-react'
import { Sheet, SheetContent, SheetFooter } from '@/components/ui/sheet'
import { SheetHero } from '@/components/detail-sheet'
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
import { updateWorkerApi, type WorkforceWorkerItem } from '@/lib/api'

interface EditWorkerSheetProps {
  worker: WorkforceWorkerItem | null
  open: boolean
  onOpenChange: (open: boolean) => void
  onSuccess: () => void
}

// WEB-39: the side-panel layout (detail-sheet.tsx), plain labels, actions in
// the footer: Retire / Bring back on the left, Save on the right.
export function EditWorkerSheet({ worker, open, onOpenChange, onSuccess }: EditWorkerSheetProps) {
  const [name, setName] = React.useState('')
  const [trade, setTrade] = React.useState('')
  const [workerType, setWorkerType] = React.useState<'permanent' | 'temporary' | 'contractor'>('permanent')
  const [dailyWage, setDailyWage] = React.useState('')
  const [contractor, setContractor] = React.useState('')
  const [status, setStatus] = React.useState<'active' | 'inactive'>('active')

  const [saving, setSaving] = React.useState(false)
  const [error, setError] = React.useState('')

  React.useEffect(() => {
    if (worker) {
      setName(worker.name || '')
      setTrade(worker.trade || 'Mason')
      setWorkerType(worker.worker_type || 'permanent')
      setDailyWage(worker.default_daily_wage ? String(worker.default_daily_wage) : '')
      setContractor(worker.contractor || '')
      setStatus(worker.status || 'active')
    }
  }, [worker])

  if (!worker) return null

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim()) {
      setError('Worker name is required.')
      return
    }

    setSaving(true)
    setError('')

    try {
      await updateWorkerApi(worker.id, {
        name: name.trim(),
        trade: trade.trim() || undefined,
        worker_type: workerType,
        default_daily_wage: dailyWage ? parseFloat(dailyWage) : undefined,
        contractor: contractor.trim() || undefined,
        status,
      })
      onSuccess()
      onOpenChange(false)
    } catch (err: any) {
      console.warn('Failed to update worker:', err)
      setError(err.response?.data?.detail || 'Failed to update worker profile.')
    } finally {
      setSaving(false)
    }
  }

  const handleToggleStatus = async () => {
    const nextStatus = status === 'active' ? 'inactive' : 'active'
    if (nextStatus === 'inactive') {
      if (!confirm(`Retire ${worker.name}? They stay in past attendance but are no longer offered for new days.`)) {
        return
      }
    }

    setSaving(true)
    try {
      await updateWorkerApi(worker.id, { status: nextStatus })
      setStatus(nextStatus)
      onSuccess()
    } catch (err: any) {
      console.warn('Failed to toggle worker status:', err)
      setError(err.response?.data?.detail || 'Failed to change worker status.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-full gap-0 overflow-y-auto p-0 sm:max-w-[440px]">
        <SheetHero tone={status === 'active' ? 'neutral' : 'warn'} kicker={status === 'active' ? 'Working' : 'Retired'} title={`Edit ${worker.name}`}>
          <span>Changes apply to new attendance; past days keep what was recorded.</span>
        </SheetHero>

        <form id="edit-worker-form" onSubmit={handleSave} className="flex flex-col gap-4 px-5 py-4 text-sm">
          {error && <p className="rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-destructive">{error}</p>}

          <div className="grid gap-1.5">
            <Label htmlFor="edit-name">Name</Label>
            <Input id="edit-name" value={name} onChange={(e) => setName(e.target.value)} required />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="grid gap-1.5">
              <Label htmlFor="edit-trade">Trade</Label>
              <Input id="edit-trade" value={trade} onChange={(e) => setTrade(e.target.value)} placeholder="Mason" />
            </div>
            <div className="grid gap-1.5">
              <Label>Type</Label>
              <Select value={workerType} onValueChange={(val: 'permanent' | 'temporary' | 'contractor') => setWorkerType(val)}>
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="permanent">Own worker</SelectItem>
                  <SelectItem value="temporary">Temporary</SelectItem>
                  <SelectItem value="contractor">Contractor's worker</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="grid gap-1.5">
              <Label htmlFor="edit-dailyWage">Wage a day (₹)</Label>
              <Input id="edit-dailyWage" type="number" inputMode="numeric" value={dailyWage} onChange={(e) => setDailyWage(e.target.value)} className="tabular-nums" />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="edit-contractor">Contractor</Label>
              <Input id="edit-contractor" value={contractor} onChange={(e) => setContractor(e.target.value)} placeholder="Own worker" />
            </div>
          </div>
        </form>

        <SheetFooter className="flex-row items-center gap-2 border-t px-5 py-3">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={handleToggleStatus}
            disabled={saving}
            className={status === 'active' ? 'gap-1.5 text-destructive hover:bg-destructive/10 hover:text-destructive' : 'gap-1.5 text-success hover:bg-success-soft hover:text-success'}
          >
            {status === 'active' ? (
              <>
                <UserX className="size-3.5" /> Retire
              </>
            ) : (
              <>
                <UserCheck className="size-3.5" /> Bring back
              </>
            )}
          </Button>
          <Button form="edit-worker-form" type="submit" size="sm" disabled={saving} className="ml-auto gap-1.5">
            <Save className="size-3.5" />
            {saving ? 'Saving…' : 'Save'}
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  )
}
