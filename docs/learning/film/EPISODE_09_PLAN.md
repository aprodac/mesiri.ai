# Episode 9, "Where every entry goes": the plan

> Asked 21 Nov 2026 (Ilan): "each data entry that was entered with the plan, and in BOQ, then materials and BOQ, then
> profit and loss, how it got connected; cost control, how it got noticed and why and what can be done; everything
> connecting with the value of the data that was entered, the owner getting what they want and being able to drill
> down. This should be the next episode." Then: "yes go ahead, write the episode 9 plan".
>
> It is the series plan's episode 9, "Is it making money?" (SERIES_PLAN section 5), widened into the episode that joins
> episodes 3 to 7 up. Filmed before episode 8 (billing): the 62-day plan already sends the running bills, so nothing it
> needs is missing. Status: **plan; the story and the checks below are built next, the shared-page fixes wait for
> Ilan** (section 7). Tracker: LRN-F29 (plan and script), LRN-F30 (story batch), UX-93 to UX-95 (what to fix).

## 1. Objective

> By the end you can take any figure the owner looks at (profit, over budget, a red line) and walk it back to the
> entries that made it, and forward from any entry to every figure it changes; say how a problem in the money is
> noticed, why, and what is done about it; and read the difference between the books and the real margin.

The viewer's test: *Ramesh asks "why is Green Villa losing money?". Open the page that answers it, go down to the line
that causes it, then to the entries on that line, and say what Anil should do on Monday.*

## 2. The map: every entry, where it goes, what it answers

The one idea of the episode: nobody types a number twice. Each thing said on site or entered in the office lands in
one place and is read by every page after it.

| Entry (episode) | Saved as | Lands on the BOQ as | Feeds | The owner's question it answers |
|---|---|---|---|---|
| The estimate and the contract (1) | BOQ lines: quantity, client rate, labour and material rate | the yardstick | Budget, contract value | "What did I sign for, and what should it cost?" |
| Work done, "plinth beam 24 rmt" (3) | activity on a BOQ line | **earned** = quantity × rates | Done %, Green / red, Budget vs actual, RA bill | "How much of the job is built?" |
| Attendance, Rahim's crew (3, 5) | labour days, wage | **labour spent** on the line (LW-11's trade rule) | Green / red, Labour reports, wage sheet | "Am I paying for work or for heads?" |
| Material used, "10 bags cement" (3) | stock out, at the bought rate | **material spent** on the line | Materials vs BOQ, Stock | "Is cement going where the BOQ says?" |
| Request, quotes, order, delivery, bill (4) | purchase, stock in, supplier bill | **committed**, then stock | Committed, Suppliers, Cash flow | "What have I promised to pay?" |
| Wages paid (5) | payment | (already counted as labour spent) | Cash and bank, P&L | "Where did the cash go?" |
| Machine log, hire bill (6) | hours, hire cost | equipment cost | Cost centres, Hire check | "What is idle costing me?" |
| Measurement, subcontract bill (7) | measured quantity, bill | **subcontract spent**, retention held | Budget vs actual, Payables | "Am I paying only for what was measured?" |
| RA bill, client's payment (8) | income, receivable | billed against earned | Project P&L, Receivables | "When does my money come in?" |

Then the owner's way down, one tap at a time: **Home** (what needs me) → **Project P&L** (books margin, real margin,
not billed yet) → **Budget vs actual** (labour, materials, subcontract; at finish) → **the red line** (Green / red) →
**its entries** (who, which day, from which message) → **what to do**.

## 3. What the screens say today (sample company, day 49, as the owner)

| Page | Green Villa |
|---|---|
| Home (day 5) | "Check the costs: heading **655%** over budget, ₹4.0 cr" |
| Cost overview | **green**, "₹5.76 L under", heading over: 0 of 2 |
| Budget vs actual | spent ₹11.45 L on lines **+ ₹11.46 L elsewhere**; labour ₹1.32 L over (at finish ₹24.51 L of ₹19.75 L); materials ₹1.31 L under; subcontract "No rate"; 26 pieces of work and ₹3.29 L of labour not on a line |
| Project P&L | **losing money**: books −71.7% (billed ₹11 L, cost ₹18.9 L), real −21.8% (work done ₹19 L, cost ₹23 L), ₹7.81 L done and not billed; "Within budget, forecast ₹56 L" |
| Materials vs BOQ | empty: "No BOQ line has its materials per unit yet" |

Four pages, three stories. An owner who sees "green" on one page and "losing money" on the next stops trusting both.

## 4. Why: the root causes

1. **Half the cost is on no BOQ line, and the forecast leaves it out.** Cost control forecasts each kind (labour,
   materials) from what is *on lines* only: ₹11.45 L. The other ₹11.46 L (bills with no cost head, labour not put on a
   line) is shown as "elsewhere" and then ignored by "at finish" and by the colour. The P&L counts all of it. So one
   says within budget and the other says losing money. (UX-93)
