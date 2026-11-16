# A project from start to finish: the guided demo in a sample company

> **Status: approved by Ilan 16 Nov 2026 in session ("Approve the plan"; D-GD1..D-GD6 at the recommended answers). Being built a part at a time: SS-64 started (narration for W1 and the BOQ page).** Asked in session: "a walkthrough … very advanced … BOQ to
> data entry to closing a project … mock data gets entered automatically to show how it will be when data is there,
> and then it removes the data by itself … when each data is entered, it focuses there, highlights there … very easy
> to go through every workflow. The dialogues said by the voice … very mid."
> Decided in session (16 Nov): **a private sandbox company** per person (not their real company, not show-only in the
> browser); **voice: new narration scripts and voice samples to choose from**; **plan first, then build**. Then (16 Nov):
> **"it shouldn't be like a video, there should be areas for participation: interactive learning"** (§4b).
> Builds on [learning-centre-plan.md](learning-centre-plan.md) (tours, walkthroughs, Learn page, voice: SS-40..SS-61).
> Tracker: **SS-64 to SS-72**.

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
| Demo company generator: two weeks of a believable project (2 projects, 4 sites, 15 workers, deliveries, use, attendance, issues; ~480 records, ~7 s), fixed story, made through the real API as the owner | `apps/whatsapp-assistant/src/admin/demo.py` (SA-30, SA-36, WEB-85) | The sample company's history. **Moved** to a shared place (§6), not copied |
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
  client).
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
- **SS-65** shared sample story (move the SA-36 generator to the backend).
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
