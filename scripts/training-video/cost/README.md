# Mesiri Cost control: sales video

A ~4½ minute video for salespeople: what Cost control answers ("4 masons + 2 helpers = ₹6,400: was ₹6,400 of work
done?") and how each page shows it. Malayalam voice (Sarvam `bulbul:v3`, speaker `kavitha`, as the Accounts video),
English subtitles drawn into the frames. Built 9 Nov 2026 for the module as it stood then (CC-01..CC-21, MP-01, D-CC4).

- `seed.py`: the demo company, through `create_company` and the API: the Demo reset's two weeks of site records
  (`apps/whatsapp-assistant/src/admin/demo.py`), then a BOQ per project, material norms, work and labour put on
  BOQ lines, and cost centres. Rates and norms are scaled for a believable story (see the comments); the figures the
  voice quotes come from this data.
- `script.py`: the lines: English subtitle, Malayalam voice text (numbers in words), the shot.
- `build.py`: `voice` (Sarvam, cached per line), `frames` (cards in the Accounts video's style, dashboard shots in the
  installed Chrome with highlight boxes and close-ups, one 1920x1080 frame per line with its subtitle), `video`
  (ffmpeg; also writes the `.en.srt` and the script with EN + ML).

## Rebuild

```bash
# a database of its own, migrated, with the local API (:8000) and dashboard (:5173) pointed at it, then:
python3 seed.py mesiri_demo_video                      # with PYTHONPATH: backend/src, shared/contracts/src,
                                                       # platform/ai/src, apps/whatsapp-assistant/src
SARVAM_API_KEY=... ../../../.venv/bin/python build.py voice
../../../.venv/bin/python build.py frames
../../../.venv/bin/python build.py video
```

Use the repo's `.venv` Python (it has Playwright and trusted certificates). Needs ffmpeg and Google Chrome. The local
backend app reads its database through `PostgresSettings()` in two places (identity, the container's stand-in when
object storage is fake), so the run used for this video pointed both at the demo database with a small wrapper.

Not committed (`.gitignore`): the tokens `seed.py` writes, `build/`, the mp4. When Cost control changes, re-seed,
re-check the figures quoted in `script.py`, then run the three steps (only changed lines are spoken again).
