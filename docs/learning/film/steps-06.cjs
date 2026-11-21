// LRN-F24: episode 6's website steps, done for real in the sample company (record.cjs runs shoot.cjs for each scene on
// its day, as its role: the owner on day 4; after Ravi's message on day 5, Anil then the owner; Anil on day 6; Meera on
// day 9). One async action per frame of the scene in episode-06.json; each returns what to light (a selector or a
// locator) or null.
const MIXER = 'Concrete mixer'
const TASK = "Get Kerala Earthmovers' mechanic to the Annex mixer before 8 am"
const FIXED = 'Mechanic rewound the motor before work; mixer running from 8 am'
/** The smallest block in the page's main area that holds this text. */
const block = (pg, text) => pg.locator('main').getByText(text, { exact: false }).locator('visible=true').first()
  .locator('xpath=ancestor::*[self::tr or self::li or self::article or contains(@class,"border-b") or contains(@class,"rounded-xl")][1]')
const problem = (pg) => pg.locator('main').getByText(/Concrete mixer breakdown/).locator('visible=true').first()
const dialog = (pg) => pg.getByRole('dialog').last()

/** The sample's date of a plan day, read off the day banner ("Day 9 of 62 · Mon, 30 Nov"). */
async function dateOf(pg, n) {
  const text = await pg.getByText(/Day \d+ of \d+ · /).first().innerText()
  const [, d, dd, mon] = text.match(/Day (\d+) of \d+ · \w+, (\d+) (\w+)/)
  const today = new Date(`${dd} ${mon} ${new Date().getFullYear()} 12:00`)
  return new Date(today.getTime() - (Number(d) - n) * 86400000)
}

/** Pick a date in the date picker with this id (the calendar opens on the month it holds; move if needed). */
async function pick(pg, h, id, date) {
  await pg.locator(`#${id}`).click()
  await h.wait(500)
  const cal = pg.locator('[data-slot="calendar"], .rdp-root').last()
  const month = date.toLocaleString('en-US', { month: 'long' })
  for (let i = 0; i < 2 && !(await cal.getByText(new RegExp(month)).count()); i++) {
    await cal.getByRole('button', { name: /next/i }).first().click()
    await h.wait(300)
  }
  await cal.locator(`button:text-is("${date.getDate()}")`).filter({ hasNot: pg.locator('[disabled]') }).first().click()
  await h.wait(300)
}

/** Enter a hire bill for the mixer: the week of its log, plan days 2 to 7 (Monday to Saturday). */
async function enterBill(pg, h, hours, amount) {
  const from = await dateOf(pg, 2)
  const to = await dateOf(pg, 7)
  await block(pg, MIXER).getByRole('button', { name: /Enter a bill/ }).click()
  await h.wait(900)
  await pick(pg, h, 'hb-from', from)
  await pick(pg, h, 'hb-to', to)
  const dlg = dialog(pg)
  await dlg.locator('#hb-h').fill(String(hours))
  await dlg.locator('#hb-a').fill(String(amount))
  await dlg.locator('#hb-r').fill('KEE/2027/0118')
  return dlg
}

module.exports = {
  machines: [
    async (pg, h) => { await h.go('/equipment'); return block(pg, MIXER) },
    async (pg, h) => { await h.go('/equipment/log'); return block(pg, MIXER) },
    async (pg, h) => {
      await h.go('/equipment')
      return pg.locator('main').getByText(/Worked th/).first().locator('xpath=ancestor::*[contains(@class,"grid")][1]')
    },
  ],
  problem: [
    async (pg, h) => { await h.go('/issues'); return block(pg, 'Concrete mixer breakdown') },
    async (pg, h) => {
      await problem(pg).click()
      await h.wait(1200)
      await pg.getByRole('button', { name: /Make a task/ }).last().click()
      await h.wait(900)
      const dlg = dialog(pg)
      await dlg.locator('#task-title').fill(TASK)
      await dlg.getByRole('combobox').filter({ hasText: /Who does it|Nobody yet/ }).first().click()
      await pg.getByRole('option', { name: /Ravi/ }).first().click()
      await dlg.getByRole('button', { name: 'Tomorrow', exact: true }).click()
      await h.wait(400)
      return dlg
    },
    async (pg, h) => {
      await dialog(pg).getByRole('button', { name: 'Give task' }).click()
      await h.wait(2500)
      // The issue's panel now says who is on it (the task, linked).
      return pg.getByText(/who is on it/i).locator('visible=true').first().locator('xpath=ancestor::section[1] | ..').first()
    },
  ],
  owner: [
    async (pg, h) => { await h.go('/'); return null },
    // Home has no line for an open problem (UX-91): Green Villa's row counts them.
    async (pg) => pg.locator('main').getByText('Green Villa', { exact: true }).locator('visible=true').last()
      .locator('xpath=ancestor::*[contains(@class,"border-b") or self::a or self::li][1]'),
    async (pg, h) => {
      await h.go('/issues')
      await problem(pg).click()
      await h.wait(1500)
      return pg.getByText(/who is on it/i).locator('visible=true').first().locator('xpath=ancestor::section[1] | ..').first()
    },
  ],
  fixed: [
    async (pg, h) => { await h.go('/tasks?view=all'); await pg.getByText(TASK).locator('visible=true').first().click(); await h.wait(1200); return 'aside[aria-label="Task detail"]' },
    async (pg, h) => {
      await pg.locator('aside[aria-label="Task detail"]').getByRole('button', { name: 'Done', exact: true }).click()
      await h.wait(2000)
      // Done, it leaves the open list: shown where it went.
      await h.go('/tasks?view=done')
      return block(pg, TASK)
    },
    async (pg, h) => {
      await h.go('/issues')
      await problem(pg).click()
      await h.wait(1200)
      await pg.getByRole('button', { name: /Mark fixed/ }).last().click()
      await h.wait(800)
      const dlg = dialog(pg)
      await dlg.locator('textarea, input[type="text"]').first().fill(FIXED)
      await dlg.getByRole('button', { name: 'Mark fixed' }).click()
      await h.wait(2500)
      await h.go('/issues?status=RESOLVED')
      return block(pg, 'Concrete mixer breakdown')
    },
  ],
  bill: [
    async (pg, h) => { await h.go('/equipment/hire'); return block(pg, MIXER) },
    async (pg, h) => enterBill(pg, h, 42, 18900),
    async (pg, h) => {
      await dialog(pg).getByRole('button', { name: 'Check the bill' }).click()
      await h.wait(2500)
      await pg.keyboard.press('Escape')
      return block(pg, MIXER)
    },
  ],
  agreed: [
    async (pg, h) => { await h.go('/equipment/hire'); return block(pg, MIXER) },
    async (pg, h) => {
      pg.once('dialog', (d) => d.accept()) // "Remove this bill?"
      await block(pg, MIXER).getByRole('button', { name: 'Remove' }).first().click()
      await h.wait(2000)
      return enterBill(pg, h, 36, 16200)
    },
    async (pg, h) => {
      await dialog(pg).getByRole('button', { name: 'Check the bill' }).click()
      await h.wait(2500)
      await pg.keyboard.press('Escape')
      return block(pg, MIXER)
    },
  ],
}
