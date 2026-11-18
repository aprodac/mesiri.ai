import * as React from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowRight, BadgeIndianRupee, ClipboardCheck, FileText, Handshake, HandCoins, Lock, MoreHorizontal, Plus, Ruler, Scale, Send, ShieldCheck, Unlock, Users, Wallet } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Callout, EmptyState, KpiStrip, SearchBox, Segmented, type KpiItem } from '@/components/page/page-kit'
import { BarKey, MoneyBar, StateChip, SubcontractHeader, TradeTile } from '@/components/subcontracts/look'
import { ValueStrip } from '@/components/subcontracts/value-strip'
import { WorkOrderDialog } from '@/components/subcontracts/dialogs'
import { PayVendorDialog } from '@/components/vendors/vendor-dialogs'
import { TriangleAlert } from 'lucide-react'
import { useAuth } from '@/lib/AuthContext'
import { useScope } from '@/lib/ScopeContext'
import { useReadOnly } from '@/lib/trial'
import { usePageTitle } from '@/lib/page-title'
import { useUrlState } from '@/lib/url-state'
import { appNow } from '@/lib/clock'
import { localIsoDate } from '@/lib/site-day'
import { mayManageMoney, rupees } from '@/lib/expenses'
import { fetchPayables, vendorUrl } from '@/lib/vendors'
import { fetchWorkOrders, mayGiveWork, n, woUrl, type WorkOrder } from '@/lib/subcontracts'
import {
  NO_MONEY, STATE_LOOK, STATE_ORDER, addSplits, jobTrade, jobView, jobWords, lastMeasured, moneySplit, ratesByWork, retentionDay, shortDay, tradeLook, worst,
  type JobState, type JobView, type MoneySplit,
} from '@/lib/subcontract-look'
import { cn } from '@/lib/utils'

// UX-64 (18 Nov 2026): Subcontract › Subcontractors, every outside team as it needs you. Figures that filter (teams
// working, work given, done, done but not billed, payable now, retention), each team's worst job state, trade, the
// money bar and the one next step; a side panel with their jobs, record and rates; and Rates by work (the same work
// across teams, cheapest first). Everything is read from GET /subcontracts/work-orders (and payables for teams with
// no work order); no figure is stored.

type View = 'teams' | 'rates'
type Filter = 'all' | 'unbilled' | 'pay' | 'retention' | JobState

interface Job { w: WorkOrder; view: JobView }
interface Team {
  id: string
  name: string
  jobs: Job[]
  state: JobState
  split: MoneySplit
  payable: number
  held: number
  advance: number
  toCheck: number
  projects: string[]
  trade: ReturnType<typeof tradeLook>
  last: string | null
  bills: number
  passedFirst: number
  caught: number
}

