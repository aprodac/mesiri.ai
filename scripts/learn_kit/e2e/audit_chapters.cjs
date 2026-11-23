// Plays the guided project's story chapters from the bubble's chapter list and records, for every step, where it is,
// what it lights up and a screenshot: the check that each step shows the very thing its words name (23 Nov 2026,
// "I don't see the correct specific thing, and one is empty"). Local only (README.md), not CI.
//   node audit_chapters.cjs <real.json> <out dir> [first chapter number] [last chapter number]
const { chromium } = require('playwright'); const fs = require('fs')
const [,, realJson, outDir, first = '4', last = '15'] = process.argv
const tok = JSON.parse(fs.readFileSync(realJson)).token
fs.mkdirSync(outDir, { recursive: true })
;(async () => {
  const b = await chromium.launch()
  const pg = await (await b.newContext({ viewport: { width: 1440, height: 900 } })).newPage()
  pg.on('pageerror', (e) => console.log('pageerror', e.message))
  await pg.addInitScript((t) => { localStorage.setItem('mesiri_dashboard_token', t) }, tok)
  const bubble = pg.locator('[role="dialog"][data-tour]').last()
  const title = async () => (await bubble.locator('#tour-title').innerText({ timeout: 2000 }).catch(() => ''))
  const waitTitle = async (re, ms = 60000) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { if (re.test(await title())) return true; await pg.waitForTimeout(500) } return false }
  const lit = () => pg.evaluate(() => {
    // The lit window (components/tour.tsx): the one element whose shadow dims the rest.
    const spot = [...document.querySelectorAll('[data-tour] > div[aria-hidden]')].find((d) => d.style.boxShadow.includes('9999px'))
    if (!spot) return 'nothing lit'
    const r = spot.getBoundingClientRect()
    return `${Math.round(r.width)}x${Math.round(r.height)} at ${Math.round(r.left)},${Math.round(r.top)}`
  })
  await pg.goto('' + (process.env.APP || 'http://localhost:5173') + '/learn'); await pg.waitForTimeout(4000)
  const q = pg.getByText('Show me step by step'); if (await q.count()) { await q.first().click(); await pg.waitForTimeout(1500) }
  for (let i = 0; i < 3; i++) { const sk = pg.getByText('Skip tour'); if (await sk.count()) { await sk.first().click(); await pg.waitForTimeout(800) } }
  await pg.getByRole('button', { name: /Start the guided project/ }).first().click()
  if (!(await waitTitle(/./, 120000))) { await pg.screenshot({ path: `${outDir}/start.png` }); console.log('no bubble after start') }
  for (let ch = Number(first); ch <= Number(last); ch++) {
    const select = bubble.locator('select').first()
    const label = await select.locator('option').nth(ch - 1).innerText()
    await select.selectOption({ index: ch - 1 }); await pg.waitForTimeout(2500)
    let last = ''
    for (let s = 0; s < 12; s++) {
      // Days may be playing to this chapter's day: wait for the bubble to come back.
      // Days may be playing to this chapter's day, then the morning briefing opens: close it to go on.
      for (let w = 0; w < 120 && !(await bubble.isVisible().catch(() => false)); w++) {
        const go = pg.getByRole('button', { name: /^(Close|Skip|Skip scene|Continue|Got it)$/i })
        if (await go.count()) await go.first().click().catch(() => {})
        await pg.waitForTimeout(5000)
      }
      await pg.waitForTimeout(3500)
      const t = await title()
      const chap = await bubble.innerText().then((x) => (x.match(/Chapter (\d+) of/) || [])[1]).catch(() => '')
      if (chap && Number(chap) !== ch) break
      if (t === last) break
      last = t
      const text = (await bubble.locator('#tour-text').innerText().catch(() => '')).replace(/\s+/g, ' ')
      const l = await lit()
      const url = pg.url().replace('' + (process.env.APP || 'http://localhost:5173') + '', '')
      const file = `${outDir}/c${String(ch).padStart(2, '0')}-s${s + 1}.png`
      await pg.screenshot({ path: file })
      console.log(`[${label} ${s + 1}] ${t} | ${url} | lit=${JSON.stringify(l)}\n    ${text.slice(0, 160)}`)
      const nx = bubble.getByRole('button', { name: /^(Next|Done|Skip this|I pressed Cancel)$/ })
      if (!(await nx.count())) break
      await nx.first().click().catch(() => {})
      await pg.waitForTimeout(1000)
    }
  }
  await b.close()
})()
