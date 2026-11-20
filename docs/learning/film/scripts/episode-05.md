# Episode 5: Wages week

> Made from `episode-05.json` by `script_md.py`; edit the JSON, then run it again.

**Status:** DRAFT script for Ilan's review (20 Nov 2026). Not recorded. The sample company plays this week as it is (days 2 to 7, from the 62-day plan); no story change is needed. Recording brief: RECORDING.md.

**Objective:** By the end you can run the weekly labour cycle: the morning attendance, the muster roll, the wage sheet, the owner's approval, Meera's payment; an advance given and taken back; and compare what labour was paid with the work it did.

**Length:** 10 scenes, 781 words of narration (about 5 minutes)

## Cold open

### 1. Wages week

*Mesiri · The course · Episode 5 · title*

On screen:

- Green Villa · 6 days · Rs 75,000
- Attendance → muster → wage sheet → approve → pay

Narration:

> Saturday, five in the evening. At the Main block and the Annex, the crews wait to be paid.
>
> About fifteen people across two sites, six days. Seventy-five thousand rupees for one week at Green Villa.
>
> Who came, which days, at what wage, what was already given in advance, and was it worth it? This episode is that Saturday, and the six mornings before it.

## On a real site

### 2. How a site's labour is paid

*On a real site · story*

On screen:

- Own workers · Daily wage, paid Saturday for the days they came
- Contractor's crew · Heads counted daily; the contractor paid for the crew
- Advance · Money before Saturday, taken back from the pay
- The register · Who came, each day: the rest is arithmetic
- A wrong register is a wrong payroll, every week.

Narration:

> Two kinds of people work on a site like Green Villa.
>
> The company's own workers, on a daily wage: a mason at eleven hundred rupees, a helper at seven fifty. Paid every Saturday, for the days they came.
>
> And a labour contractor's crew: here, Rahim's helpers. The company counts heads each day, and pays Rahim for the crew; Rahim pays his people.
>
> In between, someone always needs money before Saturday: a hospital visit, a festival. That is an advance, and it comes back out of the next pay.
>
> Underneath it all is one register: who came, each day. Everything else is that register, multiplied.

## Who does what, when

### 3. Who does what

*One week, five people · people*

On screen:

- Ravi, site engineer · Who came, every morning
- Meera, accounts · Advances; pay on Saturday
- Ramesh Nair, owner · Approve the week before it is paid
- Anil, project manager · Did the labour buy the work?
- Rahim, labour contractor · My crew's money
- One register, read by four people.

Narration:

> Who does what?
>
> Ravi says who came, every morning, as you saw in episode three.
>
> Meera gives advances, and pays on Saturday. Ramesh approves the week's sheet before a rupee goes out.
>
> Anil watches whether the labour bought the work. And Rahim collects for his crew.

## In Mesiri

### 4. Two thousand rupees before Saturday

*In Mesiri · Advances · Wednesday · steps*

**Record (on the website, step by step):**

- beat 1 · open `/labour/advances?project={Green Villa}` · picture: Advances: what is owed, by person · light: the list
- beat 2 · do: Give an advance: Suresh, Rs 2,000, from the account it is paid from · picture: the advance filled in, before Save · light: the form
- beat 3 · do: Save · picture: Suresh owes Rs 2,000 · light: Suresh's balance

*As Meera (FINANCE) on day 4: the plan's entry 'Advance of Rs 2,000 to Suresh' is hers; do it on screen (steps-05.cjs).*

Narration:

> Wednesday. Suresh, a mason at the Main block, needs two thousand rupees before Saturday.
>
> Meera gives it, and puts it in Mesiri: Suresh, two thousand, today, and the account it was paid from.
>
> Now it is owed. Suresh's balance shows it, and so will Saturday's sheet. Nobody has to remember it on a slip of paper.

### 5. The register, without a register

*In Mesiri · Muster roll · steps*

**Record (on the website, step by step):**

- beat 1 · open `/labour?view=muster&project={Green Villa}&site={Main block}` · picture: the Main block's muster: each worker, each day · light: the grid
- beat 2 · picture: Sunil absent Thursday, Prakash Friday, Joseph Saturday · light: the three absences
- beat 3 · picture: Rahim's crew, a headcount per day · light: the crew's line

*As the owner on day 7, before approving. Say only the absences the screen shows.*

Narration:

> The muster roll is the register, made from Ravi's mornings. Each worker, each day: present, half day, or absent.
>
> At the Main block, Sunil was away on Thursday, Prakash on Friday, Joseph on Saturday. Nobody wrote a register; Ravi said who came.
>
> Rahim's crew is a count, not names: two helpers most days, four when the ceiling plastering began.

