import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Construction } from 'lucide-react'
import { useModuleEnabled } from '@/lib/modules'
import { fetchLogs, hrs } from '@/lib/equipment'
import { DayBar } from './parts'

// NXT-11: the site's machines on this day, beside its DPR (the same figures the DPR's Machinery section prints), and
// the machines at the site not logged yet, with a way to log them.

export function SiteDayMachines({ siteId, date }: { siteId: string; date: string }) {
  const enabled = useModuleEnabled()('equipment')
  const { data } = useQuery({ queryKey: ['equipment', 'logs', date, null, siteId], queryFn: () => fetchLogs({ date, site_id: siteId }), enabled, retry: false })
  if (!enabled || !data || (!data.items.length && !data.missing.length)) return null
  return (
    <section className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-2">
        <h3 className="flex items-center gap-2 text-sm font-semibold"><Construction className="size-4 text-muted-foreground" /> Machines</h3>
        <span className="text-sm font-semibold tabular-nums">{hrs(data.totals.worked)}{Number(data.totals.fuel_litres) ? ` · ${Number(data.totals.fuel_litres)} L` : ''}</span>
      </div>
      <ul className="flex flex-col divide-y rounded-lg border">
        {data.items.map((l) => (
          <li key={l.id}>
            <Link to={`/equipment/${l.equipment_id}`} className="flex flex-col gap-1 px-3 py-2 text-sm transition hover:bg-muted/40">
              <span className="flex items-center justify-between gap-2">
                <span className="truncate font-medium">{l.machine}</span>
                <span className="shrink-0 text-xs text-muted-foreground tabular-nums">{hrs(l.worked_hours)}{Number(l.breakdown_hours) ? ` · ${hrs(l.breakdown_hours)} broken` : ''}{l.fuel_litres ? ` · ${Number(l.fuel_litres)} L` : ''}</span>
              </span>
              <DayBar worked={l.worked_hours} idle={l.idle_hours} breakdown={l.breakdown_hours} />
            </Link>
          </li>
        ))}
        {data.missing.map((m) => (
          <li key={m.id} className="flex items-center justify-between gap-2 px-3 py-2 text-sm text-muted-foreground">
            <span className="truncate">{m.name}</span><span className="text-xs">not logged</span>
          </li>
        ))}
      </ul>
      {data.missing.length > 0 && <Link to={`/equipment/log?date=${date}`} className="text-xs font-medium text-primary hover:underline">Log the machines for this day →</Link>}
    </section>
  )
}
