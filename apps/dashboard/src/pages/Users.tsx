import * as React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { FolderLock, MessageSquare, MessageSquareOff, MoreHorizontal, Pencil, Plus, Search, Trash2, UserCheck, UserX, Users as UsersIcon } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { useToast } from '@/components/ui/toast-notification'
import { Callout, PageError, PageHeader, Segmented } from '@/components/dpr-page'
import { AccessManagerDialog, AddEditUserDialog, WhatsAppManagerDialog } from '@/components/user-dialogs'
import { deleteUser, fetchUsers, updateUserStatus, type User } from '@/lib/api'
import { roleLabel, type Role } from '@/lib/permissions'
import { CHIP } from '@/lib/site-day'
import { apiErrorMessage } from '@/lib/logo-upload'
import { usePageTitle } from '@/lib/page-title'
import { useUrlState } from '@/lib/url-state'
import { useReadOnly } from '@/lib/trial'
import { cn } from '@/lib/utils'
import { initials, projectAccessText, useMemberships } from '@/lib/team'

// WEB-28: the team as rows that say, for each person, what matters for
// Mesiri to work -- the projects they reach and whether they have a
// WhatsApp number to report from. No count tiles, no bulk delete.

const ROLES: Role[] = ['ADMIN', 'PROJECT_MANAGER', 'SITE_ENGINEER', 'FINANCE']
const SHORT_ROLE: Record<Role, string> = { ADMIN: 'Admins', PROJECT_MANAGER: 'Managers', SITE_ENGINEER: 'Engineers', FINANCE: 'Finance' }

type Dialogs =
  | { kind: 'edit'; user: User | null }
  | { kind: 'access'; user: User }
  | { kind: 'whatsapp'; user: User }
  | { kind: 'status'; user: User }
  | { kind: 'delete'; user: User }
  | null

