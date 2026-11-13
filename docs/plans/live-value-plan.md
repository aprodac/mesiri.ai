# Live shows the value: what each entry gives the owner

> Asked by Ilan, 12 Nov 2026: Live is the page kept open while showing Mesiri to people. A material or
> labour entry by itself does not show the value; the value is what happens with that data. Live must
> show that, for every kind of entry, in a way any salesperson can explain.
>
> Status: **WEB-81 and WEB-82 done (12 Nov):** the ripple plays on Live for material came, material used and
> attendance. **WEB-83 done (12 Nov):** the owner's board is on Live in place of "Where it goes". **WEB-86 done
> (12 Nov):** work done, an issue, a bill or expense and a machine's day have their ripples, and the day has its
> closing count. A question has none yet (below). **WEB-84 done (12 Nov):** the demo deck ("Stories") is on Live
> for demo companies. The demo data is WEB-85.

## 1. Where Live stops today

Live already shows capture well: a message arrives, Mesiri understands it, it is saved, and it flies to
a module in "Where it goes" (Labour, Site log, Materials, Issues, Expenses, Daily reports, Projects &
sites), where a count goes up. "Meet Mesiri" is a nine-scene show on sample data. Presenter mode has the
QR, the voice and "Replay the day".

The story ends at "stored". Nothing on Live says what the stored entry changed: the stock, the money
owed, the budget, the bill that no longer matches. That is the gap this plan closes.

## 2. The idea in three parts

1. **The owner's board.** Six questions an owner carries all day, always on screen, each with its
   current answer in one sentence with the number inside it.
2. **The ripple.** After an entry is saved, its effects play one at a time. Each is a card: one number
   that moved (before → after), one sentence, one tag (**Money**, **Time**, **Caught**, **Proof**). Each
   card then lands on the board question it answers. The chain ends with "One message. N things you now
   know."
3. **The demo deck.** Ready messages grouped into short stories. A tap sends one through Tell Mesiri
   (the same handler as WhatsApp); the QR lets the visitor send the same line from their phone.

The ripple runs both ways: an entry lights up the answers it moved, and an answer opens into the
messages that built it ("from 14 messages by 3 people this week").

## 3. The owner's board

| # | The question | The answer shown (example) |
|---|---|---|
| 1 | Where is my money going? | "₹1,84,200 spent this week. Cement is 62% of its budget." |
| 2 | Is anything leaking? | "2 things to check: ABC billed ₹500 over the rate; 6 bags used beyond stock." |
| 3 | Is the work moving? | "Tower A: 68% done, 3 days behind the schedule." |
| 4 | What do I owe, and who owes me? | "Wages due Saturday ₹62,400. ₹3.2 lakh can be billed to the client now." |
| 5 | What will stop work tomorrow? | "Cement at Main block runs out Thursday. 2 issues open." |
| 6 | Can I prove it? | "Tonight's report: 14 lines, 9 photos, sends at 9:00 pm." |

The six are a first guess from the pages the product has. Ilan to confirm or change from what owners
ask in sales meetings (decision 1 below).

## 4. Every kind of value a construction ERP gives, and how Mesiri would show it

How to read the **How** column: it names the API that already answers this for a project or site. What
was checked on 12 Nov is that the route exists and what its description says. What was **not** checked
is whether each can give a before and after for one single entry; that is WEB-81's job. "To build" means
no such logic was found in the sweep.

### A. Is anything leaking? (control; the strongest demo moments)

| Value | The entry that triggers it | How | Tag |
|---|---|---|---|
| More used than was in stock | material used | review flag `beyond_stock` (Live shows it already) | Caught |
| The same thing entered twice | any entry | review flag `possible_duplicate` (Live shows it already) | Caught |
| Paid more than last time, or than the agreed rate | delivery with a rate, a bill | `GET /procurement/rates/{material_id}`: each purchase with the rate before it and whether it differs from its order's | Caught, Money |
| Billed for what did not arrive | bill photo | `POST /materials/invoices/match`, bill ↔ deliveries links | Caught, Money |
| Short supply against the order | delivery | purchase order `receive`, Pending deliveries | Caught |
| Used more than the estimate allows | material used + work done | BOQ norms, Cost → Materials, green/red variance | Money |
| Stock on the books is not on the ground | stock count | stock counts (`approve` posts the difference) | Caught |
| Wages paid for people who were not there | attendance | muster, wage sheets built from attendance | Caught, Money |
| Hired machine billed for hours it did not run | machine log, hire bill | `GET /equipment/hire-check` | Caught, Money |
| Subcontractor billed more than was measured | work measured, sub bill | work order `bills/check` | Caught, Money |
| Shuttering, tools not returned | issue / return of returnables | Returnables | Caught |

