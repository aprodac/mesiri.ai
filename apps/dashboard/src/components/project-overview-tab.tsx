import * as React from 'react'
import {
  Building2,
  Users,
  Hash,
  MapPin,
  User,
  Clock,
  ChevronRight,
  FileText,
  CheckCircle2,
  AlertTriangle,
  Edit2,
  Plus,
} from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import type { Project, Site, ProjectMember } from '@/lib/projects'

interface ProjectOverviewTabProps {
  project: Project
  sites: Site[]
  members: ProjectMember[]
  setActiveTab: (tab: 'overview' | 'sites' | 'members' | 'reporting' | 'whatsapp' | 'settings') => void
  setProjectDialogOpen: (open: boolean) => void
  setMemberDialogOpen: (open: boolean) => void
}

const STATUS_BADGES = {
  success: 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border-emerald-500/20',
  warning: 'bg-amber-500/10 text-amber-700 dark:text-amber-400 border-amber-500/20',
  critical: 'bg-rose-500/10 text-rose-700 dark:text-rose-400 border-rose-500/20',
  neutral: 'bg-muted text-muted-foreground border-border',
} as const

const FORM_BADGE_COLORS: Record<string, string> = {
  'Work Progress': 'bg-blue-500/10 text-blue-700 dark:text-blue-400 border-blue-500/20',
  'Workforce': 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border-emerald-500/20',
  'Equipment & Machinery': 'bg-orange-500/10 text-orange-700 dark:text-orange-400 border-orange-500/20',
  'Fuel': 'bg-purple-500/10 text-purple-700 dark:text-purple-400 border-purple-500/20',
  'Material In': 'bg-teal-500/10 text-teal-700 dark:text-teal-400 border-teal-500/20',
  'Material Out': 'bg-pink-500/10 text-pink-700 dark:text-pink-400 border-pink-500/20',
  'Expenses': 'bg-indigo-500/10 text-indigo-700 dark:text-indigo-400 border-indigo-500/20',
  'Petty Cash': 'bg-violet-500/10 text-violet-700 dark:text-violet-400 border-violet-500/20',
  'Issues / Delays': 'bg-rose-500/10 text-rose-700 dark:text-rose-400 border-rose-500/20',
  'Safety': 'bg-red-500/10 text-red-700 dark:text-red-400 border-red-500/20',
  'General Updates': 'bg-cyan-500/10 text-cyan-700 dark:text-cyan-400 border-cyan-500/20',
}

