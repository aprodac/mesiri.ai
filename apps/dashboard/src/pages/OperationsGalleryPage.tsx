import * as React from 'react'
import { Link } from 'react-router-dom'
import { useInfiniteQuery } from '@tanstack/react-query'
import {
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  ImageOff,
  Images,
  RefreshCw,
  Search,
  Sparkles,
  TriangleAlert,
} from 'lucide-react'
import { useScope } from '@/lib/ScopeContext'
import { fetchSiteGalleryApi, type GalleryItem } from '@/lib/api'
import { longDate, plural, siteDayPath } from '@/lib/site-day'
import { useSiteNames } from '@/lib/site-names'
import { useUrlState } from '@/lib/url-state'
import { Callout, PageHeader } from '@/components/dpr-page'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog'
import { cn } from '@/lib/utils'

// Gallery (WEB-24): every photo the sites sent, newest day first, one block
// per site with a link to that day's site report. Reads GET /progress/gallery,
// which since WEB-24 returns a short-lived `url` per photo plus the work
// item's date and title. Opening a photo shows it large with prev/next.

const PAGE = 60

function dayOf(item: GalleryItem): string {
  return item.work_date ?? item.created_at.slice(0, 10)
}

function titleOf(item: GalleryItem): string {
  const t = item.caption || item.parent_title || 'Site photo'
  return t.charAt(0).toUpperCase() + t.slice(1)
}

function Thumb({ item, onOpen }: { item: GalleryItem; onOpen: () => void }) {
  const [broken, setBroken] = React.useState(false)
  return (
    <button
      type="button"
      onClick={onOpen}
      className="group relative aspect-[4/3] overflow-hidden rounded-lg bg-muted text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      {item.url && !broken ? (
        <img
          src={item.url}
          alt={titleOf(item)}
          loading="lazy"
          onError={() => setBroken(true)}
          className="size-full object-cover transition-transform duration-300 group-hover:scale-[1.03]"
        />
      ) : (
        <span className="flex size-full flex-col items-center justify-center gap-1 text-xs text-muted-foreground">
          <ImageOff className="size-5" /> Photo unavailable
        </span>
      )}
      <span className="pointer-events-none absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/70 to-transparent px-2.5 pt-6 pb-2 text-xs font-medium text-white">
        <span className="line-clamp-1">{titleOf(item)}</span>
      </span>
      {item.ai_caption && (
        <span className="absolute top-2 left-2 inline-flex items-center gap-1 rounded-full bg-black/55 px-1.5 py-0.5 text-[10px] font-medium text-white backdrop-blur">
          <Sparkles className="size-3" /> AI note
        </span>
      )}
    </button>
  )
}