function buildTeams(wos: WorkOrder[], extra: { id: string; name: string }[], today: string): Team[] {
  const by = new Map<string, Team>()
  for (const w of wos) {
    if (w.status === 'cancelled') continue
    const t = by.get(w.vendor_id) ?? { id: w.vendor_id, name: w.vendor_name, jobs: [], state: 'closed', split: NO_MONEY, payable: 0, held: 0, advance: 0, toCheck: 0, projects: [], trade: tradeLook(''), last: null, bills: 0, passedFirst: 0, caught: 0 }
    t.jobs.push({ w, view: jobView(w, today) })
    t.split = addSplits(t.split, moneySplit(w.totals))
    t.payable += n(w.totals.payable_now)
    t.held += n(w.totals.retention_held)
    t.advance += n(w.totals.advance_left)
    t.toCheck += w.totals.to_check
    if (!t.projects.includes(w.project_name)) t.projects.push(w.project_name)
    const last = lastMeasured(w)
    if (last && (!t.last || last > t.last)) t.last = last
    for (const b of w.bills ?? []) {
      if (b.check_status === 'rejected' && !b.flags.length) continue
      t.bills += 1
      if (b.check_status === 'passed') t.passedFirst += 1
      if (b.check_status === 'rejected') t.caught += n(b.caught)
    }
    by.set(w.vendor_id, t)
  }
  for (const v of extra) if (!by.has(v.id)) by.set(v.id, { id: v.id, name: v.name, jobs: [], state: 'closed', split: NO_MONEY, payable: 0, held: 0, advance: 0, toCheck: 0, projects: [], trade: tradeLook(v.name), last: null, bills: 0, passedFirst: 0, caught: 0 })
  return [...by.values()].map((t) => {
    t.state = worst(t.jobs.map((j) => j.view.state))
    const biggest = [...t.jobs].sort((a, b) => n(b.w.totals.value) - n(a.w.totals.value))[0]
    t.trade = biggest ? jobTrade(biggest.w) : tradeLook(t.name)
    t.jobs.sort((a, b) => STATE_ORDER.indexOf(a.view.state) - STATE_ORDER.indexOf(b.view.state))
    return t
  }).sort((a, b) => STATE_ORDER.indexOf(a.state) - STATE_ORDER.indexOf(b.state) || b.payable - a.payable || b.split.value - a.split.value)
}

