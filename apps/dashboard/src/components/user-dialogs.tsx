import * as React from 'react'
import { useQuery } from '@tanstack/react-query'
import { Sparkles, ShieldAlert } from 'lucide-react'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog'
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
  SheetFooter,
} from '@/components/ui/sheet'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  type User,
  createUser,
  updateUser,
  updateUserAccess,
  type AccessPolicy,
} from '@/lib/api'
import { fetchProjects, fetchSites } from '@/lib/projects'
import type { ProjectItem, SiteItem } from '@/lib/scope-types'
import { ROLE_LABELS, type Role } from '@/lib/permissions'

const ROLES = (Object.keys(ROLE_LABELS) as Role[]).map((value) => ({ value, label: ROLE_LABELS[value] }))

interface AddEditUserDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  user?: User | null
  onSuccess: () => void
}

export function AddEditUserDialog({
  open,
  onOpenChange,
  user,
  onSuccess,
}: AddEditUserDialogProps) {
  const isEdit = !!user
  const [fullName, setFullName] = React.useState('')
  const [email, setEmail] = React.useState('')
  const [role, setRole] = React.useState('SITE_ENGINEER')
  const [whatsapp, setWhatsapp] = React.useState('')
  const [password, setPassword] = React.useState('')
  const [confirmPassword, setConfirmPassword] = React.useState('')
  const [loading, setLoading] = React.useState(false)
  const [error, setError] = React.useState('')

  React.useEffect(() => {
    if (open) {
      if (user) {
        setFullName(user.full_name || '')
        setEmail(user.email || '')
        setRole(user.role || 'SITE_ENGINEER')
        setWhatsapp(user.whatsapp_number || '')
        setPassword('')
        setConfirmPassword('')
      } else {
        setFullName('')
        setEmail('')
        setRole('SITE_ENGINEER')
        setWhatsapp('')
        setPassword('')
        setConfirmPassword('')
      }
      setError('')
    }
  }, [open, user])

  const generatePassword = () => {
    const chars = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%^&*'
    let pass = ''
    for (let i = 0; i < 12; i++) {
      pass += chars.charAt(Math.floor(Math.random() * chars.length))
    }
    setPassword(pass)
    setConfirmPassword(pass)
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')

    if (!fullName.trim() || !email.trim()) {
      setError('Full Name and Email are required.')
      return
    }

    if (!isEdit && !password) {
      setError('Password is required for new users.')
      return
    }

    if (password && password !== confirmPassword) {
      setError('Passwords do not match.')
      return
    }

    setLoading(true)
    try {
      if (isEdit && user) {
        await updateUser(user.id, {
          full_name: fullName,
          role,
          whatsapp_number: whatsapp.trim() || null,
          password: password || undefined,
        })
      } else {
        await createUser({
          full_name: fullName,
          email: email.trim(),
          password,
          role,
          whatsapp_number: whatsapp.trim() || null,
        })
      }
      onSuccess()
      onOpenChange(false)
    } catch (err: any) {
      setError(err.response?.data?.detail || 'An error occurred. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[480px]">
        <DialogHeader>
          <DialogTitle>{isEdit ? 'Edit User' : 'Add User'}</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4 py-2">
          {error && (
            <div className="bg-destructive/10 border border-destructive text-destructive text-xs p-2.5 rounded flex items-center gap-2">
              <ShieldAlert className="size-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          <div className="grid gap-1.5">
            <Label htmlFor="fullName">Full Name</Label>
            <Input
              id="fullName"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              placeholder="John Doe"
              required
            />
          </div>

          <div className="grid gap-1.5">
            <Label htmlFor="email">Email / Username</Label>
            <Input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="john@example.com"
              disabled={isEdit}
              required
            />
          </div>

          <div className="grid gap-1.5">
            <Label htmlFor="role">Organization Role</Label>
            <Select value={role} onValueChange={setRole}>
              <SelectTrigger className="h-9">
                <SelectValue placeholder="Select role" />
              </SelectTrigger>
              <SelectContent>
                {ROLES.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>
                    {opt.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="grid gap-1.5">
            <Label htmlFor="whatsapp">WhatsApp Number (Optional)</Label>
            <Input
              id="whatsapp"
              value={whatsapp}
              onChange={(e) => setWhatsapp(e.target.value)}
              placeholder="+919999999999"
            />
          </div>

          <div className="border-t pt-3 space-y-3">
            <div className="flex items-center justify-between">
              <Label htmlFor="password">
                {isEdit ? 'Reset Password (Optional)' : 'Account Password'}
              </Label>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={generatePassword}
                className="h-7 text-xs gap-1.5"
              >
                <Sparkles className="size-3" />
                Generate
              </Button>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="grid gap-1">
                <Input
                  id="password"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  required={!isEdit}
                />
              </div>
              <div className="grid gap-1">
                <Input
                  id="confirmPassword"
                  type="password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  placeholder="Confirm Password"
                  required={!!password}
                />
              </div>
            </div>
          </div>

          <DialogFooter className="pt-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={loading}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={loading}>
              {loading ? 'Processing...' : isEdit ? 'Save Changes' : 'Create User'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

interface AccessManagerDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  user: User | null
  onSuccess: () => void
}

export function AccessManagerDialog({
  open,
  onOpenChange,
  user,
  onSuccess,
}: AccessManagerDialogProps) {
  const [mode, setMode] = React.useState<'all_projects' | 'custom_projects'>('custom_projects')
  const [selectedProjects, setSelectedProjects] = React.useState<string[]>([])
  const [selectedSites, setSelectedSites] = React.useState<Record<string, string[]>>({})
  const [loading, setLoading] = React.useState(false)
  const [error, setError] = React.useState('')

  const { data: projects = [] } = useQuery<ProjectItem[]>({
    queryKey: ['access-projects-list'],
    queryFn: fetchProjects,
    enabled: open,
  })

  React.useEffect(() => {
    if (open && user) {
      setError('')
      const policy = user.access_policy || { mode: 'custom_projects', projects: [] }
      setMode((policy.mode as 'all_projects' | 'custom_projects') || 'custom_projects')

      const projIds: string[] = []
      const siteMap: Record<string, string[]> = {}

      if (policy.projects) {
        policy.projects.forEach((p: any) => {
          projIds.push(p.projectId)
          if (p.siteAccess?.siteIds) {
            siteMap[p.projectId] = p.siteAccess.siteIds
          } else if (p.siteAccess?.mode === 'all_sites') {
            siteMap[p.projectId] = ['__ALL_SITES__']
          }
        });
      }

      setSelectedProjects(projIds)
      setSelectedSites(siteMap)
    }
  }, [open, user])

  const toggleProject = (projectId: string) => {
    setSelectedProjects((prev) => {
      const isSelected = prev.includes(projectId)
      if (isSelected) {
        // Enforce hierarchy: Remove sites of unselected project
        const newSites = { ...selectedSites }
        delete newSites[projectId]
        setSelectedSites(newSites)
        return prev.filter((id) => id !== projectId)
      } else {
        return [...prev, projectId]
      }
    })
  }

  const toggleSite = (projectId: string, siteId: string) => {
    // A user cannot receive access to a Site without access to its parent Project
    if (!selectedProjects.includes(projectId)) {
      return
    }

    setSelectedSites((prev) => {
      const current = prev[projectId] || []
      const isSelected = current.includes(siteId)

      let updated: string[]
      if (isSelected) {
        updated = current.filter((id) => id !== siteId)
      } else {
        // If it was all sites, reset to empty first
        const cleanCurrent = current.includes('__ALL_SITES__') ? [] : current
        updated = [...cleanCurrent, siteId]
      }

      return {
        ...prev,
        [projectId]: updated,
      }
    })
  }

  const toggleAllSites = (projectId: string, projectSites: SiteItem[]) => {
    if (!selectedProjects.includes(projectId)) return

    setSelectedSites((prev) => {
      const current = prev[projectId] || []
      const isAll = current.includes('__ALL_SITES__') || current.length === projectSites.length

      return {
        ...prev,
        [projectId]: isAll ? [] : ['__ALL_SITES__'],
      }
    })
  }

  const handleSubmit = async () => {
    if (!user) return
    setLoading(true)
    setError('')

    try {
      // Rebuild AccessPolicy payload
      const policyProjects = selectedProjects.map((projId) => {
        const sites = selectedSites[projId] || []
        const isAll = sites.includes('__ALL_SITES__')
        
        return {
          projectId: projId,
          siteAccess: isAll
            ? { mode: 'all_sites' as const }
            : { mode: 'custom_sites' as const, siteIds: sites },
        }
      })

      const payload: AccessPolicy = {
        mode,
        projects: policyProjects,
      }

      await updateUserAccess(user.id, payload)
      onSuccess()
      onOpenChange(false)
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to update access policy.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="sm:max-w-md flex flex-col h-full p-0">
        <SheetHeader className="p-6 pb-2 border-b">
          <SheetTitle>Manage Access</SheetTitle>
          <SheetDescription>
            Configure project and site permissions for {user?.full_name}.
          </SheetDescription>
        </SheetHeader>

        <div className="flex-1 overflow-y-auto p-6 space-y-5">
          {error && (
            <div className="bg-destructive/10 border border-destructive text-destructive text-xs p-2.5 rounded flex items-center gap-2">
              <ShieldAlert className="size-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          <div className="space-y-2">
            <Label>Organization Access Mode</Label>
            <div className="flex items-center gap-4">
              <label className="flex items-center gap-2 text-sm font-medium cursor-pointer">
                <input
                  type="radio"
                  checked={mode === 'all_projects'}
                  onChange={() => setMode('all_projects')}
                  className="accent-primary"
                />
                All Projects (Org-Wide)
              </label>
              <label className="flex items-center gap-2 text-sm font-medium cursor-pointer">
                <input
                  type="radio"
                  checked={mode === 'custom_projects'}
                  onChange={() => setMode('custom_projects')}
                  className="accent-primary"
                />
                Custom Projects
              </label>
            </div>
          </div>

          {mode === 'custom_projects' && (
            <div className="space-y-4 border-t pt-4">
              <Label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Projects and Sites Scope
              </Label>
              <div className="space-y-3">
                {projects.map((proj) => (
                  <ProjectRow
                    key={proj.id}
                    project={proj}
                    isSelected={selectedProjects.includes(proj.id)}
                    selectedSites={selectedSites[proj.id] || []}
                    onToggleProject={() => toggleProject(proj.id)}
                    onToggleSite={(siteId) => toggleSite(proj.id, siteId)}
                    onToggleAllSites={(sites) => toggleAllSites(proj.id, sites)}
                  />
                ))}
                {projects.length === 0 && (
                  <div className="text-sm text-muted-foreground text-center py-4">
                    No projects found in the organization.
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        <SheetFooter className="p-6 border-t mt-auto">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={loading}>
            Cancel
          </Button>
          <Button onClick={handleSubmit} disabled={loading}>
            {loading ? 'Saving...' : 'Save Access Policy'}
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  )
}

function ProjectRow({
  project,
  isSelected,
  selectedSites,
  onToggleProject,
  onToggleSite,
  onToggleAllSites,
}: {
  project: ProjectItem
  isSelected: boolean
  selectedSites: string[]
  onToggleProject: () => void
  onToggleSite: (siteId: string) => void
  onToggleAllSites: (sites: SiteItem[]) => void
}) {
  const { data: sites = [] } = useQuery<SiteItem[]>({
    queryKey: ['access-sites-list', project.id],
    queryFn: () => fetchSites(project.id),
    enabled: isSelected,
  })

  const isAllSites = selectedSites.includes('__ALL_SITES__') || (sites.length > 0 && selectedSites.length === sites.length)

  return (
    <div className="border border-border/60 bg-muted/5 rounded-md p-3 space-y-2">
      <div className="flex items-center justify-between">
        <label className="flex items-center gap-2.5 text-sm font-semibold cursor-pointer">
          <input
            type="checkbox"
            checked={isSelected}
            onChange={onToggleProject}
            className="rounded border-border/80 text-primary focus:ring-primary size-4"
          />
          {project.name}
        </label>
        {isSelected && sites.length > 0 && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => onToggleAllSites(sites)}
            className="h-6 text-xs text-muted-foreground hover:text-foreground"
          >
            {isAllSites ? 'Unselect All' : 'Select All Sites'}
          </Button>
        )}
      </div>

      {isSelected && (
        <div className="pl-6 border-l border-border/60 ml-2 space-y-1.5 pt-1">
          {sites.map((site) => {
            const isChecked = isAllSites || selectedSites.includes(site.id)
            return (
              <label
                key={site.id}
                className="flex items-center gap-2 text-xs text-muted-foreground hover:text-foreground cursor-pointer"
              >
                <input
                  type="checkbox"
                  checked={isChecked}
                  onChange={() => onToggleSite(site.id)}
                  disabled={isAllSites}
                  className="rounded border-border/80 text-primary focus:ring-primary size-3.5 disabled:opacity-50"
                />
                {site.name}
              </label>
            )
          })}
          {sites.length === 0 && (
            <span className="text-xs text-muted-foreground/60 italic">No sites on this project</span>
          )}
        </div>
      )}
    </div>
  )
}

interface WhatsAppManagerDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  user: User | null
  onSuccess: () => void
}

export function WhatsAppManagerDialog({
  open,
  onOpenChange,
  user,
  onSuccess,
}: WhatsAppManagerDialogProps) {
  const [whatsapp, setWhatsapp] = React.useState('')
  const [loading, setLoading] = React.useState(false)
  const [error, setError] = React.useState('')

  React.useEffect(() => {
    if (open && user) {
      setWhatsapp(user.whatsapp_number || '')
      setError('')
    }
  }, [open, user])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!user) return
    setLoading(true)
    setError('')

    try {
      await updateUser(user.id, {
        whatsapp_number: whatsapp.trim() || null,
      })
      onSuccess()
      onOpenChange(false)
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to update WhatsApp number.')
    } finally {
      setLoading(false)
    }
  }

  const handleActionGap = (actionName: string) => {
    alert(
      `Integration Gap: "${actionName}" is not supported by the backend router. The M1 backend table exposes only raw 'whatsapp_number' storage. Real-time verification, custom mapping states, and conversation logs are managed asynchronously by the whatsapp-assistant engine.`
    )
  }

  const isMapped = !!user?.whatsapp_number

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[450px]">
        <DialogHeader>
          <DialogTitle>Manage WhatsApp Identity</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4 py-2">
          {error && (
            <div className="bg-destructive/10 border border-destructive text-destructive text-xs p-2.5 rounded flex items-center gap-2">
              <ShieldAlert className="size-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          <div className="grid gap-1.5">
            <Label htmlFor="mgrWhatsapp">Primary WhatsApp Number</Label>
            <div className="flex gap-2">
              <Input
                id="mgrWhatsapp"
                value={whatsapp}
                onChange={(e) => setWhatsapp(e.target.value)}
                placeholder="+919999999999"
                className="flex-1 font-mono"
              />
              {whatsapp && whatsapp !== user?.whatsapp_number && (
                <Button type="submit" disabled={loading}>
                  Update
                </Button>
              )}
            </div>
            <p className="text-[11px] text-muted-foreground">
              Always include country code (e.g. +91 for India, +1 for US).
            </p>
          </div>

          <div className="border border-border/80 bg-muted/10 p-3.5 space-y-3 rounded-md">
            <div className="flex justify-between items-center text-xs">
              <span className="font-semibold text-muted-foreground uppercase tracking-wider text-[10px]">
                Mapping Status
              </span>
              <Badge variant={isMapped ? 'default' : 'secondary'} className="rounded-sm px-1.5 py-0.5">
                {isMapped ? 'Added' : 'Not added'}
              </Badge>
            </div>
            {isMapped && (
              <div className="text-[11px] text-muted-foreground space-y-1">
                <div><strong>Verified Country Code:</strong> {user?.whatsapp_number?.startsWith('+') ? user.whatsapp_number.substring(0, 3) : 'Auto'}</div>
                <div><strong>Verification Mode:</strong> Automatic (Direct Mapping)</div>
              </div>
            )}
          </div>

          <div className="border-t pt-4 space-y-2">
            <span className="block text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              Actions
            </span>
            <div className="grid grid-cols-2 gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="text-xs"
                disabled={!isMapped}
                onClick={() => handleActionGap('Send Verification Code')}
              >
                Send Verification
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="text-xs text-destructive hover:bg-destructive/10"
                disabled={!isMapped}
                onClick={async () => {
                  if (confirm('Are you sure you want to unmap this WhatsApp number?')) {
                    setLoading(true)
                    try {
                      await updateUser(user!.id, { whatsapp_number: null })
                      setWhatsapp('')
                      onSuccess()
                      onOpenChange(false)
                    } catch (err: any) {
                      setError(err.response?.data?.detail || 'Failed to unmap.')
                    } finally {
                      setLoading(false)
                    }
                  }
                }}
              >
                Unmap Number
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="text-xs col-span-2"
                onClick={() => handleActionGap('Resolve Mapping Conflicts')}
              >
                Resolve Duplicate Conflicts
              </Button>
            </div>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  )
}
