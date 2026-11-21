# Episode 6: Problems and machines

> Made from `episode-06.json` by `script_md.py`; edit the JSON, then run it again.

**Status:** DRAFT for Ilan's review (21 Nov 2026). Recorded from real entries in the sample company (days 4, 5, 6 and 9); the words follow the screens.

**Objective:** By the end you can follow a problem from WhatsApp to fixed (a log, a problem, a task for someone, closed), and a machine's day (log, breakdown, hire check), and say why idle time costs money.

**Length:** 12 scenes, 832 words of narration (about 6 minutes)

## Cold open

### 1. Problems and machines

*Mesiri · The course · Episode 6 · title*

On screen:

- Annex · day 5 · the mixer stops
- Log → problem → task → fixed → bill checked

Narration:

> Thursday, half past ten, at the Annex. The plinth filling is half done, and the mixer goes quiet.
>
> The motor has burnt out. Eight people, a day's concrete to mix, and a machine the company pays for by the hour.
>
> Who writes down that it stopped? Who gets it fixed, and by when? And when the hire company's bill comes, who makes sure we do not pay for the hours it stood still? This episode is that week.

## On a real site

### 2. What stops a site

*On a real site · story*

On screen:

- What stops a site · Machine, drawing, material, people, weather
- Twice the cost · The work not done, and the crew paid to wait
- Hired machines · Billed by the hour, from the hire company's log
- What a problem needs · Said, owned by a day, closed; and the machine's hours
- A problem nobody owns stays open. A machine nobody logs is billed in full.

Narration:

> Five things stop a site: a machine, a drawing, a material, a person, the weather.
>
> Each one costs twice. The work that does not get done, and the people who are paid to wait for it.
>
> A hired machine costs a third way. The hire company bills by the hour, from its own operator's log. If nobody on site writes down the hours it stood still, those hours are on the bill.
>
> So a problem on site needs three things: someone to say it, someone to own the fix by a day, and a record that it was fixed. And a hired machine needs one more: its hours, every evening.

## Who does what, when

### 3. Who does what

*One breakdown, five people · people*

On screen:

- Ravi, site engineer · The mixer's hours; says when it stops
- Anil, project manager · Owns the fix: a task, a person, a day
- Kerala Earthmovers · Their mixer, their mechanic, their bill
- Meera, accounts · The bill against the hours logged
- Ramesh Nair, owner · What is stuck, and who has it
- One machine's day, read by four people.

Narration:

> Who does what?
>
> Ravi logs the mixer every evening, and says when it stops.
>
> Anil owns the fix: he makes it a task, with a person and a day. Ravi gets the mechanic there.
>
> Meera checks the hire company's bill against the log before it is paid. And Ramesh sees what is stuck, every morning.

## In Mesiri

### 4. A machine on hire

*In Mesiri · Equipment · Wednesday · steps*

**Record (on the website, step by step):**

- beat 1 · open `/equipment` · picture: Machines: the concrete mixer, hired, at the Annex · light: the mixer's row
- beat 2 · open `/equipment/log` · picture: Daily log: the mixer's hours, day by day · light: the day's log
- beat 3 · open `/equipment` · picture: the mixer this month: hours worked, idle, broken down · light: the month's hours

*As the owner on day 4 (Wednesday): the cast put the mixer on hire on day 2 and logged days 2 to 4. Say only the hours the screen shows.*

Narration:

> On Monday Anil put the mixer on hire for the Annex: Kerala Earthmovers, four hundred and fifty rupees an hour.
>
> Since then, Ravi's evening message has carried one more line: the mixer's hours. Seven on Monday, seven on Tuesday, seven today: twenty-one this month.
>
> That daily log is the only record on our side of the hours the mixer worked. Keep it in mind: it matters on the day the bill comes.

### 5. The mixer stops

*Thursday · Annex · evening · chat*

On screen:

- Mesiri's own reply, recorded in the sample company.

**Record (real reply):**

- Via: Tell Mesiri (same assistant as WhatsApp), as Site engineer (Ravi), on day 5
- Send: `Annex mixer worked only 1 hour today. Motor burnt out mid-morning, stopped 6 hours`
- Then: Save
- Send these words in the sample company as Ravi on day 5; the real card replaces this one.

Narration:

> Thursday evening. Ravi tells Mesiri what the mixer did: one hour, then the motor burnt out, and it stood for six.
>
> Mesiri sends back the machine's day as a card: one hour worked, six hours broken down. Ravi taps Save.
>
> And because it broke down, Mesiri opens a problem by itself, on the Annex, with the hours in its words. Ravi did not have to report it twice.

### 6. A problem becomes a task

*In Mesiri · Issues · Thursday · steps*

**Record (on the website, step by step):**

- beat 1 · open `/issues` · picture: Issues: the mixer's breakdown, open · light: the problem
- beat 2 · do: Open it → Make a task: Get Kerala Earthmovers' mechanic to the Annex mixer before 8 am · For Ravi · Due tomorrow · picture: the task form, from the problem · light: the form
- beat 3 · do: Give task · picture: the problem with its task · light: the linked task

*As Anil (PROJECT_MANAGER) on day 5, after Ravi's message.*

Narration:

