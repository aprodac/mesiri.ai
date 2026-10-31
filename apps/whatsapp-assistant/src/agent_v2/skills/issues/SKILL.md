# Issues rules

This skill covers **problems on site** and their status. `report_issue` and `update_issue` only
put a line below your words; nothing is opened or closed before the Save tap.

## Reporting a problem

- `issue_type`: rain / weather -> WEATHER; material ran out and held work up ("cement theernnu,
  pani ninnu") -> MATERIAL_SHORTAGE; people did not come -> LABOUR_SHORTAGE; a machine broke ->
  EQUIPMENT_BREAKDOWN; drawings awaited -> DRAWING_PENDING; a fall, injury or accident ->
  SAFETY (HIGH or CRITICAL); a leak, seepage or crack -> QUALITY; else OTHER.
- Keep only what THIS message says: `date` ("innale mazha" -> yesterday), how long work stopped
  (`delay_duration_minutes`: 2 hours = 120), severity (urgent -> HIGH). Never carry hours, a date
  or a severity over from an earlier message. "Since morning" with no hours: still call it; the
  system asks how many hours once.
- Rain that stopped work is BOTH `set_site_conditions` (rainy, hours lost) AND `report_issue`
  (WEATHER).
- Material that is only wanted ("nale 10 bag cement venam") is a material request, never an
  issue. Material that ran out and nothing stopped is a stock count.
- A problem that looks already open is still reported; the supervisor decides at Save.

## Closing or changing a problem

- Fixed / sorted / repaired / "close it" -> `update_issue` with `action` resolve, and the words
  that name it in `about` (["mazha"], ["mixer"]), or `all_issues` for "both" / "all". Never pick
  the issue yourself and never close the latest one by default: the system matches the words or
  lists the open issues as buttons. Their answer to that list is the button's text: pass it as
  `about`. Acknowledge -> acknowledge; a mistake -> cancel; back again -> reopen.
- Never ask "which project?" for an issue when the open issue's words already name it; never ask
  the same thing twice.

## Questions

- "Open issues ethokke?", "what is pending / out of stock / to order tomorrow": `query_open_needs`
  (requests, shortages, materials at zero) and copy its list; never the whole stock list.
