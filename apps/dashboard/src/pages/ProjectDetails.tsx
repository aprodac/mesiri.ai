import * as React from 'react'
import { useParams, useNavigate, Link, useSearchParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft,
  Building2,
  Users as UsersIcon,
  MessageSquare,
  History,
  Settings as SettingsIcon,
  Edit2,
  FolderLock,
  Plus,
  Trash2,
  Loader2,
  ShieldAlert,
  Search,
  ChevronDown,
  Send,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from '@/components/ui/table'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  fetchProject,
  fetchSitesFull,
  fetchProjectMembers,
  archiveProject,
  archiveSite,
  removeProjectMember,
  type Project,
  type Site,
  type ProjectMember,
} from '@/lib/projects'
import {
  AddEditProjectDialog,
  AddEditSiteDialog,
  ProjectMemberDialog,
} from '@/components/project-dialogs'
import { ProjectReportingTab } from '@/components/project-reporting-tab'
import { ProjectRecipientsTab } from '@/components/project-recipients-tab'
import { ProjectClientLogoCard } from '@/components/project-client-logo-card'
import { ProjectOverviewTab } from '@/components/project-overview-tab'
import { useModuleEnabled } from '@/lib/modules'

const STATUS_BADGES = {
  success: 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border-none',
  warning: 'bg-yellow-500/10 text-yellow-700 dark:text-yellow-400 border-none',
  critical: 'bg-rose-500/10 text-rose-700 dark:text-rose-400 border-none',
  neutral: 'bg-muted text-muted-foreground border-none',
} as const

