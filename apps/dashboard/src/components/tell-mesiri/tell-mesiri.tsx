import * as React from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Mic, Send, Square } from 'lucide-react'
import { sendToMesiri, sendVoiceToMesiri, type AssistantReply, type AssistantResponse } from '@/lib/api'
import { apiErrorMessage } from '@/lib/logo-upload'
import { canRecord, MAX_SECONDS, startRecording, type Recording } from '@/lib/voice-recorder'
import { Conversation, Exchange, Label, WordsIn } from '@/components/onboarding/conversation'
import { cn } from '@/lib/utils'

// Tell Mesiri from the dashboard (WEB-36): speak or type an update and Mesiri
// handles it exactly as a WhatsApp message (same handler, same workflows,
// same confirmations), shown in the onboarding conversation's layout: what
// you said on the left, Mesiri on the right. Its buttons are real buttons.

interface Turn {
  id: number
  at: Date
  kind: 'voice' | 'text' | 'tap'
  /** What was said: typed text, a tapped option's title, or the voice note's words once heard. */
  said: string | null
  seconds?: number
  pending: boolean
  replies: AssistantReply[]
  error?: string
  /** The option tapped on this turn's buttons, once one is. */
  chose?: string
}

const BAR_COUNT = 40

function clock(d: Date): string {
  return d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
}

