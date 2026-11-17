import * as React from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowRight, ArrowUpRight, BookOpenCheck, CalendarDays, CalendarRange, CheckCircle2, FolderKanban, History, Lock, PenLine, Sparkles } from 'lucide-react'
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
  mayReopen,
  reverseVoucher,
  presetPeriod,
  rupees,
  sourceLink,
  type EntryLine,
  type Period,
  type PresetKey,
  type VoucherType,
} from '@/lib/accounts'
import { VOUCHER_LOOK } from '@/components/accounts/visuals'
import { useAuth } from '@/lib/AuthContext'
import { downloadBlob } from '@/lib/export'
import { useModuleEnabled } from '@/lib/modules'
import { apiErrorMessage } from '@/lib/logo-upload'
import { cn } from '@/lib/utils'
import { NewVoucherDialog } from './new-voucher-dialog'
import { ActionIcon } from '@/components/page/action-button'

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
    <div className="flex min-w-0 max-w-full flex-wrap items-center gap-2" data-guide="books.period">
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
    <nav aria-label="Accounts" className="-mx-1 flex gap-1 overflow-x-auto px-1" data-guide="books.tabs">
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
    <Button size="sm" variant="outline" className="gap-1.5" onClick={run} disabled={busy} data-guide="books.excel">
      <ActionIcon kind="export-excel" className="size-3.5" /> {busy ? 'Preparing…' : 'Excel'}
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

/** UX-32: each kind of voucher keeps one colour on the sheet's band and amount (the chips in visuals.tsx). */
const VOUCHER_TONE: Record<VoucherType, { band: string; bar: string; fg: string }> = {
  receipt: { band: 'bg-emerald-500/[0.07]', bar: 'before:bg-emerald-500', fg: 'text-emerald-700 dark:text-emerald-400' },
  payment: { band: 'bg-rose-500/[0.07]', bar: 'before:bg-rose-500', fg: 'text-rose-700 dark:text-rose-400' },
  purchase: { band: 'bg-amber-500/[0.08]', bar: 'before:bg-amber-500', fg: 'text-amber-800 dark:text-amber-400' },
  sales: { band: 'bg-sky-500/[0.07]', bar: 'before:bg-sky-500', fg: 'text-sky-700 dark:text-sky-400' },
  contra: { band: 'bg-violet-500/[0.07]', bar: 'before:bg-violet-500', fg: 'text-violet-700 dark:text-violet-400' },
  journal: { band: 'bg-muted/50', bar: 'before:bg-muted-foreground/40', fg: 'text-foreground' },
}

/** The two sides of a voucher in plain words: debit (where it is booked) and credit (where it came from). */
const SIDE_WORDS: Record<VoucherType, { dr: string; cr: string }> = {
  purchase: { dr: 'Booked as', cr: 'Owed to' },
  payment: { dr: 'Paid to', cr: 'Paid from' },
  receipt: { dr: 'Received into', cr: 'Received from' },
  sales: { dr: 'Billed to', cr: 'Booked as' },
  contra: { dr: 'Moved into', cr: 'Moved from' },
  journal: { dr: 'Debit', cr: 'Credit' },
}

