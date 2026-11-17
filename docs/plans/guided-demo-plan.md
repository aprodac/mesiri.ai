# A project from start to finish: the guided demo in a sample company

> **Status: approved by Ilan 16 Nov 2026 in session ("Approve the plan"; D-GD1..D-GD6 at the recommended answers). Being built a part at a time: SS-64 started (narration for W1 and the BOQ page).** Asked in session: "a walkthrough … very advanced … BOQ to
> data entry to closing a project … mock data gets entered automatically to show how it will be when data is there,
> and then it removes the data by itself … when each data is entered, it focuses there, highlights there … very easy
> to go through every workflow. The dialogues said by the voice … very mid."
> Decided in session (16 Nov): **a private sandbox company** per person (not their real company, not show-only in the
> browser); **voice: new narration scripts and voice samples to choose from**; **plan first, then build**. Then (16 Nov):
> **"it shouldn't be like a video, there should be areas for participation: interactive learning"** (§4b).
> Builds on [learning-centre-plan.md](learning-centre-plan.md) (tours, walkthroughs, Learn page, voice: SS-40..SS-61).
> Tracker: **SS-64 to SS-72**. SS-67 (switch, banner, chapter list) done 17 Nov: §17.4.

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
- **The site engineer plays on a phone**: a WhatsApp-style phone in the page (Tell Mesiri, framed as a phone, with the
  kit's photos and voice notes to send). That is how most of their real users will use Mesiri.
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
  story); SS-66d (every outbound path checked for a sandbox) is open.

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

