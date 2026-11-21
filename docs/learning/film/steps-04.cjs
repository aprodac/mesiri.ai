// LRN-F15: episode 4's website steps, done for real in the sample company (record.cjs runs shoot.cjs for each scene on
// its day, as its role, arriving as `play` so that role's own entries of the day are left to do on screen). One async
// action per frame of the scene in episode-04.json; each returns what to light (a selector or a locator) or null.
/** A Pending deliveries card by its words ("200 bags still to come"). */
const card = (pg, words) => pg.locator('main section article, main div').filter({ has: pg.getByText(words, typeof words === 'string' ? { exact: true } : {}) }).filter({ has: pg.locator('[data-guide="pending.came"]') }).last()
const near = (pg, text, up = 3) => pg.getByText(text, { exact: true }).first().locator(`xpath=ancestor::*[${up}]`)

/** The three quotations of the starter kit (green_villa.CEMENT_STORY): supplier, their no., cement and steel rates. */
const QUOTES = [['Malabar Cements Agency', 'MCA/Q/0412', 400, 72], ['Kerala Steels', 'KS/Q/2280', 412, 66], ['Sri Hardwares', 'SH/Q/117', 408, 70]]
/** A shadcn (Radix) select: open it, choose the option by its words. */
async function pickRadix(pg, trigger, label) {
  await trigger.first().click()
  await pg.getByRole('option', { name: label, exact: true }).first().click()
  await pg.waitForTimeout(300)
}
/** The day before the one the date field shows (the sample's own today), picked on the calendar: a date in the story
 *  that moves with the week the sample company was opened in. */
