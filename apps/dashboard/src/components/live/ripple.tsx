import * as React from 'react'
import { ArrowRight, Pause } from 'lucide-react'
import type { EffectCard, EntryEffects } from '@/lib/api'
import { prefersReducedMotion } from '@/lib/timeline'
import { cn } from '@/lib/utils'
import { Label } from '@/components/onboarding/conversation'

// The ripple (WEB-82): what one saved entry changed, played one card at a
// time on Live's stage. Saving "50 bags cement came" is not the value; the
// stock, the order still to come, the rate against last time and what the
// supplier is owed are. Each card is one number that moved (before → after),
// one sentence, and a tag saying what kind of value it is. The chain ends on
// "One message. N things you now know.", where every card can be opened
// again or in its page. The cards come from GET /dpr/effects/{kind}/{id}:
// real records only, money only for the roles that see spending.

/** How long one card stays up before the next (the presenter can hold or move on). */
export const RIPPLE_CARD_MS = 4_200
/** How long the closing count stays. */
export const RIPPLE_END_MS = 5_200

const TAGS: Record<EffectCard['tag'], { name: string; tone: string }> = {
  money: { name: 'Money', tone: 'bg-[var(--draft-soft)] text-[var(--draft)]' },
  time: { name: 'Time saved', tone: 'bg-[var(--info-soft)] text-[var(--info)]' },
  caught: { name: 'Caught', tone: 'bg-[color-mix(in_srgb,var(--destructive)_12%,transparent)] text-[var(--destructive)]' },
  proof: { name: 'Proof', tone: 'bg-[var(--success-soft)] text-[var(--success)]' },
}

/** The owner's question a card answers (plan section 3). */
const QUESTIONS: Record<number, string> = {
  1: 'Where is my money going?',
  2: 'Is anything leaking?',
  3: 'Is the work moving?',
  4: 'What do I owe, and who owes me?',
  5: 'What will stop work tomorrow?',
  6: 'Can I prove it?',
}

function shape(n: number, rupees: boolean): string {
  if (rupees) return `₹${Math.round(n).toLocaleString('en-IN')}`
  return n.toLocaleString('en-IN', { maximumFractionDigits: 2 })
}

