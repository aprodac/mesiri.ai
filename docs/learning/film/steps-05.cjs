// LRN-F15: episode 5's website steps, done for real in the sample company (record.cjs runs shoot.cjs for each scene on
// its day, as its role: Meera on day 4; the owner, then Meera, on day 7, kept for the next scene). One async action per
// frame of the scene in episode-05.json; each returns what to light (a selector or a locator) or null.
const row = (pg, name) => pg.locator('main tr').filter({ hasText: name }).first()

module.exports = {
  advance: [
    async (pg, h) => { await h.go('/labour/advances?project={Green Villa}'); return '[data-guide="advances.give"]' },
    async (pg, h) => {
      await pg.locator('[data-guide="advances.give"]').click()
      await h.wait(900)
      const dlg = pg.getByRole('dialog').last()
      await dlg.locator('select#who').selectOption({ label: 'Suresh · mason' })
      await dlg.locator('input#amt').fill('2000')
      await dlg.locator('select#site').selectOption({ label: 'Green Villa › Main block' })
      await dlg.locator('select#acct').selectOption({ label: 'Petty cash · Main block' })
      return dlg
    },
    async (pg, h) => {
      await pg.getByRole('dialog').last().getByRole('button', { name: /^Give ₹/ }).click()
      await h.wait(2500)
      return pg.getByText('Outstanding', { exact: true }).first().locator('xpath=ancestor::*[contains(.,"taken back")][1]')
    },
  ],
  muster: [
    async (pg, h) => {
      await h.go('/labour?view=muster&project={Green Villa}')
      await pg.locator('select[aria-label="Site"]').selectOption({ label: 'Green Villa › Main block' })
      await h.wait(2500)
      return 'main table'
    },
    async (pg) => row(pg, 'Sunil'),
    async (pg) => row(pg, 'Helper (headcount)'),
  ],
  sheet: [
    async (pg, h) => { await h.go('/labour/wages?project={Green Villa}'); return '[data-guide="wages.stats"]' },
    async (pg) => row(pg, 'Suresh'),
    async (pg) => row(pg, 'Rahim'),
    async (pg, h) => {
      await pg.locator('[data-guide="wages.approve"]').click()
      await h.wait(2500)
      return '[data-guide="wages.stats"]'
    },
  ],
  pay: [
    async (pg, h) => {
      await h.go('/labour/wages?project={Green Villa}')
      await pg.locator('main button:has-text("Pay ₹")').first().click()
      await h.wait(1200)
      const dlg = pg.getByRole('dialog').last()
      await dlg.locator('select').first().selectOption({ label: 'Federal Bank current account' })
      return dlg
    },
    async (pg, h) => {
      await pg.getByRole('dialog').last().getByRole('button', { name: /^Pay ₹/ }).click()
      await h.wait(3000)
      return '[data-guide="wages.stats"]'
    },
    async (pg) => row(pg, 'Rahim'),
  ],
}
