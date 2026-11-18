import * as React from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ChevronDown, ShieldCheck } from 'lucide-react'
import { rupees } from '@/lib/expenses'
import { cn } from '@/lib/utils'
import { fetchValue, n, woUrl } from '@/lib/subcontracts'

// The value of checking subcontract bills, made visible (8 Nov 2026): what was caught before anyone paid, what was
// stopped, what waits; how many bills passed first time; advance recovered by itself; retention held. Every figure is
// read from the bills (GET /subcontracts/value), never estimated.

export function ValueStrip({ projectId, className, compact }: { projectId?: string; className?: string; compact?: boolean }) {
  const [span, setSpan] = React.useState<'period' | 'all_time'>('period')
  // UX-63: elsewhere than Bills & checks it starts as one line; a tap opens the whole strip.
  const [open, setOpen] = React.useState(!compact)
  const q = useQuery({ queryKey: ['subcontracts', 'value', projectId ?? ''], queryFn: () => fetchValue({ project_id: projectId }), retry: false })
  if (!q.data) return null
  const v = q.data
  const f = v[span]
  if (!f.bills && span === 'period' && !v.all_time.bills) return null
  const month = new Date(`${v.date_from}T00:00:00`).toLocaleDateString('en-IN', { month: 'long' })
  const passedPct = f.bills ? Math.round(f.passed_first_time / f.bills * 100) : 0
  if (!open) {
    return (
      <button type="button" onClick={() => setOpen(true)} data-guide="sub.value"
        className={cn('inline-flex w-fit max-w-full items-center gap-2 rounded-full border border-emerald-200 bg-emerald-50 py-1 pr-3 pl-1 text-sm text-emerald-900 hover:bg-emerald-100 dark:border-emerald-900 dark:bg-emerald-950/50 dark:text-emerald-200', className)}>
        <span className="inline-flex size-6 items-center justify-center rounded-full bg-emerald-600 text-white"><ShieldCheck className="size-3.5" /></span>
        <span className="truncate"><strong className="tabular-nums">{rupees(n(f.caught))}</strong> over-billing caught · {span === 'period' ? month : 'since the start'}{n(f.waiting) ? <span className="text-draft"> · {rupees(n(f.waiting))} waiting</span> : null}</span>
        <ChevronDown className="size-4 shrink-0" />
      </button>
    )
  }
  const cells = [
    { label: 'Stopped (bills rejected)', value: rupees(n(f.stopped)), tone: 'text-emerald-700 dark:text-emerald-300' },
    { label: 'Accepted with a reason', value: rupees(n(f.accepted)) },
    { label: 'Waiting for your check', value: rupees(n(f.waiting)), tone: n(f.waiting) ? 'text-draft' : '' },
    { label: 'Bills checked', value: `${f.bills}`, sub: `${passedPct}% passed first time` },
    { label: 'Advance recovered by itself', value: rupees(n(f.advance_recovered)) },
    { label: 'Retention held', value: rupees(n(v.retention_held)) },
  ]
  return (
    <section className={cn('overflow-hidden rounded-2xl border border-emerald-200 bg-gradient-to-br from-emerald-50 to-white dark:border-emerald-900 dark:from-emerald-950/50 dark:to-background', className)} aria-label="Money protected" data-guide="sub.value">
      <div className="flex flex-wrap items-center gap-4 p-4">
        <span className="inline-flex size-12 items-center justify-center rounded-2xl bg-emerald-600 text-white"><ShieldCheck className="size-6" /></span>
        <div className="min-w-0 flex-1">
          <div className="text-sm font-medium text-emerald-900 dark:text-emerald-200">Over-billing caught before payment · {span === 'period' ? month : 'since the start'}</div>
          <div className="text-3xl leading-tight font-bold tracking-tight text-emerald-800 tabular-nums dark:text-emerald-200">{rupees(n(f.caught))}</div>
          <div className="text-xs text-emerald-900/70 dark:text-emerald-200/70">on {f.flagged} of {f.bills} bills</div>
        </div>
        <div role="tablist" className="flex gap-0.5 rounded-lg bg-white/70 p-0.5 text-xs dark:bg-background/40">
          {(['period', 'all_time'] as const).map((s) => (
            <button key={s} role="tab" type="button" aria-selected={span === s} onClick={() => setSpan(s)} className={cn('h-7 rounded-md px-2.5', span === s ? 'bg-emerald-600 font-semibold text-white' : 'text-emerald-900 dark:text-emerald-200')}>
              {s === 'period' ? month : 'Since start'}
            </button>
          ))}
        </div>
      </div>
      <dl className="grid grid-cols-2 gap-px border-t border-emerald-200 bg-emerald-200 sm:grid-cols-3 lg:grid-cols-6 dark:border-emerald-900 dark:bg-emerald-900">
        {cells.map((c) => (
          <div key={c.label} className="bg-white/90 px-3 py-2 dark:bg-background/80">
            <dt className="text-[11px] text-muted-foreground">{c.label}</dt>
            <dd className={cn('text-base font-semibold tabular-nums', c.tone)}>{c.value}</dd>
            {c.sub && <dd className="text-[11px] text-muted-foreground">{c.sub}</dd>}
          </div>
        ))}
      </dl>
      {v.examples.length > 0 && span === 'period' && (
        <ul className="grid gap-1 border-t border-emerald-200 px-4 py-2 text-sm dark:border-emerald-900">
          {v.examples.map((e) => (
            <li key={e.bill_id} className="flex flex-wrap items-center gap-x-2">
              <Link to={woUrl(e.work_order_id, 'bills')} className="font-medium hover:underline">{e.vendor} · {e.ref}</Link>
              <span className="text-muted-foreground">asked {rupees(n(e.gross))}: {e.why}</span>
              <span className={cn('ml-auto font-semibold tabular-nums', e.status === 'rejected' ? 'text-emerald-700 dark:text-emerald-300' : e.status === 'approved' ? 'text-muted-foreground' : 'text-draft')}>
                {e.status === 'rejected' ? `${rupees(n(e.caught))} stopped` : e.status === 'approved' ? `${rupees(n(e.caught))} accepted` : `${rupees(n(e.caught))} held`}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
