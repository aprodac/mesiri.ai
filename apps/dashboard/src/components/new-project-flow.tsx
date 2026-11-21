import * as React from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertCircle, Building2, Check, ChevronLeft, ChevronRight, CircleDashed, FileSpreadsheet, Hash, Loader2, MapPin,
  PenLine, Plus, User as UserIcon, X,
} from 'lucide-react'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { DatePicker } from '@/components/ui/date-picker'
import { Hint } from '@/components/hint'
import { useAuth } from '@/lib/AuthContext'
import { fetchUsers, type User } from '@/lib/api'
import {
  addProjectMember, createProject, createSite, fetchProjectsFull, PROJECT_TYPES, type Project, type ProjectType,
} from '@/lib/projects'
import { CONTRACT_TYPES, fetchClients, mayBill, putContract, rupees, type Client, type ContractType } from '@/lib/billing'
import { updateProjectStart } from '@/lib/schedule'
import { expandSiteNames, MAX_SITES_AT_ONCE, sameSiteName } from '@/lib/site-batch'
import { cn, formatClock } from '@/lib/utils'

/**
 * PS / QA-04: the guided "New project" (asked 20 Nov: everything a construction company sets up before day 1, in one
 * place, the way construction ERPs do it). Five short screens: Basics, Contract, Sites and people, BOQ, Check and
 * create. Only the name is required; every other screen can be skipped and filled later on its own page.
 *
 * It saves through the routes the pages already use (POST /projects, PUT /projects/{id}/contract with a real client,
 * PATCH /projects/{id}/start, POST /projects/{id}/sites, POST /projects/{id}/members): no second way to save a project.
 * Contract terms are shown only to the people who may see client contracts (owner, admin, finance: `mayBill`).
 */

type Step = 0 | 1 | 2 | 3 | 4
const STEPS = ['Basics', 'Contract', 'Sites and people', 'BOQ', 'Check and create'] as const

/** Same comparison as the server's duplicate check ([207]): case and spacing do not count. */
const sameName = (a: string) => a.normalize('NFKC').toLocaleLowerCase().split(/\s+/).filter(Boolean).join(' ')

const num = (v: string): number | null => {
  const t = v.replace(/,/g, '').trim()
  if (!t) return null
  const n = Number(t)
  return Number.isFinite(n) ? n : NaN
}

interface Basics {
  name: string
  clientId: string | null
  clientName: string
  location: string
  type: ProjectType | ''
  area: string
  floors: string
  code: string
  codeTouched: boolean
  notes: string
}

interface Terms {
  value: string
  type: ContractType | ''
  start: string
  finish: string
  payDays: string
  retention: string
  advance: string
  recovery: string
  gst: string
  tds: string
  dlp: string
  ldWeek: string
  ldCap: string
  escalation: boolean
  escalationTerms: string
}

const EMPTY_BASICS: Basics = {
  name: '', clientId: null, clientName: '', location: '', type: '', area: '', floors: '', code: '', codeTouched: false, notes: '',
}
const EMPTY_TERMS: Terms = {
  value: '', type: '', start: '', finish: '', payDays: '', retention: '', advance: '', recovery: '', gst: '', tds: '',
  dlp: '', ldWeek: '', ldCap: '', escalation: false, escalationTerms: '',
}

type Done = { label: string; ok: boolean; error?: string }

