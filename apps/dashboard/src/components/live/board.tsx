import * as React from 'react'
import { ArrowRight, ChevronDown } from 'lucide-react'
import type { LiveBoard, LiveBoardKey, LiveBoardQuestion, LiveFeedItem } from '@/lib/api'
import { prefersReducedMotion } from '@/lib/timeline'
import { cn } from '@/lib/utils'
import { Label } from '@/components/onboarding/conversation'

// The owner's board (WEB-83, docs/plans/live-value-plan.md section 3): six questions an owner carries all day,
// each with its answer in a sentence with the number inside it. The sentences come from GET /dpr/live/board,
// which reads each module's own page data, so an answer and the page it opens always agree. Nothing is worked
// out here: the board only shows, and says which of today's messages an answer was built from.

/** What a switched-off module is called on its greyed line. */
const MODULE_NAMES: Record<string, string> = {
  cost: 'Cost control',
  labour: 'Labour',
  materials: 'Materials',
  finance: 'Finance',
  equipment: 'Machines',
}

const clock = (iso: string | null) =>
  iso ? new Date(iso).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' }) : ''

/** The questions a message answers: by what it saved (a ✅ Save tap carries the kind it saved). */
export function questionsOf(m: LiveFeedItem, board: LiveBoard | undefined): LiveBoardKey[] {
  const kind = m.kind === 'saved' && m.saved_kind ? m.saved_kind : m.kind
  return board?.kinds[kind] ?? []
}

/** Today's saved messages behind each answer. */
function builtFrom(items: LiveFeedItem[], board: LiveBoard): Map<LiveBoardKey, LiveFeedItem[]> {
  const out = new Map<LiveBoardKey, LiveFeedItem[]>()
  for (const m of items) {
    if (m.state !== 'saved') continue
    for (const key of questionsOf(m, board)) out.set(key, [...(out.get(key) ?? []), m])
  }
  return out
}

function fromLine(messages: LiveFeedItem[]): string {
  const people = new Set(messages.map((m) => m.sender_name ?? 'someone')).size
  return `From ${messages.length} ${messages.length === 1 ? 'message' : 'messages'} by ${people} ${people === 1 ? 'person' : 'people'} today`
}

