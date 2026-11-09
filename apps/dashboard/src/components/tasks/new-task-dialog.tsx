import * as React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useToast } from '@/components/ui/toast-notification'
import { fetchProjects } from '@/lib/projects'
import { apiErrorMessage } from '@/lib/logo-upload'
import { PRIORITY_LABEL, createTask, fetchTaskOptions, type TaskPriority } from '@/lib/tasks'
import type { AppScope } from '@/lib/scope-types'

// TSK-02: give a task. The project and site come from the page's scope when it has one; the people offered are the
// API's own list (GET /tasks/options), so the picker never offers someone the API would refuse.

function inDays(n: number): string {
  const d = new Date()
  d.setDate(d.getDate() + n)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

export function NewTaskDialog({ open, onOpenChange, scope }: { open: boolean; onOpenChange: (open: boolean) => void; scope: AppScope }) {
  const queryClient = useQueryClient()
  const toast = useToast()
  const scopedProject = scope.mode === 'project' || scope.mode === 'site' ? scope.projectId : ''
  const scopedSite = scope.mode === 'site' ? scope.siteId : ''
  const [projectId, setProjectId] = React.useState(scopedProject)
  const [siteId, setSiteId] = React.useState(scopedSite)
  const [title, setTitle] = React.useState('')
  const [who, setWho] = React.useState('')
  const [due, setDue] = React.useState('')
  const [priority, setPriority] = React.useState<TaskPriority>('normal')
  const [notes, setNotes] = React.useState('')

  React.useEffect(() => {
    if (!open) return
    setProjectId(scopedProject); setSiteId(scopedSite)
    setTitle(''); setWho(''); setDue(''); setPriority('normal'); setNotes('')
  }, [open, scopedProject, scopedSite])

  const { data: projects = [] } = useQuery({ queryKey: ['scope-projects'], queryFn: fetchProjects, enabled: open, staleTime: 60_000 })
  React.useEffect(() => {
    if (open && !projectId && projects.length === 1) setProjectId(projects[0].id)
  }, [open, projectId, projects])
  const { data: options } = useQuery({
    queryKey: ['tasks', 'options', projectId],
    queryFn: () => fetchTaskOptions(projectId),
    enabled: open && !!projectId,
    staleTime: 60_000,
  })

  const save = useMutation({
    mutationFn: () => createTask({
      project_id: projectId,
      title: title.trim(),
      notes: notes.trim() || null,
      site_id: siteId || null,
      due_date: due || null,
      priority,
      assignee_user_id: who.startsWith('u:') ? who.slice(2) : null,
      assignee_vendor_id: who.startsWith('v:') ? who.slice(2) : null,
    }),
    onSuccess: (t) => {
      queryClient.invalidateQueries({ queryKey: ['tasks'] })
      toast.success(`${t.ref} given${t.assigned_to ? ` to ${t.assigned_to}` : ''}`)
      onOpenChange(false)
    },
    onError: (err) => toast.error('Task not saved', apiErrorMessage(err)),
  })

  const ready = !!projectId && !!title.trim() && !save.isPending
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader><DialogTitle>New task</DialogTitle></DialogHeader>
        <form id="new-task" className="flex flex-col gap-3" onSubmit={(e) => { e.preventDefault(); if (ready) save.mutate() }}>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="task-title">What to do</Label>
            <Input id="task-title" autoFocus value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} placeholder="Tie steel for grid B" />
          </div>
          {!scopedProject && (
            <div className="flex flex-col gap-1.5">
              <Label>Project</Label>
              <Select value={projectId} onValueChange={(v) => { setProjectId(v); setSiteId(''); setWho('') }}>
                <SelectTrigger><SelectValue placeholder="Pick a project" /></SelectTrigger>
                <SelectContent>{projects.map((p) => <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>)}</SelectContent>
              </Select>
            </div>
          )}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div className="flex flex-col gap-1.5">
              <Label>For</Label>
              <Select value={who || 'none'} onValueChange={(v) => setWho(v === 'none' ? '' : v)} disabled={!options}>
                <SelectTrigger><SelectValue placeholder="Who does it" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">Nobody yet</SelectItem>
                  {options?.people.map((p) => <SelectItem key={p.id} value={`u:${p.id}`}>{p.name}</SelectItem>)}
                  {options?.subcontractors.map((s) => <SelectItem key={s.id} value={`v:${s.id}`}>{s.name} (subcontractor)</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            {!scopedSite && (
              <div className="flex flex-col gap-1.5">
                <Label>Site</Label>
                <Select value={siteId || 'none'} onValueChange={(v) => setSiteId(v === 'none' ? '' : v)} disabled={!options}>
                  <SelectTrigger><SelectValue placeholder="Any site" /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="none">Whole project</SelectItem>
                    {options?.sites.map((s) => <SelectItem key={s.id} value={s.id}>{s.name}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
            )}
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="task-due">Due</Label>
              <Input id="task-due" type="date" value={due} onChange={(e) => setDue(e.target.value)} />
              <div className="flex gap-1.5 text-xs">
                {[['Today', 0], ['Tomorrow', 1], ['In a week', 7]].map(([label, n]) => (
                  <button key={label} type="button" className="rounded-md border px-1.5 py-0.5 hover:bg-muted" onClick={() => setDue(inDays(n as number))}>{label}</button>
                ))}
              </div>
            </div>
            <div className="flex flex-col gap-1.5">
              <Label>Priority</Label>
              <Select value={priority} onValueChange={(v) => setPriority(v as TaskPriority)}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>{(['normal', 'high', 'urgent'] as TaskPriority[]).map((p) => <SelectItem key={p} value={p}>{PRIORITY_LABEL[p]}</SelectItem>)}</SelectContent>
              </Select>
            </div>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="task-notes">Notes</Label>
            <textarea id="task-notes" value={notes} maxLength={2000} onChange={(e) => setNotes(e.target.value)} rows={3}
              placeholder="Use 12 mm bars; check cover blocks before calling for the pour"
              className="rounded-md border bg-transparent px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring" />
          </div>
        </form>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button type="submit" form="new-task" disabled={!ready}>{save.isPending ? 'Saving…' : 'Give task'}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
