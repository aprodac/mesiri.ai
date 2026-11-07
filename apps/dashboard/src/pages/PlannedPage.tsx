import { Link, Navigate, useLocation } from 'react-router-dom'
import { ArrowRight, Construction, Lightbulb, MapPin } from 'lucide-react'
import { DprHeader } from '@/components/dpr-page'
import { findPage, type ModuleGroup, type ModulePage } from '@/lib/module-map'
import { usePageTitle } from '@/lib/page-title'
import { usePlannedPreview } from '@/lib/preview'
import { CHIP } from '@/lib/site-day'
import { cn } from '@/lib/utils'

// WEB-72: one page for every planned module page. It says what the page will answer, shows it
// on a real site, and links to what already works. Only reachable while "Show planned
// modules" is on; otherwise the address goes to Today, as an unknown address does.

function StatusChip({ page }: { page: ModulePage }) {
  return page.status === 'built' ? (
    <span className={cn(CHIP, 'bg-success-soft text-success')}>Working</span>
  ) : (
    <span className={cn(CHIP, 'bg-draft-soft text-draft')}>Planned · {page.phase}</span>
  )
}

function ModulePages({ group, current }: { group: ModuleGroup; current: ModulePage }) {
  return (
    <ul className="divide-y rounded-lg border">
      {group.pages.map((p) => (
        <li key={p.url}>
          <Link
            to={p.url}
            aria-current={p === current ? 'page' : undefined}
            className={cn('flex items-center gap-3 px-3 py-2.5 text-sm hover:bg-muted/60', p === current && 'bg-muted/60')}
          >
            <span className="min-w-0 flex-1">
              <span className="font-medium">{p.title}</span>
              <span className="block truncate text-xs text-muted-foreground">{p.about}</span>
            </span>
            <StatusChip page={p} />
          </Link>
        </li>
      ))}
    </ul>
  )
}

export default function PlannedPage() {
  const { pathname, search } = useLocation()
  const [preview] = usePlannedPreview()
  const hit = findPage(pathname, search)
  usePageTitle(hit?.page.title)

  if (!preview || !hit || hit.page.status !== 'planned') return <Navigate to="/today" replace />
  const { group, page } = hit
  const Icon = group.icon

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-6 pb-8 sm:px-2">
      <DprHeader
        back={{ to: '/today', label: 'Today' }}
        crumb={group.title}
        title={page.title}
        chip={<StatusChip page={page} />}
        date={page.tracker ? `Tracker ${page.tracker}` : undefined}
      />

      <section className="grid grid-cols-[minmax(0,1fr)] gap-4 md:grid-cols-[minmax(0,1fr)_280px]">
        <div className="flex min-w-0 flex-col gap-4">
          <div className="flex flex-col gap-2 rounded-xl border bg-card p-5">
            <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">What this page will answer</p>
            <p className="text-lg font-semibold leading-snug text-balance">{page.about}</p>
          </div>
          <div className="flex gap-3 rounded-xl border border-info/20 bg-info-soft p-5 text-info">
            <MapPin className="mt-0.5 size-5 shrink-0" />
            <div className="flex flex-col gap-1">
              <p className="text-xs font-semibold uppercase tracking-wider">On a real site</p>
              <p className="text-[15px] text-foreground">{page.example}</p>
            </div>
          </div>
          {page.related && page.related.length > 0 && (
            <div className="flex flex-col gap-2">
              <p className="text-sm font-semibold">Works today</p>
              <div className="flex flex-wrap gap-2">
                {page.related.map((r) => (
                  <Link key={r.url} to={r.url} className="inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-sm hover:bg-muted">
                    {r.title} <ArrowRight className="size-3.5" />
                  </Link>
                ))}
              </div>
            </div>
          )}
        </div>
        <aside className="flex min-w-0 flex-col gap-3">
          <div className="flex items-center gap-2">
            <span className="flex size-7 items-center justify-center rounded-md bg-muted">
              <Icon className="size-4" />
            </span>
            <p className="font-semibold">{group.title}</p>
          </div>
          <p className="text-sm text-muted-foreground">{group.about}</p>
          <ModulePages group={group} current={page} />
        </aside>
      </section>

      <div className="flex items-start gap-2.5 rounded-lg border border-dashed px-4 py-3 text-sm text-muted-foreground">
        <Construction className="mt-0.5 size-4 shrink-0" />
        <p>
          Planned, not built yet. You see this because <span className="font-medium text-foreground">Show planned modules</span> is on in
          the sidebar; customers don't see planned pages.
        </p>
      </div>
      <div className="flex items-start gap-2.5 text-xs text-muted-foreground">
        <Lightbulb className="mt-0.5 size-3.5 shrink-0" />
        <p>The full module map, with every page a construction ERP has, is in the "Construction ERP Map" reference.</p>
      </div>
    </div>
  )
}
