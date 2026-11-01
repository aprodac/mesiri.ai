# Expenses rules

This skill covers **money spent for the site**. `save_expense` only puts a line below your
reply; the Save tap keeps it.

## Recording an expense

- Every rupee amount exactly as said, what it was for in `description`, who was paid in
  `paid_to` / `vendor`, and `date` only when a day is named (a bill's printed date, day-month-year).
- One `save_expense` per bill with its total.
- If expenses are not switched on for the company, the tool says so: tell them in one line.

## Questions

- What was spent, or a balance -> `query_expenses`; copy the figures exactly.
