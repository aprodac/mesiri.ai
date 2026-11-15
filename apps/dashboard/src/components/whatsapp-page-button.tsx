import * as React from 'react'
import { useLocation } from 'react-router-dom'
import { MessageSquareText } from 'lucide-react'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { WhatsAppPreview } from '@/components/whatsapp-preview'
import { WHATSAPP_PREVIEW_EVENT, openWhatsAppPreview, useWhatsAppExamples } from '@/lib/whatsapp-modal'

// Every page that works from WhatsApp says so in the top bar: one tap opens a pop-up with what to send Mesiri and
// what comes back (guided onboarding, 15 Nov). Pages with no WhatsApp way in show no button; their ? help says why.

/** The pop-up, mounted once in the layout; opened by openWhatsAppPreview(). */
export function WhatsAppPreviewModal() {
  const [open, setOpen] = React.useState(false)
  const { pathname } = useLocation()
  const { page, examples } = useWhatsAppExamples()
  React.useEffect(() => {
    const show = () => setOpen(true)
    window.addEventListener(WHATSAPP_PREVIEW_EVENT, show)
    return () => window.removeEventListener(WHATSAPP_PREVIEW_EVENT, show)
  }, [])
  React.useEffect(() => setOpen(false), [pathname])
  if (!page || examples.length === 0) return null
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="max-h-[90svh] gap-3 overflow-y-auto sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{page.title} from WhatsApp</DialogTitle>
          <DialogDescription>
            Send Mesiri a message like this, as text, a voice note or with a photo. No app to open.
          </DialogDescription>
        </DialogHeader>
        <WhatsAppPreview examples={examples} />
      </DialogContent>
    </Dialog>
  )
}

/** The top-bar button. */
export function WhatsAppPageButton() {
  const { page, examples } = useWhatsAppExamples()
  if (!page || examples.length === 0) return null
  return (
    <button
      type="button"
      onClick={openWhatsAppPreview}
      className="inline-flex h-8 items-center gap-1.5 rounded-full border border-success/30 bg-success-soft px-2.5 text-xs font-medium text-success hover:border-success/60"
      title={`How ${page.title} works from WhatsApp`}
      aria-label={`How ${page.title} works from WhatsApp`}
    >
      <MessageSquareText className="size-4" aria-hidden />
      <span className="hidden sm:inline">On WhatsApp</span>
    </button>
  )
}

/** A small link that opens the pop-up, for the help panel and the page strip. */
export function SeeOnWhatsApp({ onOpen, className }: { onOpen?: () => void; className?: string }) {
  return (
    <button
      type="button"
      onClick={() => {
        onOpen?.()
        openWhatsAppPreview()
      }}
      className={
        'inline-flex items-center gap-1.5 self-start rounded-lg border border-success/30 bg-success-soft px-2.5 py-1 text-xs font-medium text-success hover:border-success/60 ' +
        (className ?? '')
      }
    >
      <MessageSquareText className="size-3.5" aria-hidden /> See how it works on WhatsApp
    </button>
  )
}