### B. Where is my money going?

| Value | Trigger | How | Tag |
|---|---|---|---|
| Today's and the week's full cost per site | any delivery, attendance, expense | `GET /finance/costs` (expenses + unbilled priced deliveries + labour) | Money |
| Budget against actual, per BOQ line | work done, delivery, attendance | `GET /cost/projects/{id}/budget`, green/red page | Money |
| Where it went, by cost centre | expense, delivery, attendance | Cost centres | Money |
| Value of stock lying on site | delivery, usage | `GET /materials/stock-value` | Money |
| The project's profit so far | all of the above | Accounts → project books | Money |

### C. What do I owe, and who owes me?

| Value | Trigger | How | Tag |
|---|---|---|---|
| Wages due this week; each worker's balance | attendance, advance | wage sheets, `GET /labour/advances/balances`, pay summary | Money |
| What each supplier is owed, overdue, not billed yet | delivery, bill, payment | `GET /finance/vendors/payables`, `GET /finance/vendors/unbilled` | Money |
| What can be billed to the client now | work done | RA bills, receivables | Money |
| Subcontractor: earned, advance, retention | work measured | work orders, statement | Money |
| Cash and bank today | expense, receipt, payment | `GET /accounts/home` | Money |
| GST, TDS and Tally ready without re-typing | bill photo | GST, TDS, Tally export | Time |

### D. Is the work moving?

| Value | Trigger | How | Tag |
|---|---|---|---|
| Done / in progress / not started, floor by floor | work done | `GET /places/progress` | Proof |
| Ahead of or behind the schedule | work done | schedules | Time |
| Days and hours lost, and why | weather, issue | site-day conditions, issues | Proof |
| Output per worker-day | attendance + work done | **to check** (worker statistics exist; a rate per trade was not found) | Money |

### E. What will stop work tomorrow?

| Value | Trigger | How | Tag |
|---|---|---|---|
| Material below its minimum, and how much to order | material used | `GET /materials/stock-levels/below` (gives the lines for a request) | Time |
| How many days the stock lasts | material used, delivery | stock summary (days-of-stock logic exists) | Time |
| What the coming work needs against what is there | work done, delivery | material plan | Time |
| Deliveries still pending; suppliers who run late | delivery | Pending deliveries, supplier performance | Time |
| Open issues and how long they have waited | issue | issues, tasks | Time |
| What is waiting for the owner's yes | request, bill, report | `GET /approvals/waiting` | Time |
| Machine service due, hire running on an idle machine | machine log | equipment | Money |

### F. Can I prove it?

