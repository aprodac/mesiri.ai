# Green Villa: the series plan

> Asked 20 Nov 2026 (Ilan): "First, let's properly know what the objective is overall. Let's note down that, and for
> each episode, what the objective is ... After that, only start creating the episodes." This page is that note.
> Nothing is filmed until it is agreed. Status: **draft for Ilan's review**.
>
> **The learning order (watch an episode, then play its days in the simulation), what is made and what is next:
> [../LEARNING_PATH.md](../LEARNING_PATH.md)** (20 Nov), including a review of this syllabus against the simulation.

## 1. Why we are making this

Two needs, in Ilan's words (20 Nov):

1. *"Us understanding the A to Z, taking a project from A to Z ... from the start to end how each thing happens, what
   role does what when."*
2. *"Making sure the product is organized and easy for any user to understand."*

And what it is not: *"The videos you are giving is about how to sell. That's not what we want."* It is told *"as a
movie ... episodes ... that cinematic storytelling"*, like the simulation's scenes.

## 2. The objective

**After watching the series, anyone in the Mesiri team, even someone who has never been on a building site, can take
one project from the first estimate to the end of the defects period and explain, at every step: what happens on the
site and in the office, who does it and when, why it matters (what is lost if it is skipped or late), and exactly
where it happens in Mesiri (the WhatsApp message or the page, and what it leads to).**

Three things follow from it:

- **Understanding, not selling.** Each episode teaches how the work is done. Mesiri appears as the place the work is
  recorded, never as a pitch. No claims about competitors, prices or time saved.
- **The whole product, in the order a project uses it.** Every one of the 79 built pages appears in the episode where
  it is first needed (section 6). A page the story cannot show yet is said to be missing, not skipped silently.
- **A test of the product, too.** Filming every step on the real screens shows where a step is hard, unclear or
  repeated. Each episode ends with a short list of what we found, which goes to the tracker (need 2 above).

**Who it is for:** the Mesiri team first (founders, new people, support, sales learning the domain). Later, cut
versions can teach customers' own staff; that is not the aim now.

## 3. The story we tell

One continuous story, the one the sample company plays (`backend/.../learn/sample_plan.py`), so every screen is real:

- **Green Villa Builders**, a building contractor with two projects: **Green Villa** (Main block, Annex), handed over
  on day 62, and **Lake View Apartments** (Tower A, Tower B), for the client Lake View Builders.
- **The cast:** the **Owner** (runs the company, approves wages, sends the running bills, hands over); **Anil**,
  project manager (orders, counts work on the BOQ, closes problems, runs the tiling subcontract); **Ravi**, site
  engineer (records every site day on WhatsApp, asks for material, receives it); **Meera**, accounts (books bills,
  pays suppliers, subcontractors and wages, records what the client pays).
- **Outside:** Malabar Cements Agency, Kerala Steels, Periyar Sand & Aggregates, Thrissur Blocks (suppliers); Joy
  Tiling Works (subcontractor); Suresh's labour team.
- **The days:** the plan's 62 days (1,477 entries) for the middle of the project; before day 1 (winning the job,
  setting up) and after day 62 (defects period, retention) come from the guided project and are told as such.

The storyboard is the A-to-Z map (`az-map/`, published as "Green Villa A to Z"): its chains are the episodes' spines.

## 4. How every episode is built

| Part | What it does | About |
|---|---|---|
| Cold open | One moment from the episode's days, cinematic (dusk, dawn, the day card) | 20 s |
| On a real site | What this part of the work is and why it matters, with no software: the trade, the people, the money, what goes wrong | 1 to 2 min |
| Who does what, when | The swimlane for these days: each person's steps and the handoffs between them, from the map | 1 min |
| In Mesiri | The chain played step by step: the WhatsApp message or the page, the card or the record, where it shows next | 3 to 5 min |
| What can go wrong | The leak this part prevents, and what Mesiri shows when it happens (a short load, a bill above the order, a red line) | 1 min |
| Recap and check yourself | Three questions with answers; then "next episode" | 1 min |
| What we found | Shown only to the team: steps that were hard, unclear or repeated on screen, each a tracker item | (notes) |

