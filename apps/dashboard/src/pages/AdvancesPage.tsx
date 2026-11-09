import * as React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { HandCoins, Undo2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { useToast } from '@/components/ui/toast-notification'
import { EmptyState, ModuleTitle, Section, StatStrip } from '@/components/page/page-kit'
import { fetchAccountsApi, fetchWorkersApi } from '@/lib/api'
import { useAuth } from '@/lib/AuthContext'
import { errorWords, useSiteOptions } from '@/lib/equipment'
import { fetchAdvanceBalances, fetchAdvances, fetchLabourTeams, giveAdvance, inr, n, voidAdvance } from '@/lib/labour-pay'
import { MONEY_ROLES } from '@/lib/module-map'
import { useScope } from '@/lib/ScopeContext'
import { usePageTitle } from '@/lib/page-title'
import { useReadOnly } from '@/lib/trial'
import { cn } from '@/lib/utils'

// LW-03 (plan docs/plans/wages-and-labour-plan.md): money given ahead of wages, to a worker or a labour team, out of
// a money account; taken back on the next wage sheet. "Gave Ravi 500 advance" on WhatsApp lands here too.

const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
const day = (v: string) => new Date(`${v}T00:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })

export default function AdvancesPage() {
  usePageTitle('Advances')
  const toast = useToast()
  const qc = useQueryClient()
  const readOnly = useReadOnly()
  const { me } = useAuth()
  const money = (MONEY_ROLES as readonly string[]).includes((me?.role || '').toUpperCase())
  const { scope } = useScope()
  const projectId = scope.mode === 'portfolio' ? null : scope.projectId
  const siteId = scope.mode === 'site' ? scope.siteId : null
  const [giving, setGiving] = React.useState(false)

  const list = useQuery({ queryKey: ['advances', projectId, siteId], queryFn: () => fetchAdvances({ project_id: projectId, site_id: siteId }) })
  const balances = useQuery({ queryKey: ['advances', 'balances', projectId], queryFn: () => fetchAdvanceBalances(projectId), enabled: money, retry: false })
  const undo = useMutation({
    mutationFn: (id: string) => voidAdvance(id, 'Taken back on the dashboard'),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['advances'] }); qc.invalidateQueries({ queryKey: ['home'] }); toast.success('Advance taken back', 'The money is back in its account.') },
    onError: (e) => toast.error('Could not take it back', errorWords(e)),
  })

  const live = (list.data?.items ?? []).filter((a) => !a.voided_at)
  const outstanding = (balances.data?.items ?? []).filter((b) => n(b.outstanding) > 0)

  return (
    <div className="mx-auto flex w-full flex-col gap-4 pb-24 sm:px-2 md:pb-8">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <ModuleTitle icon={HandCoins} title="Advances" />
        {!readOnly && <Button className="gap-1.5 font-semibold" onClick={() => setGiving(true)}><HandCoins className="size-4" /> Give advance</Button>}
      </header>

      {money && balances.data && (
        <StatStrip stats={[
          { label: 'Outstanding', value: inr(balances.data.outstanding), tone: n(balances.data.outstanding) > 0 ? 'warn' : 'good', hint: 'taken back from the next wages' },
          { label: 'People and teams', value: String(outstanding.length) },
          { label: 'Given (shown)', value: inr(live.reduce((a, x) => a + n(x.amount), 0)) },
        ]} />
      )}

      {money && outstanding.length > 0 && (
        <Section title="Still to take back" note="Most first">
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-3">
            {outstanding.map((b) => (
              <div key={b.payee_key} className="flex items-center justify-between gap-3 rounded-xl border border-draft/25 bg-draft-soft/40 px-4 py-3">
                <div className="min-w-0">
                  <p className="truncate font-medium">{b.payee_name}</p>
                  <p className="text-xs text-muted-foreground">{inr(b.given)} given · {inr(b.recovered)} taken back · last {day(b.last_given_on)}</p>
                </div>
                <span className="shrink-0 text-lg font-semibold text-draft tabular-nums">{inr(b.outstanding)}</span>
              </div>
            ))}
          </div>
        </Section>
      )}

      <Section title="Given" note={live.length ? `${live.length}` : undefined}>
        {list.isLoading ? <Skeleton className="h-40 w-full rounded-xl" /> : (list.data?.items ?? []).length === 0 ? (
          <EmptyState icon={HandCoins} title="No advances yet" about="Money given to a worker or a labour team before payday. It comes back off their next wages on its own."
            whatsapp="Gave Ravi 500 advance" action={!readOnly && <Button size="sm" onClick={() => setGiving(true)}>Give advance</Button>} />
        ) : (
          <ul className="divide-y rounded-xl border">
            {(list.data?.items ?? []).map((a) => (
              <li key={a.id} className={cn('flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5 text-sm', a.voided_at && 'opacity-50')}>
                <span className="w-16 shrink-0 text-muted-foreground tabular-nums">{day(a.given_on)}</span>
                <span className="min-w-0 flex-1">
                  <span className="font-medium">{a.payee_name}</span>
                  <span className="block text-xs text-muted-foreground">
                    {[a.site_name ?? a.project_name, a.account_name, a.created_by_name, a.source === 'whatsapp' ? 'WhatsApp' : null, a.note].filter(Boolean).join(' · ')}
                    {a.voided_at && ' · taken back'}
                  </span>
                </span>
                <span className="font-semibold tabular-nums">{inr(a.amount)}</span>
                {!a.voided_at && !readOnly && (
                  <Button variant="ghost" size="icon" className="size-8" title="Take back (money returns to its account)" aria-label="Take back" onClick={() => window.confirm(`Take back ${inr(a.amount)} given to ${a.payee_name}?`) && undo.mutate(a.id)}>
                    <Undo2 className="size-4" />
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}
      </Section>

      {giving && <GiveDialog onClose={() => setGiving(false)} defaultSite={siteId} onGiven={() => { setGiving(false); qc.invalidateQueries({ queryKey: ['advances'] }); qc.invalidateQueries({ queryKey: ['home'] }) }} />}
    </div>
  )
}

function GiveDialog({ onClose, onGiven, defaultSite }: { onClose: () => void; onGiven: () => void; defaultSite: string | null }) {
  const toast = useToast()
  const sites = useSiteOptions()
  const workers = useQuery({ queryKey: ['labour', 'workers', 'active'], queryFn: () => fetchWorkersApi({ status: 'active', limit: 200 }) })
  const teams = useQuery({ queryKey: ['labour', 'teams'], queryFn: fetchLabourTeams })
  const accounts = useQuery({ queryKey: ['finance', 'accounts', 'active'], queryFn: () => fetchAccountsApi() as Promise<{ id: string; name: string; status?: string }[]> })
  const [payee, setPayee] = React.useState('')
  const [name, setName] = React.useState('')
  const [site, setSite] = React.useState(defaultSite ?? '')
  const [amount, setAmount] = React.useState('')
  const [account, setAccount] = React.useState('')
  const [on, setOn] = React.useState(iso(new Date()))
  const [note, setNote] = React.useState('')
  const usable = (accounts.data ?? []).filter((a) => (a.status ?? 'active') === 'active')
  const siteValue = site || sites.data?.[0]?.id || ''
  const give = useMutation({
    mutationFn: () => {
      const [kind, id] = payee.split(':')
      return giveAdvance({
        site_id: siteValue, amount: n(amount), given_on: on, account_id: account || usable[0]?.id || null, note: note || undefined,
        worker_id: kind === 'worker' ? id : null, vendor_id: kind === 'team' ? id : null, payee_name: kind === 'name' ? name : null,
      })
    },
    onSuccess: (a) => { toast.success(`${inr(a.amount)} to ${a.payee_name}`, 'Taken back from their next wages.'); onGiven() },
    onError: (e) => toast.error('Could not save', errorWords(e)),
  })
  const ready = payee && (payee !== 'name:' || name.trim()) && n(amount) > 0 && siteValue
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader><DialogTitle>Give an advance</DialogTitle></DialogHeader>
        <div className="grid gap-3 text-sm">
          <div className="grid gap-1.5">
            <Label htmlFor="who">To</Label>
            <select id="who" className="h-9 rounded-lg border bg-background px-2" value={payee} onChange={(e) => setPayee(e.target.value)}>
              <option value="">Pick a worker or a team</option>
              {(teams.data?.items ?? []).length > 0 && (
                <optgroup label="Labour teams">{teams.data!.items.map((t) => <option key={t.id} value={`team:${t.id}`}>{t.name}</option>)}</optgroup>
              )}
              <optgroup label="Workers">{(workers.data?.items ?? []).map((w) => <option key={w.id} value={`worker:${w.id}`}>{w.name}{w.trade ? ` · ${w.trade}` : ''}</option>)}</optgroup>
              <option value="name:">Someone not on the register…</option>
            </select>
            {payee === 'name:' && <Input aria-label="Name" placeholder="Their name" value={name} onChange={(e) => setName(e.target.value)} />}
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="grid gap-1.5">
              <Label htmlFor="amt">Amount</Label>
              <Input id="amt" inputMode="decimal" placeholder="500" value={amount} onChange={(e) => setAmount(e.target.value)} />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="on">Given on</Label>
              <Input id="on" type="date" value={on} onChange={(e) => setOn(e.target.value)} />
            </div>
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="site">Site</Label>
            <select id="site" className="h-9 rounded-lg border bg-background px-2" value={siteValue} onChange={(e) => setSite(e.target.value)}>
              {(sites.data ?? []).map((s) => <option key={s.id} value={s.id}>{s.projectName} › {s.name}</option>)}
            </select>
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="acct">From</Label>
            <select id="acct" className="h-9 rounded-lg border bg-background px-2" value={account || usable[0]?.id || ''} onChange={(e) => setAccount(e.target.value)}>
              {usable.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
            </select>
          </div>
          <Input aria-label="Note" placeholder="Note (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button className="font-semibold" disabled={!ready || give.isPending} onClick={() => give.mutate()}>Give {n(amount) ? inr(amount) : ''}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
