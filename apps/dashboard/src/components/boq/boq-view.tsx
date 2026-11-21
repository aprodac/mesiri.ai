import * as React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { BadgeCheck, CircleAlert, Library, MapPin, MoreHorizontal, Package, Search, Trash2, TriangleAlert } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { useToast } from '@/components/ui/toast-notification'
import { Hint } from '@/components/hint'
import {
  addFromLibrary, approveBudget, deleteLibraryItem, fetchLibrary, formatQuantity, formatRupees, formatRupeesShort,
  type Boq, type BoqLine, type BoqSection, type LibraryItem, type LineInput,
} from '@/lib/boq'
import { cn } from '@/lib/utils'

/**
 * PS phase 2b (asked 20 Nov: "the current UI is hard to understand: positions, design, unwanted text"): the BOQ page's
 * parts, rebuilt on four rules. One summary with four numbers. Only what needs you, in one short list. A table whose
 * columns say one thing each (quantity, rate, amount, cost, margin, done). Words only where a number can't speak.
 * Tour markers (`data-guide`) stay on the same things as before (LEARN_AND_TOURS.md).
 */

const n = (v: string | null | undefined) => (v === null || v === undefined || v === '' ? null : Number(v))
const pct = (part: number | null, whole: number | null) => (part !== null && whole ? Math.round((part / whole) * 100) : null)
const THIN = 10

// -- the summary ------------------------------------------------------------------------------------------------------

export function BoqSummary({ boq }: { boq: Boq }) {
  const t = boq.totals
  const contract = n(t.contract_value)
  const budget = n(t.budget_cost)
  const partial = t.margin === null && t.priced_margin != null && (t.priced_lines ?? 0) > 0
  const margin = n(partial ? t.priced_margin : t.margin)
  const marginBase = n(partial ? t.priced_contract_value : t.contract_value)
  const marginPct = pct(margin, marginBase)
  const approved = boq.baseline ? n(boq.baseline.budget_cost) : null
  const drift = approved !== null && budget !== null ? budget - approved : null
  const earned = n(t.earned)
  return (
    <section className="grid grid-cols-2 overflow-hidden rounded-xl border bg-card lg:grid-cols-4" data-guide="boq.totals" aria-label="BOQ summary">
      <Figure label="Contract value" hint={{ term: 'contract value' }} value={formatRupees(t.contract_value)}
        sub={t.contract_value_with_gst ? `${formatRupeesShort(t.contract_value_with_gst)} with ${Number(t.gst_pct)}% GST` : 'before GST'} />
      <Figure label="Budget cost" hint={{ term: 'budget cost' }} value={formatRupees(t.budget_cost)}
        sub={drift !== null && Math.abs(drift) >= 1
          ? `${drift > 0 ? '+' : '−'}${formatRupeesShort(String(Math.abs(drift)))} on the approved ${formatRupeesShort(String(approved))}`
          : approved !== null ? 'as approved' : contract && budget !== null ? `${pct(budget, contract)}% of the contract` : undefined}
        tone={drift !== null && drift > 0 ? 'warn' : undefined} />
      <Figure label="Margin" hint={{ term: 'margin' }} value={margin === null ? '—' : formatRupees(String(margin))}
        tone={margin === null ? undefined : margin < 0 ? 'bad' : marginPct !== null && marginPct < THIN ? 'warn' : 'good'}
        sub={[marginPct !== null ? `${marginPct}%` : null, partial ? `on ${t.priced_lines} of ${t.line_count} lines` : null,
          t.margin_after_overheads != null ? `${formatRupeesShort(t.margin_after_overheads)} after ${Number(t.overhead_pct)}% overheads` : null]
          .filter(Boolean).join(' · ') || undefined} />
      <Figure label="Work done" hint={{ term: 'earned so far' }} value={formatRupees(t.earned ?? '0')}
        sub={budget ? `${pct(earned ?? 0, budget)}% of the budget earned` : undefined} bar={budget ? (earned ?? 0) / budget : undefined} />
    </section>
  )
}

