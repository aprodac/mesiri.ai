import * as React from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router-dom'
import {
  Search,
  Plus,
  Trash2,
  Edit2,
  ChevronDown,
  Building2,
  ExternalLink,
  Loader2,
  Grid,
  List,
  Activity,
  Clock,
  Archive,
} from 'lucide-react'
import { KpiCard } from '@/components/ui/kpi-card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
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
  DropdownMenuTrigger,
  DropdownMenuSeparator,
} from '@/components/ui/dropdown-menu'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  fetchProjectsFull,
  archiveProject,
  fetchSitesFull,
  fetchProjectMembers,
  type Project,
} from '@/lib/projects'
import { AddEditProjectDialog } from '@/components/project-dialogs'
import { useReadOnly } from '@/lib/trial'

const STATUS_BADGES = {
  success: 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border-none',
  warning: 'bg-yellow-500/10 text-yellow-700 dark:text-yellow-400 border-none',
  critical: 'bg-rose-500/10 text-rose-700 dark:text-rose-400 border-none',
  neutral: 'bg-muted text-muted-foreground border-none',
} as const

export default function Projects() {
  // Free trial over: saves are refused, so don't offer them (SS-15).
  const readOnly = useReadOnly()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  // Selection states
  const [search, setSearch] = React.useState('')
  const [statusFilter, setStatusFilter] = React.useState('ALL')
  const [sortBy, setSortBy] = React.useState<'name' | 'code' | 'status'>('name')
  
  // View mode (Table vs Grid) persisted in localStorage
  const [viewMode, setViewMode] = React.useState<'table' | 'grid'>(() => {
    const stored = localStorage.getItem('mesiri_projects_view_mode')
    return (stored as 'table' | 'grid') || 'table'
  })

  // Dialog state
  const [projectDialogOpen, setProjectDialogOpen] = React.useState(false)
  const [selectedProject, setSelectedProject] = React.useState<Project | null>(null)

  const { data: projects = [], isLoading, isError, error } = useQuery<Project[]>({
    queryKey: ['projects-list'],
    queryFn: fetchProjectsFull,
  })

  const archiveMutation = useMutation({
    mutationFn: archiveProject,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projects-list'] })
      queryClient.invalidateQueries({ queryKey: ['scope-projects'] })
    },
    onError: (err: any) => {
      alert(err.response?.data?.detail || 'Failed to archive project.')
    },
  })

  const toggleViewMode = (mode: 'table' | 'grid') => {
    setViewMode(mode)
    localStorage.setItem('mesiri_projects_view_mode', mode)
  }

  // Filtered and sorted projects
  const filteredProjects = React.useMemo(() => {
    return projects
      .filter((p) => {
        // Exclude archived projects from main list view by default unless filtered
        if (p.status === 'archived' && statusFilter !== 'archived') return false

        const matchSearch =
          p.name.toLowerCase().includes(search.toLowerCase()) ||
          (p.code && p.code.toLowerCase().includes(search.toLowerCase())) ||
          (p.client && p.client.toLowerCase().includes(search.toLowerCase())) ||
          (p.location && p.location.toLowerCase().includes(search.toLowerCase()))

        if (!matchSearch) return false

        if (statusFilter !== 'ALL') {
          if (statusFilter === 'active' && (p.status === 'on_hold' || p.status === 'archived' || p.status === 'neutral')) return false
          if (statusFilter === 'on_hold' && p.status !== 'neutral' && p.status !== 'on_hold') return false
          if (statusFilter === 'archived' && p.status !== 'archived') return false
        }

        return true
      })
      .sort((a, b) => {
        if (sortBy === 'name') return a.name.localeCompare(b.name)
        if (sortBy === 'code') return (a.code || '').localeCompare(b.code || '')
        if (sortBy === 'status') return a.status.localeCompare(b.status)
        return 0
      })
  }, [projects, search, statusFilter, sortBy])

  // Stats summaries
  const stats = React.useMemo(() => {
    const total = projects.length
    const active = projects.filter((p) => p.status !== 'archived' && p.status !== 'neutral' && p.status !== 'on_hold').length
    const onHold = projects.filter((p) => p.status === 'neutral' || p.status === 'on_hold').length
    const archived = projects.filter((p) => p.status === 'archived').length
    return { total, active, onHold, archived }
  }, [projects])

  const handleOpenProject = (project: Project) => {
    navigate(`/overview?project=${project.id}`)
  }

  return (
    <div className="flex flex-col gap-4">
      {/* Page Header */}
      <div className="flex items-center justify-between border-b pb-4">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-foreground">Projects & Sites</h1>
          <p className="text-xs text-muted-foreground">
            Manage projects, sites, members, access and reporting configuration.
          </p>
        </div>
        <div className="flex gap-2">
          {!readOnly && (
          <Button
            size="sm"
            onClick={() => {
              setSelectedProject(null)
              setProjectDialogOpen(true)
            }}
            className="h-8 gap-1.5"
          >
            <Plus className="size-4" />
            Create Project
          </Button>
          )}
        </div>
      </div>

      {/* Summary indicators */}
      <div className="grid gap-4" style={{ gridTemplateColumns: 'repeat(4, 1fr)' }}>
        <KpiCard
          title="Total Projects"
          value={<span style={{ color: '#3b82f6' }}>{stats.total}</span>}
          icon={<Building2 />}
        />
        <KpiCard
          title="Active Projects"
          value={<span style={{ color: '#10b981' }}>{stats.active}</span>}
          trend="up"
          icon={<Activity />}
        />
        <KpiCard
          title="On Hold"
          value={<span style={{ color: '#f59e0b' }}>{stats.onHold}</span>}
          icon={<Clock />}
        />
        <KpiCard
          title="Archived"
          value={<span style={{ color: '#6b7280' }}>{stats.archived}</span>}
          icon={<Archive />}
        />
      </div>

      {/* Filters & Controls */}
      <div className="flex flex-col md:flex-row gap-2 justify-between items-center border border-border/60 p-3 rounded">
        <div className="flex flex-col sm:flex-row gap-2 w-full md:w-auto flex-1">
          <div className="relative flex-1 max-w-sm">
            <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Search project name, code, client..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-9 h-9 text-xs"
            />
          </div>
          <Select value={statusFilter} onValueChange={setStatusFilter}>
            <SelectTrigger className="w-[160px] h-9">
              <SelectValue placeholder="Status Filter" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="ALL">All Active Statuses</SelectItem>
              <SelectItem value="active">Active Only</SelectItem>
              <SelectItem value="on_hold">On Hold</SelectItem>
              <SelectItem value="archived">Archived Projects</SelectItem>
            </SelectContent>
          </Select>

          <Select value={sortBy} onValueChange={(val) => setSortBy(val as any)}>
            <SelectTrigger className="w-[140px] h-9">
              <SelectValue placeholder="Sort By" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="name">Sort by Name</SelectItem>
              <SelectItem value="code">Sort by Code</SelectItem>
              <SelectItem value="status">Sort by Status</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {/* View Mode toggler */}
        <div className="flex border rounded overflow-hidden h-9 divide-x shrink-0">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => toggleViewMode('table')}
            className={`h-full rounded-none px-3 ${viewMode === 'table' ? 'bg-muted text-foreground' : 'text-muted-foreground hover:bg-muted/30'}`}
          >
            <List className="size-4" />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => toggleViewMode('grid')}
            className={`h-full rounded-none px-3 ${viewMode === 'grid' ? 'bg-muted text-foreground' : 'text-muted-foreground hover:bg-muted/30'}`}
          >
            <Grid className="size-4" />
          </Button>
        </div>
      </div>

      {/* Main List Area */}
      {isLoading ? (
        <div className="flex h-48 items-center justify-center text-sm text-muted-foreground gap-2">
          <Loader2 className="size-4 animate-spin text-primary" />
          Loading organization projects...
        </div>
      ) : isError ? (
        <div className="bg-destructive/10 border border-destructive text-destructive text-xs p-4 rounded text-center">
          Failed to load projects: {error instanceof Error ? error.message : 'Unknown API error.'}
        </div>
      ) : filteredProjects.length === 0 ? (
        <div className="border border-dashed p-12 text-center text-sm text-muted-foreground rounded-lg">
          No projects found matching the active search or filter.
        </div>
      ) : viewMode === 'table' ? (
        <div className="border border-border/60 rounded overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow className="bg-muted/10">
                <TableHead>Project</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Sites Count</TableHead>
                <TableHead>Members Count</TableHead>
                <TableHead className="w-20 text-right pr-4">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filteredProjects.map((project) => (
                <ProjectRow
                  key={project.id}
                  project={project}
                  onOpen={() => handleOpenProject(project)}
                  onEdit={() => {
                    setSelectedProject(project)
                    setProjectDialogOpen(true)
                  }}
                  onArchive={() => {
                    if (confirm(`Archive project "${project.name}"? This removes it from active list.`)) {
                      archiveMutation.mutate(project.id)
                    }
                  }}
                />
              ))}
            </TableBody>
          </Table>
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {filteredProjects.map((project) => (
            <ProjectCard
              key={project.id}
              project={project}
              onOpen={() => handleOpenProject(project)}
              onEdit={() => {
                setSelectedProject(project)
                setProjectDialogOpen(true)
              }}
              onArchive={() => {
                if (confirm(`Archive project "${project.name}"? This removes it from active list.`)) {
                  archiveMutation.mutate(project.id)
                }
              }}
            />
          ))}
        </div>
      )}

      {/* Dialog container */}
      <AddEditProjectDialog
        open={projectDialogOpen}
        onOpenChange={setProjectDialogOpen}
        project={selectedProject}
        onSuccess={() => queryClient.invalidateQueries({ queryKey: ['projects-list'] })}
      />
    </div>
  )
}

