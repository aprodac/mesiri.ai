# Sales training video: from the drawing to the site

A ~6 minute video for the sales team (internal: it shows a real customer's structural set). Plain words for people
with no civil background: how a building job works, the four parts of a building, what goes wrong today, then
Mesiri's Documents, Drawing check, materials from the drawing, the live foundation plan driven by WhatsApp, floors
and rooms, the value for each person, and how to demo. Malayalam voice (Sarvam), English subtitles.

| File | What it is |
|---|---|
| `script.json` | The narration in English, scene by scene, with the part name and the value shown on screen. `ml_overrides`: Malayalam lines corrected by hand (spoken as written) |
| `voice.py` | English → colloquial Malayalam (Sarvam mayura) → speech (bulbul:v3, `priya`), cached per line; writes `timing.json`. `--estimate` builds silent timing when Sarvam is not available |
| `cards.html`, `chat.html` | The explainer cards and the WhatsApp mock-up, revealed at each line's start |
| `setup_demo.py` | A fresh demo company on a **local** Mesiri (never production): project, floors × rooms with work, papers, S-101 rev B |
| `record.js` | Records every scene with Playwright at 1600×900: cards, chat, and the real dashboard driven at each line's start (highlights, part chip, value banner, phone overlay) |
| `build.py` | Cuts each scene to its narration, 1080p, places the voice, burns the English subtitles: `<out>/mesiri-drawings-sales-training.mp4` + `.srt` |

## Make it

Needs a local Mesiri: Postgres + Redis, the API on :8000 with `/media` mounted (local object storage), the dashboard
on :5173 (`npx vite`), and the structural set PDF (the customer's file, not in the repository) at `<out>/../../structure.pdf`.

```bash
OUT=/path/to/out
python tools/sales_video/voice.py $OUT                  # Sarvam credits needed (or --estimate)
python tools/sales_video/setup_demo.py $OUT             # local API running
NODE_PATH=$(npm root -g) node tools/sales_video/record.js $OUT   # all scenes, or name some: ... $OUT live places
python tools/sales_video/build.py $OUT
```

Change a line: edit `script.json`, run `voice.py` (only changed lines are voiced again), record that scene, build.
Check the Malayalam in `$OUT/spoken.json`; correct a line in `ml_overrides`.
