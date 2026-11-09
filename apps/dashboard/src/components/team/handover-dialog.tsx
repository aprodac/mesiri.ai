import * as React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowRight } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { useToast } from '@/components/ui/toast-notification'
import { fetchUsers } from '@/lib/api'
import { handOver, type Handover } from '@/lib/admin'
import { apiErrorMessage } from '@/lib/logo-upload'

// ADM-03: hand a person's open work to someone else (leaving, changing job). Pick the person, see what moves and
// what stays (the new person is not on that project), then hand over. Tasks move through the tasks module's own
// reassign, so each task's history says so. Deactivating stays its own action on this page.

export function HandoverDialog({ userId, name, open, onClose }: { userId: string; name: string; open: boolean; onClose: () => void }) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const [to, setTo] = React.useState('')
  const people = useQuery({ queryKey: ['users-list'], queryFn: fetchUsers, enabled: open })
  const others = (people.data ?? []).filter((u) => u.id !== userId && u.status === 'active')
  const preview = useQuery({
    queryKey: ['handover-preview', userId, to],
    queryFn: () => handOver(userId, to, true),
    enabled: open && !!to,
    retry: false,
  })
  const move = useMutation({
    mutationFn: () => handOver(userId, to, false),
    onSuccess: (r) => {
      const m = r.moved ?? { tasks: 0, activities: 0 }
      toast.success(`Handed over to ${r.to.name}`, `${plural(m.tasks, 'task')}, ${plural(m.activities, 'schedule activity', 'schedule activities')}.`)
      queryClient.invalidateQueries({ queryKey: ['tasks'] })
      queryClient.invalidateQueries({ queryKey: ['approvals'] })
      setTo('')
      onClose()
    },
    onError: (e) => toast.error('Could not hand over', apiErrorMessage(e)),
  })
  const p = preview.data
  const nothing = p && p.tasks.length === 0 && p.activities.length === 0

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) { setTo(''); onClose() } }}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Hand over {name}'s open work</DialogTitle>
          <DialogDescription>Their open tasks and schedule activities go to the person you pick.</DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="handover-to">Give it to</Label>
          <Select value={to} onValueChange={setTo}>
            <SelectTrigger id="handover-to"><SelectValue placeholder={people.isLoading ? 'Loading…' : 'Pick a person'} /></SelectTrigger>
            <SelectContent>
              {others.map((u) => <SelectItem key={u.id} value={u.id}>{u.full_name}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
        {to && (preview.isError ? (
          <p className="text-sm text-destructive">{apiErrorMessage(preview.error)}</p>
        ) : !p ? (
          <Skeleton className="h-24 w-full" />
        ) : (
          <Summary p={p} nothing={!!nothing} />
        ))}
        <DialogFooter>
          <Button variant="outline" onClick={() => { setTo(''); onClose() }}>Cancel</Button>
          <Button disabled={!p || !!nothing || move.isPending} onClick={() => move.mutate()} className="gap-1.5">
            Hand over <ArrowRight className="size-4" />
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function Summary({ p, nothing }: { p: Handover; nothing: boolean }) {
  if (nothing && p.left.tasks.length === 0 && p.left.activities.length === 0) {
    return <p className="rounded-lg border border-dashed p-3 text-sm text-muted-foreground">{p.from.name} has no open tasks or schedule activities.</p>
  }
  return (
    <div className="flex max-h-72 flex-col gap-3 overflow-y-auto text-sm">
      {p.tasks.length + p.activities.length > 0 && (
        <section>
          <h3 className="mb-1 text-xs font-semibold text-muted-foreground">Goes to {p.to.name}</h3>
          <ul className="divide-y rounded-lg border">
            {p.tasks.map((t) => <li key={t.id} className="px-3 py-2"><span className="font-medium">{t.ref}</span> {t.title} <span className="text-xs text-muted-foreground">· {t.project_name}</span></li>)}
            {p.activities.map((a) => <li key={a.id} className="px-3 py-2">{a.name} <span className="text-xs text-muted-foreground">· schedule · {a.project_name}</span></li>)}
          </ul>
        </section>
      )}
      {p.left.tasks.length + p.left.activities.length > 0 && (
        <section>
          <h3 className="mb-1 text-xs font-semibold text-amber-800 dark:text-amber-300">Stays with {p.from.name}: {p.to.name} is not on these projects</h3>
          <ul className="divide-y rounded-lg border border-amber-200 dark:border-amber-900">
            {p.left.tasks.map((t) => <li key={t.id} className="px-3 py-2"><span className="font-medium">{t.ref}</span> {t.title} <span className="text-xs text-muted-foreground">· {t.project_name}</span></li>)}
            {p.left.activities.map((a) => <li key={a.id} className="px-3 py-2">{a.name} <span className="text-xs text-muted-foreground">· {a.project_name}</span></li>)}
          </ul>
        </section>
      )}
    </div>
  )
}

function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`
}
