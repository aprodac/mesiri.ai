import { Hint } from '@/components/hint'
import * as React from 'react'
import { MONEY_PEOPLE } from '@/lib/permissions'
import { ActionButton, ActionIcon, ActionMenuItem, NoAccess } from '@/components/page/page-kit'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowRight, BadgeCheck, Calculator, ChevronDown, ChevronRight, ClipboardCheck, Copy, Download, Library, MoreHorizontal, Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { useToast } from '@/components/ui/toast-notification'
import { ModuleHeader } from '@/components/page/module-header'
import { DprSection, PageError } from '@/components/dpr-page'
import { useAuth } from '@/lib/AuthContext'
import { fetchProject, type Project } from '@/lib/projects'
import { BoqImportDialog } from '@/components/schedule/boq-import-dialog'
import { ContractFromBoq } from '@/components/boq/contract-from-boq'
import { ApproveBudgetDialog, BoqFilters, BoqNotices, BoqSummary, LibraryDialog, LineEditor, LinesTable } from '@/components/boq/boq-view'
import { downloadBlob } from '@/lib/export'
import { CopyBoqDialog } from '@/components/boq/copy-boq-dialog'
import { mayBill } from '@/lib/billing'
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
  exportBoq,
  saveToLibrary,
  type Boq,
  type BoqLine,
  type BoqSection,
  type BoqWork,
  type LineInput,
  type NormInput,
} from '@/lib/boq'
import { apiErrorMessage } from '@/lib/logo-upload'
import { usePageTitle } from '@/lib/page-title'
import { useReadOnly } from '@/lib/trial'

// CC-02: a project's Bill of Quantities. Every work item with its quantity, what the client
// pays per unit, and what it should cost us per unit. CC-04: the work done on each line (site
// work updates put on it, work-order measurements) and the budget that work earned. Later items
// (CC-05..07) put the money spent against it, to show green or red each day.


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
  return pct !== null && pct < THIN_MARGIN ? 'text-draft font-semibold' : 'text-success font-semibold'
}

/** A money cell: short (₹21.4 L), the full figure on hover. */
function Money({ value, title }: { value: string | null; title?: string }) {
  return <span title={[formatRupees(value), title].filter(Boolean).join(' · ')}>{formatRupeesShort(value)}</span>
}