### 6. The wage sheet makes itself

*In Mesiri · Wages · Saturday · steps*

**Record (on the website, step by step):**

- beat 1 · open `/labour/wages?project={Green Villa}` · picture: the week's sheet, a row per person · light: the sheet
- beat 2 · picture: Suresh's row: 6 days, Rs 6,600, advance Rs 2,000 taken back, Rs 4,600 · light: Suresh's row
- beat 3 · picture: Rahim's crew: one row, paid to the contractor · light: the crew's row
- beat 4 · do: Approve · picture: the sheet approved, its total · light: the total

*As the owner (ADMIN) on day 7: the plan's 'Approve Green Villa's wage sheet for the week' is his. Read every figure off the sheet; the Rs 75,000 is the plan's gross for both sites, days 2 to 7.*

Narration:

> Saturday. The week's wage sheet is already made from the attendance: each person's days, times their wage.
>
> Suresh: six days at eleven hundred, six thousand six hundred. Less the two thousand advance from Wednesday: four thousand six hundred to pay.
>
> Rahim's crew is one line, paid to Rahim: their days, at seven hundred a day.
>
> Ramesh reads the total, seventy-five thousand for the week, and approves it. Until he does, nothing can be paid.

### 7. Paid, and written down as it is paid

*In Mesiri · Paying · steps*

**Record (on the website, step by step):**

- beat 1 · open `/labour/wages?project={Green Villa}` · do: Pay all due, from the bank account · picture: the pay dialog · light: the dialog
- beat 2 · picture: every row paid · light: the paid rows
- beat 3 · picture: one worker's slip · light: the slip

*As Meera (FINANCE) on day 7: the plan's 'Pay Green Villa's wages for the week' is hers.*

Narration:

> Then Meera pays, from the bank and the site's cash, every row still due.
>
> Each payment is a record: who, how much, from which account, on which day. The cash box and the bank go down by exactly that.
>
> And each worker's slip is there, if one ever asks how this week's money was worked out.

### 8. Did the labour buy the work?

*In Mesiri · Green / red · screen · screen `/cost/green-red?project={Green Villa}`*

Narration:

> Paying the right people the right amount is half of it. The other half: did that labour buy the work?
>
> The BOQ already says what each unit of work should cost in labour. Every day, Mesiri puts the labour paid beside the labour the work earned.
>
> The Annex is green: its crew of seven cast twenty-four metres of plinth beam a day, worth more than ten thousand rupees of labour, for less than six thousand paid.
>
> The Main block is red. Seven people, six and a half thousand rupees a day, on conduit work the BOQ pays ninety rupees a point for: about two thousand a day earned.
>
> That is Anil's question for Monday: the masons are waiting for the plastering. Start it, or send two of them to the Annex.

## What can go wrong

### 9. Five ways a payroll leaks

*What can go wrong · leaks*

On screen:

- Names, not people · Present on paper, not on site
- Crew over-billed · 6 billed, 4 counted
- Advance forgotten · Rs 2,000 on a lost slip
- Paid, not productive · Rs 6,550 a day for Rs 1,980 of work
- Paid before approved · Nobody checked the total
- Who came, what they did, what they were paid: one register.

Narration:

> Five ways a payroll leaks.
>
> A name in the register for someone who did not come. Copied forward every day, it is a wage every week for nobody.
>
> A contractor paid for six heads when four were counted.
>
> An advance given in cash and never taken back, because it was on a slip that went missing.
>
> And the biggest, because it looks like work: a full crew, paid in full, on a site where the work does not move.

## Recap and check yourself

### 10. Three questions

*Check yourself · questions*

On screen:

- 6 days at Rs 1,100, Rs 2,000 advance: paid?
- How is Rahim's crew paid?
- Present every day, yet red: why?

Narration:

> Three questions. Pause, and answer them before you go on.
>
> One: Suresh worked six days at eleven hundred, and took two thousand on Wednesday. What is he paid on Saturday? Four thousand six hundred.
>
> Two: how is Rahim's crew paid? As one line on the sheet, their days at the crew's rate, paid to Rahim.
>
> Three: the Main block's crew was paid in full and was present every day. Why is it red? Because the work it did earned far less labour than it was paid.
>
> Next: problems and machines. A problem from WhatsApp to closed, and a machine's day. Now play a wages week yourself: chapter six of the guided project.