Look and sound: the simulation's scene language (dark screens, the brand font rising, ink lines, the iris; dusk and
dawn between days; cast cards; chapter cards), George's voice (ElevenLabs), subtitles burned in and as `.srt`, the
screens filmed from a local copy of Mesiri with the sample company played to that day: **never production**.
Length: 6 to 10 minutes an episode; about 80 minutes in all.

## 5. The episodes and their objectives

The Prologue is the existing Episode 1 ("How a construction company works", 19 Nov), kept: it was understood. The
old Episode 2 ("What owners want") is retired: it was about selling.

| # | Episode | Days | Objective: by the end you can... | Chain(s) from the map |
|---|---|---|---|---|
| 0 | **Prologue: how a construction company works** | — | name the six phases, the people, how money flows and the ten biggest leaks | (done) |
| 1 | **The job is won** | before day 1 | explain what is agreed before the first brick (drawings → BOQ → rates → contract, retention, advance) and why the BOQ is the yardstick for everything after | guided project ch. 3 |
| 2 | **Setting up** | before day 1 | list what must exist before day 1 and who sets it up: company, project, sites, the team on WhatsApp, items, suppliers and rates, the schedule and material plan, the daily report time | guided project ch. 2 |
| 3 | **A day on site** | 2 | follow one site day from Ravi's first WhatsApp message to the owner's evening report, and say what each kind of record is for (attendance, work, material used, expenses, conditions) | a day's site records → DPR |
| 4 | **Cement runs short** | 2 to 14 | walk a material chain across all four people: request → quotation and rate → order → delivery (and a short or damaged load returned) → stock and use → supplier bill checked against order and delivery → payment; and a month-end stock count | "Cement for Main block" |
| 5 | **Wages week** | 2 to 9 | run the weekly labour cycle: attendance → muster roll → wage sheet → owner approves → Meera pays; advances given and taken back; teams; and compare labour paid with work done | "A week's wages" |
| 6 | **Problems and machines** | 3 to 30 | follow a problem from WhatsApp to fixed (an issue, a task for someone, closed), and a machine's day (log, breakdown, hire check), and say why idle time costs money | "A problem on site" |
| 7 | **The subcontractor** | 34 to 49 | pay a subcontractor only for measured work: work order → measurement → bill → retention and TDS → payment | "The tiling subcontract" |
| 8 | **Billing the client** | 23 to 51 | explain how money comes in: measured work → running bill → client pays; an extra the client asks for (a variation) priced, approved and billed; what the client sees; why a late bill hurts | "The first running bill" |
| 9 | **Is it making money?** | around 30 | read a project's health halfway: work counted on the BOQ, green and red, budget against actual, materials against the BOQ, cost centres; and decide what to do about a red line | BOQ counts → cost control |
| 10 | **Month end** | 30 and 60 | close a month: GST and TDS, the cash and bank book, the books from the records (ledgers, trial balance, P&L, balance sheet), closing the month, the Tally export | month-end entries (batch 1) |
| 11 | **Handover, and after** | 55 to 62, then a year | close a project: the last stages, the snag list, the final bill, handover; then the defects period and the retention released; the credits | handover → retention |

## 6. Every page has an episode

Each built page (lib/module-map.ts) appears in the episode where a project first needs it. "Story" says whether the
62-day plan already uses it or must be extended first (batches below).

