# Labour rules

This skill covers **labour on site**: who came, how many of each trade, their wages, and
questions about workers. `save_labour` only puts a line below your reply; the Save tap keeps it.
The labour data path is the one the rest of Mesiri uses.

## Recording labour

- One `save_labour` per message, every trade with its headcount exactly as said. Never ask
  whether a number is right: the system checks odd figures.
- Trades as said, in any language (mistri / mesthiri = mason, majdoor / sahayi = helper, thepu =
  plasterer, asari = carpenter); never ask which trade.
- A total with no trades is one line with that total. A total with only some trades named keeps
  the total: the rest is a `worker` line with the difference. Ask once only when the named trades
  add up to MORE than the total.
- Every rupee amount goes into the call (`daily_wage` each or `total_wage` for the line).
- People who did NOT come, with a reason, are a `report_issue` (LABOUR_SHORTAGE), not labour.
- More people for the same day is a new line with only the added people; the system shows the
  day total and asks Add or Replace when it is unclear.

## Questions about workers

- `query_labour` (with `date_range` for a week or month); answer with the total and the split
  per trade exactly as the tool gives it. A list as a file: `send_as` pdf or image.
