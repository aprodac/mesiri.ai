import * as React from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ShieldAlert } from 'lucide-react'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { Button } from '@/components/ui/button'
import { reverseInflow, reverseOutflow, reverseTransfer } from '@/lib/materials'

interface CorrectionDialogProps {
  direction: 'IN' | 'OUT'
  movementId: string
  // When the movement is one half of a transfer between sites, the transfer
  // is corrected as a whole -- both sites go back together.
  transferId?: string | null
  originalSummary: string
  open: boolean
  onOpenChange: (open: boolean) => void
  onSuccess?: () => void
}

export function CorrectionDialog({
  direction,
  movementId,
  transferId,
  originalSummary,
  open,
  onOpenChange,
  onSuccess,
}: CorrectionDialogProps) {
  const queryClient = useQueryClient()
  const [reasonNote, setReasonNote] = React.useState('')
  const [error, setError] = React.useState('')

  React.useEffect(() => {
    if (open) {
      setReasonNote('')
      setError('')
    }
  }, [open])

  const mutation = useMutation({
    mutationFn: () =>
      transferId
        ? reverseTransfer(transferId, { reason_note: reasonNote || undefined })
        : direction === 'IN'
          ? reverseInflow(movementId, { reason_note: reasonNote || undefined })
          : reverseOutflow(movementId, { reason_note: reasonNote || undefined }),
    onSuccess: () => {
      // A prefix match on ['materials'] covers inflows/outflows/inventory/
      // ledger/catalog query keys used throughout this domain.
      queryClient.invalidateQueries({ queryKey: ['materials'] })
      onSuccess?.()
      onOpenChange(false)
    },
    onError: (err: any) => {
      setError(err.response?.data?.detail || 'Failed to record the correcting movement.')
    },
  })

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[440px]">
        <DialogHeader>
          <DialogTitle>Correct this entry</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 py-2 text-xs">
          <p className="text-muted-foreground leading-relaxed">
            Confirmed material movements are not edited directly. A correcting movement will be
            recorded to preserve the audit trail.
          </p>
          {transferId && (
            <p className="text-muted-foreground leading-relaxed">
              This is part of a transfer between sites. Both sites are corrected together.
            </p>
          )}

          <div className="bg-muted/30 border border-border/60 rounded p-2.5">
            <span className="block text-[10px] uppercase tracking-wider text-muted-foreground font-semibold mb-1">
              Original Movement
            </span>
            <span className="text-foreground font-medium">{originalSummary}</span>
          </div>

          {error && (
            <div className="bg-destructive/10 border border-destructive text-destructive p-2 rounded flex items-center gap-2">
              <ShieldAlert className="size-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          <div className="grid gap-1.5">
            <Label htmlFor="correctionNote">Why</Label>
            <textarea
              id="correctionNote"
              value={reasonNote}
              onChange={(e) => setReasonNote(e.target.value)}
              className="flex min-h-[70px] w-full rounded-md border border-input bg-transparent px-3 py-2 text-xs shadow-xs focus-visible:outline-hidden focus-visible:ring-1 focus-visible:ring-ring"
              placeholder="e.g. Entered twice, wrong site"
            />
          </div>
        </div>
        <DialogFooter className="pt-2">
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={mutation.isPending}
          >
            Cancel
          </Button>
          <Button type="button" onClick={() => mutation.mutate()} disabled={mutation.isPending}>
            {mutation.isPending ? 'Recording...' : 'Confirm Correction'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
