import * as React from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FolderLock, KeyRound, MessageSquare, MessageSquareOff, Pencil, Trash2, UserCheck, UserX } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { useToast } from '@/components/ui/toast-notification'
import { Callout, DprAside, DprHeader, DprSection, PageError } from '@/components/dpr-page'
import { AccessManagerDialog, AddEditUserDialog, WhatsAppManagerDialog } from '@/components/user-dialogs'
import { UserWhatsAppMessagesTab } from '@/components/user-whatsapp-messages-tab'
import { deleteUser, fetchUser, updateUser, updateUserStatus, type User } from '@/lib/api'
import { isOrgWide, useMemberships } from '@/lib/team'
import { roleLabel } from '@/lib/permissions'
import { CHIP } from '@/lib/site-day'
import { useSiteNames } from '@/lib/site-names'
import { apiErrorMessage } from '@/lib/logo-upload'
import { usePageTitle } from '@/lib/page-title'
import { useReadOnly } from '@/lib/trial'
import { cn } from '@/lib/utils'

// WEB-28: one person on one page -- what they can reach, the messages they
// sent on WhatsApp, their details -- instead of six tabs. The old Activity
// tab (the whole company's timeline under an "Integration Gap" notice) and
// the WhatsApp tab (one field and a jargon notice) are gone.

