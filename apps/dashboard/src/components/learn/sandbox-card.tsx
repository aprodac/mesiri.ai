import * as React from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { FlaskConical, Loader2, LogOut, Play, Trash2 } from 'lucide-react'
import { Spark } from '@/components/live/spark'
import { Button } from '@/components/ui/button'
import { useAuth } from '@/lib/AuthContext'
import { apiErrorMessage } from '@/lib/logo-upload'
import {
  SANDBOX_ROLES, enterSandbox, inSandbox, leaveSandbox, removeSandbox, sandboxSession, takeSandboxEnded, useSandboxInfo, type SandboxRole,
} from '@/lib/sandbox'
import { startWalkthrough } from '@/lib/tour-events'
import { JOURNEY, walkFor } from '@/lib/walkthroughs'
import { cn } from '@/lib/utils'

/**
 * The sample company on the Learn page (SS-67, guided-demo-plan.md sections 5 and 17): open it, in a role, with or
 * without the guided project; or remove it. Everyone in a company may have one (decision F, 17 Nov); a platform
 * admin has no company of their own, so gets none. Hidden until the server has the routes (SS-66b).
 */
export function SandboxCard() {
  const { me } = useAuth()
  const inside = inSandbox()
  const info = useSandboxInfo(!me?.is_platform_admin && !inside)
  const queries = useQueryClient()
  const [role, setRole] = React.useState<SandboxRole>('ADMIN')
  const [busy, setBusy] = React.useState<'open' | 'guided' | 'remove' | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [ended] = React.useState(takeSandboxEnded)

  if (me?.is_platform_admin) return null

  if (inside) {
    return (
      <section className="flex flex-col gap-3 rounded-xl border border-info/30 bg-info-soft p-4 text-info sm:flex-row sm:items-center">
        <Spark mood="happy" size={44} quiet className="shrink-0" />
        <div className="min-w-0 flex-1 text-sm">
          <p className="m-0 font-semibold">You are in your sample company.</p>
          <p className="m-0 text-info/90">{JOURNEY.about}</p>
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          {walkFor(JOURNEY, sandboxSession()?.role) && (
            <Button size="sm" className="gap-1.5" onClick={() => startWalkthrough(JOURNEY.id)}>
              <Play className="size-3.5" aria-hidden /> Start the guided project
            </Button>
          )}
          <Button size="sm" variant="outline" className="gap-1.5 bg-background" onClick={() => leaveSandbox()}>
            <LogOut className="size-3.5" aria-hidden /> Back to my company
          </Button>
        </div>
      </section>
    )
  }

  const data = info.data as (typeof info.data & { available?: boolean }) | undefined
  if (!data?.available) return null
  const exists = data.exists

  const open = async (guided: boolean) => {
    setBusy(guided ? 'guided' : 'open')
    setError(null)
    try {
      // The guided project is an owner's story (it starts with winning the project); in another role the person
      // looks around as that person instead.
      await enterSandbox(role, guided && role === 'ADMIN' ? JOURNEY.id : undefined)
    } catch (e) {
      setError(apiErrorMessage(e))
      setBusy(null)
    }
  }

  const remove = async () => {
    if (!window.confirm('Remove your sample company? Everything you did in it goes with it. You can make a new one any time.')) return
    setBusy('remove')
    setError(null)
    try {
      await removeSandbox()
      await queries.invalidateQueries({ queryKey: ['learn-sandbox'] })
    } catch (e) {
      setError(apiErrorMessage(e))
    }
    setBusy(null)
  }

  return (
    <section className="flex flex-col gap-3 rounded-xl border bg-card p-4 text-sm" aria-label="Your sample company">
      {ended && (
        <p className="m-0 rounded-lg bg-muted px-3 py-2 text-xs" role="status">
          Your sample session ended. Open it again to carry on.
        </p>
      )}
      <div className="flex items-start gap-3">
        <FlaskConical className="mt-0.5 size-5 shrink-0 text-info" aria-hidden />
        <div className="min-w-0 flex-1">
          <h2 className="m-0 text-base font-semibold">Try it in a sample company</h2>
          <p className="m-0 text-muted-foreground">
            Green Villa: two projects, two weeks of work. Nothing is sent.
            {exists ? ' Yours is kept until you remove it.' : ' Making it takes about 10 seconds.'}
          </p>
        </div>
      </div>

      <fieldset className="m-0 flex flex-col gap-1.5 border-0 p-0">
        <legend className="mb-1 text-xs font-medium text-muted-foreground">Go in as</legend>
        <div className="flex flex-wrap gap-1.5">
          {SANDBOX_ROLES.map((r) => (
            <button
              key={r.value}
              type="button"
              aria-pressed={role === r.value}
              onClick={() => setRole(r.value)}
              className={cn(
                'rounded-full border px-3 py-1 text-xs',
                role === r.value ? 'border-foreground bg-foreground text-background' : 'bg-background hover:bg-muted',
              )}
            >
              {r.label}{r.who !== 'you' && <span className="opacity-70"> · {r.who}</span>}
            </button>
          ))}
        </div>
      </fieldset>

      {error && <p className="m-0 text-destructive" role="alert">{error}</p>}

      <div className="flex flex-wrap items-center gap-2">
        {role === 'ADMIN' && (
          <Button size="sm" className="gap-1.5" disabled={!!busy} onClick={() => void open(true)}>
            {busy === 'guided' ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : <Play className="size-3.5" aria-hidden />}
            {busy === 'guided' ? (exists ? 'Opening…' : 'Making your sample company…') : 'Start the guided project'}
          </Button>
        )}
        <Button size="sm" variant={role === 'ADMIN' ? 'outline' : 'default'} className="gap-1.5" disabled={!!busy} onClick={() => void open(false)}>
          {busy === 'open' && <Loader2 className="size-3.5 animate-spin" aria-hidden />}
          {busy === 'open' ? (exists ? 'Opening…' : 'Making your sample company…') : exists ? 'Open my sample company' : 'Just look around'}
        </Button>
        {exists && (
          <Button size="sm" variant="ghost" className="gap-1.5 text-muted-foreground" disabled={!!busy} onClick={() => void remove()}>
            {busy === 'remove' ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : <Trash2 className="size-3.5" aria-hidden />}
            Remove it
          </Button>
        )}
      </div>
    </section>
  )
}
