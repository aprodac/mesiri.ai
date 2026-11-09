import * as React from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, ArrowLeft, CheckCircle2, ClipboardList, Download, ReceiptText, Scale } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { HireBillDialog } from '@/components/equipment/actions'
import { usePageTitle } from '@/lib/page-title'
import { useUrlState } from '@/lib/url-state'
import { useReadOnly } from '@/lib/trial'
import { exportCsv } from '@/lib/export'
import { cn } from '@/lib/utils'
import { RATE_WORDS, fetchHireCheck, hrs, iso, type HireCheckRow, inr } from '@/lib/equipment'
import { ModuleTitle } from '@/components/page/page-kit'

// NXT-13: Equipment > Hire check. "The bill says 8 hours a day; how many did it work?" Per hired machine in the period:
// the hours recorded on site, what they come to at the agreed rate (with the hire's minimum hours, never the breakdown),
// the bills and whether one asks for more. Over first.

const STATE: Record<HireCheckRow['state'], { label: string; chip: string }> = {
  over: { label: 'Bill is more', chip: 'bg-red-100 text-red-900 dark:bg-red-950 dark:text-red-100' },
  unbilled: { label: 'Not billed yet', chip: 'bg-sky-100 text-sky-900 dark:bg-sky-950 dark:text-sky-100' },
  check: { label: 'Check', chip: 'bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-100' },
  no_bill: { label: 'No bill', chip: 'bg-slate-100 text-slate-800 dark:bg-slate-800 dark:text-slate-100' },
  ok: { label: 'Matches', chip: 'bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-100' },
}

function monthRange(offset: number): [string, string, string] {
  const now = new Date()
  const first = new Date(now.getFullYear(), now.getMonth() + offset, 1)
  const last = offset === 0 ? now : new Date(now.getFullYear(), now.getMonth() + offset + 1, 0)
  return [iso(first), iso(last), first.toLocaleDateString('en-IN', { month: 'long', year: offset ? 'numeric' : undefined })]
}

