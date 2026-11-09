# Mesiri Accounts: sales training video

A ~20 minute video that teaches the sales team Mesiri Accounts and the accounting behind it: Malayalam voice
(Sarvam), English subtitles burned in. Built 9 Nov 2026 for Phase A–C (ACC-01..11, 22, 23).

- `script.py`: the chapters and lines (English subtitle; what is said when it differs; the screen or slide).
- `slides.py`: the teaching slides (double entry, Dr / Cr, groups, P&L, balance sheet, GST, TDS, roles, selling).
- `render.js`: Playwright renders slides and dashboard pages logged in as the accountant (FINANCE role), drawing a
  box around what is being talked about.
- `build.py`: `voice` (Sarvam `mayura:v1` code-mixed Malayalam, keeping accounting words and numbers in English;
  `bulbul:v3`, speaker `kavitha`), `frames`, `video` (ffmpeg: frames, voice, a subtitle band under the picture).
- `sarvam.py`: translate / speak / transcribe. The key is added by the session's network proxy (environment
  "mesiri.ai"); nothing secret is in these files.

Needs: the local API on :8000 and dashboard on :5173 with the demo company, `finance.token` and `admin.token` beside
the scripts (not committed), ffmpeg with libass. Outputs (not committed, large): the mp4, the `.srt`, and the
Malayalam script `mesiri-accounts-training-script.md` (EN + ML per line), kept in `docs/training/`.

When Accounts changes, edit `script.py`, run `voice` (only new lines are spoken) then `frames` and `video`.
