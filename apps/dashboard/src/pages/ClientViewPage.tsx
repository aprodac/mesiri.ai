import * as React from 'react'
import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { CalendarCheck2, Camera, CheckCircle2, Circle, Clock, IndianRupee, Phone } from 'lucide-react'
import { Skeleton } from '@/components/ui/skeleton'
import { billDay, rupees } from '@/lib/billing'
import { fetchClientPage, type ClientPage } from '@/lib/client-view'
import { usePageTitle } from '@/lib/page-title'
import { cn } from '@/lib/utils'

// CV-03: what the client (the house owner) sees from the link the company sent: no login, no sidebar, phone first.
// Read only. The backend decides what is on it (domains/client_view/view.py): progress, milestones, photos from
// approved site reports, submitted and certified bills and money received. Never rates, costs or suppliers.

export default function ClientViewPage() {
  const { token = '' } = useParams()
  const query = useQuery({ queryKey: ['client-page', token], queryFn: () => fetchClientPage(token), retry: false, staleTime: 5 * 60_000 })
  usePageTitle(query.data ? query.data.project.name : 'Your project')

  return (
    <div className="min-h-dvh bg-muted/40 text-foreground">
      <div className="mx-auto flex w-full max-w-2xl flex-col gap-4 px-4 py-5 pb-12">
        {query.isError ? (
          <Gone />
        ) : !query.data ? (
          <>
            <Skeleton className="h-16 w-full" />
            <Skeleton className="h-36 w-full" />
            <Skeleton className="h-56 w-full" />
          </>
        ) : (
          <Page page={query.data} />
        )}
      </div>
    </div>
  )
}

function Gone() {
  return (
    <div className="mt-16 rounded-xl border bg-background p-6 text-center">
      <h1 className="text-lg font-semibold">This link is not valid any more</h1>
      <p className="mt-2 text-sm text-muted-foreground">Ask your builder to send a new one.</p>
    </div>
  )
}

function Page({ page }: { page: ClientPage }) {
  const accent = page.company.brand_color || undefined
  return (
    <>
      <header className="flex items-center gap-3">
        {page.company.logo_url ? (
          <img src={page.company.logo_url} alt="" className="size-12 rounded-lg bg-background object-contain p-1" />
        ) : (
          <span className="inline-flex size-12 items-center justify-center rounded-lg text-lg font-semibold text-white" style={{ background: accent ?? '#15803d' }}>
            {(page.company.name ?? 'M').slice(0, 1)}
          </span>
        )}
        <div className="min-w-0">
          <div className="truncate text-xs text-muted-foreground">{page.company.name}</div>
          <h1 className="truncate text-xl leading-tight font-semibold">{page.project.name}</h1>
          {page.project.client_name && <div className="truncate text-xs text-muted-foreground">For {page.project.client_name}</div>}
        </div>
      </header>
      <Progress page={page} accent={accent} />
      <Schedule page={page} />
      <Photos page={page} />
      <Money page={page} />
      <footer className="pt-2 text-center text-xs text-muted-foreground">
        {page.company.phone && (
          <a href={`tel:${page.company.phone.replace(/\s/g, '')}`} className="mb-2 inline-flex items-center gap-1.5 rounded-full border bg-background px-3 py-1.5 text-sm text-foreground">
            <Phone className="size-4" /> Call {page.company.name ?? 'the builder'}
          </a>
        )}
        <div>Updated {billDay(page.today)} · read only</div>
      </footer>
    </>
  )
}

function Section({ icon: Icon, title, children }: { icon: typeof Clock; title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-xl border bg-background p-4">
      <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold"><Icon className="size-4 text-muted-foreground" /> {title}</h2>
      {children}
    </section>
  )
}

function Progress({ page, accent }: { page: ClientPage; accent?: string }) {
  const p = page.project
  const pct = p.progress ?? 0
  const late = p.slip_days > 0
  return (
    <Section icon={Clock} title="Progress">
      <div className="flex items-end justify-between gap-3">
        <div className="text-3xl font-semibold tabular-nums">{p.progress === null ? '—' : `${pct}%`}</div>
        <div className="text-right text-xs text-muted-foreground">
          {p.contract_finish && <div>Handover planned {billDay(p.contract_finish)}</div>}
          {p.forecast_finish && (
            <div className={cn(late && 'text-amber-700 dark:text-amber-400')}>
              Expected {billDay(p.forecast_finish)}{late ? ` (${p.slip_days} day${p.slip_days === 1 ? '' : 's'} later)` : ''}
            </div>
          )}
        </div>
      </div>
      <div className="mt-3 h-2.5 overflow-hidden rounded-full bg-muted" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
        <div className="h-full rounded-full bg-emerald-600" style={{ width: `${Math.min(pct, 100)}%`, background: accent }} />
      </div>
    </Section>
  )
}

