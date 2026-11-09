import * as React from 'react'
import { useQuery } from '@tanstack/react-query'
import { Check, ChevronRight, ChevronsUpDown, Search } from 'lucide-react'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { useIsMobile } from '@/hooks/use-mobile'
import { fetchSiteDaysApi } from '@/lib/api'
import { useAllowedScopes, useScope } from '@/lib/ScopeContext'
import { readRecentScopes } from '@/lib/scope-recent'
import { SCOPE_ICON, SCOPE_TONE, useScopeTree, type Tree } from '@/lib/scope-look'
import type { AppScope, ProjectItem, SiteItem } from '@/lib/scope-types'
import { hasUpdates, localIsoDate } from '@/lib/site-day'
import { cn } from '@/lib/utils'

// SCP-01: what the data on every page is for -- all projects, one project, or one site -- and the one place to
// change it. The top bar shows it as a path (All projects › Villa › Compound wall) whose parts take you up a level;
// the panel lists every project with its sites under it, searchable, with today's reporting beside each, so one
// click picks either. Each level keeps its colour everywhere (WEB-20): all projects blue, a project green, a site
// orange. Phones get the same list as a sheet.

export function ScopeBar() {
  const { scope, setPortfolioScope, setProjectScope } = useScope()
  const allowed = useAllowedScopes()
  const { tree } = useScopeTree()
  const isMobile = useIsMobile()
  const [open, setOpen] = React.useState(false)

  // A switcher only when there is something to switch to: a site engineer with one site has one view.
  const choices =
    (allowed.includes('portfolio') ? 1 : 0) +
    (allowed.includes('project') ? tree.length : 0) +
    (allowed.includes('site') ? tree.reduce((n, t) => n + t.sites.length, 0) : 0)
  const canSwitch = choices > 1

  const mode = scope.mode
  const Icon = SCOPE_ICON[mode]
  const badge = (
    <span className={cn('flex size-6 shrink-0 items-center justify-center rounded-md', SCOPE_TONE[mode])}>
      <Icon className="size-3.5" aria-hidden />
    </span>
  )

  // The path. Parts above the current level are links up (desktop); the last part opens the panel.
  const up: { label: string; go: () => void }[] = []
  if (mode !== 'portfolio' && allowed.includes('portfolio')) up.push({ label: 'All projects', go: setPortfolioScope })
  if (mode === 'site' && allowed.includes('project')) {
    up.push({ label: scope.projectName, go: () => setProjectScope({ id: scope.projectId, name: scope.projectName }) })
  }
  const current = mode === 'portfolio' ? 'All projects' : mode === 'project' ? scope.projectName : scope.siteName
  // A site engineer's site says which project it is in, since there is no project part to click.
  const context = mode === 'site' && !allowed.includes('project') ? scope.projectName : null

  const label = (
    <span className="flex min-w-0 items-baseline gap-1.5">
      <span className="truncate">{current}</span>
      {context && <span className="hidden truncate text-xs font-normal text-muted-foreground sm:inline">{context}</span>}
    </span>
  )

  const pill = 'flex h-9 min-w-0 items-center gap-1 rounded-lg border bg-card pl-1.5 pr-1 text-sm font-semibold shadow-xs'

  if (!canSwitch) {
    return (
      <div className={cn(pill, 'max-w-[55vw] pr-2.5 sm:max-w-sm')} title="What this page shows">
        {badge}
        <span className="ml-1 min-w-0">{label}</span>
      </div>
    )
  }

  const trigger = (
    <button
      type="button"
      className="flex min-w-0 items-center gap-1.5 rounded-md px-1.5 py-1 hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring"
      aria-label={`Showing ${current}. Change what the pages show`}
      onClick={isMobile ? () => setOpen(true) : undefined}
    >
      <span className="min-w-0 max-w-[38vw] sm:max-w-[16rem]">{label}</span>
      <ChevronsUpDown className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
    </button>
  )

  return (
    <nav aria-label="What the pages show" className={cn(pill, 'max-w-[62vw] md:max-w-none')}>
      {badge}
      {up.map((part) => (
        <React.Fragment key={part.label}>
          <button
            type="button"
            onClick={part.go}
            className="hidden max-w-[10rem] truncate rounded-md px-1.5 py-1 font-medium text-muted-foreground hover:bg-muted hover:text-foreground md:inline"
            title={`Show ${part.label}`}
          >
            {part.label}
          </button>
          <ChevronRight className="hidden size-3.5 shrink-0 text-muted-foreground/60 md:inline" aria-hidden />
        </React.Fragment>
      ))}
      {isMobile ? (
        <>
          {trigger}
          <Sheet open={open} onOpenChange={setOpen}>
            <SheetContent side="bottom" className="max-h-[85svh] gap-0 rounded-t-2xl p-0">
              <SheetHeader className="border-b px-4 py-3">
                <SheetTitle>Show data for</SheetTitle>
                <SheetDescription>Every page follows what you pick here.</SheetDescription>
              </SheetHeader>
              <ScopePanel tree={tree} onDone={() => setOpen(false)} inMenu={false} />
            </SheetContent>
          </Sheet>
        </>
      ) : (
        <DropdownMenu open={open} onOpenChange={setOpen}>
          <DropdownMenuTrigger asChild>{trigger}</DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="w-[22rem] p-0">
            <div className="border-b px-3 py-2.5">
              <div className="text-sm font-semibold">Show data for</div>
              <div className="text-xs text-muted-foreground">Every page follows what you pick here.</div>
            </div>
            <ScopePanel tree={tree} onDone={() => setOpen(false)} inMenu />
          </DropdownMenuContent>
        </DropdownMenu>
      )}
    </nav>
  )
}

