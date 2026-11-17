import * as React from 'react'
import { ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { PAGE_SIZES } from '@/lib/paging'
import { cn } from '@/lib/utils'

// UX-36: one pager for lists paged in the browser. "21–40 of 132", page buttons with gaps (1 … 4 5 6 … 9), first,
// previous, next, last, and how many to a page. A page past the end (the list got shorter) shows the last page.
// `usePaged` (lib/paging.ts) slices the list; the caller keeps page and size where it likes (the address, for a link that keeps them).

/** 1 … 4 5 6 … 9: the first, the last, and the pages around the current one. */
function pageList(page: number, pages: number): (number | 'gap')[] {
  const want = new Set([1, pages, page - 1, page, page + 1].filter((p) => p >= 1 && p <= pages))
  const out: (number | 'gap')[] = []
  for (const p of [...want].sort((a, b) => a - b)) {
    const last = out[out.length - 1]
    if (typeof last === 'number' && p - last > 1) out.push('gap')
    out.push(p)
  }
  return out
}

export function Pager({
  page,
  pages,
  from,
  to,
  total,
  noun = 'rows',
  size,
  sizes = PAGE_SIZES,
  onPage,
  onSize,
  className,
}: {
  page: number
  pages: number
  from: number
  to: number
  total: number
  /** What is counted: "lines", "days". */
  noun?: string
  size?: number
  sizes?: readonly number[]
  onPage: (page: number) => void
  onSize?: (size: number) => void
  className?: string
}) {
  const ref = React.useRef<HTMLElement>(null)
  if (total === 0) return null
  // Turning a page brings the list's top back into view when it has scrolled away.
  const go = (p: number) => {
    onPage(p)
    const list = ref.current?.parentElement
    if (list && list.getBoundingClientRect().top < 0) list.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
  return (
    <nav ref={ref} aria-label="Pages" className={cn('flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground', className)}>
      <span className="tabular-nums">
        <span className="font-semibold text-foreground">
          {from}–{to}
        </span>{' '}
        of <span className="font-semibold text-foreground">{total}</span> {noun}
      </span>
      <div className="flex items-center gap-2">
        {onSize && size !== undefined && total > Math.min(...sizes) && (
          <label className="hidden items-center gap-1.5 sm:flex">
            <span>Show</span>
            <select
              value={size}
              onChange={(e) => onSize(Number(e.target.value))}
              className="h-8 rounded-md border bg-card px-1.5 text-xs text-foreground"
              aria-label="How many to a page"
            >
              {sizes.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
        )}
        {pages > 1 && (
          <div className="flex items-center gap-1">
            <Button variant="outline" size="icon" className="hidden size-8 bg-card sm:inline-flex" disabled={page <= 1} onClick={() => go(1)} aria-label="First page">
              <ChevronsLeft className="size-3.5" />
            </Button>
            <Button variant="outline" size="icon" className="size-8 bg-card" disabled={page <= 1} onClick={() => go(page - 1)} aria-label="Previous page">
              <ChevronLeft className="size-3.5" />
            </Button>
            {pageList(page, pages).map((p, i) =>
              p === 'gap' ? (
                <span key={`gap${i}`} className="px-1" aria-hidden>
                  …
                </span>
              ) : (
                <Button
                  key={p}
                  variant={p === page ? 'default' : 'outline'}
                  size="icon"
                  className={cn('size-8 tabular-nums', p !== page && 'bg-card')}
                  aria-current={p === page ? 'page' : undefined}
                  aria-label={`Page ${p}`}
                  onClick={() => go(p)}
                >
                  {p}
                </Button>
              ),
            )}
            <Button variant="outline" size="icon" className="size-8 bg-card" disabled={page >= pages} onClick={() => go(page + 1)} aria-label="Next page">
              <ChevronRight className="size-3.5" />
            </Button>
            <Button variant="outline" size="icon" className="hidden size-8 bg-card sm:inline-flex" disabled={page >= pages} onClick={() => go(pages)} aria-label="Last page">
              <ChevronsRight className="size-3.5" />
            </Button>
          </div>
        )}
      </div>
    </nav>
  )
}
