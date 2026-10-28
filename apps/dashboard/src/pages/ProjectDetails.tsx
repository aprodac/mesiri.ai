import * as React from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Archive, Clock, FileText, MapPin, MoreHorizontal, Pencil, Plus, Send, Sparkles, Trash2, Users } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { useToast } from '@/components/ui/toast-notification'
import { Callout, DprAside, DprHeader, DprSection, PageError } from '@/components/dpr-page'
import { AddEditProjectDialog, AddEditSiteDialog, ProjectMemberDialog } from '@/components/project-dialogs'
import { ProjectReportingTab } from '@/components/project-reporting-tab'
import { ProjectRecipientsTab } from '@/components/project-recipients-tab'
import { ProjectClientLogoCard } from '@/components/project-client-logo-card'
import { SiteWhatsAppGroupButton } from '@/components/site-whatsapp-group'
import {
  archiveProject,
  archiveSite,
  fetchProject,
  fetchProjectMembers,
  fetchSitesFull,
  removeProjectMember,
  type Project,
  type ProjectMember,
  type Site,
} from '@/lib/projects'
import { roleLabel } from '@/lib/permissions'
import { CHIP, localIsoDate, plural, siteDayPath } from '@/lib/site-day'
import { useModuleEnabled } from '@/lib/modules'
import { usePageTitle } from '@/lib/page-title'
import { useReadOnly } from '@/lib/trial'
import { apiErrorMessage } from '@/lib/logo-upload'
import { cn } from '@/lib/utils'

// WEB-28: one project's setup on one page -- its sites, its people, when its
// DPR goes out and who gets it -- in flat sections instead of seven tabs.
// The old "WhatsApp" tab (a "deferred to V2" notice) and "Delete project"
// (a button that only showed an alert) are gone.

const STATUS_CHIP: Record<string, string> = {
  success: 'bg-success-soft text-success',
  warning: 'bg-draft-soft text-draft',
  critical: 'bg-destructive/10 text-destructive',
  neutral: 'bg-muted text-muted-foreground',
}

/** ?tab=… from older links (the getting-started checklist) -> the section to scroll to. */
const SECTION_FOR_TAB: Record<string, string> = {
  sites: 'sites',
  members: 'people',
  reporting: 'daily-report',
  recipients: 'recipients',
  settings: 'details',
}

