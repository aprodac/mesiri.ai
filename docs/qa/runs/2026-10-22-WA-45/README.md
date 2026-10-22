# WA-45: today's site, switching, new sites (22 Oct 2026)

`today-site-switch-create.png`: three conversations run through the real message
handler (`build_message_handlers`), the same harness as
`apps/whatsapp-assistant/tests/unit/test_work_site_journey.py`. The bot's texts and
buttons are exactly what the handler sent. Only the AI's choices and wording are
scripted (`FakeToolCallingProvider`), and in the third panel the classic pipeline is
a stand-in that runs the real `site_create` nodes for its confirmation.

1. **Morning site check.** The day's first message, from someone with 2+ sites,
   waits for "Where are you working today?". The tap sets today's site, then the
   message runs there.
2. **Switch mid-day.** "now at site A" -> `set_work_site` -> today's site is Site A.
3. **Create a site.** `create_site` -> the existing `site_create` workflow and its
   Yes/No. On Yes the existing `CreateSiteHandler` saves it and it becomes today's site.

Not verified here: the live model's tool choice (no AI key in this run), and a
real database (the Yes is executed by code covered by existing tests).
