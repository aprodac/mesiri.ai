# Episode 4: Cement runs short

> Made from `episode-04.json` by `script_md.py`; edit the JSON, then run it again.

**Status:** PLAN and DRAFT script for Ilan's review (20 Nov 2026). Not recorded. Needs first: story batch 2 for the Main block's cement (sample_plan.py, LRN-F18: the move from the Annex, the three quotes, the order of 200 bags at Rs 400, the lorry with 190 and 6 torn, the return, the bill at Rs 410), so the sample company plays the kit's paperwork; the kit's cement GST corrected to 18% (LRN-F17). Recording brief: RECORDING.md.

**Objective:** By the end you can walk a material chain across the four people: the request, the quotes, the order, the delivery checked at the gate (a short load, torn bags returned), the stock, the supplier's bill checked against the order and the delivery, and the payment. The month-end stock count moves to episode 10 (month end).

**Length:** 14 scenes, 1120 words of narration (about 7 minutes)

## Cold open

### 1. Cement runs short

*Mesiri · The course · Episode 4 · title*

On screen:

- Tuesday · Main block · 0 bags
- Request → quotes → order → lorry → bill → payment

Narration:

> Tuesday, seven in the morning. At the Main block, six people are on site, and there is no cement.
>
> The masons can lay nothing, plaster nothing. They will be paid for the day all the same.
>
> Ravi asked for a hundred bags last night. Between his message and a mason mixing mortar there are four people, three suppliers, a lorry, two papers and a bill. This episode follows every one.

## On a real site

### 2. One chain, three papers that must agree

*On a real site · story*

On screen:

- Request · Quotes · The site asks; three prices are compared
- Order · What, how much, at what rate, by when
- Challan, at the gate · What was sent, what came, what was fit
- Bill · Must agree with the order and the gate
- Payment · Only what all three agree on
- Order, gate, bill: three papers, one number.

Narration:

> Every material a site uses comes down the same chain.
>
> The site asks. The office gets prices, and orders from the best. The order says what, how much, at what rate, and when.
>
> The lorry comes with a challan: what was sent. At the gate, someone counts what actually came, and what was fit to use.
>
> The bill comes later. Before a rupee is paid, three papers must agree: the order, the challan as counted at the gate, and the bill.
>
> Where they do not agree, the difference is money: a short load, a torn bag, a rate that crept up. Checked, it is caught. Not checked, it is simply paid.

## Who does what, when

### 3. Who does what

*Four people, one load of cement · people*

On screen:

- Ravi, site engineer · Ask in time; count at the gate
- Anil, project manager · How much, from whom, at what rate
- Meera, accounts · Pay what the papers agree on
- Malabar Cements Agency · Lorry, challan, bill
- Ramesh Nair, owner · Only when it does not add up
- Each one checks the one before.

Narration:

> Who does what?
>
> Ravi asks for the cement, and counts it at the gate.
>
> Anil decides how much and from whom, and places the order.
>
> Meera checks the bill against the order and the gate, and pays.
>
> And the supplier, Malabar, sends the lorry, the challan and the bill. Ramesh sees it all on the evening report, and steps in only when something does not add up.

## In Mesiri

### 4. First, get the masons working

*In Mesiri · Requests, Stock · Tuesday 8 am · steps*

**Record (on the website, step by step):**

- beat 1 · open `/procurement/requests?project={Green Villa}` · picture: Ravi's request: 100 bags cement, Main block · light: the request
- beat 2 · open `/materials?project={Green Villa}` · picture: Stock: Main block 0 cement, Annex about 110 · light: the two cement rows
- beat 3 · do: Move: 40 bags cement, Annex → Main block · picture: the move filled in, before Save · light: the form
- beat 4 · do: Save · picture: Stock after the move: Main block 40, Annex less 40 · light: the two rows