| Module | Pages | Episode | Story |
|---|---|---|---|
| Planning | Project start, BOQ & budget | 1 | ready (guided project) |
| Planning | Schedule, Material plan, Places, Drawing check, Documents, Live plans | 2 | batch 3 |
| Settings | Projects & sites, Team, Company, WhatsApp, Settings, Bring your data, Activity log | 2 | ready (setup); Activity log batch 3 |
| Materials | Items | 2 | batch 2 |
| Procurement | Rates | 2, 4 | batch 2 |
| Site | Today, Daily reports, Site log, Weekly & monthly, Analytics, Home | 3 | ready |
| Materials | Stock, Movements, Stock value | 3, 4 | ready |
| Finance | Expenses | 3 | ready |
| Materials | Requests, Stock count | 4 | ready; Stock count batch 2 |
| Procurement | Requests, Quotations, Purchase orders, Pending deliveries, Returns, Suppliers | 4 | ready; Quotations, Returns batch 2 |
| Finance | Suppliers (bills, payments) | 4 | ready |
| Site | Approvals | 5 | ready |
| Labour | Attendance, Muster roll, Workers, Wages, Advances, Teams | 5 | ready; Teams batch 3 |
| Site | Issues | 6 | ready |
| Tasks | My tasks, All tasks, Overdue, Done | 6 | batch 3 |
| Equipment | Machines, Daily log, Hire check, Vehicles, Shuttering & tools | 6 | batch 2 |
| Subcontract | Subcontractors, Work orders, Bills & checks | 7 | ready |
| Client billing | Clients, RA bills | 8 | ready |
| Client billing | Variations, Client view | 8 | batch 3 |
| Accounts | Receivables | 8 | ready |
| Cost control | Overview, Green / red, Budget vs actual, Materials vs BOQ, Cost centres | 9 | ready |
| Accounts | Project P&L | 9 | ready |
| Finance | Money, Settings | 10 | ready; Settings is setup |
| Accounts | Cash & bank book, Day book, Ledgers, Cash flow, Profit & loss, GST, TDS, Tally export, Trial balance, Balance sheet, Chart of accounts, Months | 10 | ready: Day book, Ledgers, Cash flow, P&L; the rest batch 1 |

## 7. What must be true before filming

1. **The story covers every page** (the batches, each played end to end through the real API, the plan's tests and
   `docs/plans/sample-plan.md` regenerated):
   - **Batch 1, month end and books** (episode 10): GST, TDS, the cash and bank book, closing the month, the Tally
     export, trial balance, balance sheet. Accounts is on for every company since 20 Nov (BE-07).
   - **Batch 2, buying and machines** (episodes 2, 4, 6): items, rates, quotations, returns, stock count, equipment.
   - **Batch 3, planning, people and the client** (episodes 2, 5, 6, 8): schedule, material plan, places, drawing check,
     documents, tasks, labour teams, variations, client view, activity log.
2. **The screens are the ones we keep:** the new sidebar, top bar, Home and Today (UX-74, UX-75) are in; any page found
   hard in an episode's "What we found" is fixed before its final cut.
3. **The figures said are the figures on screen:** every number in the narration is read off the sample company on
   that day.

## 8. How we know it worked

- Someone new watches the Prologue and episodes 1 to 11 and answers each episode's three questions without help.
- They then play the sample company themselves (any role) and do that role's part of a day without asking.
- Every page in section 6 has appeared on screen at least once, in an episode that says why it is needed.
- Each episode's "What we found" list is in the tracker, and the worst items are fixed.

## 9. Order of work

1. **This plan agreed** (Ilan).
2. Batch 1, then episode 10's script; batch 2; batch 3 (each: story extended, played, map regenerated).
3. Scripts for episodes 1 to 11, each from this page's objective, read and agreed before filming.
4. Film in story order: 1, 2, 3, ... 11; each sent for review before the next.

## Open questions for Ilan

- ~~Keep the **Prologue** as it is, or redo it in the series' look?~~ Kept as it is (20 Nov); file `episode-00.json`.
- ~~**Language:** English narration with English subtitles first; Malayalam later?~~ English first (20 Nov).
- ~~**Length:** 6 to 10 minutes an episode (about 80 in all), or shorter?~~ Agreed 20 Nov: 6 to 10 minutes.
- Anything the series must teach that is missing from section 5?
