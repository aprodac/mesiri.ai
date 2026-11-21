# Learning Mesiri: the path, and where we are

> Asked 20 Nov 2026 (Ilan): "put up a doc ... so I can continue it, so I can create the episodes first, then the
> simulation ... do we have the correct syllabus and order?" This page is the one place for that: the order to learn
> in, what each step is, what is made, and what to do next. The detail of each episode lives in
> [film/SERIES_PLAN.md](film/SERIES_PLAN.md); the simulation's chapters in `apps/dashboard/src/lib/walkthroughs.ts`
> (`JOURNEY_CHAPTERS`). Update the status columns here as things are made.

## 1. How to learn: watch, then play

**Each step is an episode first, then the same days in the simulation.**

- The **episode** gives the *why*: what happens on a real site, who does what, what goes wrong, and where it lands in
  Mesiri. Six to ten minutes (agreed 20 Nov).
- The **simulation** (the sample company, Green Villa) gives the *doing*: you play one role on the same days and see
  each record land. Clicking without the story teaches buttons, not construction.
- After both, three questions (the episode's "check yourself") and, for the team, a note of anything that was hard or
  unclear on screen: it goes to the tracker.

So the order of **making** them is the same: write and film an episode, then write (or fix) its simulation chapter,
then play-test the pair, then the next.

## 2. The syllabus, in order

The order follows one project from the day it is won to the end of the defects period, which is the order a real
contractor meets each thing. "Sim" is the simulation's chapter (`JOURNEY_CHAPTERS`); "written" means written for
Green Villa's own days with "Your turn" steps Mesiri checks; "general" means it plays the general walkthrough, not yet
Green Villa's story.

| Step | Watch | Then play (role) | You can then... | Episode | Sim chapter |
|---|---|---|---|---|---|
| 0 | **Prologue:** how a construction company works | Open the sample company, look around (Owner) | name the phases, the people, how money flows, the big leaks | done (19 Nov) | ch. 1 "Your sample company": done |
| 1 | **Ep 1: The job is won** (drawings, BOQ, rates, contract, retention, advance) | ch. 2 "Set up Green Villa" (contract, BOQ upload) and ch. 3 "The BOQ" (Owner) | say what is agreed before the first brick and why the BOQ is the yardstick | **built, for review** (9.8 min; script [film/scripts/episode-01.md](film/scripts/episode-01.md)) | **written**, tested and fixed 20 Nov (UX-77) |
| 2 | **Ep 2: Setting up** (sites, team on WhatsApp, items, suppliers, rates, schedule, report time) | Project start's other steps: schedule, team, suppliers (Owner) | list what must exist before day 1, and who sets it up | **built, for review** (9 min; [film/scripts/episode-02.md](film/scripts/episode-02.md)) | **missing**: the sample company comes already set up; needs a short chapter (see 3.2) |
| 3 | **Ep 3: A day on site** | ch. 4 "A day on site" (Ravi, then the Owner's evening report) | follow one site day from Ravi's message to the daily report | **scripted, for review** ([film/scripts/episode-03.md](film/scripts/episode-03.md)) | general |
| 4 | **Ep 4: Cement runs short** (request, quote, order, delivery, short load, stock, supplier bill, payment) | ch. 5 "Material" (Ravi, Anil) and ch. 8 "Money out" (Meera) | walk the material chain across all four people | **built, for review** (8.4 min, recorded from real entries, 21 Nov; [film/scripts/episode-04.md](film/scripts/episode-04.md)) | general |
| 5 | **Ep 5: Wages week** | ch. 6 "Labour and wages" (Ravi, Owner, Meera) | run the weekly labour cycle, advances included | **built, for review** (5.6 min, recorded from real entries, 20 Nov; [film/scripts/episode-05.md](film/scripts/episode-05.md)) | general |
| 6 | **Ep 6: Problems and machines** | none yet | follow a problem from WhatsApp to closed; a machine's day | recorded 21 Nov ([plan](film/EPISODE_06_PLAN.md)); waits for review | **missing** (see 3.3) |
| 7 | **Ep 7: The subcontractor** | ch. 7 "A subcontractor" (Anil, Meera) | pay a subcontractor only for measured work | recorded 21 Nov ([plan](film/EPISODE_07_PLAN.md)); waits for review | general |
| 8 | **Ep 8: Billing the client** | ch. 9 "Billing the client" (Owner) | explain how money comes in, variations included | to script | general |
| 9 | **Ep 9: Is it making money?** ("Where every entry goes") | ch. 10 "Is it making money?" (Owner, Anil) | read a project's health halfway and act on a red line | recorded 21 Nov ([plan](film/EPISODE_09_PLAN.md)); waits for review | general |
| 10 | **Ep 10: Month end** | ch. 11 "Month end" (Meera) | close a month: GST, TDS, cash and bank, the books, Tally | to script; needs story batch 1 | general |
| 11 | **Ep 11: Handover, and after** | none yet (the 62-day plan's last days, played with Next day) | close a project: snags, final bill, handover, defects period, retention | to script | **missing** (see 3.3) |

## 3. Is this the right syllabus and order? The review (20 Nov)

**The order is right.** It is the order a project runs: won, set up, the daily site, material, labour, problems,
subcontract, billing, the health check, month end, handover. Each episode needs only what came before it. Seven things
need fixing so the episodes and the simulation match:

1. **Episodes 1 and 2 are the other way round in the simulation.** The simulation's ch. 2 sets the contract and
   uploads the BOQ, then ch. 3 reads it; the series has "The job is won" (BOQ, contract) before "Setting up". Keep the
   series' order (it is the real one: you win on the BOQ, then set up) and pair Ep 1 with **ch. 2 and ch. 3 together**,
   as in the table. No simulation change.
2. **Ep 2 "Setting up" has nothing to play.** The sample company starts with its sites, team and suppliers already
   made. Add a short chapter after the BOQ: schedule the sections (Project start step 4), check the team and the site
   engineer on WhatsApp (step 6), see suppliers and opening stock (step 7). Look-and-tell, plus one "Your turn" (dates
   on the schedule).
3. **Ep 6 and Ep 11 have no chapter.** Add "Problems and machines" (an issue from WhatsApp to closed, a task, a
   machine's log) and "Handover" (the snag list, the final bill, handover; the defects period told). The 62-day plan
   already has the handover and the final bill (project bible D2).
4. **Chapters 4 to 11 play the general walkthroughs**, written for any company, not Green Villa's days with "Your
   turn" steps Mesiri checks. Each is rewritten for the story when its episode is scripted, the same way ch. 2 and 3
   were (SS-69).
5. **One subject a builder would expect is missing everywhere: quality and safety** (inspections before a pour, cube
   tests, the client's engineer signing off; a safety talk, a near miss). Mesiri has no page for them yet, so no
   episode can show them on screen. Decide: mention them in Ep 3's "On a real site" as work done outside Mesiri, or
   plan the pages first. **Open question for Ilan.**

6. **Every phase of building is seen once.** The 62 days are Green Villa's finishing and Lake View's frame (project
   bible D1), so the foundation and the frame happen only at Lake View. Rule for every cold open: open on a site
   moment from that day's phase (Lake View for foundation and frame, Green Villa for finishing), so by the end the
   viewer has seen each phase. No new episode.
7. **Drawings could become their own episode.** Ep 1 already reads one sheet (A-101 and its copied label). The kit's
   set is now all 8 sheets drawn like a real one (LRN-F6: both plans, elevation, section, footings, columns,
   electrical, plumbing, three planted mistakes). If Ep 1 feels rushed on review, split it into "The drawings" and
   "The estimate and the contract". **Open question for Ilan** (section 6).

"Money out" (the simulation's ch. 8, supplier bills and payments) is not its own episode: it is the end of Ep 4's
cement chain. That is fine; play ch. 5 and ch. 8 after Ep 4.

## 4. What to do next, in order

Tick as done; each item also has a tracker row.

- [ ] **Answer the open questions** (section 6). Answered 20 Nov: length 6 to 10 minutes; keep the Prologue; English first.
- [x] **Ep 1 script**: `film/episode-01.json` (the Prologue is now `episode-00.json`), readable in
      [film/scripts/episode-01.md](film/scripts/episode-01.md). Drafted 20 Nov.
- [x] **Ep 1 built** (20 Nov): the starter kit's drawing, estimate and contract summary on screen, the sample company's
      screens, George's voice; 9.8 minutes. `out/episode-01.mp4` is not committed: shared as a file.
- [ ] **Ep 1 reviewed** (Ilan); changes to the words are re-recorded line by line, then rebuilt.
- [ ] **Film Ep 1**, review it.
- [ ] Play Ep 1 + sim ch. 2 and 3 as someone new (Owner); note what was unclear.
- [x] **Ep 2 script** (20 Nov): [film/scripts/episode-02.md](film/scripts/episode-02.md).
- [ ] Episodes 2 and 3 recorded by the brief [film/RECORDING.md](film/RECORDING.md) (real entries only, LRN-F15).
- [ ] Ep 2 reviewed; then the "Setting up" chapter (3.2) played in the sample company, UX-81 fixed, film, play-test.
- [ ] Ep 3 script, film; rewrite ch. 4 for Green Villa's day; play-test. Then Ep 4 with ch. 5 and 8; Ep 5 with ch. 6.
- [ ] Ep 6 with its new chapter (3.3); Ep 7 with ch. 7; Ep 8 with ch. 9; Ep 9 with ch. 10.
- [ ] Story batch 1 (month end and the books, SERIES_PLAN 7.1), then Ep 10 with ch. 11. Parked until before Ep 10.
- [ ] Ep 11 with its new chapter (3.3).

## 5. Already done, and parked

| What | State |
|---|---|
| Prologue ("How a construction company works") | Done, 19 Nov. Kept |
| The simulation's narrator | ElevenLabs (George) for every voiced walkthrough line, static files (UX-76). Still the old voice: the small ⓘ hints. A changed voiced line needs `scripts/scene_audio/` run again |
| The simulation up to the BOQ | Played and 12 flaws fixed (UX-77): the seeded work in a site's real order, the margin, the guide's words and steps, the phone layout |
| Work done before Mesiri (a project joined midway) | Parked (UX-78): needs a product decision. The guide says Green Villa's earlier months are on paper |
| BOQ units "month", "LS" | Parked (UX-79): needs approval (shared units) |
| Story batches 1 to 3 (pages the 62 days do not use yet) | Batch 1 before Ep 10; batches 2 and 3 before the episodes that need them (SERIES_PLAN 7) |

## 6. Open questions for Ilan

1. ~~Keep the Prologue as it is?~~ Yes, kept (20 Nov).
2. ~~Language?~~ English first (20 Nov).
3. **Quality and safety** (3.5): told as outside Mesiri for now, or pages first?
4. The three new simulation chapters (**Setting up**, **Problems and machines**, **Handover**: 3.2, 3.3): agreed?
5. Split Ep 1 into **The drawings** and **The estimate and the contract** (3.7), only if it feels rushed on review?

## 7. Where things live

| What | Where |
|---|---|
| Episode objectives, structure, every page's episode | [film/SERIES_PLAN.md](film/SERIES_PLAN.md) |
| The agreed story (cast, timeline, decisions D1 to D5) | [film/PROJECT_BIBLE.md](film/PROJECT_BIBLE.md) |
| Episode scripts and the film builder | `film/episode-NN.json`, `film/build.mjs`, `film/README.md` |
| The A-to-Z map (the storyboard) | `film/az-map/` (rebuild with `film/az_map.py`) |
| The simulation's chapters | `apps/dashboard/src/lib/walkthroughs.ts` `JOURNEY_CHAPTERS`; rules in `docs/engineering/LEARN_AND_TOURS.md` |
| The sample company's story | `backend/src/mesiri/application/organizations/sample_story.py` (two weeks), `.../learn/sample_plan.py` (62 days) |
| Play-test script (to the end of the BOQ) | `scripts/learn_kit/e2e/play_journey.cjs` |
