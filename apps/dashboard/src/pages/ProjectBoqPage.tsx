import * as React from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { BookOpen, Calculator, CalendarRange, ClipboardCheck, FileSpreadsheet, MoreHorizontal, Pencil, Plus, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { useToast } from '@/components/ui/toast-notification'
import { Callout, DprHeader, DprSection, PageError } from '@/components/dpr-page'
import { useAuth } from '@/lib/AuthContext'
import { fetchProject, type Project } from '@/lib/projects'
import { BoqImportDialog } from '@/components/schedule/boq-import-dialog'
import {
  createLine,
  createSection,
  deleteLine,
  deleteSection,
  fetchBoq,
  fetchBoqWork,
  formatQuantity,
  formatRupees,
  maySeeBoq,
  putWorkOnLine,
  updateLine,
  updateSection,
  type Boq,
  type BoqLine,
  type BoqSection,
  type BoqTotals,
  type BoqWork,
  type LineInput,
} from '@/lib/boq'
import { apiErrorMessage } from '@/lib/logo-upload'
import { usePageTitle } from '@/lib/page-title'
import { useReadOnly } from '@/lib/trial'
import { cn } from '@/lib/utils'

// CC-02: a project's Bill of Quantities. Every work item with its quantity, what the client
// pays per unit, and what it should cost us per unit. CC-04: the work done on each line (site
// work updates put on it, work-order measurements) and the budget that work earned. Later items
// (CC-05..07) put the money spent against it, to show green or red each day.

const NUM = 'text-right tabular-nums'

function marginClass(value: string | null): string {
  if (value === null) return 'text-muted-foreground'
  return Number(value) < 0 ? 'text-destructive font-semibold' : 'text-success font-semibold'
}

function TotalsStrip({ totals }: { totals: BoqTotals }) {
  const missing = [
    totals.lines_without_client_rate > 0 && `${totals.lines_without_client_rate} without a client rate`,
    totals.lines_without_budget_rate > 0 && `${totals.lines_without_budget_rate} without a budget rate`,
  ].filter(Boolean)
  const tiles = [
    { label: 'Contract value', hint: 'What the client pays', value: formatRupees(totals.contract_value), cls: '' },
    { label: 'Budget cost', hint: 'What it should cost us', value: formatRupees(totals.budget_cost), cls: '' },
    { label: 'Margin', hint: 'Contract value − budget cost', value: formatRupees(totals.margin), cls: marginClass(totals.margin) },
    ...(totals.earned !== undefined
      ? [{ label: 'Earned so far', hint: 'Budget earned by the work done', value: formatRupees(totals.earned), cls: '' }]
      : []),
  ]
  return (
    <div className="flex flex-col gap-2">
      <div className={cn('grid gap-3', tiles.length > 3 ? 'sm:grid-cols-2 xl:grid-cols-4' : 'sm:grid-cols-3')}>
        {tiles.map((t) => (
          <div key={t.label} className="rounded-lg border px-4 py-3">
            <p className="text-xs text-muted-foreground">{t.label}</p>
            <p className={cn('text-xl tabular-nums', t.cls || 'font-semibold')}>{t.value}</p>
            <p className="text-xs text-muted-foreground">{t.hint}</p>
          </div>
        ))}
      </div>
      {missing.length > 0 && (
        <p className="text-xs text-muted-foreground">
          {totals.line_count} lines · {missing.join(' · ')}. The margin shows once every line has both rates.
        </p>
      )}
    </div>
  )
}

type LineDialogState = { section: BoqSection; line: BoqLine | null } | null

const EMPTY_LINE: LineInput = {
  work: '', unit: '', planned_quantity: '', boq_code: '', client_rate: '', labour_rate: '', material_rate: '', subcontract_rate: '', revision_reason: '',
}

function LineDialog({
  state,
  onClose,
  onSave,
  saving,
}: {
  state: LineDialogState
  onClose: () => void
  onSave: (input: LineInput) => void
  saving: boolean
}) {
  const [form, setForm] = React.useState<LineInput>(EMPTY_LINE)
  React.useEffect(() => {
    const l = state?.line
    setForm(
      l
        ? {
            work: l.work, unit: l.unit, planned_quantity: String(Number(l.planned_quantity)), boq_code: l.boq_code ?? '',
            client_rate: l.client_rate ?? '', labour_rate: l.labour_rate ?? '', material_rate: l.material_rate ?? '',
            subcontract_rate: l.subcontract_rate ?? '', revision_reason: '',
          }
        : EMPTY_LINE,
    )
  }, [state])
  const set = (k: keyof LineInput) => (e: React.ChangeEvent<HTMLInputElement>) => setForm((f) => ({ ...f, [k]: e.target.value }))
  const qtyChanged = !!state?.line && Number(form.planned_quantity) !== Number(state.line.planned_quantity)
  const budget = ['labour_rate', 'material_rate', 'subcontract_rate'].reduce((s, k) => s + (Number(form[k as keyof LineInput]) || 0), 0)
  const qty = Number(form.planned_quantity) || 0

  const field = (id: keyof LineInput, label: string, props: React.InputHTMLAttributes<HTMLInputElement> = {}) => (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={`boq-${id}`}>{label}</Label>
      <Input id={`boq-${id}`} value={(form[id] as string) ?? ''} onChange={set(id)} {...props} />
    </div>
  )

  return (
    <Dialog open={!!state} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{state?.line ? 'Edit line' : `Add a line to ${state?.section.name ?? ''}`}</DialogTitle>
          <DialogDescription>One work item from the estimate. Rates are per unit; leave a rate empty if you don't have it yet.</DialogDescription>
        </DialogHeader>
        <form
          className="flex flex-col gap-3"
          onSubmit={(e) => {
            e.preventDefault()
            onSave(form)
          }}
        >
          <div className="grid gap-3 sm:grid-cols-[90px_1fr]">
            {field('boq_code', 'Item no.', { placeholder: state?.section.code ? `${state.section.code}.1` : '1.1' })}
            {field('work', 'Work', { placeholder: 'Internal plastering 12 mm', required: true })}
          </div>
          <div className="grid grid-cols-2 gap-3">
            {field('planned_quantity', 'Quantity', { inputMode: 'decimal', placeholder: '18000', required: true })}
            {field('unit', 'Unit', { placeholder: 'sqft, cum, rft, nos', required: true })}
          </div>
          {qtyChanged && field('revision_reason', 'Why the quantity changed (kept in history)', { placeholder: 'Balcony added' })}
          {field('client_rate', 'Client rate (₹ per unit, what the client pays)', { inputMode: 'decimal', placeholder: '42' })}
          <fieldset className="flex flex-col gap-1.5">
            <legend className="mb-1 text-sm font-medium">Budget rate (₹ per unit, what it should cost us)</legend>
            <div className="grid grid-cols-3 gap-3">
              {field('labour_rate', 'Labour', { inputMode: 'decimal', placeholder: '14' })}
              {field('material_rate', 'Material', { inputMode: 'decimal', placeholder: '22' })}
              {field('subcontract_rate', 'Subcontract', { inputMode: 'decimal', placeholder: '—' })}
            </div>
            {qty > 0 && budget > 0 && (
              <p className="text-xs text-muted-foreground">
                Budget ₹{budget.toLocaleString('en-IN')} per unit × {qty.toLocaleString('en-IN')} = ₹{(budget * qty).toLocaleString('en-IN', { maximumFractionDigits: 2 })}
              </p>
            )}
          </fieldset>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
            <Button type="submit" disabled={saving}>{saving ? 'Saving…' : 'Save line'}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function SectionDialog({
  section,
  open,
  onClose,
  onSave,
  saving,
}: {
  section: BoqSection | null
  open: boolean
  onClose: () => void
  onSave: (name: string, code: string) => void
  saving: boolean
}) {
  const [name, setName] = React.useState('')
  const [code, setCode] = React.useState('')
  React.useEffect(() => {
    setName(section?.name ?? '')
    setCode(section?.code ?? '')
  }, [section, open])
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{section ? 'Rename section' : 'Add a section'}</DialogTitle>
          <DialogDescription>A group of lines, as in the estimate: "Concrete work", "Plastering", or a floor.</DialogDescription>
        </DialogHeader>
        <form
          className="flex flex-col gap-3"
          onSubmit={(e) => {
            e.preventDefault()
            onSave(name, code)
          }}
        >
          <div className="grid gap-3 sm:grid-cols-[90px_1fr]">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="boq-section-code">No.</Label>
              <Input id="boq-section-code" value={code} onChange={(e) => setCode(e.target.value)} placeholder="4" />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="boq-section-name">Name</Label>
              <Input id="boq-section-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Plastering" required />
            </div>
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
            <Button type="submit" disabled={saving}>{saving ? 'Saving…' : 'Save'}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function SectionTable({
  section,
  readOnly,
  onAdd,
  onEdit,
  onDelete,
}: {
  section: BoqSection
  readOnly: boolean
  onAdd: () => void
  onEdit: (line: BoqLine) => void
  onDelete: (line: BoqLine) => void
}) {
  if (section.lines.length === 0) {
    return (
      <p className="rounded-lg border border-dashed px-3 py-4 text-sm text-muted-foreground">
        No lines yet.{' '}
        {!readOnly && (
          <button type="button" className="font-medium text-foreground underline underline-offset-2" onClick={onAdd}>
            Add the first line
          </button>
        )}
      </p>
    )
  }
  return (
    <div className="overflow-x-auto rounded-lg border [contain:inline-size]">
      <table className="w-full min-w-[1040px] text-sm">
        <thead className="bg-muted/50 text-xs text-muted-foreground">
          <tr>
            <th className="px-3 py-2 text-left font-medium">No.</th>
            <th className="px-3 py-2 text-left font-medium">Work</th>
            <th className={cn('px-3 py-2 font-medium', NUM)}>Quantity</th>
            <th className="px-3 py-2 text-left font-medium">Done</th>
            <th className={cn('px-3 py-2 font-medium', NUM)}>Client rate</th>
            <th className={cn('px-3 py-2 font-medium', NUM)}>Budget rate</th>
            <th className={cn('px-3 py-2 font-medium', NUM)}>Contract value</th>
            <th className={cn('px-3 py-2 font-medium', NUM)}>Budget cost</th>
            <th className={cn('px-3 py-2 font-medium', NUM)}>Earned</th>
            <th className={cn('px-3 py-2 font-medium', NUM)}>Margin</th>
            {!readOnly && <th className="w-10" aria-label="Actions" />}
          </tr>
        </thead>
        <tbody className="divide-y">
          {section.lines.map((line) => (
            <tr key={line.id}>
              <td className="px-3 py-2 text-muted-foreground">{line.boq_code ?? ''}</td>
              <td className="px-3 py-2">
                <span className="font-medium">{line.work}</span>
                {line.revision_no > 1 && <span className="ml-2 text-xs text-muted-foreground">rev {line.revision_no}</span>}
              </td>
              <td className={cn('px-3 py-2', NUM)}>
                {formatQuantity(line.planned_quantity)} <span className="text-muted-foreground">{line.unit}</span>
              </td>
              <td className="px-3 py-2">
                <DoneCell line={line} />
              </td>
              <td className={cn('px-3 py-2', NUM)}>{formatRupees(line.client_rate)}</td>
              <td className={cn('px-3 py-2', NUM)} title={[line.labour_rate && `Labour ₹${line.labour_rate}`, line.material_rate && `Material ₹${line.material_rate}`, line.subcontract_rate && `Subcontract ₹${line.subcontract_rate}`].filter(Boolean).join(' + ')}>
                {formatRupees(line.budget_rate)}
              </td>
              <td className={cn('px-3 py-2', NUM)}>{formatRupees(line.contract_value)}</td>
              <td className={cn('px-3 py-2', NUM)}>{formatRupees(line.budget_cost)}</td>
              <td
                className={cn('px-3 py-2', NUM)}
                title={[line.earned_labour && `Labour ₹${line.earned_labour}`, line.earned_material && `Material ₹${line.earned_material}`, line.earned_subcontract && `Subcontract ₹${line.earned_subcontract}`].filter(Boolean).join(' + ')}
              >
                {Number(line.done_quantity) > 0 ? formatRupees(line.earned) : '—'}
              </td>
              <td className={cn('px-3 py-2', NUM, marginClass(line.margin))}>{formatRupees(line.margin)}</td>
              {!readOnly && (
                <td className="px-1 py-1">
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button variant="ghost" size="icon" className="size-8" aria-label={`More for ${line.work}`}>
                        <MoreHorizontal className="size-4" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" className="w-36">
                      <DropdownMenuItem onClick={() => onEdit(line)}>
                        <Pencil className="mr-2 size-3.5" /> Edit
                      </DropdownMenuItem>
                      <DropdownMenuSeparator />
                      <DropdownMenuItem className="text-destructive focus:text-destructive" onClick={() => onDelete(line)}>
                        <Trash2 className="mr-2 size-3.5" /> Remove
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </td>
              )}
            </tr>
          ))}
        </tbody>
        <tfoot className="border-t bg-muted/30 text-sm">
          <tr>
            <td className="px-3 py-2" colSpan={6}>
              <span className="font-medium">Section total</span>
            </td>
            <td className={cn('px-3 py-2 font-semibold', NUM)}>{formatRupees(section.totals.contract_value)}</td>
            <td className={cn('px-3 py-2 font-semibold', NUM)}>{formatRupees(section.totals.budget_cost)}</td>
            <td className={cn('px-3 py-2 font-semibold', NUM)}>{formatRupees(section.totals.earned)}</td>
            <td className={cn('px-3 py-2', NUM, marginClass(section.totals.margin))}>{formatRupees(section.totals.margin)}</td>
            {!readOnly && <td />}
          </tr>
        </tfoot>
      </table>
    </div>
  )
}

function DoneCell({ line }: { line: BoqLine }) {
  const done = Number(line.done_quantity)
  const pct = Math.min(Number(line.percent_done ?? 0), 100)
  return (
    <div className="flex min-w-[120px] flex-col gap-1">
      <span className="tabular-nums">
        {done > 0 ? formatQuantity(line.done_quantity) : <span className="text-muted-foreground">Nothing yet</span>}
        {done > 0 && <span className="text-muted-foreground"> · {line.percent_done}%</span>}
      </span>
      {done > 0 && (
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted" aria-hidden="true">
          <div className={cn('h-full rounded-full', line.over_planned ? 'bg-amber-500' : 'bg-primary')} style={{ width: `${pct}%` }} />
        </div>
      )}
      {line.over_planned && <span className="text-xs text-amber-700 dark:text-amber-400">More than planned</span>}
      {line.done_in_other_unit > 0 && (
        <span className="text-xs text-muted-foreground">{line.done_in_other_unit} in another unit, not added</span>
      )}
    </div>
  )
}

function formatDay(iso: string): string {
  const d = new Date(`${iso}T00:00:00`)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })
}

/** One recorded work quantity not yet on a BOQ line: pick the line (the suggestion is preselected) and confirm. */
function WorkRow({
  work,
  lines,
  readOnly,
  saving,
  onPut,
}: {
  work: BoqWork
  lines: BoqLine[]
  readOnly: boolean
  saving: boolean
  onPut: (lineId: string) => void
}) {
  const sameUnit = lines.filter((l) => l.unit === work.unit)
  const [lineId, setLineId] = React.useState(work.suggested_line_id ?? '')
  return (
    <li className="flex flex-col gap-2 px-3 py-2.5 sm:flex-row sm:items-center sm:gap-3">
      <div className="min-w-0 flex-1">
        <p className="truncate font-medium">{work.work || 'Work update'}</p>
        <p className="text-xs text-muted-foreground">
          {formatDay(work.date)}
          {work.site_name ? ` · ${work.site_name}` : ''} ·{' '}
          <span className="tabular-nums">
            {formatQuantity(work.quantity)} {work.unit}
          </span>
        </p>
      </div>
      {work.on_work_order ? (
        <span className="text-xs text-muted-foreground">On a work order: change it there</span>
      ) : sameUnit.length === 0 ? (
        <span className="text-xs text-muted-foreground">No BOQ line in {work.unit}</span>
      ) : (
        !readOnly && (
          <div className="flex items-center gap-2">
            <Select value={lineId} onValueChange={setLineId}>
              <SelectTrigger className="h-9 w-full sm:w-[260px]" aria-label={`BOQ line for ${work.work ?? 'this work'}`}>
                <SelectValue placeholder="Pick the BOQ line" />
              </SelectTrigger>
              <SelectContent>
                {sameUnit.map((l) => (
                  <SelectItem key={l.id} value={l.id}>
                    {l.boq_code ? `${l.boq_code} · ` : ''}
                    {l.work}
                    {l.id === work.suggested_line_id ? ' (suggested)' : ''}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button size="sm" disabled={!lineId || saving} onClick={() => onPut(lineId)}>
              Count
            </Button>
          </div>
        )
      )}
    </li>
  )
}

const blankToNull = (v: string | null | undefined) => {
  const t = (v ?? '').trim()
  return t === '' ? null : t
}

export default function ProjectBoqPage() {
  const { id = '' } = useParams()
  const { me } = useAuth()
  const toast = useToast()
  const readOnly = useReadOnly()
  const queryClient = useQueryClient()
  const allowed = maySeeBoq(me?.role)

  const projectQuery = useQuery<Project>({ queryKey: ['project-details', id], queryFn: () => fetchProject(id), enabled: !!id })
  const boqQuery = useQuery<Boq>({ queryKey: ['boq', id], queryFn: () => fetchBoq(id), enabled: !!id && allowed })
  const workQuery = useQuery<BoqWork[]>({ queryKey: ['boq-work', id], queryFn: () => fetchBoqWork(id), enabled: !!id && allowed })
  usePageTitle(`BOQ · ${projectQuery.data?.name ?? 'Project'}`)

  const [lineDialog, setLineDialog] = React.useState<LineDialogState>(null)
  const [sectionDialog, setSectionDialog] = React.useState<{ open: boolean; section: BoqSection | null }>({ open: false, section: null })
  const [importing, setImporting] = React.useState(false)
  const [confirm, setConfirm] = React.useState<{ kind: 'line'; line: BoqLine } | { kind: 'section'; section: BoqSection } | null>(null)

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['boq', id] })
    queryClient.invalidateQueries({ queryKey: ['boq-work', id] })
  }
  const fail = (title: string) => (err: unknown) => toast.error(title, apiErrorMessage(err))

  const saveLine = useMutation({
    mutationFn: async (input: LineInput) => {
      if (!lineDialog) return
      const body: LineInput = {
        work: input.work.trim(),
        unit: input.unit.trim(),
        planned_quantity: input.planned_quantity.trim(),
        boq_code: blankToNull(input.boq_code),
        client_rate: blankToNull(input.client_rate),
        labour_rate: blankToNull(input.labour_rate),
        material_rate: blankToNull(input.material_rate),
        subcontract_rate: blankToNull(input.subcontract_rate),
      }
      if (lineDialog.line) {
        await updateLine(id, lineDialog.line.id, { ...body, revision_reason: blankToNull(input.revision_reason) })
      } else {
        await createLine(id, lineDialog.section.id, body)
      }
    },
    onSuccess: () => {
      toast.success(lineDialog?.line ? 'Line saved' : 'Line added')
      setLineDialog(null)
      refresh()
    },
    onError: fail('Could not save the line'),
  })

  const saveSection = useMutation({
    mutationFn: async ({ name, code }: { name: string; code: string }) => {
      const body = { name: name.trim(), code: blankToNull(code) }
      if (sectionDialog.section) await updateSection(id, sectionDialog.section.id, body)
      else await createSection(id, body)
    },
    onSuccess: () => {
      setSectionDialog({ open: false, section: null })
      refresh()
    },
    onError: fail('Could not save the section'),
  })

  const remove = useMutation({
    mutationFn: async () => {
      if (confirm?.kind === 'line') await deleteLine(id, confirm.line.id)
      if (confirm?.kind === 'section') await deleteSection(id, confirm.section.id)
    },
    onSuccess: () => {
      toast.success('Removed')
      setConfirm(null)
      refresh()
    },
    onError: fail('Could not remove'),
  })

  const putWork = useMutation({
    mutationFn: ({ work, lineId }: { work: BoqWork; lineId: string }) => putWorkOnLine(id, work.id, lineId),
    onSuccess: () => {
      toast.success('Counted on the BOQ line')
      refresh()
    },
    onError: fail('Could not count the work'),
  })

  const project = projectQuery.data
  const back = { to: `/projects/${id}`, label: project?.name ?? 'Project' }

  if (!allowed) {
    return (
      <div className="mx-auto flex w-full max-w-md flex-col items-center gap-3 py-16 text-center">
        <p className="font-medium">The BOQ shows the company's rates and margins.</p>
        <p className="text-sm text-muted-foreground">Only owners, admins, finance and project managers can open it.</p>
        <Button asChild variant="outline" size="sm">
          <Link to={back.to}>Back to {back.label}</Link>
        </Button>
      </div>
    )
  }
  if (projectQuery.isLoading || boqQuery.isLoading) {
    return (
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-4 sm:px-2" aria-busy="true" aria-label="Loading">
        <Skeleton className="h-8 w-72" />
        <Skeleton className="h-24 rounded-lg" />
        <Skeleton className="h-48 rounded-lg" />
      </div>
    )
  }
  if (boqQuery.isError || !boqQuery.data) {
    return <PageError message="The BOQ could not be loaded." onRetry={() => boqQuery.refetch()} back={back} />
  }
  const boq = boqQuery.data

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-4 pb-8 sm:px-2">
      <DprHeader
        back={back}
        crumb="Project"
        title="BOQ and budget"
        date={project?.name}
        action={
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" variant="outline" className="gap-1.5" asChild>
              <Link to={`/planning/schedule?project=${id}`}><CalendarRange className="size-3.5" /> Schedule</Link>
            </Button>
            {!readOnly && (
              <Button size="sm" variant="outline" className="gap-1.5" onClick={() => setImporting(true)}>
                <FileSpreadsheet className="size-3.5" /> Import from Excel
              </Button>
            )}
            {!readOnly && (
              <Button size="sm" className="gap-1.5 font-semibold" onClick={() => setSectionDialog({ open: true, section: null })}>
                <Plus className="size-3.5" /> Add section
              </Button>
            )}
          </div>
        }
      />

      <Callout tone="muted" icon={BookOpen}>
        The BOQ (Bill of Quantities) lists every work item in the project: how much, what the client pays per unit, and what it should cost
        us per unit. Work the site records is counted on its line (Done), with the budget it earned; next, each day's spending is set
        against it to show green or red.
      </Callout>

      {boq.sections.length === 0 ? (
        <div className="flex flex-col items-start gap-3 rounded-lg border border-dashed px-4 py-6">
          <p className="font-medium">No BOQ yet for this project.</p>
          <p className="text-sm text-muted-foreground">
            Upload the estimate Excel you already have (Description, Unit, Qty, Rate): every line comes in with its section, and the
            sections become the schedule. Or start with one section by hand, for example "Plastering".
          </p>
          {!readOnly && (
            <div className="flex flex-wrap gap-2">
              <Button size="sm" className="gap-1.5" onClick={() => setImporting(true)}>
                <FileSpreadsheet className="size-3.5" /> Upload the BOQ Excel
              </Button>
              <Button size="sm" variant="outline" className="gap-1.5" onClick={() => setSectionDialog({ open: true, section: null })}>
                <Plus className="size-3.5" /> Add the first section by hand
              </Button>
            </div>
          )}
        </div>
      ) : (
        <>
          <TotalsStrip totals={boq.totals} />
          {(workQuery.data?.length ?? 0) > 0 && (
            <DprSection icon={ClipboardCheck} title="Work done, not on a BOQ line yet" meta={workQuery.data?.length}>
              <p className="mb-2 text-sm text-muted-foreground">
                Work the site recorded that isn't counted against the budget yet. Pick its line and press Count; Mesiri suggests one where the
                words and unit match, but never counts it by itself.
              </p>
              <ul className="divide-y rounded-lg border text-sm">
                {workQuery.data?.map((w) => (
                  <WorkRow
                    key={w.id}
                    work={w}
                    lines={boq.sections.flatMap((s) => s.lines)}
                    readOnly={readOnly}
                    saving={putWork.isPending}
                    onPut={(lineId) => putWork.mutate({ work: w, lineId })}
                  />
                ))}
              </ul>
            </DprSection>
          )}
          <div className="flex flex-col">
            {boq.sections.map((section) => (
              <DprSection
                key={section.id}
                icon={Calculator}
                title={section.code ? `${section.code}. ${section.name}` : section.name}
                meta={section.lines.length || undefined}
                action={
                  !readOnly && (
                    <div className="flex items-center gap-1">
                      <Button size="sm" variant="outline" className="gap-1.5" onClick={() => setLineDialog({ section, line: null })}>
                        <Plus className="size-3.5" /> Add line
                      </Button>
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button variant="ghost" size="icon" className="size-8" aria-label={`More for ${section.name}`}>
                            <MoreHorizontal className="size-4" />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end" className="w-40">
                          <DropdownMenuItem onClick={() => setSectionDialog({ open: true, section })}>
                            <Pencil className="mr-2 size-3.5" /> Rename
                          </DropdownMenuItem>
                          <DropdownMenuSeparator />
                          <DropdownMenuItem className="text-destructive focus:text-destructive" onClick={() => setConfirm({ kind: 'section', section })}>
                            <Trash2 className="mr-2 size-3.5" /> Remove
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </div>
                  )
                }
              >
                <SectionTable
                  section={section}
                  readOnly={readOnly}
                  onAdd={() => setLineDialog({ section, line: null })}
                  onEdit={(line) => setLineDialog({ section, line })}
                  onDelete={(line) => setConfirm({ kind: 'line', line })}
                />
              </DprSection>
            ))}
          </div>
        </>
      )}

      <LineDialog state={lineDialog} onClose={() => setLineDialog(null)} onSave={(f) => saveLine.mutate(f)} saving={saveLine.isPending} />
      <SectionDialog
        section={sectionDialog.section}
        open={sectionDialog.open}
        onClose={() => setSectionDialog({ open: false, section: null })}
        onSave={(name, code) => saveSection.mutate({ name, code })}
        saving={saveSection.isPending}
      />
      <Dialog open={!!confirm} onOpenChange={(o) => !o && setConfirm(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{confirm?.kind === 'section' ? `Remove ${confirm.section.name}?` : `Remove ${confirm?.kind === 'line' ? confirm.line.work : ''}?`}</DialogTitle>
            <DialogDescription>
              {confirm?.kind === 'section'
                ? `Its ${confirm.section.lines.length} lines go with it. A section with work already logged against it can't be removed.`
                : 'The line and its earlier quantities are removed from the BOQ.'}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirm(null)}>Cancel</Button>
            <Button variant="destructive" disabled={remove.isPending} onClick={() => remove.mutate()}>
              {remove.isPending ? 'Removing…' : 'Remove'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <BoqImportDialog projectId={id} projectName={project?.name} open={importing} onOpenChange={setImporting} />
    </div>
  )
}
