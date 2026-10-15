import * as React from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  Search,
  Plus,
  Trash2,
  Edit2,
  FolderLock,
  MessageSquare,
  SlidersHorizontal,
  UserCheck,
  UserX,
  Building2,
  ExternalLink,
  ChevronDown,
  Loader2,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Avatar } from '@/components/ui/avatar'
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from '@/components/ui/table'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  DropdownMenuSeparator,
} from '@/components/ui/dropdown-menu'
import {
  fetchUsers,
  deleteUser,
  updateUserStatus,
  updateUserAccess,
  type User,
  type AccessPolicy,
} from '@/lib/api'
import { fetchProjects } from '@/lib/projects'
import { BulkActionBar } from '@/components/ui/bulk-action-bar'
import {
  AddEditUserDialog,
  AccessManagerDialog,
  WhatsAppManagerDialog,
} from '@/components/user-dialogs'
import type { ProjectItem } from '@/lib/scope-types'
import { useReadOnly } from '@/lib/trial'

const ROLE_BADGES = {
  ADMIN: 'destructive',
  PROJECT_MANAGER: 'default',
  SITE_ENGINEER: 'secondary',
  FINANCE: 'outline',
} as const

export default function Users() {
  // Free trial over: saves are refused, so don't offer them (SS-15).
  const readOnly = useReadOnly()
  const queryClient = useQueryClient()
  const [search, setSearch] = React.useState('')
  const [roleFilter, setRoleFilter] = React.useState('ALL')
  const [statusFilter, setStatusFilter] = React.useState('ALL')
  const [whatsappFilter, setWhatsappFilter] = React.useState('ALL')
  const [projectFilter, setProjectFilter] = React.useState('ALL')
  const [sortBy, setSortBy] = React.useState<'name' | 'role' | 'status'>('name')
  const [selectedIds, setSelectedIds] = React.useState<string[]>([])
  
  // Dialog Open States
  const [addEditOpen, setAddEditOpen] = React.useState(false)
  const [selectedUserForEdit, setSelectedUserForEdit] = React.useState<User | null>(null)
  
  const [accessOpen, setAccessOpen] = React.useState(false)
  const [selectedUserForAccess, setSelectedUserForAccess] = React.useState<User | null>(null)

  const [whatsappOpen, setWhatsappOpen] = React.useState(false)
  const [selectedUserForWhatsapp, setSelectedUserForWhatsapp] = React.useState<User | null>(null)

  // Advanced filters expansion
  const [showAdvanced, setShowAdvanced] = React.useState(false)

  // Fetch Users
  const { data: users = [], isLoading, isError, error } = useQuery<User[]>({
    queryKey: ['users-list'],
    queryFn: fetchUsers,
  })

  // Fetch Projects for filtering
  const { data: projects = [] } = useQuery<ProjectItem[]>({
    queryKey: ['filter-projects-list'],
    queryFn: fetchProjects,
  })

  // Mutations
  const deleteMutation = useMutation({
    mutationFn: deleteUser,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users-list'] })
      setSelectedIds([])
    },
    onError: (err: any) => {
      alert(err.response?.data?.detail || 'Failed to delete user.')
    },
  })

  const statusMutation = useMutation({
    mutationFn: ({ userId, status }: { userId: string; status: string }) =>
      updateUserStatus(userId, status),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users-list'] })
    },
    onError: (err: any) => {
      alert(err.response?.data?.detail || 'Failed to update user status.')
    },
  })

  const accessBulkMutation = useMutation({
    mutationFn: ({ userId, policy }: { userId: string; policy: AccessPolicy }) =>
      updateUserAccess(userId, policy),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users-list'] })
    },
  })

  // Filtered & Sorted list
  const filteredUsers = React.useMemo(() => {
    return users
      .filter((u) => {
        // Text search (name, email, whatsapp)
        const matchText =
          u.full_name.toLowerCase().includes(search.toLowerCase()) ||
          u.email.toLowerCase().includes(search.toLowerCase()) ||
          (u.whatsapp_number && u.whatsapp_number.includes(search))
        if (!matchText) return false

        // Role Filter
        if (roleFilter !== 'ALL' && u.role !== roleFilter) return false

        // Status Filter
        if (statusFilter !== 'ALL' && u.status !== statusFilter) return false

        // WhatsApp Filter
        if (whatsappFilter !== 'ALL') {
          const hasWhatsapp = !!u.whatsapp_number
          if (whatsappFilter === 'MAPPED' && !hasWhatsapp) return false
          if (whatsappFilter === 'UNMAPPED' && hasWhatsapp) return false
        }

        // Project Filter
        if (projectFilter !== 'ALL') {
          const policy = u.access_policy
          if (!policy) return false
          if (policy.mode === 'all_projects') return true
          const hasProject = policy.projects?.some((p) => p.projectId === projectFilter)
          if (!hasProject) return false
        }

        return true
      })
      .sort((a, b) => {
        if (sortBy === 'name') return a.full_name.localeCompare(b.full_name)
        if (sortBy === 'role') return a.role.localeCompare(b.role)
        if (sortBy === 'status') return a.status.localeCompare(b.status)
        return 0
      })
  }, [users, search, roleFilter, statusFilter, whatsappFilter, projectFilter, sortBy])

  // Count summaries
  const stats = React.useMemo(() => {
    const total = users.length
    const active = users.filter((u) => u.status === 'active').length
    const inactive = users.filter((u) => u.status === 'inactive' || u.status === 'suspended').length
    const withWa = users.filter((u) => !!u.whatsapp_number).length
    const withoutWa = total - withWa

    return { total, active, inactive, withWa, withoutWa }
  }, [users])

  // Selection handlers
  const handleSelectAll = (checked: boolean) => {
    if (checked) {
      setSelectedIds(filteredUsers.map((u) => u.id))
    } else {
      setSelectedIds([])
    }
  }

  const handleSelectRow = (userId: string, checked: boolean) => {
    if (checked) {
      setSelectedIds((prev) => [...prev, userId])
    } else {
      setSelectedIds((prev) => prev.filter((id) => id !== userId))
    }
  }

  // Bulk operations
  const handleBulkStatus = async (status: 'active' | 'inactive') => {
    if (confirm(`Change status to ${status} for ${selectedIds.length} users?`)) {
      for (const id of selectedIds) {
        await statusMutation.mutateAsync({ userId: id, status })
      }
      setSelectedIds([])
    }
  }

  const handleBulkDelete = async () => {
    if (confirm(`Permanently delete ${selectedIds.length} selected users? This action is irreversible.`)) {
      for (const id of selectedIds) {
        await deleteMutation.mutateAsync(id)
      }
      setSelectedIds([])
    }
  }

  const handleBulkAssignProject = async (projectId: string) => {
    if (confirm(`Assign project to ${selectedIds.length} selected users?`)) {
      for (const id of selectedIds) {
        const targetUser = users.find((u) => u.id === id)
        if (!targetUser) continue
        const policy = targetUser.access_policy || { mode: 'custom_projects', projects: [] }
        
        // Skip if already assigned or in all_projects mode
        if (policy.mode === 'all_projects') continue
        const alreadyAssigned = policy.projects?.some((p) => p.projectId === projectId)
        if (alreadyAssigned) continue

        const updatedProjects = [...(policy.projects || []), { projectId, siteAccess: { mode: 'all_sites' as const } }]
        await accessBulkMutation.mutateAsync({
          userId: id,
          policy: { ...policy, projects: updatedProjects } as AccessPolicy,
        })
      }
      setSelectedIds([])
    }
  }

  const clearFilters = () => {
    setSearch('')
    setRoleFilter('ALL')
    setStatusFilter('ALL')
    setWhatsappFilter('ALL')
    setProjectFilter('ALL')
    setSortBy('name')
  }

  return (
    <div className="flex flex-col gap-4">
      {/* Page Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-foreground">Users</h1>
          <p className="text-xs text-muted-foreground">
            Manage organization users, roles, project/site access policies, and WhatsApp identities.
          </p>
        </div>
        <div className="flex gap-2">
          {!readOnly && (
          <Button
            size="sm"
            onClick={() => {
              setSelectedUserForEdit(null)
              setAddEditOpen(true)
            }}
            className="h-8 gap-1.5"
          >
            <Plus className="size-4" />
            Add User
          </Button>
          )}
        </div>
      </div>

      {/* User Summary Widget */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5 border border-border/60 bg-muted/5 p-3 rounded">
        <div>
          <span className="block text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            Total Users
          </span>
          <span className="text-lg font-bold font-mono">{stats.total}</span>
        </div>
        <div>
          <span className="block text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            Active Users
          </span>
          <span className="text-lg font-bold text-emerald-600 dark:text-emerald-400 font-mono">
            {stats.active}
          </span>
        </div>
        <div>
          <span className="block text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            Inactive / Suspended
          </span>
          <span className="text-lg font-bold text-rose-600 dark:text-rose-400 font-mono">
            {stats.inactive}
          </span>
        </div>
        <div>
          <span className="block text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            Mapped WhatsApp
          </span>
          <span className="text-lg font-bold text-primary font-mono">{stats.withWa}</span>
        </div>
        <div>
          <span className="block text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            Unmapped WhatsApp
          </span>
          <span className="text-lg font-bold text-muted-foreground font-mono">{stats.withoutWa}</span>
        </div>
      </div>

      {/* Search and Filters Toolbar */}
      <div className="flex flex-col gap-3 border border-border/60 p-3 rounded">
        <div className="flex flex-col md:flex-row gap-2">
          <div className="relative flex-1">
            <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Search name, email, phone, or WhatsApp..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-9 h-9"
            />
          </div>
          <div className="flex gap-2">
            <Select value={roleFilter} onValueChange={setRoleFilter}>
              <SelectTrigger className="w-[140px] h-9">
                <SelectValue placeholder="All Roles" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="ALL">All Roles</SelectItem>
                <SelectItem value="ADMIN">Admin / Director</SelectItem>
                <SelectItem value="PROJECT_MANAGER">Project Manager</SelectItem>
                <SelectItem value="SITE_ENGINEER">Site Engineer</SelectItem>
                <SelectItem value="FINANCE">Finance</SelectItem>
              </SelectContent>
            </Select>

            <Select value={statusFilter} onValueChange={setStatusFilter}>
              <SelectTrigger className="w-[140px] h-9">
                <SelectValue placeholder="All Statuses" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="ALL">All Statuses</SelectItem>
                <SelectItem value="active">Active</SelectItem>
                <SelectItem value="inactive">Inactive</SelectItem>
                <SelectItem value="suspended">Suspended</SelectItem>
                <SelectItem value="invited">Invited</SelectItem>
              </SelectContent>
            </Select>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setShowAdvanced(!showAdvanced)}
              className="h-9 text-xs gap-1.5"
            >
              <SlidersHorizontal className="size-3.5" />
              Advanced
            </Button>
            {(search || roleFilter !== 'ALL' || statusFilter !== 'ALL' || whatsappFilter !== 'ALL' || projectFilter !== 'ALL') && (
              <Button variant="ghost" size="sm" onClick={clearFilters} className="h-9 text-xs">
                Clear
              </Button>
            )}
          </div>
        </div>

        {/* Expandable Advanced Filters */}
        {showAdvanced && (
          <div className="grid gap-3 border-t pt-3 grid-cols-1 sm:grid-cols-3">
            <div className="grid gap-1">
              <label className="text-[10px] uppercase font-semibold text-muted-foreground">WhatsApp Link</label>
              <Select value={whatsappFilter} onValueChange={setWhatsappFilter}>
                <SelectTrigger className="h-9">
                  <SelectValue placeholder="WhatsApp Link" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="ALL">All Mappings</SelectItem>
                  <SelectItem value="MAPPED">Mapped Only</SelectItem>
                  <SelectItem value="UNMAPPED">Unmapped Only</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="grid gap-1">
              <label className="text-[10px] uppercase font-semibold text-muted-foreground">Project Access</label>
              <Select value={projectFilter} onValueChange={setProjectFilter}>
                <SelectTrigger className="h-9">
                  <SelectValue placeholder="Project Access" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="ALL">All Projects</SelectItem>
                  {projects.map((p) => (
                    <SelectItem key={p.id} value={p.id}>
                      {p.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="grid gap-1">
              <label className="text-[10px] uppercase font-semibold text-muted-foreground">Sort Table By</label>
              <Select value={sortBy} onValueChange={(val) => setSortBy(val as any)}>
                <SelectTrigger className="h-9">
                  <SelectValue placeholder="Sort By" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="name">Name</SelectItem>
                  <SelectItem value="role">Role</SelectItem>
                  <SelectItem value="status">Status</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
        )}
      </div>

      {/* Main Data Table */}
      {isLoading ? (
        <div className="flex h-48 items-center justify-center text-sm text-muted-foreground gap-2">
          <Loader2 className="size-4 animate-spin text-primary" />
          Loading users directory...
        </div>
      ) : isError ? (
        <div className="bg-destructive/10 border border-destructive text-destructive text-xs p-4 rounded text-center">
          Failed to load users: {error instanceof Error ? error.message : 'Unknown API error.'}
        </div>
      ) : filteredUsers.length === 0 ? (
        <div className="border border-dashed p-12 text-center text-sm text-muted-foreground rounded-lg">
          No users match the active search query or filter parameters.
        </div>
      ) : (
        <div className="border border-border/60 rounded overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow className="bg-muted/10">
                <TableHead className="w-12 px-4">
                  <input
                    type="checkbox"
                    checked={selectedIds.length === filteredUsers.length}
                    onChange={(e) => handleSelectAll(e.target.checked)}
                    className="rounded border-border/80 text-primary focus:ring-primary size-4"
                  />
                </TableHead>
                <TableHead>User</TableHead>
                <TableHead>Role</TableHead>
                <TableHead>Project Scope</TableHead>
                <TableHead>WhatsApp Number</TableHead>
                <TableHead>Account Status</TableHead>
                <TableHead className="w-20 text-right pr-4">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filteredUsers.map((user) => {
                const isSelected = selectedIds.includes(user.id)
                const mappedProjectCount = user.access_policy?.projects?.length ?? 0
                const isAllProjects = user.access_policy?.mode === 'all_projects'

                return (
                  <TableRow key={user.id} data-state={isSelected ? 'selected' : undefined}>
                    <TableCell className="px-4">
                      <input
                        type="checkbox"
                        checked={isSelected}
                        onChange={(e) => handleSelectRow(user.id, e.target.checked)}
                        className="rounded border-border/80 text-primary focus:ring-primary size-4"
                      />
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-2.5">
                        <Avatar className="size-8 rounded-full border border-border bg-muted flex items-center justify-center text-xs font-semibold text-muted-foreground">
                          {user.full_name.substring(0, 2).toUpperCase()}
                        </Avatar>
                        <div className="flex flex-col">
                          <Link
                            to={`/users/${user.id}`}
                            className="font-medium text-foreground hover:underline flex items-center gap-1"
                          >
                            {user.full_name}
                            <ExternalLink className="size-3 text-muted-foreground/60" />
                          </Link>
                          <span className="text-[11px] text-muted-foreground">{user.email}</span>
                        </div>
                      </div>
                    </TableCell>
                    <TableCell>
                      <Badge variant={ROLE_BADGES[user.role] || 'secondary'} className="text-[10px] rounded-sm px-1.5 py-0">
                        {user.role}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {isAllProjects ? (
                        <span className="font-semibold text-primary">All Projects</span>
                      ) : mappedProjectCount > 0 ? (
                        <span>{mappedProjectCount} Assigned</span>
                      ) : (
                        <span className="italic text-muted-foreground/60">No access</span>
                      )}
                    </TableCell>
                    <TableCell className="font-mono text-xs">
                      {user.whatsapp_number ? (
                        <div className="flex items-center gap-1.5 text-foreground">
                          <MessageSquare className="size-3 text-emerald-500" />
                          {user.whatsapp_number}
                        </div>
                      ) : (
                        <span className="text-muted-foreground/40 italic">Not Added</span>
                      )}
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant={user.status === 'active' ? 'default' : 'outline'}
                        className={`text-[10px] rounded-sm px-1.5 py-0 ${
                          user.status === 'active'
                            ? 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border-none'
                            : 'bg-rose-500/10 text-rose-700 dark:text-rose-400 border-none'
                        }`}
                      >
                        {user.status}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right pr-4">
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button variant="ghost" className="size-8 p-0">
                            <ChevronDown className="size-4 text-muted-foreground" />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end" className="w-40">
                          <DropdownMenuItem onClick={() => {
                            setSelectedUserForEdit(user)
                            setAddEditOpen(true)
                          }}>
                            <Edit2 className="size-3.5 mr-2" />
                            Edit Profile
                          </DropdownMenuItem>
                          <DropdownMenuItem onClick={() => {
                            setSelectedUserForAccess(user)
                            setAccessOpen(true)
                          }}>
                            <FolderLock className="size-3.5 mr-2" />
                            Manage Access
                          </DropdownMenuItem>
                          <DropdownMenuItem onClick={() => {
                            setSelectedUserForWhatsapp(user)
                            setWhatsappOpen(true)
                          }}>
                            <MessageSquare className="size-3.5 mr-2" />
                            Manage WhatsApp
                          </DropdownMenuItem>
                          <DropdownMenuSeparator />
                          {user.status === 'active' ? (
                            <DropdownMenuItem
                              onClick={() =>
                                statusMutation.mutate({ userId: user.id, status: 'inactive' })
                              }
                            >
                              <UserX className="size-3.5 mr-2 text-rose-500" />
                              Deactivate
                            </DropdownMenuItem>
                          ) : (
                            <DropdownMenuItem
                              onClick={() =>
                                statusMutation.mutate({ userId: user.id, status: 'active' })
                              }
                            >
                              <UserCheck className="size-3.5 mr-2 text-emerald-500" />
                              Activate
                            </DropdownMenuItem>
                          )}
                          <DropdownMenuItem
                            onClick={async () => {
                              if (
                                confirm(
                                  `Are you sure you want to permanently delete user "${user.full_name}"?`
                                )
                              ) {
                                deleteMutation.mutate(user.id)
                              }
                            }}
                            className="text-destructive hover:bg-destructive/10"
                          >
                            <Trash2 className="size-3.5 mr-2" />
                            Delete User
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </div>
      )}

      {/* Bulk Operations Sticky Toolbar */}
      <BulkActionBar selectedCount={selectedIds.length} onClear={() => setSelectedIds([])}>
        <Button
          variant="outline"
          size="sm"
          onClick={() => handleBulkStatus('active')}
          className="h-8 text-xs text-emerald-600 dark:text-emerald-400 gap-1"
        >
          <UserCheck className="size-3.5" />
          Activate
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={() => handleBulkStatus('inactive')}
          className="h-8 text-xs text-rose-600 dark:text-rose-400 gap-1"
        >
          <UserX className="size-3.5" />
          Deactivate
        </Button>

        {/* Quick bulk project assigner */}
        {projects.length > 0 && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="sm" className="h-8 text-xs gap-1">
                <Building2 className="size-3.5" />
                Assign Project
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="max-h-48 overflow-y-auto">
              {projects.map((p) => (
                <DropdownMenuItem key={p.id} onClick={() => handleBulkAssignProject(p.id)}>
                  {p.name}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        )}

        <Button
          variant="outline"
          size="sm"
          onClick={handleBulkDelete}
          className="h-8 text-xs text-destructive hover:bg-destructive/10 gap-1"
        >
          <Trash2 className="size-3.5" />
          Delete Selected
        </Button>
      </BulkActionBar>

      {/* Dialog Containers */}
      <AddEditUserDialog
        open={addEditOpen}
        onOpenChange={setAddEditOpen}
        user={selectedUserForEdit}
        onSuccess={() => queryClient.invalidateQueries({ queryKey: ['users-list'] })}
      />

      <AccessManagerDialog
        open={accessOpen}
        onOpenChange={setAccessOpen}
        user={selectedUserForAccess}
        onSuccess={() => queryClient.invalidateQueries({ queryKey: ['users-list'] })}
      />

      <WhatsAppManagerDialog
        open={whatsappOpen}
        onOpenChange={setWhatsappOpen}
        user={selectedUserForWhatsapp}
        onSuccess={() => queryClient.invalidateQueries({ queryKey: ['users-list'] })}
      />
    </div>
  )
}
