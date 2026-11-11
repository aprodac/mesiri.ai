import * as React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, Scale, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useToast } from '@/components/ui/toast-notification'
import { correctVoucher, fetchVoucherLedgers, postVoucher, rupees, type Entry, type ManualType, type VoucherLedger } from '@/lib/accounts'
import { fetchProjects } from '@/lib/projects'
import { cn } from '@/lib/utils'

// ACC-12: a manual voucher, keyboard first, as in Tally. Date, then rows of ledger · Dr · Cr, then the narration.
// Ledger: type to search, ↑ ↓ to choose, Enter to take it (the difference so far is offered on the side that balances);
// Enter in Dr goes to Cr when Dr is empty, else to the next row; Enter in Cr goes to the next row (a new row appears).
// The difference shows live and Save waits for it to be nil; the database's balance check stays the real guard.
// With ``correcting`` the same form posts the reversal of that voucher and this new one together (owner, admin).

type Row = { key: number; ledgerId: string; text: string; debit: string; credit: string; projectId: string; costCentre: string }

const blank = (key: number): Row => ({ key, ledgerId: '', text: '', debit: '', credit: '', projectId: '', costCentre: '' })
const paise = (v: string) => Math.round((Number(v) || 0) * 100)
const amount = (p: number) => (p / 100).toFixed(2)

