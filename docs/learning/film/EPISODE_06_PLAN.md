# Episode 6, "Problems and machines": the plan

> Asked 21 Nov 2026 (Ilan): "just continue with the next episode". Episodes 4 and 5 are the other session's (LRN-F19,
> LRN-F21), so this is the next one. Status: **draft; the recommended answers in section 6 are what is built unless
> Ilan says otherwise**. Series objective and the episode's row: [SERIES_PLAN.md](SERIES_PLAN.md) section 5.
> Recording rules: [RECORDING.md](RECORDING.md) (real entries only). Tracker: LRN-F24 (plan and script),
> LRN-F25 (story batch).

## 1. Objective

From the series plan, unchanged:

> By the end you can follow a problem from WhatsApp to fixed (an issue, a task for someone, closed), and a machine's
> day (log, breakdown, hire check), and say why idle time costs money.

Said as the viewer's test: *a hired mixer stops on site. Say who records it and where, who owns the fix and by when,
how you know it is fixed, and how you make sure you do not pay the hire company for the hours it stood still.*

Length: about 7 minutes.

## 2. What we found planning it: nothing to film yet

| Needed on screen | The sample company's 62 days (`sample_plan.py`) | The starter kit (`green_villa.HIRE`, `make_kit.py`) |
|---|---|---|
| A machine on hire | none: no machine is ever added | Kerala Earthmovers & Equipments' concrete mixer for the Annex, ₹450 an hour |
| The daily machine log | none | "36 hours logged" (said, never logged) |
| A breakdown | the 6 plan issues are typed in by hand; one is the Tower B vibrator (day 17, a hand tool, not a hired machine) | "two half days the mixer stood idle with the motor fault" |
| A task for someone, done | none: the Tasks pages are empty all 62 days | none |
| The hire bill and its check | none | bill KEE/2027/0118: 42 hours billed, 36 logged; the catch is 6 hours (₹2,700 + GST) |
| Kerala Earthmovers as a supplier | not in the seed's suppliers | named on the bill |

The kit has the lesson; the played days do not. As with episode 4, the story is played first (a story batch), then
the episode is scripted on the real screens.

## 3. The story (batch for episode 6)

One chain carries both halves of the episode: the problem *is* the machine's breakdown.

| Day | Date | Who | What, and where in Mesiri |
|---|---|---|---|
| seed | before day 1 | (seed) | Kerala Earthmovers & Equipments added as a supplier (Equipment hire) |
| 2 | Mon 16 Nov | Anil | The mixer put on hire for the Annex from today: Kerala Earthmovers, ₹450 an hour, no minimum hours (Equipment, Machines) |
| 2 to 7 | Mon to Sat | Ravi | Each evening the mixer's line in his site message: hours worked (Machines, Daily log). Days 2, 3, 4 and 7: **7 hours** |
| 5 | Thu 19 Nov | Ravi | "Mixer 4 hours, motor tripping, stopped 3 hours": 4 worked, 3 breakdown. Mesiri raises the problem itself from the breakdown (an issue, Equipment breakdown, on the Annex) |
| 5 | Thu 19 Nov | Anil | Opens the problem, gives it a task: "Send a mechanic for the mixer motor", for Kerala Earthmovers, due tomorrow, linked to the issue (Tasks) |
| 6 | Fri 20 Nov | Ravi | "Mixer 4 hours, stopped 3 hours till the mechanic came": 4 worked, 3 breakdown (a second half day lost) |
| 6 | Fri 20 Nov | Anil | Task done ("Starter relay changed"); the problem closed with the same note (Site, Issues) |
| 9 | Mon 23 Nov | Meera | Kerala Earthmovers' bill KEE/2027/0118 for 16 to 21 Nov: **42 hours**, ₹18,900 + GST (Equipment, Hire check: *over*, "Bill says 42 hours; 36 recorded on site", ₹2,700 more) |
| 9 | Mon 23 Nov | Anil | Phones Kerala Earthmovers; they accept the log. The bill corrected to 36 hours, ₹16,200 (Hire check: *ok*) |

Logged: 7 + 7 + 7 + 4 + 4 + 7 = **36 hours worked**, 6 hours breakdown, 6 days on site, no day missing (the period is
Monday to Saturday, so Sunday's no-log does not count). Billed 42 = 6 days × 7 hours, as if the mixer never stopped.
The kit's figures stay as they are; only the bill's "For" line changes to the week it covers (plinth beam and filling).

## 4. The episode (draft order, about 7 minutes)

| Part | What | About |
|---|---|---|
| Cold open | Day 5, the Annex: the mixer's hum stops mid-pour; the crew wait with empty pans | 20 s |
| On a real site | What stops a site: a machine, a drawing, a material, a person, the weather. Hired machines are paid by the hour whether they work or not, unless someone writes down when they stopped. Idle crew cost the wage too: 7 people × 3 hours | 1.5 min |
| Who does what, when | Ravi records (the log, the problem); Anil owns the fix (the task, closing it); Meera books the bill; the owner sees what is stuck | 1 min |
| In Mesiri | (1) the machine on hire (steps, Anil, day 2); (2) Ravi's evening line with the breakdown (real reply, day 5); (3) the problem it raised, and Anil's task for Kerala Earthmovers (steps, day 5); (4) day 6: task done, problem closed (steps); (5) the hire bill (paper) and Hire check saying *over* (steps, Meera, day 9); (6) the bill corrected | 3.5 min |
| What the owner sees | Home on day 5: the open problem and who owns it; Hire check on day 9: the 6 hours to question | 40 s |
| What can go wrong | No log → a bill nobody can question; a problem with no owner → it stays open for days; a task closed with the problem still open | 1 min |
| Recap and check yourself | Three questions | 1 min |

## 5. What this needs built

- **Story batch (LRN-F25):** in `green_villa.py`, the machine story (`HIRE` gains the days and hours above); in
  `sample_plan.py` new kinds: `machine` (POST `/equipment`), `machine_log` (POST `/equipment/logs`), `task` (POST
  `/tasks`), `task_status` (POST `/tasks/{task_id}/status`), `hire_bill` (POST `/equipment/hire-bills`),
  `hire_bill_fix` (PATCH `/equipment/hire-bills/{bill_id}`); Kerala Earthmovers in the seed's suppliers. The plan test
  and the Postgres test that all 62 days still play.
- **Script (LRN-F24):** `episode-06.json`, `scripts/episode-06.md`, `steps-06.cjs`, recorded with `record.cjs`.

## 6. Questions, with the recommended answer (built unless Ilan says otherwise)

1. **Which problem carries the episode?** *Recommended:* the mixer's breakdown (it is both the problem and the
   machine, and it is the kit's hire bill). The Tower B vibrator (day 17) and the Annex drawing (day 24) are shown
   only on the Issues list, as "the same path, other problems".
2. **Who is the task for?** *Recommended:* Kerala Earthmovers (a task can be for a supplier), so the viewer sees that
   the owner of a fix can be outside the company.
3. **Does the bill get corrected or paid short?** *Recommended:* corrected to 36 hours (the supplier accepts the log);
   paying short with a note is said in "What can go wrong".
4. **The kit's dates** (bill KEE/2027/…, handover July 2027) do not match the story's Nov 2026 to Jan 2027. Not
   changed here; noted for the kit's owner.
