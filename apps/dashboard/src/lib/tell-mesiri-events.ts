// Tell Mesiri from any page (asked 16 Nov: "from the web dashboard can users message Mesiri?"): the top bar's button,
// the On WhatsApp pop-up's "Send it here" and the walkthroughs' practice steps all open the one Tell Mesiri box
// (components/tell-mesiri/tell-mesiri-dock.tsx), like lib/jump.ts. The same assistant as WhatsApp (WEB-36).
export const TELL_MESIRI_EVENT = 'mesiri:tell'

/** Open the Tell Mesiri box, with these words typed in when given (the person still presses send). */
export function openTellMesiri(text?: string) {
  window.dispatchEvent(new CustomEvent<string | undefined>(TELL_MESIRI_EVENT, { detail: text }))
}
