import * as React from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowUpRight, BookOpenCheck, CalendarRange, FileSpreadsheet, History, Lock } from 'lucide-react'
import { Segmented } from '@/components/dpr-page'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { useToast } from '@/components/ui/toast-notification'
import {
  PRESET_LABEL,
  VOUCHER_LABEL,
  cell,
  downloadAccountsExcel,
  fetchEntry,
  formatDay,
  mayReadBooks,
  presetPeriod,
  rupees,
  sourceLink,
  type Period,
  type PresetKey,
} from '@/lib/accounts'
import { useAuth } from '@/lib/AuthContext'
import { downloadBlob } from '@/lib/export'
import { useModuleEnabled } from '@/lib/modules'
import { apiErrorMessage } from '@/lib/logo-upload'
import { cn } from '@/lib/utils'

// ACC-05: what every Accounts page shares: the period (kept in the address, so a view can be sent to the CA), the
// row of Accounts pages, a voucher opened in a side sheet from any figure, and the Excel button.

const PRESETS: PresetKey[] = ['this_month', 'last_month', 'this_quarter', 'fy', 'last_fy', 'custom']

/** The period from the address (?range=fy or ?from=&to=), the year so far by default. */
export function usePeriod(fallback: Exclude<PresetKey, 'custom'> = 'fy') {
  const [params, setParams] = useSearchParams()
  const range = (params.get('range') as PresetKey | null) ?? (params.get('from') ? 'custom' : fallback)
  const period: Period =
    range === 'custom'
      ? { date_from: params.get('from') ?? presetPeriod(fallback).date_from, date_to: params.get('to') ?? presetPeriod(fallback).date_to }
      : presetPeriod(range)
  const set = (patch: Record<string, string | null>) =>
    setParams(
      (p) => {
        const next = new URLSearchParams(p)
        for (const [k, v] of Object.entries(patch)) {
          if (v === null) next.delete(k)
          else next.set(k, v)
        }
        return next
      },
      { replace: true },
    )
  return {
    range,
    period,
    setRange: (r: PresetKey) => (r === 'custom' ? set({ range: 'custom', from: period.date_from, to: period.date_to }) : set({ range: r, from: null, to: null })),
    setDates: (p: Period) => set({ range: 'custom', from: p.date_from, to: p.date_to }),
  }
}

export function PeriodBar({ state }: { state: ReturnType<typeof usePeriod> }) {
  return (
    <div className="flex min-w-0 max-w-full flex-wrap items-center gap-2">
      <Segmented<PresetKey> label="Period" value={state.range} options={PRESETS.map((p) => ({ value: p, label: PRESET_LABEL[p] }))} onChange={state.setRange} />
      {state.range === 'custom' ? (
        <div className="flex items-center gap-1.5 text-sm">
          <Input type="date" aria-label="From" value={state.period.date_from} max={state.period.date_to} onChange={(e) => e.target.value && state.setDates({ ...state.period, date_from: e.target.value })} className="h-8 w-[150px] dark:[color-scheme:dark]" />
          <span className="text-muted-foreground">to</span>
          <Input type="date" aria-label="To" value={state.period.date_to} min={state.period.date_from} onChange={(e) => e.target.value && state.setDates({ ...state.period, date_to: e.target.value })} className="h-8 w-[150px] dark:[color-scheme:dark]" />
        </div>
      ) : (
        <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
          <CalendarRange className="size-3.5" /> {formatDay(state.period.date_from)} – {formatDay(state.period.date_to)}
        </span>
      )}
    </div>
  )
}

const PAGES = [
  { to: '/accounts', label: 'Home' },
  { to: '/accounts/pl', label: 'Profit & loss' },
  { to: '/accounts/balance-sheet', label: 'Balance sheet' },
  { to: '/accounts/cash-bank', label: 'Cash & bank' },
  { to: '/accounts/projects', label: 'Projects' },
  { to: '/accounts/gst', label: 'GST' },
  { to: '/accounts/tds', label: 'TDS' },
  { to: '/accounts/trial-balance', label: 'Trial balance' },
  { to: '/accounts/day-book', label: 'Day book' },
  { to: '/accounts/ledgers', label: 'Ledgers' },
  { to: '/accounts/chart', label: 'Chart of accounts' },
  { to: '/accounts/periods', label: 'Months' },
]

/** The Accounts pages in one row, keeping the period and scope as you move between them. */
export function BooksTabs({ current }: { current: string }) {
  const [params] = useSearchParams()
  const keep = new URLSearchParams()
  for (const k of ['range', 'from', 'to', 'project', 'site']) {
    const v = params.get(k)
    if (v) keep.set(k, v)
  }
  const qs = keep.toString()
  return (
    <nav aria-label="Accounts" className="-mx-1 flex gap-1 overflow-x-auto px-1">
      {PAGES.map((p) => (
        <Link
          key={p.to}
          to={`${p.to}${qs ? `?${qs}` : ''}`}
          aria-current={current === p.to ? 'page' : undefined}
          className={cn(
            'shrink-0 rounded-md px-2.5 py-1 text-sm',
            current === p.to ? 'bg-muted font-medium text-foreground' : 'text-muted-foreground hover:text-foreground',
          )}
        >
          {p.label}
        </Link>
      ))}
    </nav>
  )
}

