import * as React from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Ban, BookPlus, CircleAlert, NotebookPen, Plus, Scale, Trash2 } from 'lucide-react'
import { BooksClosed, BooksTabs, PeriodBar, VoucherSheet, usePeriod } from '@/components/accounts/books'
import { Callout, DprHeader, DprSection, PageError, StatStrip } from '@/components/dpr-page'
import { Button } from '@/components/ui/button'
import { Combobox } from '@/components/ui/combobox'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { useToast } from '@/components/ui/toast-notification'
import { useAuth } from '@/lib/AuthContext'
import { cancelVoucher, fetchChart, fetchVouchers, formatDay, mayReadBooks, rupees, saveVoucher, type Voucher } from '@/lib/accounts'
import { apiErrorMessage } from '@/lib/logo-upload'
import { usePageTitle } from '@/lib/page-title'
import { fetchProjects } from '@/lib/projects'
import { cn } from '@/lib/utils'

// ACC-12: manual vouchers, for what no record on site or in the office says (a provision, a correction, a
// reclassification). Kept as records and posted by the books like any other, so a closed month is never changed.
// Never a bank or cash ledger: money that moved is a movement in Finance › Money (a transfer posts as a contra on its
// own), so the books keep agreeing with it. Backend: /accounts/vouchers.

type Row = { key: number; ledger_id: string; debit: string; credit: string; project_id: string }

let nextKey = 1
const emptyRow = (): Row => ({ key: nextKey++, ledger_id: '', debit: '', credit: '', project_id: '' })
const today = () => new Date().toLocaleDateString('en-CA') // the local day (YYYY-MM-DD), not UTC's
const paise = (v: string) => Math.round(Number(v || 0) * 100)

