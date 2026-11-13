import * as React from 'react'
import { Check, ChevronLeft, Loader2, Printer, Send, X } from 'lucide-react'
import { sendToMesiri, type AssistantReplyOption, type LiveBoard, type LiveDeckStory } from '@/lib/api'
import { apiErrorMessage } from '@/lib/logo-upload'
import { cn } from '@/lib/utils'
import { Label } from '@/components/onboarding/conversation'

// The demo deck (WEB-84, docs/plans/live-value-plan.md section 6): the stories a presenter runs on Live. Each step
// has the line to say; a step with a message sends it through Tell Mesiri (the same handler as WhatsApp), and Live
// plays it like any other message. The stories come from GET /dpr/live/deck, which gives them only to a company
// marked as a demo: a ready message is a real entry once sent.

const esc = (s: string) => s.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]!)

/** WEB-92: the presenter's sheet: the stories and the lines to say on one page, from the same table as the deck. */
export function sheetHtml(stories: LiveDeckStory[], question: (key: string) => string | undefined): string {
  const body = stories
    .map(
      (s, i) => `<section><h2>${i + 1}. ${esc(s.title)} <small>${s.minutes} min${s.short ? ' · in the short show' : ''}</small></h2><ol>${s.steps
        .map(
          (step) =>
            `<li><p class="say">${esc(step.say)}</p>${step.send ? `<p class="send">Send: <b>${esc(step.send)}</b></p>` : ''}${step.do ? `<p class="do">${esc(step.do)}</p>` : ''}</li>`,
        )
        .join('')}</ol>${question(s.ends_on) ? `<p class="ends">Ends on: ${esc(question(s.ends_on)!)}</p>` : ''}</section>`,
    )
    .join('')
  return `<!doctype html><html><head><meta charset="utf-8"><title>Mesiri Live: the presenter's sheet</title><style>
body{font:13px/1.4 system-ui,sans-serif;margin:24px;color:#111}h1{font-size:18px;margin:0 0 4px}
h2{font-size:14px;margin:14px 0 4px}small{font-weight:400;color:#555}ol{margin:0;padding-left:18px}li{margin:0 0 6px}
p{margin:0}.say{font-weight:600}.send b{background:#eee;padding:1px 4px}.do,.ends,.note{color:#555}
section{break-inside:avoid}</style></head><body><h1>Mesiri Live: the presenter's sheet</h1>
<p class="note">Say the bold line, then send the message from “Stories” on Live. Space holds a card, → moves on, S skips to the end. The short show is stories ${stories
    .map((s, i) => (s.short ? i + 1 : null))
    .filter(Boolean)
    .join(' and ')}.</p>${body}</body></html>`
}

type Sent =
  | { state: 'sending' }
  | { state: 'sent'; reply: string; options: AssistantReplyOption[]; chose?: string }
  | { state: 'failed'; error: string }

