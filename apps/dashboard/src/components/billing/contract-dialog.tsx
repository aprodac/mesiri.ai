import { Hint } from '@/components/hint'
import * as React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { DatePicker } from '@/components/ui/date-picker'
import { cn } from '@/lib/utils'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { useToast } from '@/components/ui/toast-notification'
import { apiErrorMessage } from '@/lib/logo-upload'
import { fetchClients, fetchContract, putContract, rupees, type Contract, type ContractInput } from '@/lib/billing'

// NXT-01: a project's client and contract terms. The RA bills (NXT-02) use them: retention held from each bill,
// the mobilisation advance recovered from each bill, GST added and TDS taken off.

// UX-27: what each term means is in its "?" (a glossary word, or the words here), not a grey line under every field.
const TERMS: { key: keyof Contract; label: string; explain?: React.ComponentProps<typeof Hint>; suffix?: string; type?: string }[] = [
  { key: 'contract_value', label: 'Contract value', suffix: '₹', explain: { term: 'contract value' } },
  { key: 'contract_no', label: 'Agreement number', type: 'text' },
  { key: 'signed_on', label: 'Signed on', type: 'date' },
  { key: 'retention_pct', label: 'Retention', suffix: '%', explain: { term: 'retention', example: '5% retention on a ₹10 lakh bill: ₹50,000 held until the defects period ends.' } },
  { key: 'mobilisation_advance', label: 'Mobilisation advance', suffix: '₹', explain: { term: 'mobilisation advance' } },
  { key: 'advance_recovery_pct', label: 'Advance recovery per bill', suffix: '%', explain: { title: 'Advance recovery', text: 'The share of each bill that pays back the mobilisation advance, until all of it is back.', example: '10% a bill: on a ₹10 lakh bill, ₹1 lakh goes back against the advance.' } },
  { key: 'gst_pct', label: 'GST', suffix: '%', explain: { term: 'GST' } },
  { key: 'tds_pct', label: 'TDS', suffix: '%', explain: { term: 'TDS' } },
  { key: 'defect_liability_months', label: 'Defect liability', suffix: 'months', explain: { term: 'defects period' } },
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

  const set = (key: string) => (v: string) => setForm((f) => ({ ...f, [key]: v }))
  const field = (key: keyof Contract) => TERMS.find((t) => t.key === key)!

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[92vh] flex-col gap-0 p-0 sm:max-w-xl">
        <DialogHeader className="border-b px-6 pt-5 pb-4">
          <DialogTitle>Client and contract</DialogTitle>
          <DialogDescription>{contract.data?.project.name}: copy these from the agreement. Every RA bill uses them.</DialogDescription>
        </DialogHeader>
        <form id="contract-form" className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto px-6 py-5" onSubmit={(e) => { e.preventDefault(); save.mutate() }}>
          <Group title="Client">
            <div className="grid gap-2 sm:grid-cols-2">
              <Select value={clientId || NO_CLIENT} onValueChange={(v) => setClientId(v === NO_CLIENT ? '' : v)}>
                <SelectTrigger id="ct-client" aria-label="Client" className="h-10 w-full"><SelectValue placeholder="Who pays for the work" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value={NO_CLIENT}>Not set</SelectItem>
                  {clients.data?.map((c) => <SelectItem key={c.id} value={c.id}>{c.name}</SelectItem>)}
                  <SelectItem value="new">+ A new client</SelectItem>
                </SelectContent>
              </Select>
              {clientId === 'new' && (
                <Input autoFocus aria-label="New client's name" placeholder="Their name, e.g. Dr. Anand Krishnan" className="h-10" value={newName} onChange={(e) => setNewName(e.target.value)} />
              )}
            </div>
          </Group>

          <Group title="The agreement">
            <div className="grid gap-3 sm:grid-cols-[1.4fr_1fr]">
              <Term t={field('contract_value')} value={form.contract_value} onChange={set('contract_value')} below={inWords(form.contract_value)} />
              <Term t={field('contract_no')} value={form.contract_no} onChange={set('contract_no')} />
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <Term t={field('signed_on')} value={form.signed_on} onChange={set('signed_on')} />
            </div>
          </Group>

          <Group title="Held back and paid back">
            <div className="grid gap-3 sm:grid-cols-2">
              <Term t={field('retention_pct')} value={form.retention_pct} onChange={set('retention_pct')} />
              <Term t={field('defect_liability_months')} value={form.defect_liability_months} onChange={set('defect_liability_months')} />
              <Term t={field('mobilisation_advance')} value={form.mobilisation_advance} onChange={set('mobilisation_advance')} below={inWords(form.mobilisation_advance)} />
              <Term t={field('advance_recovery_pct')} value={form.advance_recovery_pct} onChange={set('advance_recovery_pct')} />
            </div>
          </Group>

          <Group title="Taxes">
            <div className="grid grid-cols-2 gap-3">
              <Term t={field('gst_pct')} value={form.gst_pct} onChange={set('gst_pct')} />
              <Term t={field('tds_pct')} value={form.tds_pct} onChange={set('tds_pct')} />
            </div>
          </Group>

          <div className="grid gap-1.5">
            <Label htmlFor="ct-terms" className="text-sm font-medium">Payment terms</Label>
            <Input id="ct-terms" className="h-10" placeholder="Within 30 days of certification" value={form.payment_terms ?? ''} onChange={(e) => set('payment_terms')(e.target.value)} />
          </div>

          <Example form={form} />
        </form>
        <DialogFooter className="border-t px-6 py-3">
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button type="submit" form="contract-form" disabled={save.isPending || (clientId === 'new' && !newName.trim())}>
            {save.isPending ? 'Saving…' : 'Save'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

const NO_CLIENT = '__none__'

function Group({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <fieldset className="grid gap-3">
      <legend className="mb-2 text-xs font-semibold tracking-wide text-muted-foreground uppercase">{title}</legend>
      {children}
    </fieldset>
  )
}

/** One term: its label and "?", the field with ₹ in front or %, months after, and a line under it when useful. */
function Term({ t, value, onChange, below }: { t: (typeof TERMS)[number]; value?: string; onChange: (v: string) => void; below?: string | null }) {
  const id = `ct-${t.key}`
  const money = t.suffix === '₹'
  return (
    <div className="grid content-start gap-1.5">
      <span className="flex items-center gap-1">
        <Label htmlFor={id} className="text-sm font-medium">{t.label}</Label>
        {t.explain && <Hint {...t.explain} />}
      </span>
      {t.type === 'date' ? (
        <DatePicker id={id} value={value ?? ''} onChange={onChange} className="[&>button]:h-10" />
      ) : (
        <div className="relative">
          {money && <span className="pointer-events-none absolute inset-y-0 left-3 flex items-center text-sm text-muted-foreground">₹</span>}
          <Input
            id={id}
            type={t.type ?? 'number'}
            min={0}
            step="any"
            inputMode={t.type ? undefined : 'decimal'}
            value={value ?? ''}
            onChange={(e) => onChange(e.target.value)}
            className={cn(
              'h-10 [appearance:textfield] tabular-nums [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none',
              money && 'pl-7',
              t.suffix && !money && 'pr-16',
            )}
          />
          {t.suffix && !money && <span className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-sm text-muted-foreground">{t.suffix}</span>}
        </div>
      )}
      {below && <span className="text-xs text-muted-foreground tabular-nums">{below}</span>}
    </div>
  )
}

/** "₹82,06,050" in words a person says: "82.06 lakh", "1.04 crore". */
function inWords(v?: string): string | null {
  const n = Number(v || 0)
  if (!n) return null
  if (n >= 1e7) return `${(n / 1e7).toFixed(2).replace(/\.?0+$/, '')} crore`
  if (n >= 1e5) return `${(n / 1e5).toFixed(2).replace(/\.?0+$/, '')} lakh`
  return null
}

/**
 * UX-28: what these terms do to one bill, from the numbers typed (a ₹10 lakh bill of work), so the percentages mean
 * something before the first RA bill. The RA bill itself works it out from the BOQ (NXT-02).
 */
function Example({ form }: { form: Form }) {
  const pct = (k: string) => Number(form[k] || 0)
  const work = 1_000_000
  const retention = (work * pct('retention_pct')) / 100
  const advance = Number(form.mobilisation_advance || 0) ? (work * pct('advance_recovery_pct')) / 100 : 0
  const gst = (work * pct('gst_pct')) / 100
  const tds = (work * pct('tds_pct')) / 100
  if (!retention && !advance && !gst && !tds) return null
  const paid = work - retention - advance + gst - tds
  const row = (label: string, amount: number, sign: '+' | '−' | '', strong = false) => (
    <div className={cn('flex justify-between gap-3 tabular-nums', strong && 'border-t pt-1.5 font-semibold')}>
      <span className={strong ? '' : 'text-muted-foreground'}>{label}</span>
      <span>{sign}{rupees(amount)}</span>
    </div>
  )
  return (
    <section className="grid gap-1.5 rounded-lg border bg-muted/40 p-3 text-sm" aria-label="On one bill">
      <h3 className="m-0 text-sm font-semibold">On a bill for ₹10 lakh of work</h3>
      {retention > 0 && row(`Retention held (${pct('retention_pct')}%)`, retention, '−')}
      {advance > 0 && row(`Advance paid back (${pct('advance_recovery_pct')}%)`, advance, '−')}
      {gst > 0 && row(`GST added (${pct('gst_pct')}%)`, gst, '+')}
      {tds > 0 && row(`TDS kept by the client (${pct('tds_pct')}%)`, tds, '−')}
      {row('You receive', paid, '', true)}
    </section>
  )
}
