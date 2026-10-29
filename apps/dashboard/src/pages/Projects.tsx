import * as React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchSiteDaysApi } from '@/lib/api'
import { fetchAllOpenIssues } from '@/lib/issues'
import { FROZEN, hasUpdates, localIsoDate } from '@/lib/site-day'
import { Link } from 'react-router-dom'
import { Archive, Building2, Clock, MapPin, MoreHorizontal, Pencil, Plus, Search, Users } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { useToast } from '@/components/ui/toast-notification'
import { PageError, PageHeader } from '@/components/dpr-page'
import { ROW_ACCENT } from '@/lib/cues'
import { AddEditProjectDialog } from '@/components/project-dialogs'
import { archiveProject, fetchProjectMembers, fetchProjectsFull, fetchSitesFull, type Project } from '@/lib/projects'
import { CHIP, plural } from '@/lib/site-day'
import { usePageTitle } from '@/lib/page-title'
import { useUrlState } from '@/lib/url-state'
import { FilterSelect } from '@/components/filter-select'
import { useReadOnly } from '@/lib/trial'
import { cn, formatClock } from '@/lib/utils'

// WEB-28: Projects & Sites as rows that say what each project is set up
// with -- its sites, its people, when its DPR goes out -- instead of
// coloured count tiles and "NO-CODE • No Client • No Location".

type Show = 'current' | 'paused' | 'all'

/** Projects not being worked on now: kept out of the default list. */
const PAUSED = ['On Hold', 'Completed', 'Archived']

const STATUS_CHIP: Record<string, string> = {
  success: 'bg-success-soft text-success',
  warning: 'bg-draft-soft text-draft',
  critical: 'bg-destructive/10 text-destructive',
  neutral: 'bg-muted text-muted-foreground',
}

