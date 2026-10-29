# Teammate brain — Claude Code behind the WhatsApp bot (TM-03b)

Approved people tag the bot in a project's team group; the listener (`../listener`) checks who
they are and passes the message here. The brain runs **one ongoing Claude Code session per group**
(Agent SDK) in that project's repo, and the answer is posted back to the team group.

```
@bot … ──► listener (approved?) ──► brain: Claude Code session for that group ──► reply in the team group
```

## Two kinds of turn, enforced in code (`src/brain.js`)

| Turn | When | Claude can |
| --- | --- | --- |
| **Planning** | every message | read code, git history, the inbox and request log; post **previews** (an HTML mockup rendered to an image, or a screenshot of an allowed dev page); record a plan. Nothing in the repo can change. |
| **Working** | only after an approved person replies `@bot ok <plan number>` in the team group | edit and run a fixed list of commands (git, gh pr, npm, python, tests…), following the project's git flow; post progress and screenshots of the result |

`permissionMode: "dontAsk"`: anything not on the list is refused, never asked. Always denied:
force pushes, `--no-verify`, `git config` / `-c` / `remote`, reading `.env` files, printing the
environment, `gh auth/secret/api`, editing `.git/`. A read-only pre-push hook (`hooks/pre-push`)
lets each repo push only to its own branch (Mercon `ilan`, Mesiri `main`). Caps: turns per day,
dollars per turn. Refusals during a working turn are posted as **🔐 Needs your permission**, and
Claude flags anything else that needs the owner (**👀 Please check Claude Code**, a decision, a
credential) with its `needs_attention` tool.

**Hybrid:** when a project has a cloud routine (`TEAMMATE_ROUTINE_<PROJECT>_URL` / `_TOKEN`), an approved
plan isn't worked on here: the brain fires the routine with the plan, and the group gets
"▶️ Working on [n] — watch it live in Claude Code: <session link>". The cloud session (your Teammate
environment, visible in your Claude Code app and on claude.ai) does the work and posts progress back.
Setup: `ROUTINE_PROMPT.md`.

Merging to `main` (production) is never part of the default flow; it happens only when the group
says so. For a hard guarantee, protect `main` on GitHub (required review).

## Group commands

- `@bot <question or request>` — answered by Claude (planning turn); **replying to one of the bot's messages works too, no @ needed**
- **Voice note sent as a reply to the bot** — transcribed (Gemini, ~₹0.10-0.50), echoed as `🗣 Heard: "…"`, then answered like a normal question. Team groups only; never run as a command (approvals need typed `@bot ok <n>`)
- `@bot ok <n>` — approve plan *n* (working turn)
- `@bot new <name>` — start a separate conversation in this group; the others are kept
- `@bot sessions` / `@bot switch <name>` — list / change the current conversation
- `@bot reset` — clear the current conversation
- **Mesiri work** (plan 25): in a group labelled for the `mesiri` project, the bot plans changes anywhere in the
  Mesiri repo except `.github/` and `.env` files, following `CLAUDE.md`. **Only an owner can approve a Mesiri
  plan, from any group: pushing to `main` deploys Mesiri production**, so an approval is a production deploy.
  The cloud routine (`ROUTINE_PROMPT_MESIRI.md`) runs the `CLAUDE.md` checks before every push and stops with
  "👀 Please check Claude Code" when a check can't run.
