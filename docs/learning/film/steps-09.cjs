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

module.exports = {
  noticed: [
    async (pg, h) => { await h.go('/cost/green-red?project={Green Villa}'); return 'main section:has([data-guide]) >> nth=0' },
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
    async (pg, h) => { await h.go('/tasks?view=all&project={Green Villa}'); return visible(pg.locator('[data-guide="tasks.add"]')) },
    async (pg, h) => {
      await visible(pg.locator('[data-guide="tasks.add"]')).click()
      await h.wait(1000)
      const dlg = dialog(pg)
      await dlg.locator('#task-title').fill(TASK)
      const project = dlg.getByRole('combobox').filter({ hasText: /Pick a project/ })
      if (await project.count()) {
        await project.first().click()
        await pg.getByRole('option', { name: 'Green Villa' }).first().click()
        await h.wait(800)
      }
      await dlg.getByRole('combobox').filter({ hasText: /Who does it|Nobody yet/ }).first().click()
      await pg.getByRole('option', { name: /Ravi/ }).first().click()
      await dlg.getByRole('button', { name: 'Tomorrow', exact: true }).click()
      await h.wait(400)
      return dlg
    },
    async (pg, h) => {
      await dialog(pg).getByRole('button', { name: 'Give task' }).click()
      await h.wait(2500)
      return row(pg, TASK)
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
