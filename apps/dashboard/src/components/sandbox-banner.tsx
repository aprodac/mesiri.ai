import * as React from 'react'
import { FlaskConical, Loader2, LogOut, Play, RotateCcw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { apiErrorMessage } from '@/lib/logo-upload'
import { leaveSandbox, resetSandbox, sandboxRoleLabel, sandboxSession } from '@/lib/sandbox'
import { startWalkthrough } from '@/lib/tour-events'
import { JOURNEY, walkFor } from '@/lib/walkthroughs'

/**
 * "Sample company: nothing here is real" at the top of every page while this tab is in the person's sample company
 * (SS-67, guided-demo-plan.md section 17.2). Leave goes back to their own company (the sample stays, to pick up
 * later); Start over removes it and makes a fresh one; the guided project can be started from here at any time.
 */
export function SandboxBanner() {
  const session = sandboxSession()
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  if (!session) return null

  const reset = async () => {
    if (!window.confirm('Start over? Everything you did in the sample company is removed and a fresh one is made (about 10 seconds).')) return
    setBusy(true)
    setError(null)
    try {
      await resetSandbox()
    } catch (e) {
      setError(apiErrorMessage(e))
      setBusy(false)
    }
  }

  return (
    <section
      role="status"
      aria-label="Sample company"
      data-sandbox-banner=""
      className="flex flex-col gap-2 rounded-xl border border-info/30 bg-info-soft px-4 py-2.5 text-info sm:flex-row sm:items-center sm:gap-3"
    >
      <FlaskConical className="hidden size-5 shrink-0 sm:block" aria-hidden />
      <div className="min-w-0 flex-1 text-sm">
        <p className="m-0 font-semibold">Sample company: nothing here is real.</p>
        <p className="m-0 text-info/90">
          {session.name}, as {sandboxRoleLabel(session.role)}
          {session.role !== 'ADMIN' && session.user_name ? ` (${session.user_name})` : ''}. Try anything: no one gets a message, and your own company is not touched.
        </p>
        {error && <p className="m-0 mt-1 text-destructive">{error}</p>}
      </div>
      <div className="flex shrink-0 flex-wrap gap-2">
        {walkFor(JOURNEY, session.role) && (
          <Button size="sm" variant="outline" className="gap-1.5 bg-background" disabled={busy} onClick={() => startWalkthrough(JOURNEY.id)}>
            <Play className="size-3.5" aria-hidden /> Guided project
          </Button>
        )}
        <Button size="sm" variant="outline" className="gap-1.5 bg-background" disabled={busy} onClick={() => void reset()}>
          {busy ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : <RotateCcw className="size-3.5" aria-hidden />}
          {busy ? 'Making a fresh one…' : 'Start over'}
        </Button>
        <Button size="sm" className="gap-1.5" disabled={busy} onClick={() => leaveSandbox()}>
          <LogOut className="size-3.5" aria-hidden /> Leave
        </Button>
      </div>
    </section>
  )
}
