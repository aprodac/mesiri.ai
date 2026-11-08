import * as React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDown } from 'lucide-react'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Combobox } from '@/components/ui/combobox'
import { useToast } from '@/components/ui/toast-notification'
import { fetchVendorsApi } from '@/lib/api'
import { useAuth } from '@/lib/AuthContext'
import { cn } from '@/lib/utils'
import {
  MACHINE_TYPES, VEHICLE_TYPES, createMachine, errorWords, iso, updateMachine, useSiteOptions,
  type Kind, type Machine, type MachineInput, type Ownership, type RateUnit,
} from '@/lib/equipment'

// NXT-11: add a machine or vehicle, or change one. The few things that decide its cost first (owned or hired, from
// whom, the rate), the rest folded under "More details". A hire company typed here becomes a vendor of kind hire.

function Segmented<T extends string>({ value, options, onChange, label }: { value: T; options: { value: T; label: string }[]; onChange: (v: T) => void; label: string }) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded-lg bg-muted p-1">
      {options.map((o) => (
        <button key={o.value} type="button" role="radio" aria-checked={value === o.value} onClick={() => onChange(o.value)}
          className={cn('h-8 rounded-md px-3 text-sm', value === o.value ? 'bg-background font-semibold shadow-sm' : 'text-foreground/70 hover:text-foreground')}>
          {o.label}
        </button>
      ))}
    </div>
  )
}

const num = (v: string) => v.replace(/[^0-9.]/g, '')

