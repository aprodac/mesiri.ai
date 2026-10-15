import * as React from 'react'
import { useMutation } from '@tanstack/react-query'
import { Lock } from 'lucide-react'
import { requestContinue } from '@/lib/api'
import { apiErrorMessage } from '@/lib/logo-upload'
import { useTrial } from '@/lib/trial'
import { Button } from '@/components/ui/button'

/**
 * "Your free trial has ended" bar at the top of every page (SS-15). Reading
 * still works; saves are refused by the backend (SS-08). The owner can ask to
 * continue right here; anyone else is told to ask the owner.
 */
export function TrialBanner() {
  const trial = useTrial()
  const [requested, setRequested] = React.useState(false)
  const continueMutation = useMutation({
    mutationFn: requestContinue,
    onSuccess: () => setRequested(true),
  })

  if (!trial.readOnly) return null
  const asked = requested || trial.continueRequested

  return (
    <section
      role="status"
      aria-label="Free trial ended"
      className="flex flex-col sm:flex-row sm:items-center gap-3 rounded-xl border border-draft/30 bg-draft-soft px-4 py-3 text-draft"
    >
      <Lock className="size-5 shrink-0 hidden sm:block" aria-hidden />
      <div className="flex-1 min-w-0 text-sm">
        <p className="font-semibold">Your free trial has ended — your data is read-only.</p>
        <p className="text-draft/90">
          {asked
            ? 'Thanks — our team will call you to keep your reports going.'
            : trial.isOwner
              ? 'Everything you recorded is safe. Continue with Mesiri to keep reporting and editing.'
              : "Everything is safe. Ask your company's owner to continue with Mesiri."}
        </p>
        {continueMutation.isError && (
          <p className="text-destructive mt-1">{apiErrorMessage(continueMutation.error)}</p>
        )}
      </div>
      {trial.isOwner && !asked && (
        <Button
          className="shrink-0"
          disabled={continueMutation.isPending}
          onClick={() => continueMutation.mutate()}
        >
          {continueMutation.isPending ? 'Sending…' : 'Continue with Mesiri'}
        </Button>
      )}
    </section>
  )
}
