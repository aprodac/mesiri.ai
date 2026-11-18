import * as React from 'react'
import { NavLink } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ClipboardCheck, Handshake, ScrollText } from 'lucide-react'
import { ModuleHeader } from '@/components/page/module-header'
import { rupees } from '@/lib/expenses'
import { fetchBillsWaiting } from '@/lib/subcontracts'
import { BAR_PARTS, STATE_LOOK, type JobState, type MoneySplit } from '@/lib/subcontract-look'
import { cn } from '@/lib/utils'

// UX-64: the subcontract module's shared parts. The header band with the module's three pages as tabs (Bills carries
// how many wait), the state chip, the trade tile and the money bar, so every page reads the same way.

const PAGES = [
  { to: '/subcontract/teams', label: 'Subcontractors', icon: Handshake },
  { to: '/subcontract/work-orders', label: 'Work orders', icon: ScrollText },
  { to: '/subcontract/bills', label: 'Bills & checks', icon: ClipboardCheck, count: true },
]

export function SubcontractHeader({ icon, title, children, back }: {
  icon: React.ComponentType<{ className?: string }>
  title: React.ReactNode
  children?: React.ReactNode
  back?: { to: string; label: string }
}) {
  return (
    <div className="flex flex-col gap-2">
      <ModuleHeader icon={icon} title={title} back={back}>{children}</ModuleHeader>
      {!back && <SubcontractTabs />}
    </div>
  )
}

export function SubcontractTabs() {
  const waiting = useQuery({ queryKey: ['subcontracts', 'waiting'], queryFn: fetchBillsWaiting, retry: false, staleTime: 30_000 })
  const n = waiting.data?.length ?? 0
  return (
    <nav aria-label="Subcontract pages" className="flex w-fit max-w-full overflow-x-auto rounded-lg border bg-card p-0.5 shadow-xs" data-guide="sub.tabs">
      {PAGES.map((p) => (
        <NavLink
          key={p.to}
          to={p.to}
          className={({ isActive }) => cn('inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-md px-3 py-1.5 text-sm font-medium',
            isActive ? 'bg-foreground text-background' : 'text-foreground/75 hover:bg-muted hover:text-foreground')}
        >
          <p.icon className="size-4" />{p.label}
          {p.count && n > 0 && <span className="rounded-full bg-amber-500 px-1.5 text-xs font-semibold text-white tabular-nums">{n}</span>}
        </NavLink>
      ))}
    </nav>
  )
}

export function StateChip({ state, note, className }: { state: JobState; note?: string | null; className?: string }) {
  const look = STATE_LOOK[state]
  return (
    <span className={cn('inline-flex shrink-0 items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-semibold whitespace-nowrap', look.chip, className)}>
      <span className={cn('size-1.5 rounded-full', look.dot)} />{look.label}{note ? <span className="font-normal opacity-80">· {note}</span> : null}
    </span>
  )
}

export function TradeTile({ look, size = 'md' }: { look: { label: string; icon: React.ComponentType<{ className?: string }>; tile: string }; size?: 'sm' | 'md' | 'lg' }) {
  const Icon = look.icon
  return (
    <span className={cn('flex shrink-0 items-center justify-center rounded-xl', look.tile, size === 'sm' ? 'size-8' : size === 'lg' ? 'size-12' : 'size-10')} title={look.label}>
      <Icon className={size === 'sm' ? 'size-4' : size === 'lg' ? 'size-6' : 'size-5'} />
    </span>
  )
}

/** Paid · billed not paid · done not billed · not done, as one bar the width of the work's value. */
export function MoneyBar({ split, className, tall }: { split: MoneySplit; className?: string; tall?: boolean }) {
  const total = split.value || Math.max(split.done, split.billed) || 1
  const parts = { paid: split.paid, owed: Math.max(split.billed - split.paid, 0), unbilled: split.unbilled, left: split.left }
  const words = BAR_PARTS.filter((p) => parts[p.key] > 0).map((p) => `${p.label} ${rupees(parts[p.key])}`).join(', ')
  return (
    <span className={cn('flex overflow-hidden rounded-full bg-muted', tall ? 'h-3' : 'h-2', className)} role="img" aria-label={words || 'Nothing yet'} title={words}>
      {BAR_PARTS.map((p) => parts[p.key] > 0 && (
        <span key={p.key} className={cn('h-full', p.fill)} style={{ width: `${(parts[p.key] / total) * 100}%` }} />
      ))}
    </span>
  )
}

/** The money bar's key, once a page. */
export function BarKey({ className }: { className?: string }) {
  return (
    <span className={cn('flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground', className)}>
      {BAR_PARTS.map((p) => (
        <span key={p.key} className="inline-flex items-center gap-1.5"><span className={cn('h-2 w-3.5 rounded-sm', p.fill, p.key === 'left' && 'border')} />{p.label}</span>
      ))}
    </span>
  )
}
