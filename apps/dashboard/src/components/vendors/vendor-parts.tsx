import { Link } from 'react-router-dom'
import { FileWarning, HandCoins } from 'lucide-react'
import { rupees } from '@/lib/expenses'
import { cn } from '@/lib/utils'
import { useAuth } from '@/lib/AuthContext'
import { usePapersAttention } from '@/lib/vendor-documents'
import { BUCKETS, num, usePayables, vendorUrl, type Buckets } from '@/lib/vendors'

// CC-09: small pieces of the supplier pages, and the link every other page uses to open a supplier's account.

/** How long the money owed has waited: one bar, four ages, with the amounts under it. */
export function AgeBar({ buckets, compact }: { buckets: Buckets; compact?: boolean }) {
  const total = BUCKETS.reduce((n, b) => n + num(buckets[b.key]), 0)
  if (total <= 0) return <p className="text-sm text-muted-foreground">Nothing waiting.</p>
  return (
    <div className="flex flex-col gap-2">
      <div className="flex h-3 overflow-hidden rounded-full bg-muted" role="img"
        aria-label={BUCKETS.map((b) => `${b.label}: ${rupees(num(buckets[b.key]))}`).join(', ')}>
        {BUCKETS.map((b) => num(buckets[b.key]) > 0 && (
          <span key={b.key} className={cn(b.tone, 'h-full border-r border-background last:border-r-0')} style={{ width: `${(num(buckets[b.key]) / total) * 100}%` }} />
        ))}
      </div>
      {!compact && (
        <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm sm:grid-cols-4">
          {BUCKETS.map((b) => (
            <div key={b.key} className="flex items-center gap-2">
              <span className={cn('size-2.5 shrink-0 rounded-full', b.tone)} aria-hidden />
              <dt className="text-muted-foreground">{b.label}</dt>
              <dd className={cn('ml-auto font-medium tabular-nums', num(buckets[b.key]) === 0 && 'text-muted-foreground')}>{rupees(num(buckets[b.key]))}</dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  )
}

/** A supplier's name that opens its account: used on expenses, orders, receipts, rates and money. */
export function VendorLink({ id, name, tab, className, onClick }: { id: string | null | undefined; name: string | null | undefined; tab?: string; className?: string; onClick?: () => void }) {
  if (!name) return null
  if (!id) return <span className={className}>{name}</span>
  return (
    <Link to={vendorUrl(id, tab)} onClick={(e) => { e.stopPropagation(); onClick?.() }} className={cn('relative z-10 underline-offset-2 hover:underline', className)} title={`Open ${name}'s account`}>
      {name}
    </Link>
  )
}

/** Under a supplier picked or typed (an order, an expense): what stands with them today, and their account. */
export function SupplierHint({ name, className }: { name: string; className?: string }) {
  const payables = usePayables()
  const key = name.trim().toLowerCase()
  const v = key ? payables.data?.vendors.find((x) => x.name.toLowerCase() === key) : undefined
  if (!v) return null
  const bal = num(v.balance)
  const parts = [
    bal > 0 ? `You owe them ${rupees(bal)}` : bal < 0 ? `They hold ${rupees(-bal)} of yours as advance` : null,
    num(v.overdue) > 0 ? `${rupees(num(v.overdue))} overdue` : null,
    v.unbilled_count ? `${v.unbilled_count} ${v.unbilled_count === 1 ? 'delivery' : 'deliveries'} not billed` : null,
  ].filter(Boolean)
  if (!parts.length) return null
  return (
    <p className={cn('flex items-center gap-1.5 text-xs text-muted-foreground', className)}>
      <HandCoins className="size-3.5 shrink-0" />
      <span className={cn(num(v.overdue) > 0 && 'text-draft')}>{parts.join(' · ')}</span>
      <Link to={vendorUrl(v.id)} target="_blank" className="ml-auto shrink-0 font-semibold text-foreground underline-offset-2 hover:underline">Account</Link>
    </p>
  )
}

/** Today: supplier money that needs a look (overdue bills, deliveries long without a bill), for who sees spending. */
export function SuppliersWaiting() {
  const payables = usePayables()
  const t = payables.data?.totals
  if (!t) return null
  const overdue = num(t.overdue)
  const late = payables.data!.vendors.filter((v) => num(v.overdue) > 0).length
  const unbilled = num(t.unbilled)
  if (overdue <= 0 && unbilled <= 0) return null
  return (
    <Link to="/finance/vendors" className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl border bg-card px-3 py-2.5 text-sm hover:bg-muted/30">
      <HandCoins className="size-4 text-muted-foreground" />
      <span className="font-medium">Suppliers</span>
      {overdue > 0 && <span className="text-draft">{rupees(overdue)} overdue to {late} {late === 1 ? 'supplier' : 'suppliers'}</span>}
      {unbilled > 0 && <span className="text-muted-foreground">{rupees(unbilled)} delivered with no bill</span>}
      <span className="ml-auto text-xs font-semibold">Open</span>
    </Link>
  )
}

/** PRC-52, Today: supplier papers expired, missing or expiring within 15 days, for the owner, admin and finance. */
export function SupplierPapersWaiting() {
  const { me } = useAuth()
  const allowed = ['ADMIN', 'OWNER', 'SUPER_ADMIN', 'FINANCE'].includes((me?.role || '').toUpperCase())
  const { data = [] } = usePapersAttention(allowed)
  if (!allowed || data.length === 0) return null
  // Papers, not suppliers: one supplier can have a GST certificate expiring and its PAN missing.
  const all = data.flatMap((x) => x.papers)
  const expired = all.filter((p) => p.status === 'expired').length
  const soon = all.filter((p) => p.status === 'expiring').length
  const missing = all.filter((p) => p.status === 'missing').length
  const first = data[0]
  return (
    <Link to={data.length === 1 ? vendorUrl(first.vendor_id, 'documents') : '/finance/vendors'} className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl border bg-card px-3 py-2.5 text-sm hover:bg-muted/30">
      <FileWarning className="size-4 text-muted-foreground" />
      <span className="font-medium">Supplier papers</span>
      {expired > 0 && <span className="text-draft">{expired} expired</span>}
      {soon > 0 && <span className="text-amber-700 dark:text-amber-400">{soon} expiring within 15 days</span>}
      {missing > 0 && <span className="text-muted-foreground">{missing} missing (GST or PAN)</span>}
      <span className="min-w-0 truncate text-xs text-muted-foreground">{data.slice(0, 3).map((x) => x.name).join(', ')}{data.length > 3 ? '…' : ''}</span>
      <span className="ml-auto text-xs font-semibold">Open</span>
    </Link>
  )
}