function ProjectRow({
  project,
  onOpen,
  onEdit,
  onArchive,
}: {
  project: Project
  onOpen: () => void
  onEdit: () => void
  onArchive: () => void
}) {
  // Query site and member counts asynchronously
  const { data: sites = [] } = useQuery({
    queryKey: ['project-sites-count', project.id],
    queryFn: () => fetchSitesFull(project.id),
  })

  const { data: members = [] } = useQuery({
    queryKey: ['project-members-count', project.id],
    queryFn: () => fetchProjectMembers(project.id),
  })

  return (
    <TableRow>
      <TableCell>
        <div className="flex flex-col">
          <Link
            to={`/projects/${project.id}`}
            className="font-medium text-foreground hover:underline flex items-center gap-1.5"
          >
            {project.name}
            <ExternalLink className="size-3 text-muted-foreground/60" />
          </Link>
          <span className="text-[10px] text-muted-foreground font-mono">
            {project.code || 'NO-CODE'} • {project.client || 'No Client'} • {project.location || 'No Location'}
          </span>
        </div>
      </TableCell>
      <TableCell>
        <Badge variant="outline" className={`text-[10px] rounded-sm py-0 ${STATUS_BADGES[project.status as keyof typeof STATUS_BADGES] || STATUS_BADGES.neutral}`}>
          {project.statusLabel || project.status}
        </Badge>
      </TableCell>
      <TableCell className="text-xs font-mono text-muted-foreground">{sites.length} site(s)</TableCell>
      <TableCell className="text-xs font-mono text-muted-foreground">{members.length} member(s)</TableCell>
      <TableCell className="text-right pr-4">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" className="size-8 p-0">
              <ChevronDown className="size-4 text-muted-foreground" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-40">
            <DropdownMenuItem onClick={onOpen}>
              <Building2 className="size-3.5 mr-2" />
              Open Project
            </DropdownMenuItem>
            <DropdownMenuItem asChild>
              <Link to={`/projects/${project.id}`} className="flex items-center w-full">
                <ExternalLink className="size-3.5 mr-2" />
                Admin Console
              </Link>
            </DropdownMenuItem>
            <DropdownMenuItem onClick={onEdit}>
              <Edit2 className="size-3.5 mr-2" />
              Edit Settings
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={onArchive} className="text-destructive hover:bg-destructive/10">
              <Trash2 className="size-3.5 mr-2" />
              Archive Project
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </TableCell>
    </TableRow>
  )
}

