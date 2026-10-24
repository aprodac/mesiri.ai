import * as React from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  Search,
  Plus,
  Edit2,
  FolderLock,
  MessageSquare,
  SlidersHorizontal,
  ChevronDown,
  Loader2,
  ExternalLink,
  UserCheck,
  UserX,
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
} from '@/components/ui/dropdown-menu'
import {
  fetchUsers,
  updateUserStatus,
  type User,
} from '@/lib/api'
import { fetchProjects } from '@/lib/projects'
import {
  AddEditUserDialog,
  AccessManagerDialog,
  WhatsAppManagerDialog,
} from '@/components/user-dialogs'
import type { ProjectItem } from '@/lib/scope-types'

const ROLE_BADGES = {
  ADMIN: 'destructive',
  PROJECT_MANAGER: 'default',
  SITE_ENGINEER: 'secondary',
  FINANCE: 'outline',
} as const

export function UsersTab() {
  const queryClient = useQueryClient()
  const [search, setSearch] = React.useState('')
  const [roleFilter, setRoleFilter] = React.useState('ALL')
  const [statusFilter, setStatusFilter] = React.useState('ALL')
  const [whatsappFilter, setWhatsappFilter] = React.useState('ALL')
  const [projectFilter, setProjectFilter] = React.useState('ALL')
  const [showAdvanced, setShowAdvanced] = React.useState(false)

  // Dialog Open States
  const [addEditOpen, setAddEditOpen] = React.useState(false)
  const [selectedUserForEdit, setSelectedUserForEdit] = React.useState<User | null>(null)
  
  const [accessOpen, setAccessOpen] = React.useState(false)
  const [selectedUserForAccess, setSelectedUserForAccess] = React.useState<User | null>(null)

  const [whatsappOpen, setWhatsappOpen] = React.useState(false)
  const [selectedUserForWhatsapp, setSelectedUserForWhatsapp] = React.useState<User | null>(null)

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

  // Status Change Mutation
  const toggleStatusMutation = useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) =>
      updateUserStatus(id, status),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users-list'] })
    },
  })

  // Clear filters
  const clearFilters = () => {
    setSearch('')
    setRoleFilter('ALL')
    setStatusFilter('ALL')
    setWhatsappFilter('ALL')
    setProjectFilter('ALL')
  }

  // Filter users client-side to preserve performance and avoid double roundtrips
  const filteredUsers = React.useMemo(() => {
    return users.filter((user) => {
      // 1. Search term match
      if (search.trim()) {
        const query = search.toLowerCase()
        const matchName = user.full_name.toLowerCase().includes(query)
        const matchEmail = user.email.toLowerCase().includes(query)
        const matchWa = user.whatsapp_number?.toLowerCase().includes(query)
        if (!matchName && !matchEmail && !matchWa) return false
      }

      // 2. Role match
      if (roleFilter !== 'ALL' && user.role !== roleFilter) return false

      // 3. Status match
      if (statusFilter !== 'ALL' && user.status !== statusFilter) return false

      // 4. WhatsApp Mapping match
      const hasWhatsapp = !!user.whatsapp_number
      if (whatsappFilter === 'MAPPED' && !hasWhatsapp) return false
      if (whatsappFilter === 'UNMAPPED' && hasWhatsapp) return false

      // 5. Project Access match
      if (projectFilter !== 'ALL') {
        const hasProjectAccess = user.access_policy?.projects?.some(
          (p) => p.projectId === projectFilter
        )
        const hasAllAccess = user.access_policy?.mode === 'all_projects'
        if (!hasProjectAccess && !hasAllAccess) return false
      }

      return true
    })
  }, [users, search, roleFilter, statusFilter, whatsappFilter, projectFilter])

  return (
    <div className="space-y-4">
      {/* Search and Filters Toolbar */}
      <div className="flex flex-col gap-3 border border-border/60 p-3 rounded">
        <div className="flex flex-col md:flex-row gap-2">
          <div className="relative flex-1">
            <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Search name, email, or WhatsApp..."
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
            <Button
              size="sm"
              onClick={() => {
                setSelectedUserForEdit(null)
                setAddEditOpen(true)
              }}
              className="h-9 text-xs gap-1"
            >
              <Plus className="size-4" />
              Add User
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
          <div className="grid gap-3 border-t pt-3 grid-cols-1 sm:grid-cols-2">
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
                const mappedProjectCount = user.access_policy?.projects?.length ?? 0
                const isAllProjects = user.access_policy?.mode === 'all_projects'

                return (
                  <TableRow key={user.id}>
                    <TableCell>
                      <div className="flex items-center gap-2.5">
                        <Avatar className="size-8 rounded-full border border-border bg-muted flex items-center justify-center text-xs font-semibold text-muted-foreground">
                          {user.full_name.substring(0, 2).toUpperCase()}
                        </Avatar>
                        <div className="flex flex-col">
                          <Link
                            to={`/team/${user.id}`}
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
                        <DropdownMenuContent align="end" className="w-44">
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
                            WhatsApp Number
                          </DropdownMenuItem>
                          {user.status === 'active' ? (
                            <DropdownMenuItem
                              className="text-rose-600 dark:text-rose-400"
                              onClick={() => toggleStatusMutation.mutate({ id: user.id, status: 'suspended' })}
                            >
                              <UserX className="size-3.5 mr-2" />
                              Suspend User
                            </DropdownMenuItem>
                          ) : (
                            <DropdownMenuItem
                              className="text-emerald-600 dark:text-emerald-400"
                              onClick={() => toggleStatusMutation.mutate({ id: user.id, status: 'active' })}
                            >
                              <UserCheck className="size-3.5 mr-2" />
                              Activate User
                            </DropdownMenuItem>
                          )}
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

      {/* Reusable dialog integrations */}
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
