import * as React from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft,
  User as UserIcon,
  Shield,
  MessageSquare,
  History,
  Settings as SettingsIcon,
  Edit2,
  FolderLock,
  ShieldAlert,
  Loader2,
  Building2,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  fetchUser,
  updateUser,
  updateUserStatus,
  updateUserAccess,
  deleteUser,
  api,
  type User,
} from '@/lib/api'
import { fetchProjects } from '@/lib/projects'
import {
  AddEditUserDialog,
  AccessManagerDialog,
  WhatsAppManagerDialog,
} from '@/components/user-dialogs'
import { UserOverviewTab } from '@/components/user-overview-tab'
import { UserWhatsAppMessagesTab } from '@/components/user-whatsapp-messages-tab'
import type { ProjectItem } from '@/lib/scope-types'
import { roleLabel } from '@/lib/permissions'

const ROLE_BADGES = {
  ADMIN: 'destructive',
  PROJECT_MANAGER: 'default',
  SITE_ENGINEER: 'secondary',
  FINANCE: 'outline',
} as const

interface TimelineEntry {
  id: string
  event_type: string
  summary: string
  occurred_at: string
}

export default function UserDetails() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [activeTab, setActiveTab] = React.useState<'overview' | 'access' | 'whatsapp' | 'whatsapp_messages' | 'activity' | 'settings'>('overview')

  // Dialog States
  const [editOpen, setEditOpen] = React.useState(false)
  const [accessOpen, setAccessOpen] = React.useState(false)
  const [whatsappOpen, setWhatsappOpen] = React.useState(false)

  // Password reset fields
  const [newPassword, setNewPassword] = React.useState('')
  const [confirmPassword, setConfirmPassword] = React.useState('')
  const [pwdLoading, setPwdLoading] = React.useState(false)
  const [pwdSuccess, setPwdSuccess] = React.useState(false)
  const [pwdError, setPwdError] = React.useState('')

  // Fetch User
  const { data: user, isLoading, isError, error } = useQuery<User>({
    queryKey: ['user-details', id],
    queryFn: () => fetchUser(id!),
    enabled: !!id,
  })

  // Fetch Timeline for Activity tab (general timeline)
  const { data: timeline = [], isLoading: isTimelineLoading } = useQuery<TimelineEntry[]>({
    queryKey: ['org-timeline'],
    queryFn: async () => {
      const res = await api.get<{ items: TimelineEntry[] }>('/timeline', {
        params: { limit: 20 },
      })
      return res.data.items
    },
    enabled: activeTab === 'activity',
  })

  // Fetch Projects for displaying names in Access tab
  const { data: projects = [] } = useQuery<ProjectItem[]>({
    queryKey: ['all-projects-details'],
    queryFn: fetchProjects,
  })

  // Status mutation
  const statusMutation = useMutation({
    mutationFn: (status: string) => updateUserStatus(id!, status),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['user-details', id] })
    },
    onError: (err: any) => {
      alert(err.response?.data?.detail || 'Failed to update user status.')
    },
  })

  // Delete user mutation
  const deleteMutation = useMutation({
    mutationFn: () => deleteUser(id!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users-list'] })
      navigate('/team')
    },
    onError: (err: any) => {
      alert(err.response?.data?.detail || 'Failed to delete user.')
    },
  })

  // Access reset mutation
  const revokeAccessMutation = useMutation({
    mutationFn: () =>
      updateUserAccess(id!, { mode: 'custom_projects', projects: [] }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['user-details', id] })
    },
    onError: (err: any) => {
      alert(err.response?.data?.detail || 'Failed to revoke access.')
    },
  })

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center text-sm text-muted-foreground gap-2">
        <Loader2 className="size-4 animate-spin text-primary" />
        Loading user account details...
      </div>
    )
  }

  if (isError || !user) {
    return (
      <div className="space-y-4">
        <Link to="/team" className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
          <ArrowLeft className="size-3" /> Back to Directory
        </Link>
        <div className="bg-destructive/10 border border-destructive text-destructive text-xs p-4 rounded text-center">
          Failed to load user details: {error instanceof Error ? error.message : 'User not found.'}
        </div>
      </div>
    )
  }

  const handlePasswordReset = async (e: React.FormEvent) => {
    e.preventDefault()
    setPwdError('')
    setPwdSuccess(false)

    if (newPassword.length < 6) {
      setPwdError('Password must be at least 6 characters long.')
      return
    }

    if (newPassword !== confirmPassword) {
      setPwdError('Passwords do not match.')
      return
    }

    setPwdLoading(true)
    try {
      await updateUser(user.id, { password: newPassword })
      setPwdSuccess(true)
      setNewPassword('')
      setConfirmPassword('')
    } catch (err: any) {
      setPwdError(err.response?.data?.detail || 'Failed to update password.')
    } finally {
      setPwdLoading(false)
    }
  }

  return (
    <div className="flex flex-col gap-4 text-sm">
      {/* Header section */}
      <div className="flex flex-col gap-1.5">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b pb-4">
          <div className="flex items-center gap-3">
            <div className="size-10 rounded-full border border-primary/20 bg-primary/10 flex items-center justify-center text-sm font-bold text-primary shrink-0">
              {user.full_name.substring(0, 2).toUpperCase()}
            </div>
            <div>
              <h1 className="text-lg font-bold text-foreground flex items-center gap-2 leading-none">
                {user.full_name}
                <Badge variant="outline" className={`text-xs rounded-sm py-0.5 ${ROLE_BADGES[user.role as keyof typeof ROLE_BADGES] || 'bg-muted text-muted-foreground border'}`}>
                  {roleLabel(user.role)}
                </Badge>
              </h1>
              <span className="text-xs text-muted-foreground">
                {roleLabel(user.role)} · {user.email} · {user.whatsapp_number || 'No WhatsApp number'}
              </span>
            </div>
          </div>
          <div className="flex gap-2">
            <Button size="sm" variant="outline" onClick={() => setEditOpen(true)} className="h-7 text-xs gap-1.5 font-bold border border-primary/30 text-primary hover:bg-primary hover:text-white dark:hover:bg-primary bg-transparent rounded-md px-3 transition-all">
              <Edit2 className="size-3" /> Edit Profile
            </Button>
            <Button size="sm" variant="outline" onClick={() => setAccessOpen(true)} className="h-7 text-xs gap-1.5 font-bold border border-slate-500/30 text-slate-700 hover:bg-slate-600 hover:text-white dark:text-slate-300 dark:hover:bg-slate-500 bg-transparent rounded-md px-3 transition-all">
              <FolderLock className="size-3" /> Manage Access
            </Button>
          </div>
        </div>
      </div>

      {/* Tabs list */}
      <div className="flex border-b border-border/60 gap-4 text-xs font-semibold text-muted-foreground overflow-x-auto">
        <button
          onClick={() => setActiveTab('overview')}
          className={`pb-2 border-b-2 transition-colors ${
            activeTab === 'overview' ? 'border-primary text-foreground' : 'border-transparent hover:text-foreground'
          } flex items-center gap-1.5 whitespace-nowrap`}
        >
          <UserIcon className="size-3.5" />
          Overview
        </button>
        <button
          onClick={() => setActiveTab('access')}
          className={`pb-2 border-b-2 transition-colors ${
            activeTab === 'access' ? 'border-primary text-foreground' : 'border-transparent hover:text-foreground'
          } flex items-center gap-1.5 whitespace-nowrap`}
        >
          <Shield className="size-3.5" />
          Projects
        </button>
        <button
          onClick={() => setActiveTab('whatsapp')}
          className={`pb-2 border-b-2 transition-colors ${
            activeTab === 'whatsapp' ? 'border-primary text-foreground' : 'border-transparent hover:text-foreground'
          } flex items-center gap-1.5 whitespace-nowrap`}
        >
          <MessageSquare className="size-3.5" />
          WhatsApp number
        </button>
        <button
          onClick={() => setActiveTab('whatsapp_messages')}
          className={`pb-2 border-b-2 transition-colors ${
            activeTab === 'whatsapp_messages' ? 'border-primary text-foreground' : 'border-transparent hover:text-foreground'
          } flex items-center gap-1.5 whitespace-nowrap`}
        >
          <History className="size-3.5" />
          WhatsApp Messages
        </button>
        <button
          onClick={() => setActiveTab('activity')}
          className={`pb-2 border-b-2 transition-colors ${
            activeTab === 'activity' ? 'border-primary text-foreground' : 'border-transparent hover:text-foreground'
          } flex items-center gap-1.5 whitespace-nowrap`}
        >
          <History className="size-3.5" />
          Activity
        </button>
        <button
          onClick={() => setActiveTab('settings')}
          className={`pb-2 border-b-2 transition-colors ${
            activeTab === 'settings' ? 'border-primary text-foreground' : 'border-transparent hover:text-foreground'
          } flex items-center gap-1.5 whitespace-nowrap`}
        >
          <SettingsIcon className="size-3.5" />
          Account Settings
        </button>
      </div>

      {/* Tab Panels */}
      <div className="py-2">
        {activeTab === 'overview' && (
          <UserOverviewTab
            user={user}
            projects={projects}
            setActiveTab={setActiveTab}
            setEditOpen={setEditOpen}
            setAccessOpen={setAccessOpen}
            setWhatsappOpen={setWhatsappOpen}
            statusMutation={statusMutation}
          />
        )}

        {activeTab === 'access' && (
          <Card className="rounded-none border-border/70 shadow-none">
            <CardHeader className="pb-3 border-b flex flex-row items-center justify-between gap-4">
              <div>
                <CardTitle className="text-xs uppercase tracking-wider text-muted-foreground font-semibold">
                  Access Permissions Summary
                </CardTitle>
                <CardDescription className="text-[11px] text-muted-foreground">
                  Shows projects and sites the user has access to.
                </CardDescription>
              </div>
              <Button size="sm" variant="outline" onClick={() => setAccessOpen(true)}>
                Modify Access
              </Button>
            </CardHeader>
            <CardContent className="pt-4 space-y-4">
              <div className="flex items-center gap-2 text-xs">
                <span className="text-muted-foreground">Authorization Mode:</span>
                <Badge variant="outline" className="rounded-sm">
                  {user.access_policy?.mode === 'all_projects' ? 'All projects' : 'Selected projects'}
                </Badge>
              </div>

              {user.access_policy?.mode === 'all_projects' ? (
                <div className="bg-muted/10 border border-border p-4 rounded text-xs flex gap-2.5">
                  <Shield className="size-4 text-primary shrink-0" />
                  <div>
                    <strong className="block text-foreground">Full Organization Access</strong>
                    <span className="text-muted-foreground">
                      User automatically inherits access to all current and future projects and sites.
                    </span>
                  </div>
                </div>
              ) : (
                <div className="space-y-3">
                  {(user.access_policy?.projects || []).map((policyProj) => {
                    const matchedProj = projects.find((p) => p.id === policyProj.projectId)
                    const isAllSites = policyProj.siteAccess?.mode === 'all_sites'
                    const siteIds = policyProj.siteAccess?.siteIds || []

                    return (
                      <div
                        key={policyProj.projectId}
                        className="border border-border/60 bg-muted/5 p-3.5 rounded-sm text-xs space-y-1.5"
                      >
                        <div className="flex items-center gap-2 font-semibold text-foreground">
                          <Building2 className="size-4 text-muted-foreground" />
                          {matchedProj?.name || `Project (ID: ${policyProj.projectId})`}
                        </div>
                        <div className="pl-6 text-muted-foreground space-y-1">
                          <div>
                            <strong>Sites Scope:</strong>{' '}
                            {isAllSites ? (
                              <span className="text-primary font-medium">All Sites (Project-wide)</span>
                            ) : siteIds.length > 0 ? (
                              <span>{siteIds.length} Site(s) Assigned</span>
                            ) : (
                              <span className="italic text-muted-foreground/60">No sites mapped</span>
                            )}
                          </div>
                          {!isAllSites && siteIds.length > 0 && (
                            <div className="flex flex-wrap gap-1.5 pt-1">
                              {siteIds.map((sid) => (
                                <Badge key={sid} variant="outline" className="text-[10px] rounded-sm">
                                  Site ID: {sid}
                                </Badge>
                              ))}
                            </div>
                          )}
                        </div>
                      </div>
                    )
                  })}
                  {(!user.access_policy?.projects || user.access_policy.projects.length === 0) && (
                    <div className="border border-dashed p-6 text-center text-xs text-muted-foreground italic">
                      No project access configured.
                    </div>
                  )}
                </div>
              )}
            </CardContent>
          </Card>
        )}

        {activeTab === 'whatsapp' && (
          <Card className="rounded-none border-border/70 shadow-none">
            <CardHeader className="pb-3 border-b flex flex-row items-center justify-between gap-4">
              <div>
                <CardTitle className="text-xs uppercase tracking-wider text-muted-foreground font-semibold">
                  WhatsApp Connection Details
                </CardTitle>
              </div>
              <Button size="sm" variant="outline" onClick={() => setWhatsappOpen(true)}>
                Modify Identity
              </Button>
            </CardHeader>
            <CardContent className="pt-4 space-y-4 text-xs">
              <div className="grid gap-2 border p-3 bg-muted/5 border-border/80">
                <div className="flex justify-between items-center py-1">
                  <span className="text-muted-foreground">WhatsApp number</span>
                  <span className="font-mono text-foreground font-semibold">
                    {user.whatsapp_number || 'None'}
                  </span>
                </div>
                <div className="flex justify-between items-center py-1 border-t">
                  <span className="text-muted-foreground">Mapping Status</span>
                  <Badge variant={user.whatsapp_number ? 'default' : 'secondary'} className="rounded-sm">
                    {user.whatsapp_number ? 'Added' : 'Not added'}
                  </Badge>
                </div>
              </div>

              <div className="bg-destructive/5 border border-destructive/20 text-muted-foreground p-3.5 rounded text-[11px] flex gap-2">
                <ShieldAlert className="size-4 text-destructive shrink-0" />
                <div>
                  <strong className="block text-foreground mb-0.5">Verification & Group Mapping</strong>
                  Standard WhatsApp status mapping logic is controlled natively by the async WhatsApp webhook parser engine. You can change the primary phone number map above, but interactive verifications must be completed via incoming WhatsApp messages.
                </div>
              </div>
            </CardContent>
          </Card>
        )}

        {activeTab === 'whatsapp_messages' && (
          <UserWhatsAppMessagesTab
            user={user}
            setActiveTab={setActiveTab}
            setWhatsappOpen={setWhatsappOpen}
          />
        )}

        {activeTab === 'activity' && (
          <Card className="rounded-none border-border/70 shadow-none">
            <CardHeader className="pb-3 border-b">
              <CardTitle className="text-xs uppercase tracking-wider text-muted-foreground font-semibold">
                User Activity Log
              </CardTitle>
            </CardHeader>
            <CardContent className="pt-4 space-y-4">
              <div className="bg-yellow-500/5 border border-yellow-500/20 text-muted-foreground p-3 rounded text-[11px] flex gap-2">
                <ShieldAlert className="size-4 text-yellow-600 dark:text-yellow-400 shrink-0" />
                <span>
                  <strong>Integration Gap:</strong> User-specific activity logging is not supported in the backend endpoint. Showing general organization activities below.
                </span>
              </div>

              {isTimelineLoading ? (
                <div className="flex justify-center text-xs py-4 text-muted-foreground">
                  Loading timeline events...
                </div>
              ) : timeline.length === 0 ? (
                <div className="text-center text-xs italic text-muted-foreground py-4">
                  No activity logs found.
                </div>
              ) : (
                <div className="relative border-l border-border pl-4 ml-2 space-y-4">
                  {timeline.map((entry) => (
                    <div key={entry.id} className="relative text-xs">
                      <div className="absolute -left-[21px] top-1 size-2 rounded-full bg-border border border-background" />
                      <div className="flex flex-col">
                        <span className="font-semibold text-foreground">{entry.summary || entry.event_type}</span>
                        <span className="text-[10px] text-muted-foreground">
                          {new Date(entry.occurred_at).toLocaleString()}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        )}

        {activeTab === 'settings' && (
          <div className="space-y-4">
            {/* Password Reset Section */}
            <Card className="rounded-none border-border/70 shadow-none">
              <CardHeader className="pb-3 border-b">
                <CardTitle className="text-xs uppercase tracking-wider text-muted-foreground font-semibold">
                  Change Credentials / Password
                </CardTitle>
              </CardHeader>
              <CardContent className="pt-4">
                <form onSubmit={handlePasswordReset} className="max-w-sm space-y-3 text-xs">
                  {pwdError && (
                    <div className="bg-destructive/10 border border-destructive text-destructive text-[11px] p-2 rounded">
                      {pwdError}
                    </div>
                  )}
                  {pwdSuccess && (
                    <div className="bg-emerald-500/10 border border-emerald-500 text-emerald-700 dark:text-emerald-400 text-[11px] p-2 rounded">
                      Password updated successfully!
                    </div>
                  )}

                  <div className="grid gap-1">
                    <Label htmlFor="newPassword">New Password</Label>
                    <Input
                      id="newPassword"
                      type="password"
                      value={newPassword}
                      onChange={(e: React.ChangeEvent<HTMLInputElement>) => setNewPassword(e.target.value)}
                      placeholder="••••••••"
                      required
                    />
                  </div>

                  <div className="grid gap-1">
                    <Label htmlFor="confirmPasswordDetails">Confirm Password</Label>
                    <Input
                      id="confirmPasswordDetails"
                      type="password"
                      value={confirmPassword}
                      onChange={(e: React.ChangeEvent<HTMLInputElement>) => setConfirmPassword(e.target.value)}
                      placeholder="Confirm new password"
                      required
                    />
                  </div>

                  <Button type="submit" disabled={pwdLoading} className="text-xs mt-1">
                    {pwdLoading ? 'Updating...' : 'Reset Password'}
                  </Button>
                </form>
              </CardContent>
            </Card>

            {/* Dangerous Actions */}
            <Card className="rounded-none border-destructive/20 shadow-none">
              <CardHeader className="pb-3 border-b bg-destructive/5">
                <CardTitle className="text-xs uppercase tracking-wider text-destructive font-semibold">
                  Danger Zone
                </CardTitle>
              </CardHeader>
              <CardContent className="pt-4 space-y-4 text-xs">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3.5 border-b border-border/40">
                  <div className="flex flex-col gap-0.5">
                    <span className="font-semibold text-foreground">Remove project access</span>
                    <span className="text-[11px] text-muted-foreground">
                      Remove all custom project permissions. This reverts the user to standard access.
                    </span>
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      if (confirm('Are you sure you want to revoke all project permissions?')) {
                        revokeAccessMutation.mutate()
                      }
                    }}
                    className="text-xs shrink-0"
                  >
                    Revoke All Access
                  </Button>
                </div>

                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                  <div className="flex flex-col gap-0.5">
                    <span className="font-semibold text-foreground">Delete Account</span>
                    <span className="text-[11px] text-muted-foreground">
                      Permanently purge this user. This will fail if the user owns historical records in the organization.
                    </span>
                  </div>
                  <Button
                    variant="destructive"
                    size="sm"
                    onClick={() => {
                      if (confirm(`Purge user account for "${user.full_name}"? This action cannot be undone.`)) {
                        deleteMutation.mutate()
                      }
                    }}
                    className="text-xs shrink-0"
                  >
                    Delete User
                  </Button>
                </div>
              </CardContent>
            </Card>
          </div>
        )}
      </div>

      {/* Shared Dialog Containers */}
      <AddEditUserDialog
        open={editOpen}
        onOpenChange={setEditOpen}
        user={user}
        onSuccess={() => queryClient.invalidateQueries({ queryKey: ['user-details', id] })}
      />

      <AccessManagerDialog
        open={accessOpen}
        onOpenChange={setAccessOpen}
        user={user}
        onSuccess={() => queryClient.invalidateQueries({ queryKey: ['user-details', id] })}
      />

      <WhatsAppManagerDialog
        open={whatsappOpen}
        onOpenChange={setWhatsappOpen}
        user={user}
        onSuccess={() => queryClient.invalidateQueries({ queryKey: ['user-details', id] })}
      />
    </div>
  )
}
