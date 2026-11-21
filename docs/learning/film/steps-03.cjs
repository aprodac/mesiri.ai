// LRN-F15: episode 3's website steps (shoot.cjs runs them in order and takes a picture after each; record.cjs runs
// shoot.cjs for them inside the sample company, as Anil, on day 2, before Ravi's own messages of the day). One async
// action per frame of the scene in episode-03.json; each returns what to light (a selector or a locator) or null.
const PANEL = 'section[aria-label="Tell Mesiri"]:visible'
/** What Ravi phoned in: the same words as his morning message. */
const PHONED = 'Annex: Manoj, Satheesh, Vinod present. Rahim crew 4 helpers'

module.exports = {
  // The website has no attendance form of its own: the office types into New, the same assistant as WhatsApp.
  office: [
    async (pg, h) => { await h.go('/labour?project={Green Villa}'); return 'tbody tr:first-child' },
    async (pg, h) => {
      await pg.locator('[data-guide="app.tell"]').click() // New
      await pg.getByText('Tell Mesiri anything').click()
      await h.wait(900)
      await pg.locator('#tell-mesiri-text:visible').first().fill(PHONED)
      return PANEL
    },
    async (pg, h) => {
      await pg.locator(`${PANEL} button[aria-label="Send"]`).first().click()
      await pg.locator(`${PANEL} button:has-text("Save")`).last().waitFor({ timeout: 90000 })
      await h.wait(600)
      return PANEL
    },
    async (pg, h) => {
      await pg.locator(`${PANEL} button:has-text("Save")`).last().click()
      // Mesiri's answer to Save: ✅ for what was saved; a ❌ line is a refusal, never filmed as a save.
      await pg.locator(PANEL).getByText(/✅|❌/).last().waitFor({ timeout: 90000 })
      if (await pg.locator(PANEL).getByText('❌').count()) throw new Error('office: Save was refused (❌ on the reply)')
      await h.wait(1500)
      await h.go('/labour?project={Green Villa}')
      return 'tbody tr:first-child'
    },
  ],
}
