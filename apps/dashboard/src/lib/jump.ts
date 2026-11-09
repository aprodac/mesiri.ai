// The jump box (components/jump-box.tsx, UX-04) listens for this event; anything can open it.
export const JUMP_EVENT = 'mesiri:jump'

/** Open the jump box from anywhere (the sidebar's Search row). */
export function openJump() {
  window.dispatchEvent(new Event(JUMP_EVENT))
}
