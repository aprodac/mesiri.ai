import * as React from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ShieldAlert,
  ShieldAlert as ShieldIcon,
  Loader2,
  MapPin,
  Briefcase,
  User as UserIcon,
  Hash,
} from 'lucide-react'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog'
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
  createProject,
  updateProject,
  createSite,
  updateSite,
  addProjectMember,
  type Project,
  type Site,
} from '@/lib/projects'
import { fetchUsers, type User } from '@/lib/api'

interface AddEditProjectDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  project?: Project | null
  onSuccess: () => void
}


export function AddEditProjectDialog({
  open,
  onOpenChange,
  project,
  onSuccess,
}: AddEditProjectDialogProps) {
  const isEdit = !!project
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [name, setName] = React.useState('')
  const [code, setCode] = React.useState('')
  const [client, setClient] = React.useState('')
  const [location, setLocation] = React.useState('')
  const [description, setDescription] = React.useState('')
  const [status, setStatus] = React.useState('success')
  const [loading, setLoading] = React.useState(false)
  const [error, setError] = React.useState('')

  React.useEffect(() => {
    if (open) {
      if (project) {
        setName(project.name || '')
        setCode(project.code || '')
        setClient(project.client || '')
        setLocation(project.location || '')
        setDescription(project.description || '')
        setStatus(project.status || 'success')
      } else {
        setName('')
        const projectsList = queryClient.getQueryData<any[]>(['projects-list']) || []
        const nextNum = projectsList.length + 1
        setCode(`PRJ-${String(nextNum).padStart(3, '0')}`)
        setClient('')
        setLocation('')
        setDescription('')
        setStatus('success')
      }
      setError('')
    }
  }, [open, project, queryClient])

  const generateProjectCode = () => {
    if (!name.trim()) return
    const initials = name
      .trim()
      .split(/\s+/)
      .map((w) => w[0])
      .join('')
      .toUpperCase()
      .substring(0, 3) || 'PRJ'
    const projectsList = queryClient.getQueryData<any[]>(['projects-list']) || []
    const nextNum = projectsList.length + 1
    const formattedNum = String(nextNum).padStart(3, '0')
    setCode(`${initials}-${formattedNum}`)
  }

  const handleSubmit = async (e: React.FormEvent, openAfter = false) => {
    e.preventDefault()
    if (!name.trim()) {
      setError('Project Name is required.')
      return
    }

    setLoading(true)
    setError('')

    try {
      if (isEdit && project) {
        await updateProject(project.id, {
          name: name.trim(),
          code: code.trim() || null,
          client: client.trim() || null,
          location: location.trim() || null,
          description: description.trim() || null,
          status,
        })
        queryClient.invalidateQueries({ queryKey: ['projects-list'] })
        queryClient.invalidateQueries({ queryKey: ['scope-projects'] })
        queryClient.invalidateQueries({ queryKey: ['project-details', project.id] })
        onSuccess()
        onOpenChange(false)
      } else {
        const created = await createProject({
          name: name.trim(),
          code: code.trim() || null,
          client: client.trim() || null,
          location: location.trim() || null,
          description: description.trim() || null,
        })
        queryClient.invalidateQueries({ queryKey: ['projects-list'] })
        queryClient.invalidateQueries({ queryKey: ['scope-projects'] })
        onSuccess()
        onOpenChange(false)
        if (openAfter) {
          navigate(`/today?project=${created.id}`)
        } else {
          navigate(`/projects/${created.id}?new=1`)
        }
      }
    } catch (err: any) {
      setError(err.response?.data?.detail || 'An error occurred. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[460px] max-h-[85vh] overflow-y-auto px-5 py-4">
        <DialogHeader className="pb-1 border-b">
          <DialogTitle className="text-sm font-bold tracking-tight text-foreground uppercase">
            {isEdit ? 'Edit Project Config' : 'Create New Project'}
          </DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4 py-3 text-xs">
          {error && (
            <div className="bg-destructive/10 border border-destructive text-destructive p-2 rounded flex items-center gap-2">
              <ShieldIcon className="size-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          {/* Group 1: Basic Information */}
          <div className="space-y-3">
            <span className="block font-bold uppercase tracking-wider text-[10px] text-muted-foreground/80">
              Basic Information
            </span>

            <div className="grid gap-1.5">
              <Label htmlFor="projName" className="font-semibold">Project Name</Label>
              <div className="relative">
                <Briefcase className="absolute left-2.5 top-2.5 size-3.5 text-muted-foreground/60" />
                <Input
                  id="projName"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g. Skyline Towers"
                  className="pl-9 h-9"
                  required
                />
              </div>
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <div className="grid gap-1.5">
                <div className="flex justify-between items-center">
                  <Label htmlFor="projCode" className="font-semibold">Project Code</Label>
                  {!isEdit && (
                    <button
                       type="button"
                       onClick={generateProjectCode}
                       className="text-[9px] text-primary hover:underline font-semibold"
                     >
                       Generate from Name
                     </button>
                  )}
                </div>
                <div className="relative">
                  <Hash className="absolute left-2.5 top-2.5 size-3.5 text-muted-foreground/60" />
                  <Input
                    id="projCode"
                    value={code}
                    onChange={(e) => setCode(e.target.value)}
                    placeholder="e.g. SKY-782"
                    className="pl-9 h-9 font-mono"
                  />
                </div>
              </div>

              <div className="grid gap-1.5">
                <Label htmlFor="projLocation" className="font-semibold">Location</Label>
                <div className="relative">
                  <MapPin className="absolute left-2.5 top-2.5 size-3.5 text-muted-foreground/60" />
                  <Input
                    id="projLocation"
                    value={location}
                    onChange={(e) => setLocation(e.target.value)}
                    placeholder="e.g. Sector 4, North Zone"
                    className="pl-9 h-9"
                  />
                </div>
              </div>
            </div>

            <div className="grid gap-1.5">
              <Label htmlFor="projClient" className="font-semibold">Client Name</Label>
              <div className="relative">
                <UserIcon className="absolute left-2.5 top-2.5 size-3.5 text-muted-foreground/60" />
                <Input
                  id="projClient"
                  value={client}
                  onChange={(e) => setClient(e.target.value)}
                  placeholder="e.g. Mercon Corp"
                  className="pl-9 h-9"
                />
              </div>
            </div>

            <div className="grid gap-1.5">
              <Label htmlFor="projDesc" className="font-semibold">Description</Label>
              <textarea
                id="projDesc"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                className="flex min-h-[50px] w-full rounded-md border border-input bg-transparent px-3 py-2 text-xs shadow-xs focus-visible:outline-hidden focus-visible:ring-1 focus-visible:ring-ring"
                placeholder="Brief summary of project scope..."
              />
            </div>

            {isEdit && (
              <div className="grid gap-1.5">
                <Label htmlFor="projStatus" className="font-semibold">Project Status</Label>
                <Select value={status} onValueChange={setStatus}>
                  <SelectTrigger className="h-9">
                    <SelectValue placeholder="Select status" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="success">Active / On Track</SelectItem>
                    <SelectItem value="warning">At Risk</SelectItem>
                    <SelectItem value="critical">Critical</SelectItem>
                    <SelectItem value="neutral">On Hold / Completed</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            )}
          </div>



          <DialogFooter className="pt-3 border-t">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={loading} className="h-8">
              Cancel
            </Button>
            {!isEdit && (
              <Button
                type="button"
                variant="outline"
                disabled={loading}
                className="h-8"
                onClick={(e) => handleSubmit(e as unknown as React.FormEvent, true)}
              >
                {loading ? 'Creating...' : 'Create & Open Project'}
              </Button>
            )}
            <Button type="submit" disabled={loading} className="h-8">
              {loading ? 'Saving...' : isEdit ? 'Save Changes' : 'Create Project'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

interface AddEditSiteDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  projectId: string
  site?: Site | null
  onSuccess: () => void
}

export function AddEditSiteDialog({
  open,
  onOpenChange,
  projectId,
  site,
  onSuccess,
}: AddEditSiteDialogProps) {
  const isEdit = !!site
  const queryClient = useQueryClient()
  const [name, setName] = React.useState('')
  const [status, setStatus] = React.useState('active')
  const [loading, setLoading] = React.useState(false)
  const [error, setError] = React.useState('')

  React.useEffect(() => {
    if (open) {
      if (site) {
        setName(site.name || '')
        setStatus(site.status || 'active')
      } else {
        setName('')
        setStatus('active')
      }
      setError('')
    }
  }, [open, site])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim()) {
      setError('Site Name is required.')
      return
    }

    setLoading(true)
    setError('')

    try {
      if (isEdit && site) {
        await updateSite(projectId, site.id, { name: name.trim(), status })
      } else {
        await createSite(projectId, { name: name.trim() })
      }

      queryClient.invalidateQueries({ queryKey: ['project-sites', projectId] })
      queryClient.invalidateQueries({ queryKey: ['scope-sites', projectId] })
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
      <DialogContent className="sm:max-w-[400px]">
        <DialogHeader>
          <DialogTitle>{isEdit ? 'Edit Site' : 'Add Site'}</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4 py-2 text-xs">
          {error && (
            <div className="bg-destructive/10 border border-destructive text-destructive p-2.5 rounded flex items-center gap-2">
              <ShieldAlert className="size-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          <div className="grid gap-1.5">
            <Label htmlFor="siteName">Site Name</Label>
            <Input
              id="siteName"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Building A Wing"
              required
            />
          </div>

          {isEdit && (
            <div className="grid gap-1.5">
              <Label htmlFor="siteStatus">Site Status</Label>
              <Select value={status} onValueChange={setStatus}>
                <SelectTrigger className="h-9">
                  <SelectValue placeholder="Select status" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="active">Active</SelectItem>
                  <SelectItem value="archived">Archived</SelectItem>
                </SelectContent>
              </Select>
            </div>
          )}

          <DialogFooter className="pt-2">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={loading}>
              Cancel
            </Button>
            <Button type="submit" disabled={loading}>
              {loading ? 'Saving...' : isEdit ? 'Save Changes' : 'Create Site'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

interface ProjectMemberDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  projectId: string
  existingUserIds: string[]
  onSuccess: () => void
}

export function ProjectMemberDialog({
  open,
  onOpenChange,
  projectId,
  existingUserIds,
  onSuccess,
}: ProjectMemberDialogProps) {
  const queryClient = useQueryClient()
  const [selectedUserId, setSelectedUserId] = React.useState('')
  const [role, setRole] = React.useState('SITE_ENGINEER')
  const [loading, setLoading] = React.useState(false)
  const [error, setError] = React.useState('')

  const { data: allUsers = [], isLoading: isUsersLoading } = useQuery<User[]>({
    queryKey: ['org-users-selection'],
    queryFn: fetchUsers,
    enabled: open,
  })

  // Filter out users who are already members of this project
  const availableUsers = React.useMemo(() => {
    return allUsers.filter((u) => !existingUserIds.includes(u.id))
  }, [allUsers, existingUserIds])

  React.useEffect(() => {
    if (open) {
      setSelectedUserId('')
      setRole('SITE_ENGINEER')
      setError('')
    }
  }, [open])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!selectedUserId) {
      setError('Please select a user to add.')
      return
    }

    setLoading(true)
    setError('')

    try {
      await addProjectMember(projectId, { userId: selectedUserId, role })
      queryClient.invalidateQueries({ queryKey: ['project-members', projectId] })
      onSuccess()
      onOpenChange(false)
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to add project member.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[420px]">
        <DialogHeader>
          <DialogTitle>Add Project Member</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4 py-2 text-xs">
          {error && (
            <div className="bg-destructive/10 border border-destructive text-destructive p-2.5 rounded flex items-center gap-2">
              <ShieldAlert className="size-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          <div className="grid gap-1.5">
            <Label htmlFor="memberSelect">Select Organization User</Label>
            {isUsersLoading ? (
              <div className="flex items-center gap-1.5 text-xs text-muted-foreground py-2">
                <Loader2 className="size-3.5 animate-spin text-primary" /> Loading users list...
              </div>
            ) : availableUsers.length === 0 ? (
              <div className="text-xs text-muted-foreground italic py-2 border rounded border-dashed px-3">
                No organization users available to assign.
              </div>
            ) : (
              <Select value={selectedUserId} onValueChange={setSelectedUserId}>
                <SelectTrigger className="h-9">
                  <SelectValue placeholder="-- Choose User --" />
                </SelectTrigger>
                <SelectContent>
                  {availableUsers.map((u) => (
                    <SelectItem key={u.id} value={u.id}>
                      {u.full_name} ({u.email})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </div>

          <div className="grid gap-1.5">
            <Label htmlFor="memberRole">Project Role</Label>
            <Select value={role} onValueChange={setRole}>
              <SelectTrigger className="h-9">
                <SelectValue placeholder="Select role" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="PROJECT_MANAGER">Project Manager</SelectItem>
                <SelectItem value="SITE_ENGINEER">Site Engineer</SelectItem>
                <SelectItem value="FINANCE">Finance / Accountant</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <DialogFooter className="pt-2">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={loading}>
              Cancel
            </Button>
            <Button type="submit" disabled={loading || !selectedUserId}>
              {loading ? 'Adding...' : 'Add to Project'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