type LineDialogState = { section: BoqSection; line: BoqLine | null } | null

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
          <DialogTitle className="flex items-center gap-2">{section ? 'Rename section' : 'Add a section'} <Hint title="A section" text='A group of lines, as in the estimate: "Concrete work", "Plastering", or a floor.' /></DialogTitle>
          <DialogDescription className="sr-only">A group of BOQ lines.</DialogDescription>
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
              <Input id="boq-section-code" value={code} onChange={(e) => setCode(e.target.value)} placeholder="e.g. 4" />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="boq-section-name">Name</Label>
              <Input id="boq-section-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Plastering" required />
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
            <span className="h-1.5 w-12 overflow-hidden rounded-full bg-card" aria-hidden>
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
    // SS-69: work with no suggested line (it could be several) is what the guided project asks the person to place.
    <li data-guide={suggested ? undefined : 'boq.pick'} className="flex flex-col gap-2 px-3 py-2.5 sm:flex-row sm:items-center sm:gap-4">
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
            <Hint
              title="Pick the BOQ line"
              text="Which item of the BOQ this work belongs to. Only lines in the same unit are offered. Mesiri suggests one when it is sure; when several fit (three kinds of plastering), you choose."
            />
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
  // PS: the New project flow's "Import the estimate Excel" opens the BOQ on its import (?import=1).
  const [importing, setImporting] = React.useState(() => new URLSearchParams(window.location.search).get('import') === '1')
  // PS phase 2: start the BOQ from an earlier project's.
  const [copying, setCopying] = React.useState(false)
  // PS phase 2b: filters, the approved budget, the rate library.
  const [site, setSite] = React.useState<string | null>(null)
  const [unpricedOnly, setUnpricedOnly] = React.useState(false)
  const [approving, setApproving] = React.useState(false)
  const [libraryFor, setLibraryFor] = React.useState<BoqSection | null>(null)
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
      // PS phase 2b: the editor sends the line already cleaned (empty rates as null, the split by site).
      const { revision_reason: reason, ...body } = input
      if (lineDialog.line) {
        await updateLine(id, lineDialog.line.id, { ...body, revision_reason: reason ?? null })
      } else {
        await createLine(id, lineDialog.section.id, { ...body, sites: body.sites?.length ? body.sites : undefined })
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

  const toLibrary = useMutation({
    mutationFn: (line: BoqLine) => saveToLibrary(id, line.id),
    onSuccess: () => toast.success('Saved to the rate library', 'Add it to any project from a section\'s menu.'),
    onError: fail('Could not save to the library'),
  })
  const exportFile = useMutation({
    mutationFn: (withCosts: boolean) => exportBoq(id, withCosts),
    onSuccess: (blob, withCosts) => downloadBlob(`${projectQuery.data?.name ?? 'Project'} - BOQ${withCosts ? ' with costs' : ''}.xlsx`, blob),
    onError: fail('Could not export the BOQ'),
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
  // PS phase 2b: one site's share, or only the lines still missing a rate; sections with nothing to show are left out.
  const shownSections = boq.sections
    .filter((s) => s.lines.length > 0 || !s.scheduled)
    .map((s) => ({
      ...s,
      lines: s.lines.filter((l) => (!site || l.sites?.some((x) => x.site_id === site)) && (!unpricedOnly || l.budget_rate === null || l.client_rate === null)),
    }))
    .filter((s) => (!site && !unpricedOnly) || s.lines.length > 0)

  return (
    <div className="mx-auto flex w-full flex-col gap-4 pb-8 sm:px-2">
      <ModuleHeader icon={Calculator} title="BOQ and budget" module="Planning" back={back} chip={
          // The schedule is another page, not something done here: a quiet link by the title, not a button.
          <Link to={`/planning/schedule?project=${id}`} data-guide="boq.schedule" className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-sm text-muted-foreground hover:bg-muted hover:text-foreground">
            <ActionIcon kind="schedule" className="size-3.5" /> Schedule <ChevronRight className="size-3.5" aria-hidden />
          </Link>}>
        <div className="flex flex-wrap items-center gap-2">
            {!readOnly && <ActionButton kind="import-excel" onClick={() => setImporting(true)} data-guide="boq.import" />}
            {boq.sections.length > 0 && (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="outline" size="sm" className="gap-1.5">More <ChevronDown className="size-3.5" aria-hidden /></Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-60">
                  <DropdownMenuItem onClick={() => exportFile.mutate(false)}><Download className="mr-2 size-3.5" /> Export for the client (.xlsx)</DropdownMenuItem>
                  <DropdownMenuItem onClick={() => exportFile.mutate(true)}><Download className="mr-2 size-3.5" /> Export with our costs (.xlsx)</DropdownMenuItem>
                  {!readOnly && (
                    <>
                      <DropdownMenuSeparator />
                      {mayBill(me?.role) && <DropdownMenuItem onClick={() => setApproving(true)}><BadgeCheck className="mr-2 size-3.5" /> Approve budget</DropdownMenuItem>}
                      <DropdownMenuItem onClick={() => setCopying(true)}><Copy className="mr-2 size-3.5" /> Copy from a past project</DropdownMenuItem>
                    </>
                  )}
                </DropdownMenuContent>
              </DropdownMenu>
            )}
            {!readOnly && (
              // One yellow button per page: while the BOQ is empty, the upload below is it; while site work waits
              // with suggested lines, "Add all" is.
              <ActionButton kind="add" primary={boq.sections.length > 0 && (readOnly || suggestedWork.length === 0)} onClick={() => setSectionDialog({ open: true, section: null })}>
                Add section
              </ActionButton>
            )}
          </div>
      </ModuleHeader>

      {boq.sections.length === 0 ? (
        <div className="flex flex-col items-start gap-3 rounded-lg border border-dashed px-4 py-6" data-guide="boq.empty">
          <p className="font-medium">No BOQ yet</p>
          {!readOnly && (
            <div className="flex flex-wrap gap-2">
              <ActionButton kind="import-excel" primary onClick={() => setImporting(true)}>Upload the BOQ Excel</ActionButton>
              <Button variant="outline" size="sm" className="gap-1.5" onClick={() => setCopying(true)} data-guide="boq.copy">
                <Copy className="size-4" /> Copy from a past project
              </Button>
              <ActionButton kind="add" onClick={() => setSectionDialog({ open: true, section: null })}>Add the first section by hand</ActionButton>
            </div>
          )}
        </div>
      ) : (
        <>
          <BoqSummary boq={boq} />
          <BoqNotices boq={boq} money={mayBill(me?.role)} readOnly={readOnly} onApprove={() => setApproving(true)} onShowUnpriced={() => setUnpricedOnly(true)}>
            {mayBill(me?.role) && !readOnly && <ContractFromBoq projectId={id} boqTotal={boq.totals.contract_value} />}
          </BoqNotices>
          {(workQuery.data?.length ?? 0) > 0 && (
            <DprSection
              icon={ClipboardCheck}
              iconClass="bg-draft-soft text-draft"
              title="Site work to add to the BOQ"
              guide="boq.waiting"
              meta={
                <span className="inline-flex items-center gap-1.5">
                  <span className="rounded-full bg-draft-soft px-2 py-0.5 text-xs font-medium text-draft">{workQuery.data?.length} waiting</span>
                  <Hint
                    title="Site work to add to the BOQ"
                    text="Work the site reported (on WhatsApp, the app or here) that is not on a BOQ line yet. Put each on its line: the line's progress, what the client owes you and the schedule all move with it."
                    example="'40 sqm plastering' on line 4.1 Plastering: that line goes from 10% to 14% done."
                  />
                </span>
              }
              action={
                !readOnly && suggestedWork.length > 0 && (
                  <ActionButton kind="add" primary data-guide="boq.addall" disabled={putAll.isPending || putWork.isPending} onClick={() => putAll.mutate(suggestedWork)}>
                    {putAll.isPending ? 'Adding…' : suggestedWork.length > 1 ? `Add all ${suggestedWork.length} suggested` : 'Add the suggested one'}
                  </ActionButton>
                )
              }
            >
              <ul className="divide-y rounded-lg border border-draft/30 bg-card text-sm">
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
          <BoqFilters sites={boq.sites ?? []} site={site} onSite={setSite} unpricedOnly={unpricedOnly} onUnpricedOnly={setUnpricedOnly}
            anySplit={boq.sections.some((s) => s.lines.some((l) => !!l.sites?.length))} />
          <div className="flex flex-col gap-1">
            {shownSections.length === 0 && (
              <p className="rounded-lg border border-dashed px-4 py-6 text-center text-sm text-muted-foreground">
                {unpricedOnly ? 'Every line has its cost rate.' : 'No line is split to this site yet.'}{' '}
                <button type="button" className="font-medium underline underline-offset-2" onClick={() => { setSite(null); setUnpricedOnly(false) }}>Show all lines</button>
              </p>
            )}
            {shownSections.map((section) => (
              <DprSection
                key={section.id}
                className="[&>header]:rounded-lg [&>header]:bg-muted [&>header]:px-3 [&>header]:py-2"
                guide="boq.section"
                icon={Calculator}
                title={section.code ? `${section.code}. ${section.name}` : section.name}
                // PS phase 2b: filtered, the header says what is shown (its totals are the whole section's).
                meta={site || unpricedOnly
                  ? <span className="text-sm text-muted-foreground">{section.lines.length} line{section.lines.length === 1 ? '' : 's'} shown</span>
                  : <SectionSummary section={section} />}
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
                        <DropdownMenuContent align="end" className="w-52">
                          <DropdownMenuItem onClick={() => setLibraryFor(section)}><Library className="mr-2 size-3.5" /> Add from rate library</DropdownMenuItem>
                          <ActionMenuItem kind="edit" onClick={() => setSectionDialog({ open: true, section })}>Rename section</ActionMenuItem>
                          <DropdownMenuSeparator />
                          <ActionMenuItem kind="delete" onClick={() => setConfirm({ kind: 'section', section })} />
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </div>
                  )
                }
              >
                {section.lines.length === 0 ? (
                  <p className="rounded-lg border border-dashed px-3 py-4 text-sm text-muted-foreground">
                    No lines yet.{' '}
                    {!readOnly && <button type="button" className="font-medium text-foreground underline underline-offset-2" onClick={() => setLineDialog({ section, line: null })}>Add the first line</button>}
                  </p>
                ) : (
                  <LinesTable section={section} readOnly={readOnly} site={site} actions={{
                    onEdit: (line) => setLineDialog({ section: boq.sections.find((s) => s.id === section.id) ?? section, line }),
                    onNorms: setNormsLine,
                    onDelete: (line) => setConfirm({ kind: 'line', line }),
                    onToLibrary: (line) => toLibrary.mutate(line),
                  }} />
                )}
              </DprSection>
            ))}
            <ScheduleOnly sections={boq.sections.filter((s) => s.lines.length === 0 && s.scheduled)} readOnly={readOnly} onAdd={(section) => setLineDialog({ section, line: null })} />
          </div>
        </>
      )}

      <LineEditor state={lineDialog} sites={boq.sites ?? []} onClose={() => setLineDialog(null)} onSave={(f) => saveLine.mutate(f)} saving={saveLine.isPending} />
      <ApproveBudgetDialog projectId={id} boq={boq} open={approving} onOpenChange={setApproving} />
      <LibraryDialog projectId={id} section={libraryFor} open={!!libraryFor} onOpenChange={(o) => !o && setLibraryFor(null)} />
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
      <CopyBoqDialog projectId={id} open={copying} onOpenChange={setCopying} />
    </div>
  )
}
