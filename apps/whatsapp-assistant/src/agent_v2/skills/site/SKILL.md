# Site day rules

This skill covers **the site's day**: weather, whether the site worked, tomorrow's plan, which
site they are at, and questions for their engineer.

- Weather, whether the site worked, and tomorrow's plan are `set_site_conditions`, with only what
  THEY said. Weather they did not state is never set: you have no weather data.
- A change of the site they are at today is `set_work_site`; a site not in their list is never
  created here.
- A question they ask you to put to their engineer is `note_for_engineer`; it shows a Send button:
  say what will be sent, never that it was sent. Only when they asked for the engineer.
- Which projects or sites they are on -> `my_scope`.
- Reminders at a time are not built yet: say so plainly.
