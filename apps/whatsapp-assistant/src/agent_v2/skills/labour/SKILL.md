# Labour rules

This skill covers **labour on site**: how many people of each trade came, their wages, and
questions about workers. `save_labour` only puts a line below your words; the supervisor's Save
tap keeps it. Labour, attendance and payroll data paths are not changed by v2: the tool is the
same one the rest of Mesiri uses.

## Recording labour

- One `save_labour` per message, every trade in `workers` with its headcount, exactly as said
  ("500 mason" is 500: never ask whether a number is right; the system checks odd figures).
- Trade words: mistri / mesthiri / മേസ്തിരി = mason; majdoor / mazdoor / labour / sahayi /
  സഹായി / helper = helper; thepu / ടേപ്പ് pani = plasterer; asari / carpenter; electrician;
  plumber; painter. Take them as said, never ask which trade, never tell them to select one.
- A total with no trades ("30 per vannu", "total 30 workers") is one line with that total.
- **A total with only some trades named** ("50 labourers came: 10 helpers, 20 electricians, the rest
  others") is ONE `save_labour`: the named trades with their numbers and the rest as `worker` with
  the difference (50 - 10 - 20 = 20 worker), so the line adds up to the total they said. Never drop
  the total and never ask for the split. Only when the named trades add up to MORE than the total
  call `ask` once with both figures as options ("50 total" / "60, as listed").
- Wages: every rupee amount goes into the call (`daily_wage` each, or `total_wage` for the
  whole line). Never drop an amount.
- A date word belongs to the record: "innale" / "yesterday" -> `date` yesterday.
- A correction of the figure on the open lines below ("alla, 6 mason aanu", "helper 10 aanu") is
  `change_line` on that line with only the trade that changes, never a second labour line and
  never "more masons". Say the whole line back with its numbers.
- More people of the same day ("10 helpers koode undayirunnu") is a NEW line with only the
  added people; the system shows the day total and asks Add or Replace when it is unclear.
- Absent people with a reason ("5 per vannilla, oralkku pani") is a `report_issue`
  (LABOUR_SHORTAGE), never a labour line with those people.
- Shifts ("raavile 5, uchakku shesham 5") are said back as given; the total is what is saved.

## Questions about workers

- "Innu ethra per?", "how many workers this week?": `query_labour` (with `date_range` for a
  week or month), no trade unless they name one. Answer with the total and the per-trade split
  exactly as the tool wrote it ("Innu 13 per: 8 mason, 5 helper."). "Trade wise" always gives
  numbers per trade.
- A list "as PDF" / "as an image": `query_labour` with `send_as` pdf or image; the system sends
  the file. Never say a file was sent unless the tool did it.
