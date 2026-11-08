// Records every scene of the sales video (Playwright, Chromium), timed to the narration.
//
//   NODE_PATH=$(npm root -g) node tools/sales_video/record.js OUT_DIR [scene ...]
//
// Reads OUT_DIR/timing.json (voice.py) and OUT_DIR/demo.json (setup_demo.py). Cards and the chat are this folder's
// HTML pages; the rest is the real dashboard (http://localhost:5173, API on :8000) on the demo company. Each scene is
// OUT_DIR/scenes/<id>.webm, with OUT_DIR/scenes/<id>.json saying how many seconds to cut from its start (the page
// loading before the narration starts).
const { chromium } = require('playwright')
const fs = require('fs')
const path = require('path')

const OUT = process.argv[2]
const ONLY = process.argv.slice(3)
const HERE = __dirname
const timing = JSON.parse(fs.readFileSync(path.join(OUT, 'timing.json'), 'utf8'))
const demo = JSON.parse(fs.readFileSync(path.join(OUT, 'demo.json'), 'utf8'))
const W = 1600, H = 900
const APP = 'http://localhost:5173'
const API = 'http://localhost:8000'
const STRUCTURE = path.join(OUT, '..', '..', 'structure.pdf')
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

async function api(method, url, body) {
  const res = await fetch(`${API}${url}`, { method, headers: { Authorization: `Bearer ${demo.token}`, 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined })
  if (!res.ok) throw new Error(`${method} ${url}: ${res.status} ${await res.text()}`)
  return res.json()
}

// Undo the work at a place (so a re-recording shows the change happen again).
async function clear(placeLabel) {
  const places = (await api('GET', `/projects/${demo.project}/places`)).places
  const place = places.find((p) => p.label === placeLabel)
  if (!place) return
  for (const w of (await api('GET', `/projects/${demo.project}/places/${place.id}/work`)).work) {
    if (w.place === placeLabel) await api('DELETE', `/progress/activities/${w.id}`, { reason: 'sales video re-take' })
  }
}

async function work(place, kind, finished, day = 8) {
  return api('POST', '/progress/activities', { project_id: demo.project, site_id: demo.site, activity_date: `2026-11-0${day}`, work_type: kind, narrative: `${place} ${kind}`, place, finished, quantities: [] })
}

// --- what is drawn over the dashboard ---------------------------------------------------------------------------
const OVERLAY = `
(() => {
  if (window.__ov) return
  window.__ov = true
  const css = document.createElement('style')
  css.textContent = \`
    #ov-part { position: fixed; top: 64px; right: 24px; z-index: 99999; background: #0f172a; color: #fff; font: 600 18px Inter, sans-serif;
      padding: 10px 18px; border-radius: 999px; box-shadow: 0 6px 20px rgba(0,0,0,.2); }
    #ov-value { position: fixed; top: 64px; left: 50%; transform: translate(-50%, -20px); opacity: 0; z-index: 99999; background: #facc15;
      color: #111; font: 700 22px Inter, sans-serif; padding: 12px 24px; border-radius: 14px; box-shadow: 0 8px 26px rgba(0,0,0,.25);
      transition: all .6s ease; }
    #ov-value.on { opacity: 1; transform: translate(-50%, 0); }
    #ov-hl { position: fixed; z-index: 99998; pointer-events: none; border: 4px solid #facc15; border-radius: 14px;
      box-shadow: 0 0 0 9999px rgba(15,23,42,.18), 0 0 26px rgba(250,204,21,.9); transition: all .5s ease; opacity: 0; }
    #ov-phone { position: fixed; right: 36px; bottom: 140px; width: 360px; z-index: 99999; background: #111; border-radius: 34px; padding: 10px;
      box-shadow: 0 20px 50px rgba(0,0,0,.35); transform: translateY(30px); opacity: 0; transition: all .5s ease; }
    #ov-phone.on { transform: none; opacity: 1; }
    #ov-phone .scr { background: #efeae2; border-radius: 26px; overflow: hidden; }
    #ov-phone .top { background: #075e54; color: #fff; font: 700 17px Inter, sans-serif; padding: 14px 16px; }
    #ov-phone .msgs { padding: 12px; display: flex; flex-direction: column; gap: 8px; min-height: 160px; }
    #ov-phone .m { max-width: 85%; padding: 9px 12px; border-radius: 10px; font: 16px/1.35 Inter, sans-serif; box-shadow: 0 1px 1px rgba(0,0,0,.1);
      animation: ovin .4s ease; }
    #ov-phone .me { align-self: flex-end; background: #d9fdd3; }
    #ov-phone .bot { align-self: flex-start; background: #fff; }
    @keyframes ovin { from { opacity: 0; transform: translateY(8px) } to { opacity: 1; transform: none } }
  \`
  document.head.appendChild(css)
  for (const id of ['ov-part', 'ov-value', 'ov-hl']) { const d = document.createElement('div'); d.id = id; document.body.appendChild(d) }
  const ph = document.createElement('div'); ph.id = 'ov-phone'
  ph.innerHTML = '<div class="scr"><div class="top">Mesiri</div><div class="msgs"></div></div>'
  document.body.appendChild(ph)
  document.getElementById('ov-part').style.display = 'none'
  const loop = () => {
    const el = window.__hlEl, box = document.getElementById('ov-hl')
    if (el && el.isConnected) {
      const r = el.getBoundingClientRect(), p = 8
      Object.assign(box.style, { opacity: 1, left: r.left - p + 'px', top: r.top - p + 'px', width: r.width + 2 * p + 'px', height: r.height + 2 * p + 'px' })
    } else box.style.opacity = 0
    requestAnimationFrame(loop)
  }
  loop()
})()`

async function prep(page, scene) {
  await page.evaluate(OVERLAY)
  await page.evaluate(({ part, value }) => {
    const p = document.getElementById('ov-part')
    if (part) { p.textContent = part; p.style.display = 'block' }
    document.getElementById('ov-value').textContent = value ? '✓ ' + value : ''
  }, { part: scene.part, value: scene.value })
}
const value = (page) => page.evaluate(() => document.getElementById('ov-value').textContent && document.getElementById('ov-value').classList.add('on'))
async function hl(page, locator, scroll = true) {
  if (!locator) return page.evaluate(() => { window.__hlEl = null })
  const el = await locator.first().elementHandle({ timeout: 3000 }).catch(() => null)
  if (!el) return console.log('  (nothing to highlight)')
  await el.evaluate((e, scroll) => { if (scroll) e.scrollIntoView({ behavior: 'smooth', block: 'center' }); window.__hlEl = e }, scroll)
}
async function scrollTo(page, locator, block = 'start') {
  const el = await locator.first().elementHandle({ timeout: 8000 }).catch(() => null)
  if (el) await el.evaluate((e, b) => e.scrollIntoView({ behavior: 'smooth', block: b }), block)
}
async function phone(page, messages) {
  await page.evaluate(() => document.getElementById('ov-phone').classList.add('on'))
  for (const [who, text, wait] of messages) {
    await sleep(wait || 900)
    await page.evaluate(({ who, text }) => {
      const m = document.createElement('div'); m.className = `m ${who}`; m.innerHTML = text
      document.querySelector('#ov-phone .msgs').appendChild(m)
    }, { who, text })
  }
}
const phoneOff = (page) => page.evaluate(() => document.getElementById('ov-phone').classList.remove('on'))
// react-query refetches on window focus: what was just saved shows without a reload.
const refetch = (page) => page.evaluate(() => { document.dispatchEvent(new Event('visibilitychange')); window.dispatchEvent(new Event('visibilitychange')); window.dispatchEvent(new Event('focus')) })

// --- the scenes -------------------------------------------------------------------------------------------------
const SCENES = {
  async card(page, scene) {
    const t = JSON.stringify(scene.lines.map((l) => [l.start, l.dur]))
    await page.goto(`file://${HERE}/cards.html?scene=${scene.visual}&t=${encodeURIComponent(t)}`)
    await page.waitForLoadState('networkidle')
    return []
  },
  async chat_footings(page, scene) {
    const t = JSON.stringify(scene.lines.map((l) => [l.start, l.dur]))
    await page.goto(`file://${HERE}/chat.html?t=${encodeURIComponent(t)}`)
    return []
  },
  async rec_documents(page, scene, L) {
    await page.goto(`${APP}/planning/documents?project=${demo.project}`)
    await page.getByText('Building permit').first().waitFor()
    await prep(page, scene)
    const file = page.locator('input[type=file]').first()
    return [
      [L[0].start + 0.3, () => hl(page, page.getByText('Drop files here'))],
      [L[0].start + L[0].dur * 0.6, () => file.setInputFiles(STRUCTURE)],
      [L[1].start, () => hl(page, page.locator('li', { hasText: 'Footing & Column Details' }))],
      [L[2].start, () => file.setInputFiles(path.join(OUT, 'S-101 Column layout rev C.pdf'))],
      [L[2].start + 2.0, () => hl(page, page.locator('li', { hasText: 'Column Layout' }))],
      [L[3].start, async () => { await hl(page, null); await page.getByRole('button', { name: /^Contract/ }).click() }],
      [L[3].start + 0.8, () => hl(page, page.locator('nav[aria-label=Folders]'))],
      [L[4].start, async () => { await hl(page, null); await page.getByRole('button', { name: /^All/ }).click() }],
      [L[4].start + 0.3, () => phone(page, [['me', 'Latest S-101 drawing ayakku', 300], ['bot', '📎 <b>S-101 Column layout rev C.pdf</b>', 1600], ['bot', 'S-101 Column Layout rev C sent. Rev B is out of date.', 700]])],
      [L[4].start + L[4].dur * 0.6, () => value(page)],
    ]
  },
  async rec_check(page, scene, L) {
    await page.goto(`${APP}/planning/drawing-check`)
    await page.locator('input[type=file]').first().waitFor({ state: 'attached' })
    await prep(page, scene)
    return [
      [L[0].start + 0.5, () => page.locator('input[type=file]').first().setInputFiles(STRUCTURE)],
      [L[0].start + L[0].dur * 0.7, () => hl(page, page.getByText('Sheets', { exact: true }).first())],
      [L[1].start, async () => { await scrollTo(page, page.getByRole('heading', { name: 'Sheets' })); await sleep(700); await hl(page, page.locator('table').first()) }],
      [L[2].start, async () => { await scrollTo(page, page.getByRole('heading', { name: 'What to check' })); await sleep(700); await hl(page, page.getByText('F6 combined footing').locator('xpath=ancestor::li')) }],
      [L[3].start + L[3].dur * 0.4, () => value(page)],
    ]
  },
  async rec_quantities(page, scene, L) {
    await page.goto(`${APP}/planning/drawing-check`)
    await page.locator('input[type=file]').first().setInputFiles(STRUCTURE)
    await page.getByText('Foundation from the structural drawings').waitFor({ timeout: 30000 })
    await prep(page, scene)
    const heading = page.getByText('Foundation from the structural drawings')
    return [
      [L[0].start, () => scrollTo(page, heading)],
      [L[1].start, () => hl(page, heading.locator('xpath=ancestor::section').locator('> div').nth(1))],
      [L[2].start, async () => { await hl(page, heading.locator('xpath=ancestor::section').locator('table').first()) }],
      [L[3].start, async () => { await hl(page, null); await scrollTo(page, page.getByText('Draft BOQ', { exact: false }).first()); await sleep(800); await hl(page, page.getByText('Draft BOQ', { exact: false }).first().locator('xpath=ancestor::section[1]')) }],
      [L[3].start + L[3].dur * 0.5, () => value(page)],
    ]
  },
  async rec_live(page, scene, L) {
    // The structural set uploaded in the Documents scene: tracked, some footings reported, B3 not yet.
    const first = await api('GET', `/projects/${demo.project}/live-maps`)
    for (const d of first.untracked) await api('POST', `/documents/${d.id}/track`)
    const found = (await api('GET', `/projects/${demo.project}/live-maps`)).maps.find((m) => m.kind === 'foundation')
    if (found.summary.done + found.summary.in_progress <= 1) {
      for (const g of ['A3', 'A5', 'A7', 'B5', 'B7', 'D3', 'D5', 'D7']) await work(`${g} footing concreted`, 'Footing concrete', true, 6)
      for (const g of ['E5 footing steel tied', 'E7 PCC done', 'A9 excavation']) await work(g, 'Footing work', false, 7)
    }
    await clear('Foundation / B3')
    await page.goto(`${APP}/planning/live?project=${demo.project}`)
    await page.getByText(/footings done/).first().waitFor({ timeout: 20000 })
    await prep(page, scene)
    const canvas = page.locator('.touch-none').first()
    const b3 = () => canvas.getByRole('button', { name: 'B3', exact: true })
    return [
      [L[0].start + 0.4, async () => { await work('B3 footing concreted', 'Footing concrete', true); await refetch(page) }],
      [L[0].start + 1.6, () => hl(page, b3(), false)],
      [L[1].start, () => hl(page, page.locator('aside section').first(), false)],
      [L[2].start, async () => { await b3().click(); await sleep(900); await hl(page, page.locator('aside section').first(), false) }],
      [L[3].start, () => { hl(page, null); return value(page) }],
    ]
  },
  async rec_places(page, scene, L) {
    await clear('First Floor / Room 2')
    await work('first floor room 2', 'Brickwork', true, 5)
    await page.goto(`${APP}/planning/places?project=${demo.project}`)
    await page.getByRole('table').waitFor({ timeout: 20000 })
    await prep(page, scene)
    const grid = page.getByRole('table')
    const ff = page.locator('tr', { hasText: 'First Floor' }).first()
    return [
      [0.2, () => scrollTo(page, grid, 'start')],
      [L[0].start + 0.5, () => hl(page, grid)],
      [L[1].start + 0.4, () => phone(page, [['me', 'First floor room 2 plastering done', 200]])],
      [L[1].start + 1.6, async () => { await work('first floor room 2', 'Plastering', true); await refetch(page) }],
      [L[1].start + 2.4, () => hl(page, page.locator('tr', { hasText: 'Room 2' }).nth(1))],
      [L[2].start, async () => {
        await hl(page, ff)
        const r = await api('GET', `/projects/${demo.project}/places/progress?place=first%20floor`)
        const rooms = r.places.filter((p) => p.depth > 0 && p.left.length).map((p) => `${p.name}: ${p.left.join(', ').toLowerCase()}`)
        await page.evaluate(() => { document.querySelector('#ov-phone .msgs').innerHTML = '' })
        await phone(page, [['me', 'First floor-il enthokke baaki?', 200], ['bot', `<b>First Floor</b>, left:<br>${rooms.join('<br>')}`, 1500]])
      }],
      [L[2].start + L[2].dur * 0.6, () => value(page)],
    ]
  },
}

async function record(browser, scene) {
  const dir = path.join(OUT, 'scenes', scene.id + '-raw')
  fs.rmSync(dir, { recursive: true, force: true })
  const context = await browser.newContext({ viewport: { width: W, height: H }, recordVideo: { dir, size: { width: W, height: H } } })
  const page = await context.newPage()
  const born = Date.now()
  if (!scene.visual.startsWith('card') && !scene.visual.startsWith('chat')) {
    await page.goto(`${APP}/`)
    await page.evaluate((t) => localStorage.setItem('mesiri_dashboard_token', t), demo.token)
  }
  const L = scene.lines
  const run = SCENES[scene.visual] || SCENES.card
  const steps = await run(page, scene, L)
  const ready = Date.now()
  const errors = []
  await Promise.all(steps.map(([at, fn]) => sleep(at * 1000).then(fn).catch((e) => errors.push(String(e).slice(0, 160)))))
  await sleep(Math.max(0, ready + scene.total * 1000 - Date.now()))
  await context.close()
  const raw = fs.readdirSync(dir).find((f) => f.endsWith('.webm'))
  fs.renameSync(path.join(dir, raw), path.join(OUT, 'scenes', scene.id + '.webm'))
  fs.rmSync(dir, { recursive: true, force: true })
  fs.writeFileSync(path.join(OUT, 'scenes', scene.id + '.json'), JSON.stringify({ cut: (ready - born) / 1000, total: scene.total, errors }))
  console.log(scene.id, `${scene.total.toFixed(1)}s`, errors.length ? errors : '')
}

;(async () => {
  fs.mkdirSync(path.join(OUT, 'scenes'), { recursive: true })
  const browser = await chromium.launch()
  for (const scene of timing) {
    if (ONLY.length && !ONLY.includes(scene.id)) continue
    await record(browser, scene)
  }
  await browser.close()
})()