export default function Projects() {
  const readOnly = useReadOnly()
  const toast = useToast()
  const queryClient = useQueryClient()
  usePageTitle('Projects & Sites')
  const [search, setSearch] = useUrlState<string>('q', '')
  const [show, setShow] = useUrlState<Show>('show', 'current')
  const [editing, setEditing] = React.useState<Project | null>(null)
  const [dialogOpen, setDialogOpen] = React.useState(false)
  const [archiving, setArchiving] = React.useState<Project | null>(null)

  const query = useQuery<Project[]>({ queryKey: ['projects-list'], queryFn: fetchProjectsFull })
  // WEB-37: today at a glance on each project -- sites reported and open
  // issues -- from the same reads Today uses (cached between the pages).
  const [today] = React.useState(() => localIsoDate(new Date()))
  const days = useQuery({ queryKey: ['site-days', today, undefined], queryFn: () => fetchSiteDaysApi(today) })
  const openIssues = useQuery({ queryKey: ['today-open-issues', undefined], queryFn: () => fetchAllOpenIssues(undefined) })
  const todayFor = (projectId: string): ProjectToday | undefined => {
    if (!days.data) return undefined
    const sites = days.data.items.filter((d) => d.project_id === projectId)
    const issues = (openIssues.data ?? []).filter((i) => i.project_id === projectId)
    return {
      sites: sites.length,
      reported: sites.filter((d) => hasUpdates(d) || FROZEN.includes(d.status)).length,
      issues: issues.length,
      urgent: issues.filter((i) => ['CRITICAL', 'HIGH'].includes(i.severity.toUpperCase())).length,
    }
  }
  const projects = React.useMemo(() => query.data ?? [], [query.data])

  const archive = useMutation({
    mutationFn: archiveProject,
    onSuccess: (_, id) => {
      const name = projects.find((p) => p.id === id)?.name ?? 'The project'
      toast.success('Archived', `${name} is off the active list.`)
      setArchiving(null)
      queryClient.invalidateQueries({ queryKey: ['projects-list'] })
      queryClient.invalidateQueries({ queryKey: ['scope-projects'] })
    },
    onError: () => toast.error('Could not archive', 'Please try again.'),
  })

  const paused = projects.filter((p) => PAUSED.includes(p.statusLabel))
  const current = projects.length - paused.length
  const visible = projects
    .filter((p) => (show === 'all' ? true : show === 'paused' ? PAUSED.includes(p.statusLabel) : !PAUSED.includes(p.statusLabel)))
    .filter((p) => {
      const q = search.trim().toLowerCase()
      return !q || [p.name, p.code, p.client, p.location].some((v) => v?.toLowerCase().includes(q))
    })
    .sort((a, b) => a.name.localeCompare(b.name))

  const openNew = () => {
    setEditing(null)
    setDialogOpen(true)
  }

  if (query.isError) {
    return <PageError message="Your projects could not be loaded." onRetry={() => query.refetch()} back={{ to: '/today', label: 'Back to Today' }} />
  }

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-4 pb-8 sm:px-2">
      <PageHeader
        title="Projects & Sites"
        subtitle={query.isLoading ? 'Loading…' : `${plural(current, 'project')} running${paused.length ? ` · ${paused.length} paused or done` : ''}`}
        actions={
          !readOnly && (
            <Button size="sm" className="gap-1.5 font-semibold" onClick={openNew}>
              <Plus className="size-4" /> New project
            </Button>
          )
        }
      />

      {projects.length > 3 || paused.length > 0 ? (
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative w-full sm:w-64">
            <Search className="absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
            <Input placeholder="Search projects…" aria-label="Search projects" value={search} onChange={(e) => setSearch(e.target.value)} className="h-9 pl-8" />
          </div>
          {paused.length > 0 && (
            <FilterSelect<Show>
              label="Show"
              value={show}
              onChange={setShow}
              className="h-9 w-[180px]"
              options={[
                { value: 'current', label: `Running · ${current}` },
                { value: 'paused', label: `Paused or done · ${paused.length}` },
                { value: 'all', label: 'All projects' },
              ]}
            />
          )}
        </div>
      ) : null}

      {query.isLoading ? (
        <div className="flex flex-col gap-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-20 rounded-lg" />
          ))}
        </div>
      ) : projects.length === 0 ? (
        <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed py-14 text-center">
          <Building2 className="size-6 text-muted-foreground" aria-hidden="true" />
          <p className="font-medium">No projects yet</p>
          <p className="max-w-sm text-sm text-muted-foreground">Add a project and its sites; site updates on WhatsApp then land in its daily report.</p>
          {!readOnly && (
            <Button className="mt-2 gap-1.5" onClick={openNew}>
              <Plus className="size-4" /> New project
            </Button>
          )}
        </div>
      ) : visible.length === 0 ? (
        <p className="rounded-xl border border-dashed py-10 text-center text-sm text-muted-foreground">No projects match.</p>
      ) : (
        <ul className="flex flex-col divide-y rounded-xl border">
          {visible.map((project) => (
            <ProjectRow
              key={project.id}
              project={project}
              today={todayFor(project.id)}
              readOnly={readOnly}
              onEdit={() => {
                setEditing(project)
                setDialogOpen(true)
              }}
              onArchive={() => setArchiving(project)}
            />
          ))}
        </ul>
      )}

      <AddEditProjectDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        project={editing}
        onSuccess={() => queryClient.invalidateQueries({ queryKey: ['projects-list'] })}
      />

      <Dialog open={archiving !== null} onOpenChange={(open) => !open && setArchiving(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="text-base font-semibold">Archive {archiving?.name}?</DialogTitle>
            <DialogDescription>
              It leaves the active list and its daily report stops. Its reports and records are kept.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setArchiving(null)}>
              Cancel
            </Button>
            <Button variant="destructive" disabled={archive.isPending} onClick={() => archiving && archive.mutate(archiving.id)}>
              {archive.isPending ? 'Archiving…' : 'Archive'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

function ProjectRow({
  project,
  readOnly,
  onEdit,
  onArchive,
  today,
}: {
  project: Project
  today?: ProjectToday
  readOnly: boolean
  onEdit: () => void
  onArchive: () => void
}) {
  const sites = useQuery({ queryKey: ['project-sites-count', project.id], queryFn: () => fetchSitesFull(project.id) })
  const members = useQuery({ queryKey: ['project-members-count', project.id], queryFn: () => fetchProjectMembers(project.id) })
  const siteList = sites.data ?? []
  const people = members.data?.length ?? 0
  const facts = [project.client && `Client: ${project.client}`, project.location, project.code].filter(Boolean)

  return (
    <li
      className={cn(
        'flex flex-col gap-2 px-4 py-3 sm:flex-row sm:items-center sm:gap-4',
        today?.urgent ? ROW_ACCENT.bad : today && today.sites > 0 && today.reported === today.sites ? ROW_ACCENT.good : ROW_ACCENT.none,
      )}
    >
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <div className="flex flex-wrap items-center gap-2">
          <Link to={`/projects/${project.id}`} className="font-semibold hover:underline">
            {project.name}
          </Link>
          <span className={cn(CHIP, STATUS_CHIP[project.status] ?? STATUS_CHIP.neutral)}>{project.statusLabel}</span>
        </div>
        {facts.length > 0 && <p className="text-sm text-muted-foreground">{facts.join(' · ')}</p>}
        {today && today.sites > 0 && <TodayLine today={today} />}
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
          <span className="inline-flex items-center gap-1.5">
            <MapPin className="size-3.5 text-muted-foreground" aria-hidden="true" />
            {sites.isLoading ? '…' : siteList.length === 0 ? <span className="text-draft">No sites yet</span> : siteList.map((s) => s.name).join(', ')}
          </span>
          <span className="inline-flex items-center gap-1.5">
            <Users className="size-3.5 text-muted-foreground" aria-hidden="true" />
            {members.isLoading ? '…' : people === 0 ? <span className="text-muted-foreground">Admins only</span> : people === 1 ? '1 person' : `${people} people`}
          </span>
          <span className="inline-flex items-center gap-1.5 text-muted-foreground">
            <Clock className="size-3.5" aria-hidden="true" />
            {project.autoGenerateDpr ? `Daily cutoff ${formatClock(project.reportingCutoffTime) ?? project.reportingCutoffTime}` : 'Automatic DPR off'}
          </span>
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-1.5">
        <Button asChild variant="outline" size="sm">
          <Link to={`/projects/${project.id}`}>Open</Link>
        </Button>
        {!readOnly && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon" className="size-8" aria-label={`More for ${project.name}`}>
                <MoreHorizontal className="size-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-44">
              <DropdownMenuItem onClick={onEdit}>
                <Pencil className="mr-2 size-3.5" /> Edit details
              </DropdownMenuItem>
              <DropdownMenuItem asChild>
                <Link to={`/today?project=${project.id}`}>
                  <Building2 className="mr-2 size-3.5" /> Today's updates
                </Link>
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={onArchive} className="text-destructive focus:text-destructive">
                <Archive className="mr-2 size-3.5" /> Archive
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </div>
    </li>
  )
}

type ProjectToday = { sites: number; reported: number; issues: number; urgent: number }

/** "Today: 1 of 2 sites reported · 2 open issues", coloured by how it stands. */
function TodayLine({ today }: { today: ProjectToday }) {
  const all = today.reported === today.sites
  return (
    <p className="flex flex-wrap items-center gap-1.5 text-sm">
      <span className="text-muted-foreground">Today:</span>
      <span className={cn(CHIP, all ? 'bg-success-soft text-success' : today.reported ? 'bg-draft-soft text-draft' : 'bg-muted text-muted-foreground')}>
        {today.reported} of {today.sites} {today.sites === 1 ? 'site' : 'sites'} reported
      </span>
      {today.issues > 0 && (
        <span className={cn(CHIP, today.urgent ? 'bg-destructive/10 text-destructive' : 'bg-draft-soft text-draft')}>
          {today.issues} open {today.issues === 1 ? 'issue' : 'issues'}
          {today.urgent ? ` · ${today.urgent} urgent` : ''}
        </span>
      )}
    </p>
  )
}
