# Expenses rules

This skill covers **money spent for the site**. `save_expense` only puts a line below your words;
the Save tap keeps it.

## Recording an expense

- Every rupee amount is kept: `amount` exactly as said, what it was for in `description`, who
  was paid in `paid_to` / `vendor`, the `date` when they say one ("innale"). Never invent a date:
  a bill's date is the date printed on it, read as day-month-year for Indian bills.
- A bill photo is read for you: one `save_expense` per bill with the total.
- When the system asks which account it was paid from, their answer ("Office cash", "2", "site
  cash", "ente pocket") is the answer to that question: `answer_question`, never a new expense
  and never the question again.
- If expenses are not switched on for their company, the tool says so: tell them plainly in one
  line, never pretend it was kept.

## Questions

- "Ethra chelavaayi?", "this week's expenses", "balance in site cash": `query_expenses` (`kind`
  expenses or balance). Copy the figures exactly.
