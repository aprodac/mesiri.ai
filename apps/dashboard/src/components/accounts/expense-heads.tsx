import * as React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Building2, HardHat, Lightbulb, Search } from 'lucide-react'
import { Segmented } from '@/components/dpr-page'
import { Hint } from '@/components/hint'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { useToast } from '@/components/ui/toast-notification'
import { fetchExpenseHeads, headsToCheck, rupees, setExpenseHead, type ExpenseHead } from '@/lib/accounts'
import { apiErrorMessage } from '@/lib/logo-upload'
import { cn } from '@/lib/utils'

// UX-59 (asked 18 Nov 2026: "do the approach professionals follow"): every expense category is a head of account,
// a site (direct, contract) cost or an office (indirect, head-office) cost, as in Tally: its ledger sits under Direct
// or Indirect Expenses. Site overheads (site staff, site office, power, hire) are site costs. Moving a head reads its
// past entries the new way too; totals and profit do not change, only the split. Backend: /accounts/expense-heads.

type Head = ExpenseHead['head']

export function useExpenseHeads(enabled: boolean) {
  return useQuery({ queryKey: ['accounts', 'expense-heads'], queryFn: fetchExpenseHeads, enabled, retry: false })
}

/** "3 office costs counted as site cost · Review": a chip that opens the review, when there is something to look at. */
export function HeadsCheckChip({ enabled, className }: { enabled: boolean; className?: string }) {
  const q = useExpenseHeads(enabled)
  const [open, setOpen] = React.useState(false)
  const check = headsToCheck(q.data?.heads)
  if (!check.length) return null
  const sum = check.reduce((t, h) => t + Number(h.on_projects), 0)
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className={cn('inline-flex w-fit items-center gap-1.5 rounded-full border border-draft/30 bg-draft-soft px-2.5 py-1 text-xs font-medium text-draft hover:border-draft', className)}
        title={check.map((h) => h.name).join(', ')}
      >
        <Lightbulb className="size-3.5" aria-hidden />
        <span className="font-semibold">{check.length}</span> office {check.length === 1 ? 'cost' : 'costs'} counted as site · {rupees(sum)} · Review
      </button>
      <ExpenseHeadsDialog open={open} onOpenChange={setOpen} />
    </>
  )
}

export function ExpenseHeadsDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const q = useExpenseHeads(open)
  const qc = useQueryClient()
  const toast = useToast()
  const [needle, setNeedle] = React.useState('')
  const save = useMutation({
    mutationFn: ({ id, head }: { id: string; head: Head }) => setExpenseHead(id, head),
    onSuccess: (h) => {
      toast.success(`${h.name}: ${h.head === 'office' ? 'office cost (indirect)' : 'site cost (direct)'}`)
      void qc.invalidateQueries({ queryKey: ['accounts'] })
    },
    onError: (e) => toast.error('Not changed', apiErrorMessage(e)),
  })
  const heads = (q.data?.heads ?? [])
    .filter((h) => !needle || h.name.toLowerCase().includes(needle.toLowerCase()))
    // The ones whose name says otherwise first, then the biggest.
    .sort((a, b) => Number(b.suggested !== b.head) - Number(a.suggested !== a.head) || Number(b.amount) - Number(a.amount))
  const office = (q.data?.heads ?? []).filter((h) => h.head === 'office').length
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            Site or office costs
            <Hint
              title="Site or office costs"
              text="Site (direct) costs are everything spent for a job, site overheads too: materials, labour, subcontract, hire, site staff, site office. Office (indirect) costs run the company: office rent and staff, audit, bank charges. A change reads past entries the new way too; totals and profit stay."
            />
          </DialogTitle>
          <DialogDescription className="flex flex-wrap gap-1.5">
            <span className="inline-flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-xs text-foreground"><HardHat className="size-3" aria-hidden /> {(q.data?.heads.length ?? 0) - office} site</span>
            <span className="inline-flex items-center gap-1 rounded-full bg-info-soft px-2 py-0.5 text-xs text-info"><Building2 className="size-3" aria-hidden /> {office} office</span>
          </DialogDescription>
        </DialogHeader>
        <label className="flex h-8 items-center gap-2 rounded-lg border bg-card px-2.5">
          <Search className="size-3.5 text-muted-foreground" aria-hidden />
          <span className="sr-only">Find a category</span>
          <input value={needle} onChange={(e) => setNeedle(e.target.value)} placeholder="Find a category" className="w-full bg-transparent text-sm outline-none" />
        </label>
        {!q.data ? (
          <div className="h-40 animate-pulse rounded-lg bg-muted" />
        ) : (
          <ul className="divide-y rounded-lg border bg-card">
            {heads.map((h) => {
              const differs = h.suggested !== h.head
              return (
                <li key={h.category_id} className={cn('flex flex-wrap items-center gap-x-3 gap-y-1.5 px-3 py-2', differs && 'bg-draft-soft/40')}>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium">{h.name}</span>
                    <span className="flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground tabular-nums">
                      {Number(h.amount) ? rupees(h.amount) : 'nothing booked'}
                      {Number(h.on_projects) !== 0 && Number(h.on_projects) !== Number(h.amount) && <span>· {rupees(h.on_projects)} on projects</span>}
                      {differs && (
                        <span className="inline-flex items-center gap-1 rounded-full bg-draft-soft px-1.5 py-px font-semibold text-draft">
                          <Lightbulb className="size-3" aria-hidden /> looks like {h.suggested}
                        </span>
                      )}
                    </span>
                  </span>
                  <Segmented<Head>
                    label={`${h.name}: site or office`}
                    value={h.head}
                    options={[
                      { value: 'site', label: 'Site' },
                      { value: 'office', label: 'Office' },
                    ]}
                    onChange={(head) => head !== h.head && !save.isPending && save.mutate({ id: h.category_id, head })}
                  />
                </li>
              )
            })}
          </ul>
        )}
      </DialogContent>
    </Dialog>
  )
}
