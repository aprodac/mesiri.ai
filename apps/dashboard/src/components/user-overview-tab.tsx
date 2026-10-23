import * as React from 'react'
import {
  User as UserIcon,
  Shield,
  MessageSquare,
  ChevronRight,
  Clock,
  Edit2,
  FolderLock,
  UserX,
  UserCheck,
} from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import type { User } from '@/lib/api'
import type { ProjectItem } from '@/lib/scope-types'
import { roleLabel } from '@/lib/permissions'

interface UserOverviewTabProps {
  user: User
  projects: ProjectItem[]
  setActiveTab: (tab: 'overview' | 'access' | 'whatsapp' | 'activity' | 'settings') => void
  setEditOpen: (open: boolean) => void
  setAccessOpen: (open: boolean) => void
  setWhatsappOpen: (open: boolean) => void
  statusMutation: any
}

const ROLE_BADGES = {
  ADMIN: 'bg-rose-500/10 text-rose-700 dark:text-rose-400 border-rose-500/20',
  PROJECT_MANAGER: 'bg-blue-500/10 text-blue-700 dark:text-blue-400 border-blue-500/20',
  SITE_ENGINEER: 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border-emerald-500/20',
  FINANCE: 'bg-amber-500/10 text-amber-700 dark:text-amber-400 border-amber-500/20',
} as const