export default function ProjectDetails() {
  const { id = '' } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const toast = useToast()
  const readOnly = useReadOnly()
  const isModuleEnabled = useModuleEnabled()
  const queryClient = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()
  const [today] = React.useState(() => localIsoDate(new Date()))

  const [projectDialogOpen, setProjectDialogOpen] = React.useState(false)
  const [siteDialogOpen, setSiteDialogOpen] = React.useState(false)
  const [memberDialogOpen, setMemberDialogOpen] = React.useState(false)
  const [selectedSite, setSelectedSite] = React.useState<Site | null>(null)
  const [confirm, setConfirm] = React.useState<
    { kind: 'project' } | { kind: 'site'; site: Site } | { kind: 'member'; member: ProjectMember } | null
  >(null)

  const projectQuery = useQuery<Project>({ queryKey: ['project-details', id], queryFn: () => fetchProject(id), enabled: !!id })
  const sitesQuery = useQuery<Site[]>({ queryKey: ['project-sites', id], queryFn: () => fetchSitesFull(id), enabled: !!id })
  const membersQuery = useQuery<ProjectMember[]>({ queryKey: ['project-members', id], queryFn: () => fetchProjectMembers(id), enabled: !!id })
  const project = projectQuery.data
  const sites = sitesQuery.data ?? []
  const members = membersQuery.data ?? []
  usePageTitle(`${project?.name ?? 'Project'} · Projects & Sites`)

  // Older links open a tab (?tab=reporting): scroll to that section instead.
  const tab = searchParams.get('tab')
  React.useEffect(() => {
    if (!project || !tab) return
    document.getElementById(SECTION_FOR_TAB[tab] ?? '')?.scrollIntoView({ block: 'start' })
  }, [project, tab])

  const onFail = (title: string) => (err: unknown) => toast.error(title, apiErrorMessage(err))
  const archiveProjectMutation = useMutation({
    mutationFn: () => archiveProject(id),
    onSuccess: () => {
      toast.success('Archived', `${project?.name ?? 'The project'} is off the active list.`)
      queryClient.invalidateQueries({ queryKey: ['projects-list'] })
      queryClient.invalidateQueries({ queryKey: ['scope-projects'] })
      navigate('/projects')
    },
    onError: onFail('Could not archive the project'),
  })
  const archiveSiteMutation = useMutation({
    mutationFn: (siteId: string) => archiveSite(id, siteId),
    onSuccess: () => {
      setConfirm(null)
      toast.success('Site archived', 'Its reports are kept.')
      queryClient.invalidateQueries({ queryKey: ['project-sites', id] })
      queryClient.invalidateQueries({ queryKey: ['project-sites-count', id] })
    },
    onError: onFail('Could not archive the site'),
  })
  const removeMemberMutation = useMutation({
    mutationFn: (userId: string) => removeProjectMember(id, userId),
    onSuccess: () => {
      setConfirm(null)
      toast.success('Removed', 'They no longer see this project.')
      queryClient.invalidateQueries({ queryKey: ['project-members', id] })
      queryClient.invalidateQueries({ queryKey: ['project-members-count', id] })
    },
    onError: onFail('Could not remove'),
  })

  if (projectQuery.isLoading) {
    return (
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-4 sm:px-2" aria-busy="true" aria-label="Loading">
        <Skeleton className="h-4 w-40" />
        <Skeleton className="h-8 w-72" />
        <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_300px]">
          <div className="flex flex-col gap-3">
            <Skeleton className="h-28 rounded-lg" />
            <Skeleton className="h-28 rounded-lg" />
          </div>
          <Skeleton className="h-48 rounded-lg" />
        </div>
      </div>
    )
  }
  if (projectQuery.isError || !project) {
    return <PageError message="This project could not be loaded." onRetry={() => projectQuery.refetch()} back={{ to: '/projects', label: 'Back to Projects' }} />
  }

  const openSiteDialog = (site: Site | null) => {
    setSelectedSite(site)
    setSiteDialogOpen(true)
  }
  const dismissNew = () => {
    const next = new URLSearchParams(searchParams)
    next.delete('new')
    setSearchParams(next, { replace: true })
  }
  const facts = [project.client && `Client: ${project.client}`, project.location, project.code && `Code ${project.code}`].filter(Boolean)

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-4 pb-8 sm:px-2">
      <DprHeader
        back={{ to: '/projects', label: 'Projects & Sites' }}
        crumb="Project"
        title={project.name}
        chip={<span className={cn(CHIP, STATUS_CHIP[project.status] ?? STATUS_CHIP.neutral)}>{project.statusLabel}</span>}
        date={facts.join(' · ') || undefined}
        action={
          <div className="flex flex-wrap items-center gap-2">
            <Button asChild variant="outline" size="sm">
              <Link to={`/today?project=${project.id}`}>Today's updates</Link>
            </Button>
            {isModuleEnabled('finance') && (
              <Button asChild variant="outline" size="sm">
                <Link to={`/finance/expenses?project_id=${project.id}`}>Finance</Link>
              </Button>
            )}
            {!readOnly && (
              <Button size="sm" className="gap-1.5 font-semibold" onClick={() => setProjectDialogOpen(true)}>
                <Pencil className="size-3.5" /> Edit details
              </Button>
            )}
          </div>
        }
      />

      {searchParams.get('new') === '1' ? (
        <Callout
          tone="success"
          icon={Sparkles}
          action={
            <Button variant="ghost" size="sm" onClick={dismissNew}>
              Dismiss
            </Button>
          }
        >
          Project created. Add its sites and the people who report from them.
        </Callout>
      ) : !sitesQuery.isLoading && sites.length === 0 ? (
        <Callout
          tone="draft"
          icon={MapPin}
          action={
            !readOnly && (
              <Button size="sm" variant="outline" className="bg-background" onClick={() => openSiteDialog(null)}>
                Add a site
              </Button>
            )
          }
        >
          No sites yet: updates from WhatsApp need a site to land on.
        </Callout>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_300px]">
        <div className="flex min-w-0 flex-col">
          <DprSection
            id="sites"
            icon={MapPin}
            title="Sites"
            meta={sites.length || undefined}
            action={
              !readOnly && (
                <Button size="sm" variant="outline" className="gap-1.5" onClick={() => openSiteDialog(null)}>
                  <Plus className="size-3.5" /> Add site
                </Button>
              )
            }
            >
            {sitesQuery.isLoading ? (
              <Skeleton className="h-16 rounded-lg" />
            ) : sites.length > 0 ? (
              <ul className="divide-y rounded-lg border">
                {sites.map((site) => (
                  <li key={site.id} className="flex items-center gap-3 px-3 py-2">
                    <div className="flex min-w-0 flex-1 items-center gap-2">
                      <span className="font-medium">{site.name}</span>
                      {site.status !== 'active' && <span className={cn(CHIP, 'bg-muted text-muted-foreground')}>{site.status}</span>}
                    </div>
                    {!readOnly && site.status === 'active' && <SiteWhatsAppGroupButton projectId={id} siteId={site.id} />}
                    <Button asChild variant="ghost" size="sm" className="gap-1.5">
                      <Link to={siteDayPath(site.id, today)}>
                        <FileText className="size-3.5" /> Today's DPR
                      </Link>
                    </Button>
                    {!readOnly && (
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button variant="ghost" size="icon" className="size-8" aria-label={`More for ${site.name}`}>
                            <MoreHorizontal className="size-4" />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end" className="w-40">
                          <DropdownMenuItem onClick={() => openSiteDialog(site)}>
                            <Pencil className="mr-2 size-3.5" /> Rename
                          </DropdownMenuItem>
                          <DropdownMenuSeparator />
                          <DropdownMenuItem className="text-destructive focus:text-destructive" onClick={() => setConfirm({ kind: 'site', site })}>
                            <Archive className="mr-2 size-3.5" /> Archive
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    )}
                  </li>
                ))}
              </ul>
            ) : null}
          </DprSection>

          <DprSection
            id="people"
            icon={Users}
            title="People on this project"
            meta={members.length || undefined}
            action={
              !readOnly && (
                <Button size="sm" variant="outline" className="gap-1.5" onClick={() => setMemberDialogOpen(true)}>
                  <Plus className="size-3.5" /> Add person
                </Button>
              )
            }
            >
            {membersQuery.isLoading ? (
              <Skeleton className="h-16 rounded-lg" />
            ) : members.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                Only company admins see this project. Add its site engineers and managers so they can report and review.
              </p>
            ) : (
              <ul className="divide-y rounded-lg border">
                {members.map((m) => (
                  <li key={m.userId} className="flex items-center gap-3 px-3 py-2">
                    <div className="flex min-w-0 flex-1 flex-col">
                      <Link to={`/team/${m.userId}`} className="font-medium hover:underline">
                        {m.fullName}
                      </Link>
                      <span className="truncate text-xs text-muted-foreground">
                        {roleLabel(m.role)}
                        {m.email ? ` · ${m.email}` : ''}
                      </span>
                    </div>
                    {!readOnly && (
                      <Button
                        variant="ghost"
                        size="icon"
                        className="size-8 text-muted-foreground hover:text-destructive"
                        aria-label={`Remove ${m.fullName}`}
                        title="Remove from project"
                        onClick={() => setConfirm({ kind: 'member', member: m })}
                      >
                        <Trash2 className="size-4" />
                      </Button>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </DprSection>

          <DprSection id="daily-report" icon={Clock} title="Daily report">
            <ProjectReportingTab key={`${project.id}-${project.reportingCutoffTime}-${project.dprSendDeadline}-${project.autoGenerateDpr}`} project={project} readOnly={readOnly} />
          </DprSection>

          <DprSection id="recipients" icon={Send} title="Who gets the DPR">
            <ProjectRecipientsTab projectId={project.id} />
          </DprSection>
        </div>

        <DprAside>
          <section id="details" className="flex scroll-mt-20 flex-col gap-2">
            <div className="flex items-center justify-between">
              <h2 className="text-[15px] font-semibold">Details</h2>
              {!readOnly && (
                <Button variant="ghost" size="sm" onClick={() => setProjectDialogOpen(true)}>
                  Edit
                </Button>
              )}
            </div>
            <dl className="grid grid-cols-[88px_1fr] gap-x-3 gap-y-1.5 text-sm">
              {(
                [
                  ['Client', project.client],
                  ['Location', project.location],
                  ['Code', project.code],
                ] as const
              ).map(([k, v]) => (
                <React.Fragment key={k}>
                  <dt className="text-muted-foreground">{k}</dt>
                  <dd className={cn('min-w-0 break-words', !v && 'text-muted-foreground')}>{v || 'Not set'}</dd>
                </React.Fragment>
              ))}
            </dl>
            {project.description && <p className="text-sm text-muted-foreground">{project.description}</p>}
          </section>
          <section className="flex flex-col gap-2 border-t pt-4">
            <h2 className="text-[15px] font-semibold">Client logo on the DPR</h2>
            <ProjectClientLogoCard projectId={project.id} clientName={project.client} />
          </section>
          {!readOnly && (
            <section className="border-t pt-4">
              <Button variant="ghost" size="sm" className="gap-1.5 text-destructive hover:text-destructive" onClick={() => setConfirm({ kind: 'project' })}>
                <Archive className="size-3.5" /> Archive this project
              </Button>
            </section>
          )}
        </DprAside>
      </div>

      <Dialog open={confirm !== null} onOpenChange={(open) => !open && setConfirm(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="text-base font-semibold">
              {confirm?.kind === 'project'
                ? `Archive ${project.name}?`
                : confirm?.kind === 'site'
                  ? `Archive ${confirm.site.name}?`
                  : confirm?.kind === 'member'
                    ? `Remove ${confirm.member.fullName}?`
                    : ''}
            </DialogTitle>
            <DialogDescription>
              {confirm?.kind === 'project'
                ? 'It leaves the active list and its daily report stops. Its reports and records are kept.'
                : confirm?.kind === 'site'
                  ? 'Updates can no longer be sent for it. Its reports and records are kept.'
                  : `They stop seeing ${project.name}. ${plural(members.length - 1, 'person')} will be left on it.`}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirm(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              disabled={archiveProjectMutation.isPending || archiveSiteMutation.isPending || removeMemberMutation.isPending}
              onClick={() => {
                if (confirm?.kind === 'project') archiveProjectMutation.mutate()
                else if (confirm?.kind === 'site') archiveSiteMutation.mutate(confirm.site.id)
                else if (confirm?.kind === 'member') removeMemberMutation.mutate(confirm.member.userId)
              }}
            >
              {confirm?.kind === 'member' ? 'Remove' : 'Archive'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <AddEditProjectDialog
        open={projectDialogOpen}
        onOpenChange={setProjectDialogOpen}
        project={project}
        onSuccess={() => {
          queryClient.invalidateQueries({ queryKey: ['project-details', id] })
          queryClient.invalidateQueries({ queryKey: ['projects-list'] })
        }}
      />
      <AddEditSiteDialog
        open={siteDialogOpen}
        onOpenChange={setSiteDialogOpen}
        projectId={project.id}
        site={selectedSite}
        onSuccess={() => {
          queryClient.invalidateQueries({ queryKey: ['project-sites', id] })
          queryClient.invalidateQueries({ queryKey: ['project-sites-count', id] })
        }}
      />
      <ProjectMemberDialog
        open={memberDialogOpen}
        onOpenChange={setMemberDialogOpen}
        projectId={project.id}
        existingUserIds={members.map((m) => m.userId)}
        onSuccess={() => {
          queryClient.invalidateQueries({ queryKey: ['project-members', id] })
          queryClient.invalidateQueries({ queryKey: ['project-members-count', id] })
        }}
      />
    </div>
  )
}