export default function UserDetails() {
  const { id = '' } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const toast = useToast()
  const readOnly = useReadOnly()
  const queryClient = useQueryClient()
  const siteNames = useSiteNames()
  const [dialog, setDialog] = React.useState<'edit' | 'access' | 'whatsapp' | 'status' | 'delete' | 'password' | null>(null)

  const query = useQuery<User>({ queryKey: ['user-details', id], queryFn: () => fetchUser(id), enabled: !!id })
  const memberships = useMemberships()
  const user = query.data
  usePageTitle(`${user?.full_name ?? 'Person'} · Team`)

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['user-details', id] })
    queryClient.invalidateQueries({ queryKey: ['users-list'] })
    queryClient.invalidateQueries({ queryKey: ['project-members-count'] })
  }
  const statusMutation = useMutation({
    mutationFn: (status: string) => updateUserStatus(id, status),
    onSuccess: (_, status) => {
      toast.success(status === 'active' ? 'Active again' : 'Deactivated', status === 'active' ? 'They can use Mesiri again.' : 'They can no longer use the dashboard or send updates.')
      setDialog(null)
      refresh()
    },
    onError: (err) => toast.error('Could not change', apiErrorMessage(err)),
  })
  const deleteMutation = useMutation({
    mutationFn: () => deleteUser(id),
    onSuccess: () => {
      toast.success('Deleted', `${user?.full_name ?? 'They'} are removed from the team.`)
      queryClient.invalidateQueries({ queryKey: ['users-list'] })
      navigate('/team')
    },
    onError: (err) => toast.error('Could not delete', apiErrorMessage(err)),
  })

  if (query.isLoading) {
    return (
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-4 sm:px-2" aria-busy="true" aria-label="Loading">
        <Skeleton className="h-4 w-32" />
        <Skeleton className="h-8 w-64" />
        <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_300px]">
          <Skeleton className="h-48 rounded-lg" />
          <Skeleton className="h-48 rounded-lg" />
        </div>
      </div>
    )
  }
  if (query.isError || !user) {
    return <PageError message="This person could not be loaded." onRetry={() => query.refetch()} back={{ to: '/team', label: 'Back to Team' }} />
  }

  const orgWide = isOrgWide(user)
  // What access is checked against (project_members); the access settings
  // only say which sites, when limited.
  const projectIds = memberships.byUser.get(user.id) ?? []
  const siteGrant = new Map((user.access_policy?.projects ?? []).map((g) => [g.projectId, g.siteAccess]))
  const active = user.status === 'active'

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-4 pb-8 sm:px-2">
      <DprHeader
        back={{ to: '/team', label: 'Team' }}
        crumb="Person"
        title={user.full_name}
        chip={!active ? <span className={cn(CHIP, 'bg-muted text-muted-foreground')}>{user.status === 'invited' ? 'Invited' : 'Deactivated'}</span> : undefined}
        date={roleLabel(user.role)}
        action={
          !readOnly && (
            <Button size="sm" className="gap-1.5 font-semibold" onClick={() => setDialog('edit')}>
              <Pencil className="size-3.5" /> Edit
            </Button>
          )
        }
      />

      {!user.whatsapp_number ? (
        <Callout
          tone="draft"
          icon={MessageSquareOff}
          action={
            !readOnly && (
              <Button size="sm" variant="outline" className="bg-background" onClick={() => setDialog('whatsapp')}>
                Add number
              </Button>
            )
          }
        >
          No WhatsApp number: they can't send updates from site.
        </Callout>
      ) : !orgWide && !memberships.loading && projectIds.length === 0 ? (
        <Callout
          tone="draft"
          icon={FolderLock}
          action={
            !readOnly && (
              <Button size="sm" variant="outline" className="bg-background" onClick={() => setDialog('access')}>
                Give access
              </Button>
            )
          }
        >
          No projects yet: what they send can't land on a site.
        </Callout>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_300px]">
        <div className="flex min-w-0 flex-col">
          <DprSection
            icon={FolderLock}
            title="Projects and sites"
            action={
              !readOnly &&
              user.role !== 'ADMIN' && (
                <Button size="sm" variant="outline" onClick={() => setDialog('access')}>
                  Change
                </Button>
              )
            }
          >
            {orgWide ? (
              <p className="text-sm text-muted-foreground">
                {user.role === 'ADMIN' ? 'Admins reach every project and site, including new ones.' : 'Every project and site, including new ones.'}
              </p>
            ) : memberships.loading ? (
              <Skeleton className="h-10 rounded-lg" />
            ) : projectIds.length === 0 ? (
              <p className="text-sm text-muted-foreground">None yet.</p>
            ) : (
              <ul className="divide-y rounded-lg border text-sm">
                {projectIds.map((pid) => {
                  const custom = siteGrant.get(pid)?.mode === 'custom_sites'
                  const ids = siteGrant.get(pid)?.siteIds ?? []
                  return (
                    <li key={pid} className="flex flex-wrap items-baseline justify-between gap-x-3 px-3 py-2">
                      <Link to={`/projects/${pid}`} className="font-medium hover:underline">
                        {memberships.names.get(pid) ?? 'A project'}
                      </Link>
                      <span className="text-muted-foreground">
                        {!custom ? 'All sites' : ids.length === 0 ? 'No sites' : ids.map((sid) => siteNames.get(sid)?.name ?? 'A site').join(', ')}
                      </span>
                    </li>
                  )
                })}
              </ul>
            )}
          </DprSection>

          <DprSection icon={MessageSquare} title="Messages on WhatsApp">
            <UserWhatsAppMessagesTab user={user} setActiveTab={() => undefined} setWhatsappOpen={(open) => setDialog(open ? 'whatsapp' : null)} />
          </DprSection>
        </div>

        <DprAside>
          <section className="flex flex-col gap-2">
            <h2 className="text-[15px] font-semibold">Details</h2>
            <dl className="grid grid-cols-[84px_1fr] gap-x-3 gap-y-1.5 text-sm">
              <dt className="text-muted-foreground">Role</dt>
              <dd>{roleLabel(user.role)}</dd>
              <dt className="text-muted-foreground">Email</dt>
              <dd className="min-w-0 break-all">{user.email || <span className="text-muted-foreground">Not set</span>}</dd>
              <dt className="text-muted-foreground">WhatsApp</dt>
              <dd className="flex items-center justify-between gap-2">
                <span className={cn('tabular-nums', !user.whatsapp_number && 'text-draft')}>
                  {user.whatsapp_number ? `+${user.whatsapp_number.replace(/^\+/, '')}` : 'Not added'}
                </span>
                {!readOnly && (
                  <button type="button" className="text-sm text-muted-foreground hover:text-foreground hover:underline" onClick={() => setDialog('whatsapp')}>
                    Change
                  </button>
                )}
              </dd>
              <dt className="text-muted-foreground">Status</dt>
              <dd>{active ? 'Active' : user.status === 'invited' ? 'Invited' : 'Deactivated'}</dd>
            </dl>
          </section>
          {!readOnly && (
            <section className="flex flex-col items-start gap-1 border-t pt-4">
              <Button variant="ghost" size="sm" className="gap-1.5" onClick={() => setDialog('password')}>
                <KeyRound className="size-3.5" /> Set a new password
              </Button>
              <Button variant="ghost" size="sm" className="gap-1.5" onClick={() => setDialog('status')}>
                {active ? <UserX className="size-3.5" /> : <UserCheck className="size-3.5" />}
                {active ? 'Deactivate' : 'Make active'}
              </Button>
              <Button variant="ghost" size="sm" className="gap-1.5 text-destructive hover:text-destructive" onClick={() => setDialog('delete')}>
                <Trash2 className="size-3.5" /> Delete
              </Button>
            </section>
          )}
        </DprAside>
      </div>

      <Dialog open={dialog === 'status' || dialog === 'delete'} onOpenChange={(open) => !open && setDialog(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="text-base font-semibold">
              {dialog === 'delete' ? `Delete ${user.full_name}?` : active ? `Deactivate ${user.full_name}?` : `Make ${user.full_name} active again?`}
            </DialogTitle>
            <DialogDescription>
              {dialog === 'delete'
                ? 'They are removed from the team for good. What they reported stays on the reports. To pause someone instead, deactivate them.'
                : active
                  ? 'They can no longer use the dashboard, and messages from their WhatsApp number are not taken as updates. You can make them active again later.'
                  : 'They can use the dashboard and send updates again.'}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialog(null)}>
              Cancel
            </Button>
            {dialog === 'delete' ? (
              <Button variant="destructive" disabled={deleteMutation.isPending} onClick={() => deleteMutation.mutate()}>
                {deleteMutation.isPending ? 'Deleting…' : 'Delete'}
              </Button>
            ) : (
              <Button variant={active ? 'destructive' : 'default'} disabled={statusMutation.isPending} onClick={() => statusMutation.mutate(active ? 'inactive' : 'active')}>
                {active ? 'Deactivate' : 'Make active'}
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <PasswordDialog user={user} open={dialog === 'password'} onClose={() => setDialog(null)} />
      <AddEditUserDialog open={dialog === 'edit'} onOpenChange={(open) => !open && setDialog(null)} user={user} onSuccess={refresh} />
      <AccessManagerDialog open={dialog === 'access'} onOpenChange={(open) => !open && setDialog(null)} user={user} onSuccess={refresh} />
      <WhatsAppManagerDialog open={dialog === 'whatsapp'} onOpenChange={(open) => !open && setDialog(null)} user={user} onSuccess={refresh} />
    </div>
  )
}

/** Set someone's password (same rules as before: 6+ characters, typed twice). */
function PasswordDialog({ user, open, onClose }: { user: User; open: boolean; onClose: () => void }) {
  const toast = useToast()
  const [password, setPassword] = React.useState('')
  const [again, setAgain] = React.useState('')
  const [error, setError] = React.useState('')
  const [saving, setSaving] = React.useState(false)

  const close = () => {
    setPassword('')
    setAgain('')
    setError('')
    onClose()
  }
  const save = async (e: React.FormEvent) => {
    e.preventDefault()
    if (password.length < 6) return setError('At least 6 characters.')
    if (password !== again) return setError("The two don't match.")
    setSaving(true)
    try {
      await updateUser(user.id, { password })
      toast.success('Password set', `${user.full_name} signs in with the new password.`)
      close()
    } catch (err) {
      setError(apiErrorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !o && close()}>
      <DialogContent className="sm:max-w-sm">
        <form onSubmit={save} className="flex flex-col gap-4">
          <DialogHeader>
            <DialogTitle className="text-base font-semibold">New password for {user.full_name}</DialogTitle>
            <DialogDescription>Tell them the new password yourself; it isn't sent to them.</DialogDescription>
          </DialogHeader>
          <div className="grid gap-1.5">
            <Label htmlFor="pw1">New password</Label>
            <Input id="pw1" type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="pw2">Type it again</Label>
            <Input id="pw2" type="password" autoComplete="new-password" value={again} onChange={(e) => setAgain(e.target.value)} />
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={close}>
              Cancel
            </Button>
            <Button type="submit" disabled={saving || !password}>
              {saving ? 'Saving…' : 'Set password'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
