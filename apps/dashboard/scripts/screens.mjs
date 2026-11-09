#!/usr/bin/env node
// UX-10: open every built dashboard page at phone and desktop width, light and dark, take a screenshot,
// and fail on a blank page, a crash screen or a console error. Run before every UX push.
//
//   node scripts/screens.mjs                        # against a dev server on :5173 with a stubbed API
//   BASE=http://localhost:5199 node scripts/screens.mjs
//   TOKEN=<jwt> API=http://localhost:8000 node scripts/screens.mjs   # against a real local API
//   ONLY=/today,/accounts WIDTHS=390 THEMES=light node scripts/screens.mjs
//   OUT=/path/to/dir ROLE=FINANCE node scripts/screens.mjs           # stubbed role (stub mode only)
//
// The page list is read from src/lib/module-map.ts (every page with status 'built') plus the pages
// outside the module map (EXTRA below), so a new built page is checked without editing this file.
import { readFileSync, mkdirSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createRequire } from 'node:module'

const require = createRequire(import.meta.url)
let chromium
try {
  ;({ chromium } = require('playwright'))
} catch {
  ;({ chromium } = require(require.resolve('playwright', { paths: ['/usr/lib/node_modules', '/usr/local/lib/node_modules'] })))
}

const here = dirname(fileURLToPath(import.meta.url))
const BASE = process.env.BASE || 'http://localhost:5173'
const API = process.env.API || 'http://localhost:8000'
const TOKEN = process.env.TOKEN || ''
const ROLE = process.env.ROLE || 'ADMIN'
const OUT = process.env.OUT || join(here, '..', '.screens')
const WIDTHS = (process.env.WIDTHS || '390,1440').split(',').map(Number)
const THEMES = (process.env.THEMES || 'light,dark').split(',')
const ONLY = process.env.ONLY ? process.env.ONLY.split(',') : null

const EXTRA = ['/today', '/reports', '/issues', '/site-log', '/analytics', '/labour', '/projects', '/team', '/company', '/whatsapp', '/settings', '/live']
const PUBLIC = ['/login', '/signup']

function builtPages() {
  const src = readFileSync(join(here, '..', 'src', 'lib', 'module-map.ts'), 'utf8')
  const urls = []
  for (const m of src.matchAll(/url: '([^']+)', status: 'built'/g)) urls.push(m[1])
  return [...new Set([...EXTRA, ...urls])]
}

const pages = (ONLY || [...PUBLIC, ...builtPages()]).map((u) => ({ url: u, auth: !PUBLIC.includes(u) }))
mkdirSync(OUT, { recursive: true })

// Stub mode: the signed-in user, and an empty answer for everything else. Pages must survive "no data".
const ME = { id: 'u1', name: 'Asha Menon', role: ROLE, org_name: 'Acme Builders', organization_id: 'o1', access_policy: { mode: 'all_projects' } }

const browser = await chromium.launch()
const failures = []
for (const width of WIDTHS) {
  for (const theme of THEMES) {
    const ctx = await browser.newContext({ viewport: { width, height: width < 600 ? 844 : 900 } })
    if (!TOKEN) {
      await ctx.route((url) => url.href.startsWith(API), (route) => {
        const u = route.request().url()
        if (u.includes('/auth/me')) return route.fulfill({ json: ME })
        return route.fulfill({ json: [] })
      })
    }
    for (const page of pages) {
      const pg = await ctx.newPage()
      const errors = []
      pg.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`))
      pg.on('console', (m) => {
        if (m.type() !== 'error') return
        const text = m.text()
        // Network noise from the stub or a missing optional endpoint is not a page failure.
        if (/Failed to load resource|ERR_|status of 4\d\d|status of 5\d\d/.test(text)) return
        errors.push(`console: ${text.slice(0, 200)}`)
      })
      await pg.addInitScript(([token, theme, auth]) => {
        try {
          if (auth && token) localStorage.setItem('mesiri_dashboard_token', token)
          else if (auth) localStorage.setItem('mesiri_dashboard_token', 'stub')
          else localStorage.removeItem('mesiri_dashboard_token')
          localStorage.setItem('theme', theme)
          if (theme === 'dark') document.documentElement.classList.add('dark')
        } catch {
          /* storage blocked: the page still renders */
        }
      }, [TOKEN, theme, page.auth])
      await pg.goto(BASE + page.url, { waitUntil: 'networkidle', timeout: 30000 }).catch((e) => errors.push(`goto: ${e.message}`))
      await pg.waitForTimeout(400)
      const state = await pg.evaluate(() => ({
        text: (document.querySelector('main') || document.body).innerText.trim().length,
        crash: /Something went wrong|Unexpected Application Error/i.test(document.body.innerText),
        sideways: document.documentElement.scrollWidth > window.innerWidth + 1,
        path: location.pathname,
      }))
      if (state.text < 15) errors.push('blank page')
      if (state.crash) errors.push('crash screen')
      if (state.sideways) errors.push(`sideways scroll (${width}px)`)
      const name = `${page.url.replace(/^\//, '').replace(/[/?=&]/g, '_') || 'root'}-${width}-${theme}.png`
      await pg.screenshot({ path: join(OUT, name) })
      if (errors.length) failures.push({ page: page.url, width, theme, landed: state.path, errors })
      await pg.close()
    }
    await ctx.close()
  }
}
await browser.close()

const total = pages.length * WIDTHS.length * THEMES.length
console.log(`${total - failures.length}/${total} screens clean · screenshots in ${OUT}`)
for (const f of failures) console.log(`FAIL ${f.page} ${f.width}px ${f.theme}${f.landed !== f.page ? ` (landed ${f.landed})` : ''}: ${f.errors.join('; ')}`)
process.exit(failures.length ? 1 : 0)