export function DemoDeck({
  stories,
  board,
  onClose,
  className,
}: {
  stories: LiveDeckStory[]
  board: LiveBoard | undefined
  onClose: () => void
  className?: string
}) {
  const [storyKey, setStoryKey] = React.useState<string | null>(null)
  /** What each step's message came back with, by `${story}:${step}`. */
  const [sent, setSent] = React.useState<Record<string, Sent>>({})
  const story = stories.find((s) => s.key === storyKey) ?? null
  const busy = Object.values(sent).some((s) => s.state === 'sending')
  const question = (key: string) => board?.questions.find((q) => q.key === key)?.question

  const send = async (id: string, body: { text?: string; interactive_reply_id?: string }, chose?: string) => {
    if (busy) return
    const was = sent[id]
    setSent((all) => ({ ...all, [id]: { state: 'sending' } }))
    try {
      const res = await sendToMesiri(body)
      const reply = res.replies.map((r) => r.text).filter(Boolean).join('\n')
      const options = res.replies.flatMap((r) => r.buttons)
      setSent((all) => ({ ...all, [id]: { state: 'sent', reply, options, chose } }))
    } catch (err) {
      // A tap that failed leaves the card it was tapped on, so it can be tapped again.
      setSent((all) => ({ ...all, [id]: chose && was ? was : { state: 'failed', error: apiErrorMessage(err) } }))
    }
  }

  return (
    <aside aria-label="Demo stories" className={cn('border border-foreground bg-background px-4 py-4', className)}>
      <div className="flex items-center justify-between gap-3">
        <Label>
          {story ? (
            <button type="button" onClick={() => setStoryKey(null)} className="flex items-center gap-1 hover:text-foreground">
              <ChevronLeft className="size-3.5" /> Stories
            </button>
          ) : (
            'Stories · ready messages for a demo'
          )}
        </Label>
        <button type="button" onClick={onClose} aria-label="Close the stories" className="text-muted-foreground hover:text-foreground">
          <X className="size-4" />
        </button>
      </div>

      {!story ? (
        <>
          <ol className="m-0 mt-3 grid list-none gap-px bg-foreground/15 p-0 sm:grid-cols-2 lg:grid-cols-5">
            {stories.map((s, i) => (
              <li key={s.key} className="bg-background">
                <button
                  type="button"
                  onClick={() => setStoryKey(s.key)}
                  className="grid h-full w-full content-start gap-1 px-3 py-3 text-left hover:bg-foreground hover:text-background"
                >
                  <span className="font-mono text-[11px] uppercase tracking-[0.06em] opacity-60">
                    {i + 1} · {s.minutes} min{s.short ? ' · short show' : ''}
                  </span>
                  <span className="text-[15px] font-semibold">{s.title}</span>
                  {question(s.ends_on) && <span className="text-[12.5px] opacity-70">Ends on: {question(s.ends_on)}</span>}
                </button>
              </li>
            ))}
          </ol>
          <p className="m-0 mt-3 text-[12.5px] text-muted-foreground">
            Each message is sent as you and saved like any other. Use “Reset demo” in the control panel to start clean.{' '}
            <button
              type="button"
              onClick={() => {
                const sheet = window.open('', '_blank')
                if (!sheet) return
                sheet.document.write(sheetHtml(stories, question))
                sheet.document.close()
                sheet.print()
              }}
              className="inline-flex items-center gap-1 border-b border-foreground font-medium text-foreground"
            >
              <Printer className="size-3.5" /> Print the presenter’s sheet
            </button>
          </p>
        </>
      ) : (
        <ol className="m-0 mt-3 grid list-none gap-3 p-0">
          {story.steps.map((step, i) => {
            const id = `${story.key}:${i}`
            const got = sent[id]
            return (
              <li key={id} className="grid grid-cols-[1.5rem_minmax(0,1fr)] gap-x-2">
                <span className="font-mono text-[12px] tabular-nums text-muted-foreground">{i + 1}</span>
                <div className="grid gap-1.5">
                  <p className="m-0 text-[14.5px] leading-snug">
                    <span className="mr-1.5 font-mono text-[10.5px] uppercase tracking-[0.08em] text-muted-foreground">Say</span>
                    {step.say}
                  </p>
                  {step.do && <p className="m-0 text-[13px] text-muted-foreground">{step.do}</p>}
                  {step.send && (
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="border border-foreground/25 bg-muted px-2.5 py-1.5 text-[13.5px]">{step.send}</span>
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => void send(id, { text: step.send! })}
                        className="flex items-center gap-1.5 border border-foreground px-3 py-1.5 text-[13px] font-medium hover:bg-foreground hover:text-background disabled:opacity-40"
                      >
                        {got?.state === 'sending' ? <Loader2 className="size-3.5 animate-spin" /> : got?.state === 'sent' ? <Check className="size-3.5" /> : <Send className="size-3.5" />}
                        {got?.state === 'sending' ? 'Sending…' : got?.state === 'sent' ? 'Send again' : 'Send'}
                      </button>
                    </div>
                  )}
                  {got?.state === 'sent' && (
                    <div className="grid gap-1.5 border-l-2 border-foreground/20 pl-2.5">
                      {got.reply && <p className="m-0 whitespace-pre-line text-[13px] text-muted-foreground">{got.reply}</p>}
                      {got.options.length > 0 && (
                        <div className="flex flex-wrap gap-1.5">
                          {got.options.map((o) => (
                            <button
                              key={o.id}
                              type="button"
                              disabled={busy || !!got.chose}
                              onClick={() => void send(id, { interactive_reply_id: o.id }, o.id)}
                              className={cn(
                                'border px-2.5 py-1 text-[12.5px] font-medium disabled:opacity-40',
                                got.chose === o.id ? 'border-foreground bg-foreground text-background disabled:opacity-100' : 'border-foreground/40 hover:border-foreground',
                              )}
                            >
                              {o.title}
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                  {got?.state === 'failed' && <p className="m-0 text-[13px] text-[var(--destructive)]">Not sent: {got.error}</p>}
                </div>
              </li>
            )
          })}
          {question(story.ends_on) && (
            <li className="border-t border-foreground/15 pt-2 text-[13px] text-muted-foreground">
              This story ends on the owner’s question: <span className="font-medium text-foreground">{question(story.ends_on)}</span>
            </li>
          )}
        </ol>
      )}
    </aside>
  )
}