function duration(seconds: number): string {
  const s = Math.max(0, Math.round(seconds))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

function LiveBars({ levels }: { levels: number[] }) {
  return (
    <div className="flex h-8 flex-1 items-center gap-[3px] overflow-hidden" aria-hidden="true">
      {levels.map((level, i) => (
        <span
          key={i}
          className="w-[3px] shrink-0 rounded-full bg-foreground"
          style={{ height: `${Math.max(8, level * 100)}%` }}
        />
      ))}
    </div>
  )
}

function Options({
  reply,
  turn,
  disabled,
  onTap,
}: {
  reply: AssistantReply
  turn: Turn
  disabled: boolean
  onTap: (id: string, title: string) => void
}) {
  const options = reply.type === 'buttons' ? reply.buttons : reply.list_rows
  return (
    <div className="flex flex-wrap gap-2 pt-1">
      {options.map((o) => {
        const chosen = turn.chose === o.id
        return (
          <button
            key={o.id}
            type="button"
            disabled={disabled || !!turn.chose}
            onClick={() => onTap(o.id, o.title)}
            title={o.description ?? undefined}
            className={cn(
              'border border-foreground px-3 py-1.5 font-mono text-[11px] uppercase tracking-[0.06em] transition-colors',
              chosen ? 'bg-foreground text-background' : 'hover:bg-foreground hover:text-background',
              turn.chose && !chosen && 'opacity-40',
              'disabled:cursor-default',
            )}
          >
            {o.title}
          </button>
        )
      })}
    </div>
  )
}

function MesiriSide({
  turn,
  busy,
  onTap,
}: {
  turn: Turn
  busy: boolean
  onTap: (turn: Turn, id: string, title: string) => void
}) {
  if (turn.error) {
    return <p className="m-0 text-sm text-destructive">{turn.error}</p>
  }
  if (turn.pending) {
    return (
      <Label className="flex items-center gap-2">
        <span className="relative flex size-2" aria-hidden="true">
          <span className="absolute inline-flex size-full animate-ping rounded-full bg-primary opacity-60 motion-reduce:animate-none" />
          <span className="relative inline-flex size-2 rounded-full bg-primary" />
        </span>
        {turn.kind === 'voice' ? 'Listening to it' : 'Reading it'}
      </Label>
    )
  }
  return (
    <div className="grid gap-3 animate-in fade-in slide-in-from-bottom-1 duration-500 motion-reduce:animate-none">
      <Label>{clock(turn.at)} · Mesiri</Label>
      {turn.replies.map((reply, i) => (
        <div key={i} className="grid gap-2">
          <p className="m-0 whitespace-pre-line text-[15px] leading-relaxed">{reply.text}</p>
          {reply.type !== 'text' && (
            <Options reply={reply} turn={turn} disabled={busy} onTap={(id, title) => onTap(turn, id, title)} />
          )}
        </div>
      ))}
    </div>
  )
}

function SiteSide({ turn }: { turn: Turn }) {
  const label =
    turn.kind === 'voice'
      ? `Voice note · ${duration(turn.seconds ?? 0)}`
      : turn.kind === 'tap'
        ? 'Tapped'
        : 'Typed'
  return (
    <div className="grid gap-2">
      <Label>{label}</Label>
      {turn.said ? (
        <WordsIn text={turn.said} className="text-[17px] leading-relaxed" />
      ) : turn.kind === 'voice' && turn.pending ? (
        <p className="m-0 text-sm text-muted-foreground">Sent. Mesiri is listening.</p>
      ) : null}
    </div>
  )
}

/**
 * The panel. `compact` (the welcome screen) shows only the latest exchange
 * and no title; the page around it shows the rest.
 */
export function TellMesiri({ compact = false, className }: { compact?: boolean; className?: string }) {
  const queryClient = useQueryClient()
  const [turns, setTurns] = React.useState<Turn[]>([])
  const [text, setText] = React.useState('')
  const [recording, setRecording] = React.useState<Recording | null>(null)
  const [levels, setLevels] = React.useState<number[]>(() => Array(BAR_COUNT).fill(0))
  const [elapsed, setElapsed] = React.useState(0)
  const [micError, setMicError] = React.useState<string | null>(null)
  const nextId = React.useRef(1)
  const busy = turns.some((t) => t.pending)
  const mic = canRecord()

  const update = (id: number, change: Partial<Turn>) =>
    setTurns((all) => all.map((t) => (t.id === id ? { ...t, ...change } : t)))

  const settle = (id: number, res: AssistantResponse, keepSaid = false) => {
    setTurns((all) =>
      all.map((t) =>
        t.id === id ? { ...t, pending: false, replies: res.replies, said: keepSaid ? t.said : res.transcript ?? t.said } : t,
      ),
    )
    // Anything saved shows on Today and the welcome screen straight away.
    void queryClient.invalidateQueries({
      predicate: (q) => typeof q.queryKey[0] === 'string' && /site-day|setup-progress/.test(q.queryKey[0] as string),
    })
  }

  const add = (turn: Omit<Turn, 'id' | 'at' | 'pending' | 'replies'>): number => {
    const id = nextId.current++
    setTurns((all) => [...all, { id, at: new Date(), pending: true, replies: [], ...turn }])
    return id
  }

  const sendText = async (e?: React.FormEvent) => {
    e?.preventDefault()
    const said = text.trim()
    if (!said || busy) return
    setText('')
    const id = add({ kind: 'text', said })
    try {
      settle(id, await sendToMesiri({ text: said }), true)
    } catch (err) {
      update(id, { pending: false, error: apiErrorMessage(err) })
    }
  }

  const tap = async (from: Turn, optionId: string, title: string) => {
    if (busy) return
    update(from.id, { chose: optionId })
    const id = add({ kind: 'tap', said: title })
    try {
      settle(id, await sendToMesiri({ interactive_reply_id: optionId }), true)
    } catch (err) {
      update(id, { pending: false, error: apiErrorMessage(err) })
    }
  }

  const finish = React.useCallback(
    async (rec: Recording) => {
      setRecording(null)
      let note
      try {
        note = await rec.stop()
      } catch {
        return
      }
      const id = add({ kind: 'voice', said: null, seconds: note.seconds })
      try {
        settle(id, await sendVoiceToMesiri(note.audio))
      } catch (err) {
        update(id, { pending: false, error: apiErrorMessage(err) })
      }
    },
    // add/settle/update only use setters and the query client
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  )

  const startMic = async () => {
    if (recording || busy) return
    setMicError(null)
    setLevels(Array(BAR_COUNT).fill(0))
    setElapsed(0)
    try {
      const rec = await startRecording((level) => setLevels((prev) => [...prev.slice(1), level]))
      setRecording(rec)
    } catch (err) {
      const denied = err instanceof DOMException && (err.name === 'NotAllowedError' || err.name === 'SecurityError')
      setMicError(
        denied
          ? 'The microphone is blocked for this site. Allow it in the browser, or type instead.'
          : 'No microphone found. Type instead.',
      )
    }
  }

  // The timer, and the minute's limit.
  React.useEffect(() => {
    if (!recording) return
    const started = performance.now()
    const timer = window.setInterval(() => {
      const s = (performance.now() - started) / 1000
      setElapsed(s)
      if (s >= MAX_SECONDS) void finish(recording)
    }, 200)
    return () => window.clearInterval(timer)
  }, [recording, finish])

  // Leaving the page mid-recording lets the microphone go.
  React.useEffect(() => () => recording?.cancel(), [recording])

  const shown = compact ? turns.slice(-1) : turns.slice(-4)

  return (
    <section aria-label="Tell Mesiri" className={cn('@container', className)}>
      {!compact && (
        <header className="flex flex-wrap items-baseline justify-between gap-2 pb-2">
          <h2 className="text-[15px] font-semibold">Tell Mesiri</h2>
          <Label className="normal-case tracking-normal">Speak or type today&apos;s work, in any language</Label>
        </header>
      )}

      {shown.length > 0 && (
        <Conversation now={Infinity}>
          <div className="divide-y border-y" aria-live="polite">
            {shown.map((turn) => (
              <Exchange
                key={turn.id}
                className="py-5"
                time={<Label>{clock(turn.at)}</Label>}
                site={<SiteSide turn={turn} />}
                mesiri={<MesiriSide turn={turn} busy={busy} onTap={tap} />}
              />
            ))}
          </div>
        </Conversation>
      )}

      <div className={cn('flex items-center gap-2 pt-3', shown.length === 0 && !compact && 'pt-1')}>
        {recording ? (
          <>
            <button
              type="button"
              onClick={() => void finish(recording)}
              className="grid size-10 shrink-0 place-items-center bg-primary text-primary-foreground"
              aria-label="Stop and send"
              title="Stop and send"
            >
              <Square className="size-4 fill-current" />
            </button>
            <LiveBars levels={levels} />
            <span className="font-mono text-xs tabular-nums text-muted-foreground">
              {duration(elapsed)} / {duration(MAX_SECONDS)}
            </span>
            <button
              type="button"
              onClick={() => {
                recording.cancel()
                setRecording(null)
              }}
              className="border-b border-foreground font-mono text-[11px] uppercase tracking-[0.06em]"
            >
              Cancel
            </button>
          </>
        ) : (
          <>
            {mic && (
              <button
                type="button"
                onClick={() => void startMic()}
                disabled={busy}
                className="grid size-10 shrink-0 place-items-center bg-foreground text-background transition-opacity disabled:opacity-40"
                aria-label="Record a voice note"
                title="Record a voice note"
              >
                <Mic className="size-4" />
              </button>
            )}
            <form onSubmit={sendText} className="flex min-w-0 flex-1 items-center border border-foreground/80 focus-within:border-foreground">
              <label htmlFor="tell-mesiri-text" className="sr-only">
                Type an update for Mesiri
              </label>
              <input
                id="tell-mesiri-text"
                value={text}
                onChange={(e) => setText(e.target.value)}
                maxLength={2000}
                autoComplete="off"
                placeholder={mic ? 'Or type: 6 masons, 4 helpers, slab shuttering done…' : 'Type: 6 masons, 4 helpers, slab shuttering done…'}
                className="h-10 min-w-0 flex-1 bg-transparent px-3 text-sm outline-none placeholder:text-muted-foreground"
              />
              <button
                type="submit"
                disabled={!text.trim() || busy}
                className="grid h-10 w-10 shrink-0 place-items-center disabled:opacity-30"
                aria-label="Send"
                title="Send"
              >
                <Send className="size-4" />
              </button>
            </form>
          </>
        )}
      </div>
      {micError && <p className="m-0 pt-2 text-xs text-destructive">{micError}</p>}
    </section>
  )
}
