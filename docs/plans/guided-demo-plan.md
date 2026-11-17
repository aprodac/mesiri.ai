# A project from start to finish: the guided demo in a sample company

> **Status: approved by Ilan 16 Nov 2026 in session ("Approve the plan"; D-GD1..D-GD6 at the recommended answers). Being built a part at a time: SS-64 started (narration for W1 and the BOQ page).** Asked in session: "a walkthrough … very advanced … BOQ to
> data entry to closing a project … mock data gets entered automatically to show how it will be when data is there,
> and then it removes the data by itself … when each data is entered, it focuses there, highlights there … very easy
> to go through every workflow. The dialogues said by the voice … very mid."
> Decided in session (16 Nov): **a private sandbox company** per person (not their real company, not show-only in the
> browser); **voice: new narration scripts and voice samples to choose from**; **plan first, then build**. Then (16 Nov):
> **"it shouldn't be like a video, there should be areas for participation: interactive learning"** (§4b).
> Builds on [learning-centre-plan.md](learning-centre-plan.md) (tours, walkthroughs, Learn page, voice: SS-40..SS-61).
> Tracker: **SS-64 to SS-78** (SS-74 split into SS-74a..e, §18). SS-67 (switch, banner, chapter list) done 17 Nov: §17.4.

## 1. Objective

One guided journey through a whole project, **Green Villa**, from the day it is won to the day it is closed, in a
**private sample company**, so every page is shown full, as it looks in real use. **Not a video: the person does the
work.** Each chapter is *watch once, then your turn*: Mesiri shows a thing once (opens the real form, fills it, saves,
lights up the new row and says why it matters), then hands over: "Now you: record today's delivery". The person does it
on the real page, Mesiri sees it land and lights it up, with a hint if they get stuck and "Show me" if they want it done
for them. Nothing touches
the person's own company, and the sample company is removed by itself when they finish. A narrator, written for
listening, tells the story. Chapters can be jumped to, so each workflow is easy to go through on its own.

## 2. What exists (investigation, 16 Nov)

| Piece | Where | Use here |
|---|---|---|
| Walkthrough engine: across pages, highlights, practice, take back, Done card | `components/walkthrough.tsx`, `lib/walkthroughs.ts` | The journey is a walkthrough; it gains a **play** step (Mesiri does the entry) |
| 69 page tours, W1–W11 workflows, outcomes, role paths | `lib/tours.ts`, `lib/walkthroughs.ts` | The chapters reuse their words and markers |
| Light up a saved record | `data-record-id` on rows, `showNew` (SS-50) | Each entry Mesiri makes is lit up the same way |
| Voice: narrator, player, speed, mute | `GET /dpr/live/voice?voice=guide`, `components/guide-voice.tsx` (SS-61) | Narration for every step |
| Demo company generator: two weeks of a believable project (2 projects, 4 sites, 15 workers, deliveries, use, attendance, issues; ~480 records, ~7 s), fixed story, made through the real API as the owner | `backend/src/mesiri/application/organizations/sample_story.py` (moved there by SS-65; the reset stays in `apps/whatsapp-assistant/src/admin/demo.py`) | The sample company's history |
| Create a company; delete a whole company cleanly (blocking links read from the catalogue) | `backend/src/mesiri/application/organizations/create_company.py`, `delete_company.py` (SA-30, SA-31) | Make and remove the sandbox |
| Sign-in token per person and company | `domains/identity/auth_service.py` `create_access_token` | A short-lived token for the sandbox |
| Project stages won → running → handover → defects → closed | Project start page (ST-05) | The last chapter. The **Closeout report** page is planned, not built |

**Gaps found:** nothing keeps a demo company out of WhatsApp sends or scheduled jobs (the team's demo uses team
numbers on purpose); a sandbox needs that gate. The generator lives in the assistant's admin code; the dashboard's API
(backend) needs it too.

## 3. The journey: chapters

Each chapter is its own walkthrough as well (run alone from Learn), and the journey is them in order. Minutes are
estimates at 1x.

| # | Chapter | What Mesiri does on screen (all in the sample company) | Pages |
|---|---|---|---|
| 0 | Your sample company | Makes it (a few seconds), explains it is private and goes away by itself | Learn → Today |
| 1 | The project is won | Moves Green Villa to Won; sets the contract dates, client, retention, advance | Project start |
| 2 | The BOQ from your Excel | Uploads a sample estimate; the lines and sections appear; fills materials per unit | BOQ, Project start |
| 3 | The schedule | Sections become bars; Quick plan; a late activity and what it pushes | Schedule |
| 4 | The team | Adds the site engineer; shows what they send | Team, Project |
| 5 | A day on site | The engineer's evening message (people, work, an issue); Today fills; the daily report | Tell Mesiri, Today, Daily reports |
| 6 | Material | Request → quotes → order → delivery with a rejected bag → use → stock running low | Requests, Quotations, Orders, GRN, Materials, Material plan |
| 7 | Labour and wages | Attendance → muster → wage sheet → an advance | Labour, Wages, Advances |
| 8 | A subcontractor | Work order → measurement → bill → TDS | Subcontract |
| 9 | Money out | An expense with a bill photo; a supplier bill and its payment | Expenses, Suppliers |
| 10 | Billing the client | RA bill on the letterhead → client payment → receivables | RA bills, Receivables |
| 11 | Is it making money? | Green / red, budget vs actual, materials vs BOQ | Cost control |
| 12 | Month end | Accounts, close the month, Tally export | Accounts, Months, Tally |
| 13 | Handover and closing | Stage to handover, defects, closed; what is left owed | Project start (Closeout report when built) |

About 20–25 minutes in all. A chapter list in the bubble lets the person jump to any chapter.

## 4. How Mesiri "enters" data: the play step

A new step kind in the one engine (no second tour system):

```ts
play: {
  // One of these, in order of preference:
  api?: { method: 'POST' | 'PATCH'; path: string; body: object }   // the same route the page's own button calls
  form?: { open: string; fill: Record<string, string>; save: string } // markers: open the real dialog, type, save
  upload?: { open: string; file: string }                            // a sample file from the dashboard's assets
  tell?: string                                                      // a message through Tell Mesiri (the assistant)
  show: string                                                       // the marker or record to light up after
}
```

- **`api`** for most entries: exact, fast, no model in the way. The page refreshes and the new row (`data-record-id`) is
  lit up with "There it is".
- **`form`** where seeing the form filled is the point (the first delivery, the RA bill): the engine opens the real
  dialog, types into each field (visible typing at the chosen speed), presses Save. Fields get `data-guide` markers;
  the build check covers them.
- **`tell`** for one or two moments that show the assistant (chapter 5): it costs a model call and a few seconds, so
  only where it is the point.
- Every play step is idempotent in the sandbox (a chapter run twice adds nothing twice) and can be skipped.

## 4b. Participation: your turn, checks, and small questions

The person learns by doing. Every chapter has at least one **Your turn** and most have a **Quick check**.

- **Your turn** (`task` step): a goal in plain words ("Order 200 bags of cement from Malabar for Main block"), the page
  it happens on, and how Mesiri knows it is done (`check`: a list route and what the new record must have, e.g. a
  purchase order for cement, 200 bags). The engine lets clicks through, watches for the record (the existing `check` of
  practice steps, SS-42/SS-50), then says "Done, there it is" and lights the row. Because this is the sample company,
  **every save is kept** (no take-back): their work becomes the next step's starting point (the order they placed is the
  one that arrives in the next task).
  - **Hints** after ~30 s without progress, pointing at the next thing to press (the field or button marker); a second
    hint later; **"Show me"** plays it for them (the `play` step of §4); **"Skip"** always there.
  - **Two ways to do it**, as in real life: on the page, or "send it here" as a WhatsApp-style message through Tell
    Mesiri (the same assistant, inside the sandbox). WhatsApp from their own phone goes to their real company, so it is
    not used inside the sample company.
  - **Wrong but saved** (200 bags of sand instead of cement): Mesiri says what it sees and how to fix it on that page
    (correct the order), so fixing a mistake is learned too.