| Value | Trigger | How | Tag |
|---|---|---|---|
| The daily report, written by itself, sent at 9 pm | every entry | daily reports, PDF (Live's finale shows it) | Proof, Time |
| Photos attached to the line they prove | photo | fact sources (Live shows it already) | Proof |
| Who said it, when, in their own words | every entry | `GET /dpr/facts/{type}/{id}/sources` | Proof |
| The client sees progress from a link | work done, photo | client view | Proof |
| Week and month reports, all projects on one page | every entry | period report, portfolio | Time |
| Every change and who made it | correction | activity log | Proof |

### G. Time saved on site and in the office (said by the presenter, shown as a count)

No app to learn; a voice note in Malayalam, Hindi, Tamil or English; one message becoming several
entries; a question answered on WhatsApp with the number; a bill photo read instead of typed; a bill
linked to its deliveries instead of entered again; approvals by a tap.

## 5. The ripple, entry by entry

Order in every chain: the obvious effect first, the surprise in the middle, the report last. A card
appears only when it is true for this entry (no order linked: no order card).

| Entry | The chain |
|---|---|
| Material came | stock up, days it lasts → the order: delivered and pending → rate against last time → supplier now owed → cost and budget → tonight's report |
| Material used | stock down, days left → below minimum: order this much → used against the estimate → cost on the work it went into → report |
| Attendance | who is on site → today's wages → the week's wage bill, advances → labour cost against budget → report |
| Work done | the floor's grid, percent done → schedule: ahead or behind → billable to the client → subcontractor's earned amount → client view → report |
| Bill photo | read: amount, GST, supplier → matched to its deliveries, or what differs → supplier owed → cost centre and budget → GST and Tally |
| Issue | on the report with its photo → task raised, who is told → days open → time lost |
| Machine log | hours and diesel → hire bill check → machine cost per site → service due |
| Question | the answer, and the messages it was built from |

### What one entry can show today (WEB-81, read in the code on 12 Nov)

Read from the code, not run against a database. "Yes" means the records hold what the card needs for
this one entry; the before is the after less the entry's own quantity or amount.

| Entry | Card | Today | From |
|---|---|---|---|
| Material came | stock before → after | yes | the stock ledger keeps a running balance per site and material |
| | days it lasts | yes | `days_left` in the stock summary (stock ÷ daily use) |
| | the order: delivered, still to come | yes, when the delivery is on an order | `material_receipts.purchase_order_line_id`, `line_received` |
| | rate against last time and against the order | yes, when a rate was given | `unit_cost` on the delivery; the Rates read compares |
| | supplier now owed | yes, when a rate and a supplier are known | the vendor ledger's summary |
| | cost and budget | project cost: yes. Per estimate line: only where the material has a norm | Full cost read; Cost → Materials |
| Material used | stock before → after, days left | yes | as above |
| | below minimum: order this much | yes, when a minimum is set | stock levels `below` |
| | used against the estimate | only where the material has a norm on an estimate line | Cost → Materials |
| Attendance | who is on site | yes | the attendance report |
| | today's wages | yes, for lines with a wage | each attendance line carries `daily_wage` |
| | the week's wage bill, advances | yes | the open wage sheet for the week; advance balances |
| | labour cost on the project | yes | Full cost read |
| | labour against the estimate line's budget | **only after a person puts the day on a line** | Cost → Labour suggests a line and never saves it by itself |
| Work done | on the report, with its photo | yes | Live shows it already |
| | counted on an estimate line → budget earned, billable to the client, schedule progress | **only after a person puts the quantity on a line** | `PUT /boq/work/{quantity_id}`: "a person puts the work on a line"; a client bill takes measured work not billed yet |
| | floor grid, subcontractor's amount, client view | not checked | |
| Issue | on the report; days open | yes | issues |
| | task raised | a task can point at an issue; whether one is raised by itself was not checked | tasks `site_issue_id` |
| Bill photo | read; matched to deliveries; what differs | yes | vendor matching keeps `billed_quantity` and `billed_rate` beside the delivery's |
| Machine log | hours against the hire bill | yes, per machine and month | hire check |

**What this changes in the build:**

1. **Five kinds of entry are "facts"** with an id Live can ask about: work done, issue, attendance,
   material came, material used. A bill and a machine log are not. The effects read therefore takes a
   record kind and id (`/dpr/effects/{kind}/{id}`), with the five fact kinds first.
2. **Work done and labour reach the budget only through a person's tap** (putting it on an estimate
   line). The honest card is "Suggested line: Plastering, 2nd floor. Once counted: ₹48,000 billable",
   with the tap done from the card in a demo. Making it automatic is a product decision (decision 5).
3. **Material came, material used and attendance are ready**: every card in their chains can be
   computed for one entry. They stay the first three (WEB-82).
4. **Live is open to everyone on a site, and money answers are kept off it today** (the feed leaves
   finance questions out). Money cards need the role rule (decision 4) before they show.
5. Cost control and Labour are behind their module switches, so a switched-off module gives a greyed
   card with no extra work.

## 6. The presentation

**The screen.** Left: the messages. Middle: Mesiri handling one, then the ripple cards. Right: the
owner's board in place of "Where it goes" (the modules stay reachable: every card and every board answer
opens its real page with the existing cut).

**The stories** (the deck). Each is two to three messages and about two minutes.

1. **A delivery day.** Cement arrives → stock and the pending order → the supplier's bill photo → "ABC
   billed ₹500 over". Ends on *Is anything leaking?*
2. **The site's day.** Attendance by voice note in Malayalam → wages → work done with a photo →
   "₹48,000 more can be billed". Ends on *What do I owe, and who owes me?*
3. **Something is wrong.** More used than in stock → Mesiri stops it → stock falls below minimum →
   "order 40 bags". Ends on *What will stop work tomorrow?*
4. **The owner asks.** "Stock at Tower A?" and "How much did we spend this week?" from the visitor's
   own phone by QR. The board answer and the WhatsApp answer are the same number.
