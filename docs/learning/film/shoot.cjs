#!/usr/bin/env node
// FILM-02: the dashboard screens an episode shows (scenes of kind "screen": `shot`, `url`, `wait`), captured from a
// local copy of Mesiri with the demo company, never production. 1600×1000 at 2x, dark theme, into .cache/shots.
//
//   node docs/learning/film/shoot.cjs 02 <token> [http://localhost:5199]
//
// The token is a demo owner's (scripts/training-video/cost/seed.py writes admin.token); the dashboard must point at
// the local API that has the demo company. See README.md, "Screens".
const { chromium } = require('playwright')
const { readFileSync, mkdirSync } = require('fs')
const { join } = require('path')
const [, , ep = '01', token, base = 'http://localhost:5199'] = process.argv
if (!token) throw new Error('usage: shoot.cjs <episode> <token> [dashboard url]')
const script = JSON.parse(readFileSync(join(__dirname, `episode-${ep.padStart(2, '0')}.json`), 'utf8'))
const out = join(__dirname, '.cache', 'shots')
mkdirSync(out, { recursive: true })
;(async () => {
  const b = await chromium.launch()
  const ctx = await b.newContext({ viewport: { width: 1600, height: 1000 }, deviceScaleFactor: 2, colorScheme: 'dark' })
  await ctx.addInitScript((t) => {
    localStorage.setItem('mesiri_dashboard_token', t)
    localStorage.setItem('theme', 'dark')
    localStorage.setItem('mesiri_guide_voice', JSON.stringify({ on: false }))
  }, token)
  for (const sc of script.scenes.filter((s) => s.kind === 'screen')) {
    const pg = await ctx.newPage()
    await pg.goto(base + sc.url)
    await pg.waitForTimeout(sc.wait || 4500)
    await pg.keyboard.press('Escape').catch(() => {}) // a first-visit tour, if one opened
    await pg.waitForTimeout(400)
    await pg.screenshot({ path: join(out, `${sc.shot}.png`) })
    console.log(sc.shot, sc.url)
    await pg.close()
  }
  await b.close()
})()