- **Quick check** (`ask` step): a question answered on the page itself, not a form: "Which BOQ line is losing money?
  Tap it" (the answer is a marker or a record); "How many bags of cement are left at Main block?" (choices). Right:
  a short why; wrong: the light moves to the answer and the narrator explains. No scores to pass; a chapter shows "3 of
  4 done by you" so people see what they did themselves.
- **Choices that change the story** (a few): "The supplier sent 150 of 200 bags. Accept the 150, or reject the
  delivery?" Either path works, and the next steps follow what they chose.
- **Pace:** the person moves on when they are ready; the narrator never runs ahead of the task. Speed 1x–2x and mute
  as now.
- **Learn page:** each chapter shows "Watch" and "Your turns" counts and what they have done; the journey can be
  resumed where they left off (the sandbox lives up to 24 h; after that, a new one starts at their chapter, with the
  earlier chapters' records made for them).

Per chapter, the mix is about one watch, two your-turns and one quick check. Chapter 5 (a day on site) for example:
watch the engineer's evening message turn into Today; **your turn:** send the next day's update through Tell Mesiri;
**quick check:** "Which site has not reported today? Tap it"; **your turn:** send the daily report.

## 5. The sandbox company

- **Start:** `POST /learn/sandbox` (signed-in person). The server makes a company "Sample: Green Villa Builders" with a
  sandbox user who has the person's name and the Owner role and **no phone number**, fills two weeks of history with
  the shared generator, and returns a **sandbox token** (2 hours, marks itself as sandbox, names the real company).
- **In the dashboard:** the real token is kept; the API client uses the sandbox token while the journey runs. A banner
  on every page: "Sample company: nothing here is real · Leave". Leaving (or finishing) switches back.
- **End:** `DELETE /learn/sandbox` on leave or finish; a nightly job removes sandboxes older than 24 hours, through
  `delete_company`.
- **Kept apart** (`organizations.sandbox_of`, additive migration): no WhatsApp send for a sandbox company (one gate in
  the assistant's outbound sender, plus no phone numbers at all); scheduled jobs skip it (daily report sends, reminders,
  tips, setup questions); left out of the control panel's counts, the trials funnel and billing. At most one live
  sandbox per person, a few per company a day.
- **Security (needs approval, D-GD1):** the sandbox token opens only the sandbox company; nothing in it reaches the real
  company; it can't be refreshed into a real token; the sandbox user can't sign in any other way.

## 6. Reuse, not copies

- The SA-36 generator moves from `apps/whatsapp-assistant/src/admin/demo.py` to
  `backend/src/mesiri/application/organizations/sample_story.py`; the demo reset and the sandbox both call it. Its story
  is extended for the chapters (a won project with no BOQ yet, so chapter 2 has something to do; a subcontractor; a
  client). **Done (SS-65):** moved; a subcontractor added (Joy Tiling Works); Green Villa already has no estimate.
  Lake View already has its client; Green Villa's client is set by chapter 1 itself. Anything else a chapter starts
  from is added with that chapter (SS-69..SS-71).
- The chapters' words start from the page tours and workflows; the narration (§7) is written once per step.

## 7. The voice

- **Narration scripts** (`say` on each step): written for listening, one running story (Green Villa, the site engineer
  Ravi, the supplier Malabar), short sentences, what happened and why it matters to the owner. The screen keeps its
  short text. Rewritten too for the four walkthroughs that already speak and the BOQ page.
- **Voice samples:** a "Choose the narrator" panel for the Mesiri team (control panel) plays the same line in three
  Sarvam narration voices (`bulbul:v4-flash`: `shubh_en_narration`, `kalpit_en_edtech`, `sarang_en_narration`) and the
  current `shubh`; the chosen one is set on the server (`guide_tts_model`, `guide_tts_speaker`), no release.
- Words spelled for the ear (BOQ → "B O Q") stay in `spokenWords`.

## 8. Work by layer

| Layer | Work |
|---|---|
| Database | Additive migration: `organizations.sandbox_of` (uuid, nullable, the real company), `organizations.sandbox_expires_at` |
| API | `POST /learn/sandbox`, `DELETE /learn/sandbox`; sandbox claim in the token; guide voice model setting and the samples route |
| Backend | Shared generator (moved); sandbox make / remove; nightly cleanup; skips in schedulers and counts |
| Assistant | Outbound gate for sandbox companies; Tell Mesiri works in a sandbox like any company |
| Dashboard | Sandbox switch and banner; `play`, `task` and `ask` steps in the engine (hints, Show me, checks, choices); field markers; chapter list in the bubble; progress per chapter on Learn; the 14 chapters; narration scripts |
| Docs | This plan, the tour rules (`LEARN_AND_TOURS.md`: how to write a play step and a narration line), tracker |

## 9. Risks

| Risk | How it is handled |
|---|---|
| A sandbox sends a WhatsApp message to a real person | No phone numbers in it at all, and a gate in the one outbound sender; a test sends from a sandbox and expects nothing |
| A sandbox shows up in real reports, the control panel or billing | `sandbox_of` filters, tested per place |
| A sandbox is left behind | Removed on leave and finish; nightly cleanup after 24 h; `delete_company` is tested on full companies |
| The sandbox token reaches the real company | It names only the sandbox company; the same scope checks as any token; a test asks the real company with it and expects 403 |
| A chapter breaks when a page changes | Play steps use the routes and markers the build already checks; a test runs every chapter's `api` steps against a real sandbox |
| Making the sandbox is slow | ~7 s today; made while chapter 0 is told; if slow, a ready-made template copied instead |
| Cost | Narration ~10,000 characters once (~₹15); Tell Mesiri only at 1–2 steps; the sandbox is database rows only |

## 10. Testing

- Backend (real Postgres, as in INF-33): make a sandbox, run every chapter's `api` steps, remove it, nothing left; a
  sandbox sends nothing; schedulers and counts skip it; the sandbox token can't reach the real company.
- Dashboard: tsc, oxlint, vite build (markers, play steps, chapter ids); the whole journey in Playwright at desktop and
  phone, light and dark, against a real local API and database this time, not only a stub.
- Voice: the samples route returns one line per voice; scripts checked for spelled words.
- Live, after deploy: run chapters 0–2 on production and confirm the sandbox is gone afterwards.

## 11. Rollback

Each part is its own commit. The migration only adds two nullable columns. Turning the journey off is one switch on the
Learn page; sandboxes left are removed by the nightly job or by `delete_company`.

## 12. Labour isolation

Chapter 7 runs labour and wages **inside the sandbox only**, through the existing routes. Labour and Attendance are
normal modules (3 Nov). No change to Payroll or Workforce code.

## 13. Decisions needed

| # | Decision | Recommended |
|---|---|---|
| D-GD1 | The sandbox (a second company and a sandbox sign-in token for a person) | **Approve as in §5** (security-sensitive) |
| D-GD2 | Who can start the journey | **Owner, admin, project manager** (a site engineer gets W1 and the site parts) |
| D-GD3 | How long a sandbox lives | **Until they leave or finish; at most 24 h** |
| D-GD4 | The assistant (Tell Mesiri) inside the journey | **At 1–2 moments only** (chapter 5) |
| D-GD5 | The last chapter before the Closeout report exists | **Use the stage track; add the report chapter when the page is built** |
| D-GD6 | The narrator voice | **Pick from the samples panel** after it is deployed |

## 14. Build order and tracker

| ID | Item | Size |
|---|---|---|
| SS-64 | Narration scripts for the voiced walkthroughs and the BOQ page; voice samples panel; guide voice model setting | S |
| SS-65 | Shared sample story (move the SA-36 generator; extend for the chapters) | S |
| SS-66 | Sandbox company: migration, make / remove, token, nightly cleanup, outbound gate, scheduler and count skips | M |
| SS-67 | Dashboard: sandbox switch and banner; chapter list in the bubble | S |
| SS-68 | Engine: the `play` step (`api`, `form`, `upload`, `tell`), field markers, build check | M |
| SS-72 | Engine: participation: `task` (your turn: goal, check, hints, Show me, mistakes explained), `ask` (quick check by tapping the page or a choice), story choices; "done by you" per chapter and resume on Learn | M |
| SS-69 | Chapters 0–5 (won, BOQ, schedule, team, a day on site) with narration | M |
| SS-70 | Chapters 6–10 (material, labour, subcontract, money, billing) with narration | L |
| SS-71 | Chapters 11–13 (cost, month end, handover and closing) with narration | M |

**Who is doing what: the tracker rows are the claims.** Before starting an item, set its row to `in-progress` with your
session in Owner, pull, and push that one change first; if the row is already claimed, take another. Mark it `done` with
the commit hash when pushed.

**Can start now, in parallel (no dependency between them):**
- **SS-64** narration and voice samples: claimed by session_014PnnwM (16 Nov).
- **SS-65** shared sample story: **done** (`fe3d4b18`, session_016qPwVK): `application/organizations/sample_story.py`.
- **SS-68** the `play` step in the engine (can be built and tested on the existing walkthroughs with `api` steps against
  the current company in a test, before the sandbox exists).

**Then:** SS-66 sandbox (after SS-65; D-GD1 approved 16 Nov) → SS-67 switch and banner → SS-72 participation (after
SS-68) → SS-69, SS-70, SS-71 chapters (after SS-67, SS-68, SS-72; the three chapter items can then run in parallel).

## 15. Estimate (Claude Opus 5.5 usage, as the learning-centre plan counts it)

| Part | Tokens processed | At API prices |
|---|---|---|
| SS-64 voice | ~15–25 M | ~$10–15 |
| SS-65..SS-68, SS-72 sandbox and engine | ~80–135 M | ~$45–80 |
| SS-69..SS-71 chapters (with your-turns and checks) | ~110–180 M | ~$65–110 |
| **Total** | **~205–340 M** | **~$120–205** |

Sarvam: narration made once, ~₹15–25. No new running costs beyond database rows for sandboxes while they exist.

## 16. The playground as a game (ideation, 17 Nov 2026)

> Asked in session (17 Nov): *"a playground company or projects everyone can use and test, in Learn Mesiri … we have to
> get some materials too, some BOQ or documents or whatever we need for the full simulation … like a role playing game,
> from one end to the other, they learn by doing."* Builds on §1–§15 (approved 16 Nov); nothing there is replaced.
> Status: **approved by Ilan 17 Nov 2026 in session: D-PG1..D-PG4 at the recommended answers** (one per person, a
> "Next day" button, the project's own numbers as the score, real roles). D-PG5 and D-PG6 taken at the recommended
> answers (they upload the kit themselves; team assignments later).

### 16.1 What §1–§15 already give, and what is new

| Already planned (SS-64..SS-72) | New in this section |
|---|---|
| A private sample company per person, removed after (SS-66) | **Play again** and **pick up where you left**: the playground is theirs until they reset it (D-PG1) |
| 14 chapters, won → closed, watch then *your turn*, quick checks, story choices (SS-69..SS-72) | Chapters become **missions on a game clock**: the site's days move forward, things happen, the project's numbers react (16.3, 16.4) |
| Mesiri enters data (`play`), the person does the next one (`task`) | **The starter kit**: the real paperwork a project runs on, as files they download and bring in themselves (16.2) |
| One person, as the owner | **Play the roles**: owner, project manager, site engineer, storekeeper, accountant, each with that role's real screens and permissions (16.5) |
| "Done by you" counts | **The report card**: the project's own numbers at handover (margin, days late, cash, stock-outs), and a certificate per role path (16.6) |
| Words per kind of person (UX-22) | The whole game in their words: someone **new to construction** learns the site as well as the software (16.7) |

### 16.2 The starter kit: the materials a real project runs on

A folder of files, made by us, all for **Green Villa** (one story, the names the narration already uses: Ravi the site
engineer, Malabar Cements, Suresh's team, Joy Tiling Works). Each file is used by a mission, and each has a **deliberate
catch** the person finds by using Mesiri, because that is what Mesiri is for.

| File | Brought in on | The catch they find |
|---|---|---|
| `Green Villa - estimate.xlsx`: ~45 lines in 6 sections (earthwork, concrete, masonry, plaster, flooring, painting) | BOQ (upload) | 3 lines have no budget rate ("Lines priced"); one line is priced at a loss (red margin) |
| `Green Villa - contract summary.pdf`: client, dates, 5% retention, 10% advance | Project start | The dates they type set the schedule's finish |
| `GF plan.pdf`, `S-101 structural.pdf` | Documents, Drawing check | A room is labelled bigger than it is drawn |
| `Materials and suppliers.xlsx`, `Workers.xlsx` | Bring your data | Two names for the same cement ("OPC 53" and "Cement OPC-53") to merge |
| 3 cement quotations (PDF) | Quotations | The cheapest per bag is dearest with transport |
| Delivery challan (photo) | Deliveries (GRN) | 190 bags on the challan, 200 on the order |
| Supplier bill (PDF) | Supplier bills | ₹10 a bag above the order: the 3-way match stops it |
| Site photos (slab, a wall crack), 2 voice notes (English, Malayalam) | Tell Mesiri (the phone in the page) | The crack becomes an issue; the voice note becomes a day's update |
| Subcontractor's measurement sheet | Subcontract bills | Measured more than the BOQ quantity |

- Made by a script in the repo (`scripts/learn_kit/`, fixed content, no randomness) and checked in under the dashboard's
  public files, so the files are versioned with the missions that use them. A test opens each file and checks the
  numbers each mission expects.
- On the Learn page: **"Download the starter kit"** (one zip) and, in each mission, the one file it needs.
- **They bring the file in themselves** (D-PG5); "Show me" does it for them. A person on a phone gets "Use the sample
  file" instead of a download.

### 16.3 The game clock: the site's days move forward

> **Superseded in detail by §18** (17 Nov): your own timeline, back and forth, skip ahead, the other roles played by the cast.

The world moves only when the person moves it: **"Next day"** in the playground's banner (and at the end of a mission).

- Each next day the server plays the site's day from the shared story (`sample_story.py`, extended): attendance, work
  on BOQ lines, use of material, a delivery that was ordered, the weather. Made through the real API like everything
  else, so every page fills the way it would in real life: progress bars move, stock goes down, the daily report is made.
- **What the person did changes the next day**: the cement they ordered arrives; if they didn't order it, it runs out
  and work stops (Today shows the site idle, the schedule slips).
- About 60 game days from won to handover, played in ~10 missions; days with nothing to learn are skipped ("A week
  passes: 6 days of work, here is what changed").

### 16.4 Events: things go wrong, as on a real site

Each event is a mission's turning point, a choice with real effects on the numbers:

| Event | The choice | What it changes |
|---|---|---|
| Malabar sends 190 of 200 bags | Accept 190 / reject the lorry | Stock, the bill, the next day's work |
| Two days of rain | Move the slab / pay overtime later | Schedule finish, labour cost |
| Cement runs short on slab day | Emergency buy at a higher rate / wait | Margin on the slab line, days late |
| Suresh's team asks for an advance | Give it / not | Cash, the wage sheet |
| A BOQ line goes red | Find why on Green / red | Teaches cost control |
| The client pays the RA bill late | Chase it / wait | Cash in hand |

No wrong answers that end the game: every path works, the numbers show the cost of it, and the narrator says what an
experienced owner would have done and why.

### 16.5 Play the roles

Each mission says who you are and when: *"You are Ravi, the site engineer. It's 6 pm at Green Villa."*

- The playground has one user per role (owner, project manager, site engineer, storekeeper, accountant), no phone
  numbers. A mission switches the dashboard to that user, so the person sees **that role's real screens and
  permissions** (a site engineer sees no rupees; the storekeeper sees stock, not margins).
- ~~**The site engineer plays on a phone**: a WhatsApp-style phone in the page.~~ **Dropped 17 Nov 2026:** customers told
  us WhatsApp alone will not work, so Mesiri gets a mobile app too ([DECISIONS.md](../DECISIONS.md)). How the site
  engineer plays waits for the app's shape (SS-76b); until then Ravi plays on the dashboard like the other roles.
- Role paths become **careers**: *Site engineer → Storekeeper → Project manager → Owner*, each a set of missions.

### 16.6 The score is the project, not points

- The **project health** strip in the banner: margin, days late, cash in hand, stock-outs: Mesiri's own numbers, so the
  game teaches what the real numbers mean.
- At handover, the **report card** is the real period / closeout report of their Green Villa, next to "how an
  experienced owner did" (the same story played well). No points, no leaderboard (D-PG3).
- Finishing a career gives a **certificate** ("Mesiri: Site engineer"), shown on Learn. An owner sees which of their
  team has finished which (a later step, D-PG6): a way to train new staff without the owner's time.

### 16.7 For each kind of person (UX-22)

The missions' narration and hints use the person's `GuideWords`: `basics` hears what a slab, a cum, a challan and
retention are as they meet them (the game doubles as construction for beginners); `expert` gets the short version
and can skip the watch parts; `data` starts with the kit's Excel files.

### 16.8 Work, on top of §8

| ID | Item | Size | Depends on |
|---|---|---|---|
| SS-73 | Starter kit: the generator script, the files, the test of their numbers, downloads on Learn and per mission | M | SS-65 |
| SS-74 | Game clock: `POST /learn/sandbox/next-day` (the story's next day through the real API, following what the person did), "a week passes" | M | SS-66 |
| SS-75 | Events and choices with effects (a table of events in the story, each a `choice` step) | M | SS-72, SS-74 |
| SS-76 | Play the roles: a playground user per role, switch per mission; the phone frame for Tell Mesiri | M | SS-66 (security: same token rules as D-GD1) |
| SS-77 | Project health strip, the report card, careers and certificates on Learn | S | SS-74 |
| SS-78 | (Later) Owner assigns missions to the team and sees progress | S | SS-77 |

The critical path is unchanged and first: **SS-66 sandbox → SS-67 switch and banner**, with SS-68 (play step, claimed)
and SS-72 (participation). SS-73 (the kit) can start now in parallel: it only needs the story.

Estimate on top of §15: ~90–150 M tokens (~$55–90); Sarvam narration for the new missions ~₹10–15.

### 16.9 Decisions

| # | Decision | Recommended |
|---|---|---|
| D-PG1 | One shared playground for everyone, or one per person | **One per person**, kept until they reset it (a shared one breaks: someone else's order changes your story) |
| D-PG2 | How time moves | **"Next day" button** (and "a week passes"), never real time |
| D-PG3 | Scoring | **The project's own numbers and a report card**; no points or leaderboard |
| D-PG4 | Play other roles with their real permissions | **Yes**, playground users per role (security-sensitive, same rules as D-GD1) |
| D-PG5 | Kit files: they upload them, or Mesiri does | **They do; "Show me" does it for them** |
| D-PG6 | Owner assigns missions to the team | **Later (SS-78)**, after the careers exist |

## 17. SS-66 design: the sandbox company, as being built (17 Nov 2026)

> Written before the code so others can build against it in parallel. Investigated 17 Nov; where this differs from §5,
> this section is the current design. Who is doing what: the **tracker rows SS-66a..SS-66d, SS-67** (claim before you start).

### 17.1 Decisions taken while designing (within D-GD1 and D-PG1..D-PG4, approved)

| # | Decision | Why |
|---|---|---|
| A | A fifth company status **`sandbox`** (`lifecycle.SANDBOX`), not operational | Every scheduled job, automatic report, reminder, tip, setup question and the WhatsApp sender's company check already ask `is_operational` / `operational_sql`; a non-operational status keeps the sandbox out of all of them in one place, instead of a skip in each. The trial guard only blocks `expired`, so the sandbox can still be written to |
| B | **No phone numbers anywhere** in a sandbox (people, workers, suppliers, report recipients) | The outbound sender is keyed by phone, not company: no number, nothing can be sent |
| C | Columns `organizations.sandbox_of`, `sandbox_user_id`, `sandbox_expires_at`, **no foreign keys** (migration 0556) | Deleting a real company or person is never blocked by its sandbox; orphans go at the next cleanup |
| D | **One per person** (unique index on `sandbox_user_id`), kept until reset, removed after **30 days unopened** (D-PG1; replaces §5's 24 h) | Opening it moves `sandbox_expires_at` on |
| E | Cleanup **on the next `POST /learn/sandbox`** (a few at a time), not a new nightly job | No new scheduler to run and watch; expired or orphaned sandboxes go through `delete_company` |
| F | **Everyone** in a company may start one (the ask on 17 Nov: "everyone can use"); not platform admins | A private sandbox costs rows only |
| G | The **people** in it: the person as owner (`ADMIN`), plus Anil (project manager), Ravi (site engineer), Meera (finance), on both projects, emails `@sandbox.mesiri.invalid`, random passwords (no login) | Real roles for SS-76 (D-PG4) from day one |
| H | The **history** comes from `sample_story.seed` through the real API, in-process (ASGI), as the sandbox owner, in a fresh context (no request transaction or tenant carried in) | Every record passes the same checks as the dashboard; no copy of business rules |
| I | Kept out of the control panel's lists, overview, trials funnel and billing by **one filter** in `companies_overview` (`sandbox_of IS NULL`), which all of them read | One place |

### 17.2 The API (for SS-67 and the chapters to build against)

All under the person's **real** token, except where it says sandbox token. A sandbox token calling `/learn/sandbox*`
gets 403 (no sandbox inside a sandbox).

| Route | Does | Returns |
|---|---|---|
| `GET /learn/sandbox` | Is there one for me? | `{ "exists": bool, "organization_id"?, "name"?, "expires_at"?, "created_at"? }` |
| `POST /learn/sandbox` body `{ "role"?: "ADMIN" \| "PROJECT_MANAGER" \| "SITE_ENGINEER" \| "FINANCE" }` (default `ADMIN`) | Opens mine, making it first if there is none (~7–10 s the first time); moves its expiry on; cleans up a few expired ones | `{ "token", "expires_at", "organization_id", "name", "role", "user_name", "created": bool, "seeded"?: {kind: count}, "failed"?: [..] }` |
| `DELETE /learn/sandbox` | Removes mine now ("Reset" = DELETE then POST) | 204 |

- **The sandbox token** is a normal access token for the sandbox user (`sub`, `org` = the sandbox, `role`, `name`,
  `org_name`) plus `"sandbox": "<real company id>"`, valid 8 hours. Every existing route accepts it unchanged and
  can only reach the sandbox company (the user belongs to it; `resolve_from_jwt` checks that). It can't be refreshed or
  turned into a real token; the sandbox users can't log in.
- **The dashboard (SS-67)** keeps the real token, puts the sandbox token in the API client while the person is in the
  sandbox, shows the banner ("Sample company: nothing here is real · Leave · Reset"), and switches back on Leave.
  `GET /auth/me` with the sandbox token returns the sandbox company and `status: "sandbox"`.

### 17.3 Files

| Layer | File |
|---|---|
| Migration | `backend/migrations/versions/0556_organizations_sandbox.py` |
| Status | `domains/organizations/lifecycle.py` (`SANDBOX`, `"sandbox"` signup source), `models/organization.py` |
| Service | `application/learn/sandbox.py`: make, open (token), remove, cleanup, the in-process API client for the seed |
| Routes | `domains/learn/sandbox_router.py`, mounted in `apps/whatsapp-assistant/src/runtime/lifecycle.py` |
| Lists | `application/organizations/companies_overview.py` (one filter) |
| Tests | unit (rules, token claims, refusals) + integration on real Postgres (make, seed, the token can't reach the real company, nothing operational sees it, remove leaves nothing) |

### 17.4 Built (SS-66a..c, 17 Nov 2026)

- Built as designed above. Run end to end against the full app and a fresh Postgres (all migrations to 0556, and 0556
  and 0555 down and up again): **the first open takes ~13 s and adds ~1,430 rows** (two projects, four sites, 15 workers,
  7 suppliers, 2 weeks of attendance, work, deliveries, use, expenses, an estimate with lines counted, an RA bill, issues;
  none failed); opening again is instant and gives any role's token.
- Checked by hand on the running app: the sandbox token sees only Green Villa and Lake View; the real company's project
  and BOQ give **404** to it, reading and writing; `/learn/sandbox` refuses it (**403**); `/auth/me` says
  `status: "sandbox"`; the real token never sees the sandbox; sandbox people can't log in (**401**); the sandbox is the
  only company `operational_sql` leaves out; removing it leaves **no rows** except its one audit-log line (kept by design).
- Tests: `backend/tests/integration/test_learn_sandbox_postgres.py` (6, real Postgres, the seed replaced by a recorder),
  `backend/tests/unit/test_lifecycle_sandbox_ss66.py`.
- **Found on the way, not changed here:** a token whose person was deleted still gets `200 []` from `GET /projects`
  (the assistant's projects router doesn't re-check the person); nothing leaks (the company is gone), but it is the
  same class as any revoked person's token and worth its own item.
- **Not covered:** the seed in CI (it needs the whole app; covered by the run above and by the demo reset using the same
  story).

### 17.5 SS-67 in the dashboard, as built (17 Nov 2026)

| Piece | File | What it does |
|---|---|---|
| Sandbox state | `apps/dashboard/src/lib/sandbox.ts` | The sandbox token, its expiry, name and role, in **sessionStorage** (one tab is in the sample, any other tab is the real company); tied to the person's own token, so another login in the tab drops it. `enterSandbox(role, start?)`, `leaveSandbox()`, `removeSandbox()`, `resetSandbox()`, `useSandboxInfo()` |
| API client | `lib/api.ts` | Every call goes with the sandbox token while in the sample, except `/learn/sandbox*` (always the person's own token). A 401 on a call sent with the sandbox token switches back to the person's own company and never signs them out (several refused together: one switch) |
| Switching | `lib/sandbox.ts` | Entering, leaving and starting over load the app fresh (`location.assign`), so no page data, project pick or sign-in from one company shows under the other. The project pick is remembered per token, so it is not carried across either |
| Banner | `components/sandbox-banner.tsx` (in `app-layout.tsx`, every page) | "Sample company: nothing here is real", the company and role, **Guided project · Start over · Leave** |
| Learn | `components/learn/sandbox-card.tsx` | Go in as Owner / Project manager (Anil) / Site engineer (Ravi) / Accounts (Meera); **Start the guided project** (owner), **Just look around** / **Open my sample company**, **Remove it**; says why when a session ended by itself. Hidden for platform admins and until the server has the routes (404/405) |
| Guided project | `lib/walkthroughs.ts` `JOURNEY_CHAPTERS`, `JOURNEY` (`guided-project`, `sandbox: true`, voiced) | Chapter 0 (two hello steps) then one chapter per §3 row, each running the workflow that covers it **until SS-69..SS-71 write the chapter's own steps** (replace that chapter's `walks`). Chapters 1-4 are one chapter for now (`new-project`); 13 (handover) is left out until it has steps. The engine refuses a `sandbox` walkthrough outside the sample |
| Chapter list | `components/walkthrough.tsx` `ChapterList` | "Chapter n of N" and a picker in the bubble; jumping goes to that chapter's first step. Chapters come from each step's `chapter` (set by `journey()`), so steps left out for a kind of person (UX-22) never break it |

Checked against a stub API in Playwright (desktop light, phone dark): Learn card → POST with the real token → the app
reloads inside, banner and chapter 1 shown → jump to Material → Leave → Open again → the sandbox token refused → back on
Learn in the real company, still signed in, with the note. The client was checked against SS-66's route and models
(`domains/learn/sandbox_router.py`: path, roles, `expires_at` = the token's) but **not clicked through against the real
API and database**; that is the live check after deploy.


### 17.6 SS-66d: nothing in a sandbox reaches a real phone (17 Nov 2026)

Every way a WhatsApp message can leave, checked:

| Way out | Reaches a sandbox? |
|---|---|
| Scheduled and automatic sends (daily reports, reminders, tips, setup questions, stock alerts, notification checks, draft reminders) | **No**: each picks companies with `operational_sql`; `sandbox` is not operational |
| The notification queue (period report sends, approvals and anything queued for a person) | **No, now**: `list_pending` leaves sandbox companies out (their rows go with the sandbox) |
| A send started while handling a dashboard request (a material request moving, Tell Mesiri sending a document, an invite) | **No, now**: the request's sandbox token marks it (`domains/shared/sandbox_gate.py`), and the one sender (`WhatsAppSender._send`) drops anything sent under the mark, tasks started from the request included |
| A reply to an incoming message | **No**: incoming messages find their company by the sender's number, and nobody in a sandbox can have one |
| A number typed into the sandbox (Team page, any people route, now or later) | **Refused, now**: migration 0557's trigger on `users`; the API answers 422 "People in the sample company can't have a WhatsApp number…" (`http/db_errors.py`, the shared handler) |

Phones on suppliers, clients, workers and report recipients can be typed in a sandbox (the learning needs those forms),
but nothing sends to them: every way out above is closed for a sandbox.

**For the chapters (SS-69+):** "Send the daily report" in a sandbox queues it and it is never sent; the chapter should
say so ("in the sample company nothing is sent; in yours it goes to the owner on WhatsApp") rather than wait for it.

Tests: `test_learn_sandbox_postgres.py` (+2: the trigger on insert and update with a real company's guard; the queue),
`apps/whatsapp-assistant/tests/unit/test_sandbox_send_gate_ss66d.py` (a sandbox request's sends and its task's sends
blocked, a real one's sent, the mark ends with the request), `test_lifecycle_sandbox_ss66.py` (the 422 wording). Checked
on the running app: adding a teammate with a number in the sandbox gets the 422; without a number, 200; in the real
company with a number, 200.

## 18. The planned simulation: your own timeline, everyone else plays their part (SS-74, 17 Nov 2026)

> Asked in session (17 Nov): *"each user has their own actually and they can go back and forth in it, and go few days
> after and all too. And if I am an accountant I should get a simulated data entered when I do each skip to days …
> every other role is doing their part automatically when we go next day."* Then: *"we need to have simulation
> planned … then it's good and easy."* Replaces §16.3's line on how time moves (D-PG2's "Next day" stays); builds on
> §17 (one sandbox per person, any role).

### 18.1 What the person can do with time

| Control (in the sample company's banner) | What happens |
|---|---|
| **Next day** | The plan's next day is played: everyone except you does their entries (18.3); yours are waiting for you (18.4) |
| **Skip ahead** 2 / 3 / 7 days | Several plan days at once, yours done for you too, except on the day you land on. "While you were away" says what happened |
| **Go back** to an earlier day | The sample company is put back as it was at the start of that day (a save point, 18.5); later days are gone, and Next day plays them again |
| **Look back** (no change) | Every page's date picker shows an earlier day; nothing is undone |

Each person's timeline is their own (one sample company each, D-PG1).

### 18.2 The plan: the whole simulation, written in advance (D-GC1)

One fixed script, `application/learn/sample_plan.py`, from day 0 (the seeded weeks' last day, a Saturday, a pay day)
to Green Villa's handover (day 62 as built). For each day
it lists **every role's entries**: who (owner, Anil, Ravi, Meera), what (one of a small set of kinds: attendance, work
done, material used, a request, an order, a delivery, a supplier bill, a payment, a wage sheet, an expense, an issue, a
BOQ line counted, a running bill …), and its numbers. It is generated once from the story's tables (`sample_story.py`:
the sites, the work stages, the use a day, the suppliers, the rates) and checked in, so anyone can read it as a table
and see exactly what happens on day 23.

- **Fixed, so it is easy and the same for everyone**: the same plan for every sample company, no randomness. The two
  seeded weeks are days −13..0; the plan starts from exactly what they leave (stock, the seeded orders still to come),
  worked out by running the seed itself against a recorder, never a copy of its rules. SS-74a sets the sample's date so
  that day 0 is a Saturday.
- **A test holds it true**: every entry's kind maps to a real API route; played start to finish against a real
  database, every entry saves, stock never goes below zero, every order is delivered and billed, every bill is paid.
- **Following the person** is only where the plan says so (`needs:`): a delivery needs its order, a bill needs its
  delivery, a payment needs its bill. If the person (playing that role) never did the entry it needs, it waits and is
  played the day after the need is met; the site is shown short of it meanwhile (cement not ordered: cement runs out,
  that site's work and use wait). Events with choices (SS-75) are plan days with two branches.

### 18.3 The cast: who does what, played as their own user

Each planned entry is played **as its role's sandbox user** (Anil, Ravi, Meera, the owner), with their token, in
process, through the same routes the dashboard calls: every record shows who entered it and passes that role's own
permissions.

| Role | Their entries in the plan |
|---|---|
| Site engineer (Ravi) | Attendance; work done; material used; deliveries received against the order; weather and tomorrow's plan; issues; requests when stock is low |
| Project manager (Anil) | Orders for the requests; work counted on BOQ lines; issues closed; subcontract measurements |
| Accounts (Meera) | Supplier bills matched to deliveries; payments; expenses; wage sheet and pay day; advances; client payments |
| Owner | Approvals; the running bill sent at month end |

### 18.4 Your part: the plan's entries for your role are your to-do

On the day you land on, the plan's entries for **your role** are not played: they are your list for the day, exactly
as written (*"Malabar's bill TB/2611, ₹43,000, for the delivery of the 3rd"*). Each opens the page it is done on, and is
ticked when a matching record exists (the plan says what matches: the kind and its key numbers). Not doing it is
allowed: the entries that need it wait (18.2). These are the raw material for the missions (SS-69..SS-71, SS-75).

### 18.5 The sample company's own date (D-GC2) and save points

A sample company has **its own today** (`organizations.sandbox_today`): the plan day's date. One `today()` for the
backend gives the real date for every real company and that date for a sandbox, in place of the 43 `date.today()`,
3 SQL `CURRENT_DATE` and 9 assistant reads; `GET /auth/me` returns it and the dashboard's own "today" reads it. So pay
weeks, months, days late, stock left in days and bill ageing are all true inside the game.

*Found 17 Nov, before any code:* the first idea, moving the sample's dates back a day at a time, breaks everything on
the calendar: pay weeks end on a fixed weekday (`pay.week_of`), accounting periods are calendar months
(`accounting_periods`), so a one-day move makes overlapping weeks and months that are not months. Rejected.

**Save points:** at the start of every day the sample company's rows are saved (per table, as JSON, `sandbox_days`;
a few hundred kB a day). Go back = put those rows back and set the sandbox's date to that day; nothing else changes.
The last 30 are kept.

### 18.6 API

All with the person's **real** token, like the rest of `/learn/sandbox` (a sandbox token gets 403).

| Route | Does | Returns |
|---|---|---|
| `GET /learn/sandbox/clock` | Where am I? | `{ "day", "date", "can_go_back_to": [{ "day", "date" }], "for_you": [{ "id", "what", "page", "done" }] }` |
| `POST /learn/sandbox/next-day` body `{ "days": 1..7 }` | Plan days played (18.1) | `{ "day", "date", "summary": [{ "who", "what", "count" }], "for_you": [...], "waiting": [...], "failed": [...] }` |
| `POST /learn/sandbox/go-back` body `{ "day": n }` | Back to that save point | `{ "day", "date" }` |

### 18.7 Decisions

| # | Decision | Taken |
|---|---|---|
| D-GC1 | How the simulation is made | **Planned in advance**: one fixed day-by-day plan of every role's entries (asked 17 Nov: "simulation planned") |
| D-GC2 | How days pass | **The sample company has its own date**; one `today()` that knows it. **Approved 17 Nov in session** (a shared component; two of the reads are in Workforce). The sandbox stays a separate simulation: real companies keep the real date |
| D-GC3 | Your role's entries when skipping days | **Done for you on the days skipped, waiting for you on the day you land** (recommended) |
| D-GC4 | Going back | **A save point a day, the last 30**; days after it are discarded (recommended) |
| D-GC5 | Skip size | **Up to 7 days at a time** (recommended: one request under ~30 s) |

Security: no new kind of token or permission. The cast's tokens are §17 sandbox tokens, made in process for the
sandbox's own users and never returned; save points and the clock refuse any company without `sandbox_of`.

### 18.8 Work (replaces SS-74's one row)

| ID | Item | Size | Depends on |
|---|---|---|---|
| SS-74a | The sample company's own date: `organizations.sandbox_today` (additive), one `today()` for backend, assistant and dashboard, `GET /auth/me` returns it | M | SS-66; **approval D-GC2** |
| SS-74b | The plan: `sample_plan.py`, every role's entries day by day to handover, generated from the story and checked in; its test (every entry a real route, stock never negative, everything ordered is delivered, billed, paid) | L | SS-65 |
| SS-74c | The player: Next day / Skip ahead play the plan as the cast's users; your role's entries become "for you" with their checks; `needs:` waits; `POST next-day`, `GET clock` | M | SS-74a, SS-74b |
| SS-74d | Save points and Go back: `sandbox_days`, save each day, restore, keep 30; `POST go-back`; real-Postgres test (save, change, go back, identical rows) | M | SS-74a |
| SS-74e | Dashboard: the clock in the sample company's banner (day n, Next day, Skip ahead, Go back), "While you were away", "For you today" | S | §18.6 (routes stubbed until SS-74c) |

Order: SS-74b (started 17 Nov) and SS-74a (D-GC2 approved 17 Nov) in parallel; then
SS-74c and SS-74d; SS-74e any time against §18.6.

## 19. SS-73: the starter kit (17 Nov 2026)

`scripts/learn_kit/make_kit.py` makes the files into `apps/dashboard/public/learn/kit/` (fixed: the same bytes every
run), with `kit.json` (what each is, where it goes, what to look for) and one zip. The Learn page's **Starter kit**
card (`components/learn/starter-kit.tsx`) reads `kit.json`: download all or one, "Goes into" links to the page, and
"What to look for" folded (finding it is the point).

| File | Brought in on | What Mesiri shows (checked by importing into a sandbox on Postgres) |
|---|---|---|
| Green Villa - estimate.xlsx: 34 lines in 9 sections, materials per unit, ₹82,06,050 | BOQ: Import from Excel | "Lines priced": 3 with no budget (the tiling and granite, for the subcontractor); the staircase in red (a loss); 6 lines with materials; 21 of the 24 site works suggest their line, the 3 Plastering ones ask which (three plastering lines) |
| Green Villa - materials and suppliers.xlsx: 7 items, 4 suppliers, opening stock, minimums | Bring your data: materials | Cement, Malabar and Joy Tiling "already in Mesiri, left as they are"; no problems |
| Green Villa - contract summary.pdf: client, value (the estimate's total), dates, 10% advance, 5% retention, 12-month defects | Project start: the contract step | Typed in by the "won" chapter |

Every work the sample site reports for Green Villa (`sample_story.DEMO_WORK`, Main block and Annex) is a line with the
same unit, so its work counts on the BOQ. No phone numbers or GSTINs anywhere.

Test: `backend/tests/unit/test_learn_kit_ss73.py` (the files are what the script makes, read through Mesiri's own
importers; every site work has its line; norms name real lines and catalogue materials; the contract says the total).

### 19.1 Second part (17 Nov 2026)

Each catch checked first against what Mesiri does today (three planned catches changed to ones it really shows):

| File | Brought in on | What Mesiri shows | Checked by |
|---|---|---|---|
| Ground floor plan A-101 (A3, 1:100, cm, title block) | Drawing check | Exactly one finding: "BEDROOM-2 is drawn 360 x 360 cm (140 sq ft) but labelled 163 sq ft. 163 sq ft is BEDROOM-1's area: the label looks copied." | `read_pdf` on the file |
| Three quotes (Malabar, Kerala Steels, Sri Hardwares: 300 bags cement, 2,000 kg steel) | Quotations | Cheapest cement (Malabar) is not cheapest total (Kerala); each item from its cheapest beats both: the compare's lowest per item / lowest total. *Changed from "dearest with transport": Mesiri has no transport cost* | the numbers |
| Delivery challan (190 of 200 bags) | Orders: Material came | 10 bags still to come on the order | the file's text |
| Malabar's bill (Rs 410 a bag; ordered at the quote's Rs 400) | Suppliers: match the bill | "rate ₹410 on the bill, ₹400 on site" | `matching.flags` |
| Joy Tiling measurement sheet (the plan's six tiled rooms, 81.94 sqm) and bill (92 sqm) | Subcontract: measurement, bill | "billed 10.06 sqm more than measured" | `subcontracts.rules.check_bill`. *Changed from "more than the BOQ": the check is bill against measurement* |

**Found and fixed on the way (Drawing check, all drawings):** in Arial-like fonts the PDF reader split words at a narrow
character, so "1100 x 450" read as "1" "100" and "ROOM-11" as "ROOM-1" "1": a room with a 1 in its size or name was
misread on real drawings too. The gap between characters is now measured between their full widths, not their ink
(`domains/drawings/pdf_text.py`); test `test_drawing_narrow_glyphs.py` (four fonts, and two words placed apart stay apart).
Not checked: real CAD exports beyond the existing tests.

**Held (SS-73b, needs a decision):** the two voice notes (Tell Mesiri records from the microphone but can't take an
audio file) and the site photos (Tell Mesiri takes no photo; made-up photos look fake: real ones we may use are better).

### 18.9 SS-74b as built (17 Nov 2026)

- `backend/src/mesiri/application/learn/sample_plan.py`: `plan()` gives 1,477 entries over 62 days (Green Villa handed
  over on day 62; Lake View keeps building). Kinds (`KINDS`): the site's day (conditions, attendance, work, use,
  expense), issue, request, delivery (Ravi); order, BOQ count, issue closed, work order, measurement (Anil); supplier
  bill, supplier payment, subcontract bill and payment, advance, wage payment, client receipt (Meera); wage approval,
  running bill, project stage (owner). Each names its route(s) for the player.
- The site's work: `STAGES` per site (Main block: conduits to snag list; Annex: plinth to painting; Lake View: three
  floor cycles each). Use is capped at the stock on site, so a short site does less work that day (day 2..4 at Main
  block: 2.2 bags of cement left by the seed, as the story intends). Requests when stock and what is coming won't last
  the supplier's lead time and 3 days; orders the next working day; lorries after the lead time; bills 2 working days
  after; suppliers paid on Saturdays for bills a week old; wages approved and paid each Saturday (and the seeded weeks'
  last week on day 2); Joy Tiling Works' work order, weekly measurement, bill and payment; Lake View's running bill on
  days 23 and 51, paid 12 days later.
- The readable plan: [sample-plan.md](sample-plan.md) (generated; `python -m mesiri.application.learn.sample_plan`).
- Test: `backend/tests/unit/test_sample_plan_ss74b.py` (14): the same every time; from what the seed leaves; ids and
  needs; roles; no Sunday work; stock never below zero; asked → ordered → delivered → billed → paid; wages every week;
  handover; the subcontract; real issue types; the story's names; every kind's route is a real route; the readable
  copy up to date.
- **Not covered here:** playing it against a real database (SS-74c: every entry through the API as its role's user,
  and that each role may make its entries). Payloads are names and numbers; the player finds each sample's ids.

### 18.10 SS-74a as built (17 Nov 2026)

- **The date lives** on the company (`organizations.sandbox_today`, migration 0558, additive) and **travels** in the
  sample company's token (`today`, beside `sandbox`). A new sample starts on the latest Saturday (`sandbox.day_zero`:
  the plan's day 0); one made before 0558 carries on from the day its records were made. Real days passing never move
  it; SS-74c (Next day) and SS-74d (Go back) move it and return a new token.
- **One clock, backend and assistant:** `domains/shared/clock.py`. `today()`, `now(zone)`, `at(moment)`, `override()`.
  Bound per request from the token by the sandbox gate middleware (every request) and by both `get_current_user`s; a
  real token clears it. With nothing bound it is exactly the old behaviour (`date.today()`), and **nothing is read from
  the database for a real company**. `company_today()` (146 callers) asks it first. The 45 code-level `date.today()`
  in 35 files, two SQL `CURRENT_DATE`s (wages' 30 days, documents expiring) and the v3 assistant's "now" (the day it
  tells the model, memory, receipts, the working day) go through it; classic, WhatsApp groups and scripts don't (a
  sample company never reaches them).
- **One clock, dashboard:** `src/lib/clock.ts` `appNow()`: the sample's date with the real time of day while this tab
  is in one, else `new Date()`. Every bare `new Date()` (98 in 69 files) now calls it. `GET /auth/me` returns `today`
  for a sample company.
- **Guards (the class, not the instance):** the dashboard build fails on a bare `new Date()` outside `lib/clock.ts`;
  `tests/unit/test_one_clock_ss74a.py` fails on a code-level `date.today()` anywhere in the backend or the assistant
  (scripts excepted).
- **Checked:** 7 clock tests; the sandbox's real-Postgres tests (9, incl. day 0, the token's date, an old sample);
  through the real assistant app in-process (real today Tue 17 Nov): the sample opened on Sat 14 Nov with 551 records,
  none failed; `/auth/me` says `today: 2026-11-14`; opening a wage sheet with no date gives the game's week (8..14 Nov).
- **Not covered:** two `CURRENT_DATE`s left on purpose (inbound WhatsApp counts, timeline entries since midnight:
  real-time events a sample company has none of); timestamps (`created_at`) stay real; a second tab opened before a
  Next day in another keeps its older date until it reloads its token (SS-74e).


## 20. SS-76: play the roles, part 1 (17 Nov 2026)

- **"Be: …" in the sample company's banner** (`components/sandbox-banner.tsx`, `lib/sandbox.ts` `switchSandboxRole`):
  Owner (you), Project manager (Anil), Site engineer (Ravi), Accounts (Meera), each with one line on what they see. It
  opens the sample company again as that person (`POST /learn/sandbox` with the role) and stays on the page when that
  role may open it, else Today (Ravi on BOQ lands on Today: a site engineer sees no rupees).
- **Found while testing on the real app:** going into the sample company asked "How would you like to start?" again,
  because its people are new users with no answer. Now every person in the sample company takes the person's own
  answer each time it is opened (`open_sandbox`), so the help explains things their way and nobody is asked twice; a
  change in their own company follows them in. Test: `test_learn_sandbox_postgres.py` (+1).
- Checked in a browser against the real app and a real database (not a stub): Learn → "Just look around" → the
  sample company as Owner → BOQ → Be: Site engineer → Ravi, on Today.
- **Not built (17 Nov decision, a mobile app is coming):** the WhatsApp-style phone for the site engineer. The mission
  switching the role by itself is SS-76b (needs the simulation script, SS-74).

### 18.11 SS-74c as built (17 Nov 2026)

- **`application/learn/sandbox_player.py`**: `next_day(days 1..7, role)` plays the plan forward as each role's sandbox
  user (a token per role, dated to the game day), through the app's own routes in process; `clock(role)` says the day
  and what is waiting for the person. Routes (the person's real token; a sandbox token gets 403):
  `GET /learn/sandbox/clock?role=`, `POST /learn/sandbox/next-day {days, role}` → the new day, a **new sandbox token**
  (its date moved), the summary (who did what), "for you", what is waiting, what failed.
- **It follows the company, not a script of ids:** an order takes the site's open request, a lorry an open order line
  for that site and material, a bill that supplier's unbilled deliveries, a payment its unpaid bills (a week old; a
  subcontract bill only what may be paid now, the route's own `payable_caps`), the client's receipt the bill that was
  sent. Not there → the entry waits and is tried again each day. So what the person did (or didn't) is what happens.
- **Your entries:** on the day you land on, your role's entries are left for you; on days skipped over they are made
  for you (D-GC3). One is ticked when what it asks for is there: records of its kind saved by your user since that
  day began, at its place (site, project or supplier), counted as the kind needs (a wage payment per sheet); four by
  their outcome (handed over, issue closed, the day's weather and plan, no work left off its BOQ line). Left undone,
  it stays yours (overdue) and what needs it waits.
- **Found while playing it on a real database, fixed in the player:** an order from a request takes its items from
  the request (send the request and the plan's quantity, not lines); the duplicate-order check (confirmed, as an office
  would); new work goes on its BOQ line by itself (BOQ-01), so Anil counts only what is left; the sample had no money
  account (the owner opens "Federal Bank current account" the first time days pass); retention on Joy's bills.
- **New table** `sandbox_played` (migration 0559, additive; row-level security; cascades with the company):
  what became of each entry, and when each day began. `organizations.sandbox_day0`: the plan's day 0 for that sample
  (a sample made before it must start over to play days).
- **Checked, real database, the whole app in process** (`tests/integration/test_sandbox_player_postgres.py`, 3, ~100 s):
  all 62 days played to handover, **nothing failed, nothing left waiting**, 1,476 entries by the cast and the
  owner's handover left for the person; as Accounts, Saturday leaves her wages and bills, paying Green Villa's
  wages ticks only that one; as the site engineer, his missing requests hold Anil's orders. Over HTTP: open, clock,
  next-day, the new token's date in `/auth/me`, a sandbox token refused (403), an unknown role (422). Unit: every kind
  has a page and a way to be ticked.
- **Not covered:** ticking counts records since the entry's day began, so one record late in a week could tick an
  older overdue entry of the same kind and place as well as that day's; the dashboard side (Next day in the banner,
  the new token swapped in, "for you" with links) is SS-74e; save points and Go back are SS-74d.

### 18.12 SS-74e as built (17 Nov 2026)

- **In the sample company's banner** (`components/sandbox-clock.tsx`, inside `sandbox-banner.tsx`): "Day 7 of 62 · Sat,
  21 Nov", **Next day**, **Skip ahead** (2 days, 3 days, a week), **For you (n)** (`· n late` when some are from
  earlier days): the person's part grouped by the page it is done on, each group a link. After days pass, once:
  **"Days 1 to 7 passed"**: who did what (Anil: orders placed 10 ...), what waits for something not done yet, and
  anything that could not be saved. Sunday says "A quiet day: nobody works on Sunday."
- `lib/sandbox.ts`: `useSandboxClock()`, `passDays(n)` (takes the new token, whose date moved, and loads the page again
  so every page reads the new day), `catchUp()` (a tab left behind by another opens itself again on the current date,
  once per date). A sample made before days could pass says to start over.
- For everyone in a sample company (17 Nov in session: no customers use it yet, so nothing is held back); the near
  term mission is the guided project up to the BOQ, so the chapters after it (SS-69 part 2 onwards) wait for the other
  pages' UI/UX upgrade.
- **Checked in a browser against the real app and a real database** (not a stub): Learn → Just look around → day 0 →
  a week → day 7, Sat 21 Nov in the top bar and on Today, "Days 1 to 7 passed", For you (2): the owner's two wage
  approvals under Wages → Next day → day 8, "2 late", and Meera's pay waiting on them; phone width, dark.
- Found on the way: Today's own "Next day" arrow (looking at a day) and this one (making a day pass) shared a name for
  screen readers; this one is now "Move the sample company on to the next day".


## 21. Up to the BOQ, playable (SS-69 part 1, SS-72 first pieces, 17 Nov 2026)

Asked 17 Nov: *"our focus right now is till BOQ, the role play thing working."* Chapters 2 and 3 of the guided project
(`gv-setup`, `gv-boq` in `lib/walkthroughs.ts`) replace the generic "new project" walkthrough there:

| Chapter | Step | The person does | Mesiri knows it is done when |
|---|---|---|---|
| Set up Green Villa | The office's turn | Opens Green Villa (the list is lit) | the page shows its steps |
| | Your turn: the dates | Types 2 Nov 2026 and 31 Jul 2027 from the contract summary, Save dates | `GET /projects/{project}/start`: `steps.dates.done` |
| | Your turn: the contract | "Set the client and contract", copies the summary | `steps.contract.done` |
| | Your turn: the BOQ | Downloads the estimate from the bubble, uploads it, Import | `steps.boq.done` |
| The BOQ | Four numbers | Reads them (3 lines unpriced, so no margin yet) | — |
| | Quick check | Taps the line that loses money (the staircase) | the tap is on `boq.loss` |
| | Your turn: count the site's work | "Add all suggested" (21 of 24) | `GET …/boq/work?unlinked`: at most 3 left |
| | Your turn: which plastering? | Picks 4.1 Plastering for one, Add to line | at most 2 left |

Each step is worded per kind of person (the beginner hears what a BOQ, retention and an advance are; the expert gets one
line). Story: Green Villa has run two weeks without the office side (no dates, contract or BOQ): the owner sets it up.

**The engine pieces (SS-72):** a check on what the API says (`has`, `rows`, `{project}`), a your-turn with no dialog
(`poll`), a kit file in the bubble (`file`), "open this project" (`pick`), and the quick check (`ask`). Rules in
`docs/engineering/LEARN_AND_TOURS.md`.

**Found and fixed while playing it on the real app:**
- The app tour ("Hi, I'm Mesiri") opened on top of the guided project inside the sample company (its people have seen no
  tour): page tours no longer open by themselves there, and any walkthrough starting closes an open tour.
- The guided project started in the plain words: it was fixed before the person's preferences had loaded after the
  sample company opened. A walkthrough now waits for them (at most 4 s).
- The bubble covered the project list it asked the person to pick from, and ran off the bottom of the screen once it
  carried the voice player, chapter list and a file: it now lights the list while waiting for the pick, and is placed
  by its measured height (scrolls inside if it ever needs to).
- The kit's contract summary gave the advance as "10%"; the contract form asks rupees and a recovery %: it now says
  ₹8,20,605 and 10% a bill, signed 20 Oct, work from 2 Nov 2026 to 31 Jul 2027.

**Checked:** played start to finish in a browser against the real app and a real database, as someone new to
construction (the beginner's words): every your-turn saved through the real dialogs, each moved on by itself, the quick
check wrong then right. Not checked: phone width and dark mode for these two chapters; other kinds of person only through
their words in the code.

**Next (SS-69 part 2):** the schedule and the team; then "A day on site" in the sample company's own words (today it
reuses the generic W1, which speaks of practice and Cancel).

## 22. Handover (17 Nov 2026, session_016qPwVK, end of session)

**Goal set by Ilan (17 Nov):** the role-play (guided project in the sample company) working end to end, **up to the BOQ
first**. Tell Mesiri file/photo input is **not** a focus now. A mobile app is coming (DECISIONS.md): don't build
WhatsApp-only assumptions.

**Done and on main:** sandbox company per person (SS-66, §17), nothing in it reaches a phone (SS-66d), starter kit
(SS-73, §19), role switch in the banner (SS-76, §20), chapters "Set up Green Villa" and "The BOQ" playable with the
your-turn engine pieces (SS-69 part 1, SS-72 first pieces, §21). Another session owns the game clock (SS-74a..e).

**Next, in order (claim the tracker row first):**
1. **SS-69 part 2, finish "up to the BOQ":** the two remaining Project start steps for Green Villa, *Schedule* (Quick
   plan from the BOQ's sections) and *Site team* (put Ravi on Green Villa; no phone numbers in a sandbox, migration 0557
   refuses them, so the step must add an existing sandbox person to the project, not invite a number). Write them as a
   chapter `gv-schedule-team` after `gv-boq` in `JOURNEY_CHAPTERS`, same pattern as `GV_SETUP` (`try: { kind: 'here',
   poll: true, check: START_CHECK('schedule') }`, words per kind of person, `say` for the voice).
2. **"A day on site" for the sample company:** today the chapter reuses the generic W1 (`site-to-report`), which talks
   about practice and Cancel and is wrong inside a sandbox (nothing needs taking back; nothing is sent: §17.6 says the
   chapter must say "in the sample company nothing is sent"). Write `gv-day` the same way. Coordinate with SS-74 (the
   game clock plays the cast's entries).
3. **Check what was not checked:** chapters 2–3 at phone width and in dark mode; the other kinds of person
   (guided, bring_data, switching) through the e2e script (`scripts/learn_kit/e2e/`, README there).
4. **SS-72 rest:** hints after ~30 s without progress, story choices, "done by you" per chapter and resume on Learn.
   "Show me" needs SS-68 (claimed 16 Nov by session_014PnnwM, no code landed: ask before taking it).

**How to verify a chapter:** `scripts/learn_kit/e2e/README.md` (real app + real Postgres + Playwright). Rules for
writing steps: `docs/engineering/LEARN_AND_TOURS.md` (the sandbox chapter bullets). Dashboard checks:
`npx tsc -b --noEmit && npx oxlint src/ && npx vite build` (the build checks every marker a step points at).

**Open questions for Ilan (not blocking the above):** SS-73b voice notes/photos (on hold, not a focus); warm dark mode
(mock-up first or build); UX-22 per-person Help/tours for the remaining ~40 pages (batches in story order).
