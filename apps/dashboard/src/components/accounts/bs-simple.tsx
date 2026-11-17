import * as React from 'react'
import { BadgeCheck, Building2, ChevronRight, ChevronsDownUp, ChevronsUpDown, CircleAlert, HandCoins, Landmark, PiggyBank, Receipt, ScrollText, Shield, Truck, Wallet, type LucideIcon } from 'lucide-react'
import { VoucherSheet } from '@/components/accounts/books'
import { buckets, then, type Bucket, type BucketKey } from '@/components/accounts/bs-model'
import { Change } from '@/components/accounts/change-chip'
import { LedgerEntries } from '@/components/accounts/ledger-entries'
import { formatDay, rupees, type BalanceSheet } from '@/lib/accounts'
import { cn } from '@/lib/utils'

// UX-33 (asked 17 Nov 2026: "the balance sheet first, and the owner view if needed"): the owner's balance sheet.
// One card says what the company is worth (what it owns less what it owes), with two bars of the same length: what
// it owns, and what it owes plus its worth. Then "can you pay what is due?" in a sentence. Then each kind of thing
// owned or owed in plain words (cash and bank, clients owe you, you owe suppliers, taxes to pay ...), each opening to
// its accounts, an account to its entries this year, an entry to its voucher. Same GET /accounts/balance-sheet as the
// Tally view; the comparison is the same call for an earlier day.

const tiny = 0.005

const LOOK: Record<BucketKey, { icon: LucideIcon; bar: string; tile: string }> = {
  cash: { icon: Wallet, bar: 'bg-sky-500', tile: 'bg-sky-500/10 text-sky-700 dark:text-sky-400' },
  clients: { icon: Receipt, bar: 'bg-sky-400', tile: 'bg-sky-500/10 text-sky-700 dark:text-sky-400' },
  held: { icon: Shield, bar: 'bg-sky-300', tile: 'bg-sky-500/10 text-sky-700 dark:text-sky-400' },
  fixed: { icon: Truck, bar: 'bg-sky-700', tile: 'bg-sky-500/10 text-sky-700 dark:text-sky-400' },
  own_other: { icon: HandCoins, bar: 'bg-sky-200', tile: 'bg-sky-500/10 text-sky-700 dark:text-sky-400' },
  suppliers: { icon: Building2, bar: 'bg-amber-500', tile: 'bg-amber-500/10 text-amber-800 dark:text-amber-400' },
  taxes: { icon: Landmark, bar: 'bg-amber-400', tile: 'bg-amber-500/10 text-amber-800 dark:text-amber-400' },
  loans: { icon: ScrollText, bar: 'bg-amber-700', tile: 'bg-amber-500/10 text-amber-800 dark:text-amber-400' },
  owe_other: { icon: HandCoins, bar: 'bg-amber-300', tile: 'bg-amber-500/10 text-amber-800 dark:text-amber-400' },
  suspense: { icon: CircleAlert, bar: 'bg-draft', tile: 'bg-draft-soft text-draft' },
  worth: { icon: PiggyBank, bar: 'bg-violet-500', tile: 'bg-violet-500/10 text-violet-700 dark:text-violet-400' },
}
const SIDE_LOOK = {
  own: { title: 'What you own', fg: 'text-sky-700 dark:text-sky-400', dot: 'bg-sky-500' },
  owe: { title: 'What you owe', fg: 'text-amber-800 dark:text-amber-400', dot: 'bg-amber-500' },
  worth: { title: 'What is left is yours', fg: 'text-violet-700 dark:text-violet-400', dot: 'bg-violet-500' },
}

/** Owning more is good news, except more that clients owe (money stuck) and more to sort; owing more is not; worth more is. */
const goodWhenUp = (b: Bucket) => b.side !== 'owe' && b.key !== 'clients'

