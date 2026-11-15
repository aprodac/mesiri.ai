import { useLocation } from 'react-router-dom'
import { findPage, type ModulePage } from './module-map'

// The "this page on WhatsApp" pop-up (components/whatsapp-page-button.tsx) listens for this event, so the top bar,
// the ? help panel and the page's first-visit strip all open the same one (like lib/jump.ts).
export const WHATSAPP_PREVIEW_EVENT = 'mesiri:whatsapp-preview'

/** Open the current page's WhatsApp preview from anywhere. */
export function openWhatsAppPreview() {
  window.dispatchEvent(new Event(WHATSAPP_PREVIEW_EVENT))
}

/** wa.me wants the number as digits only. */
export function waLink(number: string, text: string): string {
  return `https://wa.me/${number.replace(/\D/g, '')}?text=${encodeURIComponent(text)}`
}

/** The WhatsApp examples of the page at this address, if it is built and has any. */
export function useWhatsAppExamples(): { page: ModulePage | null; examples: NonNullable<ModulePage['whatsapp']> } {
  const { pathname, search } = useLocation()
  const page = findPage(pathname, search)?.page ?? null
  return { page, examples: page?.status === 'built' ? page.whatsapp ?? [] : [] }
}
