# Issues rules

This skill covers **problems on site** and their status. `report_issue` and `update_issue` only
put a line below your reply; nothing opens or closes before the Save tap.

## Reporting a problem

- `issue_type` from what happened: weather, material that ran out and held work up, people who
  did not come, a machine that broke, drawings awaited, safety (an injury or accident: HIGH or
  CRITICAL), quality (a leak or a crack), else OTHER.
- Keep only what THIS message says: its date, how long work stopped (`delay_duration_minutes`),
  how urgent. Never carry these over from an earlier message. Hours not said: still report it;
  the system asks once.
- Weather, a power cut, a holiday or less work than usual is the day's conditions
  (`set_site_conditions` only), never a `report_issue`. Only damage or a blocker is an issue.
- Material that is only wanted is a request, never an issue.
- A problem that looks already open is still reported; the supervisor decides at Save.

## Closing or changing a problem

- Fixed / sorted / close it -> `update_issue` with the words that name it in `about` (or
  `all_issues`). Never pick the issue yourself: the system matches the words or lists the open
  issues as buttons, and the tapped text is `about`. Acknowledge, cancel and reopen likewise.

## Questions

- What is open, pending, out of stock or to order -> `query_open_needs`, never the whole stock.
