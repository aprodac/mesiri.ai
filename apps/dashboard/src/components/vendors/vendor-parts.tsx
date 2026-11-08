import { Link } from 'react-router-dom'
import { rupees } from '@/lib/expenses'
import { cn } from '@/lib/utils'
import { BUCKETS, num, vendorUrl, type Buckets } from '@/lib/vendors'

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