function useOpen() {
  const [open, setOpen] = React.useState<Set<string>>(new Set())
  const toggle = (id: string) =>
    setOpen((s) => {
      const next = new Set(s)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  return { open, setOpen, toggle }
}

function Bar({ parts, of, onPick }: { parts: { key: BucketKey; label: string; v: number }[]; of: number; onPick: (k: BucketKey) => void }) {
  return (
    <div className="flex h-3.5 w-full gap-0.5 overflow-hidden rounded-full bg-muted">
      {parts
        .filter((p) => p.v > tiny)
        .map((p) => (
          <button
            key={p.key}
            type="button"
            title={`${p.label}: ${rupees(p.v)}`}
            aria-label={`${p.label}: show what is in it`}
            onClick={() => onPick(p.key)}
            className={cn('h-full cursor-pointer transition-opacity first:rounded-l-full last:rounded-r-full hover:opacity-80', LOOK[p.key].bar)}
            style={{ width: `${(p.v / of) * 100}%` }}
          />
        ))}
    </div>
  )
}

export function BsSimple({ bs, prior, priorLabel }: { bs: BalanceSheet; prior: Map<string, number> | null; priorLabel?: string }) {
  const { open, setOpen, toggle } = useOpen()
  const [entry, setEntry] = React.useState<string | null>(null)
  const all = buckets(bs)
  const of = (k: BucketKey) => all.find((b) => b.key === k)?.amount ?? 0
  const own = all.filter((b) => b.side === 'own')
  const owe = all.filter((b) => b.side === 'owe')
  const ownTotal = Number(bs.total_assets)
  const oweTotal = owe.reduce((t, b) => t + b.amount, 0)
  const worth = of('worth')
  const worthBefore = then(prior, 'b:worth')
  const scale = Math.max(ownTotal, oweTotal + Math.max(0, worth), 1)
  // Can you pay what is due? Cash and what clients owe, against what is due soon (suppliers, taxes, other dues)
  const ready = of('cash') + of('clients')
  const dueSoon = of('suppliers') + of('taxes') + of('owe_other')
  const cover = dueSoon > tiny ? ready / dueSoon : null
  const period = { date_from: bs.year_start, date_to: bs.as_of }
  const keep = typeof window !== 'undefined' && window.location.search ? window.location.search : ''

  const focus = (k: BucketKey) => {
    setOpen((s) => new Set(s).add(k))
    window.setTimeout(() => document.getElementById(`bs-${k}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 50)
  }

  if (!bs.assets.length && !bs.liabilities.length) {
    return (
      <div data-guide="bs.stats">
        <p data-guide="bs.sides" className="rounded-xl border border-dashed bg-card px-4 py-6 text-sm text-muted-foreground">
          Nothing in the books on this day yet.
        </p>
      </div>
    )
  }

  const bucketBlock = (b: Bucket) => {
    const look = LOOK[b.key]
    const Icon = look.icon
    const isOpen = open.has(b.key)
    const before = then(prior, `b:${b.key}`)
    const single = b.lines.length === 1
    const ledgers = (line: Bucket['lines'][number], indent: string) =>
      line.ledgers.map((l) => {
        const id = `ledger:${l.ledger_id}`
        const lOpen = open.has(id)
        return (
          <React.Fragment key={l.ledger_id}>
            <button type="button" onClick={() => toggle(id)} aria-expanded={lOpen} className={cn('flex w-full items-center gap-3 border-t border-border/50 py-2 pr-4 text-left text-sm hover:bg-muted/40', indent)}>
              <ChevronRight className={cn('-ml-5 size-3.5 shrink-0 text-muted-foreground transition-transform', lOpen && 'rotate-90')} />
              <span className="min-w-0 flex-1 truncate">{l.name}</span>
              {prior && <Change now={l.amount} before={then(prior, `l:${l.ledger_id}`)} goodWhenUp={goodWhenUp(b)} className="hidden sm:inline-flex" />}
              <span className={cn('w-28 shrink-0 text-right tabular-nums sm:w-32', l.amount < -tiny && 'text-destructive')}>{l.amount < -tiny ? `(${rupees(l.amount)})` : rupees(l.amount)}</span>
            </button>
            {lOpen && (
              <LedgerEntries
                ledgerId={l.ledger_id}
                period={period}
                scope={{}}
                debitUp={b.side === 'own'}
                keep={keep}
                onEntry={setEntry}
                indent={indent}
                empty="No entries this year: the amount is from before the year began."
              />
            )}
          </React.Fragment>
        )
      })
    return (
      <div key={b.key} id={`bs-${b.key}`} className="scroll-mt-24 border-t first:border-t-0">
        <button type="button" onClick={() => toggle(b.key)} aria-expanded={isOpen} className={cn('flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-muted/40', isOpen && 'bg-muted/30')}>
          <span className={cn('flex size-8 shrink-0 items-center justify-center rounded-lg', look.tile)}>
            <Icon className="size-4" aria-hidden="true" />
          </span>
          <span className="min-w-0 flex-1">
            <span className="flex items-center gap-1.5">
              <span className="font-semibold">{b.label}</span>
              <ChevronRight className={cn('size-3.5 shrink-0 text-muted-foreground transition-transform', isOpen && 'rotate-90')} />
            </span>
            <span className="block text-xs text-muted-foreground">{b.hint}</span>
          </span>
          <span className="flex shrink-0 flex-col items-end gap-1">
            <span className={cn('text-base font-semibold tabular-nums', b.amount < -tiny && 'text-destructive')}>{b.amount < -tiny ? `(${rupees(b.amount)})` : rupees(b.amount)}</span>
            <Change now={b.amount} before={before} goodWhenUp={goodWhenUp(b)} />
          </span>
        </button>
        {isOpen && single && ledgers(b.lines[0], 'pl-[4.25rem]')}
        {isOpen &&
          !single &&
          b.lines.map((line) => {
            const id = `line:${line.key}`
            const lOpen = open.has(id)
            return (
              <React.Fragment key={line.key}>
                <button type="button" onClick={() => toggle(id)} aria-expanded={lOpen} className="flex w-full items-center gap-3 border-t border-border/50 py-2 pl-[4.25rem] pr-4 text-left text-sm hover:bg-muted/40">
                  <ChevronRight className={cn('-ml-5 size-3.5 shrink-0 text-muted-foreground transition-transform', lOpen && 'rotate-90')} />
                  <span className="min-w-0 flex-1 truncate font-medium">
                    {line.name} {line.ledgers.length > 0 && <span className="text-[11px] font-normal text-muted-foreground">{line.ledgers.length}</span>}
                  </span>
                  {prior && <Change now={line.amount} before={then(prior, `s:${line.key}`)} goodWhenUp={goodWhenUp(b)} className="hidden sm:inline-flex" />}
                  <span className={cn('w-28 shrink-0 text-right font-medium tabular-nums sm:w-32', line.amount < -tiny && 'text-destructive')}>{line.amount < -tiny ? `(${rupees(line.amount)})` : rupees(line.amount)}</span>
                </button>
                {lOpen && ledgers(line, 'pl-[5.5rem]')}
              </React.Fragment>
            )
          })}
      </div>
    )
  }

  const sideCard = (side: 'own' | 'owe' | 'worth', list: Bucket[], total: number) => {
    const sl = SIDE_LOOK[side]
    return (
      <div className="overflow-hidden rounded-xl border bg-card shadow-xs">
        <div className="flex items-center justify-between gap-2 border-b bg-muted/40 px-4 py-2.5">
          <span className={cn('flex items-center gap-2 text-sm font-semibold', sl.fg)}>
            <span className={cn('size-2 rounded-full', sl.dot)} /> {sl.title}
          </span>
          <span className={cn('text-sm font-semibold tabular-nums', total < -tiny && 'text-destructive')}>{total < -tiny ? `(${rupees(total)})` : rupees(total)}</span>
        </div>
        {list.map(bucketBlock)}
      </div>
    )
  }

  const anyOpen = open.size > 0
  const allKeys = all.map((b) => b.key)
  return (
    <div className="flex flex-col gap-4">
      {/* The result */}
      <div data-guide="bs.stats" className={cn('grid gap-5 rounded-xl border bg-card p-4 shadow-xs sm:p-5 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]', worth < -tiny ? 'border-destructive/30' : 'border-violet-500/30')}>
        <div className="flex min-w-0 flex-col gap-1.5">
          <span className={cn('inline-flex w-fit items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold', bs.balanced ? 'bg-violet-500/10 text-violet-700 dark:text-violet-400' : 'bg-destructive/10 text-destructive')}>
            {bs.balanced ? <BadgeCheck className="size-3.5" /> : <CircleAlert className="size-3.5" />}
            {bs.balanced ? 'Company worth' : 'The books do not balance'} · {formatDay(bs.as_of)}
          </span>
          <p className={cn('text-3xl font-semibold tabular-nums tracking-tight sm:text-4xl', worth < -tiny ? 'text-destructive' : 'text-violet-700 dark:text-violet-400')}>
            {worth < -tiny && '−'}
            {rupees(worth)}
          </p>
          <p className="text-sm text-muted-foreground">
            You own <span className="font-semibold text-foreground">{rupees(ownTotal)}</span> and owe <span className="font-semibold text-foreground">{rupees(oweTotal)}</span>.
            {worth < -tiny ? ' You owe more than you own.' : ' The rest is yours.'}
          </p>
          {worthBefore !== null && (
            <p className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
              <Change now={worth} before={worthBefore} goodWhenUp />
              <span>
                against {rupees(worthBefore)} on {priorLabel}
              </span>
            </p>
          )}
          {Number(bs.year_profit) !== 0 && (
            <p className="text-xs text-muted-foreground">
              Of it, this year's {Number(bs.year_profit) < 0 ? 'loss' : 'profit'}: <span className={cn('font-medium', Number(bs.year_profit) < 0 ? 'text-destructive' : 'text-success')}>{rupees(bs.year_profit)}</span> since {formatDay(bs.year_start)}.
            </p>
          )}
        </div>
        <div className="flex min-w-0 flex-col justify-center gap-2.5">
          <div className="flex flex-col gap-1">
            <span className="flex justify-between text-xs text-muted-foreground">
              <span className="font-medium text-sky-700 dark:text-sky-400">What you own</span>
              <span className="tabular-nums">{rupees(ownTotal)}</span>
            </span>
            <Bar parts={own.map((b) => ({ key: b.key, label: b.label, v: b.amount }))} of={scale} onPick={focus} />
          </div>
          <div className="flex flex-col gap-1">
            <span className="flex justify-between text-xs text-muted-foreground">
              <span>
                <span className="font-medium text-amber-800 dark:text-amber-400">What you owe</span> + <span className="font-medium text-violet-700 dark:text-violet-400">what is yours</span>
              </span>
              <span className="tabular-nums">{rupees(oweTotal + worth)}</span>
            </span>
            <Bar parts={[...owe.map((b) => ({ key: b.key, label: b.label, v: b.amount })), { key: 'worth' as const, label: 'What the company is worth', v: worth }]} of={scale} onPick={focus} />
          </div>
          <div className="flex flex-wrap gap-x-3 gap-y-1 pt-0.5">
            {[...own, ...owe, ...all.filter((b) => b.side === 'worth')].map((b) => (
              <button key={b.key} type="button" onClick={() => focus(b.key)} className="inline-flex items-center gap-1.5 text-[11px] text-muted-foreground hover:text-foreground hover:underline">
                <span className={cn('size-2 rounded-full', LOOK[b.key].bar)} /> {b.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Can you pay what is due? */}
      {cover !== null && (
        <div className={cn('flex items-start gap-3 rounded-xl border px-4 py-3', cover >= 1 ? 'border-success/30 bg-success-soft/40' : 'border-draft/30 bg-draft-soft/50')}>
          {cover >= 1 ? <BadgeCheck className="mt-0.5 size-4 shrink-0 text-success" /> : <CircleAlert className="mt-0.5 size-4 shrink-0 text-draft" />}
          <p className="text-sm">
            <span className="font-semibold">{cover >= 1 ? 'You can pay what is due.' : 'Less in hand than is due.'}</span>{' '}
            <span className="text-muted-foreground">
              For every ₹1 due soon to suppliers, taxes and others ({rupees(dueSoon)}), you have{' '}
              <span className={cn('font-semibold', cover >= 1 ? 'text-success' : 'text-draft')}>₹{cover.toFixed(2)}</span> in the bank or owed by clients ({rupees(ready)}).
            </span>
          </p>
        </div>
      )}

      <div data-guide="bs.sides" className="flex flex-col gap-4">
        <div className="flex items-center justify-between gap-2 px-1">
          <h2 className="text-base font-semibold">What makes it up</h2>
          <button
            type="button"
            onClick={() => setOpen(anyOpen ? new Set() : new Set(allKeys))}
            className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium text-muted-foreground hover:bg-muted hover:text-foreground"
          >
            {anyOpen ? <ChevronsDownUp className="size-3.5" /> : <ChevronsUpDown className="size-3.5" />}
            {anyOpen ? 'Close all' : 'Open everything'}
          </button>
        </div>
        <div className="grid gap-4 lg:grid-cols-2">
          {sideCard('own', own, ownTotal)}
          <div className="flex flex-col gap-4">
            {sideCard('owe', owe, oweTotal)}
            {sideCard('worth', all.filter((b) => b.side === 'worth'), worth)}
          </div>
        </div>
        <p className="px-1 text-[11px] text-muted-foreground">Tap any line to see what is in it, an account for its entries this year, and an entry for the bill or voucher behind it.</p>
      </div>
      <VoucherSheet entryId={entry} onClose={() => setEntry(null)} onOpen={setEntry} />
    </div>
  )
}