> Anil sees it on Issues: the mixer's breakdown, high, open, on the Annex.
>
> A problem is not fixed by being seen. Anil makes it a task: get Kerala Earthmovers' mechanic to the Annex before eight tomorrow. For Ravi, due tomorrow.
>
> The task is linked to the problem. Whoever opens one sees the other: who has it, and by when.

## What the owner sees

### 7. What is stuck, and who has it

*What the owner sees · Thursday night · steps*

**Record (on the website, step by step):**

- beat 1 · open `/` · picture: Home as the owner
- beat 2 · picture: Green Villa's open problems · light: Green Villa's row
- beat 3 · open `/issues` · picture: the mixer's problem: who is on it, and by when · light: who is on it

*As the owner on day 5, after Anil's task.*

Narration:

> Thursday night, Ramesh opens Mesiri.
>
> Green Villa's row on Home counts its open problems. One tap shows them.
>
> The mixer: high, raised from Ravi's log, and who is on it: Ravi, due tomorrow morning. Ramesh does not have to phone anyone to find out. If tomorrow evening it is still open, that is the call he makes.

## In Mesiri

### 8. Fixed, and closed

*In Mesiri · Tasks · Friday · steps*

**Record (on the website, step by step):**

- beat 1 · open `/tasks?view=all` · picture: the task, due today · light: the task
- beat 2 · do: Done · picture: the task done · light: the task
- beat 3 · open `/issues` · do: the problem → Mark fixed: Mechanic rewound the motor before work; mixer running from 8 am · picture: the problem fixed · light: the problem

*As Anil on day 6: his task_status and issue_resolve are his to do on screen.*

Narration:

> Friday, before eight. Kerala Earthmovers' mechanic rewinds the motor; by eight the mixer is running.
>
> Anil marks the task done.
>
> And closes the problem, with what was done. The mixer worked its seven hours on Friday, and Ravi's log says so.

### 9. The bill meets the log

*In Mesiri · Hire check · Monday · steps*

**Record (on the website, step by step):**

- beat 1 · open `/equipment/hire` · picture: Hire check: the mixer, its hours this month · light: the mixer
- beat 2 · do: Enter a bill: Monday to Saturday, 42 hours, Rs 18,900, KEE/2027/0118 · picture: the bill form · light: the form
- beat 3 · do: Check the bill · picture: Over: Bill says 42 hours; 36 recorded on site · light: the check

*As Meera (FINANCE) on day 9: the hire bill is hers.*

Narration:

> Monday. Kerala Earthmovers' bill for the week: forty-two hours, eighteen thousand nine hundred rupees.
>
> Forty-two is six days at seven hours: as if the mixer never stopped. Meera enters it in Hire check.
>
> Mesiri puts it beside Ravi's log: thirty-six hours recorded on site. The bill asks for six hours more: two thousand seven hundred rupees, and the GST on it.

### 10. Paid for the hours it worked

*In Mesiri · Hire check · Monday · steps*

**Record (on the website, step by step):**

- beat 1 · picture: the bill over the log · light: the check
- beat 2 · do: Remove; Enter a bill: 36 hours, Rs 16,200 · picture: the corrected bill · light: the form
- beat 3 · do: Check the bill · picture: matches the hours recorded · light: the check

*As Meera on day 9, after the first bill (kept).*

Narration:

> Anil phones Kerala Earthmovers with the log in front of him. Six hours, motor burnt out, their mechanic came on Friday. They agree.
>
> Meera removes the first bill and enters the corrected one: thirty-six hours, sixteen thousand two hundred rupees.
>
> Now it matches the hours recorded. Without Thursday's line in Ravi's message, nobody could have asked.

## What can go wrong

### 11. Five ways a problem costs more

*What can go wrong · leaks*

On screen:

- No log · 42 hours billed, nothing to check against
- Nobody owns it · Seen by all, fixed by none
- Closed on paper · Task done, problem still open
- Paid to wait · A crew beside a broken mixer
- Bill paid as sent · Rs 2,700 + GST for hours it stood
- Say it, own it by a day, close it; log the machine every evening.

Narration:

> Five ways a problem costs more than it should.
>
> A machine with no daily log: the hire company's bill is the only record, and it is paid as it is.
>
> A problem everyone saw and nobody owned: it is still open on Monday.
>
> A task closed with the problem still open, or a problem closed with nothing done.
>
> And the crew waiting beside a broken machine, paid in full, with nobody asking where else they could work.

## Recap and check yourself

### 12. Three questions

*Check yourself · questions*

On screen:

- 7 hrs × 5 days + 1 hr, at Rs 450: the bill?
- Who owns a problem's fix?
- How did the problem get raised?

Narration:

> Three questions. Pause, and answer them before you go on.
>
> One: the mixer worked seven hours on five days and one hour on the sixth. What should the week's bill be at four fifty an hour? Thirty-six hours: sixteen thousand two hundred rupees.
>
> Two: who owns a problem's fix? A person, with a day: here, Ravi by eight on Friday, given by Anil.
>
> Three: how did Mesiri know the mixer had broken down? From Ravi's evening line: the breakdown hours raised the problem by themselves.
>
> Next: the subcontractor. Paying Joy Tiling only for the work that was measured.
