import * as React from 'react'
import { useQuery } from '@tanstack/react-query'
import { BellRing, UserRound } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useToast } from '@/components/ui/toast-notification'
import type { SiteIssueItem } from '@/lib/api'
import { remindIssueOwner, setIssueOwner } from '@/lib/issues'
import { fetchProjectMembers } from '@/lib/projects'
import { fetchUsers } from '@/lib/api'
import { isOrgWide } from '@/lib/team'
import { errorDetail, localIsoDate } from '@/lib/site-day'
import { cn } from '@/lib/utils'

// GM-06: who is on an issue and by when. A chip on the issue: the person and the date (red once the date has passed),
// or "No one on it"; tapping it puts someone on it (they are told on WhatsApp). "Remind" sends them a reminder, once a day.

function shortDay(iso: string): string {
  return new Date(iso + 'T00:00:00').toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short' })
}

export function IssueOwner({ issue, readOnly, onChanged }: { issue: SiteIssueItem; readOnly?: boolean; onChanged: () => void }) {
  const toast = useToast()
  const [open, setOpen] = React.useState(false)
  const [busy, setBusy] = React.useState(false)
  const today = localIsoDate(new Date())
  const overdue = !!issue.due_on && issue.due_on < today
  const name = issue.assigned_user_name

  const remind = async () => {
    setBusy(true)
    try {
      const r = await remindIssueOwner(issue.id)
      toast.success(r.sent ? 'Reminded' : 'Already reminded today', r.message)
    } catch (e) {
      toast.error('Not sent', errorDetail(e) ?? 'Try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <button type="button" disabled={readOnly} onClick={() => setOpen(true)}
        className={cn('inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium',
          !name ? 'border border-dashed text-muted-foreground hover:text-foreground'
            : overdue ? 'bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-200' : 'bg-muted text-foreground/80')}
        title={name ? 'Change who is on it' : 'Put someone on it'}>
        <UserRound className="size-3" />
        {name ? `${name}${issue.due_on ? ` · ${overdue ? 'was due' : 'by'} ${shortDay(issue.due_on)}` : ''}` : 'No one on it'}
      </button>
      {name && !readOnly && (
        <Button variant="ghost" size="sm" className="h-7 gap-1 px-2 text-xs" disabled={busy} onClick={remind} title={`Remind ${name} on WhatsApp`}>
          <BellRing className="size-3" /> Remind
        </Button>
      )}
      {open && <OwnerDialog issue={issue} onClose={() => setOpen(false)} onSaved={() => { setOpen(false); onChanged() }} />}
    </>
  )
}

function OwnerDialog({ issue, onClose, onSaved }: { issue: SiteIssueItem; onClose: () => void; onSaved: () => void }) {
  const toast = useToast()
  const members = useQuery({ queryKey: ['project-members', issue.project_id], queryFn: () => fetchProjectMembers(issue.project_id) })
  // Company-wide people (owner, admins, all-projects) are valid too; the team list answers admins only, so it is optional.
  const team = useQuery({ queryKey: ['users'], queryFn: fetchUsers, retry: false })
  const people = React.useMemo(() => {
    const out = new Map<string, string>()
    for (const m of members.data ?? []) if (!m.status || m.status === 'active') out.set(m.userId, `${m.fullName ?? m.email ?? 'Team member'} · ${m.role.toLowerCase().replace(/_/g, ' ')}`)
    for (const u of team.data ?? []) if (u.status === 'active' && isOrgWide(u) && !out.has(u.id)) out.set(u.id, `${u.full_name} · ${u.role.toLowerCase().replace(/_/g, ' ')}`)
    return [...out.entries()].sort((a, b) => a[1].localeCompare(b[1]))
  }, [members.data, team.data])
  const [who, setWho] = React.useState(issue.assigned_user_id ?? '')
  const [due, setDue] = React.useState(issue.due_on ?? '')
  const [saving, setSaving] = React.useState(false)
  const today = localIsoDate(new Date())

  const save = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaving(true)
    try {
      const after = await setIssueOwner(issue.id, { assigned_user_id: who || null, due_on: due || null })
      toast.success(after.assigned_user_name ? `${after.assigned_user_name} is on it` : 'No one on it now',
        after.assigned_user_name ? 'They are told on WhatsApp.' : undefined)
      onSaved()
    } catch (err) {
      toast.error('Not saved', errorDetail(err) ?? 'Try again.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-md">
        <form onSubmit={save} className="flex flex-col gap-4">
          <DialogHeader>
            <DialogTitle>Who is on it?</DialogTitle>
            <DialogDescription>{issue.narrative || issue.issue_type.replace(/_/g, ' ').toLowerCase()}</DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor={`owner-${issue.id}`}>Person</Label>
            <select id={`owner-${issue.id}`} value={who} onChange={(e) => setWho(e.target.value)}
              className="h-9 rounded-md border bg-background px-2 text-sm">
              <option value="">No one</option>
              {people.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
            </select>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor={`due-${issue.id}`}>Sorted by (optional)</Label>
            <Input id={`due-${issue.id}`} type="date" min={today} value={due} onChange={(e) => setDue(e.target.value)} />
          </div>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
            <Button type="submit" disabled={saving}>Save</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
