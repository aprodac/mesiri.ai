# Continue here: the episodes, then the simulation

> Written 20 Nov 2026 for Ilan, to pick up the work in any later session: **make the episodes first, then test the
> simulation against them.** Read this page, then [SERIES_PLAN.md](SERIES_PLAN.md) (what each episode must teach) and
> [PROJECT_BIBLE.md](PROJECT_BIBLE.md) (the project's facts, papers and rules). To start a session, tell Claude:
> *"Continue from docs/learning/film/CONTINUE_HERE.md, next step N."*

## 1. Where things stand

| Piece | State | Where |
|---|---|---|
| Objective and episode list | Written; 3 open questions (section 6) | `SERIES_PLAN.md` |
| The project's facts (people, two projects, papers, rules) | Agreed (D1 to D5) | `PROJECT_BIBLE.md` |
| Green Villa: estimate, contract, bills | Done (LRN-F4, D2) | `backend/src/mesiri/application/learn/green_villa.py` |
| Lake View: full estimate (38 lines, ₹5,34,72,800), contract with TDS | Done (LRN-F7) | `backend/src/mesiri/application/learn/lake_view.py` |
| The papers a project produces (estimate, contract, quotes, challan, bills, permit, rate card, return note, hire bill, handover) | Done (LRN-F5) | starter kit, `apps/dashboard/public/learn/kit/` (made by `scripts/learn_kit/make_kit.py`) |
| The drawing set, 8 sheets drawn like a real one, 3 planted mistakes | Done (LRN-F6) | `Green Villa - drawing set rev A.pdf` in the kit (drawn by `scripts/learn_kit/gv_drawings.py`) |
| The 62-day story, played through the real API | Done; plays with no failure | `backend/.../learn/sample_plan.py`, `docs/plans/sample-plan.md` |
| The A-to-Z map (the storyboard) | Done (LRN-F3) | `az-map/` (published as "Green Villa A to Z") |
| Simulation voice | ElevenLabs (George) for scenes and walkthroughs (UX-73, UX-76) | `scripts/scene_audio/` |
| Episodes | **Prologue only** (old Episode 1, kept). Old Episode 2 retired (it sold, it did not teach) | `episode-01.json`, `build.mjs`, `film.html` |
| Story batch 1 (month end and the books) | **Parked**: needed before episode 10 only | SERIES_PLAN section 7 |
| Story batches 2 and 3 (buying and machines; planning, tasks, variations) | Not started: needed before episodes 4, 6 and 8 can show every page | SERIES_PLAN section 7 |

## 2. The syllabus: is it right?

The order in SERIES_PLAN section 5 follows a project in time, which is right: the job is won, set up, run day by day,
billed, closed. Three things are missing or weak, and one change fixes each. **Proposed, waiting for Ilan's yes:**

1. **Drawings get their own episode.** A beginner cannot follow an estimate without first knowing what a plan, a
   section and a footing layout are. We now have a real 8-sheet set with three planted mistakes, so episode 1 splits:
   **1. The drawings** (how to read the set; what Drawing check catches and why it costs money if missed) and
   **2. The estimate and the contract** (drawings → quantities → BOQ → rates → contract; Green Villa's terms against
   Lake View's: an advance or none, TDS or none, the whole house or civil works only).
2. **Planning joins setting up.** The schedule and the material plan are how a project manager says "what, when, how
   much"; they were a line in "Setting up". Episode 3 becomes **Setting up and planning**.
3. **The phases of building are told, not only the office.** The 62 days are Green Villa's finishing and Lake View's
   frame. Each site episode opens on a site moment from its phase (foundation and frame at Lake View, finishing at
   Green Villa), so by the end the viewer has seen every phase once. No new episode: a rule for every cold open.

Kept as it is: wages before materials or after does not matter (both start on day 2); problems and machines stay
together until batch 2 shows the machines, then split if it runs long.

### The order, with the change

| # | Episode | Ready to script now? | Needs first |
|---|---|---|---|
| 0 | Prologue: how a construction company works | Done | Decide: keep or redo in the series look |
| 1 | The drawings | **Yes** | — |
| 2 | The estimate and the contract | **Yes** | — |
| 3 | Setting up and planning | **Yes**, except Places and Activity log (batch 3) | — |
| 4 | A day on site | **Yes** | — |
| 5 | Cement runs short | Mostly; quotations, returns, stock count need batch 2 | Batch 2 |
| 6 | Wages week | **Yes**; teams need batch 3 | — |
| 7 | Problems and machines | Problems yes; machines need batch 2, tasks batch 3 | Batches 2, 3 |
| 8 | The subcontractor | **Yes** | — |
| 9 | Billing the client | Bills yes (both projects now bill right); variations, client view need batch 3 | Batch 3 |
| 10 | Is it making money? | **Yes** | — |
| 11 | Month end | No | Batch 1 |
| 12 | Handover, and after | Mostly; retention release after the defects period to add | — |

So: **script and film 1 to 4 now** (they need nothing new), while batches 2, 3 and 1 are built in that order behind
them.

## 3. The plan, step by step

Each step ends with a push and a line in the tracker (`docs/plans/V1_TRACKER.md`, rows LRN-F*).

1. **Ilan decides** the syllabus change (section 2) and the open questions (section 6). Claude writes the answers
   into SERIES_PLAN.
2. **Scripts for episodes 1 to 4**, one file each (`episode-NN.json`, the existing format), written from SERIES_PLAN's
   objective for the episode, every figure read off the sample company. Sent for review before anything is filmed.
3. **Film episodes 1 to 4**, one at a time, each sent for review before the next (section 4 has the how).
4. **Ilan plays the simulation** for the days episodes 1 to 4 cover (section 5), as the owner and then as Ravi, and
   writes down where he got lost. Each item goes to the tracker; the worst are fixed before the next episodes.
5. **Batch 2** (buying and machines), then scripts and films for episodes 5 to 8.
6. **Batch 3** (planning, tasks, variations, client view), then episode 9, and anything in 3, 6 or 7 that waited.
7. **Batch 1** (month end and the books), then episodes 10 to 12.
8. **The whole series watched by someone new**, who answers each episode's three questions (SERIES_PLAN section 8).

## 4. How an episode is made

Per episode, in this order (the commands are in [README.md](README.md)):

1. **Script**: `episode-NN.json`. Scenes follow SERIES_PLAN section 4: cold open, on a real site, who does what and
   when, in Mesiri, what can go wrong, recap with three questions. Plain English, no selling, no claims about other
   products.
2. **Review**: Ilan reads the script. Nothing is filmed before a yes.
3. **Screens**: from a **local copy, never production**, with the **sample company** played to the episode's day (the
   same company the simulation plays). The README's older steps use `scripts/training-video/cost/seed.py`; for the
   series use the sample company instead, so the screens and the simulation agree: open it and pass the days with the
   API (`POST /learn/sandbox`, then `POST /learn/sandbox/next-day`).
4. **Build**: `node docs/learning/film/build.mjs NN` (narration with ElevenLabs, George; frames; sound), check stills
   first with `STILLS=1`.
5. **Check the figures**: every number said is the number on screen that day.
6. **Send** the MP4 and SRT for review (not committed: tens of MB).
7. **What we found**: anything hard, unclear or repeated on screen goes to the tracker.

Local machine for steps 3 and 4: Postgres and Redis running, migrated (`alembic upgrade head`), the API
(`uvicorn main:app` from `apps/whatsapp-assistant/src` with dummy WhatsApp settings), the dashboard built and served
(`npx vite preview --port 5199`). Needs Playwright's Chromium, ffmpeg, and ElevenLabs.

## 5. Testing the simulation after an episode

Play the same days as the episode, in the sample company (Learn Mesiri → Play the sample company):

- **As the owner, then as Ravi.** Do your role's part of each day without asking anyone.
- **Note, for each problem:** the day, the role, the page, what you expected, what happened. Also any line the
  narrator says badly (the walkthroughs and scenes are now ElevenLabs; the ⓘ hints still use the old voice).
- **Check the story holds:** the figures in the episode match the screens; the papers in the starter kit are the ones
  the episode talks about.

## 6. Open questions for Ilan

1. The syllabus change in section 2: yes?
2. Keep the **Prologue** as it is, or redo it in the series' look?
3. **Language**: English narration with English subtitles first, Malayalam later?
4. **Length**: 6 to 10 minutes an episode, or shorter?

## 7. Things to remember

- **One number, one source** (PROJECT_BIBLE section 7): the estimate is the BOQ, the contract value is the estimate's
  total, the drawings and the kit come from `green_villa.py` and `lake_view.py`. Change the data there, never in a
  document by hand, then regenerate (`python3 scripts/learn_kit/make_kit.py`).
- A changed walkthrough step needs its voice recorded again (`node scripts/scene_audio/guide_lines.mjs`, then
  `python3 scripts/scene_audio/make_guide_audio.py`), or it falls back to the old voice.
- The drawings have **three planted mistakes on purpose** (a copied area label, the roof at +660 against +655, the
  upstairs toilet drawn smaller); Drawing check must find exactly those three (a test holds it).
- Business facts in the films are teaching figures: have someone who has run sites check them before customers see
  the films.
