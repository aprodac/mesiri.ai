import * as React from 'react'
import { useLocation } from 'react-router-dom'
import { Check } from 'lucide-react'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { MODES, START_MODES, useSetStartMode, useStartMode, type StartMode } from '@/lib/start-mode'
import { apiErrorMessage } from '@/lib/logo-upload'
import { cn } from '@/lib/utils'

// SS-28: "How would you like to start?" (guided-onboarding-plan.md 6.1). One tap, never a form; skipping keeps the
// safe default (step by step) and is stored, so it is not asked again. Changeable from the help button.

export const START_QUESTION = 'How would you like to start?'
const START_NOTE = 'This only changes how much Mesiri explains. Change it any time: Help or Learn, "Explained for".'

/** The four answers as buttons. `current` marks the person's answer (in the help sheet). */
export function StartChoices({
  current,
  onChosen,
  className,
}: {
  current?: StartMode
  onChosen?: (mode: StartMode) => void
  className?: string
}) {
  const save = useSetStartMode()
  const choose = (mode: StartMode) => save.mutate(mode, { onSuccess: () => onChosen?.(mode) })
  return (
    <div className={cn('grid gap-2', className)}>
      {START_MODES.map((mode) => {
        const on = current === mode
        return (
          <button
            key={mode}
            type="button"
            disabled={save.isPending}
            onClick={() => choose(mode)}
            aria-pressed={on}
            className={cn(
              'flex items-start gap-3 rounded-lg border px-4 py-3 text-left transition-colors hover:border-foreground/40 hover:bg-muted/50 disabled:opacity-60',
              on && 'border-foreground/60 bg-muted/60',
            )}
          >
            <span className="min-w-0 flex-1">
              <span className="block text-sm font-semibold">{MODES[mode].label}</span>
              <span className="block text-sm text-muted-foreground">{MODES[mode].hint}</span>
            </span>
            {on && <Check className="mt-0.5 size-4 shrink-0" aria-label="Your choice" />}
          </button>
        )
      })}
      {save.isError && <p className="m-0 text-sm text-destructive">{apiErrorMessage(save.error)}</p>}
    </div>
  )
}

/** The question in the page (the welcome screen). Shown only while it should be asked. */
export function StartQuestionInline({ className }: { className?: string }) {
  const { ask, ready } = useStartMode()
  const save = useSetStartMode()
  const [answered, setAnswered] = React.useState<StartMode | null>(null)
  if (answered) {
    return <p className={cn('m-0 text-sm text-muted-foreground', className)}>Got it: {MODES[answered].label.toLowerCase()}. {START_NOTE}</p>
  }
  if (!ready || !ask) return null
  return (
    <section className={cn('grid gap-3', className)} aria-labelledby="start-question">
      <div>
        <h2 id="start-question" className="m-0 text-lg font-semibold">{START_QUESTION}</h2>
        <p className="m-0 text-sm text-muted-foreground">While your first update comes in.</p>
      </div>
      <StartChoices onChosen={setAnswered} />
      <button type="button" className="justify-self-start text-sm text-muted-foreground underline underline-offset-2" onClick={() => save.mutate('guided', { onSuccess: () => setAnswered('guided') })}>
        Skip
      </button>
    </section>
  )
}

/** The question as a dialog, on the first dashboard visit of anyone not asked yet (a team member, an owner who
 *  skipped the welcome screen). Closing it is skipping it. */
export function StartQuestionDialog() {
  const { ask, ready } = useStartMode()
  const save = useSetStartMode()
  const { pathname } = useLocation()
  const [closed, setClosed] = React.useState(false)
  // The getting-started card's own link to the welcome screen asks it there instead.
  const open = ready && ask && !closed && pathname !== '/welcome'
  const skip = () => {
    setClosed(true)
    save.mutate('guided')
  }
  return (
    <Dialog open={open} onOpenChange={(next) => !next && skip()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{START_QUESTION}</DialogTitle>
          <DialogDescription>{START_NOTE}</DialogDescription>
        </DialogHeader>
        <StartChoices onChosen={() => setClosed(true)} />
      </DialogContent>
    </Dialog>
  )
}
