// UX-95: a BOQ line opens its entries. From Budget vs actual (and Green / red) the owner goes down from a figure to the
// line and from the line to what made it: the work counted on it and the labour put on it, each with its day and site,
// linked to that site's day report (where the message that recorded it is). No new API: the BOQ's work list and the
// project's labour by day already say which line each went to.
import { useQuery } from '@tanstack/react-query'
import { HardHat, Ruler } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { api } from '@/lib/api'
import type { BoqWork } from '@/lib/boq'
import { formatQuantity, formatRupees } from '@/lib/boq'
import { appNow } from '@/lib/clock'
import { fetchProjectLabour } from '@/lib/cost'
import { cn } from '@/lib/utils'

export interface LineForDetail {
  id: string
  boq_code?: string | null
  work: string
  unit?: string | null
  planned_quantity?: string | null
  done_quantity?: string | null
  earned_labour?: string | null
  labour_cost?: string | null
  labour_man_days?: string | null
  labour_difference?: string | null
}

const iso = (d: Date) => d.toISOString().slice(0, 10)
const day = (d: string) => new Date(`${d}T12:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })
const dayReport = (date: string, siteId: string | null) => (siteId ? `/reports/${date}/sites/${siteId}` : null)

export function LineDetailSheet({ projectId, line, onOpenChange }: {
  projectId: string
  line: LineForDetail | null
  onOpenChange: (open: boolean) => void
}) {
  const open = !!line
  const work = useQuery({
    queryKey: ['boq-work', projectId, 'all'],
    queryFn: async () => (await api.get<{ work: BoqWork[] }>(`/projects/${projectId}/boq/work`, { params: { limit: 500 } })).data.work,
    enabled: open,
    staleTime: 60_000,
  })
  const today = appNow()
  const labour = useQuery({
    queryKey: ['cost-labour', projectId, 'line-detail'],
    queryFn: () => fetchProjectLabour(projectId, { date_from: iso(new Date(today.getTime() - 365 * 86400000)), date_to: iso(today) }),
    enabled: open,
    staleTime: 60_000,
  })
  const mine = (work.data ?? []).filter((w) => line && w.line_id === line.id)
  const crews = (labour.data?.groups ?? []).flatMap((g) => g.on_lines.filter((p) => line && p.line_id === line.id).map((p) => ({ g, p })))
  const gap = line?.labour_difference != null ? Number(line.labour_difference) : null
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full gap-0 overflow-y-auto p-0 sm:max-w-[480px]" data-guide="line.detail">
        {line && (
          <>
            <SheetHeader className="border-b px-5 py-4">
              <SheetTitle className="flex items-baseline gap-2 text-lg">
                {line.boq_code && <span className="rounded bg-muted px-1.5 text-xs font-medium text-muted-foreground tabular-nums">{line.boq_code}</span>}
                {line.work}
              </SheetTitle>
              <SheetDescription>Where this line's figures come from: every piece of work counted on it, every day's labour put on it.</SheetDescription>
            </SheetHeader>
            <dl className="grid grid-cols-2 gap-x-4 gap-y-2 border-b px-5 py-4 text-sm sm:grid-cols-4" data-guide="line.figures">
              <div><dt className="text-xs text-muted-foreground">Done</dt><dd className="font-semibold tabular-nums">{formatQuantity(line.done_quantity ?? '0')} / {formatQuantity(line.planned_quantity ?? '0')} {line.unit}</dd></div>
              <div><dt className="text-xs text-muted-foreground">Labour earned</dt><dd className="font-semibold tabular-nums text-info">{line.earned_labour ? formatRupees(line.earned_labour) : '—'}</dd></div>
              <div><dt className="text-xs text-muted-foreground">Labour spent</dt><dd className="font-semibold tabular-nums">{line.labour_cost ? formatRupees(line.labour_cost) : '—'}</dd></div>
              <div><dt className="text-xs text-muted-foreground">Gap</dt>
                <dd className={cn('font-semibold tabular-nums', gap !== null && (gap < 0 ? 'text-destructive' : 'text-success'))}>
                  {gap === null ? '—' : `${gap < 0 ? '−' : '+'}${formatRupees(String(Math.abs(gap)))}`}
                </dd></div>
            </dl>
            <section className="border-b px-5 py-4" data-guide="line.work">
              <h3 className="mb-2 flex items-center gap-1.5 text-sm font-semibold"><Ruler className="size-4" aria-hidden />Work counted on it <span className="font-normal text-muted-foreground">{mine.length}</span></h3>
              {work.isLoading ? <p className="text-sm text-muted-foreground">Loading…</p> : mine.length === 0 ? (
                <p className="text-sm text-muted-foreground">No work on this line yet.</p>
              ) : (
                <ul className="divide-y text-sm">
                  {mine.map((w) => {
                    const to = dayReport(w.date, w.site_id)
                    const row = (
                      <span className="flex items-baseline justify-between gap-3 py-1.5">
                        <span className="min-w-0"><span className="tabular-nums text-muted-foreground">{day(w.date)}</span> · {w.site_name ?? 'no site'}{w.work ? <span className="block truncate text-xs text-muted-foreground">{w.work}</span> : null}</span>
                        <span className="shrink-0 font-medium tabular-nums">{formatQuantity(w.quantity)} {w.unit}</span>
                      </span>
                    )
                    return <li key={w.id}>{to ? <Link to={to} className="block rounded hover:bg-muted/50" title="The site's day report: who sent it">{row}</Link> : row}</li>
                  })}
                </ul>
              )}
            </section>
            <section className="px-5 py-4" data-guide="line.labour">
              <h3 className="mb-2 flex items-center gap-1.5 text-sm font-semibold"><HardHat className="size-4" aria-hidden />Labour put on it <span className="font-normal text-muted-foreground">{crews.length} days · last 12 months</span></h3>
              {labour.isLoading ? <p className="text-sm text-muted-foreground">Loading…</p> : crews.length === 0 ? (
                <p className="text-sm text-muted-foreground">No labour on this line yet.</p>
              ) : (
                <ul className="divide-y text-sm">
                  {crews.map(({ g, p }) => {
                    const to = dayReport(g.date, g.site_id)
                    const row = (
                      <span className="flex items-baseline justify-between gap-3 py-1.5">
                        <span className="min-w-0"><span className="tabular-nums text-muted-foreground">{day(g.date)}</span> · {g.site_name ?? 'no site'} · {g.trade ?? 'crew'}{g.auto ? <span className="ml-1 text-xs text-muted-foreground">(from that day's work)</span> : null}</span>
                        <span className="shrink-0 text-right tabular-nums"><span className="font-medium">{p.cost ? formatRupees(p.cost) : 'no wage'}</span><span className="block text-xs text-muted-foreground">{formatQuantity(p.man_days)} md</span></span>
                      </span>
                    )
                    return <li key={`${g.date}-${g.site_id}-${g.trade_key}`}>{to ? <Link to={to} className="block rounded hover:bg-muted/50" title="The site's day report: who came">{row}</Link> : row}</li>
                  })}
                </ul>
              )}
            </section>
          </>
        )}
      </SheetContent>
    </Sheet>
  )
}
