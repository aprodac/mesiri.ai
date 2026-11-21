import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FileSignature } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useToast } from '@/components/ui/toast-notification'
import { fetchContract, putContract, type ContractInput } from '@/lib/billing'
import { formatRupees } from '@/lib/boq'

/**
 * QA-04 3.1 / PS phase 2: the BOQ's total and the contract value are one number typed twice. With no contract value
 * yet, offer the BOQ total as it; with both set and different, say so (the person decides which is right).
 * Only for the people who see client contracts (the caller passes `money`).
 */
export function ContractFromBoq({ projectId, boqTotal }: { projectId: string; boqTotal: string | null }) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const contract = useQuery({ queryKey: ['contract', projectId], queryFn: () => fetchContract(projectId), retry: false })
  const save = useMutation({
    mutationFn: () => {
      // The PUT writes every term: start from what is stored, so only the value changes.
      const stored = contract.data?.contract
      const body: ContractInput = {}
      if (stored) {
        for (const [k, v] of Object.entries(stored)) {
          if (k !== 'client_name' && k !== 'updated_at') (body as Record<string, unknown>)[k] = v
        }
      }
      body.contract_value = boqTotal
      return putContract(projectId, body)
    },
    onSuccess: () => {
      toast.success('Contract value set from the BOQ')
      for (const k of ['contract', 'project-start', 'ra-bills']) queryClient.invalidateQueries({ queryKey: [k] })
    },
    onError: () => toast.error('Could not set the contract value'),
  })

  const total = Number(boqTotal ?? 0)
  if (!contract.data || !total) return null
  const value = contract.data.contract?.contract_value
  if (!value) {
    return (
      <div className="flex flex-wrap items-center gap-3 rounded-xl border border-primary/30 bg-primary/5 px-4 py-3 text-sm" data-guide="boq.contract">
        <FileSignature className="size-5 shrink-0 text-primary-ink" aria-hidden />
        <span className="min-w-0 flex-1">
          <span className="font-medium">The contract value is not set yet.</span>{' '}
          <span className="text-muted-foreground">Client bills need it. The BOQ adds up to {formatRupees(boqTotal)}.</span>
        </span>
        <Button size="sm" onClick={() => save.mutate()} disabled={save.isPending}>
          {save.isPending ? 'Saving…' : `Use ${formatRupees(boqTotal)} as the contract value`}
        </Button>
      </div>
    )
  }
  const diff = total - Number(value)
  if (Math.abs(diff) < 1) return null
  return (
    <p className="rounded-xl border bg-muted/40 px-4 py-2.5 text-sm text-muted-foreground" data-guide="boq.contract">
      The contract says {formatRupees(value)}; the BOQ adds up to {formatRupees(boqTotal)}, {formatRupees(String(Math.abs(diff)))}{' '}
      {diff > 0 ? 'more' : 'less'}. One of them needs a look (a variation not in the contract yet, or a line missing).
    </p>
  )
}