export default function OperationsGalleryPage() {
  const { scope } = useScope()
  const names = useSiteNames()
  const [search, setSearch] = useUrlState<string>('q', '')
  const [open, setOpen] = React.useState<number | null>(null)

  const projectId = scope.mode !== 'portfolio' ? scope.projectId : undefined
  const siteId = scope.mode === 'site' ? scope.siteId : undefined

  const query = useInfiniteQuery({
    queryKey: ['gallery', projectId, siteId],
    queryFn: ({ pageParam }) => fetchSiteGalleryApi({ projectId, siteId, limit: PAGE, offset: pageParam }),
    initialPageParam: 0,
    getNextPageParam: (last, pages) => {
      const loaded = pages.reduce((n, p) => n + p.items.length, 0)
      return loaded < last.total ? loaded : undefined
    },
  })
  const total = query.data?.pages[0]?.total ?? 0
  const items = React.useMemo(() => query.data?.pages.flatMap((p) => p.items) ?? [], [query.data])

  const shown = React.useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return items
    return items.filter((i) =>
      [i.caption, i.ai_caption, i.parent_title, names.get(i.site_id)?.name].some((t) => (t ?? '').toLowerCase().includes(q)),
    )
  }, [items, search, names])

  // Newest day first; within a day, one block per site. `index` is the
  // photo's place in `shown`, for the viewer's prev/next.
  const days = React.useMemo(() => {
    const byDay = new Map<string, Map<string, { item: GalleryItem; index: number }[]>>()
    shown.forEach((item, index) => {
      const day = byDay.get(dayOf(item)) ?? new Map()
      day.set(item.site_id, [...(day.get(item.site_id) ?? []), { item, index }])
      byDay.set(dayOf(item), day)
    })
    return [...byDay.entries()].sort(([a], [b]) => b.localeCompare(a))
  }, [shown])

  const scopeLabel =
    scope.mode === 'portfolio' ? 'All projects' : scope.mode === 'project' ? scope.projectName : `${scope.projectName} / ${scope.siteName}`

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-4 pb-8 sm:px-2">
      <PageHeader
        title="Gallery"
        subtitle={<>Every photo the sites sent, newest first · {scopeLabel}</>}
        actions={
          <Button variant="ghost" size="icon" className="size-8" onClick={() => query.refetch()} disabled={query.isFetching} title="Refresh" aria-label="Refresh">
            <RefreshCw className={cn('size-4', query.isFetching && 'animate-spin')} />
          </Button>
        }
      />

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative w-full sm:w-72">
          <Search className="absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
          <Input placeholder="Search captions, work, site…" value={search} onChange={(e) => setSearch(e.target.value)} className="h-9 pl-8" />
        </div>
        <span className="ml-auto text-sm text-muted-foreground">
          {search ? `${shown.length} of ${items.length}` : plural(total, 'photo')}
        </span>
      </div>

      {query.isError ? (
        <Callout tone="draft" icon={TriangleAlert} action={<Button variant="outline" size="sm" className="bg-background" onClick={() => query.refetch()}>Try again</Button>}>
          The photos could not be loaded.
        </Callout>
      ) : query.isLoading ? (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
          {Array.from({ length: 10 }).map((_, i) => <Skeleton key={i} className="aspect-[4/3] rounded-lg" />)}
        </div>
      ) : days.length === 0 ? (
        <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed py-12 text-center">
          <Images className="size-6 text-muted-foreground" />
          <p className="text-sm font-medium">{search ? 'No photos match' : 'No photos yet'}</p>
          <p className="text-sm text-muted-foreground">
            {search ? 'Try another word.' : 'Photos the sites send on WhatsApp show here.'}
          </p>
        </div>
      ) : (
        <div className="flex flex-col gap-6">
          {days.map(([day, sites]) => (
            <section key={day} className="flex flex-col gap-3">
              <h2 className="sticky top-[60px] z-10 -mx-1 flex items-baseline gap-2 bg-background/95 px-1 py-1.5 text-sm font-semibold backdrop-blur">
                {longDate(day)}
                <span className="font-normal text-muted-foreground">{plural([...sites.values()].flat().length, 'photo')}</span>
              </h2>
              {[...sites.entries()].map(([site, photos]) => (
                <div key={site} className="flex flex-col gap-2">
                  <div className="flex items-center justify-between gap-2 text-sm">
                    <span className="min-w-0 truncate">
                      <span className="font-medium">{names.get(site)?.name ?? 'Site'}</span>
                      {names.get(site)?.project && <span className="text-muted-foreground"> · {names.get(site)?.project}</span>}
                    </span>
                    <Link to={siteDayPath(site, day)} className="inline-flex shrink-0 items-center gap-0.5 text-xs font-medium text-primary hover:underline">
                      Site report <ChevronRight className="size-3.5" />
                    </Link>
                  </div>
                  <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
                    {photos.map(({ item, index }) => (
                      <Thumb key={item.id} item={item} onOpen={() => setOpen(index)} />
                    ))}
                  </div>
                </div>
              ))}
            </section>
          ))}
          {query.hasNextPage && (
            <Button variant="outline" className="self-center" disabled={query.isFetchingNextPage} onClick={() => query.fetchNextPage()}>
              {query.isFetchingNextPage ? 'Loading…' : `Load more (${total - items.length} left)`}
            </Button>
          )}
        </div>
      )}

      <Viewer items={shown} index={open} onIndex={setOpen} names={names} />
    </div>
  )
}

