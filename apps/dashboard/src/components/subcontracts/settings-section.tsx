import * as React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Handshake } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useToast } from '@/components/ui/toast-notification'
import { fetchFinanceSettingsApi, updateFinanceSettingsApi } from '@/lib/api'
import { apiErrorMessage } from '@/lib/logo-upload'

// D-S0..S2 (approved 8 Nov 2026): the company's subcontract rules: TDS on subcontract bills (off until turned on),
// its default %, the default retention %, and whether subcontractors may use Mesiri's WhatsApp.

type S = { tds_enabled?: boolean; tds_default_pct?: string | number; retention_default_pct?: string | number; partner_access?: boolean }

export function SubcontractSettings({ readOnly }: { readOnly: boolean }) {
  const queryClient = useQueryClient()
  const toast = useToast()
  const settings = useQuery({ queryKey: ['finance', 'settings'], queryFn: fetchFinanceSettingsApi })
  const s = (settings.data ?? {}) as S
  const [tds, setTds] = React.useState('1')
  const [ret, setRet] = React.useState('5')
  React.useEffect(() => { if (settings.data) { setTds(String(Number(s.tds_default_pct ?? 1))); setRet(String(Number(s.retention_default_pct ?? 5))) } }, [settings.data]) // eslint-disable-line react-hooks/exhaustive-deps
  const save = useMutation({
    mutationFn: (body: Partial<S>) => updateFinanceSettingsApi(body as never),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['finance'] }); toast.success('Saved') },
    onError: (e) => toast.error('Not saved', apiErrorMessage(e)),
  })
  const Toggle = ({ on, label, hint, onChange }: { on: boolean; label: string; hint: string; onChange: (v: boolean) => void }) => (
    <label className="flex cursor-pointer items-start gap-3 rounded-lg border p-3">
      <input type="checkbox" className="mt-0.5 size-4 accent-primary" checked={on} disabled={readOnly || save.isPending} onChange={(e) => onChange(e.target.checked)} />
      <span><span className="block text-sm font-medium">{label}</span><span className="block text-xs text-muted-foreground">{hint}</span></span>
    </label>
  )
  return (
    <section className="flex flex-col gap-3 border-t pt-4">
      <h2 className="flex items-center gap-2 text-[15px] font-semibold"><Handshake className="size-4 text-muted-foreground" aria-hidden="true" /> Subcontractors</h2>
      <Toggle on={!!s.tds_enabled} label="Deduct TDS from subcontract bills (194C)" hint="Each approved bill deducts it; it collects in the “TDS payable (194C)” account until you pay the government (a transfer into it)." onChange={(v) => save.mutate({ tds_enabled: v })} />
      <Toggle on={!!s.partner_access} label="Subcontractors may use Mesiri on WhatsApp" hint="Their contacts (added on the subcontractor’s page) can ask what is pending, send bills and report work. Bills and work wait for your check; they never see anything else." onChange={(v) => save.mutate({ partner_access: v })} />
      <form className="flex flex-wrap items-end gap-3" onSubmit={(e) => { e.preventDefault(); save.mutate({ tds_default_pct: tds, retention_default_pct: ret }) }}>
        <div className="grid gap-1.5"><Label htmlFor="tdsPct">TDS % (when a subcontractor has none)</Label><Input id="tdsPct" type="number" min={0} max={20} step="any" value={tds} onChange={(e) => setTds(e.target.value)} className="h-9 w-32" disabled={readOnly} /></div>
        <div className="grid gap-1.5"><Label htmlFor="retPct">Retention % on new work orders</Label><Input id="retPct" type="number" min={0} max={50} step="any" value={ret} onChange={(e) => setRet(e.target.value)} className="h-9 w-32" disabled={readOnly} /></div>
        {!readOnly && <Button type="submit" size="sm" disabled={save.isPending}>Save</Button>}
      </form>
      <p className="text-xs text-muted-foreground">194C: 1% for an individual or HUF, 2% for a firm; set a subcontractor’s own % on its work order.</p>
    </section>
  )
}
