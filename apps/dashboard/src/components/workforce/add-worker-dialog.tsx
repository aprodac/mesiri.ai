import * as React from 'react'
import { HardHat, UserPlus } from 'lucide-react'
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
import { createWorkerApi, type CreateWorkerPayload } from '@/lib/api'
import { RegisterFields } from './register-fields'
import { emptyRegister, registerPayload, type RegisterValue } from '@/lib/labour-pay'

interface AddWorkerDialogInitialValues {
  name?: string
  trade?: string
  dailyWage?: number | null
  contractor?: string | null
}

interface AddWorkerDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onSuccess: () => void
  /** Pre-fills the form -- used from the attendance detail view to promote a
   * temporary line (worker_id absent) into the register, carrying over
   * exactly what the site already reported rather than making someone
   * retype a name and trade that were already typed once on WhatsApp. */
  initialValues?: AddWorkerDialogInitialValues
}

const COMMON_TRADES = [
  'Mason',
  'Helper',
  'Carpenter',
  'Electrician',
  'Plumber',
  'Steel Fixer',
  'Welder',
  'Painter',
  'Equipment Operator',
  'Supervisor',
]

/** Matches a freeform reported trade (e.g. "bar_bender", "mason") to the
 * dialog's fixed Select options, case/underscore-insensitively -- so
 * promoting "mason" from an attendance line actually pre-selects Mason
 * instead of silently falling back to the default. An unrecognised trade
 * (e.g. one not in COMMON_TRADES) leaves the field for the user to pick,
 * rather than guessing. */
function _matchTradeOption(reported: string | null | undefined): string | null {
  if (!reported) return null
  const normalized = reported.trim().toLowerCase().replace(/[\s_-]+/g, ' ')
  const match = COMMON_TRADES.find((t) => t.toLowerCase() === normalized)
  return match ?? null
}

export function AddWorkerDialog({ open, onOpenChange, onSuccess, initialValues }: AddWorkerDialogProps) {
  const [name, setName] = React.useState('')
  const [trade, setTrade] = React.useState('Mason')
  const [workerType, setWorkerType] = React.useState<'permanent' | 'temporary' | 'contractor'>('permanent')
  const [dailyWage, setDailyWage] = React.useState('800')
  const [contractor, setContractor] = React.useState('')
  const [register, setRegister] = React.useState<RegisterValue>(emptyRegister())

  const [submitting, setSubmitting] = React.useState(false)
  const [error, setError] = React.useState('')

  // Re-seed the form whenever the dialog opens with new initial values --
  // effect (not lazy useState init) because the SAME dialog instance is
  // reused across different attendance lines, each opening it with a
  // different worker's details.
  React.useEffect(() => {
    if (!open) return
    setName(initialValues?.name ?? '')
    setTrade(_matchTradeOption(initialValues?.trade) ?? 'Mason')
    setDailyWage(initialValues?.dailyWage != null ? String(initialValues.dailyWage) : '800')
    setContractor(initialValues?.contractor ?? '')
    setWorkerType('permanent')
    setRegister(emptyRegister())
    setError('')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, initialValues])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim()) {
      setError('Worker name is required.')
      return
    }

    setSubmitting(true)
    setError('')

    try {
      const payload: CreateWorkerPayload = {
        name: name.trim(),
        trade: trade.trim() || undefined,
        worker_type: workerType,
        default_daily_wage: dailyWage ? parseFloat(dailyWage) : undefined,
        contractor: contractor.trim() || undefined,
        status: 'active',
        ...registerPayload(register),
      }
      await createWorkerApi(payload)
      onSuccess()
      onOpenChange(false)
      setName('')
      setTrade('Mason')
      setWorkerType('permanent')
      setDailyWage('800')
      setContractor('')
    } catch (err: any) {
      console.warn('Failed to create worker:', err)
      setError(err.response?.data?.detail || 'Failed to register worker.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[480px]">
        <DialogHeader>
          <div className="flex items-center gap-2 text-amber-600 dark:text-amber-400">
            <div className="p-1.5 rounded-md bg-amber-500/10 border border-amber-500/20">
              <HardHat className="size-5" />
            </div>
            <DialogTitle className="text-base font-bold">Register Site Worker</DialogTitle>
          </div>
          <DialogDescription className="text-xs">
            Add a new worker to the organization roster for attendance tracking and daily wage calculation.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-3.5 text-xs py-2">
          {error && (
            <div className="p-2.5 rounded-md bg-red-500/10 border border-red-500/20 text-red-600 dark:text-red-400 text-xs">
              {error}
            </div>
          )}

          <div className="space-y-1">
            <Label htmlFor="name" className="text-xs font-semibold">
              Worker Full Name <span className="text-red-500">*</span>
            </Label>
            <Input
              id="name"
              placeholder="e.g. Ramesh Kumar"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="h-9 text-xs"
              required
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label className="text-xs font-semibold">Trade / Skill</Label>
              <Select value={trade} onValueChange={setTrade}>
                <SelectTrigger className="h-9 text-xs">
                  <SelectValue placeholder="Select Trade" />
                </SelectTrigger>
                <SelectContent>
                  {COMMON_TRADES.map((t) => (
                    <SelectItem key={t} value={t} className="text-xs">
                      {t}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1">
              <Label className="text-xs font-semibold">Worker Type</Label>
              <Select value={workerType} onValueChange={(val: any) => setWorkerType(val)}>
                <SelectTrigger className="h-9 text-xs">
                  <SelectValue placeholder="Select Type" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="permanent" className="text-xs">Permanent Staff</SelectItem>
                  <SelectItem value="temporary" className="text-xs">Temporary Labor</SelectItem>
                  <SelectItem value="contractor" className="text-xs">Subcontractor</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label htmlFor="dailyWage" className="text-xs font-semibold">
                Default Daily Wage (₹)
              </Label>
              <Input
                id="dailyWage"
                type="number"
                placeholder="800"
                value={dailyWage}
                onChange={(e) => setDailyWage(e.target.value)}
                className="h-9 text-xs font-mono"
              />
            </div>

            <div className="space-y-1">
              <Label htmlFor="contractor" className="text-xs font-semibold">
                Contractor / Agency Name
              </Label>
              <Input
                id="contractor"
                placeholder="e.g. Metro Builders Ltd"
                value={contractor}
                onChange={(e) => setContractor(e.target.value)}
                className="h-9 text-xs"
              />
            </div>
          </div>

          <RegisterFields value={register} onChange={setRegister} compact />

          <DialogFooter className="pt-3 border-t">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => onOpenChange(false)}
              disabled={submitting}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              size="sm"
              disabled={submitting}
              className="bg-amber-600 hover:bg-amber-700 text-white font-bold gap-1.5"
            >
              <UserPlus className="size-3.5" />
              {submitting ? 'Registering...' : 'Register Worker'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