export function NewProjectFlow({
  open, onOpenChange, afterCreate,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Where the new project opens once made; by default its start steps, or the BOQ import when chosen. */
  afterCreate?: (projectId: string) => string
}) {
  const { me } = useAuth()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const money = mayBill(me?.role)

  const [step, setStep] = React.useState<Step>(0)
  const [basics, setBasics] = React.useState<Basics>(EMPTY_BASICS)
  const [terms, setTerms] = React.useState<Terms>(EMPTY_TERMS)
  const [sitesText, setSitesText] = React.useState('')
  const [reporter, setReporter] = React.useState('')
  const [manager, setManager] = React.useState('')
  const [boq, setBoq] = React.useState<'import' | 'later'>('import')
  const [errors, setErrors] = React.useState<Record<string, string>>({})
  const [creating, setCreating] = React.useState(false)
  const [clientFocus, setClientFocus] = React.useState(false)
  const [done, setDone] = React.useState<Done[]>([])

  React.useEffect(() => {
    if (!open) return
    setStep(0); setBasics(EMPTY_BASICS); setTerms(EMPTY_TERMS); setSitesText(''); setReporter(''); setManager('')
    setBoq('import'); setErrors({}); setCreating(false); setDone([])
  }, [open])

  const projects = useQuery<Project[]>({ queryKey: ['projects-list'], queryFn: fetchProjectsFull, enabled: open })
  const clients = useQuery<Client[]>({ queryKey: ['billing-clients'], queryFn: fetchClients, enabled: open && money })
  const users = useQuery<User[]>({ queryKey: ['org-users-selection'], queryFn: fetchUsers, enabled: open, retry: false })

  // The short code follows the name ("Palm Grove Villas" -> PGV-004) until the person types their own.
  React.useEffect(() => {
    if (basics.codeTouched) return
    const initials = basics.name.trim().split(/\s+/).map((w) => w[0]).join('').toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 3)
    const n = (projects.data?.length ?? 0) + 1
    setBasics((b) => ({ ...b, code: initials ? `${initials}-${String(n).padStart(3, '0')}` : '' }))
  }, [basics.name, basics.codeTouched, projects.data?.length])

  // The daily report a new project gets: the company's own (the server copies it, [259]); said here, so 9 pm is no surprise.
  const reporting = (projects.data ?? []).find((p) => p.autoGenerateDpr)
  const sites = React.useMemo(() => expandSiteNames(sitesText), [sitesText])
  const people = (users.data ?? []).filter((u) => u.status !== 'suspended' && u.status !== 'inactive')

  const setB = (patch: Partial<Basics>) => {
    setBasics((b) => ({ ...b, ...patch }))
    setErrors((e) => { const next = { ...e }; for (const k of Object.keys(patch)) delete next[k]; return next })
  }
  const setT = (patch: Partial<Terms>) => {
    setTerms((t) => ({ ...t, ...patch }))
    setErrors((e) => { const next = { ...e }; for (const k of Object.keys(patch)) delete next[k]; return next })
  }

  /** The checks of one screen; an empty result lets the person go on. */
  const check = (s: Step): Record<string, string> => {
    const e: Record<string, string> = {}
    if (s === 0) {
      const name = basics.name.trim()
      if (!name) e.name = 'Give the project a name'
      else {
        const same = (projects.data ?? []).find((p) => sameName(p.name) === sameName(name))
        if (same) e.name = `${same.name} is already a project. Use another name.`
      }
      const area = num(basics.area)
      if (Number.isNaN(area) || (area !== null && area <= 0)) e.area = 'Built-up area is a number of sq ft'
      const floors = num(basics.floors)
      if (Number.isNaN(floors) || (floors !== null && (floors < 1 || floors > 200 || !Number.isInteger(floors)))) e.floors = 'Floors is a whole number, 1 or more'
    }
    if (s === 1 && money) {
      for (const [k, label] of [['value', 'Contract value'], ['advance', 'Advance']] as const) {
        const v = num(terms[k]); if (Number.isNaN(v) || (v !== null && v < 0)) e[k] = `${label} is an amount in ₹`
      }
      for (const k of ['retention', 'recovery', 'gst', 'tds', 'ldWeek', 'ldCap'] as const) {
        const v = num(terms[k]); if (Number.isNaN(v) || (v !== null && (v < 0 || v > 100))) e[k] = 'A % from 0 to 100'
      }
      const days = num(terms.payDays)
      if (Number.isNaN(days) || (days !== null && (days < 0 || days > 365 || !Number.isInteger(days)))) e.payDays = 'Days, 0 to 365'
      const dlp = num(terms.dlp)
      if (Number.isNaN(dlp) || (dlp !== null && (dlp < 0 || dlp > 120 || !Number.isInteger(dlp)))) e.dlp = 'Months, 0 to 120'
      const value = num(terms.value); const advance = num(terms.advance)
      if (value && advance && advance > value) e.advance = 'The advance is more than the contract value'
      const week = num(terms.ldWeek); const cap = num(terms.ldCap)
      if (week && cap !== null && !Number.isNaN(cap) && cap < week) e.ldCap = 'The cap is less than one week\'s penalty'
      if (terms.start && terms.finish && terms.finish < terms.start) e.finish = 'Handover is before the start'
    }
    if (s === 2 && sites.tooMany) e.sites = `At most ${MAX_SITES_AT_ONCE} sites at once`
    return e
  }

  const next = () => {
    const e = check(step)
    setErrors(e)
    if (Object.keys(e).length) return
    setStep((s) => Math.min(4, s + 1) as Step)
  }
  const back = () => setStep((s) => Math.max(0, s - 1) as Step)
  const goTo = (s: Step) => {
    for (let i = 0; i < s; i++) {
      const e = check(i as Step)
      if (Object.keys(e).length) { setErrors(e); setStep(i as Step); return }
    }
    setStep(s)
  }

  const contractSaid = money && (basics.clientName.trim() || Object.entries(terms).some(([k, v]) =>
    !['start', 'finish', 'escalation'].includes(k) && String(v).trim()) || terms.escalation)
  const datesSaid = !!(terms.start || terms.finish)

  const create = async () => {
    for (let i = 0; i < 4; i++) {
      const e = check(i as Step)
      if (Object.keys(e).length) { setErrors(e); setStep(i as Step); return }
    }
    setCreating(true)
    const log: Done[] = []
    const push = (d: Done) => { log.push(d); setDone([...log]) }
    let projectId: string
    try {
      const created = await createProject({
        name: basics.name.trim(),
        code: basics.code.trim() || null,
        client: basics.clientName.trim() || null,
        location: basics.location.trim() || null,
        description: basics.notes.trim() || null,
        projectType: basics.type || null,
        builtUpAreaSqft: num(basics.area),
        floors: num(basics.floors),
      })
      projectId = created.id
      push({ label: `Project ${created.name}`, ok: true })
    } catch (err: any) {
      const detail = err?.response?.data?.detail
      setErrors({ name: typeof detail === 'string' ? detail : 'The project could not be made. Try again.' })
      setStep(0)
      setCreating(false)
      setDone([])
      return
    }
    const attempt = async (label: string, run: () => Promise<unknown>) => {
      try { await run(); push({ label, ok: true }) } catch (err: any) {
        const detail = err?.response?.data?.detail
        push({ label, ok: false, error: typeof detail === 'string' ? detail : 'Not saved' })
      }
    }
    if (contractSaid) {
      await attempt('Client and contract', () => putContract(projectId, {
        client_id: basics.clientId,
        new_client: !basics.clientId && basics.clientName.trim() ? { name: basics.clientName.trim() } : null,
        contract_value: terms.value.trim() ? String(num(terms.value)) : null,
        contract_type: terms.type || null,
        retention_pct: terms.retention.trim() || null,
        mobilisation_advance: terms.advance.trim() ? String(num(terms.advance)) : null,
        advance_recovery_pct: terms.recovery.trim() || null,
        gst_pct: terms.gst.trim() || null,
        tds_pct: terms.tds.trim() || null,
        defect_liability_months: num(terms.dlp),
        client_payment_days: num(terms.payDays),
        ld_pct_per_week: terms.ldWeek.trim() || null,
        ld_cap_pct: terms.ldCap.trim() || null,
        escalation_applies: terms.escalation || null,
        escalation_terms: terms.escalation ? terms.escalationTerms.trim() || null : null,
      }))
    }
    if (datesSaid) {
      await attempt('Start and handover dates', () => updateProjectStart(projectId, {
        ...(terms.start ? { start_date: terms.start } : {}), ...(terms.finish ? { planned_finish: terms.finish } : {}),
      }))
    }
    for (const site of sites.names) await attempt(`Site ${site}`, () => createSite(projectId, { name: site }))
    if (manager) await attempt('Project manager', () => addProjectMember(projectId, { userId: manager, role: 'PROJECT_MANAGER' }))
    if (reporter && reporter !== manager) {
      await attempt('Site engineer', () => addProjectMember(projectId, { userId: reporter, role: 'SITE_ENGINEER' }))
    }
    for (const key of ['projects-list', 'scope-projects', 'lifecycle', 'billing-clients']) queryClient.invalidateQueries({ queryKey: [key] })
    setCreating(false)
    if (log.every((d) => d.ok)) finish(projectId)
    else setDone([...log, { label: '__open__', ok: true, error: projectId }])
  }

  const finish = (projectId: string) => {
    onOpenChange(false)
    if (afterCreate) navigate(afterCreate(projectId))
    else if (boq === 'import') navigate(`/projects/${projectId}/boq?project=${projectId}&import=1`)
    else navigate(`/planning/setup?project=${projectId}`)
  }

  const failedOpen = done.find((d) => d.label === '__open__')

  // ---------------------------------------------------------------------------------------------------------------
  const field = (key: string, label: string, control: React.ReactNode, hint?: React.ComponentProps<typeof Hint>, note?: string) => (
    <div className="grid content-start gap-1.5">
      <span className="flex items-center gap-1">
        <Label className="text-sm font-medium">{label}</Label>
        {hint && <Hint {...hint} />}
      </span>
      {control}
      {errors[key] ? (
        <p className="flex items-center gap-1 text-xs text-destructive" role="alert"><AlertCircle className="size-3.5" aria-hidden /> {errors[key]}</p>
      ) : note ? <p className="text-xs text-muted-foreground">{note}</p> : null}
    </div>
  )
  const input = (key: keyof Terms, placeholder: string, suffix?: string) => (
    <div className="relative">
      <Input value={String(terms[key])} onChange={(e) => setT({ [key]: e.target.value } as Partial<Terms>)} placeholder={placeholder}
        inputMode="decimal" aria-invalid={!!errors[key]} className={cn('h-10', suffix && 'pr-12', errors[key] && 'border-destructive')} />
      {suffix && <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-xs text-muted-foreground">{suffix}</span>}
    </div>
  )

  const clientMatches = React.useMemo(() => {
    const q = sameName(basics.clientName)
    if (!q || basics.clientId) return []
    return (clients.data ?? []).filter((c) => sameName(c.name).includes(q)).slice(0, 5)
  }, [basics.clientName, basics.clientId, clients.data])
  const exactClient = (clients.data ?? []).find((c) => sameName(c.name) === sameName(basics.clientName))

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!creating) onOpenChange(o) }}>
      <DialogContent className="max-h-[92vh] overflow-y-auto sm:max-w-[640px]" data-guide="new-project.flow">
        <DialogHeader>
          <DialogTitle>New project</DialogTitle>
          <DialogDescription>Only the name is needed. Skip any screen and fill it in later.</DialogDescription>
        </DialogHeader>

        <ol className="grid grid-cols-5 gap-1.5" aria-label="Steps">
          {STEPS.map((label, i) => (
            <li key={label}>
              <button type="button" onClick={() => !creating && goTo(i as Step)} disabled={creating}
                className={cn('flex w-full flex-col items-start gap-1 rounded-md px-1.5 py-1 text-left text-[11px] leading-tight',
                  i === step ? 'font-semibold text-foreground' : 'text-muted-foreground hover:text-foreground')}
                aria-current={i === step ? 'step' : undefined}>
                <span className={cn('h-1 w-full rounded-full', i < step ? 'bg-primary/60' : i === step ? 'bg-primary' : 'bg-muted')} />
                <span className="hidden sm:inline">{i + 1}. {label}</span>
                <span className="sm:hidden">{i + 1}</span>
              </button>
            </li>
          ))}
        </ol>

        {step === 0 && (
          <div className="grid gap-4">
            {field('name', 'Project name',
              <Input value={basics.name} onChange={(e) => setB({ name: e.target.value })} placeholder="e.g. Rose Garden Villas"
                autoFocus aria-invalid={!!errors.name} className={cn('h-11 text-base', errors.name && 'border-destructive')} />)}
            <div className="grid gap-4 sm:grid-cols-2">
              {field('clientName', 'Client',
                <div className="relative">
                  <UserIcon className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground/70" />
                  <Input value={basics.clientName} placeholder="e.g. Dr. Meera Nair" className="h-10 pl-9 pr-8"
                    onChange={(e) => setB({ clientName: e.target.value, clientId: null })}
                    onFocus={() => setClientFocus(true)}
                    // A pick is a mousedown inside the list, so closing waits a moment for it to land.
                    onBlur={() => window.setTimeout(() => setClientFocus(false), 150)} />
                  {basics.clientId && (
                    <button type="button" aria-label="Clear the client" onClick={() => setB({ clientName: '', clientId: null })}
                      className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"><X className="size-4" /></button>
                  )}
                  {money && clientFocus && (clientMatches.length > 0 || (basics.clientName.trim() && !basics.clientId)) && (
                    <div className="absolute z-20 mt-1 w-full overflow-hidden rounded-md border bg-popover text-sm shadow-md">
                      {clientMatches.map((c) => (
                        <button key={c.id} type="button" onClick={() => setB({ clientId: c.id, clientName: c.name })}
                          className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-muted">
                          <UserIcon className="size-3.5 text-muted-foreground" /> {c.name}
                          <span className="ml-auto text-xs text-muted-foreground">your client</span>
                        </button>
                      ))}
                      {!exactClient && basics.clientName.trim() && (
                        <div className="flex items-center gap-2 border-t px-3 py-2 text-xs text-muted-foreground">
                          <Plus className="size-3.5" /> “{basics.clientName.trim()}” will be added as a new client
                        </div>
                      )}
                    </div>
                  )}
                </div>,
                { title: 'Client', text: 'Who the building is for and who pays you. Pick one of your clients, or type a new name: it is saved as a client, so billing never asks again.' },
                basics.clientId ? 'One of your clients' : undefined)}
              {field('location', 'Location',
                <div className="relative">
                  <MapPin className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground/70" />
                  <Input value={basics.location} onChange={(e) => setB({ location: e.target.value })} placeholder="e.g. Kakkanad, Kochi" className="h-10 pl-9" />
                </div>)}
            </div>
            <div className="grid gap-4 sm:grid-cols-3">
              {field('type', 'Type',
                <Select value={basics.type} onValueChange={(v) => setB({ type: v as ProjectType })}>
                  <SelectTrigger className="h-10"><SelectValue placeholder="Choose" /></SelectTrigger>
                  <SelectContent>{PROJECT_TYPES.map((t) => <SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>)}</SelectContent>
                </Select>)}
              {field('area', 'Built-up area',
                <div className="relative">
                  <Input value={basics.area} onChange={(e) => setB({ area: e.target.value })} inputMode="decimal" placeholder="e.g. 12,800"
                    aria-invalid={!!errors.area} className={cn('h-10 pr-12', errors.area && 'border-destructive')} />
                  <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-xs text-muted-foreground">sq ft</span>
                </div>,
                { title: 'Built-up area', text: 'The floor area you build, all floors together. It gives the cost per sq ft every owner asks for.' })}
              {field('floors', 'Floors',
                <Input value={basics.floors} onChange={(e) => setB({ floors: e.target.value })} inputMode="numeric" placeholder="e.g. 2"
                  aria-invalid={!!errors.floors} className={cn('h-10', errors.floors && 'border-destructive')} />,
                { title: 'Floors', text: 'Ground floor counts as 1: G+1 is 2 floors.' })}
            </div>
            <div className="grid gap-4 sm:grid-cols-[1fr_2fr]">
              {field('code', 'Short code',
                <div className="relative">
                  <Hash className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground/70" />
                  <Input value={basics.code} onChange={(e) => setB({ code: e.target.value, codeTouched: true })} placeholder="e.g. RGV-001" className="h-10 pl-9" />
                </div>,
                { title: 'Short code', text: 'A short tag on reports, bills and lists. It follows the name; change it if you have your own.' })}
              {field('notes', 'Notes',
                <Input value={basics.notes} onChange={(e) => setB({ notes: e.target.value })} placeholder="Anything worth knowing" className="h-10" />)}
            </div>
          </div>
        )}

        {step === 1 && (
          money ? (
            <div className="grid gap-4">
              <div className="grid gap-4 sm:grid-cols-2">
                {field('value', 'Contract value', input('value', 'e.g. 82,06,050', '₹'),
                  { title: 'Contract value', text: 'What the client pays for the whole work, before GST. If you import the BOQ, its total is shown next to it.' },
                  num(terms.value) ? rupees(num(terms.value) as number) : undefined)}
                {field('type', 'Contract type',
                  <Select value={terms.type} onValueChange={(v) => setT({ type: v as ContractType })}>
                    <SelectTrigger className="h-10"><SelectValue placeholder="Choose" /></SelectTrigger>
                    <SelectContent>{CONTRACT_TYPES.map((t) => <SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>)}</SelectContent>
                  </Select>, undefined, CONTRACT_TYPES.find((t) => t.value === terms.type)?.note)}
              </div>
              <div className="grid gap-4 sm:grid-cols-3">
                {field('start', 'Work starts', <DatePicker value={terms.start} onChange={(v) => setT({ start: v })} />)}
                {field('finish', 'Handover', <DatePicker value={terms.finish} onChange={(v) => setT({ finish: v })} min={terms.start || undefined} />,
                  { title: 'Handover', text: 'When the contract says the building is handed over. Delay is counted from this date.' })}
                {field('payDays', 'Client pays in', input('payDays', 'e.g. 30', 'days'),
                  { title: 'Client pays in', text: 'Days the client takes to pay an RA bill. Cash flow expects the money then, and the bill shows overdue after it.' })}
              </div>
              <div className="grid gap-4 sm:grid-cols-3">
                {field('retention', 'Retention', input('retention', 'e.g. 5', '%'),
                  { title: 'Retention', text: 'The % the client keeps back from every bill, paid after the defect period.' })}
                {field('advance', 'Mobilisation advance', input('advance', 'e.g. 5,00,000', '₹'),
                  { title: 'Mobilisation advance', text: 'Money the client pays at the start, taken back from the bills.' })}
                {field('recovery', 'Advance taken back', input('recovery', 'e.g. 10', '% a bill'))}
              </div>
              <div className="grid gap-4 sm:grid-cols-3">
                {field('gst', 'GST on bills', input('gst', 'e.g. 18', '%'))}
                {field('tds', 'TDS the client cuts', input('tds', 'e.g. 2', '%'),
                  { title: 'TDS', text: 'Tax the client deducts from each bill and pays to the tax department for you.' })}
                {field('dlp', 'Defect period', input('dlp', 'e.g. 12', 'months'))}
              </div>
              <div className="grid gap-4 rounded-lg border bg-muted/30 p-3 sm:grid-cols-3">
                {field('ldWeek', 'Delay penalty', input('ldWeek', 'e.g. 0.5', '% a week'),
                  { title: 'Delay penalty (LD)', text: 'What the client may cut for each week of delay past handover, as a % of the contract value.', example: '0.5% a week on ₹82 L: ₹41,000 a week' })}
                {field('ldCap', 'Penalty cap', input('ldCap', 'e.g. 5', '%'), { title: 'Penalty cap', text: 'The most the penalty can reach, as a % of the contract value.' })}
                {field('escalation', 'Price escalation',
                  <label className="flex h-10 items-center gap-2 text-sm">
                    <input type="checkbox" checked={terms.escalation} onChange={(e) => setT({ escalation: e.target.checked })} className="size-4" />
                    The client pays price rises
                  </label>,
                  { title: 'Escalation', text: 'When steel, cement or wages go up beyond what the contract says, the client pays the difference. Claim it as a variation.' })}
                {terms.escalation && (
                  <div className="sm:col-span-3">
                    {field('escalationTerms', 'Escalation terms',
                      <Input value={terms.escalationTerms} onChange={(e) => setT({ escalationTerms: e.target.value })} placeholder="e.g. Steel and cement above 5% of the base month" className="h-10" />)}
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
              Contract terms are for the owner, an admin or accounts. They can add them on the project's Client billing page.
              <div className="mt-3 grid gap-4 sm:grid-cols-2">
                {field('start', 'Work starts', <DatePicker value={terms.start} onChange={(v) => setT({ start: v })} />)}
                {field('finish', 'Handover', <DatePicker value={terms.finish} onChange={(v) => setT({ finish: v })} min={terms.start || undefined} />)}
              </div>
            </div>
          )
        )}

        {step === 2 && (
          <div className="grid gap-4">
            {field('sites', 'Sites',
              <textarea value={sitesText} onChange={(e) => { setSitesText(e.target.value); setErrors({}) }} rows={2}
                placeholder="e.g. Villa 1-4   or   Tower A, Tower B"
                className="flex min-h-[56px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-xs focus-visible:outline-hidden focus-visible:ring-1 focus-visible:ring-ring" />,
              { title: 'Sites', text: 'The places on the project that report separately: each villa, tower or block. "Villa 1-4" adds Villa 1, 2, 3 and 4.' },
              sites.names.length ? undefined : 'One per line or comma. Leave empty to add later.')}
            {sites.names.length > 0 && (
              <div className="flex flex-wrap gap-1.5" aria-label="Sites to add">
                {sites.names.map((s) => (
                  <span key={sameSiteName(s)} className="inline-flex items-center gap-1 rounded-md bg-muted px-2 py-1 text-xs font-medium">
                    <MapPin className="size-3" aria-hidden /> {s}
                  </span>
                ))}
                <span className="self-center text-xs text-muted-foreground">{sites.names.length} site{sites.names.length > 1 ? 's' : ''}</span>
              </div>
            )}
            <div className="grid gap-4 sm:grid-cols-2">
              {field('manager', 'Project manager',
                <PersonSelect people={people} value={manager} onChange={setManager} loading={users.isLoading} failed={users.isError} />,
                { title: 'Project manager', text: 'Runs the project: BOQ, orders, the team. Gets the daily report.' })}
              {field('reporter', 'Site engineer (reports from site)',
                <PersonSelect people={people} value={reporter} onChange={setReporter} loading={users.isLoading} failed={users.isError} />,
                { title: 'Who reports from site', text: 'The person who sends the day\'s work, labour and deliveries on WhatsApp. Without one, nobody reports and the daily report stays empty.' },
                reporter ? undefined : 'Not on the team yet? Add them on the Team page, then here.')}
            </div>
          </div>
        )}

        {step === 3 && (
          <div className="grid gap-3">
            {([
              { key: 'import', icon: FileSpreadsheet, title: 'Import the estimate Excel', text: 'Right after creating, the BOQ page opens on the import. Sections, lines, rates and materials come in; you check them before anything is saved.' },
              { key: 'later', icon: PenLine, title: 'Add the BOQ later', text: 'Type it on the BOQ page when you are ready, or import it then.' },
            ] as const).map((o) => (
              <button key={o.key} type="button" onClick={() => setBoq(o.key)}
                className={cn('flex items-start gap-3 rounded-lg border p-3 text-left transition-colors',
                  boq === o.key ? 'border-primary bg-primary/5' : 'hover:bg-muted/50')}>
                <o.icon className="mt-0.5 size-5 shrink-0 text-muted-foreground" aria-hidden />
                <span className="grid gap-0.5">
                  <span className="text-sm font-medium">{o.title}</span>
                  <span className="text-xs text-muted-foreground">{o.text}</span>
                </span>
                {boq === o.key && <Check className="ml-auto size-4 shrink-0 text-primary" aria-hidden />}
              </button>
            ))}
          </div>
        )}

        {step === 4 && (
          <div className="grid gap-3 text-sm">
            {done.length > 0 ? (
              <ul className="grid gap-1.5" aria-label="What was saved">
                {done.filter((d) => d.label !== '__open__').map((d) => (
                  <li key={d.label} className="flex items-start gap-2">
                    {d.ok ? <Check className="mt-0.5 size-4 text-emerald-600" aria-hidden /> : <AlertCircle className="mt-0.5 size-4 text-destructive" aria-hidden />}
                    <span>{d.label}{!d.ok && <span className="text-destructive">: {d.error}</span>}</span>
                  </li>
                ))}
                {creating && <li className="flex items-center gap-2 text-muted-foreground"><Loader2 className="size-4 animate-spin" /> Saving…</li>}
              </ul>
            ) : (
              <dl className="grid gap-2 rounded-lg border p-3">
                <Row label="Project" onEdit={() => setStep(0)}>
                  <span className="font-medium">{basics.name.trim()}</span>
                  {basics.code && <span className="text-muted-foreground"> · {basics.code}</span>}
                  {basics.type && <span className="text-muted-foreground"> · {PROJECT_TYPES.find((t) => t.value === basics.type)?.label}</span>}
                  {(basics.area || basics.floors) && (
                    <span className="text-muted-foreground"> · {[basics.area && `${(num(basics.area) ?? 0).toLocaleString('en-IN')} sq ft`, basics.floors && `${basics.floors} floor${basics.floors === '1' ? '' : 's'}`].filter(Boolean).join(', ')}</span>
                  )}
                </Row>
                <Row label="Client" onEdit={() => setStep(0)}>
                  {basics.clientName.trim() ? <>{basics.clientName.trim()} <span className="text-muted-foreground">{basics.clientId ? '(your client)' : money ? '(new client)' : ''}</span></> : <Missing />}
                </Row>
                <Row label="Contract" onEdit={() => setStep(1)}>
                  {!money ? <span className="text-muted-foreground">Set by the owner or accounts</span>
                    : terms.value ? <>{rupees(num(terms.value) as number)}{terms.type && ` · ${CONTRACT_TYPES.find((t) => t.value === terms.type)?.label}`}{terms.payDays && ` · paid in ${terms.payDays} days`}{terms.retention && ` · ${terms.retention}% retention`}{terms.ldWeek && ` · penalty ${terms.ldWeek}% a week`}</> : <Missing />}
                </Row>
                <Row label="Dates" onEdit={() => setStep(1)}>
                  {datesSaid ? `${showDay(terms.start)} to ${showDay(terms.finish)}` : <Missing />}
                </Row>
                <Row label="Sites" onEdit={() => setStep(2)}>{sites.names.length ? sites.names.join(', ') : <Missing />}</Row>
                <Row label="People" onEdit={() => setStep(2)}>
                  {manager || reporter ? [manager && `PM ${personName(people, manager)}`, reporter && `site engineer ${personName(people, reporter)}`].filter(Boolean).join(', ') : <Missing />}
                </Row>
                <Row label="BOQ" onEdit={() => setStep(3)}>{boq === 'import' ? 'Import the Excel next' : 'Later'}</Row>
              </dl>
            )}
            {done.length === 0 && (
              <p className="flex items-start gap-2 rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
                <Building2 className="mt-0.5 size-4 shrink-0" aria-hidden />
                {reporting
                  ? `Daily report: like your other projects, the day closes at ${formatClock(reporting.reportingCutoffTime)} and the report goes on WhatsApp by ${formatClock(reporting.dprSendDeadline ?? '21:00')} (${reporting.reportingTimezone}). Change it on the project page.`
                  : 'Daily report: the day closes at 6:00 pm and the report goes on WhatsApp by 9:00 pm. Change it on the project page.'}
              </p>
            )}
            {failedOpen && (
              <p className="text-xs text-muted-foreground">The project is made. What did not save can be added on the project's page.</p>
            )}
          </div>
        )}

        <div className="flex items-center gap-2 border-t pt-3">
          {step > 0 && !creating && !failedOpen && (
            <Button type="button" variant="ghost" onClick={back} className="gap-1"><ChevronLeft className="size-4" /> Back</Button>
          )}
          <span className="ml-auto" />
          {failedOpen ? (
            <Button type="button" onClick={() => finish(String(failedOpen.error))}>Open the project</Button>
          ) : step < 4 ? (
            <>
              {step > 0 && <Button type="button" variant="outline" onClick={() => setStep((s) => (s + 1) as Step)}>Skip</Button>}
              <Button type="button" onClick={next} disabled={step === 0 && !basics.name.trim()} className="gap-1">Next <ChevronRight className="size-4" /></Button>
            </>
          ) : (
            <Button type="button" onClick={create} disabled={creating || !basics.name.trim()} className="gap-1.5">
              {creating ? <Loader2 className="size-4 animate-spin" /> : <Check className="size-4" />} Create project
            </Button>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}

function Row({ label, onEdit, children }: { label: string; onEdit: () => void; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[88px_1fr_auto] items-baseline gap-2">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd>{children}</dd>
      <button type="button" onClick={onEdit} className="text-xs text-primary-ink hover:underline">Change</button>
    </div>
  )
}

const DAY = new Intl.DateTimeFormat('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })

/** "2026-11-16" as "16 Nov 2026"; a dash when not set. */
function showDay(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso)
  return m ? DAY.format(new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]))) : '—'
}

function Missing() {
  return <span className="inline-flex items-center gap-1 text-muted-foreground"><CircleDashed className="size-3.5" aria-hidden /> Later</span>
}

function personName(people: User[], id: string): string {
  return people.find((p) => p.id === id)?.full_name ?? 'someone'
}

function PersonSelect({ people, value, onChange, loading, failed }: {
  people: User[]; value: string; onChange: (v: string) => void; loading: boolean; failed: boolean
}) {
  if (loading) return <div className="flex h-10 items-center gap-2 text-xs text-muted-foreground"><Loader2 className="size-3.5 animate-spin" /> Loading the team…</div>
  if (failed || people.length === 0) return <div className="flex h-10 items-center text-xs text-muted-foreground">Add people on the Team page first</div>
  return (
    <Select value={value || 'none'} onValueChange={(v) => onChange(v === 'none' ? '' : v)}>
      <SelectTrigger className="h-10"><SelectValue placeholder="Choose" /></SelectTrigger>
      <SelectContent>
        <SelectItem value="none">Nobody yet</SelectItem>
        {people.map((u) => <SelectItem key={u.id} value={u.id}>{u.full_name}</SelectItem>)}
      </SelectContent>
    </Select>
  )
}
