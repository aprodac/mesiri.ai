// What someone joining a site needs to start reporting (SS-18, WEB-17):
// Mesiri's number and what to send. Mesiri can't message a new person first
// (WhatsApp allows that only through an approved template, SS-12), so the
// owner forwards this, exactly as the WhatsApp shared-contact flow does.

export function inviteText({ number, name, site }: { number: string; name?: string; site?: string }): string {
  const hello = name ? `Hi ${name.split(/\s+/)[0]}, please` : 'Please'
  return (
    `${hello} send today's site work${site ? ` for ${site}` : ''} to Mesiri on WhatsApp: ${number}. ` +
    'A voice note is fine, in any language: who worked, what got done, anything that held you up.'
  )
}

/** A wa.me link that opens a chat (with `to`, or a contact picker) with the text typed in. */
export function whatsappShareLink(text: string, to?: string | null): string {
  const digits = (to ?? '').replace(/\D/g, '')
  return `https://wa.me/${digits}?text=${encodeURIComponent(text)}`
}
