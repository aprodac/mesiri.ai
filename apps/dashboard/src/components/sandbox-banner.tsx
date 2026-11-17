import * as React from 'react'
import { Check, ChevronDown, FlaskConical, Loader2, LogOut, Play, RotateCcw, UserRound } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { apiErrorMessage } from '@/lib/logo-upload'
import { SANDBOX_ROLES, leaveSandbox, resetSandbox, sandboxRoleLabel, sandboxSession, switchSandboxRole, type SandboxRole } from '@/lib/sandbox'
import { startWalkthrough } from '@/lib/tour-events'
import { JOURNEY, pageOpenFor, walkFor } from '@/lib/walkthroughs'
import { SandboxClock } from '@/components/sandbox-clock'

/**
 * "Sample company: nothing here is real" at the top of every page while this tab is in the person's sample company
 * (SS-67, guided-demo-plan.md section 17.2). Leave goes back to their own company (the sample stays, to pick up
 * later); Start over removes it and makes a fresh one; the guided project can be started from here at any time.
 * SS-76: "Be …" switches to another of its people (Anil, Ravi, Meera, or the owner) in place, to see their screens.
 */
export function SandboxBanner() {
  const session = sandboxSession()
  const [busy, setBusy] = React.useState<'reset' | 'role' | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  if (!session) return null

  const reset = async () => {
    if (!window.confirm('Start over? Everything you did in the sample company is removed and a fresh one is made (about 10 seconds).')) return
    setBusy('reset')
    setError(null)
    try {
      await resetSandbox()
    } catch (e) {
      setError(apiErrorMessage(e))
      setBusy(null)
    }
  }

  const become = async (role: SandboxRole) => {
    if (role === session.role) return
    setBusy('role')
    setError(null)
    try {
      await switchSandboxRole(role, pageOpenFor)
    } catch (e) {
      setError(apiErrorMessage(e))
      setBusy(null)
    }
  }
  const current = SANDBOX_ROLES.find((r) => r.value === session.role)

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
          {/* The backend names the role's person "Anil (project manager)"; the owner is the person themself. */}
          {session.name}, as {session.role !== 'ADMIN' && session.user_name ? session.user_name : sandboxRoleLabel(session.role)}. Try anything: no one gets a message, and your own company is not touched.
          {current && <span className="hidden sm:inline"> {current.label} sees: {current.sees.toLowerCase()}.</span>}
        </p>
        {error && <p className="m-0 mt-1 text-destructive">{error}</p>}
        {/* SS-74e: the sample company's days: Next day, Skip ahead, and what is the person's to do. */}
        <div className="mt-2">
          <SandboxClock />
        </div>
      </div>
      <div className="flex shrink-0 flex-wrap gap-2">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button size="sm" variant="outline" className="gap-1.5 bg-background" disabled={!!busy} data-guide="sandbox.role">
              {busy === 'role' ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : <UserRound className="size-3.5" aria-hidden />}
              {busy === 'role' ? 'Switching…' : `Be: ${current?.label ?? 'Owner'}`}
              <ChevronDown className="size-3.5" aria-hidden />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-72">
            <DropdownMenuLabel className="text-xs font-normal text-muted-foreground">See the sample company as</DropdownMenuLabel>
            {SANDBOX_ROLES.map((r) => (
              <DropdownMenuItem key={r.value} onSelect={() => void become(r.value)} className="items-start gap-2">
                <Check className={r.value === session.role ? 'mt-0.5 size-4' : 'mt-0.5 size-4 opacity-0'} aria-hidden />
                <span className="min-w-0">
                  <span className="block text-sm font-medium">{r.label} <span className="font-normal text-muted-foreground">({r.who})</span></span>
                  <span className="block text-xs text-muted-foreground">{r.sees}</span>
                </span>
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
        {walkFor(JOURNEY, session.role) && (
          <Button size="sm" variant="outline" className="gap-1.5 bg-background" disabled={!!busy} onClick={() => startWalkthrough(JOURNEY.id)}>
            <Play className="size-3.5" aria-hidden /> Guided project
          </Button>
        )}
        <Button size="sm" variant="outline" className="gap-1.5 bg-background" disabled={!!busy} onClick={() => void reset()}>
          {busy === 'reset' ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : <RotateCcw className="size-3.5" aria-hidden />}
          {busy === 'reset' ? 'Making a fresh one…' : 'Start over'}
        </Button>
        <Button size="sm" className="gap-1.5" disabled={!!busy} onClick={() => leaveSandbox()}>
          <LogOut className="size-3.5" aria-hidden /> Leave
        </Button>
      </div>
    </section>
  )
}