function ProjectCard({
  project,
  onOpen,
  onEdit,
  onArchive,
}: {
  project: Project
  onOpen: () => void
  onEdit: () => void
  onArchive: () => void
}) {
  const { data: sites = [] } = useQuery({
    queryKey: ['project-sites-count', project.id],
    queryFn: () => fetchSitesFull(project.id),
  })

  const { data: members = [] } = useQuery({
    queryKey: ['project-members-count', project.id],
    queryFn: () => fetchProjectMembers(project.id),
  })

  return (
    <div className="border border-border/80 bg-card p-4 space-y-3.5 rounded flex flex-col justify-between hover:border-border transition-colors">
      <div className="space-y-1">
        <div className="flex justify-between items-start gap-2">
          <Link to={`/projects/${project.id}`} className="font-bold text-foreground hover:underline text-sm leading-tight">
            {project.name}
          </Link>
          <Badge variant="outline" className={`text-[9px] rounded-sm py-0 shrink-0 ${STATUS_BADGES[project.status as keyof typeof STATUS_BADGES] || STATUS_BADGES.neutral}`}>
            {project.statusLabel || project.status}
          </Badge>
        </div>
        <span className="block text-[10px] text-muted-foreground font-mono uppercase tracking-wider">
          Code: {project.code || 'None'}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-2 text-xs border-y py-2 border-border/40">
        <div>
          <span className="text-muted-foreground block text-[10px]">Client</span>
          <span className="font-medium text-foreground">{project.client || 'None'}</span>
        </div>
        <div>
          <span className="text-muted-foreground block text-[10px]">Location</span>
          <span className="font-medium text-foreground">{project.location || 'None'}</span>
        </div>
      </div>

      <div className="flex justify-between items-center text-[11px] text-muted-foreground">
        <span>{sites.length} Sites</span>
        <span>{members.length} Members</span>
      </div>

      <div className="flex gap-2 pt-1.5">
        <Button size="sm" onClick={onOpen} className="flex-1 text-xs h-8">
          Open Project
        </Button>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" size="sm" className="h-8 w-9 p-0">
              <ChevronDown className="size-4 text-muted-foreground" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-40">
            <DropdownMenuItem asChild>
              <Link to={`/projects/${project.id}`} className="flex items-center w-full">
                <ExternalLink className="size-3.5 mr-2" />
                Admin Console
              </Link>
            </DropdownMenuItem>
            <DropdownMenuItem onClick={onEdit}>
              <Edit2 className="size-3.5 mr-2" />
              Edit Settings
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={onArchive} className="text-destructive hover:bg-destructive/10">
              <Trash2 className="size-3.5 mr-2" />
              Archive Project
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </div>
  )
}
