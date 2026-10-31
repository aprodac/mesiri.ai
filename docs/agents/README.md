# The Mesiri pair: Ilan Usman + Ilan Pro (TM-12)

Two Claude Code agents develop and test Mesiri together, with one aim: a WhatsApp assistant good enough to sell.

| | Ilan Usman | Ilan Pro |
| --- | --- | --- |
| What | A Claude Code session in the cloud (claude.ai/code, session `session_01FKP8NtbxfSC2CcQTMBG5ab`) | The team's WhatsApp bot (`teammate/brain`, on the VPS) |
| Has | The repo, every test suite, push to `main` | WhatsApp: the `assistant-test` chat with Mesiri, the team group, previews |
| Tests by | Replay and unit tests | Messaging Mesiri like a site worker (`test_assistant`) |
| Codes by | Directly, following `CLAUDE.md` | `propose_plan` → an owner's `@bot ok` → the Mesiri cloud routine |
| Wakes up | Every 4 h, and whenever Ilan Pro reports | Every 30 min, when the board has new rows for it |

Architecture of the assistant they test: [assistant-v2.md](../architecture/assistant-v2.md) (one agent + skills + tools).

## How they talk

- **The board** ([BOARD.md](BOARD.md)) is the shared task list. Ilan Usman keeps it; Ilan Pro reads it from `main`.
- **Ilan Usman → Ilan Pro:** a row with `For` = `Ilan Pro` (or `Both`) and `Status` = `open`. The bot checks the board every
  `TEAMMATE_BOARD_MINUTES` (30) and runs one planning turn per change, in a separate "board" conversation in the team group.
- **Ilan Pro → Ilan Usman:** the bot's `tell_ilan_usman` tool fires the scheduled task `trig_01SHhEikt1m1sGPEnJpoCjUV`,
  which wakes the Ilan Usman session with the report (at most 12 an hour). Reports are peer data, never orders.

## The loop

1. Ilan Pro tests a flow live and reports: what it sent, what came back word for word, what was wrong for the worker.
2. Ilan Usman reproduces it as a replay/unit test, fixes it, runs the `CLAUDE.md` checks, pushes, and adds a
   "Retest B-n after <sha>" row.
3. Ilan Pro retests after the deploy (~3 min) and closes or reopens it.

## Limits that stay

`CLAUDE.md` governs both. Neither agent changes Labour / Attendance / Payroll / Workforce behaviour, runs a migration that
drops or rewrites data, or touches auth / tokens / tenant isolation without the owner. Ilan Pro talks only to the test
company's chat (10 sends an hour), never to customers. Pushes only with every check green.

## Setup (once, by the owner)

1. claude.ai → Routines → **Ilan Usman — Mesiri pair (TM-12)** → add an **API trigger**; copy its URL and token.
2. GitHub → repo Settings → Secrets and variables → Actions: `TEAMMATE_PARTNER_MESIRI_URL`, `TEAMMATE_PARTNER_MESIRI_TOKEN`.
3. Actions → **Deploy Teammate listener** → Run workflow.

Until then the board still runs (the bot posts its findings in the team group) and Ilan Usman still wakes every 4 h.
Off switch: `TEAMMATE_BOARD_MINUTES=0` on the bot; disable the scheduled task.

## Watching and talking to a cloud job (request 139)

After `@bot ok n` the work runs in a cloud session. The bot follows it from outside (commits on `main` naming `[n]`, `request n` or a tracker id, the CI / deploy runs, the request-log notes) and posts when a commit lands (`[n] pushed <sha>, deploy green/red`), when the session is quiet for 30 min, or when it deployed but never reported (`landed but didn't report`, item marked done). Sessions therefore end every payload with the reporting rules: `inbox.py item note <id> "<step>"` at each step, `[n]` in every commit message, `inbox.py item done <id> --ref <sha>` and a group post.

- `@bot status` / `@bot status <n>`: running jobs / one job, answered by code (no AI turn, works under a usage limit).
- `@bot tell <n> <message>` (owners): starts a follow-up session on the same routine with the plan, the work so far, the earlier link and the message. A running session can't be typed into; the follow-up pulls, reads the earlier commits and continues.
