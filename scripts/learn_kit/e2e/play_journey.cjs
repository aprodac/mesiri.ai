const { chromium } = require('playwright'); const fs = require('fs')
const [,, realJson, outDir, mode] = process.argv
const tok = JSON.parse(fs.readFileSync(realJson)).token
const KIT = require('path').resolve(__dirname, '../../../apps/dashboard/public/learn/kit') + '/'
const MODE_LABEL = { new_to_construction: "I'm new to construction", guided: 'Show me step by step', switching: "I've used other construction software" }[mode || 'guided']
;(async () => {
  const b = await chromium.launch()
  const pg = await (await b.newContext({ viewport: { width: 1280, height: 860 }, acceptDownloads: true })).newPage()
  pg.on('pageerror', (e) => console.log('pageerror', e.message))
  await pg.addInitScript((t) => { localStorage.setItem('mesiri_dashboard_token', t) }, tok)
  let n = 0
  const bubble = pg.locator('[role="dialog"][data-tour]').last()
  const shot = async (name) => { await pg.waitForTimeout(700); await pg.screenshot({ path: `${outDir}/j${String(++n).padStart(2, '0')}-${name}.png` }) }
  const title = async () => (await bubble.locator('#tour-title').innerText().catch(() => '?'))
  const say = async (label) => console.log(`[${label}]`, await title(), '|', (await bubble.locator('#tour-text').innerText().catch(() => '')).slice(0, 110))
  const next = async () => { await bubble.getByRole('button', { name: /^(Next|Done)$/ }).click(); await pg.waitForTimeout(1500) }
  // The date field is a calendar (components/ui/date-picker.tsx): open it, choose month and year, tap the day.
  const pickDate = async (sel, isoDate) => {
    const [y, m, d] = isoDate.split('-').map(Number)
    await pg.locator(sel).click(); await pg.waitForTimeout(400)
    const cal = pg.locator('[data-slot="popover-content"]').last()
    await cal.locator('select').nth(0).selectOption(String(m - 1)); await cal.locator('select').nth(1).selectOption(String(y))
    await cal.locator(`[data-day="${isoDate}"] button`).click()
    await pg.waitForTimeout(300)
  }
  const waitTitle = async (re, ms = 30000) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { if (re.test(await title())) return true; await pg.waitForTimeout(500) } console.log('  !! timeout waiting for', re, 'at', await title()); return false }

  await pg.goto('http://localhost:5173/learn'); await pg.waitForTimeout(4000)
  const q = pg.getByText(MODE_LABEL); if (await q.count()) { await q.first().click(); await pg.waitForTimeout(1500) }
  for (let i = 0; i < 3; i++) { const sk = pg.getByText('Skip tour'); if (await sk.count()) { await sk.first().click(); await pg.waitForTimeout(800) } }
  console.log('start ->'); await pg.getByRole('button', { name: 'Start the guided project' }).first().click()
  console.log('waiting for welcome'); await waitTitle(/Welcome/, 60000); await say('ch0'); await next(); await say('ch0b'); await next()
  await waitTitle(/office/); await say('setup-1'); await shot('setup-pick')
  await pg.getByText('Green Villa', { exact: true }).first().click(); await pg.waitForTimeout(3000); await shot('setup-hello')
  await next(); await waitTitle(/dates/); await say('dates'); await shot('dates')
  await pickDate('#ps-start', '2026-11-02'); await pickDate('#ps-finish', '2027-07-31'); await pg.getByRole('button', { name: 'Save dates' }).click()
  await waitTitle(/contract/i); await say('contract'); await shot('contract')
  await pg.locator('[data-guide="setup.contract"]').click(); await pg.waitForTimeout(1200)
  await pg.locator('#ct-client').click(); await pg.getByRole('option', { name: '+ A new client' }).click(); await pg.getByLabel("New client's name").fill('Dr. Anand Krishnan')
  for (const [k, v] of [['contract_value', '8206050'], ['contract_no', 'GV/2026/007'], ['retention_pct', '5'], ['mobilisation_advance', '820605'], ['advance_recovery_pct', '10'], ['gst_pct', '18'], ['defect_liability_months', '12']]) await pg.fill(`#ct-${k}`, v)
  await pickDate('#ct-signed_on', '2026-10-20')
  await shot('contract-form')
  await pg.locator('button[form="contract-form"]').click()
  await waitTitle(/BOQ/); await say('boq-upload'); await shot('boq-upload')
  await pg.locator('[data-guide="setup.boq"]').click(); await pg.waitForTimeout(1200)
  await pg.setInputFiles('input[type=file]', KIT + 'Green Villa - estimate.xlsx'); await pg.waitForTimeout(4000); await shot('boq-preview')
  await pg.getByRole('button', { name: /^Import \d+ lines/ }).click(); await pg.waitForTimeout(3000)
  const close = pg.getByRole('button', { name: /^Close$/ }); if (await close.count()) await close.first().click().catch(() => {})
  await waitTitle(/Three done/); await say('done3'); await shot('three-done'); await next()
  await waitTitle(/four numbers/, 40000); await say('totals'); await shot('totals'); await next()
  await waitTitle(/Quick check/); await say('ask'); await shot('ask')
  await pg.locator('tr[data-guide="boq.line"]').nth(3).click(); await pg.waitForTimeout(800)
  console.log('  wrong ->', await bubble.locator('[role=status]').last().innerText()); await shot('ask-wrong')
  await pg.locator('tr[data-guide="boq.loss"]').first().click(); await pg.waitForTimeout(800)
  console.log('  right ->', await bubble.locator('[role=status]').last().innerText()); await shot('ask-right'); await next()
  await waitTitle(/count the site/); await say('addall'); await shot('addall')
  await pg.locator('[data-guide="boq.addall"]').click()
  await waitTitle(/plastering/i, 40000); await say('plaster'); await shot('plaster')
  const row = pg.locator('[data-guide="boq.pick"]').first()
  await row.getByRole('combobox').click(); await pg.waitForTimeout(500)
  await pg.getByRole('option', { name: /^4\.1 · Plastering$/ }).click(); await pg.waitForTimeout(400)
  await row.getByRole('button', { name: 'Add to line' }).click()
  await waitTitle(/set up/, 40000); await say('end'); await shot('end')
  await b.close()
})().catch((e) => { console.log('FAILED', e.message.split('\n')[0]); process.exit(1) })
