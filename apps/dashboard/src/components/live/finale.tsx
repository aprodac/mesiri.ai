import * as React from 'react'
import { useQuery } from '@tanstack/react-query'
import { CheckCheck, FileText } from 'lucide-react'
import { fetchRecipients } from '@/lib/projects'
import { prefersReducedMotion } from '@/lib/timeline'
import { cn } from '@/lib/utils'
import { WhatsAppIcon } from '@/components/brand/whatsapp-icon'

// The Live report's ending (WEB-39): when the day's report goes out, the
// sheet folds into its PDF, the PDF drops into WhatsApp, and the people it
// went to tick off one by one, blue ticks and all. Who gets it is read from
// the project's recipient list (read-only); with none set, the project's
// admins and managers get it, and it says so.

type Stage = 'paper' | 'fold' | 'drop' | 'sent'

const FOLD_MS = 900
const DROP_MS = 800
export const FINALE_MS = 9_000

export function Finale({
  from,
  projectId,
  company,
  code,
  site,
  onDone,
}: {
  /** Where the sheet is, so the paper starts on top of it. */
  from: DOMRect
  projectId: string | undefined
  company: string
  code: string | null
  site: string
  onDone: () => void
}) {
  const still = prefersReducedMotion()
  const [stage, setStage] = React.useState<Stage>(still ? 'sent' : 'paper')
  const recipients = useQuery({
    queryKey: ['live-finale-recipients', projectId],
    queryFn: () => fetchRecipients(projectId!),
    enabled: !!projectId,
    retry: false,
    staleTime: 60_000,
  })
  const done = React.useRef(onDone)
  done.current = onDone

  React.useEffect(() => {
    const timers = still
      ? [window.setTimeout(() => done.current(), 4000)]
      : [
          window.setTimeout(() => setStage('fold'), 80),
          window.setTimeout(() => setStage('drop'), 80 + FOLD_MS + 250),
          window.setTimeout(() => setStage('sent'), 80 + FOLD_MS + 250 + DROP_MS),
          window.setTimeout(() => done.current(), FINALE_MS),
        ]
    return () => timers.forEach(window.clearTimeout)
  }, [still])

  const people = (recipients.data?.recipients ?? []).filter((r) => r.will_receive)
  const names = people.map((r) => ({ id: r.id, name: r.name || r.phone || 'Recipient', tag: r.label || (r.kind === 'contact' ? 'Client' : r.role?.toLowerCase().replace('_', ' ')) }))
  const vw = window.innerWidth
  const vh = window.innerHeight
  // The folded PDF sits just above the centre; the WhatsApp mark under it.
  const pdf = { w: 132, h: 172, x: vw / 2 - 66, y: vh / 2 - 210 }
  const paperStyle: React.CSSProperties =
    stage === 'paper'
      ? { left: from.left, top: from.top, width: from.width, height: from.height }
      : { left: pdf.x, top: pdf.y, width: pdf.w, height: pdf.h }
  const fileName = `${code || 'DPR'}.pdf`

  return (
    <div className="fixed inset-0 z-[60]" role="status" aria-live="polite" aria-label={`The daily report was sent on WhatsApp${names.length ? ` to ${names.length} people` : ''}`}>
      <div
        className={cn('absolute inset-0 bg-background/85 backdrop-blur-[2px] transition-opacity duration-700', stage === 'paper' ? 'opacity-0' : 'opacity-100')}
        aria-hidden="true"
      />

      {/* The sheet, folding into its PDF and dropping into WhatsApp */}
      <div
        aria-hidden="true"
        className="absolute overflow-hidden border border-black/15 bg-white text-[#1a1d21] shadow-[0_30px_60px_-25px_rgba(0,0,0,0.45)]"
        style={{
          ...paperStyle,
          transformOrigin: '50% 0%',
          transform:
            stage === 'drop' || stage === 'sent'
              ? `translateY(${170}px) scale(0.25)`
              : stage === 'fold'
                ? 'perspective(900px) rotateX(8deg)'
                : 'none',
          opacity: stage === 'sent' ? 0 : 1,
          transition: `left ${FOLD_MS}ms cubic-bezier(.7,0,.2,1), top ${FOLD_MS}ms cubic-bezier(.7,0,.2,1), width ${FOLD_MS}ms cubic-bezier(.7,0,.2,1), height ${FOLD_MS}ms cubic-bezier(.7,0,.2,1), transform ${DROP_MS}ms cubic-bezier(.6,0,.3,1), opacity 300ms ease-in`,
        }}
      >
        <div className="grid h-full content-start gap-2 p-3">
          <div className="flex items-center gap-1.5">
            <FileText className="size-4 shrink-0 text-primary" />
            <span className="truncate font-mono text-[10px] uppercase tracking-[0.06em] text-black/60">{fileName}</span>
          </div>
          <div className="h-[2px] bg-primary" />
          {Array.from({ length: 14 }, (_, i) => (
            <div key={i} className="h-[5px] bg-black/10" style={{ width: `${55 + ((i * 37) % 45)}%` }} />
          ))}
        </div>
      </div>

      {/* WhatsApp, and who it went to */}
      <div className="absolute inset-x-0 top-1/2 grid -translate-y-6 justify-items-center gap-5 px-4">
        <span
          className={cn(
            'grid size-16 place-items-center rounded-full bg-[#25D366] text-white shadow-lg transition-all duration-500',
            stage === 'paper' || stage === 'fold' ? 'scale-50 opacity-0' : 'scale-100 opacity-100',
          )}
          style={stage === 'sent' && !still ? { animation: 'live-ring 900ms ease-out 2' } : undefined}
          aria-hidden="true"
        >
          <WhatsAppIcon className="size-8" />
        </span>
        {stage === 'sent' && (
          <div className="grid justify-items-center gap-4">
            <p className="m-0 text-center font-brand text-[clamp(26px,4vw,40px)] leading-tight tracking-[-0.01em] animate-in fade-in slide-in-from-bottom-2 duration-500 motion-reduce:animate-none">
              Today’s report is out
            </p>
            <p className="m-0 font-mono text-[11px] uppercase tracking-[0.08em] text-muted-foreground">
              {site} · {company} · {fileName}
            </p>
            {names.length > 0 ? (
              <ul className="m-0 flex max-w-[680px] list-none flex-wrap justify-center gap-2 p-0">
                {names.slice(0, 8).map((r, i) => (
                  <li
                    key={r.id}
                    className="flex items-center gap-2 border border-foreground/20 bg-background px-3 py-1.5 text-[14px] animate-in fade-in zoom-in-95 fill-mode-both duration-300 motion-reduce:animate-none"
                    style={{ animationDelay: `${300 + i * 220}ms` }}
                  >
                    <span className="font-medium">{r.name}</span>
                    {r.tag && <span className="text-[12px] text-muted-foreground">{r.tag}</span>}
                    <CheckCheck
                      className="size-4 text-[#53bdeb] animate-in fade-in fill-mode-both duration-300 motion-reduce:animate-none"
                      style={{ animationDelay: `${700 + i * 220}ms` }}
                      aria-label="delivered"
                    />
                  </li>
                ))}
                {names.length > 8 && <li className="px-2 py-1.5 text-[14px] text-muted-foreground">and {names.length - 8} more</li>}
              </ul>
            ) : (
              <p className="m-0 text-[15px] text-muted-foreground">Sent on WhatsApp to the project’s admins and managers.</p>
            )}
          </div>
        )}
      </div>

      <button
        type="button"
        onClick={() => done.current()}
        className="absolute right-6 top-6 border-b border-foreground font-mono text-[11px] uppercase tracking-[0.06em]"
      >
        Back to live
      </button>
    </div>
  )
}
