import * as React from 'react'
import { useQuery } from '@tanstack/react-query'
import { Sparkles, ShieldAlert } from 'lucide-react'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogDescription,
} from '@/components/ui/dialog'
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
  SheetFooter,
} from '@/components/ui/sheet'
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
  fetchSetupProgress,
  updateUser,
  updateUserAccess,
  type AccessPolicy,
} from '@/lib/api'
import { inviteText, whatsappShareLink } from '@/lib/invite'
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

/** Roles that work on site and usually never open the dashboard (WEB-17). */
const WHATSAPP_ONLY_BY_DEFAULT = new Set(['SITE_ENGINEER'])

/**
 * Add or edit a person. Site staff are added with a name, a WhatsApp number
 * and a project, nothing else (WEB-17): the backend creates them through the
 * same step WhatsApp uses. A dashboard login (email + password) is opt-in.
 * After adding, the owner gets a message to forward so the person knows
 * where to report: Mesiri can't message them first (SS-12).
 */
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
  const [login, setLogin] = React.useState(false)
  const [projectId, setProjectId] = React.useState('')
  const [password, setPassword] = React.useState('')
  const [confirmPassword, setConfirmPassword] = React.useState('')
  const [loading, setLoading] = React.useState(false)
  const [error, setError] = React.useState('')
  const [added, setAdded] = React.useState<{ name: string; number: string | null; project: string | null } | null>(null)
  const [copied, setCopied] = React.useState(false)

  const projects = useQuery({
    queryKey: ['access-projects-list'],
    queryFn: fetchProjects,
    enabled: open && !isEdit,
  })
  const setup = useQuery({
    queryKey: ['setup-progress'],
    queryFn: fetchSetupProgress,
    enabled: open && !isEdit,
    retry: false,
  })
  const mesiriNumber = setup.data?.whatsapp_number ?? null

  React.useEffect(() => {
    if (open) {
      if (user) {
        setFullName(user.full_name || '')
        setEmail(user.email || '')
        setRole(user.role || 'SITE_ENGINEER')
        setWhatsapp(user.whatsapp_number || '')
        setLogin(!!user.email)
      } else {
        setFullName('')
        setEmail('')
        setRole('SITE_ENGINEER')
        setWhatsapp('')
        setLogin(false)
        setProjectId('')
      }
      setPassword('')
      setConfirmPassword('')
      setError('')
      setAdded(null)
      setCopied(false)
    }
  }, [open, user])

  // One project: put them on it without asking.
  React.useEffect(() => {
    if (!isEdit && projects.data?.length === 1 && !projectId) setProjectId(projects.data[0].id)
  }, [isEdit, projects.data, projectId])

  const changeRole = (value: string) => {
    setRole(value)
    if (!isEdit) setLogin(!WHATSAPP_ONLY_BY_DEFAULT.has(value))
  }

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

    if (!fullName.trim()) {
      setError('Add their name.')
      return
    }
    if (!isEdit && !login && !whatsapp.trim()) {
      setError('Add their WhatsApp number: it is how they send updates.')
      return
    }
    if (!isEdit && login) {
      if (!email.trim()) {
        setError('Add an email to sign in with, or turn off the dashboard login.')
        return
      }
      if (!password) {
        setError('Set a password for their dashboard login.')
        return
      }
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
        onSuccess()
        onOpenChange(false)
        return
      }
      const created = await createUser({
        full_name: fullName.trim(),
        role,
        whatsapp_number: whatsapp.trim() || null,
        ...(login ? { email: email.trim(), password } : {}),
      })
      const project = projects.data?.find((p) => p.id === projectId) ?? null
      if (project) {
        await updateUserAccess(created.id, {
          mode: 'custom_projects',
          projects: [{ projectId: project.id, siteAccess: { mode: 'all_sites' } }],
        })
      }
      onSuccess()
      if (created.whatsapp_number && mesiriNumber) {
        setAdded({ name: created.full_name, number: created.whatsapp_number, project: project?.name ?? null })
      } else {
        onOpenChange(false)
      }
    } catch (err: any) {
      setError(err.response?.data?.detail || 'An error occurred. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  if (added && mesiriNumber) {
    const text = inviteText({ number: mesiriNumber, name: added.name, site: added.project ?? undefined })
    const copy = async () => {
      try {
        await navigator.clipboard.writeText(text)
        setCopied(true)
      } catch {
        setCopied(false)
      }
    }
    return (
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="sm:max-w-[480px]">
          <DialogHeader>
            <DialogTitle>{added.name} is added</DialogTitle>
            <DialogDescription>
              Send them this on WhatsApp so they know where to report{added.project ? ` for ${added.project}` : ''}.
            </DialogDescription>
          </DialogHeader>
          <p className="rounded-md border bg-muted/40 p-3 text-sm select-all">{text}</p>
          <DialogFooter className="gap-2 pt-2 sm:justify-between">
            <Button type="button" variant="outline" onClick={copy}>
              {copied ? 'Copied' : 'Copy message'}
            </Button>
            <div className="flex gap-2">
              <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
                Done
              </Button>
              <Button asChild>
                <a href={whatsappShareLink(text, added.number)} target="_blank" rel="noreferrer">
                  Send on WhatsApp
                </a>
              </Button>
            </div>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    )
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[480px]">
        <DialogHeader>
          <DialogTitle>{isEdit ? `Edit ${user?.full_name ?? 'person'}` : 'Add a person'}</DialogTitle>
          {!isEdit && (
            <DialogDescription>Site staff need only a name and their WhatsApp number.</DialogDescription>
          )}
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4 py-2">
          {error && (
            <div className="bg-destructive/10 border border-destructive text-destructive text-xs p-2.5 rounded flex items-center gap-2">
              <ShieldAlert className="size-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          <div className="grid gap-1.5">
            <Label htmlFor="fullName">Name</Label>
            <Input
              id="fullName"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              placeholder="e.g. Ravi Menon"
              required
            />
          </div>

          <div className="grid gap-1.5">
            <Label htmlFor="whatsapp">WhatsApp number</Label>
            <Input
              id="whatsapp"
              type="tel"
              inputMode="tel"
              value={whatsapp}
              onChange={(e) => setWhatsapp(e.target.value)}
              placeholder="+91 98765 43210"
              required={!isEdit && !login}
            />
            <p className="text-xs text-muted-foreground">They send site updates to Mesiri from this number.</p>
          </div>

          <div className="grid gap-1.5">
            <Label htmlFor="role">Role</Label>
            <Select value={role} onValueChange={changeRole}>
              <SelectTrigger id="role" className="h-9">
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

          {!isEdit && (projects.data?.length ?? 0) > 0 && (
            <div className="grid gap-1.5">
              <Label htmlFor="project">Project</Label>
              <Select value={projectId} onValueChange={setProjectId}>
                <SelectTrigger id="project" className="h-9">
                  <SelectValue placeholder="Choose later" />
                </SelectTrigger>
                <SelectContent>
                  {projects.data!.map((p) => (
                    <SelectItem key={p.id} value={p.id}>
                      {p.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-xs text-muted-foreground">Their updates go to this project's sites.</p>
            </div>
          )}

          {!isEdit && (
            <label className="flex items-start gap-2.5 text-sm">
              <input
                type="checkbox"
                className="mt-0.5 size-4 accent-primary"
                checked={login}
                onChange={(e) => setLogin(e.target.checked)}
              />
              <span>
                Also give them a dashboard login
                <span className="block text-xs text-muted-foreground">Only for people who will use the web dashboard.</span>
              </span>
            </label>
          )}

          {login && (
            <div className="grid gap-1.5">
              <Label htmlFor="email">Email (to sign in)</Label>
              <Input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="ravi@company.in"
                disabled={isEdit}
                required={!isEdit}
              />
            </div>
          )}

          {login && (
            <div className="border-t pt-3 space-y-3">
              <div className="flex items-center justify-between">
                <Label htmlFor="password">
                  {isEdit ? 'New password (leave empty to keep it)' : 'Password'}
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
                    placeholder="Type it again"
                    required={!!password}
                  />
                </div>
              </div>
            </div>
          )}

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
              {loading ? 'Saving…' : isEdit ? 'Save' : 'Add person'}
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
          <SheetTitle>Projects and sites</SheetTitle>
          <SheetDescription>
            What {user?.full_name} can see and report on.
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
            <Label>Reaches</Label>
            <div className="flex items-center gap-4">
              <label className="flex items-center gap-2 text-sm font-medium cursor-pointer">
                <input
                  type="radio"
                  checked={mode === 'all_projects'}
                  onChange={() => setMode('all_projects')}
                  className="accent-primary"
                />
                Every project, including new ones
              </label>
              <label className="flex items-center gap-2 text-sm font-medium cursor-pointer">
                <input
                  type="radio"
                  checked={mode === 'custom_projects'}
                  onChange={() => setMode('custom_projects')}
                  className="accent-primary"
                />
                Only the ones ticked below
              </label>
            </div>
          </div>

          {mode === 'custom_projects' && (
            <div className="space-y-4 border-t pt-4">
              <Label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Projects and sites
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
                    No projects yet.
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
            {loading ? 'Saving…' : 'Save'}
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

  const isMapped = !!user?.whatsapp_number
  const [confirmRemove, setConfirmRemove] = React.useState(false)
  const removeNumber = async () => {
    if (!user) return
    setLoading(true)
    setError('')
    try {
      await updateUser(user.id, { whatsapp_number: null })
      setWhatsapp('')
      onSuccess()
      onOpenChange(false)
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Could not remove the number.')
    } finally {
      setLoading(false)
      setConfirmRemove(false)
    }
  }

  // WEB-29: a number field, Save and Remove. The old "Send verification"
  // and "Resolve duplicate conflicts" buttons only showed an "Integration
  // Gap" alert; they are gone.
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[420px]">
        <DialogHeader>
          <DialogTitle>WhatsApp number</DialogTitle>
          <DialogDescription>
            Messages from this number count as {user?.full_name ?? 'their'}'s site updates.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          {error && (
            <p className="flex items-center gap-2 text-sm text-destructive">
              <ShieldAlert className="size-4 shrink-0" /> {error}
            </p>
          )}
          <div className="grid gap-1.5">
            <Label htmlFor="mgrWhatsapp">Number, with country code</Label>
            <Input id="mgrWhatsapp" value={whatsapp} onChange={(e) => setWhatsapp(e.target.value)} placeholder="+91 98765 43210" inputMode="tel" autoFocus />
          </div>
          <DialogFooter className="flex-row items-center gap-2 sm:justify-between">
            {isMapped ? (
              confirmRemove ? (
                <span className="flex items-center gap-2 text-sm">
                  Remove it?
                  <Button type="button" size="sm" variant="destructive" disabled={loading} onClick={removeNumber}>
                    Remove
                  </Button>
                  <Button type="button" size="sm" variant="ghost" onClick={() => setConfirmRemove(false)}>
                    Keep
                  </Button>
                </span>
              ) : (
                <Button type="button" size="sm" variant="ghost" className="text-destructive hover:text-destructive" onClick={() => setConfirmRemove(true)}>
                  Remove number
                </Button>
              )
            ) : (
              <span />
            )}
            <Button type="submit" disabled={loading || !whatsapp.trim() || whatsapp === user?.whatsapp_number}>
              {loading ? 'Saving…' : 'Save'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