function Viewer({
  items,
  index,
  onIndex,
  names,
}: {
  items: GalleryItem[]
  index: number | null
  onIndex: (i: number | null) => void
  names: Map<string, { name: string; project: string }>
}) {
  const item = index !== null ? items[index] : null
  const prev = index !== null && index > 0 ? index - 1 : null
  const next = index !== null && index < items.length - 1 ? index + 1 : null

  React.useEffect(() => {
    if (index === null) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'ArrowLeft' && prev !== null) onIndex(prev)
      if (e.key === 'ArrowRight' && next !== null) onIndex(next)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [index, prev, next, onIndex])

  const site = item ? names.get(item.site_id) : undefined
  return (
    <Dialog open={item !== null} onOpenChange={(o) => !o && onIndex(null)}>
      <DialogContent className="gap-0 overflow-hidden p-0 sm:max-w-4xl [&>button:last-child]:z-10 [&>button:last-child]:flex [&>button:last-child]:size-8 [&>button:last-child]:items-center [&>button:last-child]:justify-center [&>button:last-child]:rounded-full [&>button:last-child]:bg-black/55 [&>button:last-child]:text-white [&>button:last-child]:opacity-100 [&>button:last-child]:top-3 [&>button:last-child]:right-3">
        {item && (
          <>
            <div className="relative flex max-h-[70vh] items-center justify-center bg-black">
              {item.url ? (
                <img src={item.url} alt={titleOf(item)} className="max-h-[70vh] w-full object-contain" />
              ) : (
                <span className="flex h-64 items-center gap-2 text-sm text-white/70">
                  <ImageOff className="size-5" /> Photo unavailable
                </span>
              )}
              {prev !== null && (
                <button type="button" onClick={() => onIndex(prev)} aria-label="Previous photo" className="absolute left-2 top-1/2 flex size-9 -translate-y-1/2 items-center justify-center rounded-full bg-black/50 text-white hover:bg-black/70">
                  <ChevronLeft className="size-5" />
                </button>
              )}
              {next !== null && (
                <button type="button" onClick={() => onIndex(next)} aria-label="Next photo" className="absolute right-2 top-1/2 flex size-9 -translate-y-1/2 items-center justify-center rounded-full bg-black/50 text-white hover:bg-black/70">
                  <ChevronRight className="size-5" />
                </button>
              )}
              <span className="absolute bottom-2 right-3 rounded bg-black/50 px-1.5 py-0.5 text-[11px] text-white tabular-nums">
                {(index ?? 0) + 1} / {items.length}
              </span>
            </div>
            <div className="flex flex-col gap-3 p-5">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <DialogTitle className="text-base font-semibold">{titleOf(item)}</DialogTitle>
                  <DialogDescription className="mt-0.5 text-sm">
                    {[longDate(dayOf(item)), site?.name, site?.project].filter(Boolean).join(' · ')}
                    {item.caption && item.parent_title ? ` · ${item.parent_title}` : ''}
                  </DialogDescription>
                </div>
                <div className="flex items-center gap-1">
                  {item.url && (
                    <Button asChild variant="ghost" size="sm" className="gap-1">
                      <a href={item.url} target="_blank" rel="noreferrer">
                        <ExternalLink className="size-4" /> Full size
                      </a>
                    </Button>
                  )}
                  <Button asChild variant="outline" size="sm" className="gap-1">
                    <Link to={siteDayPath(item.site_id, dayOf(item))}>
                      Site report <ChevronRight className="size-4" />
                    </Link>
                  </Button>
                </div>
              </div>
              {item.ai_caption && (
                <div className="flex gap-2 rounded-lg bg-ai-soft px-3 py-2 text-sm">
                  <Sparkles className="mt-0.5 size-4 shrink-0 text-ai" />
                  <span>
                    <span className="font-medium text-ai">What the AI saw: </span>
                    {item.ai_caption}
                  </span>
                </div>
              )}
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}
