import { Check, ChevronDown, Loader2, UserRound } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useToast } from '@/components/ui/toast-notification'
import { apiErrorMessage } from '@/lib/logo-upload'
import { MODES, START_MODES, useSetStartMode, useStartMode } from '@/lib/start-mode'
import { cn } from '@/lib/utils'

/**
 * UX-22: "Explained for: New to construction ▾", the one way to change how much Mesiri explains (the answer to "How
 * would you like to start?"), wherever a person may want to: the Help panel, Learn, the sample company's banner.
 * It changes the words of help, tours and the guided project at once; never what the person may see or do.
 */
/** `compact` (the sample company's banner, UX-31): the icon and who it is explained for, the words on hover. */
export function ExplainedFor({ className, guide, compact = false }: { className?: string; guide?: string; compact?: boolean }) {
  const mode = useStartMode()
  const save = useSetStartMode()
  const toast = useToast()
  if (!mode.ready) return null
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          size="sm"
          variant={compact ? 'ghost' : 'outline'}
          className={cn('gap-1.5', !compact && 'bg-background', className)}
          disabled={save.isPending}
          data-guide={guide}
          title={compact ? `Explained for: ${mode.rules.forWho}` : undefined}
        >
          {save.isPending ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : <UserRound className="size-3.5" aria-hidden />}
          {!compact && <span className="text-muted-foreground">Explained for</span>}
          <span className="font-medium">{mode.rules.forWho}</span>
          <ChevronDown className="size-3.5" aria-hidden />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-72">
        <DropdownMenuLabel className="text-xs font-normal text-muted-foreground">How much should Mesiri explain?</DropdownMenuLabel>
        {START_MODES.map((m) => (
          <DropdownMenuItem
            key={m}
            className="items-start gap-2"
            onSelect={() => save.mutate(m, { onError: (e) => toast.error('Not changed', apiErrorMessage(e)) })}
          >
            <Check className={m === mode.mode ? 'mt-0.5 size-4' : 'mt-0.5 size-4 opacity-0'} aria-hidden />
            <span className="min-w-0">
              <span className="block text-sm font-medium">{MODES[m].label}</span>
              <span className="block text-xs text-muted-foreground">{MODES[m].hint}</span>
            </span>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
