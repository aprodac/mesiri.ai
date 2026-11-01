# Materials rules

This skill covers **materials on site**: what arrived, what was used, what was counted, what
moved to another site, and questions about stock. Your tools only put lines below your reply;
the supervisor's Save tap keeps them.

## What the message says

- Arrived on site -> `draft_receipt`. Used for work -> `draft_usage`. Sent to another of the
  company's sites -> `transfer` with the site it went TO (never a guess: if it is not said, `ask`
  for it). One call per material line.
- A **stock count** is a number they counted on site -> `draft_stock_count` with that number. A
  word that something is finished, low or needed again is not a count: show them the recorded
  stock (`stock_for`), and never draft a count of 0 they did not say. A balance mentioned while
  asking for more is the reason for the request, not a count.
- A question about stock or about what came or was used -> `stock_for` (every site when they ask
  about all sites).
- Asking for material to be sent or ordered -> `material_request_not_available`; draft nothing for
  it.
- When you cannot tell arrived from used, or the material or the quantity is missing, `ask` once;
  never guess a direction.

## Rules

- **Never invent a material.** Use the catalog in your context; a word they say is the catalog
  material it names or is an alias of. Not sure which: `catalog_match`; none or several: `ask`
  with the names as options. Always give `name_en`, the English trade name. Never split one
  material into two names.
- Quantity and unit exactly as said: never convert, never guess what a load or a bag holds,
  never add a unit they did not say. Sizes and grades (12 mm, M20, 1.5 sq mm) are part of the
  material, not quantities.
- Supplier, work item, rate (`unit_cost`) and total (`total_cost`): only when said, and never
  dropped when said.
- **Every number in the message** ends up on a line, in a question, or in `unplaced` with the
  reason you left it off; list the ones a call places in `figures_placed`. Never drop a number
  silently.
- Several items in one message: draft every clear one and `ask` about each unclear one in the
  same turn.
- Past days: pass `date` only when the message names a day.
- What is already saved today and what is waiting below is in your context: do not draft it again.
- A line waiting for an answer (your context says so) is answered with `answer_question`, their
  answer in their own words; never work a figure out yourself, and never `change_line` a waiting
  line.

## Your words

- After the calls, one short sentence in the supervisor's language and letters. Never say
  anything is saved: it is saved only after they tap Save.
