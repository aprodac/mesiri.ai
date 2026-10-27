# Live scenario suite (WA-80)

**Rule (Ilan, 27 Oct 2026):** a WhatsApp fix counts as done only when its scenarios pass against the
**real** assistant (real model, real database, real WhatsApp) in **3 runs out of 3**. Tests with a scripted
model are still written, but they are not the gate: every fix of 27 Oct passed them and still failed live.

| Piece | Where |
|---|---|
| The catalogue: 58 marks (every ❌ / ⚠️ of the 27 Oct rounds) and 11 scenarios that check them | [`apps/whatsapp-assistant/tests/live/scenarios_27oct.json`](../../apps/whatsapp-assistant/tests/live/scenarios_27oct.json) |
| The runner (standard library, same API as `inbox.py test`) | [`teammate/scenarios.py`](../../teammate/scenarios.py) |
| Run it from a Claude Code session | GitHub Actions → **Claude ops** → task `bot-scenarios`, `text` = `S02,S04 x3` (empty = all, once) |
| Offline test of the catalogue and the runner (CI) | `apps/whatsapp-assistant/tests/unit/test_live_scenarios_catalogue.py` |
| The rounds the marks come from | [`runs/2026-10-27-whatsapp-live-tests/`](runs/2026-10-27-whatsapp-live-tests/README.md) |

## How a scenario works

- It runs in the `assistant-test` chat (TEST company only). Before each scenario the runner sends "cancel", so
  a leftover card cannot leak into it.
- **The TEST company is on a free trial**, capped at 200 WhatsApp messages or ₹50 of AI a day (India time,
  `trial_guardrails`). One full run is roughly 90 messages in and as many out, so three runs do not fit in one
  day while it is a trial. When the assistant answers with the trial limit the runner stops; marks not reached
  are `n/a`, never passed. Baseline: [`runs/2026-10-27-scenario-baseline.md`](runs/2026-10-27-scenario-baseline.md).
- Steps are a message (`send`) or a tap on a button of the last reply (`tap`, by title). `tap_if` taps only when
  the button is offered (e.g. "Replace" when the day already has a count). A missing `tap` blocks the rest of
  the scenario, and its checks fail.
- Scenarios make their own preconditions (save a count first) and undo what they saved, so they run on any day.
- Checks read what the code draws (card lines, buttons, repeated lines, reply time) rather than the model's
  wording. The language checks are the exception: they look for words of the sender's language.
- A mark **passes** only when every check of it passed in every run. `n/a` means a condition was not met
  (e.g. the site question was not asked, so the "dropped card" path could not be reached).

## Adding a mark

Add it to `marks` with the screenshot or message it comes from, then add a check for it in a scenario.
`scenarios.py --check` (and CI) fails while a mark has no check.
