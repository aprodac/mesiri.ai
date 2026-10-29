import * as React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, Plus, Trash2, UserPlus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useAuth } from '@/lib/AuthContext'
import { fetchUsers } from '@/lib/api'
import {
  addRecipient,
  fetchRecipients,
  recordRecipientConsent,
  removeRecipient,
  type AddRecipientPayload,
  type ReportRecipient,
} from '@/lib/projects'
import { apiErrorMessage as apiError } from '@/lib/logo-upload'

// Who gets this project's DPR on WhatsApp (tracker WEB-08, API BE-15).
// Team members receive it by default; outside contacts (the client, a
// consultant) only once their opt-in is recorded -- Meta requires it.
// WEB-28: a flat section of the project page, not a card.

const MANAGER_ROLES = new Set(['ADMIN', 'PROJECT_MANAGER'])

const ROLE_LABELS: Record<string, string> = {
  ADMIN: 'Admin',
  PROJECT_MANAGER: 'Project manager',
  SITE_ENGINEER: 'Site engineer',
  FINANCE: 'Finance',
}

function StatusPill({ r }: { r: ReportRecipient }) {
  let text: string
  let tone: string
  if (r.will_receive) {
    text = 'Will receive'
    tone = 'bg-success-soft text-success'
  } else if (!r.phone) {
    text = 'No WhatsApp number'
    tone = 'bg-draft-soft text-draft'
  } else if (r.opt_in === 'opted_out') {
    text = 'Opted out'
    tone = 'bg-destructive/10 text-destructive'
  } else {
    text = 'Waiting for opt-in'
    tone = 'bg-draft-soft text-draft'
  }
  return <span className={`whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-semibold ${tone}`}>{text}</span>
}

