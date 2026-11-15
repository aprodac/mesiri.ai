import * as React from 'react'
import { Check, Copy, Send } from 'lucide-react'
import type { WhatsAppExample } from '@/lib/module-map'
import { usePreferences } from '@/lib/start-mode'
import { cn } from '@/lib/utils'
import { waLink } from '@/lib/whatsapp-modal'

// How a page works from WhatsApp (guided onboarding, asked 15 Nov: "each page has the preview of how to make it work
// from WhatsApp"): what someone sends Mesiri, and what comes back, drawn as the chat. The words come only from the
// page's `whatsapp` examples in lib/module-map.ts; a test in the WhatsApp assistant checks each example names real
// assistant tools, so a page never shows something WhatsApp can't do.

function CardReply({ reply }: { reply: string }) {
  const [head, ...lines] = reply.split('\n')
  return (
    <div className="w-full max-w-[19rem] self-start overflow-hidden rounded-xl rounded-tl-sm border bg-background shadow-xs">
      <div className="px-3 pt-2.5 pb-2 text-[13px]">
        <p className="m-0 font-semibold">{head}</p>
        {lines.map((line) => (
          <p key={line} className="m-0 text-foreground/85">{line}</p>
        ))}
      </div>
      <div className="grid grid-cols-3 border-t text-center text-[12px] font-semibold text-success" aria-hidden>
        <span className="py-1.5">Save</span>
        <span className="border-x py-1.5">Edit</span>
        <span className="py-1.5">Cancel</span>
      </div>
    </div>
  )
}

/** One example as the chat: the message, then Mesiri's card or answer. */
function Exchange({ example }: { example: WhatsAppExample }) {
  return (
    <div className="flex flex-col gap-2 rounded-xl bg-[#ece9e1] p-3 dark:bg-[#101214]" aria-label="Example WhatsApp chat">
      <div className="max-w-[85%] self-end rounded-xl rounded-tr-sm bg-[#fff3b8] px-3 py-2 text-[13px] text-[#1a1d21] shadow-xs dark:bg-[#3a3313] dark:text-[#ecebe6]">
        {example.say}
      </div>
      {example.kind === 'save' ? (
        <CardReply reply={example.reply} />
      ) : (
        <div className="max-w-[85%] self-start rounded-xl rounded-tl-sm bg-background px-3 py-2 text-[13px] shadow-xs">{example.reply}</div>
      )}
      <p className="m-0 text-center text-[11px] text-muted-foreground">
        {example.kind === 'save' ? 'Saved when you tap Save. Then it shows on this page.' : 'Mesiri answers in the chat.'}
      </p>
    </div>
  )
}

export function WhatsAppPreview({ examples, className }: { examples: WhatsAppExample[]; className?: string }) {
  const [index, setIndex] = React.useState(0)
  const [copied, setCopied] = React.useState(false)
  const prefs = usePreferences()
  const number = prefs.data?.whatsapp_number ?? null
  const example = examples[Math.min(index, examples.length - 1)]
  React.useEffect(() => setIndex(0), [examples])
  if (!example) return null

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(example.say)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1600)
    } catch {
      setCopied(false)
    }
  }

  return (
    <section className={cn('flex flex-col gap-2', className)} aria-label="How this page works from WhatsApp">
      {examples.length > 1 && (
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="Examples">
          {examples.map((e, i) => (
            <button
              key={e.say}
              type="button"
              aria-pressed={i === index}
              onClick={() => setIndex(i)}
              className={cn(
                'rounded-full border px-2.5 py-0.5 text-xs',
                i === index ? 'border-foreground bg-foreground text-background' : 'text-muted-foreground hover:bg-muted',
              )}
            >
              {e.kind === 'save' ? 'Send: ' : 'Ask: '}
              {e.say.length > 26 ? `${e.say.slice(0, 24).trimEnd()}…` : e.say}
            </button>
          ))}
        </div>
      )}
      <Exchange example={example} />
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={copy}
          className="inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs font-medium hover:bg-muted"
        >
          {copied ? <Check className="size-3.5" aria-hidden /> : <Copy className="size-3.5" aria-hidden />}
          {copied ? 'Copied' : 'Copy the message'}
        </button>
        {number && (
          <a
            href={waLink(number, example.say)}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1.5 rounded-lg bg-success px-2.5 py-1 text-xs font-medium text-background hover:opacity-90"
          >
            <Send className="size-3.5" aria-hidden /> Try it on WhatsApp
          </a>
        )}
        {number && <span className="text-xs text-muted-foreground">Mesiri: {number}</span>}
      </div>
      <p className="m-0 text-[11px] text-muted-foreground">An example: your sites, names and numbers will be your own. Text, a voice note or a photo all work.</p>
    </section>
  )
}
