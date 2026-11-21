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
  PROJECT_TYPES,
  type Project,
  type ProjectType,
  type Site,
} from '@/lib/projects'
import { fetchUsers, type User } from '@/lib/api'
import { expandSiteNames, MAX_SITES_AT_ONCE, sameSiteName } from '@/lib/site-batch'

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
  // PS-05: the project's kind and size
  const [projectType, setProjectType] = React.useState<ProjectType | ''>('')
  const [area, setArea] = React.useState('')
  const [floors, setFloors] = React.useState('')
  const [overhead, setOverhead] = React.useState('')
  const [loading, setLoading] = React.useState(false)
  const [error, setError] = React.useState('')

  React.useEffect(() => {
    if (open) {
      setProjectType((project?.projectType as ProjectType) ?? '')
      setArea(project?.builtUpAreaSqft != null ? String(project.builtUpAreaSqft) : '')
      setFloors(project?.floors != null ? String(project.floors) : '')
      setOverhead(project?.overheadPct != null ? String(project.overheadPct) : '')
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
      setError('Give the project a name')
      return
    }
    const areaNum = area.trim() ? Number(area.replace(/,/g, '')) : null
    const floorsNum = floors.trim() ? Number(floors) : null
    if (areaNum !== null && !(areaNum > 0)) {
      setError('Built-up area is a number of sq ft')
      return
    }
    if (floorsNum !== null && !(Number.isInteger(floorsNum) && floorsNum >= 1 && floorsNum <= 200)) {
      setError('Floors is a whole number, 1 or more')
      return
    }
    const overheadNum = overhead.trim() ? Number(overhead) : null
    if (overheadNum !== null && !(overheadNum >= 0 && overheadNum <= 100)) {
      setError('Overheads is a % from 0 to 100')
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
          projectType: projectType || null,
          builtUpAreaSqft: areaNum,
          floors: floorsNum,
          overheadPct: overheadNum,
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
          projectType: projectType || null,
          builtUpAreaSqft: areaNum,
          floors: floorsNum,
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
            <Input id="projName" value={name} onChange={(e) => { setName(e.target.value); setError('') }} placeholder="e.g. Rose Garden Villas" className="h-11 text-base" required autoFocus />
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            {field('projClient', 'Client', <UserIcon className="size-4" />, client, setClient, 'e.g. Dr. Meera Nair', {
              title: 'Client', text: 'Who the building is for and who pays you. Their bills and payments are kept under this name.',
            })}
            {field('projLocation', 'Location', <MapPin className="size-4" />, location, setLocation, 'e.g. Kakkanad, Kochi', {
              title: 'Location', text: 'Where the site is. It goes on the daily report and the bills.',
            })}
          </div>

          <div className="grid gap-4 sm:grid-cols-3">
            <div className="grid gap-1.5">
              <Label className="text-sm font-medium">Type</Label>
              <Select value={projectType} onValueChange={(v) => setProjectType(v as ProjectType)}>
                <SelectTrigger className="h-10"><SelectValue placeholder="Choose" /></SelectTrigger>
                <SelectContent>{PROJECT_TYPES.map((t) => <SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <div className="grid gap-1.5">
              <span className="flex items-center gap-1">
                <Label htmlFor="projArea" className="text-sm font-medium">Built-up area</Label>
                <Hint title="Built-up area" text="The floor area you build, all floors together. It gives the cost per sq ft." />
              </span>
              <div className="relative">
                <Input id="projArea" value={area} onChange={(e) => { setArea(e.target.value); setError('') }} inputMode="decimal" placeholder="e.g. 12,800" className="h-10 pr-12" />
                <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-xs text-muted-foreground">sq ft</span>
              </div>
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="projFloors" className="text-sm font-medium">Floors</Label>
              <Input id="projFloors" value={floors} onChange={(e) => { setFloors(e.target.value); setError('') }} inputMode="numeric" placeholder="e.g. 2" className="h-10" />
            </div>
          </div>

          {isEdit && (
            <div className="grid gap-1.5 sm:max-w-[50%]">
              <span className="flex items-center gap-1">
                <Label htmlFor="projOverhead" className="text-sm font-medium">Overheads</Label>
                <Hint title="Overheads" text="Site and office costs not on any BOQ line (supervision, site office, insurance, interest), as a % of the BOQ budget cost. The BOQ then shows the margin after them." example="8% on a ₹67 lakh budget: ₹5.4 lakh" />
              </span>
              <div className="relative">
                <Input id="projOverhead" value={overhead} onChange={(e) => { setOverhead(e.target.value); setError('') }} inputMode="decimal" placeholder="e.g. 8" className="h-10 pr-24" />
                <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-xs text-muted-foreground">% of budget</span>
              </div>
            </div>
          )}

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
              <Button type="button" variant="outline" disabled={loading || !name.trim()} onClick={(e) => handleSubmit(e as unknown as React.FormEvent, true)}>
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

  // QA-04 step 2: several sites at once ("Villa 1-4", one per line), checked against the project's sites first.
  const known = (queryClient.getQueryData<Site[]>(['project-sites', projectId]) ?? [])
    .filter((s) => s.id !== site?.id).map((s) => sameSiteName(s.name))
  const parsed = React.useMemo(() => (isEdit ? { names: name.trim() ? [name.trim()] : [], tooMany: false } : expandSiteNames(name)), [name, isEdit])
  const clash = parsed.names.filter((n) => known.includes(sameSiteName(n)))
  const fresh = parsed.names.filter((n) => !known.includes(sameSiteName(n)))

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!parsed.names.length) {
      setError('Give the site a name')
      return
    }
    if (parsed.tooMany) {
      setError(`At most ${MAX_SITES_AT_ONCE} sites at once`)
      return
    }
    if (isEdit && clash.length) {
      setError(`${clash[0]} is already a site of this project`)
      return
    }
    if (!isEdit && !fresh.length) {
      setError(clash.length === 1 ? `${clash[0]} is already a site of this project` : 'These are already sites of this project')
      return
    }

    setLoading(true)
    setError('')

    const failed: string[] = []
    try {
      if (isEdit && site) {
        await updateSite(projectId, site.id, { name: name.trim(), status })
      } else {
        for (const n of fresh) {
          try {
            await createSite(projectId, { name: n })
          } catch (err: any) {
            failed.push(err.response?.data?.detail || `${n} was not added`)
          }
        }
      }
      queryClient.invalidateQueries({ queryKey: ['project-sites', projectId] })
      queryClient.invalidateQueries({ queryKey: ['scope-sites', projectId] })
      if (failed.length) {
        setError(failed.join('. '))
        setName(failed.length < fresh.length ? '' : name)
        return
      }
      onSuccess()
      onOpenChange(false)
    } catch (err: any) {
      setError(err.response?.data?.detail || 'The site was not saved. Try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[420px]">
        <DialogHeader>
          <DialogTitle>{isEdit ? `Rename ${site?.name ?? 'site'}` : 'Add sites'}</DialogTitle>
          {!isEdit && <DialogDescription>Each villa, tower or block that reports on its own.</DialogDescription>}
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4 py-2 text-sm">
          <div className="grid gap-1.5">
            <Label htmlFor="siteName">{isEdit ? 'Name' : 'Names'}</Label>
            {isEdit ? (
              <Input id="siteName" value={name} onChange={(e) => { setName(e.target.value); setError('') }} placeholder="e.g. Villa 1" aria-invalid={!!error} />
            ) : (
              <textarea
                id="siteName"
                value={name}
                onChange={(e) => { setName(e.target.value); setError('') }}
                rows={2}
                autoFocus
                aria-invalid={!!error}
                placeholder="e.g. Villa 1-4   or   Tower A, Tower B"
                className="flex min-h-[56px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-xs focus-visible:outline-hidden focus-visible:ring-1 focus-visible:ring-ring"
              />
            )}
            {error ? (
              <p className="flex items-center gap-1 text-xs text-destructive" role="alert"><ShieldAlert className="size-3.5 shrink-0" /> {error}</p>
            ) : !isEdit && parsed.names.length > 0 ? (
              <div className="flex flex-wrap gap-1.5 pt-1" aria-label="Sites to add">
                {parsed.names.map((n) => {
                  const taken = known.includes(sameSiteName(n))
                  return (
                    <span key={sameSiteName(n)} className={taken ? 'rounded-md bg-muted px-2 py-0.5 text-xs text-muted-foreground line-through' : 'rounded-md bg-muted px-2 py-0.5 text-xs font-medium'}
                      title={taken ? 'Already a site of this project' : undefined}>{n}</span>
                  )
                })}
                {clash.length > 0 && <span className="text-xs text-muted-foreground">crossed out: already a site</span>}
              </div>
            ) : !isEdit ? (
              <p className="text-xs text-muted-foreground">"Villa 1-4" adds Villa 1, 2, 3 and 4.</p>
            ) : null}
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
            <Button type="submit" disabled={loading || (isEdit ? !name.trim() : !fresh.length)}>
              {loading ? 'Saving…' : isEdit ? 'Save' : fresh.length > 1 ? `Add ${fresh.length} sites` : 'Add site'}
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