export function ExcelButton({ path, params, name }: { path: string; params: object; name: string }) {
  const toast = useToast()
  const [busy, setBusy] = React.useState(false)
  const run = async () => {
    setBusy(true)
    try {
      const { blob, filename } = await downloadAccountsExcel(path, params, name)
      downloadBlob(filename, blob)
    } catch (err) {
      toast.error('Could not make the Excel file', apiErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }
  return (
    <Button size="sm" variant="outline" className="gap-1.5" onClick={run} disabled={busy}>
      <FileSpreadsheet className="size-3.5" /> {busy ? 'Preparing…' : 'Excel'}
    </Button>
  )
}

/** Not for this role: the books are the owner's, an admin's and finance's. */
export function BooksClosed() {
  return (
    <div className="mx-auto flex w-full max-w-md flex-col items-center gap-3 py-16 text-center">
      <BookOpenCheck className="size-6 text-muted-foreground" />
      <p className="font-medium">The books show the company's money: every ledger and balance.</p>
      <p className="text-sm text-muted-foreground">Only the owner, an admin or finance can open them.</p>
    </div>
  )
}

/** A voucher in a side sheet: its lines, where it came from, and each ledger's statement one tap away. */
export function VoucherSheet({ entryId, onClose }: { entryId: string | null; onClose: () => void }) {
  const q = useQuery({ queryKey: ['accounts', 'entry', entryId], queryFn: () => fetchEntry(entryId!), enabled: !!entryId })
  const e = q.data
  const from = e ? sourceLink(e.source) : null
  const where = e ? [...new Set(e.lines.flatMap((l) => [l.project, l.site].filter(Boolean)))] : []
  return (
    <Sheet open={!!entryId} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="right" className="w-full gap-0 overflow-y-auto sm:max-w-lg">
        <SheetHeader className="border-b">
          <SheetTitle className="flex flex-wrap items-center gap-2">
            {e ? `${VOUCHER_LABEL[e.voucher_type]} ${e.ref}` : 'Voucher'}
            {e?.after_close && (
              <span className="inline-flex items-center gap-1 rounded-full bg-draft-soft px-2 py-0.5 text-xs font-medium text-draft">
                <History className="size-3" /> Changed after close
              </span>
            )}
          </SheetTitle>
          <SheetDescription>{e ? `${formatDay(e.date)} · ${rupees(e.amount)}` : 'Loading…'}</SheetDescription>
        </SheetHeader>
        {q.isLoading || !e ? (
          <div className="p-4">
            <Skeleton className="h-40 rounded-lg" />
          </div>
        ) : (
          <div className="flex flex-col gap-4 p-4">
            {e.narration && <p className="text-sm">{e.narration}</p>}
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-xs text-muted-foreground">
                  <th className="py-1.5 text-left font-medium">Ledger</th>
                  <th className="py-1.5 text-right font-medium">Debit</th>
                  <th className="py-1.5 text-right font-medium">Credit</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {e.lines.map((l, i) => (
                  <tr key={i} className="align-top">
                    <td className={cn('py-2 pr-2', Number(l.credit) > 0 && 'pl-4')}>
                      <Link to={`/accounts/ledgers/${l.ledger_id}`} className="font-medium hover:underline" onClick={onClose}>
                        {Number(l.credit) > 0 ? 'To ' : ''}
                        {l.ledger}
                      </Link>
                      {(l.cost_centre || l.site) && (
                        <p className="text-xs text-muted-foreground">{[l.site, l.cost_centre].filter(Boolean).join(' · ')}</p>
                      )}
                    </td>
                    <td className="py-2 text-right tabular-nums">{cell(l.debit)}</td>
                    <td className="py-2 text-right tabular-nums">{cell(l.credit)}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="border-t font-semibold">
                  <td className="py-2">Total</td>
                  <td className="py-2 text-right tabular-nums">{rupees(e.amount)}</td>
                  <td className="py-2 text-right tabular-nums">{rupees(e.amount)}</td>
                </tr>
              </tfoot>
            </table>
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
              <dt className="text-muted-foreground">Project</dt>
              <dd>{where.length ? where.join(' · ') : 'Head office (no project)'}</dd>
              <dt className="text-muted-foreground">Year</dt>
              <dd>{e.financial_year}</dd>
              <dt className="text-muted-foreground">Posted</dt>
              <dd>Automatically from the record, {formatDay(e.posted_at)}</dd>
            </dl>
            {e.after_close && (
              <p className="flex gap-2 rounded-lg border bg-draft-soft/40 px-3 py-2 text-xs text-muted-foreground">
                <Lock className="mt-0.5 size-3.5 shrink-0" />
                Its record changed after its month was closed. The closed month keeps what it had; this voucher carries the difference.
              </p>
            )}
            {from && (
              <Button asChild variant="outline" size="sm" className="w-fit gap-1.5">
                <Link to={from.to} onClick={onClose}>
                  {from.label} <ArrowUpRight className="size-3.5" />
                </Link>
              </Button>
            )}
          </div>
        )}
      </SheetContent>
    </Sheet>
  )
}

/** "In the books" from a module page (a supplier, Money, Receivables): shown only when Accounts is on and the
 * person may read the books. */
export function BooksLink({ to, label = 'In the books', className }: { to: string; label?: string; className?: string }) {
  const { me } = useAuth()
  const enabled = useModuleEnabled()
  if (!enabled('accounts') || !mayReadBooks(me?.role)) return null
  return (
    <Button asChild variant="ghost" size="sm" className={cn('gap-1.5', className)}>
      <Link to={to}>
        <BookOpenCheck className="size-4" /> {label}
      </Link>
    </Button>
  )
}