5. **9 pm.** The report folds into its PDF and goes out. The closing line: "N messages today. M things
   you know. Nobody opened an app."

Full show: about ten minutes. Short show (stories 1 and 5): three minutes. "Meet Mesiri" stays as the
opening on sample data; the stories run on the demo company's real records.

**For the presenter.**

- A line to say under every card and every story step, in plain words.
- Space holds the ripple on a card, → moves on, S skips to the summary (Meet Mesiri already takes ← → Esc).
- The deck opens from the header; a story can start at any step.
- "Reset demo" (exists in the control panel) puts the company back to the same starting story.
- A greyed card for a module that is switched off: "With Cost control you would also see…" (decision 3).

**Honesty rules.** Only numbers the system computed. Sample scenes say "Sample". A "₹ caught" total
counts only differences the code found.

## 7. How it is built

- **One read-only API**, `GET /dpr/effects/{kind}/{id}` (see the WEB-81 findings), beside the existing
  `/sources`. It returns the ordered cards for one saved entry: `kind`, `tag`, `before`, `after`,
  `sentence`, `say` (the presenter's line), `opens` (the page), and the board question it answers.
- **One table of effect rules** per entry kind. A new effect is one entry in the table. Each rule calls
  the read function the module's own route already uses; no module's figures are computed twice.
- **The board**: one read, `GET /dpr/live/board`, answering the six questions from the same module reads.
- **The feed carries record ids** (WEB-59 noted it does not yet), so Live can ask for an entry's effects.
- **Roles**: money cards only for roles that see spending, as the feed already does for a bill.
- **No new tables. No migration.**

### What is built (WEB-82, 12 Nov)

- `GET /dpr/effects/{kind}/{id}` (`domains/dpr/effects.py`): the cards for `material_receipt`, `material_usage`
  and `labour_report`. Building is pure (one function per kind in `RULES`); reading calls the stock summary, the
  order's received total, the Rates purchases, the supplier ledger, the Full cost read, the wage sheet's
  arithmetic and the advance balances. Nothing is written.
- A save's trace now keeps its record's id (`agent_api/whatsapp.py`, one helper for both traces), and the feed
  names the records a message saved (`records`). A message saved before this has no id, so it plays as before
  with no ripple.
- Live plays each saved record's ripple after its message: one card at a time, then "One message. N things you
  now know." Space holds, ← → move, S skips to the end, Esc closes; a card opens its page; the module it
  belongs to rings.
- A "before" is shown only when the entry is the newest movement of that material at the site (stock), is not
  yet on a bill (supplier), or is the report that counts for the day (the week's wages). Otherwise only "now".
- Not built here: the estimate-line cards (budget per line, used against the estimate) and greyed cards for
  switched-off modules, which come with WEB-86.

### What is built: the owner's board (WEB-83, 12 Nov)

- **`GET /dpr/live/board`** (`backend/src/mesiri/domains/dpr/board.py`): one table, `QUESTIONS`. A question is a
  list of parts; a part is one module's own route function (`READS`) and the sentence said from what it returned.
  The same pattern as `approvals/inbox.py`. A new answer is one part in the table.
- **What each question reads today:**

  | Question | Reads (module) |
  |---|---|
  | Where is my money going? | Full cost, last 7 days (finance); budget against actual, all projects (cost) |
  | Is anything leaking? | Stock summary: closing below zero (materials); Rates: paid above the best rate, items rising (materials) |
  | Is the work moving? | Schedule lifecycle: percent done, days behind (dpr); today's site days: work updates, workers (dpr) |
  | What do I owe, and who owes me? | Wages owed summary (labour); supplier payables (finance); work that can be billed now (dpr, WEB-91); client receivables (dpr) |
  | What will stop work tomorrow? | Below minimum (materials); days of stock left (materials); open issues (dpr); waiting for my yes (dpr) |
  | Can I prove it? | Today's site days: lines, photos, sites heard from, reports sent (dpr) |

- **Who sees what:** each read is the route function itself, so its own role and scope rule runs. A read that
  answers 403 or 404 is left out and the answer says "Shown to the owner, finance and project managers", never
  "nothing". A switched-off module is not read and is named on a greyed line (decision 3).
- **On Live** (`components/live/board.tsx`): the board is the right column. A saved message lands on the questions
  it answers and the board is read again; a ripple card lands on its question (the card's number 1 to 6 is the
  board's order); an answer opens into the day's messages behind it ("from 3 messages by 1 person today") and
  into its page with the cinematic cut. The modules stay as a row of chips, "Where it is kept".
- **Not in yet:** the plan's examples "Cement is 62% of its budget" (needs a budget per material; the board says
  the project's percent), "₹3.2 lakh can be billed to the client now" (measured work not billed: no read gives it
  company-wide; the board says what clients owe), "wages due Saturday" (the board says wages approved and unpaid,
  drafts waiting, advances out), and the report's send time on the board.
- The board is as of now, whatever day Live shows.

### What is built: the remaining ripples (WEB-86, 12 Nov)

Four more entries in the one table (`effects.RULES` and `effects.READS`), built the same way as WEB-82's.

| Entry | Cards, in order | Read from |
|---|---|---|
| Work done | the site's work today → its floor (done, left) → the schedule (percent done, days behind) → the estimate line → photos → the report | the Today page's site day; the floor grid's roll-up; the schedule's summary; the estimate's own work list and line suggestion; the sources panel |
| Issue | open issues at the site, how long the oldest has waited → the task raised for it → photos → the report | the Today page's open count; `tasks.site_issue_id`; the sources panel |
| Bill or expense | what was read (amount, GST, supplier) → the bill against its deliveries, what differs → the supplier owed → the week's cost | the expense; the supplier page's own list of a bill's deliveries (called as the person asking); the supplier ledger; Full cost |
| Machine log | hours, idle, diesel → breakdown hours and why → the month's hire so far | the equipment module's `rules.worked` and `rules.hire_lines`, as the hire check counts it |

- **The estimate line keeps the person's tap (decision 5).** Work counted on a line says what it earned. Work not on
  a line says the line Mesiri suggests and what it *would* come to, and opens the estimate page; it is never said
  as earned.
- **A bill is the company's spending.** For a role that does not see it, the route answers 404 and nothing is read.
  The estimate line and the hire amount are left out of the chain for those roles; the rest of the chain stays.
- **A bill and a machine log are not report facts**, so the route finds their project and site in their own
  tables (`effects.RECORD_TABLES`) for the same site rule.
- **The feed** knows a machine log now (`log_machines` → "Machine log") and carries the saved record of each new
  kind. A message that logs two machines carries both (`ids` in the save's trace, trace only).
- **The day's closing count**: the bar at the bottom of Live adds "N things you now know", the cards of every
  ripple shown since the page opened (a replay counts once).
- **Not built: the question's ripple** ("the answer, and the messages it was built from"). A lookup does not
  record which entries it read, so the messages behind an answer cannot be named truthfully today. It needs the
  lookup's trace to keep the record ids it returned; left as WEB-87.
- **Not in:** the subcontractor's amount and the client view for work done; whether an issue raises a task by
  itself (the card shows a task only when one exists); a cost-centre card and a GST card for a bill; service due
  for a machine.

### What is built: the demo deck (WEB-84, 12 Nov)

- **`GET /dpr/live/deck`** (`backend/src/mesiri/domains/dpr/deck.py`): one table, `STORIES`, the five stories of
  section 6. A step is the line to say and either a message to send or something done by hand (a bill photo from
  a phone, Replay the day). The messages name the demo's own sites.
- **Demo companies only.** A ready message is a real entry once sent. The route gives stories only to a company
  with `demo_company` set (the same mark the one-tap reset needs); any other company gets none, so its Live has no
  Stories button. To use it on another company, the Mesiri team marks it as a demo in the control panel.
- **On Live** (`components/live/deck.tsx`): "Stories" in the header opens the deck. A step's Send goes through Tell
  Mesiri's own call (`POST /assistant/messages`), as the signed-in person; Mesiri's reply and its buttons (Save,
  Cancel) show under the step and can be tapped there. Live then plays the message like any other.
- The short show is the first and the last story. The hold / next / back / skip keys came with WEB-82.
- **Depends on WEB-85** for the full effect: the bill over the rate, the order still to come, the budget and the
  client bill show only once the demo company has those records.

### What is built: upgrades for the demo (WEB-88, 89, 91, 92; 13 Nov)

- **The tap on the work card (WEB-88).** "Estimate line" offers "Count it on this line". The tap is the estimate's
  own route; the entry is read again and the card becomes "₹48,000 earned … to bill the client", held on screen.
- **The board's missing words (WEB-89).** The site on "lasts N more days"; when the next report goes out by itself.
- **The day's closing line (WEB-89).** Over the bottom bar: "N messages today. M things you now know. Nobody
  opened an app."
- **"Can be billed to the client now" (WEB-91).** `GET /billing/to-bill`: measured work on no client bill yet, at
  the client rate. Billing's own working (`bills.unbilled_lines`), the one a new RA bill draft is made from.
- **The presenter's sheet (WEB-92).** Printed from Stories, from the deck's own table.
- **Blocked: a running "₹ caught" total (WEB-90).** Which differences count, and over what period, is a product
  decision; no single read gives it today.

### Phases (tracker)

| Item | What | Size |
|---|---|---|
| WEB-81 | Check, per entry kind, which effects can be computed for one entry today; fix the list in section 5 to what is true | S |
| WEB-82 | Effects API + record ids on the feed + the ripple on Live for **material came, material used, attendance** | L |
| WEB-83 | The owner's board (six answers; an answer opens into its messages) | M |
| WEB-84 | The demo deck: stories, the lines to say, hold / next / skip | M |
| WEB-85 | Demo company data for the stories: orders, a supplier bill over the rate, BOQ with budget, minimum stock, a wage sheet, a client bill | M |
| WEB-86 | The remaining ripples: work done, bill photo, issue, machine log, question; the closing count | L |

### The plan's required parts

- **Objective:** a visitor watching Live understands, from one message, what the owner gains.
- **Scope:** Live (dashboard), two read APIs in `dpr`, the demo data. Not in scope: changing what any
  module computes; new animations beyond the card and its landing.
- **Business value:** the sales demo shows control and money, where today it shows data entry.
- **Files expected to change:** `apps/dashboard/src/components/live/*` (new `ripple.tsx`, `board.tsx`,
  `deck.tsx`; `company.tsx`, `modules.tsx`), `apps/dashboard/src/lib/api.ts`,
  `backend/src/mesiri/domains/dpr/` (router, `live_feed`, new `effects.py`),
  `apps/whatsapp-assistant/src/admin/demo.py`, tests beside each.
- **Backend / API:** the two reads above; record ids on `/dpr/live/feed`. **Database:** none.
- **Frontend:** the ripple, the board, the deck, presenter keys.
- **Risks:** (1) an effect that cannot be computed per entry (found in WEB-81, then left out, not faked);
  (2) more reads per message on a page that polls every second: effects are read once per saved entry and
  kept; (3) money shown to a role that should not see it: the role rule is tested per card; (4) Live is
  already 2,000 + 1,500 lines: the new parts go in their own files.
- **Testing:** backend unit tests per effect rule (the entry, a sibling kind, and the case where the card
  must not appear); a role test per money card; the dashboard's `tsc`, `oxlint`, build; a browser run of
  each story on the demo company with screenshots.
- **Rollback:** dashboard and read-only API only; revert the commits. The demo data change is undone by
  reverting and pressing Reset demo.
- **Labour isolation:** Labour, Wages (Payroll) and Workforce are only **read**, through the reads their
  own routes use. Nothing in them changes. If a read function has to be added inside Payroll or
  Workforce, that step stops for Ilan's approval.
- **Success criteria:** each of the five stories runs start to finish on a freshly reset demo company; a
  person who has not seen the product can present the short show from the lines on screen; every number
  on a card equals the number on the page it opens.

## 8. Decisions (Ilan, 12 Nov, in session: "do the recommended")

1. **The six questions** stay as in section 3, in that order.
2. **Who is in the room:** usually the owner, sometimes a GM or a site engineer. Chains lead with Money
   and Caught; the Time cards stay in every chain for the GM and the engineer.
3. **Greyed cards** for a module that is switched off: shown.
4. **Roles:** money cards show to the roles that see Expenses; everyone else gets the chain without them.
5. **Work done and the estimate line:** the person's tap stays; the card offers it.

## 9. Not verified

- WEB-81 was read in the code only; nothing was run against a database or the demo company.
- Not checked: whether a delivery sent on WhatsApp is put on its order by itself; the floor grid, the
  subcontractor's amount and the client view for work done; whether an issue raises a task by itself.
- Output per worker-day: no existing logic found.
- The demo company now has orders, a supplier's bill, an estimate with budget, wage sheets, advances and a
  client bill (WEB-85, 12 Nov); checked by a reset on a real Postgres, not on production.