export default function ProjectDetails() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const isModuleEnabled = useModuleEnabled()
  const queryClient = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()
  const isNewProject = searchParams.get('new') === '1'

  const handleDismissBanner = () => {
    const nextParams = new URLSearchParams(searchParams)
    nextParams.delete('new')
    setSearchParams(nextParams, { replace: true })
  }

  const [activeTab, setActiveTab] = React.useState<'overview' | 'sites' | 'members' | 'reporting' | 'recipients' | 'whatsapp' | 'settings'>('overview')

  // Dialog open states
  const [projectDialogOpen, setProjectDialogOpen] = React.useState(false)
  const [siteDialogOpen, setSiteDialogOpen] = React.useState(false)
  const [memberDialogOpen, setMemberDialogOpen] = React.useState(false)
  
  // Selected entities for editing
  const [selectedSite, setSelectedSite] = React.useState<Site | null>(null)

  // Search states inside tabs
  const [siteSearch, setSiteSearch] = React.useState('')
  const [memberSearch, setMemberSearch] = React.useState('')

  // Queries
  const { data: project, isLoading, isError, error } = useQuery<Project>({
    queryKey: ['project-details', id],
    queryFn: () => fetchProject(id!),
    enabled: !!id,
  })

  const { data: sites = [], isLoading: isSitesLoading } = useQuery<Site[]>({
    queryKey: ['project-sites', id],
    queryFn: () => fetchSitesFull(id!),
    enabled: !!id,
  })

  const { data: members = [], isLoading: isMembersLoading } = useQuery<ProjectMember[]>({
    queryKey: ['project-members', id],
    queryFn: () => fetchProjectMembers(id!),
    enabled: !!id,
  })

  // Mutations
  const archiveProjectMutation = useMutation({
    mutationFn: () => archiveProject(id!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projects-list'] })
      queryClient.invalidateQueries({ queryKey: ['scope-projects'] })
      navigate('/projects')
    },
    onError: (err: any) => {
      alert(err.response?.data?.detail || 'Failed to archive project.')
    },
  })

  const archiveSiteMutation = useMutation({
    mutationFn: (siteId: string) => archiveSite(id!, siteId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['project-sites', id] })
    },
    onError: (err: any) => {
      alert(err.response?.data?.detail || 'Failed to archive site.')
    },
  })

  const removeMemberMutation = useMutation({
    mutationFn: (userId: string) => removeProjectMember(id!, userId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['project-members', id] })
    },
    onError: (err: any) => {
      alert(err.response?.data?.detail || 'Failed to remove project member.')
    },
  })

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center text-sm text-muted-foreground gap-2">
        <Loader2 className="size-4 animate-spin text-primary" />
        Loading project administration panel...
      </div>
    )
  }

  if (isError || !project) {
    return (
      <div className="space-y-4 text-xs">
        <Link to="/projects" className="flex items-center gap-1 text-muted-foreground hover:text-foreground">
          <ArrowLeft className="size-3" /> Back to Projects & Sites
        </Link>
        <div className="bg-destructive/10 border border-destructive text-destructive p-4 rounded text-center">
          Failed to load project details: {error instanceof Error ? error.message : 'Project not found.'}
        </div>
      </div>
    )
  }

  const handleOpenProject = () => {
    navigate(`/overview?project=${project.id}`)
  }

  const handleOpenSite = (site: Site) => {
    navigate(`/overview?project=${project.id}&site=${site.id}`)
  }

  // Filters site list
  const filteredSites = sites.filter(
    (s) =>
      s.name.toLowerCase().includes(siteSearch.toLowerCase()) ||
      s.status.toLowerCase().includes(siteSearch.toLowerCase())
  )

  // Filters member list
  const filteredMembers = members.filter(
    (m) =>
      m.fullName.toLowerCase().includes(memberSearch.toLowerCase()) ||
      m.email.toLowerCase().includes(memberSearch.toLowerCase()) ||
      m.role.toLowerCase().includes(memberSearch.toLowerCase())
  )

  return (
    <div className="flex flex-col gap-4 text-sm">
      {/* Header section */}
      <div className="flex flex-col gap-1.5">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b pb-4">
          <div className="flex items-center gap-3">
            <div className="size-10 rounded-full border border-primary/20 bg-primary/10 flex items-center justify-center text-primary shrink-0">
              <Building2 className="size-5" />
            </div>
            <div>
              <h1 className="text-lg font-bold text-foreground flex items-center gap-2 leading-none">
                {project.name}
                <Badge variant="outline" className={`text-xs rounded-sm py-0.5 ${STATUS_BADGES[project.status as keyof typeof STATUS_BADGES] || STATUS_BADGES.neutral}`}>
                  {project.statusLabel || project.status}
                </Badge>
              </h1>
              <span className="text-xs text-muted-foreground font-mono">
                {project.code || 'NO-CODE'} · {project.client || 'No Client'} · {project.location || 'No Location'}
              </span>
            </div>
          </div>
          <div className="flex gap-2">
            <Button size="sm" onClick={handleOpenProject} className="h-7 gap-1">
              Open Project
            </Button>
            {isModuleEnabled('finance') && (
              <Button
                size="sm"
                variant="outline"
                onClick={() => navigate(`/finance/expenses?project_id=${project.id}`)}
                className="h-7 gap-1 text-emerald-600 border-emerald-500/40 hover:bg-emerald-500/10 font-semibold"
              >
                View Finance
              </Button>
            )}
            <Button size="sm" variant="outline" onClick={() => setProjectDialogOpen(true)} className="h-7 gap-1">
              <Edit2 className="size-3" /> Edit Settings
            </Button>
          </div>
        </div>
      </div>

      {/* Internal Tabs list */}
      <div className="flex border-b border-border/60 gap-4 font-semibold text-muted-foreground overflow-x-auto">
        <button
          onClick={() => setActiveTab('overview')}
          className={`pb-2 border-b-2 transition-colors ${
            activeTab === 'overview' ? 'border-primary text-foreground' : 'border-transparent hover:text-foreground'
          } flex items-center gap-1.5 whitespace-nowrap`}
        >
          <Building2 className="size-3.5" />
          Overview
        </button>
        <button
          onClick={() => setActiveTab('sites')}
          className={`pb-2 border-b-2 transition-colors ${
            activeTab === 'sites' ? 'border-primary text-foreground' : 'border-transparent hover:text-foreground'
          } flex items-center gap-1.5 whitespace-nowrap`}
        >
          <FolderLock className="size-3.5" />
          Sites ({sites.length})
        </button>
        <button
          onClick={() => setActiveTab('members')}
          className={`pb-2 border-b-2 transition-colors ${
            activeTab === 'members' ? 'border-primary text-foreground' : 'border-transparent hover:text-foreground'
          } flex items-center gap-1.5 whitespace-nowrap`}
        >
          <UsersIcon className="size-3.5" />
          Members ({members.length})
        </button>
        <button
          onClick={() => setActiveTab('reporting')}
          className={`pb-2 border-b-2 transition-colors ${
            activeTab === 'reporting' ? 'border-primary text-foreground' : 'border-transparent hover:text-foreground'
          } flex items-center gap-1.5 whitespace-nowrap`}
        >
          <History className="size-3.5" />
          Reporting
        </button>
        <button
          onClick={() => setActiveTab('recipients')}
          className={`pb-2 border-b-2 transition-colors ${
            activeTab === 'recipients' ? 'border-primary text-foreground' : 'border-transparent hover:text-foreground'
          } flex items-center gap-1.5 whitespace-nowrap`}
        >
          <Send className="size-3.5" />
          DPR Recipients
        </button>
        <button
          onClick={() => setActiveTab('whatsapp')}
          className={`pb-2 border-b-2 transition-colors ${
            activeTab === 'whatsapp' ? 'border-primary text-foreground' : 'border-transparent hover:text-foreground'
          } flex items-center gap-1.5 whitespace-nowrap`}
        >
          <MessageSquare className="size-3.5" />
          WhatsApp
        </button>
        <button
          onClick={() => setActiveTab('settings')}
          className={`pb-2 border-b-2 transition-colors ${
            activeTab === 'settings' ? 'border-primary text-foreground' : 'border-transparent hover:text-foreground'
          } flex items-center gap-1.5 whitespace-nowrap`}
        >
          <SettingsIcon className="size-3.5" />
          Settings
        </button>
      </div>

      {/* Tab Panels */}
      <div className="py-1">
        {activeTab === 'overview' && (
          <div className="space-y-4">
            {isNewProject && (
              <div className="bg-emerald-500/10 border border-emerald-500/30 text-emerald-700 dark:text-emerald-400 p-3 rounded-sm flex justify-between items-center text-xs">
                <span>Project created successfully. Add sites, members, and configure reporting when ready.</span>
                <button
                  type="button"
                  onClick={handleDismissBanner}
                  className="text-xs font-semibold text-emerald-700 dark:text-emerald-400 hover:underline"
                >
                  Dismiss
                </button>
              </div>
            )}
            <ProjectOverviewTab
              project={project}
              sites={sites}
              members={members}
              setActiveTab={setActiveTab}
              setProjectDialogOpen={setProjectDialogOpen}
              setMemberDialogOpen={setMemberDialogOpen}
            />
          </div>
        )}

        {activeTab === 'sites' && (
          <Card className="rounded-none border-border/70 shadow-none">
            <CardHeader className="pb-3 border-b flex flex-row items-center justify-between gap-4">
              <div>
                <CardTitle className="text-xs uppercase tracking-wider text-muted-foreground font-semibold">
                  Project Sites Registry
                </CardTitle>
                <CardDescription className="text-[11px]">
                  Sites represent physical locations or sub-divisions inside this project.
                </CardDescription>
              </div>
              <Button
                size="sm"
                onClick={() => {
                  setSelectedSite(null)
                  setSiteDialogOpen(true)
                }}
                className="h-8 gap-1.5"
              >
                <Plus className="size-4" />
                Add Site
              </Button>
            </CardHeader>
            <CardContent className="pt-4 space-y-3">
              <div className="flex max-w-xs gap-2">
                <Search className="size-4 text-muted-foreground self-center ml-2 absolute" />
                <Input
                  placeholder="Search sites..."
                  value={siteSearch}
                  onChange={(e) => setSiteSearch(e.target.value)}
                  className="pl-8 h-8 text-xs w-full"
                />
              </div>

              {isSitesLoading ? (
                <div className="flex justify-center text-xs py-4 text-muted-foreground">
                  <Loader2 className="size-3.5 animate-spin mr-2" /> Loading sites list...
                </div>
              ) : filteredSites.length === 0 ? (
                <div className="text-center text-xs italic text-muted-foreground py-6 border border-dashed rounded">
                  No sites registered on this project.
                </div>
              ) : (
                <div className="border border-border/60 rounded overflow-hidden">
                  <Table>
                    <TableHeader>
                      <TableRow className="bg-muted/10">
                        <TableHead>Site Name</TableHead>
                        <TableHead>Status</TableHead>
                        <TableHead className="w-24 text-right pr-4">Actions</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {filteredSites.map((site) => (
                        <TableRow key={site.id}>
                          <TableCell>
                            <span className="font-semibold text-foreground">{site.name}</span>
                          </TableCell>
                          <TableCell>
                            <Badge variant={site.status === 'active' ? 'default' : 'outline'} className="text-[9px] rounded-sm py-0">
                              {site.status}
                            </Badge>
                          </TableCell>
                          <TableCell className="text-right pr-4">
                            <DropdownMenu>
                              <DropdownMenuTrigger asChild>
                                <Button variant="ghost" className="size-8 p-0">
                                  <ChevronDown className="size-4 text-muted-foreground" />
                                </Button>
                              </DropdownMenuTrigger>
                              <DropdownMenuContent align="end" className="w-36">
                                <DropdownMenuItem onClick={() => handleOpenSite(site)}>
                                  <Building2 className="size-3.5 mr-2" />
                                  Open Site
                                </DropdownMenuItem>
                                <DropdownMenuItem onClick={() => {
                                  setSelectedSite(site)
                                  setSiteDialogOpen(true)
                                }}>
                                  <Edit2 className="size-3.5 mr-2" />
                                  Edit Site
                                </DropdownMenuItem>
                                <DropdownMenuSeparator />
                                <DropdownMenuItem
                                  onClick={() => {
                                    if (confirm(`Archive site "${site.name}"?`)) {
                                      archiveSiteMutation.mutate(site.id)
                                    }
                                  }}
                                  className="text-destructive hover:bg-destructive/10"
                                >
                                  <Trash2 className="size-3.5 mr-2" />
                                  Archive Site
                                </DropdownMenuItem>
                              </DropdownMenuContent>
                            </DropdownMenu>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}
            </CardContent>
          </Card>
        )}

        {activeTab === 'members' && (
          <Card className="rounded-none border-border/70 shadow-none">
            <CardHeader className="pb-3 border-b flex flex-row items-center justify-between gap-4">
              <div>
                <CardTitle className="text-xs uppercase tracking-wider text-muted-foreground font-semibold">
                  Project Membership Scope
                </CardTitle>
                <CardDescription className="text-[11px]">
                  Users explicitly assigned to this project.
                </CardDescription>
              </div>
              <Button size="sm" onClick={() => setMemberDialogOpen(true)} className="h-8 gap-1.5">
                <Plus className="size-4" />
                Add Member
              </Button>
            </CardHeader>
            <CardContent className="pt-4 space-y-3">
              <div className="flex max-w-xs gap-2">
                <Search className="size-4 text-muted-foreground self-center ml-2 absolute" />
                <Input
                  placeholder="Search members..."
                  value={memberSearch}
                  onChange={(e) => setMemberSearch(e.target.value)}
                  className="pl-8 h-8 text-xs w-full"
                />
              </div>

              {isMembersLoading ? (
                <div className="flex justify-center text-xs py-4 text-muted-foreground">
                  <Loader2 className="size-3.5 animate-spin mr-2" /> Loading members list...
                </div>
              ) : filteredMembers.length === 0 ? (
                <div className="text-center text-xs italic text-muted-foreground py-6 border border-dashed rounded">
                  No members assigned to this project.
                </div>
              ) : (
                <div className="border border-border/60 rounded overflow-hidden">
                  <Table>
                    <TableHeader>
                      <TableRow className="bg-muted/10">
                        <TableHead>User Name</TableHead>
                        <TableHead>Email</TableHead>
                        <TableHead>Project Role</TableHead>
                        <TableHead className="w-20 text-right pr-4">Actions</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {filteredMembers.map((member) => (
                        <TableRow key={member.userId}>
                          <TableCell>
                            <span className="font-semibold text-foreground">{member.fullName}</span>
                          </TableCell>
                          <TableCell className="font-mono text-muted-foreground text-[10px]">{member.email}</TableCell>
                          <TableCell>
                            <Badge variant="outline" className="text-[9px] rounded-sm py-0">
                              {member.role}
                            </Badge>
                          </TableCell>
                          <TableCell className="text-right pr-4">
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => {
                                if (confirm(`Remove "${member.fullName}" from this project?`)) {
                                  removeMemberMutation.mutate(member.userId)
                                }
                              }}
                              className="text-destructive hover:bg-destructive/10 size-8 p-0"
                            >
                              <Trash2 className="size-4" />
                            </Button>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}
            </CardContent>
          </Card>
        )}

        {activeTab === 'reporting' && (
          <ProjectReportingTab project={project} />
        )}

        {activeTab === 'recipients' && <ProjectRecipientsTab projectId={project.id} />}

        {activeTab === 'whatsapp' && (
          <Card className="rounded-none border-border/70 shadow-none">
            <CardHeader className="pb-3 border-b">
              <CardTitle className="text-xs uppercase tracking-wider text-muted-foreground font-semibold">
                WhatsApp Connection Link
              </CardTitle>
            </CardHeader>
            <CardContent className="pt-6 space-y-4">
              <div className="bg-yellow-500/5 border border-yellow-500/20 text-muted-foreground p-3.5 rounded text-[11px] flex gap-2.5">
                <ShieldAlert className="size-4 text-yellow-600 dark:text-yellow-400 shrink-0" />
                <div>
                  <strong className="block text-foreground mb-0.5">Integration Deferred (V2)</strong>
                  Interactive WhatsApp ingestion group-linking and participant configuration is deferred until the core WhatsApp webhook ingestion architecture is fully deployed.
                </div>
              </div>

              <div className="border border-dashed p-10 text-center text-muted-foreground text-xs italic">
                No active WhatsApp group links mapped for this project.
              </div>
            </CardContent>
          </Card>
        )}

        {activeTab === 'settings' && (
          <div className="space-y-4">
            <ProjectClientLogoCard projectId={project.id} clientName={project.client} />

            {/* Project edit triggers */}
            <Card className="rounded-none border-border/70 shadow-none">
              <CardHeader className="pb-3 border-b">
                <CardTitle className="text-xs uppercase tracking-wider text-muted-foreground font-semibold">
                  Metadata Configurations
                </CardTitle>
              </CardHeader>
              <CardContent className="pt-4 flex flex-wrap gap-3">
                <Button variant="outline" size="sm" onClick={() => setProjectDialogOpen(true)}>
                  Modify Info Sheet
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    if (confirm('Archive this project? This removes it from active list views.')) {
                      archiveProjectMutation.mutate()
                    }
                  }}
                >
                  Archive Project
                </Button>
              </CardContent>
            </Card>

            {/* Danger Zone */}
            <Card className="rounded-none border-destructive/20 shadow-none">
              <CardHeader className="pb-3 border-b bg-destructive/5">
                <CardTitle className="text-xs uppercase tracking-wider text-destructive font-semibold">
                  Danger Zone
                </CardTitle>
              </CardHeader>
              <CardContent className="pt-4 space-y-3">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                  <div className="flex flex-col gap-0.5">
                    <span className="font-semibold text-foreground">Permanently Delete Project</span>
                    <span className="text-[11.5px] text-muted-foreground">
                      This action is highly protected. It will delete the project metadata and all nested site records.
                    </span>
                  </div>
                  <Button
                    variant="destructive"
                    size="sm"
                    onClick={() => {
                      alert('Delete action aborted. Mercon project files containing active records must be archived instead of permanently deleted to preserve organization timeline history.')
                    }}
                    className="shrink-0 text-xs"
                  >
                    Delete Project
                  </Button>
                </div>
              </CardContent>
            </Card>
          </div>
        )}
      </div>

      {/* Dialog Containers */}
      <AddEditProjectDialog
        open={projectDialogOpen}
        onOpenChange={setProjectDialogOpen}
        project={project}
        onSuccess={() => queryClient.invalidateQueries({ queryKey: ['project-details', id] })}
      />

      <AddEditSiteDialog
        open={siteDialogOpen}
        onOpenChange={setSiteDialogOpen}
        projectId={project.id}
        site={selectedSite}
        onSuccess={() => queryClient.invalidateQueries({ queryKey: ['project-sites', id] })}
      />

      <ProjectMemberDialog
        open={memberDialogOpen}
        onOpenChange={setMemberDialogOpen}
        projectId={project.id}
        existingUserIds={members.map((m) => m.userId)}
        onSuccess={() => queryClient.invalidateQueries({ queryKey: ['project-members', id] })}
      />
    </div>
  )
}