export function MachineDialog({ open, onOpenChange, editing, defaultKind = 'machine', defaultSiteId, onSaved }: {
  open: boolean
  onOpenChange: (open: boolean) => void
  editing?: Machine | null
  defaultKind?: Kind
  defaultSiteId?: string
  onSaved?: (m: Machine) => void
}) {
  const { me } = useAuth()
  const seesMoney = ['ADMIN', 'OWNER', 'SUPER_ADMIN', 'FINANCE', 'PROJECT_MANAGER'].includes((me?.role || '').toUpperCase())
  const toast = useToast()
  const qc = useQueryClient()
  const sites = useSiteOptions()
  const vendors = useQuery({ queryKey: ['vendors'], queryFn: fetchVendorsApi, enabled: open && seesMoney, staleTime: 60_000 })

  const [kind, setKind] = React.useState<Kind>(defaultKind)
  const [name, setName] = React.useState('')
  const [type, setType] = React.useState('')
  const [ownership, setOwnership] = React.useState<Ownership>('hired')
  const [hireCompany, setHireCompany] = React.useState('')
  const [rate, setRate] = React.useState('')
  const [unit, setUnit] = React.useState<RateUnit>('hour')
  const [minHours, setMinHours] = React.useState('')
  const [siteId, setSiteId] = React.useState('')
  const [onHireFrom, setOnHireFrom] = React.useState(iso(new Date()))
  const [reg, setReg] = React.useState('')
  const [make, setMake] = React.useState('')
  const [operator, setOperator] = React.useState('')
  const [service, setService] = React.useState('')
  const [notes, setNotes] = React.useState('')
  const [more, setMore] = React.useState(false)
  const [error, setError] = React.useState('')

  React.useEffect(() => {
    if (!open) return
    setKind(editing?.kind ?? defaultKind)
    setName(editing?.name ?? '')
    setType(editing?.type ?? '')
    setOwnership(editing?.ownership ?? 'hired')
    setHireCompany(editing?.vendor_name ?? '')
    setRate(editing?.rate ? String(Number(editing.rate)) : '')
    setUnit(editing?.rate_unit ?? 'hour')
    setMinHours(editing?.min_hours_per_day ?? '')
    setSiteId(editing ? editing.site_id ?? '' : defaultSiteId ?? '')
    setOnHireFrom(editing?.on_hire_from ?? iso(new Date()))
    setReg(editing?.registration_no ?? '')
    setMake(editing?.make_model ?? '')
    setOperator(editing?.operator_name ?? '')
    setService(editing?.service_every_hours ?? '')
    setNotes(editing?.notes ?? '')
    setMore(!!editing && !!(editing.registration_no || editing.make_model || editing.operator_name || editing.service_every_hours || editing.notes))
    setError('')
  }, [open, editing, defaultKind, defaultSiteId])

  const save = useMutation({
    mutationFn: async () => {
      const body: MachineInput = {
        name: name.trim(), type: type.trim() || null, kind, ownership,
        registration_no: reg.trim() || null, make_model: make.trim() || null, operator_name: operator.trim() || null,
        service_every_hours: service || null, notes: notes.trim() || null,
      }
      if (ownership === 'hired') {
        if (hireCompany.trim() && hireCompany.trim() !== editing?.vendor_name) body.hire_company = hireCompany.trim()
        if (seesMoney || !editing) {
          body.rate = rate || null
          body.rate_unit = rate ? unit : null
          body.min_hours_per_day = unit === 'hour' && minHours ? minHours : null
        }
      }
      if (!editing) {
        body.site_id = siteId || null
        if (ownership === 'hired' && siteId) body.on_hire_from = onHireFrom
        return createMachine(body)
      }
      return updateMachine(editing.id, body)
    },
    onSuccess: (m) => {
      qc.invalidateQueries({ queryKey: ['equipment'] })
      toast.success(editing ? `${m.name} saved` : `${m.name} added (${m.ref})`, !editing && m.site_name ? `At ${m.site_name}. Log its day from the board or on WhatsApp: "${m.name} 6 hrs, 30 L diesel".` : undefined)
      onSaved?.(m)
      onOpenChange(false)
    },
    onError: (e) => setError(errorWords(e)),
  })

  const types = kind === 'vehicle' ? VEHICLE_TYPES : MACHINE_TYPES
  const hireVendors = (vendors.data ?? []).filter((v) => v.status === 'active')
  const siteOptions = (sites.data ?? []).map((s) => ({ value: s.id, label: `${s.projectName} › ${s.name}` }))
  const ready = name.trim().length > 0 && (editing || siteId || ['ADMIN', 'OWNER', 'SUPER_ADMIN', 'PROJECT_MANAGER'].includes((me?.role || '').toUpperCase()))

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[92vh] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{editing ? `Change ${editing.name}` : kind === 'vehicle' ? 'Add a vehicle' : 'Add a machine'}</DialogTitle>
        </DialogHeader>
        <form className="flex flex-col gap-4" onSubmit={(e) => { e.preventDefault(); if (ready) save.mutate() }}>
          {!editing && <Segmented label="Machine or vehicle" value={kind} onChange={setKind} options={[{ value: 'machine', label: 'Machine' }, { value: 'vehicle', label: 'Vehicle' }]} />}
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="eq-name">Name, as the site calls it</Label>
              <Input id="eq-name" autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder={kind === 'vehicle' ? 'Tipper KL-07' : 'JCB, JCB 2, Mixer'} maxLength={80} />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="eq-type">Type</Label>
              <Input id="eq-type" list="eq-types" value={type} onChange={(e) => setType(e.target.value)} placeholder="Pick or type" maxLength={60} />
              <datalist id="eq-types">{types.map((t) => <option key={t} value={t} />)}</datalist>
            </div>
          </div>

          <div className="flex flex-col gap-2 rounded-xl border bg-muted/30 p-3">
            <Segmented label="Owned or hired" value={ownership} onChange={setOwnership} options={[{ value: 'hired', label: 'Hired' }, { value: 'owned', label: 'Our own' }]} />
            {ownership === 'hired' && (
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="flex flex-col gap-1.5 sm:col-span-2">
                  <Label htmlFor="eq-vendor">Hire company</Label>
                  <Input id="eq-vendor" list="eq-vendors" value={hireCompany} onChange={(e) => setHireCompany(e.target.value)} placeholder="Kerala Earthmovers" maxLength={120} />
                  <datalist id="eq-vendors">{hireVendors.map((v) => <option key={v.id} value={v.name} />)}</datalist>
                </div>
                {(seesMoney || !editing) && (
                  <>
                    <div className="flex flex-col gap-1.5">
                      <Label htmlFor="eq-rate">Hire rate</Label>
                      <div className="flex items-center rounded-md border bg-background focus-within:ring-2 focus-within:ring-ring">
                        <span className="pl-2.5 text-sm text-muted-foreground">₹</span>
                        <Input id="eq-rate" inputMode="decimal" className="border-0 font-semibold tabular-nums shadow-none focus-visible:ring-0" value={rate} onChange={(e) => setRate(num(e.target.value))} placeholder="1100" />
                      </div>
                    </div>
                    <div className="flex flex-col gap-1.5">
                      <Label>Per</Label>
                      <Segmented label="Rate per" value={unit} onChange={setUnit} options={[{ value: 'hour', label: 'Hour' }, { value: 'day', label: 'Day' }, { value: 'month', label: 'Month' }]} />
                    </div>
                    {unit === 'hour' && (
                      <div className="flex flex-col gap-1.5 sm:col-span-2">
                        <Label htmlFor="eq-min">Minimum hours a day (charged even when it works less)</Label>
                        <Input id="eq-min" inputMode="decimal" className="w-28 tabular-nums" value={minHours} onChange={(e) => setMinHours(num(e.target.value))} placeholder="8" />
                      </div>
                    )}
                  </>
                )}
              </div>
            )}
          </div>

          {!editing && (
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="flex flex-col gap-1.5">
                <Label>Site it is at</Label>
                <Combobox options={siteOptions} value={siteId} onValueChange={setSiteId} placeholder="Pick a site" searchPlaceholder="Site or project" emptyText="No site with that name" />
              </div>
              {ownership === 'hired' && siteId && (
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="eq-from">On hire from</Label>
                  <Input id="eq-from" type="date" value={onHireFrom} max={iso(new Date())} onChange={(e) => setOnHireFrom(e.target.value)} />
                </div>
              )}
            </div>
          )}

          <button type="button" onClick={() => setMore((m) => !m)} className="inline-flex w-fit items-center gap-1 text-sm font-medium text-muted-foreground hover:text-foreground" aria-expanded={more}>
            <ChevronDown className={cn('size-4 transition', more && 'rotate-180')} /> More details
          </button>
          {more && (
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="eq-reg">{kind === 'vehicle' ? 'Registration no.' : 'Number / serial'}</Label>
                <Input id="eq-reg" value={reg} onChange={(e) => setReg(e.target.value)} placeholder="KL-07-AB-1234" maxLength={40} />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="eq-make">Make and model</Label>
                <Input id="eq-make" value={make} onChange={(e) => setMake(e.target.value)} placeholder="JCB 3DX" maxLength={80} />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="eq-op">{kind === 'vehicle' ? 'Driver' : 'Operator'}</Label>
                <Input id="eq-op" value={operator} onChange={(e) => setOperator(e.target.value)} placeholder="Suresh" maxLength={80} />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="eq-svc">Service every (hours worked)</Label>
                <Input id="eq-svc" inputMode="decimal" value={service} onChange={(e) => setService(num(e.target.value))} placeholder="250" />
              </div>
              <div className="flex flex-col gap-1.5 sm:col-span-2">
                <Label htmlFor="eq-notes">Notes</Label>
                <Input id="eq-notes" value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Operator's batta included" maxLength={500} />
              </div>
            </div>
          )}
          {error && <p role="alert" className="rounded-lg bg-destructive/10 px-3 py-2 text-sm text-destructive">{error}</p>}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
            <Button type="submit" disabled={!ready || save.isPending}>{save.isPending ? 'Saving…' : editing ? 'Save' : 'Add'}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