2. **The overview adds the kinds up**, so labour heading 24% over is hidden by the materials budget not used yet:
   green overall with a red kind inside. (UX-93)
3. **The early forecast has no floor.** At-finish = spent ÷ earned × budget, refused only when nothing is earned. On day
   5 almost nothing was on lines, so it projected ₹4 crore: "655% over". (UX-94)
4. **A BOQ line does not open its entries.** On Budget vs actual a line's labour links to "put labour on lines", but the
   line itself opens nothing: the owner can go from the P&L down to a line, not from a line down to Ravi's message.
   (The P&L's own "Line by line" does list every bill and expense.) (UX-95)
5. **The sample company's data, not the product:** Green Villa's estimate has no materials per unit (so Materials vs
   BOQ is empty); much of its labour and many bills are on no line; the tiling line has no subcontract rate (so
   subcontract shows "No rate"); no office costs (indirect ₹0, so the margin looks better than it is). (LRN-F30)

## 5. The story the episode needs (LRN-F30, built next)

- **Materials per unit** on Green Villa's estimate lines (cement bags a cum, steel kg a cum, blocks a sqm, tiles a sqm),
  in `green_villa.ESTIMATE` and the kit's estimate: Materials vs BOQ then shows cement used against what the work done
  should have used. The month-end count's 3 bags short (episode 4) shows up here too.
- **Everything on its line**: the plan's labour by trade onto lines (LW-11's rule), its bills given a cost head, the
  tiling line a subcontract rate (₹320, the work order's). "Elsewhere" goes to near zero, so the pages can agree.
- **Office costs**: rent, the accountant, the vehicle, monthly (the P&L's indirect cost, Head office).
- **One red line with a cause, noticed and acted on** (the arc the episode follows):
  - Days 26 to 33, Main block plastering: walls chased again for conduits missed on the first pass are plastered twice;
    labour runs at about 1.4 times the BOQ rate. (A new catch, named as one: project bible rule 5.)
  - Day 30: Green / red shows plastering red; Home's "Needs you" says "Check the costs: plastering". Anil opens the
    line, sees the two weeks of attendance against little work, and the reason (rework, the site's notes).
  - Day 31: he moves two masons to the Annex and raises a variation for the client's late change (episode 8 bills it).
  - Day 40: the line is back within 5%; the P&L's real margin turns positive once the ₹7.8 L of work is billed.

## 6. The episode (about 8 minutes)

| Part | What |
|---|---|
| Cold open | Ramesh, Saturday night: "Green Villa says green on one page and losing money on another. Which is it?" |
| On a real site | How a builder knows a job is making money: the BOQ is the yardstick; earned (work done at its rates) against spent; the books (billed against paid) are not the same as the real margin; why money is noticed late without this |
| Who does what | Everyone enters what they do (Ravi, Anil, Meera); nobody enters a total; the owner reads, and asks |
| In Mesiri: the map | One entry followed forward: Ravi's "plastering 38 sqm, 6 masons, 12 bags" lands on the line as earned, labour spent, material spent; the same entry in the P&L and Green / red |
| In Mesiri: noticed | Day 30: Home's item; Green / red, plastering red; why (labour spent against earned); down to the line's entries: two weeks of attendance, the notes on rework |
| In Mesiri: acted on | Anil moves two masons; the variation for the client's change; day 40, the line back |
| What the owner sees | Project P&L: books margin, real margin, not billed yet, at finish; the drill from the margin to the line to the entry |
| What can go wrong | Entries on no line (cost control blind); reading the books as the real margin; a forecast from three days of work; office costs left out; noticing at the month's end instead of the day |
| Three questions | |

## 7. What must be decided or built before filming

| # | What | Who decides | Plan |
|---|---|---|---|
| UX-93 | The pages tell one story: "at finish" and the colour include cost on no line (or say plainly they cannot judge it), and the overview shows a red kind inside a green project | **Ilan** (Cost control and Home are shared pages) | Recommended: forecast on all cost, with the part on no line shown as its own piece ("₹11.46 L not on a line: put it on lines to see where"); a project is never green while a kind inside it is heading over |
| UX-94 | No forecast until enough is earned (e.g. 10% of the budget, or two weeks of work on lines); before that "too early to tell" | **Ilan** (Home) | One rule in `costing/forecast.py`, used by every page |
| UX-95 | A BOQ line opens its entries: the work, the attendance, the material used, the bills on it, each linked to its record and message | Built (Cost control module), with Ilan's yes on the design | A side panel on Budget vs actual and Green / red |
| LRN-F30 | The story batch of section 5 | Built (the learn module) | Plan unit tests and the Postgres all-days test |

## 8. Open questions

1. Episode order: this as episode 9 filmed before 8 (recommended), or renumbered as 8.
2. The red line's cause: rework after conduits missed on the first pass (recommended: it follows the Main block's
   order, conduits then plastering) or a slow crew.
3. Should the episode show the books (P&L, Tally) at all, or only the real margin? Recommended: both, side by side, once:
   the difference is the lesson.
