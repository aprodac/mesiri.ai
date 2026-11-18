import * as React from 'react'
import { Check, ChevronDown, FlaskConical, Loader2, LogOut, MoreHorizontal, Play, RotateCcw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ExplainedFor } from '@/components/explained-for'
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
 * UX-31 (17 Nov, "less description and better UI"): one white row: a Sample tag (what it means on hover), the company
 * and who you are as one menu, the days, then Explained for, Guided project, a menu with Start over, and Leave.
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

  const who = session.role !== 'ADMIN' && session.user_name ? session.user_name : sandboxRoleLabel(session.role)

  return (
    <section
      role="status"
      aria-label="Sample company"
      data-sandbox-banner=""
      className="flex flex-col gap-2 rounded-xl border bg-card px-3 py-2 text-sm shadow-xs"
    >
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex min-w-0 items-center gap-2">
        <span
          className="inline-flex shrink-0 items-center gap-1 rounded-md bg-info-soft px-2 py-1 text-xs font-semibold text-info"
          title="Nothing here is real: nothing is sent and your own company is untouched."
        >
          <FlaskConical className="size-3.5" aria-hidden /> Sample
        </span>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              className="inline-flex min-w-0 items-center gap-1 rounded-md px-1.5 py-1 text-left hover:bg-muted disabled:opacity-60"
              disabled={!!busy}
              data-guide="sandbox.role"
              aria-label={`${session.name}, seen as ${who}. Change who you are`}
            >
              <span className="truncate font-semibold">{session.name}</span>
              <span className="shrink-0 text-muted-foreground">·</span>
              {busy === 'role' ? (
                <span className="inline-flex shrink-0 items-center gap-1 text-muted-foreground"><Loader2 className="size-3.5 animate-spin" aria-hidden /> Switching…</span>
              ) : (
                <span className="truncate text-muted-foreground">{current?.label ?? who}</span>
              )}
              <ChevronDown className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="w-72">
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
      </div>

      <div className="flex flex-wrap items-center gap-1.5 sm:justify-end">
        <ExplainedFor compact guide="sandbox.explained" />
        {walkFor(JOURNEY, session.role) && (
          <Button size="sm" variant="ghost" className="gap-1.5" disabled={!!busy} onClick={() => startWalkthrough(JOURNEY.id)}>
            <Play className="size-3.5" aria-hidden /> Guided project
          </Button>
        )}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button size="icon" variant="ghost" className="size-8" disabled={!!busy} aria-label="More for the sample company">
              {busy === 'reset' ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <MoreHorizontal className="size-4" aria-hidden />}
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-60">
            <DropdownMenuItem onSelect={() => void reset()} className="items-start gap-2">
              <RotateCcw className="mt-0.5 size-4" aria-hidden />
              <span className="min-w-0">
                <span className="block text-sm font-medium">Start over</span>
                <span className="block text-xs text-muted-foreground">A fresh sample company, from day 1</span>
              </span>
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
        <Button size="sm" variant="outline" className="gap-1.5" disabled={!!busy} onClick={() => leaveSandbox()}>
          <LogOut className="size-3.5" aria-hidden /> Leave
        </Button>
      </div>
      </div>
      {/* SS-74e: the sample company's days: Next day, Skip ahead, and what is the person's to do. */}
      <div className="border-t pt-2">
        <SandboxClock />
      </div>
      {busy === 'reset' && <p className="m-0 text-xs text-muted-foreground">Making a fresh one…</p>}
      {error && <p className="m-0 text-sm text-destructive">{error}</p>}
    </section>
  )
}