export default function Users() {
  const readOnly = useReadOnly()
  const toast = useToast()
  const queryClient = useQueryClient()
  usePageTitle('Team')
  const [search, setSearch] = useUrlState<string>('q', '')
  const [role, setRole] = useUrlState<string>('role', 'ALL')
  const [show, setShow] = useUrlState<'active' | 'inactive'>('show', 'active')
  const [dialog, setDialog] = React.useState<Dialogs>(null)

  const query = useQuery<User[]>({ queryKey: ['users-list'], queryFn: fetchUsers })
  const memberships = useMemberships()
  const users = React.useMemo(() => query.data ?? [], [query.data])
  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['users-list'] })
    queryClient.invalidateQueries({ queryKey: ['project-members-count'] })
  }

  const statusMutation = useMutation({
    mutationFn: ({ user, status }: { user: User; status: string }) => updateUserStatus(user.id, status),
    onSuccess: (_, { user, status }) => {
      toast.success(status === 'active' ? 'Active again' : 'Deactivated', status === 'active' ? `${user.full_name} can use Mesiri again.` : `${user.full_name} can no longer use the dashboard or send updates.`)
      setDialog(null)
      refresh()
    },
    onError: (err) => toast.error('Could not change', apiErrorMessage(err)),
  })
  const deleteMutation = useMutation({
    mutationFn: (user: User) => deleteUser(user.id),
    onSuccess: (_, user) => {
      toast.success('Deleted', `${user.full_name} is removed from the team.`)
      setDialog(null)
      refresh()
    },
    onError: (err) => toast.error('Could not delete', apiErrorMessage(err)),
  })

  const isActive = (u: User) => u.status === 'active' || u.status === 'invited'
  const active = users.filter(isActive)
  const inactive = users.length - active.length
  const noWhatsApp = active.filter((u) => !u.whatsapp_number)
  const roleCounts = ROLES.map((r) => ({ r, n: users.filter((u) => u.role === r && (show === 'active') === isActive(u)).length })).filter((x) => x.n > 0)
  const visible = users
    .filter((u) => (show === 'active') === isActive(u))
    .filter((u) => role === 'ALL' || u.role === role)
    .filter((u) => {
      const q = search.trim().toLowerCase()
      return !q || [u.full_name, u.email, u.whatsapp_number].some((v) => v?.toLowerCase().includes(q))
    })
    .sort((a, b) => a.full_name.localeCompare(b.full_name))

  if (query.isError) {
    return <PageError message="The team could not be loaded." onRetry={() => query.refetch()} back={{ to: '/today', label: 'Back to Today' }} />
  }

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-4 pb-8 sm:px-2">
      <PageHeader
        title="Team"
        subtitle={query.isLoading ? 'Loading…' : `${active.length} ${active.length === 1 ? 'person' : 'people'}${inactive ? ` · ${inactive} deactivated` : ''}`}
        actions={
          !readOnly && (
            <Button size="sm" className="gap-1.5 font-semibold" onClick={() => setDialog({ kind: 'edit', user: null })}>
              <Plus className="size-4" /> Add person
            </Button>
          )
        }
      />

      {noWhatsApp.length > 0 && (
        <Callout tone="draft" icon={MessageSquareOff}>
          <strong className="font-semibold">
            {noWhatsApp.length === 1 ? `${noWhatsApp[0].full_name} has` : `${noWhatsApp.length} people have`} no WhatsApp number
          </strong>
          <span className="hidden sm:inline"> and can't send updates from site. Add it from the ⋯ menu.</span>
        </Callout>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative w-full sm:w-64">
          <Search className="absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
          <Input placeholder="Search name, email or number…" aria-label="Search the team" value={search} onChange={(e) => setSearch(e.target.value)} className="h-9 pl-8" />
        </div>
        {roleCounts.length > 1 && (
          <Segmented<string>
            label="Role"
            value={role}
            onChange={setRole}
            options={[{ value: 'ALL', label: 'Everyone' }, ...roleCounts.map(({ r, n }) => ({ value: r, label: SHORT_ROLE[r], count: n }))]}
          />
        )}
        {inactive > 0 && (
          <Segmented<'active' | 'inactive'>
            label="Show"
            value={show}
            onChange={setShow}
            options={[
              { value: 'active', label: 'Active' },
              { value: 'inactive', label: 'Deactivated', count: inactive },
            ]}
          />
        )}
      </div>

      {query.isLoading ? (
        <div className="flex flex-col gap-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-16 rounded-lg" />
          ))}
        </div>
      ) : visible.length === 0 ? (
        <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed py-12 text-center">
          <UsersIcon className="size-6 text-muted-foreground" aria-hidden="true" />
          <p className="text-sm font-medium">{users.length === 0 ? 'No one on the team yet' : 'No one matches'}</p>
        </div>
      ) : (
        <ul className="flex flex-col divide-y rounded-xl border">
          {visible.map((user) => {
            const access = memberships.loading
              ? { text: '…', none: false }
              : projectAccessText(user, memberships.byUser.get(user.id) ?? [], memberships.names)
            return (
              <li key={user.id} className="flex items-center gap-3 px-4 py-3">
                <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-semibold text-muted-foreground" aria-hidden="true">
                  {initials(user.full_name)}
                </span>
                <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                  <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                    <Link to={`/team/${user.id}`} className="font-semibold hover:underline">
                      {user.full_name}
                    </Link>
                    <span className="text-sm text-muted-foreground">{roleLabel(user.role)}</span>
                    {user.status !== 'active' && <span className={cn(CHIP, 'bg-muted text-muted-foreground')}>{user.status === 'invited' ? 'Invited' : 'Deactivated'}</span>}
                  </div>
                  <div className="flex flex-wrap gap-x-4 gap-y-0.5 text-sm">
                    <span className={cn('inline-flex min-w-0 items-center gap-1.5', access.none ? 'text-draft' : 'text-muted-foreground')}>
                      <FolderLock className="size-3.5 shrink-0" aria-hidden="true" />
                      <span className="truncate">{access.text}</span>
                    </span>
                    <span className={cn('inline-flex items-center gap-1.5 tabular-nums', user.whatsapp_number ? 'text-muted-foreground' : 'text-draft')}>
                      <MessageSquare className="size-3.5 shrink-0" aria-hidden="true" />
                      {user.whatsapp_number ? `+${user.whatsapp_number.replace(/^\+/, '')}` : 'No WhatsApp number'}
                    </span>
                  </div>
                </div>
                {!readOnly && (
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button variant="ghost" size="icon" className="size-8 shrink-0" aria-label={`More for ${user.full_name}`}>
                        <MoreHorizontal className="size-4" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" className="w-52">
                      <DropdownMenuItem onClick={() => setDialog({ kind: 'edit', user })}>
                        <Pencil className="mr-2 size-3.5" /> Edit name, email, role
                      </DropdownMenuItem>
                      <DropdownMenuItem onClick={() => setDialog({ kind: 'access', user })}>
                        <FolderLock className="mr-2 size-3.5" /> Projects and sites
                      </DropdownMenuItem>
                      <DropdownMenuItem onClick={() => setDialog({ kind: 'whatsapp', user })}>
                        <MessageSquare className="mr-2 size-3.5" /> WhatsApp number
                      </DropdownMenuItem>
                      <DropdownMenuSeparator />
                      <DropdownMenuItem onClick={() => setDialog({ kind: 'status', user })}>
                        {user.status === 'active' ? <UserX className="mr-2 size-3.5" /> : <UserCheck className="mr-2 size-3.5" />}
                        {user.status === 'active' ? 'Deactivate' : 'Make active'}
                      </DropdownMenuItem>
                      <DropdownMenuItem className="text-destructive focus:text-destructive" onClick={() => setDialog({ kind: 'delete', user })}>
                        <Trash2 className="mr-2 size-3.5" /> Delete
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                )}
              </li>
            )
          })}
        </ul>
      )}

      <Dialog open={dialog?.kind === 'status' || dialog?.kind === 'delete'} onOpenChange={(open) => !open && setDialog(null)}>
        <DialogContent className="sm:max-w-md">
          {(dialog?.kind === 'status' || dialog?.kind === 'delete') && (
            <>
              <DialogHeader>
                <DialogTitle className="text-base font-semibold">
                  {dialog.kind === 'delete'
                    ? `Delete ${dialog.user.full_name}?`
                    : dialog.user.status === 'active'
                      ? `Deactivate ${dialog.user.full_name}?`
                      : `Make ${dialog.user.full_name} active again?`}
                </DialogTitle>
                <DialogDescription>
                  {dialog.kind === 'delete'
                    ? 'They are removed from the team for good. What they reported stays on the reports. To pause someone instead, deactivate them.'
                    : dialog.user.status === 'active'
                      ? 'They can no longer use the dashboard, and messages from their WhatsApp number are not taken as updates. You can make them active again later.'
                      : 'They can use the dashboard and send updates again.'}
                </DialogDescription>
              </DialogHeader>
              <DialogFooter>
                <Button variant="outline" onClick={() => setDialog(null)}>
                  Cancel
                </Button>
                {dialog.kind === 'delete' ? (
                  <Button variant="destructive" disabled={deleteMutation.isPending} onClick={() => deleteMutation.mutate(dialog.user)}>
                    {deleteMutation.isPending ? 'Deleting…' : 'Delete'}
                  </Button>
                ) : (
                  <Button
                    variant={dialog.user.status === 'active' ? 'destructive' : 'default'}
                    disabled={statusMutation.isPending}
                    onClick={() => statusMutation.mutate({ user: dialog.user, status: dialog.user.status === 'active' ? 'inactive' : 'active' })}
                  >
                    {dialog.user.status === 'active' ? 'Deactivate' : 'Make active'}
                  </Button>
                )}
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>

      <AddEditUserDialog
        open={dialog?.kind === 'edit'}
        onOpenChange={(open) => !open && setDialog(null)}
        user={dialog?.kind === 'edit' ? dialog.user : null}
        onSuccess={refresh}
      />
      <AccessManagerDialog
        open={dialog?.kind === 'access'}
        onOpenChange={(open) => !open && setDialog(null)}
        user={dialog?.kind === 'access' ? dialog.user : null}
        onSuccess={refresh}
      />
      <WhatsAppManagerDialog
        open={dialog?.kind === 'whatsapp'}
        onOpenChange={(open) => !open && setDialog(null)}
        user={dialog?.kind === 'whatsapp' ? dialog.user : null}
        onSuccess={refresh}
      />
    </div>
  )
}
