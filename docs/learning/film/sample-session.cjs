// LRN-F15: open a page inside the sample company the way the dashboard does (lib/sandbox.ts, lib/clock.ts): the
// person's own token in localStorage, the sample's session (its token, role and own date) in this tab's sessionStorage,
// tied to that own token by the same fingerprint. Then every "today" on every page is the sample's day.
function fingerprint(token) {
  let h = 5381
  for (let i = 0; i < token.length; i++) h = ((h << 5) + h + token.charCodeAt(i)) | 0
  return `${token.length}.${(h >>> 0).toString(36)}`
}

/** What the tab must hold: `own` the person's token, `sample` an answer of POST /learn/sandbox or next-day/go-back. */
function sessionFor(own, sample, role) {
  return {
    token: sample.token,
    expires_at: sample.expires_at,
    name: sample.name || 'Sample company',
    role: sample.role || role,
    user_name: sample.user_name || '',
    today: sample.today || sample.date,
    real: fingerprint(own),
  }
}

/** The pages' theme: light (asked 20 Nov: "can u take in light mode"); THEME=dark for the old look. */
const THEME = process.env.THEME || 'light'

/** A browser context's init script: own token, the sample's session, the theme, the guide's voice off. */
async function enter(ctx, own, session) {
  await ctx.addInitScript(([t, s, theme]) => {
    localStorage.setItem('mesiri_dashboard_token', t)
    if (s) sessionStorage.setItem('mesiri_sandbox', JSON.stringify(s))
    localStorage.setItem('theme', theme)
    localStorage.setItem('mesiri_guide_voice', JSON.stringify({ on: false }))
  }, [own, session, THEME])
}

module.exports = { fingerprint, sessionFor, enter, THEME }