- `@bot upgrade: <what to change in the bot>` (owners) — plans the change in the bot's own repo (`aprodac/mesiri.ai`, `teammate/`) in a separate "upgrade" conversation; `@bot ok <n>` from an **owner** starts the **Teammate upgrade — Mesiri bot** cloud routine, which edits `teammate/` only, runs the bot's tests, pushes to `main`, and the push redeploys the bot automatically (`ROUTINE_PROMPT_MESIRI.md`). If an upgrade breaks the bot, fix it from a Claude Code session on the PC.
- **Direct messages** — an approved person can talk to the bot 1-on-1 (no @); each chat is its own ongoing session and everything goes back to that chat. `ok <n>` works there for the sender's project; `approve`, `remove`, `make owner`, `upgrade` and changing the model stay in the team group.
- `test_assistant` (tool; usable in planning turns) — sends text, an image or a voice note (`audio_path`, .ogg/.mp3/.m4a under /tmp, 5 MB) to the project's `assistant-test` chat, waits up to ~90 s for the Mesiri assistant's replies and returns them with each reply's time after the send ack (+12.4 s, first/last); menus and buttons come back as numbered options, and `choose` (number or exact title) taps one of the latest menu instead of typing; the bot then draws the conversation with `preview_html` and posts it to the team group. If there is no test chat it flags `needs_attention` (link the number, label the chat, register the bot's number as a worker in a TEST company).
- **The Mesiri pair (TM-12):** the bot is *Ilan Pro*; *Ilan Usman* is a Claude Code cloud session. Every `TEAMMATE_BOARD_MINUTES` (30) the bot reads `docs/agents/BOARD.md` and, when rows open for it change, runs a planning turn on them in a "board" conversation in the team group; `tell_ilan_usman` reports back by firing the routine in `TEAMMATE_PARTNER_<PROJECT>_URL` / `_TOKEN`. See `docs/agents/README.md`.
- **Several Claude accounts (TM-14)** — the one bot number can run on any number of Claude accounts, **A, B, C, …**, chosen **per WhatsApp group**: each group runs on the account an owner picked for it, else the default (the planning turns' login, the cloud routine its approved work fires, the partner routine). `@bot account` shows them (default, this group's, missing login or routine, limited until when). Owners, in a team group: `@bot account <letter>` (this group only; also `switch account to b`), `@bot account default <letter>` (every group that hasn't picked one; also `@bot account b everywhere`), `@bot account reset` (this group follows the default again), `@bot account auto off|on` (on by default). **Automatic switching:** when a group's account hits its usage limit, the bot posts `🔁 Claude account A hit its usage limit; this group uses B until it resets (~3:40 pm).`, and runs the same message or plan again on the next free account in letter order (for an approved plan: the next one with a routine for the project), in the same conversation. The limit belongs to the account, so every group on it borrows the same way; when the limit resets each group goes back to its own account by itself. Each account is tried at most once per message, so it never loops; when no account is free it says so with the earliest reset time, and the auto loop pauses until then. A limited account is skipped until its reset time (30 min when none is given); an owner picking it tries it at once. State: `<dir>/accounts.json` (survives restarts).
  - **Adding an account:** on a PC logged into the new account, `claude setup-token`; on claude.ai as that account, a cloud environment with `TEAMMATE_TOKEN`, `api.whatsapp.mesiri.ai` allowed and GitHub access to the repos, and in it the project routine(s) from `ROUTINE_PROMPT*.md` with an API trigger. Then add lines to the one GitHub secret **`TEAMMATE_CLAUDE_ACCOUNTS`** (one `KEY=value` per line; account A is the plain secrets, every other account uses the same names with its letter added) and re-run *Deploy Teammate listener*:
    ```
    CLAUDE_CODE_OAUTH_TOKEN_B=sk-ant-oat01-…
    TEAMMATE_ROUTINE_MESIRI_URL_B=https://api.anthropic.com/v1/claude_code/routines/trig_…/fire
    TEAMMATE_ROUTINE_MESIRI_TOKEN_B=sk-ant-…
    TEAMMATE_PARTNER_MESIRI_URL_B=…        (optional, the Ilan Usman routine on that account)
    TEAMMATE_PARTNER_MESIRI_TOKEN_B=…
    CLAUDE_CODE_OAUTH_TOKEN_C=…            (and so on for C, D, …)
    ```
    The deploy accepts only those variable names (anything else is skipped and reported by line number, never printed). An account exists once its `CLAUDE_CODE_OAUTH_TOKEN_<X>` does; without routines it can still answer, and approved work then goes to an account that has one. Removing an account: delete its lines and redeploy (if it was active, the bot goes back to A). Only the active account's login is ever in Claude's environment; the others and every routine token are kept out.
- `@bot settings` — the project's Claude model and effort; owners change them with `@bot model opus|sonnet|haiku|fable` (or a full `claude-…` id) and `@bot effort low|medium|high|xhigh|max|default`. Applies to the server brain; the cloud routine keeps the model set in the routine.

- **Auto loop (request 61, `src/auto.js`):** `@bot auto on [hours]` (owners, team group; 12 h default, 24 h max) makes the bot work in small cycles by itself: a planning turn tests the assistant with `test_assistant`, picks **one** issue in *Conversation* or *Getting things out* and calls `propose_plan` with `auto.area`; **code, not the model, approves it** (area in scope, no guard word such as labour / attendance / payroll / workforce / migration / auth / token / permission / tenant / security / `.github` / `.env` / `teammate/` / shared component, under `TEAMMATE_AUTO_PUSHES_PER_DAY` (6), one plan at a time) and fires the cloud routine with `Approved by: auto`. When a commit naming the request is on `main` (or its log item is `done`) it waits `TEAMMATE_AUTO_VERIFY_DELAY_MIN` (5) for the deploy, then a verify turn re-tests and reports fixed / not fixed. Plans that fail the checks are posted for a human `@bot ok`. `@bot auto` shows the state; `@bot auto off` / `@bot stop` (anyone approved) stops it. It stops by itself on expiry, 2 failed cycles in a row, the spending cap or a permission denial. A Claude usage limit only **pauses** it (one message, resumes at the reset time, else every 30 min); a run stopped mid-work is re-fired once. Caps: `TEAMMATE_AUTO_CYCLES_PER_DAY` (16), `TEAMMATE_AUTO_GAP_MIN` (15), `TEAMMATE_AUTO_QUIET_GAP_MIN` (60), `TEAMMATE_AUTO_WORK_TIMEOUT_MIN` (120), `TEAMMATE_AUTO_PLAN_USD` (planning budget, default the normal one). Auto turns don't use the daily turn cap. State: `<dir>/auto.json` (survives restarts). Needs the project's cloud routine.

A reply always continues the conversation that wrote the message you reply to, so several topics can
run side by side in one group.
- `@bot who` / `approve @x` / `remove @x` / `make owner @x` — handled by the listener

- **Watching cloud jobs (request 139, `src/work_status.js`, `src/watchdog.js`):** after `@bot ok n` the work runs in a Claude Code cloud session and the routine API only returns its link, so the bot reads the job from outside: commits on the project's branch since the start that name `request n`, `[n]` or any tracker id in the plan / the log item's notes (`WA-86`), the CI and *Deploy to Production* runs of those commits (GitHub REST, read-only, the project's own token), the request-log item (status, notes) and the links. Every cloud payload ends with a fixed **reporting footer**: `inbox.py item note <id> "<step>"` at each step (the heartbeats), `[n]` in every commit message, finish with `inbox.py item done <id> --ref <sha>` and a group post. Planning turns may also run `gh run list/view` and `gh api repos/<repo>/commits…` (write flags such as `-X`, `-f`, `--input` are denied; no other endpoint is allowed). The **watchdog** (`TEAMMATE_WATCH_MINUTES`, default 10, 0 = off) checks every `running_in_cloud` plan: a new commit → `[n] pushed <sha>, deploy green/red` (once per commit, when its deploy has a result, or after 30 min); 30 min with no note and no commit → one post with the link (again only after new activity and a new silence); deploy green and 20 min of silence with no note after it → `landed but didn't report`, item marked done with the sha. State: `<dir>/watch.json`.
- **Status and tell (request 139), answered by code with no AI turn (free, work under a usage limit):** `@bot status` lists the running jobs, `@bot status <n>` one job (commits, deploy, last note, links, follow-ups). `@bot tell <n> <message>` (owners): the routine API can't type into a running session, so it starts a **follow-up session** on the same routine and account (switching account on a usage limit like any start). Its payload carries the original plan, the collector's status, the earlier session link and the message, and tells it to pull, read the earlier commits, continue (not restart) and keep the request id, heartbeats and rules. The bot posts `💬 [n] follow-up started: <link>` and records it on the item; `status` shows both sessions. The bot can do the same itself with the `tell_job` tool after a live re-test, but only while the plan is still running, with `scope` quoting a passage of the plan that covers the problem, at most 3 times per plan; otherwise it proposes a new plan. `status_of_work` gives the planning turn the same view as `@bot status`. **Not possible:** reading a session's live chat or typing into the same running session (the API has no read or send for sessions).

## Running it

A systemd service (`../deploy/teammate-brain.service`) as its own user, writing only to
`/var/lib/teammate-brain`, with memory/CPU limits. It needs `CLAUDE_CODE_OAUTH_TOKEN`
(`claude setup-token`), `GH_TOKEN`, and the listener's `TEAMMATE_API_TOKEN`; the listener needs
`TEAMMATE_BRAIN_URL=http://127.0.0.1:8791`. Previews need Chromium in `/opt/pw-browsers`
(`npx playwright-core install --with-deps chromium`).

```bash
cd teammate/brain && npm install && npm test     # fake Claude, no tokens needed
```

## Production watch (TM-16)

Every `TEAMMATE_PROD_WATCH_MINUTES` (30; 0 = off) the brain reads the newest production messages of each project
that has `TEAMMATE_OPS_<PROJECT>_URL` / `_TOKEN` (Mesiri: the read-only `/claude-ops/sql` API, one audited SELECT).
Plain code flags messages: failed or stuck, a reply slower than 15 s, a reply that admits a dead end, the same
question twice, the user resending or pushing back (`src/prod_watch.js`, `flagRows`). Only when something is
flagged, one planning turn runs in the project's team group (a separate "watch" conversation) with those
conversations as data: Claude judges what really went wrong, finds the root cause and its class
(`docs/engineering/FIX_APPROACH.md` in the Mesiri repo), records one plan per root cause and posts a short report;
`@bot ok <n>` builds it. When nothing is real it answers `NOTHING_TO_REPORT` and nothing is posted.

The ops token stays in the brain's own process (filtered out of Claude's environment): Claude sees the flagged
conversations, never the token, and cannot query production itself. Reported messages are remembered
(`prod-watch.json`), so nothing is reported twice; more than 12 flagged conversations wait for the next look.
