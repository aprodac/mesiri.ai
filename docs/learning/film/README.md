# Mesiri, the course: films

Short episodes (about 8 minutes each) for the team, so a beginner understands the business and the product before
pitching it. Asked 19 Nov 2026: "a big movie ... so that a beginner like us can in depth understand and learn before
going to any pitch". Agreed: a series of short episodes, not one long film, so each can be redone on its own as the
product changes.

| # | Episode | Source | Status |
|---|---|---|---|
| 1 | How a construction company works | Field Guide 00 (`../src/00-big-picture.html`) | built 19 Nov, watched by Ilan ("understood many things"; asked where the software is: from episode 2) |
| 2 | What owners want, and why they buy | Field Guide 00a (roles), and the real screens: Today, Home, Cost control, Live | built 20 Nov, to be reviewed |
| 3 | One day at Green Villa (site → WhatsApp → report → Live) | the product, the sample company | to do |
| 4 | Material, from request to payment | Field Guide 03, the product | to do |
| 5 | The BOQ, and "is it making money?" | the product | to do |
| 6 | Putting it together for a pitch | needs the team's pitch, pricing and objections | to do |

**Check before using with customers:** the business facts come from the field guides, which are drafts: typical
figures, to be checked by someone who has run sites.

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
STILLS=beats node docs/learning/film/build.mjs 02  # a picture at the end of every beat (each zoom, each highlight)
ONLY=cement node docs/learning/film/build.mjs 01  # one scene as a video
```

## Screens (episode 2 on)

A scene of kind `screen` films a real dashboard page (`shot`, `url`, `wait`): the camera moves to each `focus` region
on its beat and `boxes` light up the part being talked about (regions as fractions of the page, 0 to 1). The pictures
come from a **local copy with the demo company, never production**:

1. A local Postgres and Redis, migrated (`alembic -c backend/alembic.ini upgrade head`), and the app as production runs
   it (`uvicorn main:app` in `apps/whatsapp-assistant/src`, PYTHONPATH as in the root CLAUDE.md) with dummy
   `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_APP_SECRET` and `WHATSAPP_ACCESS_TOKEN`, so it can send nothing real.
2. `python3 scripts/training-video/cost/seed.py mesiri`: the demo company (Green Villa, Lake View Apartments, two weeks
   of site records, a BOQ, cost); it writes `admin.token`.
3. The dashboard built and served on :5199 (`npx vite preview --port 5199`), pointing at the local API.
4. `node docs/learning/film/shoot.cjs 02 "$(cat scripts/training-video/cost/admin.token)"` → `.cache/shots/*.png`.

The figures said in the narration are read off these screens: re-shoot, re-check the words, then build.

Needs Playwright's Chromium, ffmpeg, and ElevenLabs (`ELEVENLABS_API_KEY`, or a Claude Code session that has it
connected). `.cache` (narration clips, drawn scenes) and `out` are not committed: an episode is about 8 minutes and
tens of MB, shared as a file.
