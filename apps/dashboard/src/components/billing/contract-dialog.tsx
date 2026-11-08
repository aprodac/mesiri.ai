import * as React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { useToast } from '@/components/ui/toast-notification'
import { apiErrorMessage } from '@/lib/logo-upload'
import { fetchClients, fetchContract, putContract, rupees, type Contract, type ContractInput } from '@/lib/billing'

// NXT-01: a project's client and contract terms. The RA bills (NXT-02) use them: retention held from each bill,
// the mobilisation advance recovered from each bill, GST added and TDS taken off.

const TERMS: { key: keyof Contract; label: string; hint?: string; suffix?: string; type?: string }[] = [
  { key: 'contract_value', label: 'Contract value', suffix: '₹' },
  { key: 'contract_no', label: 'Agreement number', type: 'text' },
  { key: 'signed_on', label: 'Signed on', type: 'date' },
  { key: 'retention_pct', label: 'Retention', suffix: '%', hint: 'Held from each bill until the defect period ends' },
  { key: 'mobilisation_advance', label: 'Mobilisation advance', suffix: '₹', hint: 'Paid by the client at the start' },
  { key: 'advance_recovery_pct', label: 'Advance recovery per bill', suffix: '%', hint: 'Of each bill, until the advance is back' },
  { key: 'gst_pct', label: 'GST', suffix: '%' },
  { key: 'tds_pct', label: 'TDS', suffix: '%', hint: 'Deducted by the client' },
  { key: 'defect_liability_months', label: 'Defect liability', suffix: 'months' },
]

type Form = Record<string, string>

/** A stored value as the form shows it: "8500000.00" as 8500000, a date or text as it is, nothing as empty. */
const blank = (v: unknown) => (v === null || v === undefined ? '' : typeof v === 'string' && /^\d+(\.\d+)?$/.test(v) ? String(Number(v)) : String(v))

export function ContractDialog({ projectId, open, onOpenChange }: { projectId: string; open: boolean; onOpenChange: (o: boolean) => void }) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const contract = useQuery({ queryKey: ['contract', projectId], queryFn: () => fetchContract(projectId), enabled: open })
  const clients = useQuery({ queryKey: ['billing-clients'], queryFn: fetchClients, enabled: open })
  const [form, setForm] = React.useState<Form>({})
  const [clientId, setClientId] = React.useState('')
  const [newName, setNewName] = React.useState('')

  React.useEffect(() => {
    if (!open || !contract.data) return
    const c = contract.data.contract
    const f: Form = {}
    for (const t of TERMS) f[t.key] = blank(c?.[t.key])
    f.payment_terms = c?.payment_terms ?? ''
    setForm(f)
    setClientId(c?.client_id ?? '')
    setNewName('')
  }, [open, contract.data])

  const save = useMutation({
    mutationFn: () => {
      const body: ContractInput = {}
      for (const t of TERMS) {
        const v = (form[t.key] ?? '').trim()
        ;(body as Record<string, unknown>)[t.key] = v === '' ? null : t.key === 'defect_liability_months' ? Number(v) : v
      }
      body.payment_terms = form.payment_terms?.trim() || null
      if (clientId === 'new') body.new_client = { name: newName.trim() }
      else body.client_id = clientId || null
      return putContract(projectId, body)
    },
    onSuccess: () => {
      toast.success('Contract saved')
      for (const k of ['contract', 'billing-clients', 'project-start', 'ra-bills']) queryClient.invalidateQueries({ queryKey: [k] })
      onOpenChange(false)
    },
    onError: (e) => toast.error('Could not save the contract', apiErrorMessage(e)),
  })

  const value = Number(form.contract_value || 0)
  const retention = value && form.retention_pct ? (value * Number(form.retention_pct)) / 100 : null

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[92vh] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Client and contract</DialogTitle>
          <DialogDescription>
            {contract.data?.project.name}: the terms from the agreement. Every RA bill uses them, so nobody works out retention or advance recovery by hand.
          </DialogDescription>
        </DialogHeader>
        <form id="contract-form" className="grid gap-3" onSubmit={(e) => { e.preventDefault(); save.mutate() }}>
          <div className="grid gap-1.5">
            <Label htmlFor="ct-client">Client</Label>
            <select id="ct-client" className="h-9 rounded-md border bg-background px-2 text-sm" value={clientId} onChange={(e) => setClientId(e.target.value)}>
              <option value="">Not set</option>
              {clients.data?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              <option value="new">+ A new client…</option>
            </select>
            {clientId === 'new' && (
              <Input autoFocus aria-label="New client's name" placeholder="Mr. Abdullakutty" value={newName} onChange={(e) => setNewName(e.target.value)} />
            )}
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            {TERMS.map((t) => (
              <div key={t.key} className="grid gap-1">
                <Label htmlFor={`ct-${t.key}`} className="text-sm">{t.label}</Label>
                <div className="relative">
                  <Input id={`ct-${t.key}`} type={t.type ?? 'number'} min={0} step="any" inputMode={t.type ? undefined : 'decimal'}
                    value={form[t.key] ?? ''} onChange={(e) => setForm((f) => ({ ...f, [t.key]: e.target.value }))}
                    className={t.suffix && !t.type ? 'pr-16' : ''} />
                  {t.suffix && !t.type && <span className="pointer-events-none absolute inset-y-0 right-2 flex items-center text-xs text-muted-foreground">{t.suffix}</span>}
                </div>
                {t.hint && <p className="text-xs text-muted-foreground">{t.hint}</p>}
              </div>
            ))}
          </div>
          <div className="grid gap-1">
            <Label htmlFor="ct-terms">Payment terms</Label>
            <Input id="ct-terms" placeholder="Within 30 days of certification" value={form.payment_terms ?? ''} onChange={(e) => setForm((f) => ({ ...f, payment_terms: e.target.value }))} />
          </div>
          {retention !== null && (
            <p className="text-xs text-muted-foreground">On the full value, retention comes to {rupees(retention)}, released after the defect period.</p>
          )}
        </form>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button type="submit" form="contract-form" disabled={save.isPending || (clientId === 'new' && !newName.trim())}>
            {save.isPending ? 'Saving…' : 'Save'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