export default function SubcontractorsPage() {
  usePageTitle('Subcontractors')
  const navigate = useNavigate()
  const readOnly = useReadOnly()
  const { me } = useAuth()
  const office = mayGiveWork(me?.role) && !readOnly
  const pays = mayManageMoney(me?.role) && !readOnly
  // SCP-03: with a project picked, the teams working on it and their figures there.
  const { scope } = useScope()
  const projectId = scope.mode === 'portfolio' ? '' : scope.projectId
  const [view, setView] = useUrlState<View>('view', 'teams')
  const [filter, setFilter] = useUrlState<Filter>('show', 'all')
  const [q, setQ] = useUrlState<string>('q', '')
  const [open, setOpen] = useUrlState<string>('team', '')
  const [creating, setCreating] = React.useState<string | null>(null)
  const [paying, setPaying] = React.useState<{ id: string; name: string } | null>(null)

  const wos = useQuery({ queryKey: ['subcontracts', 'list', projectId], queryFn: () => fetchWorkOrders(projectId ? { project_id: projectId } : {}) })
  const pay = useQuery({ queryKey: ['finance', 'payables', 'sub', projectId], queryFn: () => fetchPayables({ include_settled: true, ...(projectId ? { project_id: projectId } : {}) }), retry: false })
  const money = !!wos.data?.with_money
  const today = localIsoDate(appNow())
  const teams = React.useMemo(() => buildTeams(wos.data?.work_orders ?? [],
    (pay.data?.vendors ?? []).filter((v) => v.kind === 'subcontractor').map((v) => ({ id: v.id, name: v.name })), today), [wos.data, pay.data, today])

  const working = teams.filter((t) => t.jobs.some((j) => j.w.status === 'issued'))
  const total = teams.reduce((s, t) => addSplits(s, t.split), NO_MONEY)
  const payable = teams.reduce((s, t) => s + t.payable, 0)
  const held = teams.reduce((s, t) => s + t.held, 0)
  const due = teams.filter((t) => t.jobs.some((j) => j.view.state === 'retention'))
  const matches = (t: Team) => filter === 'all' ? true
    : filter === 'unbilled' ? t.split.unbilled > 0
      : filter === 'pay' ? t.payable > 0
        : filter === 'retention' ? due.includes(t)
          : t.jobs.some((j) => j.view.state === filter)
  const needle = q.trim().toLowerCase()
  const shown = teams.filter(matches).filter((t) => !needle || [t.name, t.trade.label, ...t.projects, ...t.jobs.map((j) => jobWords(j.w))].join(' ').toLowerCase().includes(needle))
  const picked = teams.find((t) => t.id === open) ?? null

  const toggle = (f: Filter) => setFilter(filter === f ? 'all' : f)
  const tiles: KpiItem[] = [
    { key: 'teams', label: 'Teams working', value: working.length, icon: Users, hint: `${teams.length} in all`, pressed: filter === 'all', onClick: () => setFilter('all') },
    ...(money ? [
      { key: 'given', label: 'Work given', value: rupees(total.value), kind: 'money' as const, hint: `${Math.round(total.value ? total.done / total.value * 100 : 0)}% done` , share: total.value ? total.done / total.value : undefined },
      { key: 'unbilled', label: 'Done, not billed', value: rupees(total.unbilled), icon: Ruler, tone: total.unbilled > 0 ? ('attention' as const) : ('default' as const), hint: 'you will owe this', pressed: filter === 'unbilled', onClick: () => toggle('unbilled') },
      { key: 'pay', label: 'Payable now', value: rupees(payable), icon: HandCoins, tone: payable > 0 ? ('info' as const) : ('default' as const), pressed: filter === 'pay', onClick: () => toggle('pay') },
      { key: 'ret', label: 'Retention held', value: rupees(held), icon: Lock, hint: due.length ? `${due.length} due to release` : 'none due', tone: due.length ? ('attention' as const) : ('default' as const), pressed: filter === 'retention', onClick: () => toggle('retention') },
    ] : []),
  ].map((k) => ({ ...k, loading: wos.isLoading }))

  const stateCounts = STATE_ORDER.filter((s) => !['closed', 'done', 'track'].includes(s))
    .map((s) => ({ s, count: teams.filter((t) => t.jobs.some((j) => j.view.state === s)).length })).filter((x) => x.count > 0)

  return (
    <div className="mx-auto flex w-full flex-col gap-4 pb-24 sm:px-2 md:pb-8">
      <SubcontractHeader icon={Handshake} title="Subcontractors">
        {office && <Button className="gap-1.5 font-semibold" data-guide="subs.orders" onClick={() => setCreating('')}><Plus className="size-4" />New work order</Button>}
      </SubcontractHeader>

      {money && <ValueStrip projectId={projectId || undefined} compact />}
      <KpiStrip guide="subs.tiles" stats={tiles} />

      <div className="flex flex-wrap items-center justify-between gap-2">
        <Segmented label="View" value={view} onChange={setView} guide="subs.view" options={[{ value: 'teams', label: 'Teams', count: teams.length }, ...(money ? [{ value: 'rates' as const, label: 'Rates by work' }] : [])]} />
        {view === 'teams' && <SearchBox value={q} onChange={setQ} placeholder="Team, trade, project" label="Search subcontractors" className="w-full sm:w-[240px]" />}
      </div>

      {wos.isError ? (
        <Callout tone="draft" icon={TriangleAlert} action={<Button variant="outline" size="sm" className="bg-background" onClick={() => wos.refetch()}>Try again</Button>}>The subcontractors could not be loaded.</Callout>
      ) : wos.isLoading ? (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-52 rounded-xl" />)}</div>
      ) : view === 'rates' && money ? (
        <RatesView wos={wos.data?.work_orders ?? []} />
      ) : !teams.length ? (
        <div data-guide="subs.empty"><EmptyState icon={Handshake} title="No subcontractor yet" about="A work order adds one." className="bg-card" action={office ? <Button size="sm" className="gap-1.5" onClick={() => setCreating('')}><Plus className="size-4" />New work order</Button> : undefined} /></div>
      ) : (
        <>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap gap-1.5" role="group" aria-label="Show" data-guide="subs.filters">
              {stateCounts.map(({ s, count }) => (
                <button key={s} type="button" aria-pressed={filter === s} onClick={() => toggle(s)}
                  className={cn('inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold shadow-xs', filter === s ? 'border-foreground bg-foreground text-background' : 'bg-card hover:bg-muted')}>
                  <span className={cn('size-2 rounded-full', STATE_LOOK[s].dot)} />{STATE_LOOK[s].label}<span className="tabular-nums opacity-70">{count}</span>
                </button>
              ))}
              {filter !== 'all' && <button type="button" className="px-2 text-xs font-medium text-muted-foreground underline-offset-2 hover:underline" onClick={() => setFilter('all')}>Show all</button>}
            </div>
            {money && <BarKey />}
          </div>
          {shown.length === 0 ? (
            <EmptyState icon={Handshake} title="No team matches" className="bg-card" action={<Button variant="outline" size="sm" onClick={() => { setFilter('all'); setQ('') }}>Show all</Button>} />
          ) : (
            <ul className="grid gap-3 md:grid-cols-2 xl:grid-cols-3" data-guide="subs.list">
              {shown.map((t) => (
                <TeamCard key={t.id} team={t} money={money} office={office} pays={pays} onOpen={() => setOpen(t.id)} onPay={() => setPaying({ id: t.id, name: t.name })} onNew={() => setCreating(t.id)} />
              ))}
            </ul>
          )}
        </>
      )}

      <TeamSheet team={picked} money={money} today={today} onClose={() => setOpen('')} onNew={office ? () => setCreating(picked?.id ?? '') : undefined} />
      <WorkOrderDialog open={creating !== null} onOpenChange={(o) => !o && setCreating(null)}
        preset={{ project_id: projectId || undefined, site_id: scope.mode === 'site' ? scope.siteId : undefined, ...(creating ? { vendor_id: creating, vendor_name: teams.find((t) => t.id === creating)?.name } : {}) }}
        onSaved={(wo) => navigate(woUrl(wo.id))} />
      {paying && <PayVendorDialog open onOpenChange={(o) => !o && setPaying(null)} vendor={paying} projectId={projectId || null} />}
    </div>
  )
}

