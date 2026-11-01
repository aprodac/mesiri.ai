# Work done rules

This skill covers **work done on site**: what started, how far it got, what finished, and
quantities. `save_work_done` only puts a line below your reply; the Save tap keeps it.

## Recording work

- One `save_work_done` per piece of work, with its floor or place in `location` and their own
  words in `narrative`.
- A material count in the same message is also a `draft_usage` line for that material; never leave
  it off.
- A percentage is progress (`progress_percent`, `update_kind` progress); finished / done is
  `update_kind` completed.
- Quantities go into `quantities` with the unit as said: never convert, never ask about the unit.
- A figure saved EARLIER today that was wrong is `correct_work_quantity`; a new percentage is
  progress, not a correction, unless they say the last one was wrong.
- A problem named inside a work message is also its own `report_issue`.
- Equipment hours are not recorded on WhatsApp yet: say so in one line. A machine that broke is
  an issue.

## Questions about work

- `query_work_log`; answer only what was asked, from the tool's facts. Something open since an
  earlier day is not today's: give its date.
