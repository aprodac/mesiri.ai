# Tours, walkthroughs and Learn Mesiri: the rules for every change

> Asked 15 Nov 2026 in session: "make sure the next updates also follow this". Applies to every dashboard change
> by a person or a Claude session: a new page, a changed page, a new feature, a page tour, a workflow, an outcome.
> Design and history: [learning-centre-plan.md](../plans/learning-centre-plan.md) (sections 9 to 11).

## Where things live

| What | File |
|---|---|
| Page tours (one per page, hand-written) and the app tour | `apps/dashboard/src/lib/tours.ts` |
| Workflows, workflow parts, outcomes ("What you get"), role paths | `apps/dashboard/src/lib/walkthroughs.ts` |
| The tour overlay (dim, light, Spark bubble) and page tours' runner | `apps/dashboard/src/components/tour.tsx` |
| The walkthrough engine (across pages, practice, take back, Done card) | `apps/dashboard/src/components/walkthrough.tsx` |
| The Learn page (`/learn`) | `apps/dashboard/src/pages/LearnPage.tsx` |
| What each page does on WhatsApp (examples and their tools) | `apps/dashboard/src/lib/module-map.ts` `whatsapp` |

One engine, one overlay, one definition. Never a second tour system, a page-specific popup tour, or a copy of a
step's words in another place.

## When you build or change a page

1. **Markers, never positions.** Point a step at `data-guide="<page>.<thing>"` on the element (or `guide="..."` on
   `Segmented` / `StatStrip`). Removing or renaming a marked element: fix its steps in the same change. The build
   fails otherwise (`vite.config.ts` `checkTourMarkers`), and that is the point: never silence it.
2. **WhatsApp examples.** A built page has `whatsapp` examples or a `whatsappNone` line in `module-map.ts`; each
   example names real assistant tools (`tests/agent_api/test_module_map_whatsapp.py`).
3. **A page tour** follows the recipe in the plan, section 5.4: 3 to 6 things, plain words, a Spark mood, keyed by the
   page path in `PAGE_TOURS`. If the page first asks for a project, give the tour `startWhen` (its content markers).
   It then appears on the Learn page, in its module card, and in every outcome that names `page-<path>`, by itself:
   add nothing else.
4. **Words per kind of person (UX-22).** The start mode gives each person `GuideWords`: `basics` (new to construction:
   the site itself explained, one idea per step), `steps` (new to tools), `data` (bringing Excel or paper), `expert`
   (used other software: what is different, in a line). A tour step's `for: { basics: {...}, expert: null }` gives its
   words per kind (`null` leaves it out), `only: ['basics']` makes a step for some kinds only; the hello gets
   `introFor`. The page's help (`lib/page-help.ts`) gets `forYou` (one card, two lines at most), `stepsFor`, and per
   part `for` and `find` (its `data-guide` marker: Help lights it up when tapped; the build checks it). A kind with
   nothing written falls back (basics → steps → plain), so leave out what the plain words already say well.
5. **Changed a page enough that people who finished its tour should see it again:** raise the tour's `version`.
6. **A list that a practice saves into:** give each row `data-record-id={record.id}`, so "There it is" can light up
   the exact row (`showNew: true` on that step).

## When you write a workflow (W1..W11)

- **Build it from parts** (`part: true`) and join them with `composed(...)`, so a role path or an outcome can use half
  of it (a site engineer gets W2's asking and delivery, not ordering). Never write the same step twice.
- **Steps go to built pages only** (`page:` must be a built page in `module-map.ts`; the build checks it). A workflow
  step whose element is not on screen (no data yet) is told in the middle of the screen, so write its text to make
  sense without the light: "Every evening each site gets its report", not "Click here".
- **Practice is real data** (decision D-L3). Every practice is one of these two, never neither:
  - **Save, then take back**: `try: { kind: 'whatsapp', say, tools, check }` (or `kind: 'here'` on the real button),
    then a "There it is" step (`showNew: true`), then a step with `takeBack` (the WhatsApp words and their undo
    `tools`, or the dashboard way). Only for records WhatsApp or the dashboard can take back (today: deliveries
    `undo_receipt`, usage `undo_usage`, transfers `undo_transfer`, expenses `undo_expense`, requests
    `cancel_material_request`, orders `cancel_order`). Check the tool exists in `agent_api/tools.py` `ALLOWED`.
  - **Look at the card, then Cancel**: `save: false`. For records that can't be taken back on WhatsApp (a site update,
    attendance, an advance, a payment). Nothing is saved.
- **A practice message must not create something new that stays behind** after the take-back: no supplier, worker,
  team or material name the company may not have ("10 bags cement came", not "... from Malabar"). Cancel practices
  may name people, since nothing is saved.
- **Every practice names its tools** (`tools: [...]`, and `tools` on `takeBack`); the WhatsApp test checks each is a
  real writing tool. Keep `say: '...', tools: [...]` on one line so the test reads it.
