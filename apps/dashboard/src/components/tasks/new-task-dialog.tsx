import * as React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link2 } from 'lucide-react'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useToast } from '@/components/ui/toast-notification'
import { fetchProjects } from '@/lib/projects'
import { apiErrorMessage } from '@/lib/logo-upload'
import { PRIORITY_LABEL, createTask, fetchTaskOptions, type TaskPrefill, type TaskPriority } from '@/lib/tasks'
import type { AppScope } from '@/lib/scope-types'

// TSK-02/03: give a task. The project and site come from the page's scope when it has one, or from what the task is
// made from (an issue, a schedule activity: `prefill`). Everything offered comes from the API's own list
// (GET /tasks/options), so the pickers never offer something the API would refuse. A BOQ line's progress is read
// from the work site records; nothing here types progress (D-T4).

function inDays(n: number): string {
  const d = new Date()
  d.setDate(d.getDate() + n)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

const NONE = 'none'

export function NewTaskDialog({ open, onOpenChange, scope, prefill }: {
  open: boolean
  onOpenChange: (open: boolean) => void
  scope: AppScope
  prefill?: TaskPrefill | null
}) {
  const queryClient = useQueryClient()
  const toast = useToast()
  const scopedProject = prefill?.project_id || (scope.mode === 'project' || scope.mode === 'site' ? scope.projectId : '')
  const scopedSite = prefill?.site_id || (scope.mode === 'site' ? scope.siteId : '')
  const prefillKey = JSON.stringify(prefill ?? null)
  const [projectId, setProjectId] = React.useState(scopedProject)
  const [siteId, setSiteId] = React.useState(scopedSite)
  const [title, setTitle] = React.useState('')
  const [who, setWho] = React.useState('')
  const [due, setDue] = React.useState('')
  const [priority, setPriority] = React.useState<TaskPriority>('normal')
  const [notes, setNotes] = React.useState('')
  const [placeId, setPlaceId] = React.useState('')
  const [lineId, setLineId] = React.useState('')
  const [expected, setExpected] = React.useState('')

  React.useEffect(() => {
    if (!open) return
    setProjectId(scopedProject); setSiteId(scopedSite)
    setTitle(prefill?.title ?? ''); setNotes(prefill?.notes ?? '')
    setWho(''); setDue(''); setPriority('normal'); setPlaceId(''); setLineId(''); setExpected('')
    // eslint-disable-next-line react-hooks/exhaustive-deps -- prefillKey stands for prefill (a new object each render)
  }, [open, scopedProject, scopedSite, prefillKey])

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
  const places = (options?.places ?? []).filter((p) => !siteId || !p.site_id || p.site_id === siteId)
  // From a schedule activity: its own BOQ lines first.
  const lines = [...(options?.lines ?? [])].sort((a, b) =>
    Number(b.work_package_id === prefill?.work_package_id) - Number(a.work_package_id === prefill?.work_package_id))
  const line = options?.lines.find((l) => l.id === lineId)

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
      place_id: placeId || null,
      planned_item_id: lineId || null,
      expected_quantity: lineId && Number(expected) > 0 ? expected : null,
      work_package_id: prefill?.work_package_id || null,
      site_issue_id: prefill?.site_issue_id || null,
    }),
    onSuccess: (t) => {
      queryClient.invalidateQueries({ queryKey: ['tasks'] })
      toast.success(`${t.ref} given${t.assigned_to ? ` to ${t.assigned_to}` : ''}`)
      onOpenChange(false)
    },
    onError: (err) => toast.error('Task not saved', apiErrorMessage(err)),
  })

  const ready = !!projectId && !!title.trim() && !save.isPending
  const showProject = !scopedProject
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[92vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader><DialogTitle>New task</DialogTitle></DialogHeader>
        {prefill?.from && (
          <p className="flex items-start gap-2 rounded-lg bg-muted/60 px-3 py-2 text-sm"><Link2 className="mt-0.5 size-4 shrink-0 text-muted-foreground" />{prefill.from}</p>
        )}
        <form id="new-task" className="flex flex-col gap-3" onSubmit={(e) => { e.preventDefault(); if (ready) save.mutate() }}>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="task-title">What to do</Label>
            <Input id="task-title" autoFocus value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} placeholder="Tie steel for grid B" />
          </div>
          {showProject && (
            <div className="flex flex-col gap-1.5">
              <Label>Project</Label>
              <Select value={projectId} onValueChange={(v) => { setProjectId(v); setSiteId(''); setWho(''); setPlaceId(''); setLineId('') }}>
                <SelectTrigger><SelectValue placeholder="Pick a project" /></SelectTrigger>
                <SelectContent>{projects.map((p) => <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>)}</SelectContent>
              </Select>
            </div>
          )}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div className="flex flex-col gap-1.5">
              <Label>For</Label>
              <Select value={who || NONE} onValueChange={(v) => setWho(v === NONE ? '' : v)} disabled={!options}>
                <SelectTrigger><SelectValue placeholder="Who does it" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value={NONE}>Nobody yet</SelectItem>
                  {options?.people.map((p) => <SelectItem key={p.id} value={`u:${p.id}`}>{p.name}</SelectItem>)}
                  {options?.subcontractors.map((s) => <SelectItem key={s.id} value={`v:${s.id}`}>{s.name} (subcontractor)</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            {!scopedSite && (
              <div className="flex flex-col gap-1.5">
                <Label>Site</Label>
                <Select value={siteId || NONE} onValueChange={(v) => { setSiteId(v === NONE ? '' : v); setPlaceId('') }} disabled={!options}>
                  <SelectTrigger><SelectValue placeholder="Any site" /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value={NONE}>Whole project</SelectItem>
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
            {places.length > 0 && (
              <div className="flex flex-col gap-1.5 sm:col-span-2">
                <Label>Where on site</Label>
                <Select value={placeId || NONE} onValueChange={(v) => setPlaceId(v === NONE ? '' : v)}>
                  <SelectTrigger><SelectValue placeholder="Anywhere" /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value={NONE}>Anywhere</SelectItem>
                    {places.map((p) => <SelectItem key={p.id} value={p.id}>{p.label}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
            )}
            {lines.length > 0 && (
              <div className="flex flex-col gap-1.5 sm:col-span-2">
                <Label>BOQ line</Label>
                <Select value={lineId || NONE} onValueChange={(v) => { setLineId(v === NONE ? '' : v); setExpected('') }}>
                  <SelectTrigger><SelectValue placeholder="Not on a BOQ line" /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value={NONE}>Not on a BOQ line</SelectItem>
                    {lines.map((l) => <SelectItem key={l.id} value={l.id}>{l.section ? `${l.section} › ` : ''}{l.work} ({l.unit})</SelectItem>)}
                  </SelectContent>
                </Select>
                {line && (
                  <div className="flex items-center gap-2">
                    <Input type="number" min="0" step="any" inputMode="decimal" className="w-32" value={expected} onChange={(e) => setExpected(e.target.value)} placeholder="How much" aria-label={`Quantity expected, in ${line.unit}`} />
                    <span className="text-sm text-muted-foreground">{line.unit} expected · progress comes from site's work updates</span>
                  </div>
                )}
              </div>
            )}
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