export default function VouchersPage() {
  usePageTitle('Vouchers')
  const { me } = useAuth()
  const allowed = mayReadBooks(me?.role)
  const periodState = usePeriod('this_month')
  const { period } = periodState
  const [params, setParams] = useSearchParams()
  const q = useQuery({ queryKey: ['accounts', 'vouchers', period], queryFn: () => fetchVouchers(period), enabled: allowed })
  const [editing, setEditing] = React.useState<Voucher | 'new' | null>(null)
  const [cancelling, setCancelling] = React.useState<Voucher | null>(null)
  const [entryId, setEntryId] = React.useState<string | null>(null)
  const openId = params.get('open')

  React.useEffect(() => {
    if (!openId || !q.data) return
    const v = q.data.vouchers.find((x) => x.id === openId)
    if (v) setEditing(v)
  }, [openId, q.data])

  if (!allowed) return <BooksClosed />
  if (q.isError) return <PageError message="The vouchers could not be loaded." onRetry={() => q.refetch()} back={{ to: '/accounts', label: 'Accounts' }} />
  const d = q.data
  const posted = d?.vouchers.filter((v) => v.status === 'posted') ?? []
  const closeEditor = () => {
    setEditing(null)
    if (openId) setParams((p) => { const n = new URLSearchParams(p); n.delete('open'); return n }, { replace: true })
  }

  return (
    <div className="mx-auto flex w-full flex-col gap-4 pb-8 sm:px-2">
      <DprHeader
        back={{ to: '/accounts/day-book', label: 'Day book' }}
        crumb="Accounts"
        title="Vouchers"
        date="Journals typed by the accountant"
        action={<Button size="sm" className="gap-1.5" onClick={() => setEditing('new')}><Plus className="size-4" /> New voucher</Button>}
      />
      <BooksTabs current="/accounts/vouchers" />
      <PeriodBar state={periodState} />
      {!d ? (
        <Skeleton className="h-72 rounded-xl" />
      ) : (
        <>
          <StatStrip
            stats={[
              { label: 'Vouchers', value: String(posted.length), icon: NotebookPen },
              { label: 'Amount', value: rupees(d.total), icon: Scale },
              { label: 'Cancelled', value: String(d.vouchers.length - posted.length), icon: Ban, tone: d.vouchers.length - posted.length ? 'warn' : 'default' },
            ]}
          />
          <Callout tone="muted" icon={BookPlus}>
            Everything on site and in the office is already in the books on its own. A voucher is only for what no record says: a provision, a correction, moving an amount to the right ledger. Money between your own accounts is a transfer in <Link to="/finance/money" className="underline">Finance › Money</Link>; it posts here as a contra.
          </Callout>
          <DprSection icon={NotebookPen} title="In this period" meta={d.vouchers.length || undefined}>
            {d.vouchers.length === 0 ? (
              <p className="rounded-lg border border-dashed px-4 py-6 text-sm text-muted-foreground">No vouchers in this period. Most months need none.</p>
            ) : (
              <ul className="divide-y rounded-lg border text-sm">
                {d.vouchers.map((v) => (
                  <li key={v.id} className={cn('flex flex-col gap-2 px-3 py-2.5 sm:flex-row sm:items-center sm:gap-4', v.status === 'cancelled' && 'opacity-60')}>
                    <button type="button" className="min-w-0 flex-1 text-left" onClick={() => (v.status === 'posted' ? setEditing(v) : v.entry_id && setEntryId(v.entry_id))}>
                      <span className="flex flex-wrap items-center gap-2 font-medium">
                        <span className={cn(v.status === 'cancelled' && 'line-through')}>{v.narration}</span>
                        {v.status === 'cancelled' && <span className="rounded-full bg-muted px-2 py-0.5 text-xs font-normal">Cancelled</span>}
                      </span>
                      <span className="block text-xs text-muted-foreground">
                        {[formatDay(v.date), v.ref, v.lines.map((l) => l.ledger).join(' · '), v.created_by ? `by ${v.created_by}` : null,
                          v.status === 'cancelled' && v.cancel_reason ? `cancelled: ${v.cancel_reason}` : null].filter(Boolean).join(' · ')}
                      </span>
                    </button>
                    <span className="font-semibold tabular-nums">{rupees(v.amount)}</span>
                    {v.status === 'posted' && (
                      <Button size="sm" variant="ghost" className="text-muted-foreground" onClick={() => setCancelling(v)}>Cancel</Button>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </DprSection>
        </>
      )}
      {editing && <VoucherEditor voucher={editing === 'new' ? null : editing} onClose={closeEditor} />}
      <CancelDialog voucher={cancelling} onClose={() => setCancelling(null)} />
      <VoucherSheet entryId={entryId} onClose={() => setEntryId(null)} />
    </div>
  )
}

function VoucherEditor({ voucher, onClose }: { voucher: Voucher | null; onClose: () => void }) {
  const toast = useToast()
  const qc = useQueryClient()
  const chart = useQuery({ queryKey: ['accounts', 'chart'], queryFn: fetchChart })
  const projects = useQuery({ queryKey: ['scope-projects'], queryFn: fetchProjects, staleTime: 60_000 })
  const [date, setDate] = React.useState(voucher?.date ?? today())
  const [narration, setNarration] = React.useState(voucher?.narration ?? '')
  const [rows, setRows] = React.useState<Row[]>(() =>
    voucher
      ? voucher.lines.map((l) => ({ key: nextKey++, ledger_id: l.ledger_id, debit: Number(l.debit) ? String(Number(l.debit)) : '', credit: Number(l.credit) ? String(Number(l.credit)) : '', project_id: l.project_id ?? '' }))
      : [emptyRow(), emptyRow()],
  )
  const groups = new Map((chart.data?.groups ?? []).map((g) => [g.id, g.name]))
  // Bank and cash ledgers are left out: money that moved is recorded in Finance › Money.
  const options = (chart.data?.ledgers ?? [])
    .filter((l) => l.is_active && l.link_kind !== 'money_account')
    .map((l) => ({ value: l.id, label: `${l.name} · ${groups.get(l.group_id) ?? ''}` }))
  const projectOptions = [{ value: '', label: 'No project (head office)' }, ...(projects.data ?? []).map((p) => ({ value: p.id, label: p.name }))]
  const dr = rows.reduce((s, r) => s + paise(r.debit), 0)
  const cr = rows.reduce((s, r) => s + paise(r.credit), 0)
  const filled = rows.filter((r) => r.ledger_id && (paise(r.debit) || paise(r.credit)))
  const ready = narration.trim().length >= 3 && filled.length >= 2 && dr === cr && dr > 0
  const set = (key: number, patch: Partial<Row>) => setRows((rs) => rs.map((r) => (r.key === key ? { ...r, ...patch } : r)))
  const balance = () => {
    const gap = dr - cr
    if (!gap) return
    const last = [...rows].reverse().find((r) => !paise(r.debit) && !paise(r.credit)) ?? rows[rows.length - 1]
    set(last.key, gap > 0 ? { credit: (Math.abs(gap) / 100).toFixed(2), debit: '' } : { debit: (Math.abs(gap) / 100).toFixed(2), credit: '' })
  }
  const save = useMutation({
    mutationFn: () => saveVoucher({
      date, narration: narration.trim(),
      lines: filled.map((r) => ({ ledger_id: r.ledger_id, debit: r.debit || '0', credit: r.credit || '0', project_id: r.project_id || null })),
    }, voucher?.id),
    onSuccess: (v) => {
      toast.success(voucher ? 'Voucher changed' : `Voucher ${v.ref ?? ''} posted`)
      qc.invalidateQueries({ queryKey: ['accounts'] })
      onClose()
    },
    onError: (err: unknown) => toast.error('Not saved', apiErrorMessage(err)),
  })
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && ready && !save.isPending) {
      e.preventDefault()
      save.mutate()
    }
  }
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[92vh] overflow-y-auto sm:max-w-3xl" onKeyDown={onKey}>
        <DialogHeader>
          <DialogTitle>{voucher ? `Voucher ${voucher.ref ?? ''}` : 'New voucher'}</DialogTitle>
          <DialogDescription>A journal: what is debited and what is credited, equal to the paisa. Tab moves between cells; Ctrl+Enter posts it.</DialogDescription>
        </DialogHeader>
        <div className="grid gap-3 sm:grid-cols-[160px_1fr]">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="v-date">Date</Label>
            <Input id="v-date" type="date" value={date} onChange={(e) => setDate(e.target.value)} className="dark:[color-scheme:dark]" />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="v-narration">Narration</Label>
            <Input id="v-narration" value={narration} onChange={(e) => setNarration(e.target.value)} placeholder="e.g. Audit fee for 2026-27 provided" maxLength={500} autoFocus />
          </div>
        </div>
        <div className="flex flex-col gap-2">
          <div className="hidden grid-cols-[1fr_110px_110px_170px_32px] gap-2 px-1 text-xs text-muted-foreground sm:grid">
            <span>Ledger</span><span className="text-right">Debit</span><span className="text-right">Credit</span><span>Project</span><span />
          </div>
          {rows.map((r) => (
            <div key={r.key} className="grid grid-cols-2 gap-2 rounded-lg border p-2 sm:grid-cols-[1fr_110px_110px_170px_32px] sm:border-0 sm:p-0">
              <div className="col-span-2 sm:col-span-1">
                <Combobox options={options} value={r.ledger_id} onValueChange={(v) => set(r.key, { ledger_id: v })} placeholder={chart.isLoading ? 'Loading ledgers…' : 'Pick a ledger'} searchPlaceholder="Type a ledger" />
              </div>
              <Input aria-label="Debit" inputMode="decimal" value={r.debit} placeholder="Debit" className="text-right tabular-nums"
                onChange={(e) => set(r.key, { debit: e.target.value.replace(/[^0-9.]/g, ''), credit: e.target.value ? '' : r.credit })} />
              <Input aria-label="Credit" inputMode="decimal" value={r.credit} placeholder="Credit" className="text-right tabular-nums"
                onChange={(e) => set(r.key, { credit: e.target.value.replace(/[^0-9.]/g, ''), debit: e.target.value ? '' : r.debit })} />
              <div className="col-span-2 sm:col-span-1">
                <Combobox options={projectOptions} value={r.project_id} onValueChange={(v) => set(r.key, { project_id: v })} placeholder="No project" searchPlaceholder="Type a project" />
              </div>
              <Button type="button" variant="ghost" size="icon" aria-label="Remove line" disabled={rows.length <= 2} onClick={() => setRows((rs) => rs.filter((x) => x.key !== r.key))}>
                <Trash2 className="size-4" />
              </Button>
            </div>
          ))}
          <div className="flex flex-wrap items-center gap-2">
            <Button type="button" variant="outline" size="sm" className="gap-1.5" onClick={() => setRows((rs) => [...rs, emptyRow()])}><Plus className="size-3.5" /> Line</Button>
            {dr !== cr && <Button type="button" variant="ghost" size="sm" className="gap-1.5" onClick={balance}><Scale className="size-3.5" /> Balance it</Button>}
            <span className={cn('ml-auto text-sm tabular-nums', dr === cr ? 'text-success' : 'text-draft')}>
              Debit {rupees(dr / 100)} · Credit {rupees(cr / 100)}{dr !== cr ? ` · differ by ${rupees(Math.abs(dr - cr) / 100)}` : ' · balanced'}
            </span>
          </div>
        </div>
        {voucher && (
          <Callout tone="muted" icon={CircleAlert}>A voucher in a closed month stays as it is: reopen the month, or cancel it (the difference is then posted on the first open day, marked).</Callout>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Close</Button>
          <Button onClick={() => save.mutate()} disabled={!ready || save.isPending}>{save.isPending ? 'Posting…' : voucher ? 'Save changes' : 'Post voucher'}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function CancelDialog({ voucher, onClose }: { voucher: Voucher | null; onClose: () => void }) {
  const toast = useToast()
  const qc = useQueryClient()
  const [reason, setReason] = React.useState('')
  const act = useMutation({
    mutationFn: () => cancelVoucher(voucher!.id, reason.trim()),
    onSuccess: () => {
      toast.success('Voucher cancelled')
      qc.invalidateQueries({ queryKey: ['accounts'] })
      setReason('')
      onClose()
    },
    onError: (err: unknown) => toast.error('Not cancelled', apiErrorMessage(err)),
  })
  return (
    <Dialog open={!!voucher} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Cancel this voucher?</DialogTitle>
          <DialogDescription>{voucher?.narration}: {rupees(voucher?.amount)}. It is kept, marked cancelled, and taken out of the books. Say why, for the CA.</DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="cancel-reason">Reason</Label>
          <Input id="cancel-reason" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. provided twice" maxLength={500} autoFocus />
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Keep it</Button>
          <Button variant="destructive" onClick={() => act.mutate()} disabled={reason.trim().length < 3 || act.isPending}>{act.isPending ? 'Cancelling…' : 'Cancel voucher'}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
