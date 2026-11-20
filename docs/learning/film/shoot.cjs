#!/usr/bin/env node
// FILM-02: the pictures an episode's "screen" scenes show, into .cache/shots (1600×1000 at 2x), and where each marked
// thing sits on them (.cache/shots/<shot>.json: name → {x, y, w, h} as fractions), which build.mjs turns into the
// camera's focus and the highlight boxes (`{ "mark": "name" }`), so nothing is placed by guesswork.
//
//   node docs/learning/film/shoot.cjs 01 <token> [http://localhost:5173] [http://localhost:8000]
//
// Three kinds of picture:
// - a Mesiri page (`url`): from a local copy of Mesiri, never production, with a demo or sample company's token (for the
//   sample company, the token POST /learn/sandbox returns). `{Green Villa}` in the url is that project's id. `scroll`: a
//   selector brought to the top first. `marks`: name → a selector on the page.
// - a paper from the starter kit (`paper`: { "pdf": "<file in public/learn/kit>", "page": 1, "marks": { name: "words" } }):
//   the page as it prints, on a dark desk; a mark is the run of words on the page.
// - a sheet from the kit (`sheet`: { "xlsx": "<file>", "sheet": "BOQ", "rows": 14, "marks": { name: "<item no.>" } }):
//   the workbook's rows drawn as a spreadsheet; a mark is the row whose first cell is that item number.
// Theme dark, the guide's voice off, any first-visit tour closed.
const { chromium } = require('playwright')
const { readFileSync, writeFileSync, mkdirSync, existsSync } = require('fs')
const { join, resolve } = require('path')
const { spawnSync } = require('child_process')

const [, , ep = '01', token, base = 'http://localhost:5173', apiBase = 'http://localhost:8000'] = process.argv
const script = JSON.parse(readFileSync(join(__dirname, `episode-${ep.padStart(2, '0')}.json`), 'utf8'))
const out = join(__dirname, '.cache', 'shots')
const KIT = resolve(__dirname, '../../../apps/dashboard/public/learn/kit')
const PY = existsSync(resolve(__dirname, '../../../.venv/bin/python')) ? resolve(__dirname, '../../../.venv/bin/python') : 'python3'
const W = 1600, H = 1000
mkdirSync(out, { recursive: true })

