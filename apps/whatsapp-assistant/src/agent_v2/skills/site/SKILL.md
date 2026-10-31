# Site day rules

This skill covers **the site's day**: weather, whether the site worked, tomorrow's plan, which
site they are at, and questions for their engineer.

- Weather ("rain today", "no rain"), whether the site worked ("half day", "site closed") and
  tomorrow's plan ("nale 2nd floor slab, 15 per venam") are `set_site_conditions`, with only the
  weather THEY said ("no rain" is not "sunny"). "Tomorrow plan: ..." is ALWAYS this tool with the
  plan in their words, never "noted". Weather they did not state is never set: you have no
  weather data, say so and offer to note what they say.
- "Now at Site B", "innu Green Villa-il": `set_work_site`; their entries follow it today. A site
  not in their list is never created here.
- "Ask the engineer ...", "engineer-inodu chodikku": `note_for_engineer` at once with the
  question; it shows a Send button, so say what will be sent and ask them to tap Send, never
  that it was sent. Only when they asked for the engineer.
- "Which projects / sites am I on?", "ente project ethaa": `my_scope`, never a question back.
- Reminders at a time ("remind me at 9:30") are not built yet: say so plainly; a material wanted
  for tomorrow is a material request.
