# Recording an episode: the brief

> Written 20 Nov 2026 so another session can record episodes 2 and 3 (and later ones) without this conversation.
> The scripts are agreed to teach **the software**: every entry is shown being made for real, on WhatsApp (through
> Tell Mesiri, the same assistant) or on the website, never drawn. Read [README.md](README.md) for the tools and
> [../LEARNING_PATH.md](../LEARNING_PATH.md) for where each episode sits.

## The local copy (learned 20 Nov)

- **Never run the backend's integration or contract tests against the database you film from**: they empty its
  tables. Use a separate database for them.
- **Files:** `MESIRI_OBJECT_STORAGE__PROVIDER=local` with a `LOCAL_ROOT`, `PUBLIC_BASE_URL=http://localhost:8000` and
  a `SIGNING_SECRET`, or uploaded drawings have no picture and Track on site cannot read them.
- A sample company's token lasts 8 hours; take a fresh one (`POST /learn/sandbox`) after a long break.

## The rules for every recording

1. **Real entries only.** A chat scene with `capture` is sent for real and Mesiri's real reply card is what the film
   shows. A scene of kind `steps` is done for real on the website, a picture per frame. Nothing is mocked.
2. **The words follow the screen.** If the real reply, page or figure differs from the script, change the narration
   (in `episode-NN.json`), run `python3 script_md.py NN`, and say so in the report. Never change the screen to fit
   the words.
3. **A local copy, never production.** Local Postgres and Redis, the app as production runs it, the dashboard built
   and served (README, "Screens and papers", steps 1 to 2). The sample company is made with the person's own login
   and played with "Next day".
4. **The owner is Ramesh Nair** (project bible D3): name the local login Ramesh Nair *before* opening the sample
   company, or take a fresh sample token after renaming (the name is inside the token).
5. **English narration**, George (ElevenLabs), 6 to 10 minutes an episode (all agreed 20 Nov).
6. **Do not rebuild episode 1** unless asked (Ilan, 20 Nov). Its sidebar shows the old login name; that waits.
7. `.cache` and `out` are not committed. Send the finished `out/episode-NN.mp4` and `.srt` to the person as files.

## Recording real replies: record.cjs (built 20 Nov, LRN-F15)

```bash
node docs/learning/film/record.cjs 03 "$(cat scripts/training-video/cost/admin.token)" http://localhost:5199
ONLY=rain node docs/learning/film/record.cjs 03 <own token>   # one scene again; its days are still played from 0
```

- Starts the person's sample company afresh (it stops if the copy does not open on day 0), then goes day by day:
  a `steps` scene with `as` (a role) and `day` is filmed first by `shoot.cjs` (its `steps-NN.cjs`) inside the sample
  company as that role; then **Go back** puts the day back, and the chat scenes of that day are sent for real as
  `capture.role` through `POST /assistant/messages` (the same handler as WhatsApp). `capture.choose` names the answers
  to tap when Mesiri asks first (which metal, which cash box), then `capture.tap` (Save). Each reply and tap goes to
  `.cache/shots/<scene>.chat.json`; `build.mjs` draws them in place of the script's guess (`REAL=0` builds the guess).
- **The assistant needs a model key** on the local API: `MESIRI_GEMINI__API_KEY` and `MESIRI_GEMINI__MODEL=gemini-3.5-
  flash-lite` (production's). One recording of episode 3 is about 8 model calls of some 39,000 tokens each. The key
  used on 20 Nov hit its monthly spending cap after three runs: check the budget first.
- **Pages inside the sample company** are opened the way the dashboard does (`sample-session.cjs`): the person's own
  token, and the sample's session (its token and own date) in the tab, so every "today" is the sample's day. For
  screens: `SAMPLE=<the next-day answer as JSON> node shoot.cjs NN <own token> ...` (`SKIP_STEPS=1` for screens only).
- **Light mode** is the default for every picture (asked 20 Nov); `THEME=dark` for the old look.
- **Never run the integration tests against the filming database**: they create and clean up companies and end the
  sample company's sessions mid-recording ("Sign in again", 20 Nov). Use a separate database for tests.
- Mesiri answers Ravi in his own mix (Malayalam in English letters): the narration says so, never translates it away.

## Episode 2, "Setting up": recorded 20 Nov

Built with `steps-02.cjs` from the sample company after the guided project's chapters 2 and 3 (reset first: Documents,
tracking, the import and the quick plan are saved). Kept below as the record of what it needed.

- [ ] **UX-81 fixed**: Rates must show M sand's rise (₹1,650 → ₹1,750); today it says "same".
- [ ] The sample company on **day 0** ("Before day 1"), as the owner, after the guided project's chapters 2 and 3
      (`scripts/learn_kit/e2e/play_journey.cjs`).
- [ ] The `steps` scenes are the setting-up itself, done for real on the website in this order, each filmed as it is
      done: Drawing check (the kit's drawing set) → Documents (the set kept) → Places (from it) → Bring your data
      (the kit's materials workbook) → Schedule (Quick plan) → Team (Ravi's number typed, then Cancel: a sample
      company never takes a WhatsApp number).
- [ ] The paper scenes are already shot (`shoot.cjs 02`, `ONLY=<shot>`): A-201, A-301, the vendors sheet, the rate card.
- [ ] Check every figure said against the screen (Drawing check's questions; the material plan's 6 of 34 lines and
      its cement and blocks; the 9 pm report time).

## Episode 3, "A day on site": recorded 20 Nov

- [x] Screens (Today, Stock, Green Villa's day-2 report), light, an owner's copy on day 2 (Mon 16 Nov).
- [x] Every chat, real, as Ravi on day 2 (and the rain on day 10), first take, after the fixes below; the photo
      dropped (Ilan). The Malayalam voice note as written (Ilan: "it's fine as it is").
- [x] `office`: Anil types Ravi's phoned-in line into New (the website has no attendance form of its own). It needed
      WA-316 (5): as a project manager the assistant put names in `worker_id` and Save was refused.
- [x] Built: `node docs/learning/film/build.mjs 03` → `out/episode-03.mp4` (about 7 minutes).

## Then, for each episode

1. `node docs/learning/film/shoot.cjs NN <sample token>` (and the new captures and steps).
2. `STILLS=beats node docs/learning/film/build.mjs NN`: look at every picture; fix layout before drawing the film.
3. `node docs/learning/film/build.mjs NN` (about 30 to 40 minutes; only changed scenes are drawn again).
4. Watch the frames at a few points, check the sound, send the `.mp4` and `.srt`, and update the tracker row
   (LRN-F11, LRN-F13) and LEARNING_PATH.md's table.
