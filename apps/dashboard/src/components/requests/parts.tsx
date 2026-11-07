import { Check, ChevronDown, Clock, MessageCircle } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { cn } from '@/lib/utils'
import {
  HAZARD,
  STATUS_LOOK,
  URGENCY_LOOK,
  categoryLook,
  cover,
  initials,
  neededWords,
  swatch,
  type MaterialRequest,
  type RequestLine,
  type RequestStatus,
} from '@/lib/requests'

// PRC-22: the small pieces the Requests page is drawn from, so every row, panel and dropdown uses the same cues.

export function CategoryTile({ mainCategory, size = 'md' }: { mainCategory: string | null; size?: 'sm' | 'md' | 'lg' }) {
  const { icon: Icon, tile } = categoryLook(mainCategory)
  const box = { sm: 'size-6 rounded-md', md: 'size-10 rounded-xl', lg: 'size-12 rounded-xl' }[size]
  const glyph = { sm: 'size-3.5', md: 'size-5', lg: 'size-6' }[size]
  return (
    <span className={cn('inline-flex shrink-0 items-center justify-center', box, tile)} aria-hidden>
      <Icon className={glyph} />
    </span>
  )
}

export function StatusChip({ status }: { status: RequestStatus }) {
  const look = STATUS_LOOK[status]
  return (
    <span className={cn('inline-flex shrink-0 items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-semibold', look.chip)}>
      <span className={cn('size-1.5 rounded-full', look.dot)} />
      {look.label}
    </span>
  )
}

export function UrgencyChip({ request, className }: { request: MaterialRequest; className?: string }) {
  return (
    <span className={cn('inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold whitespace-nowrap', URGENCY_LOOK[request.urgency].chip, className)}>
      <Clock className="size-3" strokeWidth={2.6} />
      {neededWords(request)}
    </span>
  )
}

export function Avatar({ id, name, size = 'sm' }: { id: string | null; name: string | null; size?: 'sm' | 'md' }) {
  const colour = swatch(id || name || '?')
  return (
    <span
      className={cn('inline-flex shrink-0 items-center justify-center rounded-full font-bold', size === 'sm' ? 'size-5 text-[9px]' : 'size-7 text-[11px]')}
      style={{ background: `${colour}22`, color: colour }}
      aria-hidden
    >
      {initials(name)}
    </span>
  )
}

export function ProjectDot({ id }: { id: string }) {
  return <span className="size-2.5 shrink-0 rounded-[3px]" style={{ background: swatch(id) }} aria-hidden />
}

export function WhatsAppMark() {
  return (
    <span title="Asked on WhatsApp" className="inline-flex size-5 items-center justify-center rounded-full bg-success-soft text-success">
      <MessageCircle className="size-3" strokeWidth={2.4} />
      <span className="sr-only">Asked on WhatsApp</span>
    </span>
  )
}

/** Here (green), already ordered (blue), still to buy (hazard stripes): the whole bar is what was asked. */
export function CoverBar({ line, className }: { line: RequestLine; className?: string }) {
  const c = cover(line)
  return (
    <span className={cn('flex h-2.5 overflow-hidden rounded-full bg-muted', className)} aria-hidden>
      <span className="bg-green-700" style={{ width: `${c.here}%` }} />
      <span className="bg-blue-400" style={{ width: `${c.ordered}%` }} />
      <span className={HAZARD} style={{ width: `${c.buy}%` }} />
    </span>
  )
}

export interface FilterOption {
  value: string
  label: string
  count: number
  /** A coloured square, an avatar, or a category tile before the label. */
  swatch?: string
  avatar?: { id: string; name: string }
  category?: string | null
  dot?: string
}

/** A filter as a pill that opens a list with the same cues as the rows (colours, avatars, category icons, counts). */
export function FilterPill({
  icon: Icon,
  label,
  allLabel,
  value,
  options,
  onChange,
}: {
  icon: LucideIcon
  label: string
  allLabel: string
  value: string
  options: FilterOption[]
  onChange: (value: string) => void
}) {
  const chosen = options.find((o) => o.value === value)
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        className={cn(
          'inline-flex h-9 items-center gap-1.5 rounded-lg border px-2.5 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring',
          chosen ? 'border-yellow-500 bg-yellow-50 font-semibold text-yellow-900 dark:bg-yellow-950 dark:text-yellow-100' : 'bg-background hover:border-foreground/30',
        )}
        aria-label={label}
      >
        <Icon className="size-4 opacity-80" />
        {chosen && <OptionMark option={chosen} small />}
        <span className="max-w-[160px] truncate">{chosen ? chosen.label : label}</span>
        {chosen && <span className="rounded-full bg-foreground px-1.5 text-[11px] font-bold text-background">1</span>}
        <ChevronDown className="size-3.5 opacity-70" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-64 p-1.5">
        <FilterItem active={!chosen} onSelect={() => onChange('')} label={allLabel} count={options.reduce((n, o) => n + o.count, 0)} />
        {options.map((o) => (
          <FilterItem key={o.value} active={o.value === value} onSelect={() => onChange(o.value === value ? '' : o.value)} label={o.label} count={o.count}>
            <OptionMark option={o} />
          </FilterItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

function FilterItem({ active, onSelect, label, count, children }: { active: boolean; onSelect: () => void; label: string; count: number; children?: React.ReactNode }) {
  return (
    <DropdownMenuItem onSelect={onSelect} className={cn('min-h-10 gap-2.5 rounded-md', active && 'bg-yellow-50 dark:bg-yellow-950')}>
      {children}
      <span className={cn('flex-1 truncate', active && 'font-semibold')}>{label}</span>
      <span className="rounded-full bg-muted px-1.5 text-xs tabular-nums text-muted-foreground">{count}</span>
      {active && <Check className="size-4 text-yellow-700 dark:text-yellow-300" strokeWidth={2.6} />}
    </DropdownMenuItem>
  )
}

function OptionMark({ option, small }: { option: FilterOption; small?: boolean }) {
  if (option.avatar) return <Avatar id={option.avatar.id} name={option.avatar.name} />
  if (option.category !== undefined) return <CategoryTile mainCategory={option.category} size="sm" />
  if (option.swatch) return <span className={cn('shrink-0 rounded-[3px]', small ? 'size-2.5' : 'size-3')} style={{ background: option.swatch }} />
  if (option.dot) return <span className={cn('shrink-0 rounded-full', small ? 'size-2' : 'size-2.5', option.dot)} />
  return null
}