export function OwnerBoard({
  board,
  failed,
  items,
  ringing,
  presenting,
  nodeRef,
  onOpen,
  className,
}: {
  board: LiveBoard | undefined
  /** The board could not be read: said, never shown as empty answers. */
  failed: boolean
  /** The day's messages already on screen. */
  items: LiveFeedItem[]
  /** Questions a message just landed on ('q:<key>'), and how. */
  ringing: Map<string, 'land' | 'alarm'>
  presenting: boolean
  nodeRef: (key: LiveBoardKey, el: HTMLElement | null) => void
  onOpen: (q: LiveBoardQuestion, path: string, el: HTMLElement, line?: string) => void
  className?: string
}) {
  const [open, setOpen] = React.useState<LiveBoardKey | null>(null)
  const from = React.useMemo(() => (board ? builtFrom(items, board) : new Map<LiveBoardKey, LiveFeedItem[]>()), [items, board])

  return (
    <section aria-label="The owner’s board" className={className}>
      <Label>The owner’s board</Label>
      {failed && !board ? (
        <p className="m-0 mt-4 text-sm text-muted-foreground">The board could not be read just now. The messages still show.</p>
      ) : !board ? (
        <p className="m-0 mt-4 text-sm text-muted-foreground">Reading the answers…</p>
      ) : (
        <ul className="m-0 mt-4 grid list-none grid-cols-1 gap-px bg-foreground/15 p-0 sm:grid-cols-2 xl:grid-cols-1">
          {board.questions.map((q) => {
            const how = ringing.get(`q:${q.key}`)
            const messages = from.get(q.key) ?? []
            const [first, ...rest] = q.lines
            const offNames = q.off.map((m) => MODULE_NAMES[m] ?? m).join(' and ')
            const expanded = open === q.key && messages.length > 0
            return (
              <li
                key={q.key}
                ref={(el) => nodeRef(q.key, el)}
                className={cn(
                  'relative grid gap-1.5 border bg-background px-3.5 py-3',
                  how === 'alarm' ? 'z-40 border-[var(--destructive)]' : 'border-transparent',
                )}
                style={
                  prefersReducedMotion() || !how
                    ? undefined
                    : { animation: how === 'alarm' ? 'live-shake 600ms ease-out 2' : 'live-land 1.4s ease-out' }
                }
              >
                <span className="font-mono text-[11px] uppercase tracking-[0.06em] text-muted-foreground">{q.question}</span>
                {first ? (
                  <button
                    type="button"
                    onClick={(e) => onOpen(q, first.opens, e.currentTarget, first.text)}
                    className={cn(
                      'group flex items-start justify-between gap-2 text-left font-semibold leading-snug hover:text-primary-ink',
                      presenting ? 'text-[19px]' : 'text-[15px]',
                    )}
                  >
                    {/* The key makes a changed answer come in again, so the number is seen to move. */}
                    <span key={first.text} style={prefersReducedMotion() ? undefined : { animation: 'live-in 400ms ease-out' }}>
                      {first.text}
                    </span>
                    <ArrowRight className="mt-1 size-3.5 shrink-0 opacity-40 transition-transform group-hover:translate-x-0.5 group-hover:opacity-100" aria-hidden="true" />
                  </button>
                ) : q.quiet ? (
                  <button
                    type="button"
                    onClick={(e) => onOpen(q, q.opens, e.currentTarget)}
                    className={cn('text-left text-muted-foreground hover:text-foreground', presenting ? 'text-[17px]' : 'text-[14px]')}
                  >
                    {q.quiet}
                  </button>
                ) : q.hidden ? (
                  <span className="text-[13.5px] text-muted-foreground">Shown to the owner, finance and project managers.</span>
                ) : q.off.length ? (
                  <span className="text-[13.5px] text-muted-foreground opacity-70">With {offNames} you would see this here.</span>
                ) : (
                  <span className="text-[13.5px] text-muted-foreground">Could not be read just now.</span>
                )}
                {rest.map((line) => (
                  <button
                    key={line.read + line.text}
                    type="button"
                    onClick={(e) => onOpen(q, line.opens, e.currentTarget, line.text)}
                    className="text-left text-[13px] leading-snug text-muted-foreground hover:text-foreground"
                  >
                    {line.text}
                  </button>
                ))}
                {first && q.off.length > 0 && (
                  <span className="text-[12px] text-muted-foreground opacity-70">With {offNames} you would also see more here.</span>
                )}
                {messages.length > 0 && (
                  <button
                    type="button"
                    aria-expanded={expanded}
                    onClick={() => setOpen(expanded ? null : q.key)}
                    className="flex items-center gap-1 text-left font-mono text-[10.5px] uppercase tracking-[0.06em] text-muted-foreground hover:text-foreground"
                  >
                    {fromLine(messages)}
                    <ChevronDown className={cn('size-3 transition-transform', expanded && 'rotate-180')} aria-hidden="true" />
                  </button>
                )}
                {expanded && (
                  <ul className="m-0 grid list-none gap-1 border-l-2 border-foreground/20 p-0 pl-2.5">
                    {messages.slice(-5).reverse().map((m) => (
                      <li key={m.id} className="text-[12.5px] leading-snug">
                        <span className="font-mono text-[11px] tabular-nums text-muted-foreground">{clock(m.received_at)}</span>{' '}
                        <span className="font-medium">{m.sender_name ?? 'Someone'}</span>
                        {m.site_name ? <span className="text-muted-foreground"> · {m.site_name}</span> : null}
                        <span className="block text-muted-foreground">{m.summaries[0] ?? m.text ?? ''}</span>
                      </li>
                    ))}
                    {messages.length > 5 && (
                      <li className="text-[12px] text-muted-foreground">and {messages.length - 5} earlier</li>
                    )}
                  </ul>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