/** A voucher in a side sheet: its lines, where it came from, and each ledger's statement one tap away. */
export function VoucherSheet({ entryId, onClose, onOpen }: { entryId: string | null; onClose: () => void; onOpen?: (id: string) => void }) {
  const q = useQuery({ queryKey: ['accounts', 'entry', entryId], queryFn: () => fetchEntry(entryId!), enabled: !!entryId })
  const e = q.data
  const { me } = useAuth()
  const toast = useToast()
  const queryClient = useQueryClient()
  // ACC-12: a manual voucher is never edited: reversed (with a reason), or corrected (reverse + new, owner / admin).
  const [reversing, setReversing] = React.useState(false)
  const [reason, setReason] = React.useState('')
  const [correcting, setCorrecting] = React.useState(false)
  const reverse = useMutation({
    mutationFn: () => reverseVoucher(e!.id, reason.trim()),
    onSuccess: (r) => {
      queryClient.invalidateQueries({ queryKey: ['accounts'] })
      setReversing(false)
      setReason('')
      toast.success(`Reversed by ${r.ref}`, r.after_close ? `Its month is closed, so the reversal is on ${formatDay(r.date)}.` : undefined)
    },
    onError: (err) => toast.error('Not reversed', apiErrorMessage(err)),
  })
  const mayChange = !!e?.manual && !e.reverses_id && !e.reversed_by_id && mayReadBooks(me?.role)
  const from = e ? sourceLink(e.source) : null
  const where = e ? [...new Set(e.lines.flatMap((l) => [l.project, l.site].filter(Boolean)))] : []
  const look = e ? VOUCHER_LOOK[e.voucher_type] : null
  const tone = e ? VOUCHER_TONE[e.voucher_type] : VOUCHER_TONE.journal
  const words = e ? SIDE_WORDS[e.voucher_type] : SIDE_WORDS.journal
  const debits = e ? e.lines.filter((l) => Number(l.debit) > 0) : []
  const credits = e ? e.lines.filter((l) => Number(l.credit) > 0) : []
  const balanced = e ? Math.abs(e.lines.reduce((t, l) => t + Number(l.debit) - Number(l.credit), 0)) < 0.005 : false
  const TypeIcon = look?.icon
  const side = (title: string, lines: EntryLine[], amountOf: (l: EntryLine) => string, cls: string, dot: string) => (
    <div className={cn('min-w-0 flex-1 rounded-xl border bg-card p-3 shadow-xs', cls)}>
      <p className="mb-1.5 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
        <span className={cn('size-1.5 rounded-full', dot)} /> {title}
      </p>
      <ul className="flex flex-col gap-1.5">
        {lines.map((l, i) => (
          <li key={i} className="min-w-0">
            <Link to={`/accounts/ledgers/${l.ledger_id}`} onClick={onClose} className="block truncate text-sm font-semibold hover:underline">
              {l.ledger}
            </Link>
            <span className="flex items-baseline justify-between gap-2">
              <span className="truncate text-xs text-muted-foreground">{[l.site, l.cost_centre].filter(Boolean).join(' · ')}</span>
              <span className="shrink-0 text-sm tabular-nums">{rupees(amountOf(l))}</span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
  return (
    <Sheet open={!!entryId} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="right" className="w-full gap-0 overflow-y-auto bg-background-bright sm:max-w-lg">
        <SheetHeader className={cn('relative gap-2 border-b px-5 pb-4 pt-5 before:absolute before:inset-x-0 before:top-0 before:h-1', tone.band, tone.bar)}>
          <div className="flex items-center gap-3 pr-8">
            <span className={cn('flex size-10 shrink-0 items-center justify-center rounded-xl', look ? look.chip : 'bg-muted')}>
              {TypeIcon ? <TypeIcon className="size-5" /> : null}
            </span>
            <div className="min-w-0">
              <SheetTitle className="flex flex-wrap items-center gap-2 text-base">
                {e ? `${VOUCHER_LABEL[e.voucher_type]} ${e.ref}` : 'Voucher'}
              </SheetTitle>
              <SheetDescription className="text-xs">{e ? `${formatDay(e.date)} · ${look?.word ?? ''}` : 'Loading…'}</SheetDescription>
            </div>
          </div>
          {e && (
            <>
              <p className={cn('text-3xl font-semibold tabular-nums tracking-tight', tone.fg)}>{rupees(e.amount)}</p>
              {e.narration && <p className="text-sm text-foreground/80">{e.narration}</p>}
              <div className="flex flex-wrap gap-1.5">
                <span className="inline-flex items-center gap-1 rounded-full border bg-card px-2 py-0.5 text-xs">
                  <FolderKanban className="size-3 text-muted-foreground" /> {where.length ? where.join(' · ') : 'Head office'}
                </span>
                <span className={cn('inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium', e.manual ? 'bg-info-soft text-info' : 'bg-success-soft text-success')}>
                  {e.manual ? <PenLine className="size-3" /> : <Sparkles className="size-3" />}
                  {e.manual ? `By hand${e.created_by_name ? `, ${e.created_by_name}` : ''}` : 'Posted from the record'}
                </span>
                {e.after_close && (
                  <span className="inline-flex items-center gap-1 rounded-full bg-draft-soft px-2 py-0.5 text-xs font-medium text-draft">
                    <History className="size-3" /> Changed after close
                  </span>
                )}
                {e.reversed_by_id && <span className="inline-flex items-center gap-1 rounded-full bg-destructive/10 px-2 py-0.5 text-xs font-medium text-destructive">Reversed</span>}
              </div>
            </>
          )}
        </SheetHeader>
        {q.isLoading || !e ? (
          <div className="p-5">
            <Skeleton className="h-40 rounded-xl" />
          </div>
        ) : (
          <div className="flex flex-col gap-4 p-5">
            {/* What happened, as a flow: where it came from (credit) -> where it is booked (debit) */}
            <div className="flex flex-col items-stretch gap-2 sm:flex-row sm:items-center">
              {side(words.cr, credits, (l) => l.credit, 'border-l-4 border-l-info/60', 'bg-info')}
              <ArrowRight className="mx-auto size-4 shrink-0 rotate-90 text-muted-foreground sm:rotate-0" aria-hidden="true" />
              {side(words.dr, debits, (l) => l.debit, 'border-l-4 border-l-draft/60', 'bg-draft')}
            </div>

            <div className="overflow-hidden rounded-xl border bg-card shadow-xs">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b bg-muted/50 text-xs text-muted-foreground">
                    <th className="px-3 py-2 text-left font-medium">Ledger</th>
                    <th className="px-3 py-2 text-right font-medium">Debit</th>
                    <th className="px-3 py-2 text-right font-medium">Credit</th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {e.lines.map((l, i) => (
                    <tr key={i} className="align-top">
                      <td className={cn('py-2 pl-3 pr-2', Number(l.credit) > 0 && 'pl-6')}>
                        <Link to={`/accounts/ledgers/${l.ledger_id}`} className="font-medium hover:underline" onClick={onClose}>
                          {Number(l.credit) > 0 ? 'To ' : ''}
                          {l.ledger}
                        </Link>
                        {(l.cost_centre || l.site) && <p className="text-xs text-muted-foreground">{[l.site, l.cost_centre].filter(Boolean).join(' · ')}</p>}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums text-draft">{cell(l.debit)}</td>
                      <td className="px-3 py-2 text-right tabular-nums text-info">{cell(l.credit)}</td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr className="border-t-[1.5px] border-foreground/25 bg-muted/30 font-semibold">
                    <td className="px-3 py-2">
                      <span className="flex items-center gap-2">
                        Total
                        {balanced && (
                          <span className="inline-flex items-center gap-1 rounded-full bg-success-soft px-1.5 py-px text-[10px] font-medium text-success">
                            <CheckCircle2 className="size-3" /> Balanced
                          </span>
                        )}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">{rupees(e.amount)}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{rupees(e.amount)}</td>
                  </tr>
                </tfoot>
              </table>
            </div>

            <dl className="grid grid-cols-2 gap-2 text-sm">
              <div className="rounded-xl border bg-card px-3 py-2">
                <dt className="flex items-center gap-1.5 text-[11px] text-muted-foreground"><CalendarDays className="size-3" /> Date</dt>
                <dd className="font-medium">{formatDay(e.date)}</dd>
              </div>
              <div className="rounded-xl border bg-card px-3 py-2">
                <dt className="flex items-center gap-1.5 text-[11px] text-muted-foreground"><BookOpenCheck className="size-3" /> Financial year</dt>
                <dd className="font-medium">{e.financial_year}</dd>
              </div>
              <div className="col-span-2 rounded-xl border bg-card px-3 py-2">
                <dt className="flex items-center gap-1.5 text-[11px] text-muted-foreground"><History className="size-3" /> Posted</dt>
                <dd>{e.manual ? `By hand${e.created_by_name ? `, ${e.created_by_name}` : ''}, ${formatDay(e.posted_at)}` : `Automatically from the record, ${formatDay(e.posted_at)}`}</dd>
              </div>
              {e.reverses_id && (
                <div className="col-span-2 rounded-xl border bg-card px-3 py-2">
                  <dt className="text-[11px] text-muted-foreground">Reverses</dt>
                  <dd><button type="button" className="underline-offset-2 hover:underline" onClick={() => onOpen?.(e.reverses_id!)}>the voucher it undoes</button>{e.reversal_reason ? ` · ${e.reversal_reason}` : ''}</dd>
                </div>
              )}
              {e.reversed_by_id && (
                <div className="col-span-2 rounded-xl border border-destructive/30 bg-destructive/[0.04] px-3 py-2">
                  <dt className="text-[11px] text-destructive">Reversed</dt>
                  <dd><button type="button" className="underline-offset-2 hover:underline" onClick={() => onOpen?.(e.reversed_by_id!)}>open the reversal</button></dd>
                </div>
              )}
            </dl>
            {e.after_close && (
              <p className="flex gap-2 rounded-xl border border-draft/30 bg-draft-soft/60 px-3 py-2 text-xs text-draft">
                <Lock className="mt-0.5 size-3.5 shrink-0" />
                Its record changed after its month was closed. The closed month keeps what it had; this voucher carries the difference.
              </p>
            )}
            {reversing && (
              <form className="flex flex-col gap-2 rounded-xl border bg-card p-3" onSubmit={(ev) => { ev.preventDefault(); if (reason.trim().length >= 3) reverse.mutate() }}>
                <label htmlFor="rev-reason" className="text-sm font-medium">Why is it reversed?</label>
                <Input id="rev-reason" autoFocus value={reason} maxLength={300} placeholder="Entered twice" onChange={(ev) => setReason(ev.target.value)} />
                <p className="text-xs text-muted-foreground">The mirror is posted and linked; this voucher stays as it is. A closed month's voucher is reversed on the first open day.</p>
                <div className="flex gap-2">
                  <Button type="submit" size="sm" disabled={reason.trim().length < 3 || reverse.isPending}>Reverse</Button>
                  <Button type="button" variant="ghost" size="sm" onClick={() => setReversing(false)}>Cancel</Button>
                </div>
              </form>
            )}
            <div className="flex flex-wrap gap-2">
              {from && (
                <Button asChild size="sm" className="gap-1.5">
                  <Link to={from.to} onClick={onClose}>
                    {from.label} <ArrowUpRight className="size-3.5" />
                  </Link>
                </Button>
              )}
              {mayChange && !reversing && (
                <>
                  <Button variant="outline" size="sm" className="gap-1.5" onClick={() => setReversing(true)}><ActionIcon kind="undo" className="size-3.5" /> Reverse</Button>
                  {mayReopen(me?.role) && <Button variant="outline" size="sm" className="gap-1.5" onClick={() => setCorrecting(true)}><PenLine className="size-3.5" /> Correct</Button>}
                </>
              )}
            </div>
          </div>
        )}
      </SheetContent>
      <NewVoucherDialog open={correcting} correcting={e} onClose={() => setCorrecting(false)} onSaved={(n) => onOpen?.(n.id)} />
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