/** The one thing to do next for a team, worst first. */
function nextStep(t: Team, pays: boolean, office: boolean): { label: string; icon: React.ComponentType<{ className?: string }>; to?: string; pay?: boolean } | null {
  const job = (s: JobState) => t.jobs.find((j) => j.view.state === s)?.w
  if (t.toCheck > 0) return { label: `Check ${t.toCheck === 1 ? 'bill' : `${t.toCheck} bills`}`, icon: ClipboardCheck, to: '/subcontract/bills' }
  if (pays && t.payable > 0) return { label: `Pay ${rupees(t.payable)}`, icon: HandCoins, pay: true }
  const ret = job('retention')
  if (pays && ret) return { label: 'Release retention', icon: Unlock, to: woUrl(ret.id) }
  const draft = job('draft')
  if (office && draft) return { label: 'Issue work order', icon: Send, to: woUrl(draft.id) }
  const live = job('late') ?? job('idle') ?? job('track')
  if (live) return { label: 'Measure', icon: Ruler, to: woUrl(live.id, 'measured') }
  return null
}

function TeamCard({ team: t, money, office, pays, onOpen, onPay, onNew }: { team: Team; money: boolean; office: boolean; pays: boolean; onOpen: () => void; onPay: () => void; onNew: () => void }) {
  const navigate = useNavigate()
  const step = nextStep(t, pays, office)
  const top = t.jobs[0]
  const live = t.jobs.filter((j) => j.w.status === 'issued' || j.w.status === 'draft').length
  const done = t.split.value ? Math.round(t.split.done / t.split.value * 100) : 0
  return (
    <li className={cn('relative flex flex-col gap-3 overflow-hidden rounded-xl border bg-card p-4 shadow-xs before:absolute before:inset-y-0 before:left-0 before:w-1', STATE_LOOK[t.state].edge)}>
      <button type="button" onClick={onOpen} className="flex items-start gap-3 text-left" aria-label={`Open ${t.name}`}>
        <TradeTile look={t.trade} />
        <span className="min-w-0 flex-1">
          <span className="block truncate font-semibold">{t.name}</span>
          <span className="block truncate text-xs text-muted-foreground">{t.trade.label} · {live ? `${live} live ${live === 1 ? 'job' : 'jobs'}` : 'no live job'}</span>
        </span>
      </button>
      {t.jobs.length > 0 && <StateChip className="-mt-1 w-fit" state={t.state} note={top?.view.state === t.state ? top.view.note : null} />}
      {t.projects.length > 0 && (
        <div className="flex flex-wrap gap-1">{t.projects.map((p) => <span key={p} className="max-w-full truncate rounded-full bg-muted px-2 py-0.5 text-xs">{p}</span>)}</div>
      )}
      {money && t.split.value > 0 && (
        <div className="flex flex-col gap-1.5">
          <MoneyBar split={t.split} />
          <div className="flex justify-between text-xs text-muted-foreground tabular-nums">
            <span><span className="font-semibold text-foreground">{done}%</span> done of {rupees(t.split.value)}</span>
            {t.split.unbilled > 0 && <span className="font-medium text-amber-700 dark:text-amber-300">{rupees(t.split.unbilled)} not billed</span>}
          </div>
        </div>
      )}
      {!money && t.jobs.length > 0 && <span className="text-xs text-muted-foreground">{t.jobs.map((j) => `${j.w.ref} ${j.w.totals.progress_pct}% done`).join(' · ')}</span>}
      {money && (t.payable > 0 || t.held > 0 || t.advance > 0) && (
        <dl className="grid grid-cols-3 gap-2 rounded-lg bg-muted/50 px-3 py-2 text-xs" data-guide="subs.money">
          <div><dt className="text-muted-foreground">Payable</dt><dd className={cn('font-semibold tabular-nums', t.payable > 0 && 'text-info')}>{rupees(t.payable)}</dd></div>
          <div><dt className="text-muted-foreground">Retention</dt><dd className="font-semibold tabular-nums">{rupees(t.held)}</dd></div>
          <div><dt className="text-muted-foreground">Advance left</dt><dd className="font-semibold tabular-nums">{rupees(t.advance)}</dd></div>
        </dl>
      )}
      <div className="mt-auto flex items-center gap-2" data-guide="subs.actions">
        {step ? (
          <Button size="sm" className="h-9 flex-1 gap-1.5 sm:h-8" onClick={() => (step.pay ? onPay() : step.to && navigate(step.to))}><step.icon className="size-4" />{step.label}</Button>
        ) : (
          <Button size="sm" variant="outline" className="h-9 flex-1 sm:h-8" onClick={onOpen}>Open</Button>
        )}
        <DropdownMenu>
          <DropdownMenuTrigger asChild><Button size="icon" variant="outline" className="size-9 sm:size-8" aria-label={`More for ${t.name}`}><MoreHorizontal className="size-4" /></Button></DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-52">
            <DropdownMenuItem onClick={onOpen}><Handshake className="size-4" /> Their record</DropdownMenuItem>
            <DropdownMenuItem onClick={() => navigate(`/subcontract/work-orders?vendor=${t.id}&tab=all`)}><FileText className="size-4" /> Work orders</DropdownMenuItem>
            {money && <DropdownMenuItem onClick={() => navigate(`/subcontract/statement/${t.id}`)}><FileText className="size-4" /> Statement</DropdownMenuItem>}
            <DropdownMenuItem onClick={() => navigate(vendorUrl(t.id))}><Wallet className="size-4" /> Account</DropdownMenuItem>
            {office && <DropdownMenuItem onClick={onNew}><Plus className="size-4" /> New work order</DropdownMenuItem>}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </li>
  )
}