function today(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function fyStart(iso: string): string {
  const [y, m] = iso.split('-').map(Number)
  return `${m >= 4 ? y : y - 1}-04-01`
}

function errorWords(err: unknown): string {
  const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map((d) => (d as { msg?: string }).msg ?? '').join(' ')
  return 'That did not save. Try again.'
}

export function NewVoucherDialog({ open, onClose, correcting, onSaved }: { open: boolean; onClose: () => void; correcting?: Entry | null; onSaved?: (e: Entry) => void }) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const { data } = useQuery({ queryKey: ['accounts', 'voucher-ledgers'], queryFn: fetchVoucherLedgers, enabled: open, staleTime: 60_000 })
  const { data: projects = [] } = useQuery({ queryKey: ['projects', 'names'], queryFn: fetchProjects, enabled: open, staleTime: 60_000 })
  const [type, setType] = React.useState<ManualType>('journal')
  const [date, setDate] = React.useState(today())
  const [narration, setNarration] = React.useState('')
  const [reason, setReason] = React.useState('')
  const [rows, setRows] = React.useState<Row[]>([blank(1), blank(2)])
  const [more, setMore] = React.useState(false)
  const [error, setError] = React.useState('')
  const refs = React.useRef<Record<string, HTMLInputElement | null>>({})
  const focus = (key: number, field: 'ledger' | 'dr' | 'cr') => setTimeout(() => refs.current[`${field}-${key}`]?.focus(), 0)

  React.useEffect(() => {
    if (!open) return
    setError('')
    setReason('')
    if (correcting) {
      setType(correcting.voucher_type === 'contra' ? 'contra' : 'journal')
      setDate(correcting.date)
      setNarration(correcting.narration ?? '')
      setRows(correcting.lines.map((l, i) => ({ key: i + 1, ledgerId: l.ledger_id, text: l.ledger, debit: Number(l.debit) ? l.debit : '', credit: Number(l.credit) ? l.credit : '', projectId: l.project_id ?? '', costCentre: l.cost_centre ?? '' })))
      setMore(correcting.lines.some((l) => l.project_id || l.cost_centre))
    } else {
      setType('journal')
      setDate(today())
      setNarration('')
      setRows([blank(1), blank(2)])
      setMore(false)
    }
  }, [open, correcting])

  const ledgers = React.useMemo(() => (data?.ledgers ?? []).filter((l) => type === 'journal' || l.contra), [data, type])
  const dr = rows.reduce((n, r) => n + paise(r.debit), 0)
  const cr = rows.reduce((n, r) => n + paise(r.credit), 0)
  const used = rows.filter((r) => r.ledgerId && (paise(r.debit) || paise(r.credit)))
  const balanced = dr === cr && dr > 0 && used.length >= 2
  const badRow = rows.find((r) => (r.ledgerId && paise(r.debit) && paise(r.credit)) || (!r.ledgerId && (paise(r.debit) || paise(r.credit))))

  const update = (key: number, patch: Partial<Row>) => setRows((all) => all.map((r) => (r.key === key ? { ...r, ...patch } : r)))
  const nextRow = (key: number) => {
    const i = rows.findIndex((r) => r.key === key)
    if (i < rows.length - 1) return focus(rows[i + 1].key, 'ledger')
    const k = Math.max(...rows.map((r) => r.key)) + 1
    setRows((all) => [...all, blank(k)])
    focus(k, 'ledger')
  }
  const pick = (row: Row, l: VoucherLedger) => {
    // Tally's habit: the next line is offered the difference on the side that balances.
    const others = rows.filter((r) => r.key !== row.key)
    const gap = others.reduce((n, r) => n + paise(r.debit) - paise(r.credit), 0)
    const fill = !paise(row.debit) && !paise(row.credit) && gap !== 0
    update(row.key, { ledgerId: l.id, text: l.name, ...(fill ? (gap > 0 ? { credit: amount(gap), debit: '' } : { debit: amount(-gap), credit: '' }) : {}) })
    focus(row.key, fill && gap > 0 ? 'cr' : 'dr')
  }

  const save = useMutation({
    mutationFn: () => {
      const body = {
        date, voucher_type: type, narration: narration.trim(),
        lines: used.map((r) => ({ ledger_id: r.ledgerId, debit: paise(r.debit) ? amount(paise(r.debit)) : '0', credit: paise(r.credit) ? amount(paise(r.credit)) : '0', project_id: r.projectId || null, cost_centre: r.costCentre || null })),
      }
      return correcting ? correctVoucher(correcting.id, reason.trim(), body) : postVoucher(body)
    },
    onSuccess: (e) => {
      queryClient.invalidateQueries({ queryKey: ['accounts'] })
      toast.success(correcting ? `Corrected: ${e.ref}` : `Saved ${e.ref}`, correcting ? 'The old voucher is reversed and linked.' : 'In the day book, the ledgers and every report.')
      onSaved?.(e)
      onClose()
    },
    onError: (e) => setError(errorWords(e)),
  })
  const canSave = balanced && !badRow && narration.trim().length > 0 && !!date && (!correcting || reason.trim().length >= 3) && !save.isPending

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[100dvh] gap-3 overflow-y-auto sm:max-w-3xl" onKeyDown={(e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && canSave) { e.preventDefault(); save.mutate() } }}>
        <DialogHeader>
          <DialogTitle>{correcting ? `Correct ${correcting.ref}` : 'New voucher'}</DialogTitle>
          <DialogDescription>{correcting ? 'The old voucher is reversed (kept, linked) and this one is posted, in one step.' : 'Enter moves on; Ctrl + Enter saves when it balances.'}</DialogDescription>
        </DialogHeader>

        <div className="flex flex-wrap items-end gap-3">
          <div className="flex flex-col gap-1">
            <Label htmlFor="v-date">Date</Label>
            <Input id="v-date" type="date" value={date} autoFocus onChange={(e) => setDate(e.target.value)} className="w-40 dark:[color-scheme:dark]"
              onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); focus(rows[0].key, 'ledger') } }} />
          </div>
          <div role="radiogroup" aria-label="Kind of voucher" className="flex gap-0.5 rounded-lg bg-muted p-1">
            {(['journal', 'contra'] as const).map((t) => (
              <button key={t} type="button" role="radio" aria-checked={type === t} onClick={() => setType(t)} disabled={!!correcting}
                className={cn('h-8 rounded-md px-3 text-sm', type === t ? 'bg-background font-semibold shadow-sm' : 'text-foreground/75')}>
                {t === 'journal' ? 'Journal' : 'Contra'}
              </button>
            ))}
          </div>
          {!correcting && (
            <Button type="button" variant="ghost" size="sm" className="h-8 text-xs" title="A Journal on the first day of the year, against Opening balance difference"
              onClick={() => { setType('journal'); setDate(fyStart(date || today())); setNarration('Opening balance') }}>
              Opening balance
            </Button>
          )}
          <Button type="button" variant="ghost" size="sm" className="ml-auto h-8 text-xs" onClick={() => setMore((m) => !m)}>{more ? 'Hide' : 'Show'} project / cost centre</Button>
        </div>
        {type === 'contra' && <p className="-mt-1 text-xs text-muted-foreground">Contra: money between cash and bank only, e.g. cash deposited in the bank.</p>}

        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full min-w-[34rem] text-sm">
            <thead className="bg-muted/40 text-xs text-muted-foreground">
              <tr>
                <th className="px-2 py-1.5 text-left font-medium">Ledger</th>
                <th className="w-32 px-2 py-1.5 text-right font-medium">Dr ₹</th>
                <th className="w-32 px-2 py-1.5 text-right font-medium">Cr ₹</th>
                {more && <th className="w-40 px-2 py-1.5 text-left font-medium">Project</th>}
                {more && <th className="w-32 px-2 py-1.5 text-left font-medium">Cost centre</th>}
                <th className="w-8" />
              </tr>
            </thead>
            <tbody className="divide-y">
              {rows.map((r) => (
                <tr key={r.key}>
                  <td className="px-1 py-1"><LedgerPicker row={r} ledgers={ledgers} inputRef={(el) => { refs.current[`ledger-${r.key}`] = el }} onText={(text) => update(r.key, { text, ledgerId: '' })} onPick={(l) => pick(r, l)} onSkip={() => focus(r.key, 'dr')} /></td>
                  <td className="px-1 py-1">
                    <Input ref={(el) => { refs.current[`dr-${r.key}`] = el }} aria-label="Debit" inputMode="decimal" value={r.debit} className="h-9 text-right tabular-nums"
                      onChange={(e) => update(r.key, { debit: e.target.value.replace(/[^0-9.]/g, ''), ...(e.target.value ? { credit: '' } : {}) })}
                      onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); if (paise(r.debit)) nextRow(r.key); else focus(r.key, 'cr') } }} />
                  </td>
                  <td className="px-1 py-1">
                    <Input ref={(el) => { refs.current[`cr-${r.key}`] = el }} aria-label="Credit" inputMode="decimal" value={r.credit} className="h-9 text-right tabular-nums"
                      onChange={(e) => update(r.key, { credit: e.target.value.replace(/[^0-9.]/g, ''), ...(e.target.value ? { debit: '' } : {}) })}
                      onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); if (balanced) document.getElementById('v-narration')?.focus(); else nextRow(r.key) } }} />
                  </td>
                  {more && (
                    <td className="px-1 py-1">
                      <select aria-label="Project" value={r.projectId} onChange={(e) => update(r.key, { projectId: e.target.value })} className="h-9 w-full rounded-md border bg-background px-2 text-sm">
                        <option value="">Head office</option>
                        {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                      </select>
                    </td>
                  )}
                  {more && (
                    <td className="px-1 py-1">
                      <select aria-label="Cost centre" value={r.costCentre} onChange={(e) => update(r.key, { costCentre: e.target.value })} className="h-9 w-full rounded-md border bg-background px-2 text-sm">
                        <option value="">—</option>
                        {(data?.cost_centres ?? []).map((c) => <option key={c} value={c}>{c}</option>)}
                      </select>
                    </td>
                  )}
                  <td className="px-1 py-1">
                    {rows.length > 2 && <Button type="button" variant="ghost" size="icon" className="size-8" aria-label="Remove line" tabIndex={-1} onClick={() => setRows((all) => all.filter((x) => x.key !== r.key))}><X className="size-4" /></Button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <Button type="button" variant="ghost" size="sm" className="h-8 gap-1 text-xs" onClick={() => nextRow(rows[rows.length - 1].key)}><Plus className="size-3.5" /> Line</Button>
          <span data-testid="voucher-difference" className={cn('ml-auto inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-sm tabular-nums', balanced ? 'bg-success-soft text-success' : 'bg-muted text-foreground')}>
            <Scale className="size-4" /> Dr {rupees(amount(dr))} · Cr {rupees(amount(cr))}{dr !== cr ? ` · difference ${rupees(amount(Math.abs(dr - cr)))}` : balanced ? ' · balanced' : ''}
          </span>
        </div>
        {badRow && <p className="text-xs text-destructive">A line needs a ledger and one amount, on one side.</p>}

        <div className="flex flex-col gap-1">
          <Label htmlFor="v-narration">Narration</Label>
          <Input id="v-narration" value={narration} maxLength={500} placeholder="Cash deposited in HDFC · Bank charges for October · Opening balance" onChange={(e) => setNarration(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && canSave) { e.preventDefault(); save.mutate() } }} />
        </div>
        {correcting && (
          <div className="flex flex-col gap-1">
            <Label htmlFor="v-reason">Why it is corrected</Label>
            <Input id="v-reason" value={reason} maxLength={300} placeholder="Amount was 500, not 5,000" onChange={(e) => setReason(e.target.value)} />
          </div>
        )}
        {error && <p className="text-sm text-destructive">{error}</p>}
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
          <Button type="button" disabled={!canSave} onClick={() => save.mutate()}>{correcting ? 'Reverse and post' : 'Save voucher'}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function LedgerPicker({ row, ledgers, inputRef, onText, onPick, onSkip }: { row: Row; ledgers: VoucherLedger[]; inputRef: (el: HTMLInputElement | null) => void; onText: (t: string) => void; onPick: (l: VoucherLedger) => void; onSkip: () => void }) {
  const [openList, setOpenList] = React.useState(false)
  const [hi, setHi] = React.useState(0)
  const words = row.text.trim().toLowerCase()
  const matches = React.useMemo(() => {
    if (row.ledgerId) return []
    const hits = ledgers.filter((l) => !words || l.name.toLowerCase().includes(words) || l.group.toLowerCase().includes(words))
    return hits.sort((a, b) => Number(!a.name.toLowerCase().startsWith(words)) - Number(!b.name.toLowerCase().startsWith(words))).slice(0, 8)
  }, [ledgers, words, row.ledgerId])
  const listId = `ledgers-${row.key}`
  return (
    <div className="relative">
      <Input ref={inputRef} value={row.text} placeholder="Ledger" className="h-9" role="combobox" aria-expanded={openList && matches.length > 0} aria-controls={listId} aria-autocomplete="list"
        onFocus={() => setOpenList(true)} onBlur={() => setTimeout(() => setOpenList(false), 120)}
        onChange={(e) => { onText(e.target.value); setHi(0); setOpenList(true) }}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown') { e.preventDefault(); setHi((h) => Math.min(h + 1, matches.length - 1)) }
          else if (e.key === 'ArrowUp') { e.preventDefault(); setHi((h) => Math.max(h - 1, 0)) }
          else if (e.key === 'Enter') {
            e.preventDefault()
            if (matches[hi]) { onPick(matches[hi]); setOpenList(false) } else if (row.ledgerId) onSkip()
          }
        }} />
      {openList && matches.length > 0 && (
        <ul id={listId} role="listbox" className="absolute top-full left-0 z-50 mt-1 max-h-64 w-full min-w-64 overflow-y-auto rounded-md border bg-popover p-1 shadow-md">
          {matches.map((l, i) => (
            <li key={l.id} role="option" aria-selected={i === hi} onMouseDown={(e) => { e.preventDefault(); onPick(l); setOpenList(false) }}
              className={cn('flex cursor-pointer items-baseline justify-between gap-2 rounded px-2 py-1.5 text-sm', i === hi && 'bg-accent')}>
              <span className="truncate">{l.name}</span><span className="shrink-0 text-xs text-muted-foreground">{l.group}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
