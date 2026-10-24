import * as React from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { Download, FileText, ListChecks, Printer, RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'

/** A4 at 96 dpi: the width the PDF's HTML is laid out for. */
const PAGE_WIDTH = 794
const PAGE_HEIGHT = 1123
/** How often a live DPR re-reads the day (WEB-27). */
export const LIVE_REFRESH_MS = 30_000

export type DprView = 'review' | 'document'

/** Review (confirm items) or Document (the report as the PDF will look). */
export function DprViewToggle({ value, onChange }: { value: DprView; onChange: (v: DprView) => void }) {
  const options: { key: DprView; label: string; icon: typeof FileText }[] = [
    { key: 'review', label: 'Review', icon: ListChecks },
    { key: 'document', label: 'Document', icon: FileText },
  ]
  return (
    <div role="group" aria-label="View" className="inline-flex h-10 shrink-0 rounded-lg border bg-muted/50 p-0.5">
      {options.map(({ key, label, icon: Icon }) => (
        <button
          key={key}
          type="button"
          aria-pressed={value === key}
          onClick={() => onChange(key)}
          className={cn(
            'inline-flex items-center gap-1.5 rounded-md px-2.5 text-sm sm:px-3 font-medium text-muted-foreground transition-colors',
            value === key ? 'bg-background text-foreground shadow-xs' : 'hover:text-foreground',
          )}
        >
          <Icon className="size-4" aria-hidden="true" />
          {label}
        </button>
      ))}
    </div>
  )
}

/**
 * The DPR as a page of paper: the HTML the PDF is printed from, re-read every
 * 30 seconds while `live`, so updates from site appear as they arrive. Shown
 * in a sandboxed frame (no scripts; the server escapes every value, BE-36),
 * scaled down to fit narrow screens.
 */
export function DprDocument({
  queryKey,
  fetchHtml,
  live,
  title,
  onDownload,
}: {
  queryKey: readonly unknown[]
  fetchHtml: () => Promise<string>
  live: boolean
  title: string
  /** Opens the stored PDF; absent until one exists. */
  onDownload?: () => void
}) {
  const query = useQuery({
    queryKey,
    queryFn: fetchHtml,
    refetchInterval: live ? LIVE_REFRESH_MS : false,
    placeholderData: keepPreviousData,
  })
  const frame = React.useRef<HTMLIFrameElement>(null)
  const box = React.useRef<HTMLDivElement>(null)
  const [scale, setScale] = React.useState(1)
  const [height, setHeight] = React.useState(PAGE_HEIGHT)

  React.useLayoutEffect(() => {
    const el = box.current
    if (!el) return
    const fit = () => setScale(Math.min(1, el.clientWidth / PAGE_WIDTH))
    fit()
    const observer = new ResizeObserver(fit)
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  const measure = () => {
    const doc = frame.current?.contentDocument
    if (doc) setHeight(Math.max(PAGE_HEIGHT, doc.documentElement.scrollHeight))
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        {live ? (
          <span className="inline-flex items-center gap-2 text-muted-foreground">
            <span className="relative flex size-2" aria-hidden="true">
              <span className="absolute inline-flex size-full animate-ping rounded-full bg-success opacity-60" />
              <span className="relative inline-flex size-2 rounded-full bg-success" />
            </span>
            <span className="sm:hidden">Live</span>
            <span className="hidden sm:inline">Live · updates every 30 seconds</span>
            {query.dataUpdatedAt > 0 && (
              <span className="hidden sm:inline">
                · last {new Date(query.dataUpdatedAt).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}
              </span>
            )}
          </span>
        ) : (
          <span className="text-muted-foreground">As confirmed</span>
        )}
        <div className="ml-auto flex items-center gap-1.5">
          <Button
            variant="ghost"
            size="icon"
            className="size-8"
            title="Refresh"
            aria-label="Refresh"
            onClick={() => query.refetch()}
            disabled={query.isFetching}
          >
            <RefreshCw className={cn('size-4', query.isFetching && 'animate-spin')} />
          </Button>
          <Button variant="outline" size="sm" className="gap-1.5" disabled={!query.data} onClick={() => frame.current?.contentWindow?.print()}>
            <Printer className="size-4" /> Print
          </Button>
          {onDownload && (
            <Button size="sm" className="gap-1.5 font-semibold" onClick={onDownload}>
              <Download className="size-4" /> PDF
            </Button>
          )}
        </div>
      </div>

      <div className="rounded-xl bg-muted/70 p-2 sm:p-6">
        <div ref={box} className="mx-auto w-full" style={{ maxWidth: PAGE_WIDTH }}>
          {query.isError && !query.data ? (
            <div className="flex flex-col items-center gap-3 rounded-md bg-background py-16 text-center">
              <p className="text-sm font-medium">The document could not be loaded.</p>
              <Button variant="outline" size="sm" onClick={() => query.refetch()}>
                Try again
              </Button>
            </div>
          ) : !query.data ? (
            <Skeleton className="w-full rounded-md" style={{ aspectRatio: `${PAGE_WIDTH} / ${PAGE_HEIGHT}` }} />
          ) : (
            <div className="overflow-hidden rounded-md bg-white shadow-md ring-1 ring-black/5" style={{ height: height * scale }}>
              <iframe
                ref={frame}
                title={title}
                srcDoc={query.data}
                // No scripts. Same origin only so the page's height can be
                // read and Print can reach the frame.
                sandbox="allow-same-origin allow-modals"
                onLoad={measure}
                className="block border-0 bg-white"
                style={{ width: PAGE_WIDTH, height, transform: `scale(${scale})`, transformOrigin: 'top left' }}
              />
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
