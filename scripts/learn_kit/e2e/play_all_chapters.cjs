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
    const bx = await cal.locator(`[data-day="${isoDate}"] button`).boundingBox(); const hit = await pg.evaluate(([x,y]) => { const e = document.elementFromPoint(x,y); return e ? e.outerHTML.slice(0,120) + ' pe=' + getComputedStyle(e).pointerEvents : null }, [bx.x+bx.width/2, bx.y+bx.height/2]); console.log('  hit', isoDate, hit); await pg.mouse.click(bx.x+bx.width/2, bx.y+bx.height/2); await pg.waitForTimeout(500); console.log('  field now:', await pg.locator(sel).innerText())
    await pg.waitForTimeout(300)
  }
  const waitTitle = async (re, ms = 30000) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { if (re.test(await title())) return true; await pg.waitForTimeout(500) } console.log('  !! timeout waiting for', re, 'at', await title()); return false }

  await pg.goto('http://localhost:5173/learn'); await pg.waitForTimeout(4000)
  const q = pg.getByText(MODE_LABEL); if (await q.count()) { await q.first().click(); await pg.waitForTimeout(1500) }
  for (let i = 0; i < 3; i++) { const sk = pg.getByText('Skip tour'); if (await sk.count()) { await sk.first().click(); await pg.waitForTimeout(800) } }
  console.log('start ->'); await pg.getByRole('button', { name: 'Start the guided project' }).first().click()
  console.log('waiting for welcome'); await waitTitle(/Welcome/, 60000); await say('ch0'); await next(); await say('ch0b'); await next()
  await waitTitle(/office/); await say('setup-1'); await shot('setup-pick')
  // Picking Green Villa moves the guide on by itself (no Next).
  await pg.getByText('Green Villa', { exact: true }).first().click(); await pg.waitForTimeout(3000); await shot('setup-hello')
  await waitTitle(/dates/); await say('dates'); await shot('dates')
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
  await waitTitle(/at a glance/, 40000); await say('totals'); await shot('totals'); await next()
  await waitTitle(/count the site/); await say('addall'); await shot('addall')
  await pg.locator('[data-guide="boq.addall"]').click()
  await waitTitle(/plastering/i, 40000); await say('plaster'); await shot('plaster')
  // All three plastering entries go on 4.1; each row leaves the list once added.
  for (let i = 0; i < 3; i++) {
    const row = pg.locator('[data-guide="boq.pick"]').first()
    await row.getByRole('combobox').click(); await pg.waitForTimeout(500)
    await pg.getByRole('option', { name: /^4\.1 · Plastering$/ }).click(); await pg.waitForTimeout(400)
    await row.getByRole('button', { name: 'Add to line' }).click(); await pg.waitForTimeout(2000)
  }
  await waitTitle(/Quick check/, 40000); await say('ask'); await shot('ask')
  await pg.locator('tr[data-guide="boq.line"]').nth(3).click(); await pg.waitForTimeout(800)
  console.log('  wrong ->', await bubble.locator('[role=status]').last().innerText()); await shot('ask-wrong')
  await pg.locator('tr[data-guide="boq.loss"]').first().click(); await pg.waitForTimeout(800)
  console.log('  right ->', await bubble.locator('[role=status]').last().innerText()); await shot('ask-right'); await next()

  // ---- every step after the quick check ----
  const bbuttons = async () => (await bubble.locator('button').allInnerTexts().catch(() => [])).map((s) => s.trim()).filter(Boolean)
  const clickIf = async (loc, label) => { if (await loc.count()) { await loc.first().click({ timeout: 8000 }).catch((e) => console.log('   click fail', label || '', e.message.split('\n')[0])); await pg.waitForTimeout(1500); return true } console.log('   not found:', label || ''); return false }
  const skipScenes = async () => { for (let i = 0; i < 4; i++) { const s = pg.getByRole('button', { name: /^Skip$/ }); if (await s.count() && await s.first().isVisible()) { await s.first().click().catch(() => {}); await pg.waitForTimeout(1200) } else break } }
  const briefing = async () => {
    const go = pg.locator('button:visible').filter({ hasText: /Go on with the story|^\s*(Later|Close)\s*$/ })
    if (!(await go.count())) return false
    const part = (await pg.locator('body').innerText()).match(/Your part today[\s\S]{0,260}?(Go on with the story|Later|Close)/)
    console.log('   BRIEFING:', (part ? part[0] : '?').replace(/\n/g, ' · '))
    await go.first().click().catch(() => {}); await pg.waitForTimeout(1500); return true
  }
  const dlg = () => pg.locator('[role=dialog]:not([data-tour])').last()
  const onScreen = async () => {
    const b = await bubble.boundingBox().catch(() => null); const H = 860
    const sx = await pg.evaluate(() => Math.max(...[...document.querySelectorAll('*')].map((e) => e.scrollLeft || 0)))
    return (b ? (b.y + b.height <= H + 1 ? 'bubble on screen' : `BUBBLE CUT OFF (bottom ${Math.round(b.y + b.height)})`) : 'no bubble') + (sx > 0 ? ` · SIDEWAYS SCROLL ${sx}` : '')
  }
  let last = '', same = 0, idle = 0
  for (let k = 0; k < 300; k++) {
    if (!(await bubble.count())) {
      if (await briefing()) continue
      await skipScenes(); await pg.waitForTimeout(4000)
      if (++idle % 5 === 0) console.log('   (waiting, no bubble) ->', pg.url().replace('http://localhost:5173', ''))
      if (idle > 80) { console.log('   GAVE UP waiting'); await shot('gaveup'); break }
      continue
    }
    idle = 0
    const t = await title(); const txt = (await bubble.locator('#tour-text').innerText().catch(() => '')).slice(0, 170)
    const key = t + '|' + txt
    if (key !== last) { same = 0; last = key; console.log(`\n#${k} ${pg.url().replace('http://localhost:5173', '').replace(/\?.*/, '')}  ${await onScreen()}\n   ${t} | ${txt}`); await shot(t.replace(/[^a-z0-9]+/gi, '_').slice(0, 40)) } else same++
    if (same > 12) { console.log('   STUCK, buttons:', await bbuttons()); await shot('stuck'); break }
    if (/^Your turn/i.test(t) && same === 0) {
      if (/the schedule/i.test(t)) { await clickIf(pg.locator('[data-guide="schedule.quick"]'), 'quick'); await clickIf(dlg().getByRole('button', { name: /^Plan \d+/ }), 'plan') }
      else if (/crew Ravi missed/i.test(t)) {
        await clickIf(pg.locator('[data-guide="today.sites"]').getByText('Annex', { exact: true }), 'annex row'); await pg.waitForTimeout(3000)
        console.log('   now on', pg.url().replace('http://localhost:5173', '').replace(/\?.*/, ''), '· bubble still there:', await bubble.count() > 0)
        await clickIf(pg.locator('[data-guide="dayform.add-attendance"]'), 'attendance btn')
        await pg.fill('#att-trade', 'Carpenter'); await pg.fill('#att-count', '2'); await pg.fill('#att-wage', '1000'); await shot('attendance-form')
        await clickIf(dlg().getByRole('button', { name: 'Save attendance' }), 'save att')
      }
      else if (/what they did/i.test(t)) {
        await clickIf(pg.locator('[data-guide="dayform.add-work"]'), 'work btn')
        await pg.fill('#work-what', 'Plinth beam'); await pg.waitForTimeout(300); console.log('   unit filled from BOQ:', await pg.inputValue('#work-unit'))
        await pg.fill('#work-qty', '6'); if (!(await pg.inputValue('#work-unit'))) await pg.fill('#work-unit', 'rmt'); await shot('work-form')
        await clickIf(dlg().getByRole('button', { name: 'Save work' }), 'save work')
      }
      else if (/new problem/i.test(t)) {
        await clickIf(pg.locator('[data-guide="issues.add"]:visible'), 'report btn')
        await pg.locator('#issue-site').click(); await pg.waitForTimeout(400); await clickIf(pg.getByRole('option', { name: /Annex/ }), 'annex opt')
        await clickIf(dlg().getByRole('button', { name: 'Weather' }), 'weather'); await clickIf(dlg().getByRole('button', { name: /^High$/ }), 'high')
        await pg.fill('#issue-what', 'Rain filled the plinth trench; the pump is at the Main block.'); await shot('issue-form')
        await clickIf(dlg().getByRole('button', { name: 'Report issue' }), 'submit issue')
      }
      else if (/tea bill/i.test(t)) {
        await clickIf(pg.locator('[data-guide="exp.add"]:visible'), 'exp btn')
        await pg.fill('#amount', '240'); await pg.locator('#category').click(); await pg.waitForTimeout(400); await clickIf(pg.getByRole('option', { name: /^Food$/ }), 'food')
        await pg.fill('#vendor', 'Tea stall').catch(() => console.log('   no vendor field')); await shot('expense-form')
        console.log('   expense dialog buttons:', (await dlg().locator('button').allInnerTexts()).join(' | '))
        await clickIf(dlg().locator('button[type=submit]'), 'submit expense')
      }
      else if (/approve it/i.test(t)) { await clickIf(pg.locator('[data-guide="wages.approve"]'), 'approve'); await clickIf(pg.getByRole('button', { name: /^(Approve|Yes, approve|Confirm)$/ }), 'confirm') }
      else if (/approve the count/i.test(t)) { await clickIf(pg.getByText('SC-0001', { exact: false }), 'SC-0001'); await pg.waitForTimeout(2000); await clickIf(pg.getByRole('button', { name: /Approve differences/i }), 'approve diff') }
      else if (/running bill|final bill/i.test(t)) { await clickIf(pg.locator('[data-guide="ra.new"]'), 'new ra'); await pg.waitForTimeout(1500); await clickIf(dlg().locator('button').filter({ hasText: /^(Create|Draft|Make|Save)/ }), 'ra create (if any)') }
      else if (/send it/i.test(t)) { await clickIf(pg.locator('[data-guide="ra.submit"]'), 'submit ra'); await pg.waitForTimeout(800); await clickIf(pg.locator('[role=alertdialog] button, [role=dialog]:not([data-tour]) button').filter({ hasText: /^(Submit|Yes|Confirm|Send)/ }), 'confirm submit') }
      else if (/hand it over/i.test(t)) { await clickIf(pg.locator('[data-guide="setup.stage"]').getByRole('button', { name: /Handover/ }), 'handover') }
      else if (/defects period/i.test(t)) { await clickIf(pg.locator('[data-guide="setup.stage"]').getByRole('button', { name: /Defect/ }), 'defect') }
      else if (/close it/i.test(t)) { await clickIf(pg.locator('[data-guide="setup.stage"]').getByRole('button', { name: /Closed/ }), 'closed') }
      await pg.waitForTimeout(4000); await shot('after-' + t.replace(/[^a-z0-9]+/gi, '_').slice(0, 30))
      continue
    }
    const nx = bubble.getByRole('button', { name: /^(Next|Done)$/ })
    if (await nx.count() && await nx.first().isEnabled()) { await nx.first().click().catch(() => {}); await pg.waitForTimeout(1800) }
    else { if (same === 4) console.log('   waiting; buttons:', await bbuttons()); await pg.waitForTimeout(2500) }
    await skipScenes(); await briefing()
    const done = pg.getByText('Green Villa is closed', { exact: true })
    if (await done.count()) { console.log('\nFINISH CARD:', (await pg.locator('[data-guide="journey.done"]').innerText()).replace(/\n/g, ' · ')); await shot('finish'); break }
  }
  await pg.goto('http://localhost:5173/planning/setup'); await pg.waitForTimeout(5000)
  console.log('\nAFTER: Project start Next chip:', await pg.locator('[data-guide="setup.next"]').count(), '· sidebar Set up:', await pg.locator('[data-guide="app.setup"]').count(), '·', (await pg.locator('main').innerText()).match(/Site team[^\n]*\n[^\n]*/)?.[0]?.replace(/\n/g, ' '))
  await shot('final-setup'); await b.close()
})().catch((e) => { console.log('FAILED', e.message.split('\n')[0]); process.exit(1) })