function Figure({ label, value, sub, tone, hint, bar }: {
  label: string; value: string; sub?: string; tone?: 'good' | 'warn' | 'bad'; hint?: React.ComponentProps<typeof Hint>; bar?: number
}) {
  return (
    <div className="flex min-w-0 flex-col gap-1 border-b border-r p-4 last:border-r-0 lg:border-b-0 [&:nth-child(2)]:border-r-0 lg:[&:nth-child(2)]:border-r">
      <span className="flex items-center gap-1 text-xs font-medium text-muted-foreground">{label}{hint && <Hint {...hint} />}</span>
      <span className={cn('text-xl font-semibold tabular-nums sm:text-2xl', tone === 'good' && 'text-success', tone === 'warn' && 'text-draft', tone === 'bad' && 'text-destructive')}>{value}</span>
      {bar !== undefined && (
        <span className="h-1.5 w-full overflow-hidden rounded-full bg-muted" aria-hidden><span className="block h-full rounded-full bg-info" style={{ width: `${Math.min(bar * 100, 100)}%` }} /></span>
      )}
      {sub && <span className="text-xs text-muted-foreground">{sub}</span>}
    </div>
  )
}

// -- what needs you -------------------------------------------------------------------------------------------------

export function BoqNotices({ boq, money, readOnly, onApprove, onShowUnpriced, children }: {
  boq: Boq; money: boolean; readOnly: boolean; onApprove: () => void; onShowUnpriced: () => void; children?: React.ReactNode
}) {
  const unpriced = boq.totals.lines_without_budget_rate
  const noRate = boq.totals.lines_without_client_rate
  const b = boq.baseline
  const changes = b ? b.lines_changed + b.lines_added + b.lines_removed : 0
  return (
    <div className="flex flex-col gap-2">
      {(unpriced > 0 || noRate > 0) && (
        <Notice icon={CircleAlert} tone="warn" action={<Button size="sm" variant="outline" onClick={onShowUnpriced}>Show them</Button>}>
          {[unpriced > 0 && `${unpriced} line${unpriced > 1 ? 's have' : ' has'} no cost rate`, noRate > 0 && `${noRate} no client rate`].filter(Boolean).join(', ')}: their margin is not counted yet.
        </Notice>
      )}
      {children}
      {b ? (
        <Notice icon={BadgeCheck} tone="ok">
          <span className="font-medium">{b.name} approved</span> on {new Date(b.locked_at).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })}
          {b.locked_by ? ` by ${b.locked_by}` : ''}.{' '}
          {changes ? <span className="text-draft">Since then: {[b.lines_changed && `${b.lines_changed} changed`, b.lines_added && `${b.lines_added} added`, b.lines_removed && `${b.lines_removed} removed`].filter(Boolean).join(', ')}.</span> : 'No change since.'}
          {money && !readOnly && changes > 0 && <button type="button" className="ml-2 font-medium underline underline-offset-2" onClick={onApprove}>Approve again</button>}
        </Notice>
      ) : money && !readOnly && boq.totals.line_count > 0 ? (
        <Notice icon={BadgeCheck} tone="muted" action={<Button size="sm" variant="outline" onClick={onApprove}>Approve budget</Button>}>
          Budget not approved yet. Approving keeps this version, and every later change shows against it.
        </Notice>
      ) : null}
    </div>
  )
}

function Notice({ icon: Icon, tone, action, children }: { icon: typeof CircleAlert; tone: 'warn' | 'ok' | 'muted'; action?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className={cn('flex flex-wrap items-center gap-3 rounded-lg border px-3 py-2 text-sm',
      tone === 'warn' && 'border-draft/30 bg-draft-soft/40', tone === 'ok' && 'bg-success-soft/40', tone === 'muted' && 'bg-muted/30')}>
      <Icon className={cn('size-4 shrink-0', tone === 'warn' ? 'text-draft' : tone === 'ok' ? 'text-success' : 'text-muted-foreground')} aria-hidden />
      <span className="min-w-0 flex-1">{children}</span>
      {action}
    </div>
  )
}

// -- filters --------------------------------------------------------------------------------------------------------

export function BoqFilters({ sites, site, onSite, unpricedOnly, onUnpricedOnly, anySplit }: {
  sites: { id: string; name: string }[]; site: string | null; onSite: (s: string | null) => void
  unpricedOnly: boolean; onUnpricedOnly: (v: boolean) => void; anySplit: boolean
}) {
  const chip = (active: boolean) => cn('rounded-full border px-3 py-1 text-sm transition', active ? 'border-foreground bg-foreground text-background' : 'bg-card hover:bg-muted')
  return (
    <div className="flex flex-wrap items-center gap-2" aria-label="Filter the BOQ">
      {sites.length > 1 && (
        <>
          <button type="button" className={chip(site === null)} onClick={() => onSite(null)}>All sites</button>
          {sites.map((s) => (
            <button key={s.id} type="button" className={chip(site === s.id)} onClick={() => onSite(s.id)}>
              <MapPin className="mr-1 inline size-3.5" aria-hidden />{s.name}
            </button>
          ))}
          {!anySplit && <span className="text-xs text-muted-foreground">No line is split by site yet: edit a line to split it.</span>}
          <span className="mx-1 h-5 w-px bg-border" aria-hidden />
        </>
      )}
      <button type="button" className={chip(unpricedOnly)} onClick={() => onUnpricedOnly(!unpricedOnly)}>No cost rate</button>
    </div>
  )
}