type Reporting = Map<string, { reported: boolean; workers: number }>

function ScopePanel({ tree, onDone, inMenu }: { tree: Tree; onDone: () => void; inMenu: boolean }) {
  const { scope, setPortfolioScope, setProjectScope, setSiteScope } = useScope()
  const allowed = useAllowedScopes()
  const [q, setQ] = React.useState('')
  const [today] = React.useState(() => localIsoDate(new Date()))
  // Today's reporting for every site (the Today page's rule, hasUpdates) this person sees: the same request the Today page makes for all projects.
  const days = useQuery({
    queryKey: ['site-days', today, undefined],
    queryFn: () => fetchSiteDaysApi(today, undefined),
    staleTime: 30_000,
  })
  const reporting: Reporting = React.useMemo(
    () => new Map((days.data?.items ?? []).map((s) => [s.site_id, { reported: hasUpdates(s), workers: s.workers }])),
    [days.data],
  )

  const pickProject = allowed.includes('project')
  const pickSite = allowed.includes('site')
  const needle = q.trim().toLowerCase()
  const shown = tree
    .map(({ project, sites }) => {
      const projectHit = !needle || project.name.toLowerCase().includes(needle)
      return { project, projectHit, sites: projectHit ? sites : sites.filter((s) => s.name.toLowerCase().includes(needle)) }
    })
    .filter((t) => t.projectHit || t.sites.length)
  const totalRows = tree.length + tree.reduce((n, t) => n + t.sites.length, 0)

  const recent = React.useMemo(() => {
    if (needle) return []
    const cur = scope.mode === 'portfolio' ? '' : `${scope.projectId}:${scope.mode === 'site' ? scope.siteId : ''}`
    return readRecentScopes()
      .filter((r) => `${r.projectId}:${r.siteId ?? ''}` !== cur)
      .map((r) => {
        const t = tree.find((x) => x.project.id === r.projectId)
        const site = r.siteId ? t?.sites.find((s) => s.id === r.siteId) : undefined
        if (!t || (r.siteId && !site) || (!r.siteId && !pickProject) || (r.siteId && !pickSite)) return null
        return { project: t.project, site }
      })
      .filter((x): x is { project: ProjectItem; site: SiteItem | undefined } => !!x)
      .slice(0, 3)
  }, [needle, scope, tree, pickProject, pickSite])

  const go = (fn: () => void) => () => {
    fn()
    onDone()
  }
  const isCurrent = (s: AppScope['mode'], projectId?: string, siteId?: string) =>
    scope.mode === s &&
    (s === 'portfolio' || (scope.mode !== 'portfolio' && scope.projectId === projectId)) &&
    (s !== 'site' || (scope.mode === 'site' && scope.siteId === siteId))

  const reportLine = (sites: SiteItem[]) => {
    if (!sites.length || !days.data) return sites.length ? `${sites.length} ${sites.length === 1 ? 'site' : 'sites'}` : 'No sites yet'
    const n = sites.filter((s) => reporting.get(s.id)?.reported).length
    return `${n} of ${sites.length} ${sites.length === 1 ? 'site' : 'sites'} reported today`
  }
  const allSites = tree.flatMap((t) => t.sites)

  return (
    <div className="flex max-h-[min(70svh,32rem)] flex-col">
      {totalRows > 6 && (
        <div className="relative border-b px-3 py-2">
          <Search className="pointer-events-none absolute top-1/2 left-5 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <input
            autoFocus={!inMenu}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            // Typing goes to the box, not the menu's jump-to-letter.
            onKeyDown={(e) => e.key !== 'Escape' && e.key !== 'ArrowDown' && e.stopPropagation()}
            placeholder="Find a project or site"
            className="h-9 w-full rounded-md border bg-background pr-2 pl-8 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
            aria-label="Find a project or site"
          />
        </div>
      )}
      <div className="flex-1 overflow-y-auto p-1.5">
        {recent.length > 0 && (
          <Group title="Recent">
            {recent.map(({ project, site }) => (
              <Row
                key={`${project.id}:${site?.id ?? ''}`}
                inMenu={inMenu}
                level={site ? 'site' : 'project'}
                name={site ? site.name : project.name}
                note={site ? project.name : reportLine(tree.find((t) => t.project.id === project.id)?.sites ?? [])}
                onPick={go(() => (site ? setSiteScope(project, site) : setProjectScope(project)))}
              />
            ))}
          </Group>
        )}
        {allowed.includes('portfolio') && !needle && (
          <Group title="Company">
            <Row
              inMenu={inMenu}
              level="portfolio"
              name="All projects"
              note={tree.length ? `${tree.length} ${tree.length === 1 ? 'project' : 'projects'} · ${reportLine(allSites)}` : 'Every project together'}
              current={isCurrent('portfolio')}
              onPick={go(setPortfolioScope)}
            />
          </Group>
        )}
        <Group title={pickProject ? 'Projects and their sites' : 'Your sites'}>
          {shown.map(({ project, sites }) => (
            <div key={project.id} className="py-0.5">
              {pickProject ? (
                <Row
                  inMenu={inMenu}
                  level="project"
                  name={project.name}
                  note={pickSite ? reportLine(sites) : 'Whole project'}
                  current={isCurrent('project', project.id)}
                  onPick={go(() => setProjectScope(project))}
                />
              ) : (
                <div className="px-2 pt-1.5 pb-0.5 text-xs font-medium text-muted-foreground">{project.name}</div>
              )}
              {pickSite &&
                sites.map((site) => {
                  const r = reporting.get(site.id)
                  return (
                    <Row
                      key={site.id}
                      inMenu={inMenu}
                      level="site"
                      indent={pickProject}
                      name={site.name}
                      note={!days.data ? undefined : r?.reported ? `Reported today${r.workers ? ` · ${r.workers} workers` : ''}` : 'Not reported yet today'}
                      dot={!days.data ? undefined : r?.reported ? 'good' : 'wait'}
                      current={isCurrent('site', project.id, site.id)}
                      onPick={go(() => setSiteScope(project, site))}
                    />
                  )
                })}
            </div>
          ))}
          {!shown.length && <p className="px-2 py-6 text-center text-sm text-muted-foreground">Nothing called “{q.trim()}”.</p>}
        </Group>
      </div>
    </div>
  )
}

