import { useQuery } from '@tanstack/react-query'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useSiteOptions } from '@/lib/equipment'
import { fetchLabourTeams, type RegisterValue } from '@/lib/labour-pay'

// LW-01: who to call, whose team, where they work. One set of fields for adding and editing a worker. Picking a team
// is what pays the worker through that contractor on the wage sheet (D-W2).

export function RegisterFields({ value, onChange, compact }: { value: RegisterValue; onChange: (v: RegisterValue) => void; compact?: boolean }) {
  const teams = useQuery({ queryKey: ['labour', 'teams'], queryFn: fetchLabourTeams })
  const sites = useSiteOptions()
  const label = compact ? 'text-xs font-semibold' : undefined
  const field = compact ? 'h-9 text-xs' : 'h-9'
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
      <div className="grid gap-1.5">
        <Label htmlFor="reg-phone" className={label}>WhatsApp number</Label>
        <Input id="reg-phone" inputMode="tel" placeholder="98765 43210" className={field} value={value.phone} onChange={(e) => onChange({ ...value, phone: e.target.value })} />
      </div>
      <div className="grid gap-1.5">
        <Label htmlFor="reg-team" className={label}>Team</Label>
        <select id="reg-team" className={`${field} rounded-md border bg-background px-2`} value={value.vendorId} onChange={(e) => onChange({ ...value, vendorId: e.target.value })}>
          <option value="">Paid directly</option>
          {(teams.data?.items ?? []).map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
        </select>
      </div>
      <div className="grid gap-1.5">
        <Label htmlFor="reg-site" className={label}>Works at</Label>
        <select id="reg-site" className={`${field} rounded-md border bg-background px-2`} value={value.siteId} onChange={(e) => onChange({ ...value, siteId: e.target.value })}>
          <option value="">Any site</option>
          {(sites.data ?? []).map((s) => <option key={s.id} value={s.id}>{s.projectName} › {s.name}</option>)}
        </select>
      </div>
    </div>
  )
}
