# Recording an episode: the brief

> Written 20 Nov 2026 so another session can record episodes 2 and 3 (and later ones) without this conversation.
> The scripts are agreed to teach **the software**: every entry is shown being made for real, on WhatsApp (through
> Tell Mesiri, the same assistant) or on the website, never drawn. Read [README.md](README.md) for the tools and
> [../LEARNING_PATH.md](../LEARNING_PATH.md) for where each episode sits.

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

## What the tools still need (build these first, LRN-F15)

| Need | Where | What |
|---|---|---|
| Real replies in chat scenes | `shoot.cjs` | For a scene with `capture`: in the sample company as that role, on that day, open Tell Mesiri (`[data-guide="app.tell"]`), send `capture.send`, wait for the card, take the reply's text and card (title, rows, buttons) and write them into `.cache/shots/<scene id>.chat.json`; `build.mjs` uses them in place of the script's `messages`. Tap `capture.tap` (Save, or Cancel) after the picture. A photo: attach the picture named. |
| Step-by-step website scenes | `film.html`, `shoot.cjs`, `build.mjs` | A new kind `steps`: `frames`, each a picture taken after its action (`url` to open, `do` to perform, `show` what it must show, `mark` what to light), shown in turn on its beat (`at`), the box on `mark`. Simplest: shoot each frame as a page picture with its marks (as `screen` does), and draw `steps` as a `screen` whose picture changes on each frame's beat. The `do` lines are plain words: turn them into Playwright actions in a small per-episode file (`steps-NN.cjs`) rather than guessing selectors in the JSON. |
| The role and the day | `shoot.cjs` | Open the sample company as the role a scene names (`POST /learn/sandbox` with that role) and play it to the scene's day ("Next day" through `POST /learn/sandbox/next-day`) before shooting. |

## Episode 2, "Setting up": before recording

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

## Episode 3, "A day on site": before recording

- [ ] The sample company played to **day 2** (a Monday) as the owner; the chats sent as **Ravi** (site engineer) on
      day 2, and the rain chat on **day 10**.
- [ ] Ravi's evening line is sent as the Malayalam words in the script (as Mesiri hears his voice note): **have a
      Malayalam speaker check them** first.
- [ ] The photo: any clear photo of tied plinth beam steel the team may use (none in the kit; add one to the kit if
      it is kept).
- [ ] The website scene (`office`) on a copy where Ravi's morning attendance was not saved (Cancel it), so the
      website makes the record.
- [ ] The daily report: the PDF of day 2 shot as a paper (add it to `shoot.cjs` as a paper from a downloaded file).
- [ ] The labour contractor is "Rahim" on screen; if LRN-F14 renames him, change the narration.

## Then, for each episode

1. `node docs/learning/film/shoot.cjs NN <sample token>` (and the new captures and steps).
2. `STILLS=beats node docs/learning/film/build.mjs NN`: look at every picture; fix layout before drawing the film.
3. `node docs/learning/film/build.mjs NN` (about 30 to 40 minutes; only changed scenes are drawn again).
4. Watch the frames at a few points, check the sound, send the `.mp4` and `.srt`, and update the tracker row
   (LRN-F11, LRN-F13) and LEARNING_PATH.md's table.
