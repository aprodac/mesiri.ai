import * as React from 'react'
import { MONEY_PEOPLE } from '@/lib/permissions'
import { ActionButton, ActionIcon, ActionMenuItem, NoAccess } from '@/components/page/page-kit'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowRight, Calculator, ClipboardCheck, ChevronRight, MoreHorizontal, Package, Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { useToast } from '@/components/ui/toast-notification'
import { DprHeader, DprSection, PageError, StatStrip, type Stat } from '@/components/dpr-page'
import { useAuth } from '@/lib/AuthContext'
import { fetchProject, type Project } from '@/lib/projects'
import { BoqImportDialog } from '@/components/schedule/boq-import-dialog'
import { NormsDialog } from '@/components/boq/norms-dialog'
import {
  copyLineNorms,
  createLine,
  createSection,
  deleteLine,
  deleteSection,
  fetchBoq,
  fetchBoqWork,
  formatQuantity,
  formatRupees,
  formatRupeesShort,
  maySeeBoq,
  putLineNorms,
  putWorkOnLine,
  updateLine,
  updateSection,
  type Boq,
  type BoqLine,
  type BoqSection,
  type BoqTotals,
  type BoqWork,
  type LineInput,
  type NormInput,
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

/** Margin as a share of the contract value, whole percent (null when either is missing). */
function marginPct(margin: string | null, contract: string | null): number | null {
  if (margin === null || !Number(contract)) return null
  return Math.round((Number(margin) / Number(contract)) * 100)
}

// Colour marks only a problem (UX-19): a loss is red, a thin margin (under 5%) amber, a healthy one plain ink.
// Green on every line said nothing.
const THIN_MARGIN = 5
function marginClass(value: string | null, contract?: string | null): string {
  if (value === null) return 'text-muted-foreground'
  if (Number(value) < 0) return 'text-destructive font-semibold'
  const pct = marginPct(value, contract ?? null)
  return pct !== null && pct < THIN_MARGIN ? 'text-draft font-semibold' : 'font-medium'
}

/** A money cell: short (₹21.4 L), the full figure on hover. */
function Money({ value, title }: { value: string | null; title?: string }) {
  return <span title={[formatRupees(value), title].filter(Boolean).join(' · ')}>{formatRupeesShort(value)}</span>
}

function TotalsStrip({ totals }: { totals: BoqTotals }) {
  // UX-15: the figures draw what they mean: margin by colour, the budget's share of the contract and the budget
  // earned so far as bars, the priced lines as "x of y" (amber while some still have no rate).
  const num = (v: string | null | undefined) => (v === null || v === undefined ? null : Number(v))
  const contract = num(totals.contract_value)
  const budget = num(totals.budget_cost)
  const earned = num(totals.earned)
  const priced = totals.line_count - Math.max(totals.lines_without_client_rate, totals.lines_without_budget_rate)
  const stats: Stat[] = [
    { label: 'Contract value', value: formatRupees(totals.contract_value), kind: 'money', hint: 'client pays' },
    {
      label: 'Budget cost', value: formatRupees(totals.budget_cost), kind: 'bill',
      share: contract && budget !== null ? budget / contract : undefined, hint: contract && budget !== null ? `${Math.round((budget / contract) * 100)}% of contract` : undefined,
    },
    { label: 'Margin', value: formatRupees(totals.margin), kind: 'margin', tone: totals.margin === null ? 'default' : Number(totals.margin) < 0 ? 'bad' : 'good', hint: marginPct(totals.margin, totals.contract_value) !== null ? `${marginPct(totals.margin, totals.contract_value)}% of contract` : undefined },
    ...(totals.earned !== undefined
      ? [{
          label: 'Earned so far', value: formatRupees(totals.earned), kind: 'progress' as const,
          share: budget && earned !== null ? earned / budget : 0, hint: budget && earned !== null ? `${Math.round((earned / budget) * 100)}% of budget` : 'by work done',
        }]
      : []),
    {
      label: 'Lines priced', value: priced, of: totals.line_count, kind: 'work', tone: priced < totals.line_count ? 'attention' : 'good',
      hint: [totals.lines_without_client_rate > 0 && `${totals.lines_without_client_rate} no client rate`, totals.lines_without_budget_rate > 0 && `${totals.lines_without_budget_rate} no budget rate`].filter(Boolean).join(' · ') || 'all priced',
    },
  ]
  return <StatStrip stats={stats} phoneCols={2} guide="boq.totals" />
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
  onNorms,
  onDelete,
}: {
  section: BoqSection
  readOnly: boolean
  onAdd: () => void
  onEdit: (line: BoqLine) => void
  onNorms: (line: BoqLine) => void
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
  // A section whose lines carry no BOQ codes gives the No. column nothing to show: it is left out.
  const hasCodes = section.lines.some((l) => l.boq_code)
  return (
    <div className="overflow-x-auto rounded-lg border [contain:inline-size]" data-guide="boq.lines">
      <table className="w-full min-w-[880px] text-sm">
        <thead className="bg-muted/50 text-xs text-muted-foreground">
          <tr>
            {hasCodes && <th className="px-3 py-2 text-left font-medium">No.</th>}
            <th className="px-3 py-2 text-left font-medium">Work</th>
            <th className={cn('px-3 py-2 font-medium', NUM)}>Quantity</th>
            <th className="px-3 py-2 text-left font-medium">Done</th>
            <th className={cn('px-3 py-2 font-medium', NUM)} title="What the client pays per unit, and what it should cost you">Rate · cost</th>
            <th className={cn('px-3 py-2 font-medium', NUM)}>Contract value</th>
            <th className={cn('px-3 py-2 font-medium', NUM)} title="The budget the work done so far has earned">Earned</th>
            <th className={cn('px-3 py-2 font-medium', NUM)}>Margin</th>
            {!readOnly && <th className="w-10" aria-label="Actions" />}
          </tr>
        </thead>
        <tbody className="divide-y">
          {section.lines.map((line) => {
            const pct = marginPct(line.margin, line.contract_value)
            return (
              <tr key={line.id}>
                {hasCodes && <td className="px-3 py-2.5 align-top text-muted-foreground tabular-nums">{line.boq_code ?? ''}</td>}
                <td className="px-3 py-2.5">
                  <span className="font-medium">{line.work}</span>
                  {line.revision_no > 1 && <span className="ml-2 text-xs text-muted-foreground">rev {line.revision_no}</span>}
                  <MaterialsNote line={line} readOnly={readOnly} onNorms={() => onNorms(line)} />
                </td>
                <td className={cn('px-3 py-2.5 whitespace-nowrap', NUM)}>
                  {formatQuantity(line.planned_quantity)} <span className="text-muted-foreground">{line.unit}</span>
                </td>
                <td className="px-3 py-2.5">
                  <DoneCell line={line} />
                </td>
                <td
                  className={cn('px-3 py-2.5 whitespace-nowrap', NUM)}
                  title={[line.labour_rate && `Labour ₹${line.labour_rate}`, line.material_rate && `Material ₹${line.material_rate}`, line.subcontract_rate && `Subcontract ₹${line.subcontract_rate}`].filter(Boolean).join(' + ')}
                >
                  <div>{formatRupees(line.client_rate)}</div>
                  <div className="text-xs text-muted-foreground">cost {formatRupees(line.budget_rate)}</div>
                </td>
                <td className={cn('px-3 py-2.5 whitespace-nowrap', NUM)}>
                  <Money value={line.contract_value} title={line.budget_cost ? `budget cost ${formatRupees(line.budget_cost)}` : undefined} />
                </td>
                <td
                  className={cn('px-3 py-2.5 whitespace-nowrap', NUM)}
                  title={[line.earned_labour && `Labour ₹${line.earned_labour}`, line.earned_material && `Material ₹${line.earned_material}`, line.earned_subcontract && `Subcontract ₹${line.earned_subcontract}`].filter(Boolean).join(' + ')}
                >
                  {Number(line.done_quantity) > 0 ? formatRupeesShort(line.earned) : <span className="text-muted-foreground">—</span>}
                </td>
                <td className={cn('px-3 py-2.5 whitespace-nowrap', NUM, marginClass(line.margin, line.contract_value))}>
                  <Money value={line.margin} />
                  {pct !== null && <div className="text-xs font-normal opacity-80">{pct < 0 ? `−${-pct}` : pct}%</div>}
                </td>
                {!readOnly && (
                  <td className="px-1 py-1">
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button variant="ghost" size="icon" className="size-8" aria-label={`More for ${line.work}`}>
                          <MoreHorizontal className="size-4" />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end" className="w-44">
                        <ActionMenuItem kind="edit" onClick={() => onEdit(line)} />
                        <DropdownMenuItem onClick={() => onNorms(line)}>
                          <Package className="mr-2 size-3.5" /> Materials per {line.unit}
                        </DropdownMenuItem>
                        <DropdownMenuSeparator />
                        <ActionMenuItem kind="delete" onClick={() => onDelete(line)} />
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </td>
                )}
              </tr>
            )
          })}
        </tbody>
        <tfoot className="border-t bg-muted/30 text-sm">
          <tr>
            <td className="px-3 py-2" colSpan={hasCodes ? 5 : 4}>
              <span className="font-medium">Section total</span>
            </td>
            <td className={cn('px-3 py-2 font-semibold whitespace-nowrap', NUM)}><Money value={section.totals.contract_value} /></td>
            <td className={cn('px-3 py-2 font-semibold whitespace-nowrap', NUM)}><Money value={section.totals.earned ?? null} /></td>
            <td className={cn('px-3 py-2 whitespace-nowrap', NUM, marginClass(section.totals.margin, section.totals.contract_value))}><Money value={section.totals.margin} /></td>
            {!readOnly && <td />}
          </tr>
        </tfoot>
      </table>
    </div>
  )
}

/** A section's header line: its size, how far its work is, and its margin, so a closed section still reads. */
function SectionSummary({ section }: { section: BoqSection }) {
  const t = section.totals
  const n = section.lines.length
  if (!n) return null
  const done = Number(t.budget_cost) ? Math.round((Number(t.earned ?? 0) / Number(t.budget_cost)) * 100) : null
  const pct = marginPct(t.margin, t.contract_value)
  return (
    <span className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-sm text-muted-foreground">
      <span>{n} line{n > 1 ? 's' : ''}</span>
      <span aria-hidden>·</span>
      <Money value={t.contract_value} />
      {done !== null && (
        <>
          <span aria-hidden>·</span>
          <span className="inline-flex items-center gap-1.5" title="Budget earned by the work done">
            <span className="h-1.5 w-12 overflow-hidden rounded-full bg-muted" aria-hidden>
              <span className="block h-full rounded-full bg-info" style={{ width: `${Math.min(done, 100)}%` }} />
            </span>
            {done}% done
          </span>
        </>
      )}
      {pct !== null && (
        <>
          <span aria-hidden>·</span>
          <span className={marginClass(t.margin, t.contract_value)}>margin {pct < 0 ? `−${-pct}` : pct}%</span>
        </>
      )}
    </span>
  )
}

/** MP-01: the line's materials per unit, under its name ("Cement 8 bags · M-sand 15 cft per cum"). */
function MaterialsNote({ line, readOnly, onNorms }: { line: BoqLine; readOnly: boolean; onNorms: () => void }) {
  if (line.materials.length === 0) {
    return readOnly ? null : (
      // Missing materials is something to do: it reads as a link, not as one more grey line.
      <button type="button" className="mt-0.5 flex items-center gap-1 text-xs font-medium text-info hover:underline" onClick={onNorms}>
        <Plus className="size-3" aria-hidden /> Add materials
      </button>
    )
  }
  const text = line.materials.map((m) => `${m.material} ${formatQuantity(m.quantity_per_unit)} ${m.unit}`).join(' · ')
  return (
    <button type="button" disabled={readOnly} className="mt-0.5 flex items-start gap-1 text-left text-xs text-muted-foreground enabled:hover:text-foreground" onClick={onNorms} title="Materials per unit of this work">
      <Package className="mt-px size-3 shrink-0" aria-hidden />
      <span>{text} <span className="whitespace-nowrap">per {line.unit}</span></span>
    </button>
  )
}

const sameWork = (a: BoqLine, b: BoqLine) =>
  a.id !== b.id && a.unit === b.unit && a.work.trim().replace(/\s+/g, ' ').toLowerCase() === b.work.trim().replace(/\s+/g, ' ').toLowerCase()

/** Schedule activities with no BOQ lines (site clearing, handover, a drawing's draft schedule): listed together,
 * closed, instead of one empty section each. Adding a line makes one a normal section again. */
function ScheduleOnly({ sections, readOnly, onAdd }: { sections: BoqSection[]; readOnly: boolean; onAdd: (s: BoqSection) => void }) {
  if (!sections.length) return null
  return (
    <details className="mt-2 rounded-lg border">
      <summary className="cursor-pointer px-3 py-2 text-sm text-muted-foreground">
        {sections.length} schedule activit{sections.length > 1 ? 'ies' : 'y'} with no BOQ lines
      </summary>
      <ul className="divide-y border-t text-sm">
        {sections.map((s) => (
          <li key={s.id} className="flex items-center justify-between gap-2 px-3 py-1.5">
            <span>{s.name}</span>
            {!readOnly && <Button size="sm" variant="ghost" className="h-7 gap-1 text-xs" onClick={() => onAdd(s)}><Plus className="size-3" /> Add line</Button>}
          </li>
        ))}
      </ul>
    </details>
  )
}

function DoneCell({ line }: { line: BoqLine }) {
  const done = Number(line.done_quantity)
  const pct = Math.min(Number(line.percent_done ?? 0), 100)
  return (
    <div className="flex min-w-[120px] flex-col gap-1">
      <span className="tabular-nums whitespace-nowrap">
        {done > 0 ? (
          <>
            {formatQuantity(line.done_quantity)} <span className="text-muted-foreground">of {formatQuantity(line.planned_quantity)} {line.unit} · </span>
            <span className="font-medium">{Math.round(Number(line.percent_done ?? 0))}%</span>
          </>
        ) : (
          <span className="text-muted-foreground">Not started</span>
        )}
      </span>
      {done > 0 && (
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted" aria-hidden="true">
          <div className={cn('h-full rounded-full', line.over_planned ? 'bg-draft' : 'bg-info')} style={{ width: `${pct}%` }} />
        </div>
      )}
      {line.over_planned && <span className="text-xs font-medium text-draft">More than planned</span>}
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

/** The share of a line done after adding a quantity to it, whole percent. */
function percentAfter(line: BoqLine, add: string): { from: number; to: number } | null {
  const planned = Number(line.planned_quantity)
  if (!planned) return null
  const done = Number(line.done_quantity)
  return { from: Math.round((done / planned) * 100), to: Math.round(((done + Number(add)) / planned) * 100) }
}

/** A recorded work quantity the site sent that is not on a BOQ line yet (UX-19). With a suggestion, the row shows
 * it as the answer, with what adding it does to the line; "Change" opens the list of lines in the same unit. */
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
  const suggested = sameUnit.some((l) => l.id === work.suggested_line_id) ? work.suggested_line_id : null
  const [lineId, setLineId] = React.useState(suggested ?? '')
  const [picking, setPicking] = React.useState(!suggested)
  const target = sameUnit.find((l) => l.id === lineId)
  const move = target ? percentAfter(target, work.quantity) : null
  return (
    <li className="flex flex-col gap-2 px-3 py-2.5 sm:flex-row sm:items-center sm:gap-4">
      <div className="min-w-0 sm:w-[38%] sm:shrink-0">
        <p className="truncate font-medium">{work.work || 'Work update'}</p>
        <p className="text-xs text-muted-foreground">
          <span className="font-medium text-foreground tabular-nums">
            {formatQuantity(work.quantity)} {work.unit}
          </span>
          {' · '}
          {formatDay(work.date)}
          {work.site_name ? ` · ${work.site_name}` : ''}
        </p>
      </div>
      {work.on_work_order ? (
        <span className="text-xs text-muted-foreground">On a work order: change it there</span>
      ) : sameUnit.length === 0 ? (
        <span className="text-xs text-muted-foreground">No BOQ line in {work.unit} yet: add one, then match this</span>
      ) : readOnly ? null : (
        <>
          <div className="flex min-w-0 flex-1 items-center gap-2">
            <ArrowRight className="hidden size-4 shrink-0 text-muted-foreground sm:block" aria-hidden />
            {picking ? (
              <Select value={lineId} onValueChange={setLineId}>
                <SelectTrigger className="h-9 w-full sm:max-w-[280px]" aria-label={`BOQ line for ${work.work ?? 'this work'}`}>
                  <SelectValue placeholder="Pick the BOQ line" />
                </SelectTrigger>
                <SelectContent>
                  {sameUnit.map((l) => (
                    <SelectItem key={l.id} value={l.id}>
                      {l.boq_code ? `${l.boq_code} · ` : ''}
                      {l.work}
                      {l.id === suggested ? ' (suggested)' : ''}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            ) : (
              <div className="min-w-0">
                <p className="truncate font-medium">{target?.work}</p>
                <button type="button" className="text-xs text-muted-foreground underline underline-offset-2 hover:text-foreground" onClick={() => setPicking(true)}>
                  Change line
                </button>
              </div>
            )}
            {move && (
              <span className="ml-auto shrink-0 text-xs text-muted-foreground tabular-nums" title="How much of the line is done, before and after">
                {move.from}% → <span className="font-semibold text-info">{move.to}%</span>
              </span>
            )}
          </div>
          <Button size="sm" variant="outline" className="shrink-0" disabled={!lineId || saving} onClick={() => onPut(lineId)}>
            Add to line
          </Button>
        </>
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
  const [normsLine, setNormsLine] = React.useState<BoqLine | null>(null)
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

  const saveNorms = useMutation({
    mutationFn: async ({ norms, copy }: { norms: NormInput[]; copy: boolean }) => {
      if (!normsLine) return null
      await putLineNorms(id, normsLine.id, norms)
      // Never over another line's own materials: those lines are kept and counted (the toast says how many).
      if (copy && norms.length > 0) return copyLineNorms(id, normsLine.id, false)
      return null
    },
    onSuccess: (r) => {
      const copied = r?.copied_to.length ?? 0
      const kept = r?.kept.length ?? 0
      toast.success(copied ? `Materials saved, and on ${copied} more line${copied > 1 ? 's' : ''}` : 'Materials saved',
        kept ? `${kept} line${kept > 1 ? 's' : ''} with ${kept > 1 ? 'their' : 'its'} own materials kept as ${kept > 1 ? 'they were' : 'it was'}.` : undefined)
      setNormsLine(null)
      refresh()
    },
    onError: fail('Could not save the materials'),
  })

  const putWork = useMutation({
    mutationFn: ({ work, lineId }: { work: BoqWork; lineId: string }) => putWorkOnLine(id, work.id, lineId),
    onSuccess: () => {
      toast.success('Added to the BOQ line')
      refresh()
    },
    onError: fail('Could not add the work to the line'),
  })

  // UX-19: every row with a suggested line, in one go (one call per row; the API has no batch).
  const suggestedWork = (boqQuery.data && workQuery.data
    ? workQuery.data.filter((w) => !w.on_work_order && w.suggested_line_id && boqQuery.data.sections.some((s) => s.lines.some((l) => l.id === w.suggested_line_id && l.unit === w.unit)))
    : [])
  const putAll = useMutation({
    mutationFn: async (rows: BoqWork[]) => {
      for (const w of rows) await putWorkOnLine(id, w.id, w.suggested_line_id as string)
      return rows.length
    },
    onSuccess: (n) => {
      toast.success(`${n} added to their BOQ lines`)
      refresh()
    },
    onError: (e) => {
      refresh()
      fail('Could not add all of them')(e)
    },
  })
  const [closed, setClosed] = React.useState<Set<string>>(() => new Set())
  const toggle = (sectionId: string) =>
    setClosed((prev) => {
      const next = new Set(prev)
      if (next.has(sectionId)) next.delete(sectionId)
      else next.add(sectionId)
      return next
    })

  const project = projectQuery.data
  const back = { to: `/projects/${id}`, label: project?.name ?? 'Project' }

  if (!allowed) {
    return (
      <div className="mx-auto flex w-full max-w-md flex-col items-center gap-3 py-16 text-center">
        <NoAccess roles={MONEY_PEOPLE} className="py-0" />
        <Button asChild variant="outline" size="sm">
          <Link to={back.to}>Back to {back.label}</Link>
        </Button>
      </div>
    )
  }
  if (projectQuery.isLoading || boqQuery.isLoading) {
    return (
      <div className="mx-auto flex w-full flex-col gap-4 sm:px-2" aria-busy="true" aria-label="Loading">
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
    <div className="mx-auto flex w-full flex-col gap-4 pb-8 sm:px-2">
      <DprHeader
        back={back}
        crumb="Project"
        title="BOQ and budget"
        date={project?.name}
        chip={
          // The schedule is another page, not something done here: a quiet link by the title, not a button.
          <Link to={`/planning/schedule?project=${id}`} data-guide="boq.schedule" className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-sm text-muted-foreground hover:bg-muted hover:text-foreground">
            <ActionIcon kind="schedule" className="size-3.5" /> Schedule <ChevronRight className="size-3.5" aria-hidden />
          </Link>
        }
        action={
          <div className="flex flex-wrap items-center gap-2">
            {!readOnly && <ActionButton kind="import-excel" onClick={() => setImporting(true)} data-guide="boq.import" />}
            {!readOnly && (
              // One yellow button per page: while the BOQ is empty, the upload below is it; while site work waits
              // with suggested lines, "Add all" is.
              <ActionButton kind="add" primary={boq.sections.length > 0 && (readOnly || suggestedWork.length === 0)} onClick={() => setSectionDialog({ open: true, section: null })}>
                Add section
              </ActionButton>
            )}
          </div>
        }
      />

      {boq.sections.length === 0 ? (
        <div className="flex flex-col items-start gap-3 rounded-lg border border-dashed px-4 py-6" data-guide="boq.empty">
          <p className="font-medium">No BOQ yet</p>
          {!readOnly && (
            <div className="flex flex-wrap gap-2">
              <ActionButton kind="import-excel" primary onClick={() => setImporting(true)}>Upload the BOQ Excel</ActionButton>
              <ActionButton kind="add" onClick={() => setSectionDialog({ open: true, section: null })}>Add the first section by hand</ActionButton>
            </div>
          )}
        </div>
      ) : (
        <>
          <TotalsStrip totals={boq.totals} />
          {(workQuery.data?.length ?? 0) > 0 && (
            <DprSection
              icon={ClipboardCheck}
              iconClass="bg-draft-soft text-draft"
              title="Site work to add to the BOQ"
              meta={<span className="rounded-full bg-draft-soft px-2 py-0.5 text-xs font-medium text-draft">{workQuery.data?.length} waiting</span>}
              action={
                !readOnly && suggestedWork.length > 0 && (
                  <ActionButton kind="add" primary disabled={putAll.isPending || putWork.isPending} onClick={() => putAll.mutate(suggestedWork)}>
                    {putAll.isPending ? 'Adding…' : suggestedWork.length > 1 ? `Add all ${suggestedWork.length} suggested` : 'Add the suggested one'}
                  </ActionButton>
                )
              }
            >
              <ul className="divide-y rounded-lg border border-draft/30 text-sm">
                {workQuery.data?.map((w) => (
                  <WorkRow
                    key={w.id}
                    work={w}
                    lines={boq.sections.flatMap((s) => s.lines)}
                    readOnly={readOnly}
                    saving={putWork.isPending || putAll.isPending}
                    onPut={(lineId) => putWork.mutate({ work: w, lineId })}
                  />
                ))}
              </ul>
            </DprSection>
          )}
          <div className="flex flex-col">
            {boq.sections.filter((s) => s.lines.length > 0 || !s.scheduled).map((section) => (
              <DprSection
                key={section.id}
                icon={Calculator}
                title={section.code ? `${section.code}. ${section.name}` : section.name}
                meta={<SectionSummary section={section} />}
                open={!closed.has(section.id)}
                onToggle={section.lines.length ? () => toggle(section.id) : undefined}
                action={
                  !readOnly && (
                    <div className="flex items-center gap-1">
                      <ActionButton kind="add" onClick={() => setLineDialog({ section, line: null })}>Add line</ActionButton>
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button variant="ghost" size="icon" className="size-8" aria-label={`More for ${section.name}`}>
                            <MoreHorizontal className="size-4" />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end" className="w-40">
                          <ActionMenuItem kind="edit" onClick={() => setSectionDialog({ open: true, section })}>Rename</ActionMenuItem>
                          <DropdownMenuSeparator />
                          <ActionMenuItem kind="delete" onClick={() => setConfirm({ kind: 'section', section })} />
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
                  onNorms={setNormsLine}
                  onDelete={(line) => setConfirm({ kind: 'line', line })}
                />
              </DprSection>
            ))}
            <ScheduleOnly sections={boq.sections.filter((s) => s.lines.length === 0 && s.scheduled)} readOnly={readOnly} onAdd={(section) => setLineDialog({ section, line: null })} />
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
            <ActionButton kind="delete" primary size="default" disabled={remove.isPending} onClick={() => remove.mutate()}>
              {remove.isPending ? 'Removing…' : 'Remove'}
            </ActionButton>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <NormsDialog
        line={normsLine}
        similar={normsLine && boqQuery.data ? boqQuery.data.sections.flatMap((s) => s.lines).filter((l) => sameWork(l, normsLine)).length : 0}
        onClose={() => setNormsLine(null)}
        onSave={(norms, copy) => saveNorms.mutate({ norms, copy })}
        saving={saveNorms.isPending}
      />
      <BoqImportDialog projectId={id} projectName={project?.name} open={importing} onOpenChange={setImporting} />
    </div>
  )
}
