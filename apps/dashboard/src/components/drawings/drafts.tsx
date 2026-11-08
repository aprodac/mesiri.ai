import * as React from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CalendarRange, Calculator, Plus, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useToast } from '@/components/ui/toast-notification'
import { addDraftBoq, addDraftSchedule, type DraftActivity, type DrawingReadWithDrafts } from '@/lib/drawings'
import { apiErrorMessage } from '@/lib/logo-upload'
import { fetchLifecycle } from '@/lib/schedule'

// DR-05 / DR-06: the drafts the drawing reader makes, edited here and then added to a project. Adding never
// changes what the project already has: an activity or BOQ line that is already there is skipped and said.

function todayIso(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function ProjectSelect({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const projects = useQuery({ queryKey: ['lifecycle'], queryFn: fetchLifecycle })
  return (
    <select aria-label="Project" className="h-9 min-w-48 rounded-md border bg-background px-2 text-sm" value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">Pick the project…</option>
      {projects.data?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
    </select>
  )
}

export function DraftSchedule({ read }: { read: DrawingReadWithDrafts }) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const [rows, setRows] = React.useState<DraftActivity[]>(read.draft_schedule)
  const [projectId, setProjectId] = React.useState('')
  const [start, setStart] = React.useState(todayIso())
  React.useEffect(() => setRows(read.draft_schedule), [read])
  const total = rows.reduce((s, r) => s + r.days, 0)
  const add = useMutation({
    mutationFn: () => addDraftSchedule(projectId, start, rows.filter((r) => r.name.trim())),
    onSuccess: (r) => {
      queryClient.invalidateQueries({ queryKey: ['schedule', projectId] })
      toast.success(`${r.added.length} activities added${r.skipped.length ? `; ${r.skipped.length} already there, left as they were` : ''}`)
    },
    onError: (e) => toast.error('Could not add the schedule', apiErrorMessage(e)),
  })
  return (
    <section className="flex flex-col gap-3 rounded-xl border p-4">
      <div>
        <h2 className="flex items-center gap-2 text-base font-semibold"><CalendarRange className="size-4" /> Draft schedule from the floors</h2>
        <p className="text-sm text-muted-foreground">
          {read.floors.length ? `${read.floors.join(', ')}: ` : ''}the usual order on site, with typical days. Change names and days; about {Math.round(total / 26)} months of work days in all.
        </p>
      </div>
      <ol className="grid gap-1.5 sm:grid-cols-2">
        {rows.map((r, i) => (
          <li key={i} className="flex items-center gap-2">
            <span className="w-6 text-right text-xs text-muted-foreground tabular-nums">{i + 1}</span>
            <Input aria-label="Activity" className="h-8 flex-1" value={r.name} onChange={(e) => setRows((x) => x.map((y, k) => (k === i ? { ...y, name: e.target.value } : y)))} />
            <Input aria-label="Days" type="number" min={0} max={365} className="h-8 w-16 text-right" value={r.days} onChange={(e) => setRows((x) => x.map((y, k) => (k === i ? { ...y, days: Math.max(0, Number(e.target.value) || 0) } : y)))} />
            <Button variant="ghost" size="icon" className="size-8" aria-label="Remove" onClick={() => setRows((x) => x.filter((_, k) => k !== i))}><Trash2 className="size-3.5" /></Button>
          </li>
        ))}
      </ol>
      <Button variant="outline" size="sm" className="w-fit gap-1.5" onClick={() => setRows((x) => [...x, { name: '', days: 5 }])}><Plus className="size-3.5" /> Add an activity</Button>
      <div className="flex flex-wrap items-end gap-2 border-t pt-3">
        <ProjectSelect value={projectId} onChange={setProjectId} />
        <div className="grid gap-1"><Label htmlFor="ds-start" className="text-xs">Work starts</Label><Input id="ds-start" type="date" className="h-9 w-40" value={start} onChange={(e) => setStart(e.target.value)} /></div>
        <Button disabled={!projectId || !start || add.isPending || rows.length === 0} onClick={() => add.mutate()}>{add.isPending ? 'Adding…' : 'Add to the schedule'}</Button>
        {add.isSuccess && projectId && <Button variant="ghost" asChild><Link to={`/planning/schedule?project=${projectId}`}>Open the schedule</Link></Button>}
      </div>
      <p className="text-xs text-muted-foreground">Activities already in the project's schedule are left as they are.</p>
    </section>
  )
}

export function DraftBoq({ read }: { read: DrawingReadWithDrafts }) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const [sections, setSections] = React.useState(read.draft_boq.sections)
  const [projectId, setProjectId] = React.useState('')
  React.useEffect(() => setSections(read.draft_boq.sections), [read])
  const setQty = (s: number, l: number, q: number) =>
    setSections((x) => x.map((sec, i) => (i !== s ? sec : { ...sec, lines: sec.lines.map((ln, k) => (k === l ? { ...ln, quantity: q } : ln)) })))
  const add = useMutation({
    mutationFn: () => addDraftBoq(projectId, sections.map((s) => ({ name: s.name, lines: s.lines.filter((l) => l.quantity > 0).map(({ work, unit, quantity }) => ({ work, unit, quantity })) })).filter((s) => s.lines.length)),
    onSuccess: (r) => {
      queryClient.invalidateQueries({ queryKey: ['boq', projectId] })
      toast.success(`${r.added} BOQ lines added${r.skipped ? `; ${r.skipped} already there, left as they were` : ''}`)
    },
    onError: (e) => toast.error('Could not add to the BOQ', apiErrorMessage(e)),
  })
  if (!sections.length) return null
  return (
    <section className="flex flex-col gap-3 rounded-xl border p-4">
      <div>
        <h2 className="flex items-center gap-2 text-base font-semibold"><Calculator className="size-4" /> Draft BOQ quantities from the rooms</h2>
        <p className="text-sm text-muted-foreground">Worked out from the room sizes on each plan; wall height {read.draft_boq.clear_height_m.toFixed(2)} m ({read.draft_boq.height_note}). Check them, then add them without rates.</p>
      </div>
      {sections.map((s, si) => (
        <div key={s.name} className="overflow-x-auto rounded-lg border [contain:inline-size]">
          <p className="border-b bg-muted/40 px-3 py-1.5 text-sm font-medium">{s.name} <span className="text-xs font-normal text-muted-foreground">page {s.page}</span></p>
          {s.warning && <p className="border-b bg-draft-soft px-3 py-1.5 text-xs text-draft">{s.warning}</p>}
          <table className="w-full min-w-[560px] text-sm">
            <tbody className="divide-y">
              {s.lines.map((ln, li) => (
                <tr key={ln.work}>
                  <td className="px-3 py-1.5">{ln.work}<span className="block text-xs text-muted-foreground">{ln.basis}</span></td>
                  <td className="w-36 px-2 py-1.5 text-right">
                    <span className="inline-flex items-center gap-1">
                      <Input aria-label={`${ln.work} quantity`} type="number" min={0} step="any" className="h-8 w-24 text-right" value={ln.quantity} onChange={(e) => setQty(si, li, Number(e.target.value) || 0)} />
                      <span className="w-8 text-left text-xs text-muted-foreground">{ln.unit}</span>
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
      <div className="flex flex-wrap items-end gap-2 border-t pt-3">
        <ProjectSelect value={projectId} onChange={setProjectId} />
        <Button disabled={!projectId || add.isPending} onClick={() => add.mutate()}>{add.isPending ? 'Adding…' : 'Add to the BOQ'}</Button>
        {add.isSuccess && projectId && <Button variant="ghost" asChild><Link to={`/projects/${projectId}/boq`}>Open the BOQ</Link></Button>}
      </div>
      <p className="text-xs text-muted-foreground">One section per floor (an existing section with the same name is used). Lines already in it are left as they are. Add your rates on the BOQ page.</p>
    </section>
  )
}