// -- the lines ------------------------------------------------------------------------------------------------------

type Actions = {
  onEdit: (line: BoqLine) => void
  onNorms: (line: BoqLine) => void
  onDelete: (line: BoqLine) => void
  onToLibrary: (line: BoqLine) => void
}

/** The quantity, done and value of a line, for all of it or for one site of its split. */
function view(line: BoqLine, site: string | null) {
  const part = site ? line.sites?.find((s) => s.site_id === site) : undefined
  const qty = part ? Number(part.quantity) : Number(line.planned_quantity)
  const done = part ? Number(part.done) : Number(line.done_quantity)
  const share = part && Number(line.planned_quantity) ? qty / Number(line.planned_quantity) : 1
  return {
    qty, done, part,
    amount: n(line.contract_value) === null ? null : (n(line.contract_value) as number) * share,
    margin: n(line.margin) === null ? null : (n(line.margin) as number) * share,
  }
}

/** Sub-items (1.1.1) sit under their item: indented by the depth of their number. */
const depth = (code: string | null) => Math.max((code ?? '').split('.').filter(Boolean).length - 2, 0)

function changedSinceApproved(line: BoqLine): 'new' | 'changed' | null {
  if (line.baseline === undefined) return null
  if (line.baseline === null) return 'new'
  const b = line.baseline
  const same = (a: string | null | undefined, c: string | null | undefined) => Number(a ?? 0) === Number(c ?? 0)
  return same(b.planned_quantity, line.planned_quantity) && same(b.client_rate, line.client_rate) && same(b.budget_rate, line.budget_rate) ? null : 'changed'
}