export function ProjectRecipientsTab({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient()
  const { me } = useAuth()
  const canEdit = MANAGER_ROLES.has((me?.role || '').toUpperCase())
  const key = ['project-recipients', projectId]

  const { data, isLoading, isError, error } = useQuery({
    queryKey: key,
    queryFn: () => fetchRecipients(projectId),
  })
  const { data: users = [] } = useQuery({
    queryKey: ['users'],
    queryFn: fetchUsers,
    enabled: canEdit,
  })

  const [mode, setMode] = React.useState<'member' | 'contact' | null>(null)
  const [memberId, setMemberId] = React.useState('')
  const [contact, setContact] = React.useState({ name: '', phone: '', label: '', optedIn: false, note: '' })
  const [actionError, setActionError] = React.useState<string | null>(null)

  const openForm = (next: 'member' | 'contact' | null) => {
    setActionError(null)
    setMode(next)
  }
  const refresh = () => queryClient.invalidateQueries({ queryKey: key })
  const onError = (err: unknown) => setActionError(apiError(err))

  const add = useMutation({
    mutationFn: (payload: AddRecipientPayload) => addRecipient(projectId, payload),
    onMutate: () => setActionError(null),
    onSuccess: () => {
      setMode(null)
      setMemberId('')
      setContact({ name: '', phone: '', label: '', optedIn: false, note: '' })
      refresh()
    },
    onError,
  })
  const remove = useMutation({
    mutationFn: (id: string) => removeRecipient(projectId, id),
    onMutate: () => setActionError(null),
    onSuccess: refresh,
    onError,
  })
  const consent = useMutation({
    mutationFn: (v: { id: string; state: 'opt-in' | 'opt-out' }) =>
      recordRecipientConsent(projectId, v.id, v.state),
    onMutate: () => setActionError(null),
    onSuccess: refresh,
    onError,
  })

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 py-2 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" /> Loading recipients…
      </div>
    )
  }
  if (isError || !data) {
    return <p className="py-2 text-sm text-destructive">Could not load who gets the DPR: {apiError(error)}</p>
  }

  const listedUserIds = new Set(data.recipients.map((r) => r.user_id).filter(Boolean))
  const pickable = users.filter((u) => u.status === 'active' && !listedUserIds.has(u.id))
  const busy = add.isPending || remove.isPending || consent.isPending

  return (
    <div className="flex flex-col gap-3 text-sm">
      {canEdit && mode === null && (
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" size="sm" className="gap-1.5" onClick={() => openForm('member')}>
            <UserPlus className="size-3.5" /> Add team member
          </Button>
          <Button variant="outline" size="sm" className="gap-1.5" onClick={() => openForm('contact')}>
            <Plus className="size-3.5" /> Add outside contact
          </Button>
        </div>
      )}
      <div className="flex flex-col gap-3">
          {data.using_defaults && (
            <p className="text-muted-foreground">
              No list set yet, so the project's admins and project managers get the DPR. Adding anyone here
              replaces that.
            </p>
          )}

          {mode === 'member' && (
            <form
              className="flex flex-wrap items-end gap-2 rounded-lg border p-3"
              onSubmit={(e) => {
                e.preventDefault()
                if (memberId) add.mutate({ user_id: memberId })
              }}
            >
              <label className="grid gap-1 min-w-56">
                <span className="text-xs font-medium text-muted-foreground">Team member</span>
                <select
                  value={memberId}
                  onChange={(e) => setMemberId(e.target.value)}
                  className="h-9 rounded-md border border-input bg-background px-2 text-sm"
                >
                  <option value="">Choose…</option>
                  {pickable.map((u) => (
                    <option key={u.id} value={u.id}>
                      {u.full_name} — {ROLE_LABELS[u.role] ?? u.role}
                      {u.whatsapp_number ? '' : ' (no WhatsApp number)'}
                    </option>
                  ))}
                </select>
              </label>
              <Button type="submit" size="sm" className="h-9" disabled={!memberId || busy}>
                Add
              </Button>
              <Button type="button" variant="ghost" size="sm" className="h-9" onClick={() => openForm(null)}>
                Cancel
              </Button>
            </form>
          )}

          {mode === 'contact' && (
            <form
              className="grid gap-3 rounded-lg border p-3"
              onSubmit={(e) => {
                e.preventDefault()
                add.mutate({
                  name: contact.name,
                  phone: contact.phone,
                  label: contact.label || undefined,
                  opted_in: contact.optedIn,
                  opt_in_note: contact.optedIn ? contact.note || undefined : undefined,
                })
              }}
            >
              <div className="grid gap-3 sm:grid-cols-3">
                <label className="grid gap-1">
                  <span className="text-xs font-medium text-muted-foreground">Name</span>
                  <Input
                    required
                    value={contact.name}
                    onChange={(e) => setContact({ ...contact, name: e.target.value })}
                    className="h-9"
                  />
                </label>
                <label className="grid gap-1">
                  <span className="text-xs font-medium text-muted-foreground">WhatsApp number</span>
                  <Input
                    required
                    placeholder="+91 98765 43210"
                    value={contact.phone}
                    onChange={(e) => setContact({ ...contact, phone: e.target.value })}
                    className="h-9"
                  />
                </label>
                <label className="grid gap-1">
                  <span className="text-xs font-medium text-muted-foreground">Role (optional)</span>
                  <Input
                    placeholder="Client, consultant…"
                    value={contact.label}
                    onChange={(e) => setContact({ ...contact, label: e.target.value })}
                    className="h-9"
                  />
                </label>
              </div>
              <label className="flex items-start gap-2">
                <input
                  type="checkbox"
                  className="mt-0.5"
                  checked={contact.optedIn}
                  onChange={(e) => setContact({ ...contact, optedIn: e.target.checked })}
                />
                <span>
                  They have agreed to receive the DPR on WhatsApp.
                  <span className="block text-muted-foreground">
                    Without this they are not sent anything until they agree.
                  </span>
                </span>
              </label>
              {contact.optedIn && (
                <Input
                  placeholder="How they agreed, e.g. clause 12 of the contract"
                  value={contact.note}
                  onChange={(e) => setContact({ ...contact, note: e.target.value })}
                  className="h-9"
                />
              )}
              <div className="flex gap-2">
                <Button type="submit" size="sm" className="h-9" disabled={busy}>
                  Add contact
                </Button>
                <Button type="button" variant="ghost" size="sm" className="h-9" onClick={() => openForm(null)}>
                  Cancel
                </Button>
              </div>
            </form>
          )}

          {actionError && <p className="text-destructive">{actionError}</p>}

          {data.recipients.length > 0 && (
            <div className="divide-y rounded-lg border">
              {data.recipients.map((r) => (
                <div key={r.id} className="flex flex-wrap items-center gap-3 px-3 py-2.5">
                  <div className="min-w-0 flex-1">
                    <div className="font-medium text-foreground">
                      {r.name || 'Unnamed'}
                      <span className="ml-2 text-muted-foreground font-normal">
                        {r.kind === 'user' ? ROLE_LABELS[r.role ?? ''] ?? 'Team member' : r.label || 'Outside contact'}
                      </span>
                    </div>
                    <div className="text-xs text-muted-foreground tabular-nums">{r.phone || 'No WhatsApp number'}</div>
                  </div>
                  <StatusPill r={r} />
                  {canEdit && (
                    <div className="flex gap-1">
                      {r.kind === 'contact' && r.opt_in !== 'opted_in' && (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-8"
                          disabled={busy}
                          onClick={() => consent.mutate({ id: r.id, state: 'opt-in' })}
                        >
                          Mark agreed
                        </Button>
                      )}
                      {r.phone && r.opt_in !== 'opted_out' && (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-8"
                          disabled={busy}
                          onClick={() => consent.mutate({ id: r.id, state: 'opt-out' })}
                        >
                          Stop sending
                        </Button>
                      )}
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-8 text-destructive"
                        aria-label={`Remove ${r.name ?? 'recipient'}`}
                        disabled={busy}
                        onClick={() => remove.mutate(r.id)}
                      >
                        <Trash2 className="size-3.5" />
                      </Button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          {!canEdit && (
            <p className="text-muted-foreground">Only admins and project managers can change this list.</p>
          )}
      </div>
    </div>
  )
}
