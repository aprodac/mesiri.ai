# Mesiri, the course: films

Short episodes (about 8 minutes each) for the team, so a beginner understands the business and the product before
pitching it. Asked 19 Nov 2026: "a big movie ... so that a beginner like us can in depth understand and learn before
going to any pitch". Agreed: a series of short episodes, not one long film, so each can be redone on its own as the
product changes.

**The series is now planned in [SERIES_PLAN.md](SERIES_PLAN.md)** (20 Nov 2026): the overall objective, how each
episode is built, each episode's objective, and every page's episode. Nothing new is filmed until it is agreed. The order to learn in
(episode, then the simulation) and what to make next: [../LEARNING_PATH.md](../LEARNING_PATH.md).

Made so far: the Prologue "How a construction company works" (`episode-00.json`, kept as it is, 20 Nov) and the old
Episode 2 "What owners want" (retired: it was about selling; `retired/`). Episode 1 "The job is won" (`episode-01.json`)
is scripted, for review: read it in [scripts/episode-01.md](scripts/episode-01.md) (`python3 script_md.py 01` remakes it
from the JSON). English narration first (agreed 20 Nov).

**Check before using with customers:** the business facts come from the field guides, which are drafts: typical
figures, to be checked by someone who has run sites.

## The A-to-Z map (the storyboard)

`az-map/index.html` shows the sample company's whole planned project (62 days, 1,477 entries, from
`backend/.../learn/sample_plan.py`): the six phases, who does what, the days as swimlanes, and any chain of handoffs
(request → order → delivery → bill → payment). The film's episodes follow its chains. Rebuild its data when the plan
changes: `PYTHONPATH=backend/src:shared/contracts/src:platform/ai/src python3 docs/learning/film/az_map.py`.

## How an episode is made

- `episode-NN.json`: the script. Each scene has a `kind` (how it is drawn), its words as `beats` (one sentence or two
  each, said by the narrator) and what appears on screen, each part with `at`: the beat it appears on.
- `film.html`: draws every kind of scene at 1920×1080 in Mesiri's look (Unbounded, IBM Plex Sans, Geist Mono, the
  yellow and the hazard stripe), with subtitles.
- `build.mjs`: the narration (ElevenLabs, voice George, as in the simulation's scenes), then each scene drawn frame by
  frame (24 fps) in time with its beats, then the sound mixed (the simulation's whoosh and music) into
  `out/episode-NN.mp4` and `out/episode-NN.srt`.

```bash
node docs/learning/film/build.mjs 01            # the whole episode (only changed scenes are drawn again)
STILLS=1 node docs/learning/film/build.mjs 01   # each scene's last frame in out/stills, to check the layout
STILLS=beats node docs/learning/film/build.mjs 01  # a picture at the end of every beat (each zoom, each highlight)
ONLY=boq node docs/learning/film/build.mjs 01  # one scene as a video
```

## Screens and papers

A scene of kind `screen` shows a picture: the camera moves to each `focus` region on its beat and `boxes` light up the
part being talked about. Name the part by a **mark** (`{ "at": 1, "mark": "margin" }`, with `pad` round it):
`shoot.cjs` records where each mark sits on the picture (`.cache/shots/<shot>.json`) and `build.mjs` places the camera
and the box from it, so nothing is placed by hand (regions as fractions, 0 to 1, still work). Three kinds of picture:

- **A Mesiri page** (`url`, `wait`, `scroll`, `marks`: name → selector). `{Green Villa}` in the url is that project's
  id for the token used. From a **local copy, never production**.
- **A paper from the starter kit** (`paper`: the PDF in `apps/dashboard/public/learn/kit`, its page, `marks`: name →
  words on it; `"line: Retention"` takes the whole line). Episode 1's drawing A-101 and contract summary.
- **A sheet from the kit** (`sheet`: the workbook, its sheet, how many rows, `marks`: name → an item number), drawn as
  a spreadsheet. Episode 1's estimate.

To shoot episode 1 (the sample company after the guided project's chapters 2 and 3):

1. A local Postgres and Redis, migrated (`alembic -c backend/alembic.ini upgrade head`), and the app as production runs
   it (`uvicorn main:app` in `apps/whatsapp-assistant/src`, PYTHONPATH as in the root CLAUDE.md) with dummy
   `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_APP_SECRET` and `WHATSAPP_ACCESS_TOKEN`, so it can send nothing real.
2. The dashboard built and served (`npx vite build && npx vite preview --port 5173` in `apps/dashboard`).
3. A login on that copy; play the guided project to the end of the BOQ chapter:
   `node scripts/learn_kit/e2e/play_journey.cjs <file with {"token": ...}> <out dir> guided`.
4. The sample company's own token: `POST /learn/sandbox` with `{"role": "ADMIN"}` and that login's token; its `token`.
5. `node docs/learning/film/shoot.cjs 01 <sample token>` → `.cache/shots/*.png` and `*.json` (`ONLY=<shot>` for one).

The old episode 2 (retired) shot the demo company instead (`scripts/training-video/cost/seed.py`, `admin.token`).

The figures said in the narration are read off these screens: re-shoot, re-check the words, then build.

Needs Playwright's Chromium, ffmpeg, and ElevenLabs (`ELEVENLABS_API_KEY`, or a Claude Code session that has it
connected). `.cache` (narration clips, drawn scenes) and `out` are not committed: an episode is 6 to 10 minutes and
tens of MB, shared as a file.