function Group({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="pb-1">
      <div className="px-2 pt-2 pb-1 text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">{title}</div>
      {children}
    </div>
  )
}

function Row({
  inMenu,
  level,
  name,
  note,
  current,
  indent,
  dot,
  onPick,
}: {
  inMenu: boolean
  level: AppScope['mode']
  name: string
  note?: string
  current?: boolean
  indent?: boolean
  dot?: 'good' | 'wait'
  onPick: () => void
}) {
  const Icon = SCOPE_ICON[level]
  const body = (
    <>
      <span className={cn('flex size-7 shrink-0 items-center justify-center rounded-md', SCOPE_TONE[level])}>
        <Icon className="size-3.5" aria-hidden />
      </span>
      <span className="min-w-0 flex-1 text-left">
        <span className="block truncate text-sm font-medium">{name}</span>
        {note && (
          <span className="flex items-center gap-1.5 truncate text-xs text-muted-foreground">
            {dot && <span className={cn('size-1.5 shrink-0 rounded-full', dot === 'good' ? 'bg-success' : 'bg-amber-500')} aria-hidden />}
            {note}
          </span>
        )}
      </span>
      {current && <Check className="size-4 shrink-0 text-primary-ink" aria-label="Showing now" />}
    </>
  )
  const cls = cn(
    'flex w-full cursor-pointer items-center gap-2.5 rounded-md px-2 py-1.5',
    indent && 'pl-7',
    current && 'bg-muted',
  )
  if (inMenu) {
    return (
      <DropdownMenuItem className={cls} onSelect={onPick}>
        {body}
      </DropdownMenuItem>
    )
  }
  return (
    <button type="button" className={cn(cls, 'hover:bg-muted active:bg-muted')} onClick={onPick}>
      {body}
    </button>
  )
}
