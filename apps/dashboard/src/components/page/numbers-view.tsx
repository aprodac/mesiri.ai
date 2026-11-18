import * as React from 'react'
import { ArrowDown, ArrowUp, ArrowUpDown, BarChart3, ChevronRight, Table2 } from 'lucide-react'
import type { ShowMode, SortableColumn } from '@/lib/numbers-view'
import { cn } from '@/lib/utils'

// UX-44: the Bars / Numbers switch and the Numbers table (lib/numbers-view.ts holds the state). A Numbers table puts
// every figure in its own column, coloured by what it means; the first column (the name) stays put while the figures
// scroll on a phone; a header sorts; a row can open its page.

export function ShowSwitch({ show, onShow, label }: { show: ShowMode; onShow: (v: ShowMode) => void; label: string }) {
  return (
    <span className="inline-flex h-8 rounded-lg border bg-card p-0.5" role="group" aria-label={label}>
      {(['bars', 'numbers'] as const).map((v) => (
        <button
          key={v}
          type="button"
          aria-pressed={show === v}
          onClick={() => onShow(v)}
          className={cn('inline-flex items-center gap-1 rounded-md px-2 text-xs font-semibold transition', show === v ? 'bg-foreground text-background' : 'text-muted-foreground hover:text-foreground')}
        >
          {v === 'bars' ? <BarChart3 className="size-3.5" aria-hidden /> : <Table2 className="size-3.5" aria-hidden />}
          {v === 'bars' ? 'Bars' : 'Numbers'}
        </button>
      ))}
    </span>
  )
}

export interface NumberColumn<T> extends SortableColumn<T> {
  label: string
  /** What the column means, on hover. */
  title?: string
  /** The cell; `null` draws a grey dash. */
  cell: (row: T) => React.ReactNode | null
  /** A colour for the cell's text by what it means (red over, green under …). */
  tone?: (row: T) => string | undefined
  /** Text columns sort A to Z first and sit on the left. */
  text?: boolean
}

export function NumbersTable<T>({
  rows,
  rowKey,
  first,
  columns,
  edge,
  col,
  dir,
  onSort,
  onOpen,
  openTitle,
  footer,
  guide,
  minWidth = 900,
}: {
  rows: T[]
  rowKey: (row: T) => string
  /** The name column: it stays put while the figures scroll. */
  first: NumberColumn<T>
  columns: NumberColumn<T>[]
  /** A colour class for the row's edge (its state). */
  edge?: (row: T) => string
  col: string
  dir: 'asc' | 'desc'
  onSort: (key: string, text?: boolean) => void
  onOpen?: (row: T) => void
  openTitle?: string
  footer?: React.ReactNode
  guide?: string
  minWidth?: number
}) {
  const head = (c: NumberColumn<T>, sticky: boolean) => {
    const on = col === c.key
    return (
      <th
        key={c.key}
        title={c.title}
        aria-sort={on ? (dir === 'asc' ? 'ascending' : 'descending') : undefined}
        className={cn('px-3 py-2 font-medium whitespace-nowrap', sticky ? 'sticky left-0 z-10 bg-muted text-left' : c.text ? 'text-left' : 'text-right')}
      >
        <button
          type="button"
          onClick={() => onSort(c.key, c.text || sticky)}
          className={cn('inline-flex items-center gap-1 hover:text-foreground', !sticky && !c.text && 'flex-row-reverse', on && 'font-semibold text-foreground')}
        >
          {c.label}
          {on ? dir === 'asc' ? <ArrowUp className="size-3" aria-hidden /> : <ArrowDown className="size-3" aria-hidden /> : <ArrowUpDown className="size-3 opacity-40" aria-hidden />}
        </button>
      </th>
    )
  }
  return (
    <div className="relative" data-guide={guide}>
      <ScrollBox>
      <table className="w-full text-sm tabular-nums" style={{ minWidth }}>
        <thead className="bg-muted text-xs text-muted-foreground">
          <tr>
            {head(first, true)}
            {columns.map((c) => head(c, false))}
          </tr>
        </thead>
        <tbody className="divide-y">
          {rows.map((r) => (
            <tr key={rowKey(r)} className={cn('group', onOpen && 'cursor-pointer', 'hover:bg-muted/30')} onClick={onOpen ? () => onOpen(r) : undefined} title={openTitle}>
              <td className="sticky left-0 z-10 bg-card px-3 py-2 pl-4 group-hover:bg-muted">
                {edge && <span className={cn('absolute top-1.5 bottom-1.5 left-1.5 w-1 rounded-full', edge(r))} aria-hidden />}
                {first.cell(r)}
              </td>
              {columns.map((c) => {
                const v = c.cell(r)
                return (
                  <td key={c.key} className={cn('px-3 py-2 whitespace-nowrap', c.text ? 'text-left' : 'text-right', v !== null && c.tone?.(r))}>
                    {v === null ? <span className="text-muted-foreground">—</span> : v}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
        {footer && (
          <tfoot className="border-t bg-muted/40 text-xs text-muted-foreground">
            <tr>
              <td className="sticky left-0 z-10 bg-muted px-3 py-2 font-medium" colSpan={columns.length + 1}>
                {footer}
              </td>
            </tr>
          </tfoot>
        )}
      </table>
      </ScrollBox>
    </div>
  )
}

/** Scrolls sideways; a fade on the right says more columns are there until the end is reached. */
function ScrollBox({ children }: { children: React.ReactNode }) {
  const ref = React.useRef<HTMLDivElement>(null)
  const [more, setMore] = React.useState(false)
  const check = React.useCallback(() => {
    const el = ref.current
    if (el) setMore(el.scrollLeft + el.clientWidth < el.scrollWidth - 2)
  }, [])
  React.useEffect(() => {
    check()
    const el = ref.current
    if (!el) return
    const ro = new ResizeObserver(check)
    ro.observe(el)
    return () => ro.disconnect()
  }, [check])
  return (
    <>
      <div ref={ref} onScroll={check} className="overflow-x-auto rounded-xl border bg-card [contain:inline-size]">
        {children}
      </div>
      {more && (
        <span className="pointer-events-none absolute inset-y-px right-px flex w-12 items-center justify-end rounded-r-xl bg-gradient-to-l from-card to-transparent pr-1" aria-hidden>
          <ChevronRight className="size-4 text-muted-foreground" />
        </span>
      )}
    </>
  )
}
