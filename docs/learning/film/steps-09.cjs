// LRN-F29: episode 9's website steps, done for real in the sample company (record.cjs runs shoot.cjs for each scene on
// its day, as its role: Anil on day 18; the owner on days 25 and 30). One async action per frame of the scene in
// episode-09.json; each returns what to light (a selector or a locator) or null.
const TASK = 'Mark every conduit point before the next room is plastered'
const visible = (loc) => loc.locator('visible=true').first()
const dialog = (pg) => pg.getByRole('dialog').last()
/** The smallest row or card in the main area holding this text exactly. */
const row = (pg, text) => visible(pg.locator('main').getByText(text, { exact: true }))
  .locator('xpath=ancestor::*[self::tr or self::li or self::article or contains(@class,"border-b") or contains(@class,"rounded-xl")][1]')
const card = (pg, text) => visible(pg.locator('main').getByText(text))
  .locator('xpath=ancestor::*[contains(@class,"rounded-xl") or self::section][1]')
const panel = (pg, part) => pg.locator(`[data-guide="line.${part}"]`)
/** The sample's date of a plan day, read off the day banner ("Day 19 of 62 · Thu, 10 Dec"), as YYYY-MM-DD. */
async function dateOf(pg, n) {
  const text = await pg.getByText(/Day \d+ of \d+ · /).first().innerText()
  const [, d, dd, mon] = text.match(/Day (\d+) of \d+ · \w+, (\d+) (\w+)/)
  const today = new Date(`${dd} ${mon} ${new Date().getFullYear()} 12:00`)
  const at = new Date(today.getTime() - (Number(d) - n) * 86400000)
  return `${at.getFullYear()}-${String(at.getMonth() + 1).padStart(2, '0')}-${String(at.getDate()).padStart(2, '0')}`
}

module.exports = {
  noticed: [
    async (pg, h) => {
      // This week so far, Monday to Wednesday: the three days the plastering was redone (green_villa.REWORK).
      await h.go('/cost/green-red?project={Green Villa}')
      const from = await dateOf(pg, 16)
      const to = await dateOf(pg, 18)
      await h.go(`/cost/green-red?project={Green Villa}&from=${from}&to=${to}`)
      return 'main section:has([data-guide]) >> nth=0'
    },
    async (pg) => row(pg, 'Plastering'),
    async (pg, h) => {
      await visible(pg.locator('main').getByText('Plastering', { exact: true })).click()
      await h.wait(5000)
      return panel(pg, 'work')
    },
    async (pg) => panel(pg, 'labour'),
  ],
  materials: [
    async (pg, h) => { await h.go('/cost/materials?project={Green Villa}'); return card(pg, 'Used over the work') },
    async (pg) => row(pg, 'Cement'),
    async (pg) => visible(pg.locator('main table')),
  ],
  acted: [
    async (pg, h) => { await h.go('/tasks?view=all&project={Green Villa}'); return '[data-guide="tasks.list"]' },
    async (pg) => row(pg, TASK),
    async (pg, h) => {
      await visible(pg.getByText(TASK)).click()
      await h.wait(1500)
      return 'aside[aria-label="Task detail"]'
    },
  ],
  back: [
    async (pg, h) => { await h.go('/cost/green-red?project={Green Villa}'); return 'main section:has([data-guide]) >> nth=0' },
    async (pg) => row(pg, 'Plastering'),
    async (pg, h) => { await h.go('/cost/budget?project={Green Villa}'); return card(pg, 'Labour') },
  ],
  owner: [
    async (pg, h) => {
      await h.go('/accounts/projects/{Green Villa}')
      // "Books or real" needs Cost control's figures for the company (a slower read): wait for it.
      await pg.getByText('Books margin').first().waitFor({ timeout: 90000 })
      await h.wait(1500)
      return null
    },
    async (pg) => card(pg, 'Books margin'),
    async (pg) => card(pg, 'Finish against the BOQ budget'),
    async (pg, h) => { await h.go('/cost/budget?project={Green Villa}'); return visible(pg.locator('main table')) },
  ],
}