/** One team: their jobs, record (bills passed first time, money caught), rates and money. */
function TeamSheet({ team: t, money, today, onClose, onNew }: { team: Team | null; money: boolean; today: string; onClose: () => void; onNew?: () => void }) {
  const rates = t ? ratesByWork(t.jobs.map((j) => j.w)) : []
  const onTime = t ? t.jobs.filter((j) => j.w.end_date && (j.w.status !== 'issued' || j.w.end_date >= today)) : []
  const dated = t ? t.jobs.filter((j) => j.w.end_date && j.w.status !== 'draft') : []
  return (
    <Sheet open={!!t} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="right" className="w-full gap-0 overflow-y-auto p-0 sm:max-w-[480px]">
        {t && (
          <>
            <SheetHeader className="flex-row items-center gap-3 border-b p-4 pr-12">
              <TradeTile look={t.trade} size="lg" />
              <div className="min-w-0">
                <SheetTitle className="truncate">{t.name}</SheetTitle>
                <SheetDescription>{t.trade.label}{t.last ? ` · last measured ${shortDay(t.last)}` : ''}</SheetDescription>
              </div>
            </SheetHeader>
            <div className="flex flex-col gap-5 p-4">
              <dl className="grid grid-cols-3 gap-2 text-center">
                <Stat icon={ShieldCheck} label="Bills passed first time" value={t.bills ? `${t.passedFirst}/${t.bills}` : '—'} good={t.bills > 0 && t.passedFirst === t.bills} />
                <Stat icon={Scale} label="On time" value={dated.length ? `${onTime.length}/${dated.length}` : '—'} good={dated.length > 0 && onTime.length === dated.length} />
                {money ? <Stat icon={BadgeIndianRupee} label="Over-billing stopped" value={rupees(t.caught)} /> : <Stat icon={Ruler} label="Jobs" value={String(t.jobs.length)} />}
              </dl>
              {money && t.split.value > 0 && (
                <section className="flex flex-col gap-2">
                  <MoneyBar split={t.split} tall />
                  <BarKey />
                  <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
                    {[['Work given', t.split.value], ['Done', t.split.done], ['Billed', t.split.billed], ['Paid', t.split.paid], ['Done, not billed', t.split.unbilled], ['Payable now', t.payable], ['Retention held', t.held], ['Advance left', t.advance]].map(([k, v]) => (
                      <div key={k as string} className="flex justify-between gap-2 border-b border-dashed py-1"><dt className="text-muted-foreground">{k}</dt><dd className="font-medium tabular-nums">{rupees(v as number)}</dd></div>
                    ))}
                  </dl>
                </section>
              )}
              <section className="flex flex-col gap-2">
                <h3 className="text-sm font-semibold">Jobs</h3>
                <ul className="flex flex-col divide-y rounded-xl border">
                  {t.jobs.map(({ w, view }) => (
                    <li key={w.id}>
                      <Link to={woUrl(w.id)} className="flex flex-col gap-1.5 px-3 py-2.5 hover:bg-muted/40">
                        <span className="flex items-center gap-2">
                          <span className="font-semibold tabular-nums">{w.ref}</span>
                          <span className="min-w-0 flex-1 truncate text-sm">{w.title ?? w.lines.map((l) => l.description).join(', ')}</span>
                          <StateChip state={view.state} note={view.note} />
                        </span>
                        {money ? <MoneyBar split={moneySplit(w.totals)} /> : null}
                        <span className="flex justify-between text-xs text-muted-foreground">
                          <span className="truncate">{[w.project_name, w.site_name].filter(Boolean).join(' › ')}</span>
                          <span className="shrink-0 tabular-nums">{w.totals.progress_pct}% done{w.end_date ? ` · due ${shortDay(w.end_date)}` : ''}{w.status === 'completed' && retentionDay(w) ? ` · retention ${shortDay(retentionDay(w)!)}` : ''}</span>
                        </span>
                      </Link>
                    </li>
                  ))}
                  {t.jobs.length === 0 && <li className="px-3 py-6 text-center text-sm text-muted-foreground">No work order yet</li>}
                </ul>
              </section>
              {money && rates.length > 0 && (
                <section className="flex flex-col gap-2">
                  <h3 className="text-sm font-semibold">Their rates</h3>
                  <ul className="flex flex-col divide-y rounded-xl border text-sm">
                    {rates.map((r) => r.offers.map((o) => (
                      <li key={`${r.key}-${o.wo_id}`} className="flex items-center justify-between gap-2 px-3 py-2"><span className="truncate">{r.work}</span><span className="shrink-0 font-semibold tabular-nums">₹{o.rate.toLocaleString('en-IN')} / {r.unit}</span></li>
                    )))}
                  </ul>
                </section>
              )}
              <div className="flex flex-wrap gap-2">
                {onNew && <Button size="sm" className="gap-1.5" onClick={onNew}><Plus className="size-4" />New work order</Button>}
                {money && <Button size="sm" variant="outline" asChild><Link to={`/subcontract/statement/${t.id}`}><FileText className="size-4" />Statement</Link></Button>}
                <Button size="sm" variant="outline" asChild><Link to={vendorUrl(t.id)}>Account<ArrowRight className="size-3.5" /></Link></Button>
              </div>
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  )
}

function Stat({ icon: Icon, label, value, good }: { icon: React.ComponentType<{ className?: string }>; label: string; value: string; good?: boolean }) {
  return (
    <div className="flex flex-col items-center gap-1 rounded-xl border bg-card px-2 py-2.5">
      <Icon className={cn('size-4', good ? 'text-success' : 'text-muted-foreground')} />
      <dd className={cn('text-base font-semibold tabular-nums', good && 'text-success')}>{value}</dd>
      <dt className="text-[11px] leading-tight text-muted-foreground">{label}</dt>
    </div>
  )
}

/** The same work across teams: each team's rate a unit on one line, cheapest first, the gap to the dearest. */
function RatesView({ wos }: { wos: WorkOrder[] }) {
  const rows = ratesByWork(wos)
  if (!rows.length) return <EmptyState icon={Scale} title="No rates yet" about="Rates come from work orders." className="bg-card" />
  return (
    <ul className="grid gap-3 lg:grid-cols-2" data-guide="subs.rates">
      {rows.map((r) => {
        const low = r.offers[0].rate
        const high = r.offers.at(-1)!.rate
        const look = tradeLook(r.work)
        return (
          <li key={r.key} className="flex flex-col gap-2 rounded-xl border bg-card p-4 shadow-xs">
            <div className="flex items-center gap-3">
              <TradeTile look={look} size="sm" />
              <span className="min-w-0 flex-1 truncate font-semibold">{r.work}</span>
              <span className="text-xs text-muted-foreground">per {r.unit}</span>
              {r.offers.length > 1 && high > low && <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-900 dark:bg-amber-950 dark:text-amber-100">{Math.round((high - low) / low * 100)}% spread</span>}
            </div>
            <ul className="flex flex-col gap-1.5">
              {r.offers.map((o, i) => (
                <li key={`${o.vendor_id}-${o.wo_id}`} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1 text-sm">
                  <Link to={woUrl(o.wo_id)} className="truncate hover:underline">{o.vendor} <span className="text-xs text-muted-foreground">{o.ref} · {o.project}</span></Link>
                  <span className={cn('font-semibold tabular-nums', i === 0 && r.offers.length > 1 && 'text-success')}>₹{o.rate.toLocaleString('en-IN')}</span>
                  {r.offers.length > 1 && <span className="col-span-2 block h-1.5 overflow-hidden rounded-full bg-muted">
                    <span className={cn('block h-full rounded-full', i === 0 ? 'bg-success' : 'bg-foreground/40')} style={{ width: `${(o.rate / high) * 100}%` }} />
                  </span>}
                </li>
              ))}
            </ul>
          </li>
        )
      })}
    </ul>
  )
}