*As Anil (PROJECT_MANAGER) on day 3, by steps-04.cjs. Needs LRN-F18 (the plan's day 3 has the move). Read the figures off the screen.*

Narration:

> Tuesday, eight o'clock. Ravi's request is the first thing on Anil's screen: a hundred bags for the Main block, with why.
>
> Ordering takes days. But Stock shows the Annex holding a hundred and ten bags, and the Annex uses only ten a day for its plinth beam.
>
> So Anil moves forty bags from the Annex to the Main block, today. A tractor trip across the site, and the masons work by ten.
>
> The move is a record too: the Annex's count goes down, the Main block's goes up, and nothing is lost between them.

## On a real site

### 5. Three suppliers, the same list

*The paper · Three quotations · screen*

Narration:

> Then the order itself. Cement for the next weeks, and steel for the Annex's beams: three hundred bags and two thousand kilos. Anil asks three suppliers for a price on the same list.
>
> Malabar comes back with cement at four hundred rupees a bag, the cheapest of the three. But its steel is seventy-two rupees a kilo.
>
> Kerala Steels: cement at four hundred and twelve, steel at sixty-six. Sri Hardwares sits in the middle on both. Same list, three answers. Which is cheapest depends on what you compare.

## In Mesiri

### 6. Cheapest per item, or cheapest in total?

*In Mesiri · Quotations · steps*

**Record (on the website, step by step):**

- beat 1 · open `/procurement/quotations?project={Green Villa}` · picture: the request to Malabar, Kerala Steels and Sri Hardwares · light: the request
- beat 1 · do: enter the three quotes' rates (the kit's papers) · picture: the three columns of rates · light: the table
- beat 2 · picture: the compare: cheapest cement, cheapest total · light: the totals
- beat 3 · picture: the split: Rs 2,52,000 · light: the split
- beat 4 · do: order: cement 200 bags from Malabar at Rs 400 · picture: the purchase order · light: the order

*As Anil on day 4 (18 Nov), by steps-04.cjs. The compare's words and totals are read off the screen; if it does not show the split, say only what it shows and log it.*

Narration:

> In Mesiri, Anil sends the request to the three from Quotations, and their rates go in as they come.
>
> The compare shows what the eye misses. Cheapest cement: Malabar. Cheapest in total: Kerala Steels, at two lakh fifty-five thousand six hundred.
>
> And cheaper than both: split it. Cement from Malabar, steel from Kerala. Two lakh fifty-two thousand. Three thousand six hundred saved by reading one table.
>
> Anil orders the split. The cement order: two hundred bags now from Malabar, at four hundred, two days to deliver.

## On a real site

### 7. What the lorry says it brought

*The paper · The delivery challan · screen*

Narration:

> Friday, the lorry. The driver hands Ravi the challan: two hundred ordered, a hundred and ninety sent. Ten to follow.
>
> Ravi counts at the gate, as he should. A hundred and ninety bags, yes. But six are torn and set hard. He refuses them, there and then, with the driver watching.

## In Mesiri

### 8. Counted at the gate, said at the gate

*Friday, 11 am · Main block gate · chat*

On screen:

- Ravi says it at the gate; the office can enter the same from the challan on the website.

**Record (real reply):**

- Via: Tell Mesiri in the top bar (same assistant as WhatsApp), as Site engineer (Ravi), on day 6
- Send: `Main block: Malabar cement came, 190 bags on challan, 6 torn, sent back. 184 ok`
- Then: Save
- Record it: send these words in the sample company through Tell Mesiri, as Ravi, and film Mesiri's real reply. If the model is not available (the key's monthly cap), film the website way instead: the order's Material came, 184 bags, then Returns.

Narration:

> Ravi tells Mesiri what came, against the order: a hundred and eighty-four good bags, six torn and sent back.
>
> Mesiri ties it to Anil's order. The order now shows a hundred and eighty-four received, and sixteen still to come: the ten the challan promised, and six to replace the torn ones.
>
> The six torn bags go back on a return note, so Malabar owes Green Villa for them. Nobody has to remember it at the month's end.

## On a real site

### 9. Six bags, two thousand four hundred rupees

*The paper · Return note GV/RN/014 · screen*

Narration:

> This is the return note that goes back with the lorry: six bags, torn and set hard, two thousand four hundred rupees.
>
> In Mesiri it is a debit note against Malabar the same day. What the company owes Malabar drops by two thousand four hundred at once, before their bill even arrives.

### 10. The bill: one line, two problems

*The paper · Malabar's bill · screen*

Narration:

> Sunday, Malabar's bill. One line: a hundred and ninety bags of cement, at four hundred and ten.
>
> Two problems in one line. The rate: the order said four hundred. And the quantity: a hundred and ninety, when a hundred and eighty-four were good and six went back.
>
> Ten rupees a bag is easy to miss on a bill of a lakh. That is why nobody should have to spot it.

## In Mesiri

### 11. The bill, checked against the order and the gate

*In Mesiri · Suppliers · Malabar · steps*

**Record (on the website, step by step):**

- beat 1 · open `/finance/vendors` · picture: Malabar Cements Agency: what is owed, with the return note's Rs 2,400 off · light: Malabar
- beat 1 · do: Add the bill MCA/INV/2611: 190 bags at Rs 410; match it to Friday's delivery · picture: the bill matched to the delivery · light: the match
- beat 2 · picture: the difference: rate above the order; billed more than kept · light: the difference
- beat 3 · do: Pay what is right (or hold the bill for a corrected one) · picture: the payment, or the bill held, and why · light: the payment

*As Meera (FINANCE) on day 8, by steps-04.cjs. Read the difference and the amounts off the screen and say them; if Mesiri does not flag the quantity (only the rate), say only the rate and log it.*

Narration:

> Meera puts the bill in under Malabar, and matches it to the delivery it is for.
>
> Mesiri lays the three side by side: ordered at four hundred, billed at four hundred and ten. A hundred and ninety billed, a hundred and eighty-four kept. And the difference, in rupees, before anything is paid.
>
> Meera asks Malabar for a corrected bill, and pays only what the order and the gate agree on, less the return note.
>
> The money that leaks in most companies, a few rupees a bag, a few bags a load, stays here.

### 12. Back above the line

*In Mesiri · Stock · screen · screen `/materials?project={Green Villa}`*

Narration:

> And on site, the cement is back. The Main block holds what the gate kept, less what has been used since, above its least of a hundred bags.
>
> Sixteen bags are still to come on Malabar's order. Anil does not chase them from memory: the order shows them as not yet delivered, until they are.

## What can go wrong

### 13. Five ways a load of cement leaks money

*What can go wrong · leaks*

On screen:

- Idle crew · 2 days × 6 people, paid for nothing
- One quote, or the wrong total · Rs 3,600 left on the table
- Short load signed for · 190 on paper, 184 usable
- Torn bags kept · Rs 2,400, gone
- Bill paid as it came · Rs 10 a bag above the order
- Order, gate, bill: when all three agree, pay.

Narration:

> Five ways a load of cement leaks money.
>
> A crew standing idle while the order is placed. Two days of six people is twelve days' wages for nothing.
>
> Ordering from one supplier without asking three, or comparing the wrong total.
>
> A short load signed for at the gate, or torn bags accepted because the driver was in a hurry.
>
> And a bill paid as it comes: ten rupees a bag above the order, six bags that never stayed. Small on one bill, a margin across a year.

## Recap and check yourself

### 14. Three questions

*Check yourself · questions*

On screen:

- No cement, the order takes days: what first?
- Which three papers must agree before paying?
- 190 bags at Rs 410: what is wrong?

Narration:

> Three questions. Pause, and answer them before you go on.
>
> One: the Main block has no cement, and an order takes days. What does Anil do first? Move bags from a site that has them, the same morning.
>
> Two: which three papers must agree before Meera pays? The order, the challan as counted at the gate, and the bill.
>
> Three: Malabar's bill says a hundred and ninety bags at four hundred and ten. What is wrong? The rate, against the order's four hundred, and the quantity, against the hundred and eighty-four kept.
>
> Next: wages week. The attendance Ravi sends every morning becomes Saturday's wage sheet. Now play the material chain yourself: chapters five and eight of the guided project.