- **Only practise what this person can take back.** Some take-backs are limited by role in the backend: correcting a
  delivery, a use or a move is for `ADMIN` and `PROJECT_MANAGER` (`materials/validation.py` `ADJUSTMENT_ROLES`:
  `roles: ADJUSTERS`); taking back an expense is for the owner, an admin or finance, not a project manager
  (`authorization/roles.py` `MONEY_MANAGE_ROLES`: `roles: MONEY_MANAGERS`). For anyone else the engine makes the
  WhatsApp practice card-only (its words become "look at the card, then tap Cancel"), skips the office practice, its
  "There it is" step and its take-back (`canTakeBack`, `practiceSaved`). A new role-limited undo gets its own roles
  list and an entry in the WhatsApp test's `_role_limited_undos`.
- **A walkthrough is offered only to a role that can open at least one of its pages** (`walkFor`), so nobody gets one
  that would run empty.
- **Practice can also be sent from the dashboard**: every WhatsApp practice shows "Send it here", which opens the Tell
  Mesiri panel (`lib/tell-mesiri-events.ts` `openTellMesiri(say)`, the same assistant). Nothing to add per practice;
  the engine steps aside while the panel is open and keeps watching for the saved record.
- **Never practice on a read-only account**: the engine skips practice there; don't work around it.

## When you add or change an outcome ("What you get")

- An outcome is **a title in the role's own words, one line on why it matters, and the walkthroughs it runs**
  (`OUTCOMES` in `walkthroughs.ts`). It writes no steps of its own. Name walkthroughs by id: a workflow or part
  (`site-update`), a page tour (`page-<path with - for />`, e.g. `page-planning-materials`), a module (`module-<key>`).
  The build fails on an id that doesn't exist.
- Title it by the value, not the screen: "Catch a cost overrun before the bill comes", not "BOQ page".
- The role path ("Everything ..., in order") is made from the role's outcomes by itself.
- Open: Project manager and Finance outcomes, and the owner's billing and month-end outcomes (SS-48).

## The guided project and the sample company (SS-67)

- The guided project (`JOURNEY` in `walkthroughs.ts`, id `guided-project`) is **one walkthrough made of chapters**
  (`JOURNEY_CHAPTERS`: a title and the walkthroughs it runs). Writing a chapter's own steps (SS-69..SS-71) means
  writing a walkthrough and putting its id in that chapter's `walks`; the build checks the ids. Never set a step's
  `chapter` by hand: `journey()` does it, and the bubble's chapter list reads it.
- A walkthrough with `sandbox: true` runs **only inside the person's sample company** (`lib/sandbox.ts`): what is saved
  there stays, so it needs no take-back. Never mark one that saves into the real company.
