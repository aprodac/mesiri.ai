/** How long a Live report line takes to write itself, by its length:
 * slow enough to watch, quick enough not to drag (WEB-37). */
export function inkDuration(text: string): number {
  return Math.min(3200, 600 + text.length * 45)
}

/** The thread from the message is drawn before the line starts writing. */
export const THREAD_MS = 800

/** How long a line takes to gather out of dust, or crumble into it. */
export const DUST_MS = 1500

/** The replay's snap is slower: dust blowing away should be watched. */
export const SNAP_MS = 2000