function Schedule({ page }: { page: ClientPage }) {
  if (page.schedule.length === 0) return null
  return (
    <Section icon={CalendarCheck2} title={page.schedule_kind === 'milestones' ? 'Milestones' : 'Work plan'}>
      <ul className="flex flex-col gap-2.5">
        {page.schedule.map((a, i) => (
          <li key={`${a.name}-${i}`} className="flex items-start gap-2.5 text-sm">
            {a.done ? <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-emerald-600" /> : <Circle className="mt-0.5 size-4 shrink-0 text-muted-foreground" />}
            <div className="min-w-0 flex-1">
              <div className={cn('font-medium', a.done && 'text-muted-foreground')}>{a.name}</div>
              <div className="text-xs text-muted-foreground">
                {a.done
                  ? `Done ${billDay(a.actual_end ?? a.end)}`
                  : a.end
                    ? `Planned ${billDay(a.end)}${a.forecast_end && a.forecast_end !== a.end ? ` · expected ${billDay(a.forecast_end)}` : ''}`
                    : 'Date to be set'}
                {!a.done && !a.milestone && a.progress !== null ? ` · ${a.progress}%` : ''}
              </div>
            </div>
          </li>
        ))}
      </ul>
    </Section>
  )
}

function Photos({ page }: { page: ClientPage }) {
  const [open, setOpen] = React.useState<number | null>(null)
  if (page.photos.length === 0) return null
  const shown = open === null ? null : page.photos[open]
  return (
    <Section icon={Camera} title="Photos from site">
      <div className="grid grid-cols-3 gap-1.5">
        {page.photos.map((ph, i) => (
          <button key={ph.url} type="button" onClick={() => setOpen(i)} className="aspect-square overflow-hidden rounded-md bg-muted">
            <img src={ph.url} alt={ph.caption ?? ph.work ?? 'Site photo'} loading="lazy" className="size-full object-cover" />
          </button>
        ))}
      </div>
      {shown && (
        <div className="fixed inset-0 z-50 flex flex-col items-center justify-center bg-black/90 p-4" onClick={() => setOpen(null)} role="dialog" aria-label="Photo">
          <img src={shown.url} alt={shown.caption ?? ''} className="max-h-[80dvh] max-w-full rounded-md object-contain" />
          <div className="mt-3 text-center text-sm text-white">
            {[shown.work, shown.caption].filter(Boolean).join(' · ')}
            <div className="text-xs text-white/70">{billDay(shown.date)}</div>
          </div>
        </div>
      )}
    </Section>
  )
}

function Money({ page }: { page: ClientPage }) {
  if (page.bills.length === 0 && page.payments.length === 0 && !page.project.contract_value) return null
  const t = page.totals
  return (
    <Section icon={IndianRupee} title="Bills and payments">
      <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
        {page.project.contract_value && <Figure label="Contract" value={rupees(page.project.contract_value)} />}
        <Figure label="Billed" value={rupees(t.billed)} />
        <Figure label="Paid" value={rupees(t.received)} />
        <Figure label="Due now" value={rupees(t.due)} strong={Number(t.due) > 0} />
      </dl>
      {Number(t.advance_received) > 0 && <p className="mt-2 text-xs text-muted-foreground">Advance paid {rupees(t.advance_received)}, recovered through the bills.</p>}
      {page.bills.length > 0 && (
        <ul className="mt-4 divide-y rounded-lg border">
          {page.bills.map((b) => (
            <li key={b.ref} className="flex items-center justify-between gap-3 p-3 text-sm">
              <div className="min-w-0">
                <div className="font-medium">{b.ref} <span className="text-xs font-normal text-muted-foreground">· {billDay(b.bill_date)}</span></div>
                <div className="text-xs text-muted-foreground">
                  {b.status === 'certified' ? `Certified${b.certified_on ? ` ${billDay(b.certified_on)}` : ''}` : 'Sent for certification'}
                  {b.retention && Number(b.retention) > 0 ? ` · retention ${rupees(b.retention)}` : ''}
                </div>
              </div>
              <div className="text-right tabular-nums">
                <div className="font-medium">{rupees(b.net)}</div>
                <div className={cn('text-xs', Number(b.left) > 0 ? 'text-amber-700 dark:text-amber-400' : 'text-emerald-700 dark:text-emerald-400')}>
                  {Number(b.left) > 0 ? `${rupees(b.left)} due` : 'Paid'}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
      {page.payments.length > 0 && (
        <>
          <h3 className="mt-4 mb-2 text-xs font-semibold text-muted-foreground">Payments received</h3>
          <ul className="flex flex-col gap-1.5 text-sm">
            {page.payments.map((p, i) => (
              <li key={`${p.received_on}-${i}`} className="flex justify-between gap-3">
                <span className="text-muted-foreground">{billDay(p.received_on)}{p.bill_ref ? ` · ${p.bill_ref}` : p.kind === 'advance' ? ' · advance' : ''}</span>
                <span className="tabular-nums">{rupees(p.amount)}</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </Section>
  )
}

function Figure({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className={cn('tabular-nums font-medium', strong && 'text-amber-700 dark:text-amber-400')}>{value}</dd>
    </div>
  )
}
