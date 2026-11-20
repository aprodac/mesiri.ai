// LRN-F15: episode 2's website steps, done for real in the sample company (shoot.cjs runs them in order and takes a
// picture after each). One async action per frame of the scene in episode-02.json; each returns what to light (a
// selector or a locator) or null. Start from the sample company after the guided project's chapters 2 and 3, before
// any of this was done (Drawing check stores nothing; Documents, tracking, the import and the plan do).
const KIT_SET = 'Green Villa - drawing set rev A.pdf'
const KIT_PERMIT = 'Green Villa - building permit.pdf'
const KIT_MATERIALS = 'Green Villa - materials and suppliers.xlsx'
/** Days per section (Anil's plan): 270 days from 2 Nov 2026, ending before the handover on 31 Jul 2027. */
const DAYS = [25, 70, 45, 40, 25, 20, 15, 20, 10]

const check = (pg, text) => pg.locator('[data-guide="drawing.checks"]').getByText(text).first().locator('xpath=ancestor::*[contains(@class,"rounded")][1]')
const tile = (pg, label) => pg.getByText(label, { exact: true }).first().locator('xpath=ancestor::div[contains(@class,"border") or contains(@class,"rounded")][1]')

module.exports = {
  drawingcheck: [
    async (pg, h) => { await h.go('/planning/drawing-check?project={Green Villa}'); return '[data-guide="drawing.drop"]' },
    async (pg, h) => {
      await pg.setInputFiles('input[type=file]', h.kit(KIT_SET))
      await pg.getByText('To ask the architect').first().waitFor()
      return pg.getByText('Sheets', { exact: true }).first().locator('xpath=ancestor::*[.//text()[contains(.,"To ask the architect")]][1]')
    },
    async (pg) => check(pg, '+660'),
    async (pg) => check(pg, 'TOILET'),
    async (pg) => tile(pg, 'To ask the architect'),
  ],
  documents: [
    async (pg, h) => { await h.go('/planning/documents?project={Green Villa}'); return '[data-guide="docs.drop"]' },
    async (pg, h) => {
      await pg.setInputFiles('input[type=file]', h.kit(KIT_SET))
      await pg.getByText('Ground Floor Plan').first().waitFor()
      return pg.locator('main').getByText('Ground Floor Plan').first().locator('xpath=ancestor::*[contains(.,"KB")][1]')
    },
    async (pg, h) => {
      await pg.setInputFiles('input[type=file]', h.kit(KIT_PERMIT))
      await pg.getByText('Green Villa - building permit').first().waitFor()
      return pg.locator('main').getByText('Green Villa - building permit').first().locator('xpath=ancestor::*[contains(.,"KB")][1]')
    },
    async (pg, h) => {
      await h.go('/planning/live?project={Green Villa}', 6000)
      return pg.locator('main').getByRole('button', { name: 'Track on site', exact: true })
    },
    async (pg) => {
      await pg.locator('main').getByRole('button', { name: 'Track on site', exact: true }).click()
      await pg.waitForTimeout(5000)
      return '[data-guide="live.plan"]'
    },
    async (pg, h) => { await h.go('/planning/places?project={Green Villa}'); return pg.getByText('Rooms finished').first().locator('xpath=ancestor::*[contains(.,"Not started")][1]') },
  ],
  bring: [
    async (pg, h) => { await h.go('/bring-data'); return '[data-guide="bring.materials"]' },
    async (pg, h) => {
      await pg.getByRole('button', { name: /Upload the Excel/ }).first().click()
      await pg.waitForTimeout(1200)
      await pg.setInputFiles('[role=dialog] input[type=file]', h.kit(KIT_MATERIALS))
      await pg.getByText(/rows will go in/).first().waitFor()
      return pg.getByRole('dialog').last()
    },
    async (pg) => {
      await pg.getByRole('dialog').last().getByRole('button', { name: /^Import \d+ rows$/ }).click()
      await pg.waitForTimeout(3000)
      return null
    },
    async (pg, h) => { await pg.keyboard.press('Escape'); await h.go('/bring-data'); return '[data-guide="bring.else"]' },
  ],
  schedule: [
    async (pg, h) => { await h.go('/planning/schedule?project={Green Villa}', 5000); return pg.getByText(/sections without dates/).first().locator('xpath=ancestor::*[.//button][1]') },
    async (pg) => {
      await pg.locator('main button:has-text("Quick plan")').last().click()
      await pg.waitForTimeout(1500)
      return pg.getByRole('dialog').filter({ hasText: 'Quick plan' })
    },
    async (pg) => {
      const dlg = pg.getByRole('dialog').filter({ hasText: 'Quick plan' })
      const days = dlg.locator('input[type=number]')
      for (const [i, d] of DAYS.entries()) await days.nth(i).fill(String(d))
      await pg.waitForTimeout(600)
      return dlg.getByText(/Finishes about/)
    },
    async (pg) => {
      await pg.getByRole('dialog').filter({ hasText: 'Quick plan' }).getByRole('button', { name: /^Plan \d+ activities$/ }).click()
      await pg.waitForTimeout(4000)
      return '[data-guide="schedule.chart"]'
    },
    async () => '[data-guide="schedule.stats"]',
  ],
  team: [
    async (pg, h) => {
      await h.go('/team')
      return pg.getByText('Anil (project manager)').first().locator('xpath=ancestor::*[contains(.,"Meera (accounts)") and contains(.,"Ravi (site engineer)")][1]')
    },
    async (pg) => pg.getByText('Ravi (site engineer)').first().locator('xpath=ancestor::*[contains(.,"Site Engineer")][1]'),
    async (pg) => pg.getByText(/have no WhatsApp number/).first(),
    async (pg) => {
      await pg.getByRole('button', { name: 'More for Ravi (site engineer)' }).click()
      await pg.getByRole('menuitem', { name: /WhatsApp number/ }).click()
      await pg.waitForTimeout(1000)
      const field = pg.getByRole('dialog').last().locator('input[type=tel], input[name*=whatsapp i], input[placeholder*="+91"]').first()
      await field.fill('+91 98765 43210')
      return field
    },
    async (pg, h) => {
      await pg.keyboard.press('Escape') // a sample company never takes a WhatsApp number: filmed, then Cancel
      await h.go('/projects/{Green Villa}')
      const section = pg.getByText('Send the DPR automatically').first()
      await section.scrollIntoViewIfNeeded()
      await section.click()
      await pg.locator('main').getByRole('button', { name: 'Save', exact: true }).first().click()
      await pg.waitForTimeout(1500)
      return pg.getByText('Day closes at').first().locator('xpath=ancestor::*[.//text()[contains(.,"Send the DPR automatically")]][1]')
    },
    async (pg) => {
      await pg.getByRole('button', { name: /Add outside contact/ }).click()
      await pg.waitForTimeout(800)
      const form = pg.getByText('They have agreed to receive the DPR on WhatsApp').first().locator('xpath=ancestor::*[.//input][2]')
      const inputs = form.locator('input:not([type=checkbox])')
      await inputs.nth(0).fill('Dr. Anand Krishnan')
      await inputs.nth(1).fill('+91 98470 55555')
      await inputs.nth(2).fill('Client')
      await pg.getByText('They have agreed to receive the DPR on WhatsApp').first().click()
      await form.scrollIntoViewIfNeeded()
      return form
    },
  ],
}
