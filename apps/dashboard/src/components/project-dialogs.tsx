import * as React from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ShieldAlert,
  ShieldAlert as ShieldIcon,
  Loader2,
  MapPin,
  User as UserIcon,
  Hash,
  ChevronDown,
} from 'lucide-react'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogDescription,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Hint } from '@/components/hint'
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
  /** Where a new project opens once made (WEB-100: Project start opens its start steps). One button then. */
  afterCreate?: (projectId: string) => string
}


export function AddEditProjectDialog({
  open,
  onOpenChange,
  project,
  onSuccess,
  afterCreate,
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

  // UX-28: the short code follows the name by itself ("Green Villa" -> GV-003) until the person types their own.
  const [codeTouched, setCodeTouched] = React.useState(false)
  const [more, setMore] = React.useState(false)
  React.useEffect(() => {
    if (open) {
      setCodeTouched(!!project)
      setMore(!!project)
    }
  }, [open, project])
  React.useEffect(() => {
    if (isEdit || codeTouched || !name.trim()) return
    const initials = name.trim().split(/\s+/).map((w) => w[0]).join('').toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 3) || 'PRJ'
    const count = (queryClient.getQueryData<unknown[]>(['projects-list']) ?? []).length + 1
    setCode(`${initials}-${String(count).padStart(3, '0')}`)
  }, [name, isEdit, codeTouched, queryClient])

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
        for (const key of ['projects-list', 'scope-projects', 'lifecycle']) queryClient.invalidateQueries({ queryKey: [key] })
        onSuccess()
        onOpenChange(false)
        if (afterCreate) {
          navigate(afterCreate(created.id))
        } else if (openAfter) {
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

  const field = (id: string, label: string, icon: React.ReactNode, value: string, set: (v: string) => void, placeholder: string,
    hint?: React.ComponentProps<typeof Hint>) => (
    <div className="grid gap-1.5">
      <span className="flex items-center gap-1">
        <Label htmlFor={id} className="text-sm font-medium">{label}</Label>
        {hint && <Hint {...hint} />}
      </span>
      <div className="relative">
        <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground/70">{icon}</span>
        <Input id={id} value={value} onChange={(e) => set(e.target.value)} placeholder={placeholder} className="h-10 pl-9" />
      </div>
    </div>
  )

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-[480px]">
        <DialogHeader>
          <DialogTitle>{isEdit ? `Edit ${project?.name ?? 'project'}` : 'New project'}</DialogTitle>
          {!isEdit && <DialogDescription>Only the name is needed. The rest can come later.</DialogDescription>}
        </DialogHeader>
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          {error && (
            <p className="flex items-center gap-2 rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
              <ShieldIcon className="size-4 shrink-0" /> {error}
            </p>
          )}

          <div className="grid gap-1.5">
            <Label htmlFor="projName" className="text-sm font-medium">Project name</Label>
            <Input id="projName" value={name} onChange={(e) => setName(e.target.value)} placeholder="Green Villa" className="h-11 text-base" required autoFocus />
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            {field('projClient', 'Client', <UserIcon className="size-4" />, client, setClient, 'Mr Thomas', {
              title: 'Client', text: 'Who the building is for and who pays you. Their bills and payments are kept under this name.',
            })}
            {field('projLocation', 'Location', <MapPin className="size-4" />, location, setLocation, 'Kakkanad, Kochi', {
              title: 'Location', text: 'Where the site is. It goes on the daily report and the bills.',
            })}
          </div>

          {more ? (
            <div className="grid gap-4 rounded-lg border bg-muted/30 p-3">
              <div className="grid gap-1.5">
                <span className="flex items-center gap-1">
                  <Label htmlFor="projCode" className="text-sm font-medium">Short code</Label>
                  <Hint title="Short code" text="A short tag for the project on reports, bills and lists. It follows the name; change it if you have your own." example="Green Villa: GV-001" />
                </span>
                <div className="relative">
                  <Hash className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground/70" />
                  <Input id="projCode" value={code} onChange={(e) => { setCode(e.target.value); setCodeTouched(true) }} className="h-10 pl-9" />
                </div>
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="projDesc" className="text-sm font-medium">Notes</Label>
                <textarea
                  id="projDesc"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  className="flex min-h-[64px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-xs focus-visible:outline-hidden focus-visible:ring-1 focus-visible:ring-ring"
                  placeholder="Anything worth knowing about the project"
                />
              </div>
              {isEdit && (
                <div className="grid gap-1.5">
                  <Label htmlFor="projStatus" className="text-sm font-medium">Status</Label>
                  <Select value={status} onValueChange={setStatus}>
                    <SelectTrigger id="projStatus" className="h-10"><SelectValue placeholder="Select status" /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="success">On track</SelectItem>
                      <SelectItem value="warning">At risk</SelectItem>
                      <SelectItem value="critical">Critical</SelectItem>
                      <SelectItem value="neutral">On hold or completed</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              )}
            </div>
          ) : (
            <button type="button" onClick={() => setMore(true)} className="flex items-center gap-1 self-start text-sm text-muted-foreground hover:text-foreground">
              <ChevronDown className="size-4" aria-hidden /> More details
              <span className="text-xs tabular-nums">({code || 'code'}, notes)</span>
            </button>
          )}

          <DialogFooter className="gap-2 pt-1 sm:gap-2">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={loading}>Cancel</Button>
            {!isEdit && !afterCreate && (
              <Button type="button" variant="outline" disabled={loading} onClick={(e) => handleSubmit(e as unknown as React.FormEvent, true)}>
                Create and open Today
              </Button>
            )}
            <Button type="submit" disabled={loading || !name.trim()}>
              {loading ? 'Saving…' : isEdit ? 'Save' : 'Create project'}
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
          <DialogTitle>{isEdit ? `Rename ${site?.name ?? 'site'}` : 'Add a site'}</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4 py-2 text-xs">
          {error && (
            <div className="bg-destructive/10 border border-destructive text-destructive p-2.5 rounded flex items-center gap-2">
              <ShieldAlert className="size-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          <div className="grid gap-1.5">
            <Label htmlFor="siteName">Name</Label>
            <Input
              id="siteName"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Tower 1, Block A"
              required
            />
          </div>

          {isEdit && (
            <div className="grid gap-1.5">
              <Label htmlFor="siteStatus">Status</Label>
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
              {loading ? 'Saving…' : isEdit ? 'Save' : 'Add site'}
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
          <DialogTitle>Add a person to this project</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4 py-2 text-xs">
          {error && (
            <div className="bg-destructive/10 border border-destructive text-destructive p-2.5 rounded flex items-center gap-2">
              <ShieldAlert className="size-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          <div className="grid gap-1.5">
            <Label htmlFor="memberSelect">Person</Label>
            {isUsersLoading ? (
              <div className="flex items-center gap-1.5 text-xs text-muted-foreground py-2">
                <Loader2 className="size-3.5 animate-spin text-primary-ink" /> Loading users list...
              </div>
            ) : availableUsers.length === 0 ? (
              <div className="text-xs text-muted-foreground italic py-2 border rounded border-dashed px-3">
                No organization users available to assign.
              </div>
            ) : (
              <Select value={selectedUserId} onValueChange={setSelectedUserId}>
                <SelectTrigger className="h-9">
                  <SelectValue placeholder="Choose someone from the team" />
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
            <Label htmlFor="memberRole">Role on this project</Label>
            <Select value={role} onValueChange={setRole}>
              <SelectTrigger className="h-9">
                <SelectValue placeholder="Select role" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="PROJECT_MANAGER">Project Manager</SelectItem>
                <SelectItem value="SITE_ENGINEER">Site Engineer</SelectItem>
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