const esc = (t) => String(t ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;')
const saveMarks = (shot, marks) => writeFileSync(join(out, `${shot}.json`), JSON.stringify(marks, null, 1))

async function projectIds() {
  if (!token) return {}
  const r = await fetch(`${apiBase}/projects`, { headers: { Authorization: `Bearer ${token}` } })
  const body = await r.json()
  const list = Array.isArray(body) ? body : body.items || body.projects || []
  return Object.fromEntries(list.map((p) => [p.name, p.id]))
}

/** Words of a PDF page with their boxes (points), from pdftotext -bbox. */
function pdfWords(pdf, page) {
  const r = spawnSync('pdftotext', ['-bbox', '-f', String(page), '-l', String(page), pdf, '-'], { encoding: 'utf8' })
  const size = /<page width="([\d.]+)" height="([\d.]+)"/.exec(r.stdout)
  const words = [...r.stdout.matchAll(/<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">([^<]*)<\/word>/g)]
    .map((m) => ({ x0: +m[1], y0: +m[2], x1: +m[3], y1: +m[4], t: m[5].replace(/&amp;/g, '&') }))
  return { width: +size[1], height: +size[2], words }
}

/** The box round the first run of words matching `phrase` (fractions of the page); "line:" before it takes the whole
 *  line that run is on (a contract term's label and its value). */
function findPhrase({ width, height, words }, phrase) {
  const whole = phrase.startsWith('line:')
  const want = phrase.replace(/^line:\s*/, '').split(/\s+/)
  for (let i = 0; i + want.length <= words.length; i++) {
    if (want.every((w, j) => words[i + j].t === w)) {
      let run = words.slice(i, i + want.length)
      if (whole) {
        const mid = (run[0].y0 + run[0].y1) / 2
        run = words.filter((w) => w.y0 <= mid && w.y1 >= mid)
      }
      const x0 = Math.min(...run.map((w) => w.x0)), y0 = Math.min(...run.map((w) => w.y0))
      const x1 = Math.max(...run.map((w) => w.x1)), y1 = Math.max(...run.map((w) => w.y1))
      return { x: x0 / width, y: y0 / height, w: (x1 - x0) / width, h: (y1 - y0) / height }
    }
  }
  throw new Error(`"${phrase}" not found on the page`)
}

/** A page of the kit's PDF on a dark desk; its marks as fractions of the picture. */
async function paperShot(ctx, sc) {
  const pdf = join(KIT, sc.paper.pdf)
  const page = sc.paper.page || 1
  const png = join(out, `${sc.shot}-page`)
  spawnSync('pdftoppm', ['-png', '-r', '220', '-f', String(page), '-l', String(page), '-singlefile', pdf, png])
  const layout = pdfWords(pdf, page)
  const pg = await ctx.newPage()
  const img = readFileSync(`${png}.png`).toString('base64')
  await pg.setContent(`<body style="margin:0;width:${W}px;height:${H}px;background:radial-gradient(circle at 50% 40%,#2a2d33,#0d0e10);display:grid;place-items:center">
    <img id="p" src="data:image/png;base64,${img}" style="max-width:${W - 80}px;max-height:${H - 60}px;box-shadow:0 20px 60px rgba(0,0,0,.6)"></body>`)
  await pg.waitForTimeout(300)
  const box = await pg.locator('#p').boundingBox()
  const marks = {}
  for (const [name, phrase] of Object.entries(sc.paper.marks || {})) {
    const f = findPhrase(layout, phrase)
    marks[name] = { x: (box.x + f.x * box.width) / W, y: (box.y + f.y * box.height) / H, w: (f.w * box.width) / W, h: (f.h * box.height) / H }
  }
  marks.page = { x: box.x / W, y: box.y / H, w: box.width / W, h: box.height / H }
  await pg.screenshot({ path: join(out, `${sc.shot}.png`) })
  await pg.close()
  return marks
}

/** The kit's workbook drawn as a spreadsheet (a light grid, as Excel shows it); a mark is a row by its item number. */
async function sheetShot(ctx, sc) {
  const r = spawnSync(PY, ['-c', `
import json, sys, openpyxl
ws = openpyxl.load_workbook(sys.argv[1], data_only=True)[sys.argv[2]]
print(json.dumps([[c for c in row] for row in ws.iter_rows(values_only=True)], default=str))`, join(KIT, sc.sheet.xlsx), sc.sheet.sheet || 'BOQ'], { encoding: 'utf8' })
  if (r.status !== 0) throw new Error(r.stderr)
  const rows = JSON.parse(r.stdout)
  const keep = sc.sheet.only ? rows.filter((row, i) => i === 0 || !row[0] || sc.sheet.only.includes(String(row[0]))) : rows.slice(0, sc.sheet.rows || 20)
  const cols = 'ABCDEFGHIJ'.slice(0, Math.max(...keep.map((x) => x.length)))
  const cell = (v, i) => {
    if (v === null || v === 'None') return '<td></td>'
    const num = typeof v === 'number'
    return `<td style="text-align:${num ? 'right' : 'left'}${i === 1 ? ';min-width:330px' : ''}">${num ? v.toLocaleString('en-IN') : esc(v)}</td>`
  }
  const kind = (row) => (row[0] === 'Item no.' ? 'class="hd"' : !row[0] && row[1] ? 'class="sec"' : '')
  // A title row (text in the first cell only) runs across the columns, as Excel shows it.
  const title = (row) => row[0] && row.slice(1).every((v) => v === null || v === 'None')
  const line = (row) => (title(row) ? `<td colspan="${cols.length}" style="border-right-color:transparent">${esc(row[0])}</td>` : row.map(cell).join(''))
  const body = keep.map((row, n) => `<tr data-key="${esc(row[0])}" ${kind(row)}><th>${n + 1}</th>${line(row)}</tr>`).join('')
  const pg = await ctx.newPage()
  // A short sheet (a few vendors) is drawn larger, so it fills the picture instead of a strip at the top.
  const fontPx = Math.min(30, Math.max(15, Math.floor(450 / keep.length)))
  await pg.setContent(`<body style="margin:0;width:${W}px;height:${H}px;background:#fff;font:${fontPx}px Calibri,Arial,sans-serif;color:#111">
    <div style="height:34px;background:#217346;color:#fff;display:flex;align-items:center;padding:0 16px;font-weight:600">${esc(sc.sheet.xlsx)} · ${esc(sc.sheet.sheet || 'BOQ')}</div>
    <table style="border-collapse:collapse;margin:0;width:100%"><tr class="cl"><th></th>${[...cols].map((c) => `<th>${c}</th>`).join('')}</tr>${body}</table>
    <style>table{font-size:inherit}td,th{border:1px solid #d4d4d4;padding:3px 10px;white-space:nowrap;max-width:620px;overflow:hidden}th{background:#f3f3f3;color:#555;font-weight:400;min-width:34px}
    tr.hd td{font-weight:700;background:#f8f8f8}tr.sec td{font-weight:700;background:#eef6f0}</style></body>`)
  const marks = {}
  for (const [name, key] of Object.entries(sc.sheet.marks || {})) {
    const b = await pg.locator(`tr[data-key="${key}"]`).first().boundingBox()
    marks[name] = { x: b.x / W, y: b.y / H, w: b.width / W, h: b.height / H }
  }
  await pg.screenshot({ path: join(out, `${sc.shot}.png`) })
  await pg.close()
  return marks
}

/** A page of the local Mesiri. */
async function pageShot(ctx, sc, ids) {
  const url = sc.url.replace(/\{([^}]+)\}/g, (_, name) => {
    if (!ids[name]) throw new Error(`no project "${name}" for this token`)
    return ids[name]
  })
  const pg = await ctx.newPage()
  await pg.goto(base + url)
  await pg.waitForTimeout(sc.wait || 4500)
  await pg.keyboard.press('Escape').catch(() => {}) // a first-visit tour, if one opened
  await pg.waitForTimeout(400)
  if (sc.scroll) {
    await pg.locator(sc.scroll).first().evaluate((e) => e.scrollIntoView({ block: 'start' }))
    await pg.evaluate((by) => {
      const el = document.scrollingElement
      el.scrollBy(0, -by)
      document.querySelectorAll('main, [data-scroll], .overflow-auto').forEach((s) => s.scrollBy?.(0, -by))
    }, sc.scrollOffset ?? 90)
    await pg.waitForTimeout(600)
  }
  const marks = {}
  for (const [name, sel] of Object.entries(sc.marks || {})) {
    const b = await pg.locator(sel).first().boundingBox()
    if (!b) throw new Error(`${sc.shot}: "${sel}" is not on the page`)
    marks[name] = { x: b.x / W, y: b.y / H, w: b.width / W, h: b.height / H }
  }
  await pg.screenshot({ path: join(out, `${sc.shot}.png`) })
  await pg.close()
  return marks
}

/** LRN-F15: a "steps" scene, done for real: steps-NN.cjs gives one async action per frame, `(pg, h) => selector`
 *  (what to light, or null); a picture after each, its mark saved as `mark`. */
async function stepsShots(ctx, sc, ids) {
  const file = join(__dirname, `steps-${ep.padStart(2, '0')}.cjs`)
  const acts = require(file)[sc.id]
  if (!acts || acts.length !== sc.frames.length) throw new Error(`${sc.id}: steps-${ep}.cjs needs ${sc.frames.length} actions`)
  const pg = await ctx.newPage()
  const h = {
    url: (u) => base + u.replace(/\{([^}]+)\}/g, (_, name) => ids[name]),
    go: async (u, wait = 4500) => {
      await pg.goto(h.url(u))
      await pg.waitForTimeout(wait)
      await pg.keyboard.press('Escape').catch(() => {})
      await pg.waitForTimeout(300)
    },
    kit: (name) => join(KIT, name),
    wait: (ms) => pg.waitForTimeout(ms),
  }
  for (const [i, act] of acts.entries()) {
    const shot = sc.frames[i].shot || `ep${ep.padStart(2, '0')}-${sc.id}-${i + 1}`
    const sel = await act(pg, h)
    await pg.waitForTimeout(700)
    const marks = {}
    if (sel) {
      const box = await (typeof sel === 'string' ? pg.locator(sel) : sel).first().boundingBox()
      if (!box) throw new Error(`${shot}: the mark is not on the page`)
      marks.mark = { x: box.x / W, y: box.y / H, w: box.width / W, h: box.height / H }
    }
    await pg.screenshot({ path: join(out, `${shot}.png`) })
    saveMarks(shot, marks)
    console.log(shot, sel ? 'mark' : '(no mark)')
  }
  await pg.close()
}

;(async () => {
  const b = await chromium.launch()
  const ctx = await b.newContext({ viewport: { width: W, height: H }, deviceScaleFactor: 2, colorScheme: 'dark' })
  await ctx.addInitScript((t) => {
    if (t) localStorage.setItem('mesiri_dashboard_token', t)
    localStorage.setItem('theme', 'dark')
    localStorage.setItem('mesiri_guide_voice', JSON.stringify({ on: false }))
  }, token || '')
  const ids = script.scenes.some((s) => (s.kind === 'screen' && s.url && !s.paper && !s.sheet) || s.kind === 'steps') ? await projectIds() : {}
  for (const sc of script.scenes.filter((s) => s.kind === 'steps')) {
    if (process.env.ONLY && process.env.ONLY !== sc.id) continue
    await stepsShots(ctx, sc, ids)
  }
  for (const sc of script.scenes.filter((s) => s.kind === 'screen')) {
    if (process.env.ONLY && process.env.ONLY !== sc.shot) continue
    const marks = sc.paper ? await paperShot(ctx, sc) : sc.sheet ? await sheetShot(ctx, sc) : await pageShot(ctx, sc, ids)
    saveMarks(sc.shot, marks)
    console.log(sc.shot, Object.keys(marks).join(', ') || '(no marks)')
  }
  await b.close()
})().catch((e) => {
  console.error(e.message)
  process.exit(1)
})