export function UserOverviewTab({
  user,
  projects,
  setActiveTab,
  setEditOpen,
  setAccessOpen,
  setWhatsappOpen,
  statusMutation,
}: UserOverviewTabProps) {
  // Resolve project IDs to names
  const assignedProjects = React.useMemo(() => {
    if (user.access_policy?.mode === 'all_projects') return []
    return (user.access_policy?.projects || []).map((p) => {
      const match = projects.find((proj) => proj.id === p.projectId)
      return match ? match.name : p.projectId
    })
  }, [user.access_policy, projects])

  return (
    <TooltipProvider>
      <div className="grid gap-4 md:grid-cols-3">
        {/* User Information - Left/Middle (60-65%) */}
        <Card className="rounded-md border-border/70 shadow-xs md:col-span-2 flex flex-col justify-between overflow-hidden">
          <div>
            <CardHeader className="pb-3 border-b border-l-3 border-l-blue-500 flex flex-row items-center justify-between gap-4 bg-transparent">
              <div>
                <CardTitle className="text-xs uppercase tracking-wider text-blue-600 dark:text-blue-400 font-bold">
                  Details
                </CardTitle>
              </div>
              <Button
                variant="outline"
                size="sm"
                className="h-7 text-xs gap-1 cursor-pointer font-bold border border-blue-500/30 text-blue-600 hover:bg-blue-600 hover:text-white dark:text-blue-400 dark:hover:bg-blue-500 dark:hover:text-white bg-transparent rounded-md px-3 transition-all"
                onClick={() => setEditOpen(true)}
              >
                <Edit2 className="size-3" />
                Edit Profile
              </Button>
            </CardHeader>
            <CardContent className="pt-4 space-y-4 text-sm">
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="flex items-start gap-2.5">
                  <UserIcon className="size-5 text-blue-500 dark:text-blue-400 shrink-0 mt-0.5" />
                  <div>
                    <span className="block text-xs text-muted-foreground font-semibold uppercase tracking-wider">Full Name</span>
                    <span className="font-semibold text-foreground text-sm">{user.full_name}</span>
                  </div>
                </div>

                <div className="flex items-start gap-2.5">
                  <Shield className="size-5 text-indigo-500 dark:text-indigo-400 shrink-0 mt-0.5" />
                  <div>
                    <span className="block text-xs text-muted-foreground font-semibold uppercase tracking-wider">Role</span>
                    <Badge variant="outline" className={`text-xs rounded-sm py-0.5 mt-0.5 font-semibold ${ROLE_BADGES[user.role as keyof typeof ROLE_BADGES] || 'bg-muted text-muted-foreground border'}`}>
                      {roleLabel(user.role)}
                    </Badge>
                  </div>
                </div>

                <div className="flex items-start gap-2.5">
                  <Clock className="size-5 text-amber-500 dark:text-amber-400 shrink-0 mt-0.5" />
                  <div>
                    <span className="block text-xs text-muted-foreground font-semibold uppercase tracking-wider">Status</span>
                    <Badge variant="outline" className={`text-xs rounded-sm py-0.5 mt-0.5 font-semibold ${user.status === 'active' ? 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border-emerald-500/20' : 'bg-rose-500/10 text-rose-700 dark:text-rose-400 border-rose-500/20'}`}>
                      {user.status}
                    </Badge>
                  </div>
                </div>
              </div>
            </CardContent>
          </div>
        </Card>

        {/* Quick Status - Right (35-40%) */}
        <Card className="rounded-md border-border/70 shadow-xs flex flex-col justify-between overflow-hidden">
          <div>
            <CardHeader className="pb-3 border-b border-l-3 border-l-violet-500 bg-transparent">
              <CardTitle className="text-xs uppercase tracking-wider text-violet-600 dark:text-violet-400 font-bold">
                Access
              </CardTitle>
            </CardHeader>
            <CardContent className="pt-3 space-y-1.5 text-sm">
              {/* Projects Assigned Row */}
              <Tooltip>
                <TooltipTrigger asChild>
                  <div
                    onClick={() => setActiveTab('access')}
                    className="flex justify-between items-center py-2 px-2.5 rounded-md hover:bg-muted/50 transition-colors cursor-pointer group"
                  >
                    <div className="flex items-center gap-2">
                      <FolderLock className="size-4 text-violet-500 dark:text-violet-400" />
                      <span className="font-semibold text-foreground text-sm">Project Permissions</span>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <span className="font-bold text-sm text-violet-600 dark:text-violet-400">
                        {user.access_policy?.mode === 'all_projects' ? 'Org-Wide' : `${assignedProjects.length} Project(s)`}
                      </span>
                      <ChevronRight className="size-4 text-muted-foreground/50 group-hover:text-foreground transition-colors" />
                    </div>
                  </div>
                </TooltipTrigger>
                <TooltipContent side="left" className="p-3 w-52 space-y-2">
                  <div className="font-semibold text-xs text-muted-foreground uppercase tracking-wider">
                    Authorized Scope
                  </div>
                  {user.access_policy?.mode === 'all_projects' ? (
                    <div className="text-xs text-foreground font-medium">• All current & future projects</div>
                  ) : assignedProjects.length === 0 ? (
                    <div className="text-xs italic text-muted-foreground/80">No projects assigned.</div>
                  ) : (
                    <div className="space-y-1">
                      {assignedProjects.slice(0, 3).map((pName, idx) => (
                        <div key={idx} className="text-xs truncate text-foreground font-medium">
                          • {pName}
                        </div>
                      ))}
                      {assignedProjects.length > 3 && (
                        <div className="text-xs text-muted-foreground italic">+ {assignedProjects.length - 3} more...</div>
                      )}
                    </div>
                  )}
                  <div className="text-xs text-primary/80 dark:text-primary/90 font-semibold border-t border-border/40 pt-1.5 text-center">
                    Click to manage access
                  </div>
                </TooltipContent>
              </Tooltip>

              {/* WhatsApp Row */}
              <div
                onClick={() => setActiveTab('whatsapp')}
                className="flex justify-between items-center py-2 px-2.5 rounded-md hover:bg-muted/50 transition-colors cursor-pointer group"
              >
                <div className="flex items-center gap-2">
                  <MessageSquare className="size-4 text-sky-500 dark:text-sky-400" />
                  <span className="font-semibold text-foreground text-sm">WhatsApp Number</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <span className="font-mono text-sky-600 dark:text-sky-400 text-sm font-semibold">
                    {user.whatsapp_number || 'Not added'}
                  </span>
                  <ChevronRight className="size-4 text-muted-foreground/50 group-hover:text-foreground transition-colors" />
                </div>
              </div>

              {/* Email Row */}
              <div className="flex justify-between items-center py-2 px-2.5 rounded-md transition-colors">
                <div className="flex items-center gap-2">
                  <UserIcon className="size-4 text-slate-500 dark:text-slate-400" />
                  <span className="font-semibold text-foreground text-sm">Email Address</span>
                </div>
                <span className="text-xs text-muted-foreground truncate max-w-[150px] font-medium">
                  {user.email}
                </span>
              </div>
            </CardContent>
          </div>
        </Card>

        {/* WhatsApp Connection */}
        <Card className="rounded-md border-border/70 shadow-xs flex flex-col justify-between overflow-hidden">
          <div>
            <CardHeader className="pb-3 border-b border-l-3 border-l-sky-500 flex flex-row items-center justify-between gap-4 bg-transparent">
              <CardTitle className="text-xs uppercase tracking-wider text-sky-600 dark:text-sky-400 font-bold">
                WhatsApp Setup
              </CardTitle>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setWhatsappOpen(true)}
                className="h-7 text-xs font-bold border border-sky-500/30 text-sky-600 hover:bg-sky-600 hover:text-white dark:text-sky-400 dark:hover:bg-sky-500 bg-transparent rounded-md px-3 transition-all cursor-pointer"
              >
                Edit
              </Button>
            </CardHeader>
            <CardContent className="pt-4 text-sm flex-1">
              <div className="space-y-3.5">
                <div className="flex items-start gap-2.5">
                  <MessageSquare className="size-5 text-emerald-500 mt-0.5 shrink-0" />
                  <div>
                    <span className="block text-xs text-muted-foreground font-semibold uppercase tracking-wider">Number</span>
                    <span className="font-semibold text-foreground text-sm font-mono">
                      {user.whatsapp_number || <span className="text-muted-foreground/60 italic font-normal">Not added</span>}
                    </span>
                  </div>
                </div>

                <div className="border-t border-border/40 pt-3">
                  <span className="block text-xs text-muted-foreground font-semibold uppercase tracking-wider mb-1">Status</span>
                  {user.whatsapp_number ? (
                    <Badge variant="outline" className="bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border-emerald-500/20 text-xs rounded-sm py-0.5 font-semibold">
                      Connection Linked
                    </Badge>
                  ) : (
                    <Badge variant="outline" className="bg-muted text-muted-foreground border-border text-xs rounded-sm py-0.5 font-semibold">
                      Not added yet
                    </Badge>
                  )}
                </div>
              </div>
            </CardContent>
          </div>
        </Card>

        {/* Access Tools Card */}
        <Card className="rounded-md border-border/70 shadow-xs md:col-span-2 flex flex-col justify-between overflow-hidden">
          <div>
            <CardHeader className="pb-3 border-b border-l-3 border-l-teal-500 flex flex-row items-center justify-between gap-4 bg-transparent">
              <CardTitle className="text-xs uppercase tracking-wider text-teal-600 dark:text-teal-400 font-bold">
                Access & Status Tools
              </CardTitle>
            </CardHeader>
            <CardContent className="pt-4 space-y-4 text-sm">
              <div className="grid gap-3 sm:grid-cols-2">
                <Button
                  variant="outline"
                  onClick={() => setAccessOpen(true)}
                  className="h-9 text-xs gap-1.5 font-bold border border-teal-500/30 text-teal-600 hover:bg-teal-600 hover:text-white dark:text-teal-400 dark:hover:bg-teal-500 bg-transparent rounded-md px-3 transition-all w-full justify-center"
                >
                  <FolderLock className="size-4" /> Edit Project Permissions
                </Button>
                {user.status === 'active' ? (
                  <Button
                    variant="outline"
                    onClick={() => {
                      if (confirm(`Deactivate user "${user.full_name}"?`)) {
                        statusMutation.mutate('inactive')
                      }
                    }}
                    className="h-9 text-xs gap-1.5 font-bold border border-rose-500/30 text-rose-600 hover:bg-rose-600 hover:text-white dark:text-rose-400 dark:hover:bg-rose-500 bg-transparent rounded-md px-3 transition-all w-full justify-center"
                  >
                    <UserX className="size-4" /> Deactivate Account
                  </Button>
                ) : (
                  <Button
                    variant="outline"
                    onClick={() => statusMutation.mutate('active')}
                    className="h-9 text-xs gap-1.5 font-bold border border-emerald-500/30 text-emerald-600 hover:bg-emerald-600 hover:text-white dark:text-emerald-400 dark:hover:bg-emerald-500 bg-transparent rounded-md px-3 transition-all w-full justify-center"
                  >
                    <UserCheck className="size-4" /> Activate Account
                  </Button>
                )}
              </div>
            </CardContent>
          </div>
        </Card>
      </div>
    </TooltipProvider>
  )
}
