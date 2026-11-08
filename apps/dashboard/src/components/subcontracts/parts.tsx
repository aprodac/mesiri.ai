import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ClipboardCheck } from 'lucide-react'
import { fetchBillsWaiting } from '@/lib/subcontracts'
import { cn } from '@/lib/utils'

// NXT-05/06: how far a work order (or a line) is: done (measured) against agreed, and billed inside it. Over 100%
// shows red: more measured or billed than agreed.

export function Progress3({ done, billed, className }: { done: number; billed?: number; className?: string }) {
  const over = done > 100 || (billed ?? 0) > 100
  return (
    <span className={cn('relative block h-2.5 overflow-hidden rounded-full bg-muted', className)} role="img"
      aria-label={`${done}% done${billed !== undefined ? `, ${billed}% billed` : ''}`}>
      <span className={cn('absolute inset-y-0 left-0 rounded-full', over ? 'bg-red-500' : 'bg-violet-300 dark:bg-violet-800')} style={{ width: `${Math.min(done, 100)}%` }} />
      {billed !== undefined && <span className={cn('absolute inset-y-0 left-0 rounded-full', (billed ?? 0) > done ? 'bg-red-600' : 'bg-violet-600')} style={{ width: `${Math.min(billed, 100)}%` }} />}
    </span>
  )
}

/** Today (NXT-18): subcontract bills waiting for a person, for the roles that see spending. */
export function BillsWaitingLine() {
  const q = useQuery({ queryKey: ['subcontracts', 'waiting'], queryFn: fetchBillsWaiting, retry: false, staleTime: 60_000 })
  const list = q.data ?? []
  if (!list.length) return null
  const total = list.reduce((s, b) => s + (Number(b.gross) || 0), 0)
  return (
    <Link to="/subcontract/bills" className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl border bg-card px-3 py-2.5 text-sm hover:bg-muted/30">
      <ClipboardCheck className="size-4 text-muted-foreground" />
      <span className="font-medium">Subcontract bills</span>
      <span className="text-draft">{list.length} waiting for a check · ₹{Math.round(total).toLocaleString('en-IN')}</span>
      <span className="ml-auto text-xs font-semibold">Check</span>
    </Link>
  )
}