export default function HireCheckPage() {
  usePageTitle('Hire check')
  const readOnly = useReadOnly()
  const [offset, setOffset] = useUrlState<string>('month', '0')
  const [from, to, label] = monthRange(Number(offset) || 0)
  const [billFor, setBillFor] = React.useState<HireCheckRow | null>(null)
  const { data, isLoading, isError } = useQuery({ queryKey: ['equipment', 'hire-check', from, to], queryFn: () => fetchHireCheck({ date_from: from, date_to: to }) })
  const items = data?.items ?? []

  const exportIt = () => exportCsv(`hire-check-${from}.csv`,
    ['Machine', 'Hire company', 'Rate', 'Per', 'Min h/day', 'Site', 'Worked (h)', 'Idle (h)', 'Breakdown (h)', 'Days on site', 'Chargeable (h)', 'Comes to', 'Billed', 'Not billed', 'Check'],
    items.map((r) => [r.name, r.vendor_name ?? '', r.rate ?? '', r.rate_unit ?? '', r.min_hours_per_day ?? '', r.site_name ?? '', Number(r.worked), Number(r.idle), Number(r.breakdown),
      r.days_on_site, Number(r.charged_hours), r.expected, r.billed, r.unbilled, STATE[r.state].label]))

  return (
    <div className="mx-auto flex w-full flex-col gap-4 pb-24 sm:px-2 md:pb-8">
      <Link to="/equipment" className="inline-flex w-fit items-center gap-1 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="size-4" />Machines</Link>
      <header className="flex flex-wrap items-center justify-between gap-3">
        <ModuleTitle icon={Scale} title="Hire check" />
        <div className="flex items-center gap-2">
          <div role="tablist" aria-label="Month" className="flex gap-0.5 rounded-xl bg-muted p-1">
            {[-2, -1, 0].map((o) => (
              <button key={o} role="tab" type="button" aria-selected={Number(offset) === o} onClick={() => setOffset(String(o))}
                className={cn('h-8 rounded-lg px-3 text-sm', Number(offset) === o ? 'bg-background font-semibold shadow-sm' : 'text-foreground/75')}>{monthRange(o)[2]}</button>
            ))}
          </div>
          <Button variant="outline" className="gap-2" disabled={!items.length} onClick={exportIt}><Download className="size-4" /><span className="hidden sm:inline">Export</span></Button>
        </div>
      </header>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {[
          { label: 'Hours recorded come to', value: inr(data?.totals.expected ?? 0), icon: ClipboardList, tone: 'bg-muted' },
          { label: 'Billed', value: inr(data?.totals.billed ?? 0), icon: ReceiptText, tone: 'bg-muted' },
          { label: 'Earned, not billed yet', value: inr(data?.totals.unbilled ?? 0), icon: CheckCircle2, tone: 'bg-sky-100 text-sky-900 dark:bg-sky-950 dark:text-sky-100' },
          { label: 'Bills asking for more', value: String(data?.totals.over ?? 0), icon: AlertTriangle, tone: data?.totals.over ? 'bg-destructive text-white' : 'bg-muted' },
        ].map((k) => (
          <div key={k.label} className="flex items-center gap-3 rounded-xl border bg-card p-3">
            <span className={cn('inline-flex size-10 shrink-0 items-center justify-center rounded-lg', k.tone)}><k.icon className="size-5" /></span>
            <span className="flex flex-col"><span className="text-xl leading-tight font-semibold tabular-nums">{isLoading ? '–' : k.value}</span><span className="text-xs text-muted-foreground">{k.label}</span></span>
          </div>
        ))}
      </div>

      <section aria-label={`Hired machines, ${label}`} className="overflow-hidden rounded-xl border">
        {isLoading && <div className="h-32 animate-pulse bg-muted/40" />}
        {isError && <p className="p-6 text-sm text-destructive">The hire check did not load (it is for the roles that see spending).</p>}
        {data && items.length === 0 && <p className="p-8 text-center text-sm text-muted-foreground">No hired machine in {label}. A machine added as hired, with its rate, shows here with its hours.</p>}
        {items.map((r) => (
          <div key={r.id} className="flex flex-col gap-2 border-b px-4 py-3 last:border-b-0">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="min-w-0">
                <Link to={`/equipment/${r.id}`} className="font-semibold hover:underline">{r.name}</Link>
                <span className="ml-2 text-sm text-muted-foreground">{r.vendor_name ?? 'no hire company'}{r.site_name ? ` · ${r.site_name}` : ''}</span>
              </span>
              <span className={cn('rounded-full px-2 py-0.5 text-xs font-semibold', STATE[r.state].chip)}>{STATE[r.state].label}</span>
            </div>
            <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm tabular-nums sm:grid-cols-5">
              <span><span className="text-muted-foreground">Rate </span>{r.rate ? `₹${Number(r.rate).toLocaleString('en-IN')} ${RATE_WORDS[r.rate_unit ?? 'hour']}` : '–'}{r.min_hours_per_day ? `, min ${Number(r.min_hours_per_day)} h` : ''}</span>
              <span><span className="text-muted-foreground">Worked </span>{hrs(r.worked)}<span className="text-muted-foreground"> in {r.days_on_site} days</span></span>
              <span><span className="text-muted-foreground">Idle / broken </span>{hrs(r.idle)} / {hrs(r.breakdown)}</span>
              <span><span className="text-muted-foreground">Comes to </span><strong>{inr(r.expected)}</strong></span>
              <span><span className="text-muted-foreground">Billed </span><strong>{inr(r.billed)}</strong></span>
            </div>
            {r.bills.map((b) => b.check && (
              <div key={b.id} className={cn('rounded-lg px-3 py-2 text-xs', b.check.status === 'over' ? 'bg-red-50 dark:bg-red-950/40' : 'bg-muted/50')}>
                <span className="font-semibold">{b.bill_ref ?? 'Bill'} {b.period_from} – {b.period_to}: {inr(b.amount)}</span>
                {b.check.flags.length ? b.check.flags.map((f) => <span key={f} className="block text-muted-foreground">• {f}</span>) : <span className="ml-2 text-emerald-700 dark:text-emerald-300">matches the hours recorded</span>}
              </div>
            ))}
            {!readOnly && <Button size="sm" variant="outline" className="w-fit gap-1.5" onClick={() => setBillFor(r)}><ReceiptText className="size-4" />Enter a bill</Button>}
          </div>
        ))}
      </section>
      <p className="text-xs text-muted-foreground">Per hour: the hours worked, or the hire's minimum hours on a day it stood on site; breakdown hours are never charged. Per day: each day on site. Per month: the rate ÷ 30 for each day on hire. Pay a bill from the hire company's page in Finance › Suppliers.</p>
      <HireBillDialog machine={billFor ? { id: billFor.id, name: billFor.name, vendor_name: billFor.vendor_name, rate_unit: billFor.rate_unit } : null} open={!!billFor} onOpenChange={(o) => !o && setBillFor(null)} />
    </div>
  )
}