export function LinesTable({ section, readOnly, site, actions }: { section: BoqSection; readOnly: boolean; site: string | null; actions: Actions }) {
  const lines = section.lines
  return (
    <div data-guide="boq.lines">
      <ul className="divide-y rounded-lg border bg-card md:hidden">
        {lines.map((line) => <LineCard key={line.id} line={line} site={site} readOnly={readOnly} actions={actions} />)}
      </ul>
      <div className="hidden overflow-x-auto rounded-lg border bg-card md:block">
        <table className="w-full min-w-[860px] table-fixed text-sm">
          <colgroup>
            <col className="w-16" /><col /><col className="w-28" /><col className="w-24" /><col className="w-28" />
            <col className="w-24" /><col className="w-24" /><col className="w-28" />{!readOnly && <col className="w-10" />}
          </colgroup>
          <thead className="bg-muted/60 text-xs text-muted-foreground">
            <tr>
              <th className="px-3 py-2 text-left font-medium">No.</th>
              <th className="px-3 py-2 text-left font-medium">Work</th>
              <th className="px-3 py-2 text-right font-medium">{site ? 'Qty here' : 'Qty'}</th>
              <th className="px-3 py-2 text-right font-medium">Rate</th>
              <th className="px-3 py-2 text-right font-medium">Amount</th>
              <th className="px-3 py-2 text-right font-medium">Cost / unit</th>
              <th className="px-3 py-2 text-right font-medium">Margin</th>
              <th className="px-3 py-2 text-left font-medium">Done</th>
              {!readOnly && <th aria-label="Actions" />}
            </tr>
          </thead>
          <tbody className="divide-y">
            {lines.map((line) => {
              const v = view(line, site)
              const change = changedSinceApproved(line)
              return (
                <tr key={line.id} data-guide={(v.margin ?? 0) < 0 ? 'boq.loss' : 'boq.line'} data-record-id={line.id} className="align-top hover:bg-muted/20">
                  <td className="px-3 py-3 text-muted-foreground tabular-nums">{line.boq_code ?? ''}</td>
                  <td className="px-3 py-3" data-guide="boq.work" style={{ paddingLeft: `${0.75 + depth(line.boq_code) * 1.25}rem` }}>
                    <WorkCell line={line} change={change} readOnly={readOnly} onNorms={() => actions.onNorms(line)} />
                  </td>
                  <td className="px-3 py-3 text-right tabular-nums whitespace-nowrap">
                    {formatQuantity(String(v.qty))} <span className="text-xs text-muted-foreground">{line.unit}</span>
                    {v.part && <div className="text-xs text-muted-foreground">of {formatQuantity(line.planned_quantity)}</div>}
                  </td>
                  <td className="px-3 py-3 text-right tabular-nums whitespace-nowrap" data-guide="boq.rate">{line.client_rate ? formatRupees(line.client_rate) : <Missing />}</td>
                  <td className="px-3 py-3 text-right font-medium tabular-nums whitespace-nowrap" data-guide="boq.value">{v.amount === null ? '—' : formatRupees(String(Math.round(v.amount)))}</td>
                  <td className="px-3 py-3 text-right tabular-nums whitespace-nowrap" title={costParts(line)}>{line.budget_rate ? formatRupees(line.budget_rate) : <Missing />}</td>
                  <td className="px-3 py-3 text-right whitespace-nowrap" data-guide="boq.margin"><Margin margin={v.margin} amount={v.amount} /></td>
                  <td className="px-3 py-3" data-guide="boq.progress"><Done done={v.done} qty={v.qty} /></td>
                  {!readOnly && <td className="px-1 py-2"><LineMenu line={line} {...actions} /></td>}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function WorkCell({ line, change, readOnly, onNorms }: { line: BoqLine; change: 'new' | 'changed' | null; readOnly: boolean; onNorms: () => void }) {
  const materials = line.materials.map((m) => `${m.material} ${formatQuantity(m.quantity_per_unit)} ${m.unit}${Number(m.wastage_pct) > 0 ? ` +${Number(m.wastage_pct)}%` : ''}`).join(' · ')
  const b = line.baseline
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <span className="flex flex-wrap items-center gap-1.5">
        <span className="font-medium">{line.work}</span>
        {line.is_provisional && <Tag title="Provisional sum: an allowance, priced when the work is known">Provisional</Tag>}
        {change === 'new' && <Tag tone="info" title="Added after the budget was approved">New</Tag>}
        {change === 'changed' && b && (
          <Tag tone="warn" title={`Approved: ${formatQuantity(b.planned_quantity)} ${line.unit} at ${formatRupees(b.client_rate)}, cost ${formatRupees(b.budget_rate)}`}>Changed</Tag>
        )}
      </span>
      {materials && (
        <button type="button" disabled={readOnly} onClick={onNorms} className="truncate text-left text-xs text-muted-foreground enabled:hover:text-foreground" title={`${materials} per ${line.unit}`}>
          <Package className="mr-1 inline size-3" aria-hidden />{materials} <span className="whitespace-nowrap">per {line.unit}</span>
        </button>
      )}
      {!!line.sites?.length && (
        <span className="truncate text-xs text-muted-foreground" title={line.sites.map((s) => `${s.site}: ${formatQuantity(s.quantity)} ${line.unit}`).join('\n')}>
          <MapPin className="mr-1 inline size-3" aria-hidden />{line.sites.map((s) => `${s.site} ${formatQuantity(s.quantity)}`).join(' · ')}
        </span>
      )}
    </div>
  )
}

function Tag({ children, tone, title }: { children: React.ReactNode; tone?: 'info' | 'warn'; title?: string }) {
  return (
    <span title={title} className={cn('rounded px-1.5 py-0.5 text-[11px] font-medium', !tone && 'bg-muted text-muted-foreground', tone === 'info' && 'bg-info-soft text-info', tone === 'warn' && 'bg-draft-soft text-draft')}>
      {children}
    </span>
  )
}

function Missing() {
  return <span className="text-xs font-medium text-draft">Add rate</span>
}

function Margin({ margin, amount }: { margin: number | null; amount: number | null }) {
  if (margin === null) return <span className="text-muted-foreground">—</span>
  const p = amount ? Math.round((margin / amount) * 100) : null
  const loss = margin < 0
  return (
    <div className="flex flex-col items-end">
      <span className={cn('font-semibold tabular-nums', loss ? 'text-destructive' : p !== null && p < THIN ? 'text-draft' : 'text-success')}>
        {loss && <TriangleAlert className="mr-0.5 inline size-3" aria-hidden />}{p !== null ? `${p}%` : ''}
      </span>
      <span className="text-xs text-muted-foreground tabular-nums">{formatRupees(String(Math.round(margin)))}</span>
    </div>
  )
}

function Done({ done, qty }: { done: number; qty: number }) {
  if (!done) return <span className="text-xs text-muted-foreground">Not started</span>
  const p = qty ? Math.round((done / qty) * 100) : 0
  return (
    <div className="flex flex-col gap-1">
      <span className="text-xs tabular-nums"><span className="font-medium">{p}%</span> <span className="text-muted-foreground">· {formatQuantity(String(done))}</span></span>
      <span className="h-1.5 w-full overflow-hidden rounded-full bg-muted" aria-hidden><span className={cn('block h-full rounded-full', p > 100 ? 'bg-destructive' : 'bg-info')} style={{ width: `${Math.min(p, 100)}%` }} /></span>
    </div>
  )
}

function LineCard({ line, site, readOnly, actions }: { line: BoqLine; site: string | null; readOnly: boolean; actions: Actions }) {
  const v = view(line, site)
  return (
    <li className="flex flex-col gap-2 px-3 py-3 text-sm" data-guide={(v.margin ?? 0) < 0 ? 'boq.loss' : 'boq.line'}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0" data-guide="boq.work">
          {line.boq_code && <span className="mr-1.5 text-muted-foreground tabular-nums">{line.boq_code}</span>}
          <WorkCell line={line} change={changedSinceApproved(line)} readOnly={readOnly} onNorms={() => actions.onNorms(line)} />
        </div>
        {!readOnly && <LineMenu line={line} {...actions} />}
      </div>
      <dl className="grid grid-cols-3 gap-2 text-xs">
        <div><dt className="text-muted-foreground">Qty</dt><dd className="font-medium tabular-nums">{formatQuantity(String(v.qty))} {line.unit}</dd></div>
        <div data-guide="boq.value"><dt className="text-muted-foreground">Amount</dt><dd className="font-medium tabular-nums">{v.amount === null ? '—' : formatRupeesShort(String(v.amount))}</dd></div>
        <div data-guide="boq.margin"><dt className="text-muted-foreground">Margin</dt><dd><Margin margin={v.margin} amount={v.amount} /></dd></div>
      </dl>
      <div data-guide="boq.progress"><Done done={v.done} qty={v.qty} /></div>
      <p className="text-xs text-muted-foreground tabular-nums" data-guide="boq.rate">
        Rate {line.client_rate ? formatRupees(line.client_rate) : '—'} · cost {line.budget_rate ? formatRupees(line.budget_rate) : '—'} per {line.unit}
      </p>
    </li>
  )
}

function LineMenu({ line, onEdit, onNorms, onDelete, onToLibrary }: { line: BoqLine } & Actions) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" className="size-8" aria-label={`More for ${line.work}`}><MoreHorizontal className="size-4" /></Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-52">
        <DropdownMenuItem onClick={() => onEdit(line)}>Edit line</DropdownMenuItem>
        <DropdownMenuItem onClick={() => onNorms(line)}><Package className="mr-2 size-3.5" /> Materials per {line.unit}</DropdownMenuItem>
        <DropdownMenuItem onClick={() => onToLibrary(line)}><Library className="mr-2 size-3.5" /> Save to rate library</DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem className="text-destructive" onClick={() => onDelete(line)}><Trash2 className="mr-2 size-3.5" /> Remove</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

function costParts(line: BoqLine): string {
  return [
    line.labour_rate && `Labour ${formatRupees(line.labour_rate)}`, line.material_rate && `Material ${formatRupees(line.material_rate)}`,
    line.subcontract_rate && `Subcontract ${formatRupees(line.subcontract_rate)}`, line.machinery_rate && `Machinery ${formatRupees(line.machinery_rate)}`,
    line.other_rate && `Other ${formatRupees(line.other_rate)}`,
  ].filter(Boolean).join(' + ')
}

// -- the line editor ------------------------------------------------------------------------------------------------

const COSTS = [
  ['labour_rate', 'Labour'], ['material_rate', 'Material'], ['subcontract_rate', 'Subcontract'], ['machinery_rate', 'Machinery'], ['other_rate', 'Other'],
] as const

type Form = Required<Pick<LineInput, 'work' | 'unit' | 'planned_quantity'>> & {
  boq_code: string; client_rate: string; labour_rate: string; material_rate: string; subcontract_rate: string
  machinery_rate: string; other_rate: string; is_provisional: boolean; revision_reason: string
  split: boolean; sites: Record<string, string>
}

export function LineEditor({ state, sites, onClose, onSave, saving }: {
  state: { section: BoqSection; line: BoqLine | null } | null
  sites: { id: string; name: string }[]
  onClose: () => void
  onSave: (input: LineInput) => void
  saving: boolean
}) {
  const blank: Form = { work: '', unit: '', planned_quantity: '', boq_code: '', client_rate: '', labour_rate: '', material_rate: '', subcontract_rate: '',
    machinery_rate: '', other_rate: '', is_provisional: false, revision_reason: '', split: false, sites: {} }
  const [f, setF] = React.useState<Form>(blank)
  const [error, setError] = React.useState('')
  React.useEffect(() => {
    const l = state?.line
    setError('')
    setF(l ? {
      work: l.work, unit: l.unit, planned_quantity: String(Number(l.planned_quantity)), boq_code: l.boq_code ?? '',
      client_rate: l.client_rate ? String(Number(l.client_rate)) : '', labour_rate: l.labour_rate ? String(Number(l.labour_rate)) : '',
      material_rate: l.material_rate ? String(Number(l.material_rate)) : '', subcontract_rate: l.subcontract_rate ? String(Number(l.subcontract_rate)) : '',
      machinery_rate: l.machinery_rate ? String(Number(l.machinery_rate)) : '', other_rate: l.other_rate ? String(Number(l.other_rate)) : '',
      is_provisional: !!l.is_provisional, revision_reason: '', split: !!l.sites?.length,
      sites: Object.fromEntries((l.sites ?? []).map((s) => [s.site_id, String(Number(s.quantity))])),
    } : blank)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state])
  const set = (patch: Partial<Form>) => { setF((x) => ({ ...x, ...patch })); setError('') }
  const qty = Number(f.planned_quantity) || 0
  const cost = COSTS.reduce((s, [k]) => s + (Number(f[k]) || 0), 0)
  const rate = Number(f.client_rate) || 0
  const splitSum = sites.reduce((s, site) => s + (Number(f.sites[site.id]) || 0), 0)
  const splitOk = !f.split || Math.abs(splitSum - qty) < 0.001
  const qtyChanged = !!state?.line && Number(f.planned_quantity) !== Number(state.line.planned_quantity)
  const eg = (x: string) => (state?.line ? '' : `e.g. ${x}`)
  const splitEqually = () => {
    if (!sites.length || !qty) return
    const each = Math.floor((qty / sites.length) * 1000) / 1000
    const last = Math.round((qty - each * (sites.length - 1)) * 1000) / 1000
    set({ sites: Object.fromEntries(sites.map((s, i) => [s.id, String(i === sites.length - 1 ? last : each)])) })
  }
  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!f.work.trim() || !f.unit.trim() || !(qty > 0)) { setError('Work, unit and a quantity above 0 are needed'); return }
    if (!splitOk) { setError(`The sites add up to ${formatQuantity(String(splitSum))}; the line is ${formatQuantity(String(qty))}`); return }
    const v = (s: string) => (s.trim() === '' ? null : s.trim())
    onSave({
      work: f.work.trim(), unit: f.unit.trim(), planned_quantity: f.planned_quantity.trim(), boq_code: v(f.boq_code), client_rate: v(f.client_rate),
      labour_rate: v(f.labour_rate), material_rate: v(f.material_rate), subcontract_rate: v(f.subcontract_rate), machinery_rate: v(f.machinery_rate),
      other_rate: v(f.other_rate), is_provisional: f.is_provisional, revision_reason: v(f.revision_reason),
      sites: f.split ? sites.filter((s) => Number(f.sites[s.id]) > 0).map((s) => ({ site_id: s.id, quantity: String(Number(f.sites[s.id])) }))
        : state?.line?.sites?.length ? [] : undefined,
    })
  }
  const box = (key: keyof Form, label: string, placeholder = '', suffix?: string) => (
    <div className="grid gap-1">
      <Label htmlFor={`le-${key}`} className="text-xs text-muted-foreground">{label}</Label>
      <div className="relative">
        <Input id={`le-${key}`} value={f[key] as string} onChange={(e) => set({ [key]: e.target.value } as Partial<Form>)} placeholder={placeholder}
          inputMode={['work', 'unit', 'boq_code', 'revision_reason'].includes(key) ? undefined : 'decimal'} className={cn('h-9', suffix && 'pr-12')} />
        {suffix && <span className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-xs text-muted-foreground">{suffix}</span>}
      </div>
    </div>
  )
  return (
    <Dialog open={!!state} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[92vh] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{state?.line ? 'Edit line' : `New line in ${state?.section.name ?? ''}`}</DialogTitle>
          <DialogDescription className="sr-only">One work item: quantity, the client's rate and our cost per unit.</DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="flex flex-col gap-5">
          <fieldset className="grid gap-3">
            <div className="grid grid-cols-[5.5rem_1fr] gap-3">{box('boq_code', 'Item no.', eg('4.1'))}{box('work', 'Work', eg('Internal plastering 12 mm'))}</div>
            <div className="grid grid-cols-2 gap-3">{box('planned_quantity', 'Quantity', eg('1450'))}{box('unit', 'Unit', 'sqm, cum, rft, nos')}</div>
            {qtyChanged && box('revision_reason', 'Why the quantity changed', 'e.g. Balcony added')}
          </fieldset>

          <fieldset className="grid gap-2 rounded-lg border p-3">
            <legend className="px-1 text-sm font-medium">Rates per {f.unit || 'unit'}</legend>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
              {box('client_rate', 'Client pays', eg('420'), '₹')}
              {COSTS.map(([k, label]) => <React.Fragment key={k}>{box(k, `${label} cost`, '', '₹')}</React.Fragment>)}
            </div>
            {(rate > 0 || cost > 0) && (
              <p className="text-xs text-muted-foreground tabular-nums">
                Cost {formatRupees(String(cost))}
                {rate > 0 && cost > 0 && <> · margin <span className={cn('font-semibold', rate - cost < 0 ? 'text-destructive' : 'text-success')}>{formatRupees(String(rate - cost))} ({Math.round(((rate - cost) / rate) * 100)}%)</span></>}
                {qty > 0 && rate > 0 && <> · amount <span className="font-semibold text-foreground">{formatRupees(String(Math.round(rate * qty)))}</span></>}
              </p>
            )}
            <label className="flex items-center gap-2 pt-1 text-sm">
              <input type="checkbox" className="size-4" checked={f.is_provisional} onChange={(e) => set({ is_provisional: e.target.checked })} />
              Provisional sum <Hint title="Provisional sum" text="An allowance agreed with the client for work not designed yet (lifts, landscaping). It is priced when the work is known." />
            </label>
          </fieldset>

          {sites.length > 1 && (
            <fieldset className="grid gap-2 rounded-lg border p-3">
              <legend className="px-1 text-sm font-medium">By site</legend>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" className="size-4" checked={f.split} onChange={(e) => set({ split: e.target.checked })} />
                Split this quantity across the sites
              </label>
              {f.split && (
                <>
                  <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                    {sites.map((s) => (
                      <div key={s.id} className="grid gap-1">
                        <Label htmlFor={`site-${s.id}`} className="truncate text-xs text-muted-foreground">{s.name}</Label>
                        <Input id={`site-${s.id}`} inputMode="decimal" className="h-9" value={f.sites[s.id] ?? ''} onChange={(e) => set({ sites: { ...f.sites, [s.id]: e.target.value } })} />
                      </div>
                    ))}
                  </div>
                  <div className="flex items-center justify-between text-xs">
                    <span className={cn('tabular-nums', splitOk ? 'text-success' : 'text-destructive')}>
                      {formatQuantity(String(splitSum))} of {formatQuantity(String(qty))} {f.unit}{splitOk ? ' ✓' : ''}
                    </span>
                    <button type="button" className="font-medium underline underline-offset-2" onClick={splitEqually}>Split equally</button>
                  </div>
                </>
              )}
            </fieldset>
          )}

          {error && <p className="text-sm text-destructive" role="alert">{error}</p>}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
            <Button type="submit" disabled={saving}>{saving ? 'Saving…' : 'Save line'}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

// -- approve the budget ---------------------------------------------------------------------------------------------

export function ApproveBudgetDialog({ projectId, boq, open, onOpenChange }: { projectId: string; boq: Boq; open: boolean; onOpenChange: (o: boolean) => void }) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const [name, setName] = React.useState('')
  const [note, setNote] = React.useState('')
  const save = useMutation({
    mutationFn: () => approveBudget(projectId, { name: name.trim() || undefined, note: note.trim() || undefined }),
    onSuccess: () => {
      toast.success('Budget approved')
      queryClient.invalidateQueries({ queryKey: ['boq', projectId] })
      setName(''); setNote('')
      onOpenChange(false)
    },
    onError: (e: any) => toast.error('Could not approve the budget', e?.response?.data?.detail),
  })
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Approve this budget</DialogTitle>
          <DialogDescription>
            Keeps this version: {boq.totals.line_count} lines, contract {formatRupeesShort(boq.totals.contract_value)}, cost {formatRupeesShort(boq.totals.budget_cost)}.
            Every later change to a quantity or rate shows against it. You can approve again later.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-3">
          <div className="grid gap-1"><Label htmlFor="ab-name">Name</Label><Input id="ab-name" value={name} onChange={(e) => setName(e.target.value)} placeholder={`e.g. Budget v${boq.baseline ? '2' : '1'}`} /></div>
          <div className="grid gap-1"><Label htmlFor="ab-note">Note</Label><Input id="ab-note" value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Agreed with the client on 20 Nov" /></div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={() => save.mutate()} disabled={save.isPending}>{save.isPending ? 'Approving…' : 'Approve budget'}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// -- the rate library -----------------------------------------------------------------------------------------------

export function LibraryDialog({ projectId, section, open, onOpenChange }: { projectId: string; section: BoqSection | null; open: boolean; onOpenChange: (o: boolean) => void }) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const items = useQuery<LibraryItem[]>({ queryKey: ['boq-library', projectId], queryFn: () => fetchLibrary(projectId), enabled: open })
  const [q, setQ] = React.useState('')
  const [picked, setPicked] = React.useState<LibraryItem | null>(null)
  const [qty, setQty] = React.useState('')
  const [code, setCode] = React.useState('')
  React.useEffect(() => { if (open) { setQ(''); setPicked(null); setQty(''); setCode('') } }, [open])
  const add = useMutation({
    mutationFn: () => addFromLibrary(projectId, section!.id, { item_id: picked!.id, planned_quantity: qty, boq_code: code.trim() || null }),
    onSuccess: () => {
      toast.success('Line added from the rate library')
      queryClient.invalidateQueries({ queryKey: ['boq', projectId] })
      onOpenChange(false)
    },
    onError: (e: any) => toast.error('Could not add the line', e?.response?.data?.detail),
  })
  const remove = useMutation({
    mutationFn: (id: string) => deleteLibraryItem(projectId, id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['boq-library', projectId] }),
  })
  const shown = (items.data ?? []).filter((i) => i.work.toLowerCase().includes(q.trim().toLowerCase()))
  const cost = (i: LibraryItem) => [i.labour_rate, i.material_rate, i.subcontract_rate, i.machinery_rate, i.other_rate].reduce((s, r) => s + (Number(r) || 0), 0)
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2"><Library className="size-4" /> Add from your rate library</DialogTitle>
          <DialogDescription>Lines you saved with "Save to rate library": rates and materials come with them.{section ? ` Into ${section.name}.` : ''}</DialogDescription>
        </DialogHeader>
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search the library" className="h-9 pl-8" />
        </div>
        <ul className="max-h-64 divide-y overflow-y-auto rounded-lg border">
          {items.isLoading && <li className="px-3 py-3 text-sm text-muted-foreground">Loading…</li>}
          {!items.isLoading && shown.length === 0 && <li className="px-3 py-3 text-sm text-muted-foreground">{items.data?.length ? 'Nothing matches.' : 'The library is empty. Use "Save to rate library" on a line to add one.'}</li>}
          {shown.map((i) => (
            <li key={i.id} className={cn('flex items-center gap-2 px-3 py-2 text-sm', picked?.id === i.id && 'bg-primary/5')}>
              <button type="button" className="min-w-0 flex-1 text-left" onClick={() => setPicked(i)}>
                <span className="block truncate font-medium">{i.work}</span>
                <span className="text-xs text-muted-foreground tabular-nums">per {i.unit}: client {formatRupees(i.client_rate)} · cost {formatRupees(String(cost(i)))}</span>
              </button>
              <Button variant="ghost" size="icon" className="size-7" aria-label={`Remove ${i.work} from the library`} onClick={() => remove.mutate(i.id)}><Trash2 className="size-3.5" /></Button>
            </li>
          ))}
        </ul>
        {picked && (
          <div className="grid grid-cols-[5.5rem_1fr] gap-3">
            <div className="grid gap-1"><Label htmlFor="lib-code" className="text-xs text-muted-foreground">Item no.</Label><Input id="lib-code" className="h-9" value={code} onChange={(e) => setCode(e.target.value)} /></div>
            <div className="grid gap-1"><Label htmlFor="lib-qty" className="text-xs text-muted-foreground">Quantity for this project ({picked.unit})</Label><Input id="lib-qty" className="h-9" inputMode="decimal" value={qty} onChange={(e) => setQty(e.target.value)} autoFocus /></div>
          </div>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button disabled={!picked || !(Number(qty) > 0) || !section || add.isPending} onClick={() => add.mutate()}>{add.isPending ? 'Adding…' : 'Add line'}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