- **"Your turn" in a sandbox chapter** (SS-72): the step's `target` is the real control and `try: { kind: 'here',
  poll: true, check }` waits for the *result*, read from the API, never for a click: `check.has` names what the answer must
  say (`{ 'steps.contract.done': true }`, `{ 'work.length': { lte: 3 } }`; in a list a part names a row by its `key` or
  `id`), `check.rows` the key holding the rows, and `{project}` in `check.path` is the picked project. Already true
  when the step opens: it passes at once. `file:` offers a starter-kit file in the bubble; `pick:` names the project to
  open when the page asks for one ("Open Green Villa from the list"; the list is lit and the bubble sits beside it).
- **A step whose only ask is "open this project"** (`pick`, no `target`, no `try` or `ask`) moves on by itself once the
  project opens (UX-77); a `pick` step with a target stays, since what it shows is on the page the pick opened.
- **While a dialog is open** the bubble steps aside to a corner note that keeps a "Your turn" step's words, so the values
  to copy (a contract's figures) never have to be remembered (UX-77). Write those steps with the figures in `text`.
- **Counts in the bubble are per chapter** in the guided project ("Set up Green Villa · 2 of 5").
- **Day 0 is "Before day 1"**: name a sample-company day with `dayTitle(day)` (`lib/sandbox.ts`), never `Day ${n}`.
- **A quick check** (SS-72): `ask: { answer, right, wrong }`, the answer a `data-guide` marker (the build checks it).
  The bubble docks in the corner with nothing dimmed until they tap; a wrong tap lights the answer.
- **Inside the sample company no page tour opens by itself** (the guided project does the showing); Help's "Show me
  around" still plays one. Starting any walkthrough closes an open tour.
- **"Today" comes from one clock** (SS-74a): a sample company lives on its own date. In the dashboard use `appNow()`
  from `lib/clock.ts`, never a bare `new Date()` (the build fails on one); in the backend and the assistant use
  `clock.today()` / `clock.at(...)` from `mesiri.domains.shared.clock`, never `date.today()` (a test fails on one).
- Inside the sample company every API call goes with its token; code never reads or sends a token itself, it uses
  `api` from `lib/api.ts` (which picks the token). The `/learn/sandbox` routes always go with the person's own token.

## Voice (SS-61)

- A walkthrough speaks each step when its id is in `VOICED` (`lib/walkthroughs.ts`); the build fails on an id that
  doesn't exist. English only for now, read by the narrator voice (`MESIRI_SARVAM__GUIDE_TTS_SPEAKER`, default `shubh`,
  Indian English male).
- **Every voiced step has its own narration** (`say`), written for listening, not the screen's words read out
  (SS-64): one running story (Green Villa, Ravi the site engineer, Malabar the supplier, Suresh's team), spoken to the
  owner, short sentences, what happened and why it matters. A tour's hello (the page's `about`) gets `introSay`. A
  step with no `say` falls back to its title and text (`spokenWords`); "Pick a project" is left short on purpose.
- **The narrator's voice** is a server setting (`MESIRI_SARVAM__GUIDE_TTS_MODEL` and `__GUIDE_TTS_SPEAKER`); the
  Learn page's "Choose the narrator" (owners and admins) plays the voices on offer (`GUIDE_SAMPLES` in
  `domains/dpr/router.py`) reading the same line.
- The audio is made by the server the first time a step is heard (`GET /dpr/live/voice?voice=guide`, Sarvam, MP3) and
  kept; changed words are simply new audio. Nothing to regenerate by hand.
- The player (play / pause, 1x to 2x, mute) lives in the bubble (`components/guide-voice.tsx`, one player for
  walkthroughs and page tours); the choice is kept per browser.
- A page walkthrough's id in `VOICED` (`page-boq`) also gives that page's own tour (first visit, Help's "Show me
  around") its voice. A tour that opens by itself has no click yet, so the browser holds the sound: the player shows
  Play, never an error.
- **The sample company's scenes** (UX-73) have their own lines, made once with ElevenLabs into static files
  (`scripts/scene_audio/make_scene_audio.py` → `public/learn/scenes`, played by `lib/scene-sound.ts`), on or off with
  the guide voice. A new or renamed chapter in `JOURNEY_CHAPTERS`, or a changed line, means running that script again;
  until then its card is simply silent.
- Site words in capitals (BOQ, DPR, GRN, RA, PO, GST, TDS, PDF, CSV) are spelled out for the voice by `spokenWords`, and
  "&" is read "and". A new abbreviation goes in its `SPELLED` list.

## Hints and keys (UX-27, 17 Nov 2026)

- **A hard word or step on a page gets a `<Hint>`** (`components/hint.tsx`): a "?" beside its label; tap or hover to
  read, Listen to hear it in the guide's voice. A glossary word (`term="retention"`, `lib/glossary.ts`) or the page's
  own words (`title` + `text`, an `example` when a number helps). Shown to the people who asked for explanations (new
  to construction, step by step, bringing data). A figure in a strip takes `explain` (`KpiProps`). Its words are not
  counted by the words check (a person opened them). It is drawn over the page, or inside an open dialog, and kept on
  screen: never put it inside a button (a filter tile): put it beside it.
- **Keys in every bubble:** → next, ← back (`TourOverlay`), K or P play / pause, M mute, [ ] speed (`VoicePlayer`), Esc
  stop. Never while typing in a field or with a modifier held (`lib/keys.ts` `typingIn`). A new bubble control gets a
  key in the same place and in the key line under the bubble.
- **Dates are picked, never typed:** `<DatePicker>` (`components/ui/date-picker.tsx`, shadcn: Radix Popover +
  react-day-picker), "YYYY-MM-DD" in and out, today from `appNow()`. The build fails on `<input type="date">`. A
  walkthrough step says "pick", and e2e scripts pick (`play_journey.cjs` `pickDate`).

## Moving people between pages

Any link or navigation inside the app to another page keeps the picked project: `urlWithScope(url, scope)` from
`lib/scope-url.ts` (the sidebar, the walkthrough engine, Help and Learn links use it). A page that first asks for a
project marks its list `data-guide="project.pick"`, so a walkthrough can wait for the pick and say so.

## Before you push a change to any of this

1. `npx tsc -b --noEmit && npx oxlint src/ && npx vite build` in `apps/dashboard` (the build runs every check above).
2. The WhatsApp test, when `say` / `tools` changed:
   `PYTHONPATH=... python -m pytest tests/agent_api/test_module_map_whatsapp.py -q` in `apps/whatsapp-assistant`
   (PYTHONPATH as in the root `CLAUDE.md`).
3. Click it through in a browser against a stub API (Playwright, `require('playwright')`): start the walkthrough with
   `window.dispatchEvent(new CustomEvent('mesiri:walkthrough', { detail: '<id>' }))` and press Next to the end, at
   desktop and phone width, light and dark. In the stub, answer routes the page needs with their real shape and
   **every other route with an error (503)**, not `[]`: an empty list where a page expects an object crashes Today
   and Daily reports, which hides your change. Say in the report what was only checked against the stub.
