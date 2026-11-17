// SS-74a (docs/plans/guided-demo-plan.md section 18.5): the one "now" of the dashboard. A real company lives on the
// real date. A learning sample company (lib/sandbox.ts) lives on its own date, the day its planned simulation is at,
// which moves only when the person presses Next day or goes back: there `appNow()` is that date with the real time of
// day, so every "today", date field default, "days late" and "this week" on every page is the game's.
//
// The server says the same (domains/shared/clock.py, from the sample company's token). No imports on purpose: every
// file may use this, lib/utils.ts included.

/** Where this tab keeps its sample company session (lib/sandbox.ts writes it). */
export const SANDBOX_KEY = 'mesiri_sandbox'

/** The sample company's own date (YYYY-MM-DD) while this tab is in one, else null. */
export function sandboxDay(): string | null {
  try {
    const s = JSON.parse(window.sessionStorage.getItem(SANDBOX_KEY) || 'null') as { today?: string; expires_at?: string } | null
    if (!s?.today || !/^\d{4}-\d{2}-\d{2}$/.test(s.today)) return null
    if (s.expires_at && Date.parse(s.expires_at) <= Date.now()) return null
    return s.today
  } catch {
    return null
  }
}

/** Now: the real moment, on the sample company's date while in one. Use it wherever the code means "now" or "today",
 *  never a bare `new Date()`. */
export function appNow(): Date {
  const now = new Date()
  const day = sandboxDay()
  if (!day) return now
  const [y, m, d] = day.split('-').map(Number)
  now.setFullYear(y, m - 1, d)
  return now
}
