# Work done rules

This skill covers **work done on site**: what was started, how far it got, what was finished,
and quantities. `save_work_done` only puts a line below your words; the Save tap keeps it.

## Recording work

- One `save_work_done` per piece of work, with its floor or place in `location` and the words
  they used in `narrative`.
- A percentage ("tiling 40% aayi", "plastering 60%") is progress: `progress_percent`, and
  `update_kind` progress. "theernnu" / "kazhinju" / "done" / "completed" is `update_kind`
  completed. Started / paused / resumed are said as such.
- A quantity ("120 rft skirting", "30 sqm plastering") goes into `quantities` with its unit as
  said; never convert it, never ask about the unit.
- A figure logged EARLIER today that was wrong ("correction, it was 150 not 180") is
  `correct_work_quantity`, never a second entry. A figure on the open lines below that was wrong
  is `change_line`. A new percentage is progress, never a correction, unless they say the last
  figure was wrong ("alla, 75%").
- A problem named inside a work message ("slab complete, terrace-il leak und") is ALSO a
  `report_issue` in the same first step (see the issues rules); never fold it into the work line.
- Equipment (JCB, crane, mixer hours) is not recorded on WhatsApp yet: a message only about
  machines gets no save tool; say "Equipment isn't recorded on WhatsApp yet." A machine that
  broke down is an issue.

## Questions about work

- "Innu enthokke cheythu?", "what was done this week?": `query_work_log`; answer only what was
  asked, from the tool's facts, in their words. Something open since an earlier day is not
  today's: give its date.