export function ProjectOverviewTab({
  project,
  sites,
  members,
  setActiveTab,
  setProjectDialogOpen,
  setMemberDialogOpen,
}: ProjectOverviewTabProps) {
  const [isDescExpanded, ReactSetIsDescExpanded] = React.useState(false)

  // Filter key leadership members
  const managers = React.useMemo(() => members.filter((m) => m.role === 'PROJECT_MANAGER'), [members])
  const finance = React.useMemo(() => members.filter((m) => m.role === 'FINANCE'), [members])
  const engineers = React.useMemo(() => members.filter((m) => m.role === 'SITE_ENGINEER'), [members])

  const description = project.description || 'No description provided.'
  const shouldTruncate = description.length > 180
  const displayedDescription = (shouldTruncate && !isDescExpanded)
    ? `${description.substring(0, 180)}...`
    : description

  // Dynamic icon container style matching status
  const statusIconColor =
    project.status === 'success' ? 'text-emerald-500 dark:text-emerald-400' :
    project.status === 'warning' ? 'text-amber-500 dark:text-amber-400' :
    project.status === 'critical' ? 'text-rose-500 dark:text-rose-400' :
    'text-muted-foreground'

  return (
    <TooltipProvider>
      <div className="grid gap-4 md:grid-cols-3">
        {/* Project Information - Left/Middle (60-65%) */}
        <Card className="rounded-md border-border/70 shadow-xs md:col-span-2 flex flex-col justify-between overflow-hidden">
          <div>
            <CardHeader className="pb-3 border-b border-l-3 border-l-blue-500 flex flex-row items-center justify-between gap-4 bg-transparent">
              <div>
                <CardTitle className="text-xs uppercase tracking-wider text-blue-600 dark:text-blue-400 font-bold">
                  Project Information
                </CardTitle>
              </div>
              <Button
                variant="outline"
                size="sm"
                className="h-7 text-xs gap-1 cursor-pointer font-bold border border-blue-500/30 text-blue-600 hover:bg-blue-600 hover:text-white dark:text-blue-400 dark:hover:bg-blue-500 dark:hover:text-white bg-transparent rounded-md px-3 transition-all"
                onClick={() => setProjectDialogOpen(true)}
              >
                <Edit2 className="size-3" />
                Edit Info
              </Button>
            </CardHeader>
            <CardContent className="pt-4 space-y-4 text-sm">
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="flex items-start gap-2.5">
                  <User className="size-5 text-blue-500 dark:text-blue-400 shrink-0 mt-0.5" />
                  <div>
                    <span className="block text-xs text-muted-foreground font-semibold uppercase tracking-wider">Client</span>
                    <span className="font-semibold text-foreground text-sm">{project.client || <span className="text-muted-foreground/60 italic font-normal">Not Set</span>}</span>
                  </div>
                </div>

                <div className="flex items-start gap-2.5">
                  <MapPin className="size-5 text-amber-500 dark:text-amber-400 shrink-0 mt-0.5" />
                  <div>
                    <span className="block text-xs text-muted-foreground font-semibold uppercase tracking-wider">Location</span>
                    <span className="font-semibold text-foreground text-sm">{project.location || <span className="text-muted-foreground/60 italic font-normal">Not Set</span>}</span>
                  </div>
                </div>

                <div className="flex items-start gap-2.5">
                  <Hash className="size-5 text-indigo-500 dark:text-indigo-400 shrink-0 mt-0.5" />
                  <div>
                    <span className="block text-xs text-muted-foreground font-semibold uppercase tracking-wider">Project Code</span>
                    <span className="font-mono font-semibold text-foreground text-sm">{project.code || <span className="text-muted-foreground/60 italic font-normal">Not Set</span>}</span>
                  </div>
                </div>

                <div className="flex items-start gap-2.5">
                  <Building2 className={`size-5 shrink-0 mt-0.5 ${statusIconColor}`} />
                  <div>
                    <span className="block text-xs text-muted-foreground font-semibold uppercase tracking-wider">Status</span>
                    <Badge variant="outline" className={`text-xs rounded-sm py-0.5 mt-0.5 font-medium ${STATUS_BADGES[project.status as keyof typeof STATUS_BADGES] || STATUS_BADGES.neutral}`}>
                      {project.statusLabel || project.status}
                    </Badge>
                  </div>
                </div>
              </div>

              <div className="border-t border-border/40 pt-4 flex flex-col gap-1.5">
                <span className="text-xs text-muted-foreground font-semibold uppercase tracking-wider">Description</span>
                <p className="text-foreground leading-relaxed text-sm">
                  {displayedDescription}
                  {shouldTruncate && (
                    <button
                      type="button"
                      onClick={() => ReactSetIsDescExpanded(!isDescExpanded)}
                      className="text-primary hover:underline ml-1 font-semibold cursor-pointer"
                    >
                      {isDescExpanded ? 'Show less' : 'Show more'}
                    </button>
                  )}
                </p>
              </div>
            </CardContent>
          </div>
        </Card>

        {/* Quick Status - Right (35-40%) */}
        <Card className="rounded-md border-border/70 shadow-xs flex flex-col justify-between overflow-hidden">
          <div>
            <CardHeader className="pb-3 border-b border-l-3 border-l-violet-500 bg-transparent">
              <CardTitle className="text-xs uppercase tracking-wider text-violet-600 dark:text-violet-400 font-bold">
                Quick Status
              </CardTitle>
            </CardHeader>
            <CardContent className="pt-3 space-y-1.5 text-sm">
              {/* Sites Row */}
              <Tooltip>
                <TooltipTrigger asChild>
                  <div
                    onClick={() => setActiveTab('sites')}
                    className="flex justify-between items-center py-2 px-2.5 rounded-md hover:bg-muted/50 transition-colors cursor-pointer group"
                  >
                    <div className="flex items-center gap-2">
                      <Building2 className="size-4 text-violet-500 dark:text-violet-400" />
                      <span className="font-semibold text-foreground text-sm">Sites</span>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <span className="font-bold font-mono text-sm text-violet-600 dark:text-violet-400">{sites.length}</span>
                      <ChevronRight className="size-4 text-muted-foreground/50 group-hover:text-foreground transition-colors" />
                    </div>
                  </div>
                </TooltipTrigger>
                <TooltipContent side="left" className="p-3 w-52 space-y-2">
                  <div className="font-semibold text-xs text-muted-foreground uppercase tracking-wider">
                    Sites Preview ({sites.length})
                  </div>
                  {sites.length === 0 ? (
                    <div className="text-xs italic text-muted-foreground/80">No sites created.</div>
                  ) : (
                    <div className="space-y-1">
                      {sites.slice(0, 3).map((s) => (
                        <div key={s.id} className="flex justify-between gap-4 text-xs">
                          <span className="truncate max-w-[110px] font-medium text-foreground">{s.name}</span>
                          <span className="text-xs uppercase text-muted-foreground font-mono">{s.status}</span>
                        </div>
                      ))}
                      {sites.length > 3 && (
                        <div className="text-xs text-muted-foreground italic">+ {sites.length - 3} more...</div>
                      )}
                    </div>
                  )}
                  <div className="text-xs text-primary/80 dark:text-primary/90 font-semibold border-t border-border/40 pt-1.5 text-center">
                    Click to manage sites
                  </div>
                </TooltipContent>
              </Tooltip>

              {/* Members Row */}
              <Tooltip>
                <TooltipTrigger asChild>
                  <div
                    onClick={() => setActiveTab('members')}
                    className="flex justify-between items-center py-2 px-2.5 rounded-md hover:bg-muted/50 transition-colors cursor-pointer group"
                  >
                    <div className="flex items-center gap-2">
                      <Users className="size-4 text-sky-500 dark:text-sky-400" />
                      <span className="font-semibold text-foreground text-sm">Team members</span>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <span className="font-bold font-mono text-sm text-sky-600 dark:text-sky-400">{members.length}</span>
                      <ChevronRight className="size-4 text-muted-foreground/50 group-hover:text-foreground transition-colors" />
                    </div>
                  </div>
                </TooltipTrigger>
                <TooltipContent side="left" className="p-3 w-52 space-y-2">
                  <div className="font-semibold text-xs text-muted-foreground uppercase tracking-wider">
                    Members Preview ({members.length})
                  </div>
                  {members.length === 0 ? (
                    <div className="text-xs italic text-muted-foreground/80">No members assigned.</div>
                  ) : (
                    <div className="space-y-1">
                      {members.slice(0, 3).map((m) => (
                        <div key={m.userId} className="flex justify-between gap-4 text-xs">
                          <span className="truncate max-w-[110px] font-medium text-foreground">{m.fullName}</span>
                          <span className="text-xs text-muted-foreground font-mono truncate">{m.role.replace('_', ' ')}</span>
                        </div>
                      ))}
                      {members.length > 3 && (
                        <div className="text-xs text-muted-foreground italic">+ {members.length - 3} more...</div>
                      )}
                    </div>
                  )}
                  <div className="text-xs text-primary/80 dark:text-primary/90 font-semibold border-t border-border/40 pt-1.5 text-center">
                    Click to manage members
                  </div>
                </TooltipContent>
              </Tooltip>

              {/* Open Issues Row */}
              <div className="flex justify-between items-center py-2 px-2.5 rounded-md transition-colors">
                <div className="flex items-center gap-2">
                  <AlertTriangle className="size-4 text-rose-500 dark:text-rose-400" />
                  <span className="font-semibold text-foreground text-sm">Open Issues</span>
                </div>
                <div>
                  {project.openIssues > 0 ? (
                    <Badge variant="outline" className="bg-rose-500/10 text-rose-700 dark:text-rose-400 border-rose-500/20 font-bold font-mono text-xs rounded-sm py-0.5">
                      {project.openIssues} Active
                    </Badge>
                  ) : (
                    <span className="font-semibold text-muted-foreground/80 font-mono text-sm">0</span>
                  )}
                </div>
              </div>

              {/* Reporting Today Row */}
              <div
                onClick={() => setActiveTab('reporting')}
                className="flex justify-between items-center py-2 px-2.5 rounded-md hover:bg-muted/50 transition-colors cursor-pointer group"
              >
                <div className="flex items-center gap-2">
                  <Clock className="size-4 text-amber-500 dark:text-amber-400" />
                  <span className="font-semibold text-foreground text-sm">Daily cutoff</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <span className="font-mono text-amber-600 dark:text-amber-400 text-sm font-semibold">{project.reportingCutoffTime} ({project.reportingTimezone})</span>
                  <ChevronRight className="size-4 text-muted-foreground/50 group-hover:text-foreground transition-colors" />
                </div>
              </div>
            </CardContent>
          </div>
        </Card>

        {/* Project Team Card */}
        <Card className="rounded-md border-border/70 shadow-xs flex flex-col justify-between overflow-hidden">
          <div>
            <CardHeader className="pb-3 border-b border-l-3 border-l-sky-500 flex flex-row items-center justify-between gap-4 bg-transparent">
              <CardTitle className="text-xs uppercase tracking-wider text-sky-600 dark:text-sky-400 font-bold">
                Project Leadership
              </CardTitle>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setActiveTab('members')}
                className="h-7 text-xs font-bold border border-sky-500/30 text-sky-600 hover:bg-sky-600 hover:text-white dark:text-sky-400 dark:hover:bg-sky-500 bg-transparent rounded-md px-3 transition-all cursor-pointer"
              >
                Manage
              </Button>
            </CardHeader>
            <CardContent className="pt-4 text-sm flex-1">
              {members.length === 0 ? (
                <div className="h-full flex flex-col items-center justify-center text-center p-4">
                  <span className="text-muted-foreground italic mb-2 text-sm">No members assigned yet.</span>
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-7 text-xs gap-1 cursor-pointer font-bold border border-sky-500/30 text-sky-600 rounded-md px-3 hover:bg-sky-600 hover:text-white dark:text-sky-400 dark:hover:bg-sky-500 transition-all"
                    onClick={() => setMemberDialogOpen(true)}
                  >
                    <Plus className="size-3.5" /> Add Member
                  </Button>
                </div>
              ) : (
                <div className="space-y-4">
                  {/* Project Managers */}
                  <div className="space-y-2">
                    <span className="block text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                      Managers
                    </span>
                    {managers.length === 0 ? (
                      <div className="text-xs text-muted-foreground/80 italic pl-1">No Project Manager assigned.</div>
                    ) : (
                      <div className="space-y-2">
                        {managers.map((m) => (
                          <div key={m.userId} className="flex items-center gap-2.5">
                            <Avatar className="size-8 border">
                              <AvatarFallback className="text-xs bg-primary/10 text-primary font-bold">
                                {m.fullName.substring(0, 2).toUpperCase()}
                              </AvatarFallback>
                            </Avatar>
                            <div className="flex flex-col min-w-0">
                              <span className="font-semibold text-foreground text-sm truncate max-w-[150px] leading-tight">
                                {m.fullName}
                              </span>
                              <span className="text-xs text-muted-foreground truncate max-w-[150px]">
                                {m.email}
                              </span>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* Finance / Accountants */}
                  <div className="space-y-2 border-t border-border/40 pt-3">
                    <span className="block text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                      Finance
                    </span>
                    {finance.length === 0 ? (
                      <div className="text-xs text-muted-foreground/80 italic pl-1">No Finance User assigned.</div>
                    ) : (
                      <div className="space-y-2">
                        {finance.map((m) => (
                          <div key={m.userId} className="flex items-center gap-2.5">
                            <Avatar className="size-8 border">
                              <AvatarFallback className="text-xs bg-emerald-500/10 text-emerald-600 font-bold">
                                {m.fullName.substring(0, 2).toUpperCase()}
                              </AvatarFallback>
                            </Avatar>
                            <div className="flex flex-col min-w-0">
                              <span className="font-semibold text-foreground text-sm truncate max-w-[150px] leading-tight">
                                {m.fullName}
                              </span>
                              <span className="text-xs text-muted-foreground truncate max-w-[150px]">
                                {m.email}
                              </span>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* Site Engineers Summary */}
                  {engineers.length > 0 && (
                    <div className="border-t border-border/40 pt-3">
                      <span className="block text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1.5">
                        Site Engineers
                      </span>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <div className="flex items-center gap-2.5 pl-1 cursor-pointer w-fit">
                            <div className="flex -space-x-1.5">
                              {engineers.slice(0, 3).map((m) => (
                                <Avatar key={m.userId} className="size-6 border-2 border-card ring-1 ring-border/20">
                                  <AvatarFallback className="text-[10px] bg-muted text-muted-foreground font-semibold">
                                    {m.fullName.substring(0, 2).toUpperCase()}
                                  </AvatarFallback>
                                </Avatar>
                              ))}
                              {engineers.length > 3 && (
                                <div className="size-6 rounded-full border-2 border-card bg-muted flex items-center justify-center text-[10px] font-semibold text-muted-foreground z-10">
                                  +{engineers.length - 3}
                                </div>
                              )}
                            </div>
                            <span className="text-xs text-muted-foreground font-medium hover:text-foreground transition-colors">
                              {engineers.length} field engineers mapped
                            </span>
                          </div>
                        </TooltipTrigger>
                        <TooltipContent side="top" className="p-2 w-48 space-y-1">
                          {engineers.map((e) => (
                            <div key={e.userId} className="text-xs truncate text-foreground font-medium">
                              • {e.fullName}
                            </div>
                          ))}
                        </TooltipContent>
                      </Tooltip>
                    </div>
                  )}
                </div>
              )}
            </CardContent>
          </div>
        </Card>

        {/* Reporting Setup Card */}
        <Card className="rounded-md border-border/70 shadow-xs md:col-span-2 flex flex-col justify-between overflow-hidden">
          <div>
            <CardHeader className="pb-3 border-b border-l-3 border-l-teal-500 flex flex-row items-center justify-between gap-4 bg-transparent">
              <CardTitle className="text-xs uppercase tracking-wider text-teal-600 dark:text-teal-400 font-bold">
                Reporting Setup Summary
              </CardTitle>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setActiveTab('reporting')}
                className="h-7 text-xs font-bold border border-teal-500/30 text-teal-600 hover:bg-teal-600 hover:text-white dark:text-teal-400 dark:hover:bg-teal-500 bg-transparent rounded-md px-3 transition-all cursor-pointer"
              >
                Configure
              </Button>
            </CardHeader>
            <CardContent className="pt-4 space-y-4 text-sm">
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="flex items-start gap-2.5">
                  <Clock className="size-5 text-orange-500 dark:text-orange-400 shrink-0 mt-0.5" />
                  <div>
                    <span className="block text-xs text-muted-foreground font-semibold uppercase tracking-wider">Cutoff Time</span>
                    <span className="font-semibold text-foreground text-sm font-mono">{project.reportingCutoffTime}</span>
                  </div>
                </div>

                <div className="flex items-start gap-2.5">
                  <MapPin className="size-5 text-teal-500 dark:text-teal-400 shrink-0 mt-0.5" />
                  <div>
                    <span className="block text-xs text-muted-foreground font-semibold uppercase tracking-wider">Timezone</span>
                    <span className="font-semibold text-foreground text-sm font-mono">{project.reportingTimezone}</span>
                  </div>
                </div>

                <div className="flex items-start gap-2.5">
                  <CheckCircle2 className="size-5 text-indigo-500 dark:text-indigo-400 shrink-0 mt-0.5" />
                  <div>
                    <span className="block text-xs text-muted-foreground font-semibold uppercase tracking-wider">Auto DPR Generation</span>
                    {project.autoGenerateDpr ? (
                      <Badge variant="outline" className="bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border-emerald-500/20 text-xs rounded-sm py-0.5 mt-0.5 font-semibold">
                        Enabled
                      </Badge>
                    ) : (
                      <Badge variant="outline" className="bg-muted text-muted-foreground border-border text-xs rounded-sm py-0.5 mt-0.5 font-semibold">
                        Disabled
                      </Badge>
                    )}
                  </div>
                </div>

                <div className="flex items-start gap-2.5">
                  <FileText className="size-5 text-purple-500 dark:text-purple-400 shrink-0 mt-0.5" />
                  <div>
                    <span className="block text-xs text-muted-foreground font-semibold uppercase tracking-wider">Required Report Types</span>
                    <span className="font-semibold text-foreground text-sm font-mono">
                      {project.requiredReportTypes?.length || 0} active types
                    </span>
                  </div>
                </div>
              </div>

              {/* Badges of Required Report Types */}
              {project.requiredReportTypes && project.requiredReportTypes.length > 0 && (
                <div className="border-t border-border/40 pt-4 space-y-2">
                  <span className="text-xs text-muted-foreground font-semibold uppercase block tracking-wider">
                    Active Forms
                  </span>
                  <div className="flex flex-wrap gap-1.5">
                    {project.requiredReportTypes.map((type) => {
                      const colorClass = FORM_BADGE_COLORS[type] || 'bg-muted text-muted-foreground border-border/50'
                      return (
                        <Badge key={type} variant="outline" className={`text-xs rounded-sm font-semibold py-0.5 border ${colorClass}`}>
                          {type}
                        </Badge>
                      )
                    })}
                  </div>
                </div>
              )}
            </CardContent>
          </div>
        </Card>
      </div>
    </TooltipProvider>
  )
}
