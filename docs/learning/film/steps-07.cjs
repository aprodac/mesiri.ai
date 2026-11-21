// LRN-F27: episode 7's website steps, done for real in the sample company (record.cjs runs shoot.cjs for each scene on
// its day, as its role: the owner on day 33; Anil on day 38; Meera then Anil on day 39; Meera on day 40; the owner on
// day 49). One async action per frame of the scene in episode-07.json; each returns what to light (a selector or a
// locator) or null.
const JOY = 'Joy Tiling Works'
const REJECT = 'Measured 81.88 sqm with Joy on the finished ground floor; the bill says 92.'
const dialog = (pg) => pg.getByRole('dialog').last()
const visible = (loc) => loc.locator('visible=true').first()
/** The smallest card or row in the main area holding this text. */
const block = (pg, text) => visible(pg.locator('main').getByText(text, { exact: false }))
  .locator('xpath=ancestor::*[self::tr or self::article or self::section or contains(@class,"rounded-xl")][1]')
const tab = async (pg, h, name) => { await pg.getByRole('tab', { name: new RegExp(`^${name}`) }).click(); await h.wait(1200) }

/** Joy's work order, opened from the list. */
async function openWo(pg, h) {
  await h.go('/subcontract/work-orders')
  await visible(pg.locator('main').getByText(JOY)).click()
  await h.wait(2500)
}

/** Record Joy's bill: this many sqm, their bill number; returns the dialog once the check has answered. */
async function fillBill(pg, h, qty, no) {
  await openWo(pg, h)
  await pg.getByRole('button', { name: /Record bill/ }).first().click()
  await h.wait(1000)
  const dlg = dialog(pg)
  await dlg.getByRole('spinbutton', { name: /Billed now for/ }).first().fill(String(qty))
  await dlg.locator('#b-no').fill(no)
  await h.wait(2500) // the check runs as you type
  return dlg
}

module.exports = {
  order: [
    async (pg, h) => { await h.go('/subcontract/work-orders'); return block(pg, JOY) },
    async (pg, h) => { await openWo(pg, h); return block(pg, 'Floor tiling') },
    async (pg) => visible(pg.locator('main').getByText(/Measured|Billed/)).locator('xpath=ancestor::*[contains(@class,"grid") or contains(@class,"rounded-xl")][1]'),
  ],
  measure: [
    async (pg, h) => { await openWo(pg, h); return pg.getByRole('button', { name: 'Measure', exact: true }) },
    async (pg, h) => {
      await pg.getByRole('button', { name: 'Measure', exact: true }).click()
      await h.wait(900)
      const dlg = dialog(pg)
      await dlg.locator('#m-q').fill('81.88')
      await dlg.locator('#m-n').fill('Ground floor, room by room (A-101 rev B)')
      return dlg
    },
    async (pg, h) => {
      await dialog(pg).getByRole('button', { name: 'Save measurement' }).click()
      await h.wait(2500)
      // The Work tab: the line, now 81.88 done (the Measured tab opens on site-work suggestions: UX-92).
      await tab(pg, h, 'Work')
      return block(pg, 'Floor tiling')
    },
  ],
  bill: [
    async (pg, h) => fillBill(pg, h, 92, 'JTW-014'),
    async (pg) => visible(dialog(pg).getByText(/more than|measured|over/i)).locator('xpath=..'),
    async (pg, h) => {
      await dialog(pg).getByRole('button', { name: /Record/ }).last().click()
      await h.wait(2500)
      await tab(pg, h, 'Bills')
      return block(pg, 'JTW-014')
    },
  ],
  reject: [
    async (pg, h) => { await openWo(pg, h); await tab(pg, h, 'Bills'); return block(pg, 'JTW-014') },
    async (pg, h) => {
      await block(pg, 'JTW-014').getByRole('button', { name: 'Reject' }).click()
      await h.wait(800)
      await dialog(pg).locator('#d-r').fill(REJECT)
      return dialog(pg)
    },
    async (pg, h) => {
      await dialog(pg).getByRole('button', { name: 'Reject' }).click()
      await h.wait(2500)
      return block(pg, 'JTW-014')
    },
  ],
  corrected: [
    async (pg, h) => fillBill(pg, h, 81.88, 'JTW-014A'),
    async (pg, h) => {
      await dialog(pg).getByRole('button', { name: /Record/ }).last().click()
      await h.wait(2500)
      await tab(pg, h, 'Bills')
      return block(pg, 'JTW-014A')
    },
    async (pg) => visible(block(pg, 'JTW-014A').locator('dl')),
  ],
  owner: [
    async (pg, h) => { await openWo(pg, h); return null },
    async (pg, h) => { await tab(pg, h, 'Bills'); return 'main section:has(article)' },
    async (pg) => visible(pg.locator('main').getByText(/Retention/)).locator('xpath=ancestor::*[self::dl or contains(@class,"grid")][1]'),
  ],
}