async function pickDayBefore(pg, sel) {
  await pg.locator(sel).click()
  await pg.waitForTimeout(400)
  const cal = pg.locator('[data-slot="popover-content"]').last()
  const today = await cal.locator('[data-selected="true"], [aria-selected="true"]').first().locator('xpath=ancestor-or-self::*[@data-day][1]').getAttribute('data-day')
  const d = new Date(`${today}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() - 1)
  const iso = d.toISOString().slice(0, 10)
  const [y, m] = iso.split('-').map(Number)
  await cal.locator('select').nth(0).selectOption(String(m - 1))
  await cal.locator('select').nth(1).selectOption(String(y))
  await cal.locator(`[data-day="${iso}"] button`).click()
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
      // From Ravi's request (UX-85): its cement stays linked, raised to the month's 200 bags; the steel added.
      await h.go('/materials/requests?project={Green Villa}')
      await pg.locator('main button').filter({ hasText: 'Cement100 bags' }).first().click()
      await h.wait(800)
      await pg.getByRole('button', { name: 'Get quotes' }).first().click()
      await h.wait(1500)
      const dlg = pg.getByRole('dialog').filter({ hasText: 'Ask for quotes' }).last()
      await dlg.getByLabel('Quantity').nth(0).fill('200')
      await dlg.getByRole('button', { name: 'Add item' }).click()
      await pickItem(pg, dlg, 1, 'Steel', '1000')
      for (const s of QUOTES.map((q) => q[0])) {
        await dlg.locator('#rfq-supplier').fill(s)
        await dlg.locator('#rfq-supplier').press('Enter')
        await h.wait(300)
      }
      await dlg.getByRole('button', { name: 'Create RFQ' }).click()
      await h.wait(3000)
      if (!(await pg.locator('[data-guide="quotes.suppliers"]').count())) {
        await h.go('/procurement/quotations?project={Green Villa}')
        await pg.getByText('RFQ-0001').first().click()
        await h.wait(1500)
      }
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
        await dlg.locator('#q-delivery').fill('2')  // the papers: "Delivery in 2 days from the order"
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
  // Ravi, day 6: Malabar's lorry, recorded against the order: 190 bags on challan MCA/DC/2611, 10 still to come.
  gate: [
    async (pg, h) => {
      await h.go('/procurement/pending?project={Green Villa}&site={Green Villa › Main block}')
      return card(pg, '200 bags still to come')
    },
    async (pg, h) => {
      await card(pg, '200 bags still to come').locator('[data-guide="pending.came"]').click()
      await h.wait(1500)
      await pg.locator('[data-guide="po.receive"]').last().click()  // the order's panel, then its delivery form
      await h.wait(1500)
      const dlg = pg.getByRole('dialog').filter({ hasText: 'Challan no.' }).last()
      await dlg.getByLabel('Cement accepted').fill('190')
      await dlg.locator('#receive-challan').fill('MCA/DC/2611')
      await dlg.locator('#receive-by').fill('Ravi')
      return dlg
    },
    async (pg, h) => {
      await pg.getByRole('button', { name: 'Save delivery' }).click()
      await h.wait(3000)
      await h.go('/procurement/pending?project={Green Villa}&site={Green Villa › Main block}')
      return card(pg, /^10 bags still to come/)
    },
  ],
  // Meera, day 9: Malabar's bill MCA/INV/2611 as it came, line by line (UX-87): 190 bags at Rs 410 against the site's Rs 400.
  match: [
    async (pg, h) => {
      await h.go('/finance/vendors')
      await pg.getByText('Malabar Cements Agency', { exact: true }).first().click()
      await h.wait(3000)
      return pg.locator('main').getByText('We owe', { exact: true }).first().locator('xpath=ancestor::*[3]')
    },
    async (pg, h) => {
      await pg.getByRole('tab', { name: /Not billed/ }).or(pg.getByRole('button', { name: /^Not billed/ })).first().click()
      await h.wait(1500)
      await pg.locator('main li').filter({ hasText: /190 bags/ }).first().locator('input[type="checkbox"]').check()
      await pg.getByRole('button', { name: 'Bill these' }).click()
      await h.wait(1500)
      const dlg = pg.getByRole('dialog').filter({ has: pg.locator('#b-amount') }).last()
      await dlg.getByLabel(/rate on the bill$/).first().fill('410')
      await dlg.locator('#b-amount').fill('91922')
      await dlg.locator('#b-gst').fill('14022')
      await dlg.locator('#b-no').fill('MCA/INV/2611')
      await pickDayBefore(pg, '#b-date')  // the bill's own date, the Sunday; Meera books it on Monday
      return dlg.locator('[data-guide="bill.lines"]')
    },
    async (pg) => pg.locator('[data-guide="bill.differs"]').first(),
    async (pg, h) => {
      await pg.getByRole('dialog').filter({ has: pg.locator('#b-amount') }).last().getByRole('button', { name: 'Record bill' }).click()
      await h.wait(3000)
      await pg.getByRole('tab', { name: /Bills to pay/ }).or(pg.getByRole('button', { name: /^Bills to pay/ })).first().click()
      await h.wait(1500)
      return pg.locator('main').getByText(/MCA\/INV\/2611/).first().locator('xpath=ancestor::*[3]')
    },
    async (pg, h) => {
      // She takes it back (Expenses, the bill's menu, Take back). The plan's own check sees it taken back, so the
      // corrected bill MCA/INV/2611-R and the return settled come on day 10 as the story has them (the owner sees both).
      await h.go('/finance/expenses')
      const row = pg.locator('main tr, main li').filter({ hasText: 'MCA/INV/2611' }).first()
      await row.getByRole('button', { name: /^More for/ }).click()
      await h.wait(600)
      await pg.getByRole('menuitem', { name: /Take back/ }).click()
      await h.wait(800)
      const dlg = pg.getByRole('dialog').filter({ hasText: /^Take back/ }).last()
      await dlg.getByRole('button', { name: /^Take back$/ }).click()
      await h.wait(2500)
      // A bill taken back leaves the list; Malabar's account shows what is owed without it.
      await h.go('/finance/vendors')
      await pg.getByText('Malabar Cements Agency', { exact: true }).first().click()
      await h.wait(3000)
      return pg.locator('main').getByText('We owe', { exact: true }).first().locator('xpath=ancestor::*[3]')
    },
  ],
  // Ravi, day 16 (the month's end): the Main block's store counted; cement 3 bags under the book, wastage. Kept for the owner.
  count: [
    async (pg, h) => {
      await h.go('/materials/counts?project={Green Villa}&site={Green Villa › Main block}')
      await pg.getByRole('button', { name: /^Count all/ }).first().click()
      await h.wait(2500)
      return '[data-guide="counts.sheet"]'
    },
    async (pg, h) => {
      const row = pg.locator('[data-guide="counts.sheet"] div').filter({ has: pg.getByLabel('Counted Cement') }).filter({ hasText: /Book [0-9,.]+ bags/ }).last()
      const book = Number((await row.innerText()).match(/Book ([0-9,.]+) bags/)[1].replace(/,/g, ''))
      await pg.getByLabel('Counted Cement').fill(String(book - 3))  // counted bag by bag: three fewer than the book
      await h.wait(500)
      await pickRadix(pg, pg.getByRole('combobox', { name: 'Why Cement differs' }), 'Wastage')
      return row
    },
    async (pg, h) => {
      await pg.getByRole('button', { name: 'Save count' }).click()
      await h.wait(2500)
      return pg.locator('[data-guide="counts.list"] li').first()
    },
  ],
  // The owner, day 16: Malabar's page (what is owed now), then the month's count, approved.
  owner: [
    async (pg, h) => {
      await h.go('/finance/vendors')
      await pg.getByText('Malabar Cements Agency', { exact: true }).first().click()
      await h.wait(3000)
      await pg.getByRole('tab', { name: /Bills to pay/ }).or(pg.getByRole('button', { name: /^Bills to pay/ })).first().click()
      await h.wait(1500)
      return pg.locator('main').getByText(/MCA\/INV\/2611-R/).first().locator('xpath=ancestor::*[3]')
    },
    async (pg, h) => {
      await pg.getByRole('tab', { name: /^Returns/ }).or(pg.getByRole('button', { name: /^Returns/ })).first().click()
      await h.wait(1500)
      return pg.locator('main').getByText(/DN-0001/).first().locator('xpath=ancestor::*[2]')
    },
    async (pg, h) => {
      await h.go('/materials/counts?project={Green Villa}&site={Green Villa › Main block}')
      await pg.locator('[data-guide="counts.list"] li').first().click()
      await h.wait(1500)
      return '[data-guide="counts.sheet"]'
    },
    async (pg, h) => {
      await pg.getByRole('button', { name: 'Approve differences' }).click()
      await h.wait(2500)
      return '[data-guide="counts.sheet"]'
    },
  ],
}
