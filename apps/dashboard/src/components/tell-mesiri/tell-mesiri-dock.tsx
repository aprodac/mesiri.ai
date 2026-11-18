import * as React from 'react'
import { MessageSquarePlus, X } from 'lucide-react'
import { TellMesiri } from '@/components/tell-mesiri/tell-mesiri'
import { TELL_MESIRI_EVENT, openTellMesiri } from '@/lib/tell-mesiri-events'

// The Tell Mesiri box on every page (16 Nov): one panel, mounted once in the layout, opened by openTellMesiri(). It is
// the same box as on Today, Welcome and Live (WEB-36): what is typed or said goes through the WhatsApp handler, with its
// cards, Save and Cancel, role rules and trial guard. The conversation stays while the panel is closed and reopened.

export function TellMesiriDock() {
  const [open, setOpen] = React.useState(false)
  const [draft, setDraft] = React.useState<{ text: string; n: number } | undefined>()
  const panel = React.useRef<HTMLDivElement>(null)
  React.useEffect(() => {
    let n = 0
    const show = (e: Event) => {
      const text = (e as CustomEvent<string | undefined>).detail
      if (text) setDraft({ text, n: ++n })
      setOpen(true)
      window.setTimeout(() => panel.current?.querySelector<HTMLInputElement>('input')?.focus(), 50)
    }
    window.addEventListener(TELL_MESIRI_EVENT, show)
    return () => window.removeEventListener(TELL_MESIRI_EVENT, show)
  }, [])
  React.useEffect(() => {
    if (!open) return
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    window.addEventListener('keydown', esc)
    return () => window.removeEventListener('keydown', esc)
  }, [open])
  // A panel, not a modal: always mounted (the conversation and a card waiting for Save stay when it is closed), and
  // the page stays usable beside it. role="dialog" + data-state let a walkthrough step aside while it is open.
  return (
    <div
      ref={panel}
      role="dialog"
      aria-label="Tell Mesiri"
      data-state={open ? 'open' : 'closed'}
      data-tell-mesiri=""
      hidden={!open}
      className="fixed right-3 bottom-3 z-50 flex max-h-[min(80svh,640px)] w-[min(calc(100vw-1.5rem),30rem)] flex-col gap-2 overflow-y-auto rounded-2xl border bg-background p-4 shadow-2xl"
      style={{ marginBottom: 'env(safe-area-inset-bottom, 0px)' }}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="m-0 text-base font-semibold">Tell Mesiri</h2>
          <p className="m-0 text-xs text-muted-foreground">
            Type or speak an update or a question. You get a card to Save or Cancel.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setOpen(false)}
          className="inline-flex size-7 shrink-0 items-center justify-center rounded-full text-muted-foreground hover:bg-muted hover:text-foreground"
          aria-label="Close"
        >
          <X className="size-4" />
        </button>
      </div>
      <TellMesiri compact draft={draft} />
    </div>
  )
}

/** The top-bar button. */
export function TellMesiriButton() {
  return (
    <button
      type="button"
      onClick={() => openTellMesiri()}
      data-guide="app.tell"
      className="inline-flex h-8 items-center gap-1.5 rounded-full border px-2.5 text-xs font-medium hover:bg-muted"
      title="Tell Mesiri: type or speak an update or a question"
      aria-label="Tell Mesiri"
    >
      <MessageSquarePlus className="size-4" aria-hidden />
      <span className="hidden sm:inline">Tell Mesiri</span>
    </button>
  )
}