/** A number counting from where it was to where it is now. */
function Count({ from, to, rupees }: { from: number | null; to: number; rupees: boolean }) {
  const start = from ?? to
  const [shown, setShown] = React.useState(prefersReducedMotion() ? to : start)
  React.useEffect(() => {
    if (start === to || prefersReducedMotion()) {
      setShown(to)
      return
    }
    let frame = 0
    // The old number is read first, then it moves.
    const began = performance.now() + 700
    const tick = () => {
      const p = Math.min(1, Math.max(0, (performance.now() - began) / 1_100))
      setShown(start + (to - start) * (1 - Math.pow(1 - p, 3)))
      if (p < 1) frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [start, to])
  // While it moves, whole numbers; it lands on the exact value.
  return <span className="tabular-nums">{shape(shown === to ? to : Math.round(shown), rupees)}</span>
}

function Tag({ tag }: { tag: EffectCard['tag'] }) {
  return <span className={cn('px-2 py-0.5 font-mono text-[10.5px] uppercase tracking-[0.08em]', TAGS[tag].tone)}>{TAGS[tag].name}</span>
}

function BigCard({
  card,
  presenting,
  onOpen,
  onAct,
}: {
  card: EffectCard
  presenting: boolean
  onOpen?: (card: EffectCard, el: HTMLElement) => void
  /** WEB-88: the person's tap on the card's action; resolves when it is done, rejects with why not. */
  onAct?: (card: EffectCard) => Promise<void>
}) {
  const [acting, setActing] = React.useState<'idle' | 'busy' | string>('idle')
  const act = async () => {
    if (!onAct || acting === 'busy') return
    setActing('busy')
    try {
      await onAct(card)
    } catch (err) {
      setActing(err instanceof Error && err.message ? err.message : 'It could not be counted. Open the estimate and try there.')
    }
  }
  const after = card.after === null ? null : Number(card.after)
  const before = card.before === null ? null : Number(card.before)
  const moved = before !== null && after !== null && before !== after
  return (
    <div
      className={cn('grid w-full gap-3 border-2 bg-background px-5 py-5 text-left', card.tag === 'caught' ? 'border-[var(--destructive)]' : 'border-foreground')}
      style={prefersReducedMotion() ? undefined : { animation: 'live-pop 500ms cubic-bezier(.3,1.4,.5,1) both' }}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className={cn('font-semibold', presenting ? 'text-[20px]' : 'text-[16px]')}>{card.title}</span>
        <Tag tag={card.tag} />
      </div>
      {after !== null && (
        <p className={cn('m-0 flex flex-wrap items-baseline gap-x-3 font-semibold tracking-[-0.02em]', presenting ? 'text-[58px] leading-none' : 'text-[42px] leading-none')}>
          {moved && (
            <>
              <s className="text-[0.5em] font-medium text-muted-foreground decoration-1">{shape(before, card.rupees)}</s>
              <ArrowRight className="size-[0.4em] self-center text-muted-foreground" aria-hidden="true" />
            </>
          )}
          <span className={cn(card.tag === 'caught' && 'text-[var(--destructive)]')}>
            <Count key={card.key} from={moved ? before : null} to={after} rupees={card.rupees} />
          </span>
          {card.unit && <span className="text-[0.38em] font-medium text-muted-foreground">{card.unit}</span>}
        </p>
      )}
      <p className={cn('m-0 leading-snug', presenting ? 'text-[22px]' : 'text-[17px]')}>{card.sentence}</p>
      {card.action && onAct && (
        <div className="grid justify-items-start gap-1.5">
          <button
            type="button"
            onClick={() => void act()}
            disabled={acting === 'busy'}
            className={cn(
              'border border-foreground bg-primary px-4 py-2 font-semibold text-primary-foreground hover:bg-foreground hover:text-background disabled:opacity-50',
              presenting ? 'text-[18px]' : 'text-[14.5px]',
            )}
          >
            {acting === 'busy' ? 'Counting…' : card.action.label}
          </button>
          {acting !== 'idle' && acting !== 'busy' && <span className="text-[13px] text-[var(--destructive)]">{acting}</span>}
        </div>
      )}
      <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-2 border-t border-foreground/15 pt-3">
        <p className="m-0 max-w-[30rem] text-[13px] text-muted-foreground">
          <span className="mr-1.5 font-mono text-[10.5px] uppercase tracking-[0.08em]">Say</span>“{card.say}”
        </p>
        {card.opens && onOpen && (
          <button
            type="button"
            onClick={(e) => onOpen(card, e.currentTarget)}
            className="flex shrink-0 items-center gap-1 border-b border-foreground text-[13px] font-medium hover:text-primary-ink"
          >
            Open it <ArrowRight className="size-3.5" />
          </button>
        )}
      </div>
    </div>
  )
}

/**
 * One entry's ripple. `at` is the card showing; `at === cards.length` is the
 * closing count. `held`: the presenter stopped it on this card.
 */
export function Ripple({
  effects,
  at,
  held,
  presenting,
  onPick,
  onOpen,
  onAct,
}: {
  effects: EntryEffects
  at: number
  held: boolean
  presenting: boolean
  /** Show a card again (from the dots, or the closing list). */
  onPick: (index: number) => void
  onOpen?: (card: EffectCard, el: HTMLElement) => void
  onAct?: (card: EffectCard) => Promise<void>
}) {
  const cards = effects.cards
  const done = at >= cards.length
  const card = done ? null : cards[at]
  return (
    <div className="grid w-full max-w-[40rem] gap-3 text-left" aria-live="polite">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Label>
          What it changed{effects.what ? ` · ${effects.what}` : ''}
        </Label>
        <span className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.06em] text-muted-foreground">
          {held && !done && (
            <span className="flex items-center gap-1 text-primary-ink">
              <Pause className="size-3" /> Held
            </span>
          )}
          {done ? `${cards.length} of ${cards.length}` : `${at + 1} of ${cards.length}`}
        </span>
      </div>
      <ol className="m-0 flex list-none gap-1 p-0" aria-label="The changes, in order">
        {cards.map((c, i) => (
          <li key={c.key} className="flex-1">
            <button
              type="button"
              onClick={() => onPick(i)}
              aria-label={`${i + 1}: ${c.title}`}
              aria-current={i === at ? 'step' : undefined}
              className={cn('block h-1.5 w-full transition-colors duration-500', i < at || done ? 'bg-foreground' : i === at ? 'bg-primary' : 'bg-foreground/15')}
            />
          </li>
        ))}
      </ol>
      {card ? (
        <>
          <BigCard key={card.key} card={card} presenting={presenting} onOpen={onOpen} onAct={onAct} />
          <p className="m-0 text-[12.5px] text-muted-foreground">Answers: {QUESTIONS[card.question]}</p>
        </>
      ) : (
        <div
          className="grid gap-3 border-2 border-foreground bg-background px-5 py-5"
          style={prefersReducedMotion() ? undefined : { animation: 'live-pop 500ms cubic-bezier(.3,1.4,.5,1) both' }}
        >
          <p className={cn('m-0 font-semibold tracking-[-0.01em]', presenting ? 'text-[32px] leading-tight' : 'text-[24px] leading-tight')}>
            One message. {cards.length} {cards.length === 1 ? 'thing' : 'things'} you now know.
          </p>
          <ul className="m-0 grid list-none gap-px bg-foreground/15 p-0">
            {cards.map((c, i) => (
              <li key={c.key} className="bg-background">
                <button
                  type="button"
                  onClick={() => onPick(i)}
                  className="grid w-full grid-cols-[auto_minmax(0,1fr)] items-baseline gap-x-3 px-1 py-2 text-left hover:bg-foreground/[0.04]"
                  style={prefersReducedMotion() ? undefined : { animation: `live-in 400ms ease-out ${i * 120}ms both` }}
                >
                  <Tag tag={c.tag} />
                  <span className="min-w-0 text-[14px] leading-snug">{c.sentence}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
      <p className="m-0 hidden font-mono text-[10.5px] uppercase tracking-[0.06em] text-muted-foreground sm:block">
        Space: hold · → next · ← back · S: skip to the end
      </p>
    </div>
  )
}
