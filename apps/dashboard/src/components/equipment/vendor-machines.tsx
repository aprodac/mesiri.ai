import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Construction } from 'lucide-react'
import { fetchMachines, hrs, rateWords, inr } from '@/lib/equipment'
import { MachineAvatar, StateChip } from './parts'

// NXT-11: on a hire company's supplier page, the machines hired from them: where each is, this month's hours and
// what the hours come to. Their bills are on this account; the hire check compares them with the hours.

export function VendorMachines({ vendorId }: { vendorId: string }) {
  const { data } = useQuery({ queryKey: ['equipment', 'machines', 'vendor', vendorId], queryFn: () => fetchMachines({ vendor_id: vendorId, status: 'all' }) })
  const items = data?.items ?? []
  if (!items.length) return null
  return (
    <section aria-label="Machines hired" className="overflow-hidden rounded-xl border bg-card">
      <h2 className="flex items-center justify-between border-b bg-muted/30 px-4 py-2 text-sm font-semibold">
        <span className="inline-flex items-center gap-2"><Construction className="size-4 text-muted-foreground" />Machines hired from them</span>
        <Link to="/equipment/hire" className="text-xs font-normal text-primary hover:underline">Hire check</Link>
      </h2>
      {items.map((m) => (
        <Link key={m.id} to={`/equipment/${m.id}`} className="flex items-center gap-3 border-b px-4 py-2.5 text-sm last:border-b-0 hover:bg-muted/40">
          <MachineAvatar machine={m} size="sm" />
          <span className="flex min-w-0 flex-1 flex-col">
            <span className="truncate font-semibold">{m.name} <span className="font-normal text-muted-foreground">{m.site_name ?? ''}</span></span>
            <span className="text-xs text-muted-foreground">{rateWords(m) ?? 'no rate'} · this month {hrs(m.month.worked)}</span>
          </span>
          <StateChip state={m.state} className="hidden sm:inline-flex" />
          {m.month.hire_cost && Number(m.month.hire_cost) > 0 && <span className="shrink-0 font-semibold tabular-nums">{inr(m.month.hire_cost)}</span>}
        </Link>
      ))}
    </section>
  )
}
