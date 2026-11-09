// Renders the video's frames: slides (HTML files) and dashboard pages (logged in as the accountant), with highlight
// boxes drawn around the parts being talked about. Input: jobs.json; output: PNGs at 1920x1080.
const { chromium } = require('playwright')
const fs = require('fs')

const jobs = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'))
const tokens = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'))

async function highlight(page, targets) {
  const boxes = []
  for (const t of targets) {
    const loc = t.startsWith('css:') ? page.locator(t.slice(4)) : page.getByText(t, { exact: false })
    const all = await loc.all()
    for (const el of all) {
      if (!(await el.isVisible().catch(() => false))) continue
      const b = await el.boundingBox()
      if (!b || b.x < 230 || b.width < 4) continue // skip the sidebar
      // Grow small labels to their card: the nearest bordered ancestor if it is not huge.
      const card = await el.evaluate((n) => {
        let p = n
        for (let i = 0; i < 4 && p; i++) {
          const cs = getComputedStyle(p)
          const r = p.getBoundingClientRect()
          if ((cs.borderTopWidth !== '0px' || cs.borderLeftWidth !== '0px') && r.width < 900 && r.height < 420 && r.width > 60) {
            return { x: r.x, y: r.y, width: r.width, height: r.height }
          }
          p = p.parentElement
        }
        return null
      })
      boxes.push(card && t.length < 40 ? card : b)
      break
    }
  }
  await page.evaluate((bs) => {
    for (const b of bs) {
      const d = document.createElement('div')
      Object.assign(d.style, {
        position: 'fixed', left: `${b.x - 6}px`, top: `${b.y - 6}px`, width: `${b.width + 12}px`, height: `${b.height + 12}px`,
        border: '4px solid #f59e0b', borderRadius: '12px', boxShadow: '0 0 0 6px rgba(245,158,11,.25)', zIndex: 99999, pointerEvents: 'none',
      })
      document.body.appendChild(d)
    }
  }, boxes)
  return boxes.length
}

;(async () => {
  const browser = await chromium.launch()
  const slide = await browser.newPage({ viewport: { width: 1280, height: 720 }, deviceScaleFactor: 1.5 })
  const contexts = {}
  for (const job of jobs) {
    if (fs.existsSync(job.out) && !job.force) continue
    if (job.kind === 'html') {
      await slide.setContent(fs.readFileSync(job.html, 'utf8'), { waitUntil: 'load' })
      await slide.waitForTimeout(150)
      await slide.screenshot({ path: job.out })
      console.log('slide', job.out)
      continue
    }
    const who = job.as || 'finance'
    if (!contexts[who]) {
      contexts[who] = await browser.newContext({ viewport: { width: 1600, height: 900 }, deviceScaleFactor: 1.2 })
      await contexts[who].addInitScript((t) => localStorage.setItem('mesiri_dashboard_token', t), tokens[who])
    }
    const page = await contexts[who].newPage()
    page.on('pageerror', (e) => console.log('PAGEERR', job.url, e.message))
    await page.goto('http://localhost:5173' + job.url, { waitUntil: 'networkidle' })
    await page.waitForTimeout(1800)
    for (const c of job.click || []) {
      await page.getByText(c, { exact: false }).first().click()
      await page.waitForTimeout(700)
    }
    for (const k of job.keys || []) {
      await page.keyboard.press(k)
      await page.waitForTimeout(500)
    }
    if (job.keys && job.keys.length) await page.waitForTimeout(1200)
    if (job.scroll) {
      await page.getByText(job.scroll, { exact: false }).first().scrollIntoViewIfNeeded()
      await page.evaluate(() => window.scrollBy(0, 200))
      await page.waitForTimeout(400)
    }
    const n = await highlight(page, job.hl || [])
    if ((job.hl || []).length && !n) console.log('NO HIGHLIGHT', job.url, job.hl)
    await page.screenshot({ path: job.out })
    console.log('page', job.url, 'highlights', n)
    await page.close()
  }
  await browser.close()
})()
