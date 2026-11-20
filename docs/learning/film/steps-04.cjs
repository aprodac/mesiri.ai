// LRN-F15: episode 4's website steps, done for real in the sample company (record.cjs runs shoot.cjs for each scene on
// its day, as its role, arriving as `play` so that role's own entries of the day are left to do on screen). One async
// action per frame of the scene in episode-04.json; each returns what to light (a selector or a locator) or null.
const near = (pg, text, up = 3) => pg.getByText(text, { exact: true }).first().locator(`xpath=ancestor::*[${up}]`)

/** The three quotations of the starter kit (green_villa.CEMENT_STORY): supplier, their no., cement and steel rates. */
const QUOTES = [['Malabar Cements Agency', 'MCA/Q/0412', 400, 72], ['Kerala Steels', 'KS/Q/2280', 412, 66], ['Sri Hardwares', 'SH/Q/117', 408, 70]]
/** A shadcn (Radix) select: open it, choose the option by its words. */
async function pickRadix(pg, trigger, label) {
  await trigger.first().click()
  await pg.getByRole('option', { name: label, exact: true }).first().click()
  await pg.waitForTimeout(300)
}
/** The n-th item line of a request for quotes: the item from its list, then the quantity. */
async function pickItem(pg, dlg, n, item, qty) {
  await dlg.locator('button').filter({ hasText: /^Item$/ }).first().click()
  const search = dlg.getByPlaceholder('Name or size').last()
  await search.fill(item)
  await pg.waitForTimeout(500)
  await search.locator('xpath=ancestor::div[2]').locator('button').filter({ hasText: new RegExp(`^${item}`) }).first().click()
  await dlg.getByLabel('Quantity').nth(n).fill(qty)
}

module.exports = {
  // Anil, day 3: Ravi's request, Stock's own way out, the move of 40 bags.
  move: [
    async (pg, h) => { await h.go('/materials/requests?project={Green Villa}'); return pg.locator('main button').filter({ hasText: 'Cement100 bags' }).first() },
    async (pg, h) => { await h.go('/materials?project={Green Villa}'); return near(pg, 'Move from Annex', 4) },
    async (pg, h) => {
      await pg.getByText('Move from Annex', { exact: true }).first().click()
      await h.wait(1500)
      const dlg = pg.getByRole('dialog').last()
      await dlg.locator('#transferQuantity').fill('40')
      return dlg
    },
    async (pg, h) => {
      await pg.getByRole('dialog').last().getByRole('button', { name: 'Move it' }).click()
      await h.wait(2500)
      await h.go('/materials?project={Green Villa}')
      return near(pg, 'Cement', 4)
    },
  ],
  // Anil, day 4: the request for quotes (left from day 3), the three quotes from their papers, the cheapest per item.
  compare: [
    async (pg, h) => {
      await h.go('/procurement/quotations?project={Green Villa}')
      await pg.locator('[data-guide="quotes.add"]').first().click()
      await h.wait(1200)
      const dlg = pg.getByRole('dialog').last()
      await pickRadix(pg, dlg.getByRole('combobox').filter({ hasText: 'Choose site' }), 'Main block')
      await pickItem(pg, dlg, 0, 'Cement', '200')
      await dlg.getByRole('button', { name: 'Add item' }).click()
      await pickItem(pg, dlg, 1, 'Steel', '1000')
      for (const s of QUOTES.map((q) => q[0])) {
        await dlg.locator('#rfq-supplier').fill(s)
        await dlg.locator('#rfq-supplier').press('Enter')
        await h.wait(300)
      }
      await dlg.getByRole('button', { name: 'Create RFQ' }).click()
      await h.wait(3000)
      return pg.locator('[data-guide="quotes.suppliers"]').first()
    },
    async (pg, h) => {
      for (const [name, ref, cement, steel] of QUOTES) {
        await pg.locator('[data-guide="quotes.suppliers"] li').filter({ hasText: name }).getByRole('button', { name: 'Record quote' }).click()
        await h.wait(1000)
        const dlg = pg.getByRole('dialog').last()
        await dlg.getByLabel('Cement rate').fill(String(cement))
        await dlg.getByLabel('Steel rate').fill(String(steel))
        await dlg.locator('#q-ref').fill(ref)
        await dlg.getByRole('button', { name: 'Save quote' }).click()
        await h.wait(1800)
      }
      const table = pg.locator('[data-guide="quotes.compare"]').first()
      await table.scrollIntoViewIfNeeded()
      return table
    },
    async (pg) => {
      const box = pg.getByText('Cheapest per item', { exact: true }).first().locator('xpath=ancestor::*[2]')
      await box.scrollIntoViewIfNeeded()
      return box
    },
    async (pg) => pg.getByText('Cheapest per item', { exact: true }).first().locator('xpath=..'),
    async (pg, h) => {
      await pg.getByRole('button', { name: 'Order the cheapest per item' }).click()
      await h.wait(1200)
      const place = pg.getByRole('button', { name: /^Place orders?$/ })
      await place.click()
      await h.wait(3000)
      await h.go('/procurement/orders?project={Green Villa}')
      return '[data-guide="po.list"]'
    },
  ],
}
